"""Especializacao radial do RhythmSpawnerSystem: nasce na borda, toca o nucleo exatamente na batida."""
from __future__ import annotations

import math

import numpy as np

from ouroboros.core.memory.handles import PackedEntityId, unpack_index
from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock
from ouroboros.rhythm.runtime.rhythm_spawner_system import RhythmSpawnerSystem

from hertzbeats.components.schemas import JUDGMENT_PENDING
from hertzbeats.components.texture_ids import TEX_THREAT_BASIC

_TAU = 2.0 * math.pi


class RadialRhythmSpawnerSystem(RhythmSpawnerSystem):
    """
    E o `RhythmSpawnerSystem` da engine (herda cursor monotonico,
    compensacao de latencia e idempotencia inalterados), estendido com a
    materializacao RADIAL de cada ameaca no momento do disparo:

        - O array agendado passado a base class contem TEMPOS DE SPAWN
          (`hit_time - approach_seconds`, com clamp em 0.0), preparado
          na composicao. `hit_times` (parametro deste construtor) guarda
          os tempos de IMPACTO originais do beatmap, paralelos linha a
          linha.
        - No spawn, a ameaca nasce na borda (`spawn_radius` a partir do
          centro), no angulo derivado da `lane` extraida pela IA
          (`angulo = TAU * lane / lane_count`), e recebe uma velocidade
          constante MATEMATICAMENTE calculada para que sua borda toque o
          anel do nucleo exatamente em `target_hit_time_sec`::

              distancia_util = spawn_radius - (core_half + threat_half)
              velocidade     = distancia_util / (hit_time - agora_efetivo)

          Como o tempo restante e medido contra o `IAudioClock` ja
          compensado de latencia, um spawn atrasado por um frame lento
          simplesmente viaja proporcionalmente mais rapido -- o impacto
          continua cravado na batida.

    Zero-GC: toda a inicializacao e feita com escritas escalares
    primitivas nas linhas densas recem-anexadas (mesmo padrao do
    `_create_threat_entity` original); pools e arrays de afinacao por
    tipo de ameaca sao resolvidos UMA unica vez aqui no construtor.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        memory_manager: MemoryManager,
        scheduled_spawns: np.ndarray,
        hit_times: np.ndarray,
        threat_archetype_name: str,
        center_xy: tuple,
        spawn_radius: float,
        core_half_extent: float,
        lane_count: int,
        threat_half_by_type: np.ndarray,
        threat_texture_by_type: np.ndarray,
        threat_collision_layer: int,
        threat_collision_mask: int,
        max_threats_per_frame: int,
        min_travel_seconds: float = 0.05,
    ) -> None:
        """`scheduled_spawns` e o array `SCHEDULED_THREAT_DTYPE` com
        timestamps ja deslocados para tempos de spawn; `hit_times`
        (float64, mesma ordem) preserva os instantes de impacto. Ambos
        sao materializados pelo `BeatmapLoader` + composicao, fora do
        loop. `threat_half_by_type`/`threat_texture_by_type` sao arrays
        indexados por `threat_type` (afinacao data-driven ja resolvida).
        """
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
        self._center_x = float(center_xy[0])
        self._center_y = float(center_xy[1])
        self._spawn_radius = float(spawn_radius)
        self._core_half_extent = float(core_half_extent)
        self._lane_count = int(lane_count)
        self._threat_half_by_type = threat_half_by_type
        self._threat_texture_by_type = threat_texture_by_type
        self._threat_collision_layer = int(threat_collision_layer)
        self._threat_collision_mask = int(threat_collision_mask)
        self._min_travel_seconds = float(min_travel_seconds)

    def _create_threat_entity(self, world: World, row_index: int) -> PackedEntityId:
        """Cria a entidade via base class (que escreve `lane`/
        `threat_type` na pool `rhythm_threat`) e entao materializa os
        componentes radiais: posicao na borda, velocidade em direcao ao
        nucleo, hitbox/sprite por tipo, e os campos ritmicos
        (`target_hit_time_sec`, `spawn_angle_rad`, `packed_handle`)
        consumidos por `JudgmentSystem`/`CoreDamageSystem`.
        """
        packed = super()._create_threat_entity(world, row_index)
        entity_index = unpack_index(packed)

        threat_row = self._threat_pool.dense_row_of(entity_index)
        threat_view = self._threat_pool.active_view()
        threat_type = int(threat_view["threat_type"][threat_row])
        lane = int(threat_view["lane"][threat_row])

        hit_time = float(self._hit_times[row_index])
        time_remaining = hit_time - self._compute_effective_time()
        if time_remaining < self._min_travel_seconds:
            time_remaining = self._min_travel_seconds

        threat_half = float(self._threat_half_by_type[threat_type])
        travel_distance = self._spawn_radius - (self._core_half_extent + threat_half)
        speed = travel_distance / time_remaining

        angle = _TAU * (lane % self._lane_count) / self._lane_count
        direction_x = math.cos(angle)
        direction_y = math.sin(angle)
        spawn_x = self._center_x + direction_x * self._spawn_radius
        spawn_y = self._center_y + direction_y * self._spawn_radius

        strength = float(self._scheduled_threats["strength"][row_index])
        threat_view["strength"][threat_row] = strength
        threat_view["target_hit_time_sec"][threat_row] = hit_time
        threat_view["spawn_angle_rad"][threat_row] = angle
        threat_view["is_hit"][threat_row] = False
        threat_view["judgment"][threat_row] = JUDGMENT_PENDING
        threat_view["packed_handle"][threat_row] = packed

        transform_row = self._transform_pool.dense_row_of(entity_index)
        transform_view = self._transform_pool.active_view()
        transform_view["position_x"][transform_row] = spawn_x
        transform_view["position_y"][transform_row] = spawn_y
        transform_view["rotation_rad"][transform_row] = angle
        scale = threat_half / 8.0
        transform_view["scale_x"][transform_row] = scale
        transform_view["scale_y"][transform_row] = scale

        velocity_row = self._velocity_pool.dense_row_of(entity_index)
        velocity_view = self._velocity_pool.active_view()
        velocity_view["linear_x"][velocity_row] = -direction_x * speed
        velocity_view["linear_y"][velocity_row] = -direction_y * speed
        velocity_view["angular"][velocity_row] = 0.0

        hitbox_row = self._hitbox_pool.dense_row_of(entity_index)
        hitbox_view = self._hitbox_pool.active_view()
        hitbox_view["half_width"][hitbox_row] = threat_half
        hitbox_view["half_height"][hitbox_row] = threat_half
        hitbox_view["collision_layer"][hitbox_row] = self._threat_collision_layer
        hitbox_view["collision_mask"][hitbox_row] = self._threat_collision_mask

        sprite_row = self._sprite_pool.dense_row_of(entity_index)
        sprite_view = self._sprite_pool.active_view()
        if threat_type < self._threat_texture_by_type.shape[0]:
            sprite_view["texture_id"][sprite_row] = self._threat_texture_by_type[threat_type]
        else:
            sprite_view["texture_id"][sprite_row] = TEX_THREAT_BASIC
        sprite_view["tint_r"][sprite_row] = 255
        sprite_view["tint_g"][sprite_row] = 64 + int(120.0 * (1.0 - strength))
        sprite_view["tint_b"][sprite_row] = 80
        sprite_view["tint_a"][sprite_row] = 255
        sprite_view["layer_z"][sprite_row] = 20

        return packed
