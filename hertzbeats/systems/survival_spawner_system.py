"""Modo Sobrevivencia: paredes de som varrem a arena e cruzam o CENTRO exatamente na batida."""
from __future__ import annotations

import math

import numpy as np

from ouroboros.core.memory.handles import PackedEntityId, unpack_index
from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock
from ouroboros.rhythm.runtime.rhythm_spawner_system import RhythmSpawnerSystem

from hertzbeats.components.schemas import JUDGMENT_PENDING, MODE_TAG_SURVIVAL

_HALF_PI = math.pi / 2.0


class SurvivalSpawnerSystem(RhythmSpawnerSystem):
    """
    Estrategia de spawn do modo Sobrevivencia sobre o MESMO
    `beatmap.json`: e o `RhythmSpawnerSystem` da engine (cursor
    monotonico + compensacao de latencia intactos) materializando cada
    evento como uma PAREDE DE SOM -- uma barra laser que atravessa a
    arena inteira e cruza o centro exatamente em `target_hit_time_sec`.

    Interpretacao espacial dos campos do beatmap:
        - `lane % 4` escolhe a borda/eixo da varredura:
          0 = horizontal descendo (nasce no topo), 1 = vertical indo a
          direita (nasce a esquerda), 2 = horizontal subindo,
          3 = vertical indo a esquerda.
        - `threat_type` dita a espessura (pesadas sao mais grossas --
          mas sempre atravessaveis com um Dash bem cronometrado).
        - `strength` clareia o tint (picos de energia brilham mais).

    Cinematica (mesma compensacao do modo radial):
        velocidade = (metade_da_arena + espessura + margem) / tempo_restante
        posicao    = centro - direcao * distancia_total
        expire     = batida + tempo_restante  (saiu da arena do outro lado)

    Nao ha botao de ataque: o julgamento e 100% via CollisionSystem
    (`SurvivalDamageSystem`), e o Dash com i-frames e a unica defesa.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        memory_manager: MemoryManager,
        scheduled_spawns: np.ndarray,
        hit_times: np.ndarray,
        threat_archetype_name: str,
        arena_width: float,
        arena_height: float,
        bar_half_by_type: np.ndarray,
        threat_collision_layer: int,
        threat_collision_mask: int,
        max_threats_per_frame: int,
        min_travel_seconds: float = 0.05,
        edge_margin: float = 30.0,
    ) -> None:
        """`bar_half_by_type` e a meia-espessura da barra indexada por
        `threat_type` (data-driven, resolvida na composicao)."""
        super().__init__(
            audio_clock=audio_clock,
            scheduled_threats=scheduled_spawns,
            threat_archetype_name=threat_archetype_name,
            lane_pool_name="rhythm_threat",
            threat_type_pool_name="rhythm_threat",
            max_threats_per_frame=max_threats_per_frame,
        )
        self._transform_pool = memory_manager.get_pool("transform")
        self._velocity_pool = memory_manager.get_pool("velocity")
        self._hitbox_pool = memory_manager.get_pool("hitbox")
        self._sprite_pool = memory_manager.get_pool("sprite")
        self._threat_pool = memory_manager.get_pool("rhythm_threat")

        self._hit_times = hit_times
        self._arena_width = float(arena_width)
        self._arena_height = float(arena_height)
        self._bar_half_by_type = bar_half_by_type
        self._threat_collision_layer = int(threat_collision_layer)
        self._threat_collision_mask = int(threat_collision_mask)
        self._min_travel_seconds = float(min_travel_seconds)
        self._edge_margin = float(edge_margin)

    def _create_threat_entity(self, world: World, row_index: int) -> PackedEntityId:
        """Materializa a parede de som do evento `row_index` (ver
        docstring da classe para a cinematica)."""
        packed = super()._create_threat_entity(world, row_index)
        entity_index = unpack_index(packed)

        threat_row = self._threat_pool.dense_row_of(entity_index)
        threat_view = self._threat_pool.active_view()
        threat_type = int(threat_view["threat_type"][threat_row])
        sweep_kind = int(threat_view["lane"][threat_row]) % 4

        hit_time = float(self._hit_times[row_index])
        time_remaining = hit_time - self._compute_effective_time()
        if time_remaining < self._min_travel_seconds:
            time_remaining = self._min_travel_seconds

        bar_half = float(self._bar_half_by_type[threat_type])
        center_x = self._arena_width / 2.0
        center_y = self._arena_height / 2.0

        horizontal = sweep_kind % 2 == 0  # barra horizontal varre verticalmente
        if horizontal:
            travel = center_y + bar_half + self._edge_margin
            half_width, half_height = self._arena_width / 2.0, bar_half
        else:
            travel = center_x + bar_half + self._edge_margin
            half_width, half_height = bar_half, self._arena_height / 2.0
        speed = travel / time_remaining
        sign = 1.0 if sweep_kind < 2 else -1.0  # 0/1: topo->baixo, esq->dir; 2/3: contrario

        strength = float(self._scheduled_threats["strength"][row_index])
        threat_view["mode_tag"][threat_row] = MODE_TAG_SURVIVAL
        threat_view["strength"][threat_row] = strength
        threat_view["target_hit_time_sec"][threat_row] = hit_time
        threat_view["expire_time_sec"][threat_row] = hit_time + time_remaining
        threat_view["spawn_angle_rad"][threat_row] = _HALF_PI * sign if horizontal else 0.0
        threat_view["is_hit"][threat_row] = False
        threat_view["judgment"][threat_row] = JUDGMENT_PENDING
        threat_view["packed_handle"][threat_row] = packed

        transform_row = self._transform_pool.dense_row_of(entity_index)
        transform_view = self._transform_pool.active_view()
        transform_view["position_x"][transform_row] = center_x if horizontal else center_x - sign * travel
        transform_view["position_y"][transform_row] = center_y - sign * travel if horizontal else center_y
        transform_view["scale_x"][transform_row] = half_width / 8.0
        transform_view["scale_y"][transform_row] = half_height / 8.0

        velocity_row = self._velocity_pool.dense_row_of(entity_index)
        velocity_view = self._velocity_pool.active_view()
        velocity_view["linear_x"][velocity_row] = 0.0 if horizontal else sign * speed
        velocity_view["linear_y"][velocity_row] = sign * speed if horizontal else 0.0
        velocity_view["angular"][velocity_row] = 0.0

        hitbox_row = self._hitbox_pool.dense_row_of(entity_index)
        hitbox_view = self._hitbox_pool.active_view()
        hitbox_view["half_width"][hitbox_row] = half_width
        hitbox_view["half_height"][hitbox_row] = half_height
        hitbox_view["collision_layer"][hitbox_row] = self._threat_collision_layer
        hitbox_view["collision_mask"][hitbox_row] = self._threat_collision_mask

        sprite_row = self._sprite_pool.dense_row_of(entity_index)
        sprite_view = self._sprite_pool.active_view()
        sprite_view["texture_id"][sprite_row] = 0  # procedural: barra pela razao de escala
        sprite_view["tint_r"][sprite_row] = 255
        sprite_view["tint_g"][sprite_row] = 64 + int(160.0 * strength)
        sprite_view["tint_b"][sprite_row] = 220
        sprite_view["tint_a"][sprite_row] = 255
        sprite_view["layer_z"][sprite_row] = 20

        return packed
