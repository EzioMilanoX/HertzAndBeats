"""Modo Sobrevivencia: paredes de som TELEGRAFADAS -- linha-guia 1 aproximacao antes, letal no onset."""
from __future__ import annotations

import math

import numpy as np

from ouroboros.core.memory.handles import PackedEntityId, unpack_index
from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock
from ouroboros.rhythm.runtime.rhythm_spawner_system import RhythmSpawnerSystem

from hertzbeats.components.schemas import JUDGMENT_PENDING, MODE_TAG_SURVIVAL, PHASE_WARNING

_HALF_PI = math.pi / 2.0


class SurvivalSpawnerSystem(RhythmSpawnerSystem):
    """
    Estrategia de spawn do modo Sobrevivencia sobre o MESMO
    `beatmap.json`, com TELEGRAPHING: nada mata ao aparecer.

    Ciclo de vida de cada parede de som:
        1. AVISO (`PHASE_WARNING`), do spawn (hit - approach) ate o hit:
           linha-guia translucida piscando NO LUGAR EXATO onde a parede
           vai cair. A colisao a ignora por construcao: a hitbox nasce
           com layer/mask 0 -- o CollisionSystem nem gera pares.
        2. LETAL (`PHASE_LETHAL`), exatamente no onset (target_hit_time,
           virada feita pelo `WallPhaseSystem` no MESMO relogio do
           julgamento): cor vibrante, solida, hitbox armada.
        3. EXPIRA em `hit + strike_seconds`: destruida pelo coletor do
           `SurvivalDamageSystem` (SURVIVED se nao tocou ninguem).

    Interpretacao espacial dos campos do beatmap (deterministica e
    MUSICAL -- o mesmo som cai sempre no mesmo lugar):
        - `lane % 2` escolhe o eixo (0 = parede horizontal, 1 = vertical);
        - `lane // 2` escolhe a POSICAO (4 faixas por eixo, frac 1/8,
          3/8, 5/8, 7/8 da arena) -- como a lane vem do TIMBRE, a
          "geografia" da fase repete com a musica;
        - `threat_type` dita a espessura (pesadas mais grossas).
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
        strike_seconds: float = 0.30,
    ) -> None:
        """`bar_half_by_type` e a meia-espessura por `threat_type`;
        `strike_seconds` e a janela letal apos o onset. As camadas de
        colisao REAIS ficam guardadas para o `WallPhaseSystem` armar a
        hitbox na virada de fase."""
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
        self._strike_seconds = float(strike_seconds)

    @property
    def collision_layer(self) -> int:
        """Layer real da hitbox, armada pelo `WallPhaseSystem` na virada."""
        return self._threat_collision_layer

    @property
    def collision_mask(self) -> int:
        """Mask real da hitbox, armada pelo `WallPhaseSystem` na virada."""
        return self._threat_collision_mask

    def _create_threat_entity(self, world: World, row_index: int) -> PackedEntityId:
        """Materializa a parede em fase de AVISO no lugar exato do strike."""
        packed = super()._create_threat_entity(world, row_index)
        entity_index = unpack_index(packed)

        threat_row = self._threat_pool.dense_row_of(entity_index)
        threat_view = self._threat_pool.active_view()
        threat_type = int(threat_view["threat_type"][threat_row])
        lane = int(threat_view["lane"][threat_row])

        hit_time = float(self._hit_times[row_index])
        bar_half = float(self._bar_half_by_type[threat_type])
        horizontal = lane % 2 == 0
        if threat_type != 0:
            # PESADA (pico de energia/drop): cai no CENTRO da arena --
            # o anti-camping ritmico; ninguem estaciona impune no meio
            position_fraction = 0.5
        else:
            position_fraction = (lane // 2) % 4 / 4.0 + 0.125  # 1/8, 3/8, 5/8, 7/8

        if horizontal:
            position_x = self._arena_width / 2.0
            position_y = self._arena_height * position_fraction
            half_width, half_height = self._arena_width / 2.0, bar_half
        else:
            position_x = self._arena_width * position_fraction
            position_y = self._arena_height / 2.0
            half_width, half_height = bar_half, self._arena_height / 2.0

        strength = float(self._scheduled_threats["strength"][row_index])
        threat_view["mode_tag"][threat_row] = MODE_TAG_SURVIVAL
        threat_view["phase"][threat_row] = PHASE_WARNING
        threat_view["strength"][threat_row] = strength
        threat_view["target_hit_time_sec"][threat_row] = hit_time
        threat_view["expire_time_sec"][threat_row] = hit_time + self._strike_seconds
        threat_view["spawn_angle_rad"][threat_row] = _HALF_PI if horizontal else 0.0
        threat_view["is_hit"][threat_row] = False
        threat_view["judgment"][threat_row] = JUDGMENT_PENDING
        threat_view["packed_handle"][threat_row] = packed

        transform_row = self._transform_pool.dense_row_of(entity_index)
        transform_view = self._transform_pool.active_view()
        transform_view["position_x"][transform_row] = position_x
        transform_view["position_y"][transform_row] = position_y
        transform_view["scale_x"][transform_row] = half_width / 8.0
        transform_view["scale_y"][transform_row] = half_height / 8.0

        velocity_row = self._velocity_pool.dense_row_of(entity_index)
        velocity_view = self._velocity_pool.active_view()
        velocity_view["linear_x"][velocity_row] = 0.0  # parede ESTATICA: o aviso e o lugar
        velocity_view["linear_y"][velocity_row] = 0.0
        velocity_view["angular"][velocity_row] = 0.0

        # AVISO: o CollisionSystem ignora por construcao (layer/mask 0,
        # nenhum par e gerado); o WallPhaseSystem arma na virada
        hitbox_row = self._hitbox_pool.dense_row_of(entity_index)
        hitbox_view = self._hitbox_pool.active_view()
        hitbox_view["half_width"][hitbox_row] = half_width
        hitbox_view["half_height"][hitbox_row] = half_height
        hitbox_view["collision_layer"][hitbox_row] = 0
        hitbox_view["collision_mask"][hitbox_row] = 0

        sprite_row = self._sprite_pool.dense_row_of(entity_index)
        sprite_view = self._sprite_pool.active_view()
        sprite_view["texture_id"][sprite_row] = 0  # barra procedural
        sprite_view["tint_r"][sprite_row] = 255
        sprite_view["tint_g"][sprite_row] = 64 + int(160.0 * strength)
        sprite_view["tint_b"][sprite_row] = 220
        sprite_view["tint_a"][sprite_row] = 60  # translucida ate o onset
        sprite_view["layer_z"][sprite_row] = 8

        return packed
