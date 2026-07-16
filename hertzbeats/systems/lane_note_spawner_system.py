"""Modo Arcade 4K: notas caem em 4 colunas rumo a linha de julgamento (estilo FNF/VSRG)."""
from __future__ import annotations

import math

import numpy as np

from ouroboros.core.memory.handles import PackedEntityId, unpack_index
from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock
from ouroboros.rhythm.runtime.rhythm_spawner_system import RhythmSpawnerSystem

from hertzbeats.components.schemas import JUDGMENT_PENDING, MODE_TAG_LANES

LANE_COUNT_4K: int = 4
"""Numero fixo de colunas do modo Arcade (D/F/J/K)."""


class LaneNoteSpawnerSystem(RhythmSpawnerSystem):
    """
    Estrategia de spawn do modo Arcade 4K sobre o MESMO `beatmap.json`:
    e o `RhythmSpawnerSystem` da engine materializando cada evento como
    uma NOTA que cai verticalmente e cruza a linha de julgamento
    exatamente em `target_hit_time_sec`.

    Interpretacao espacial dos campos do beatmap:
        - `lane % 4` escolhe a coluna (distribuicao deterministica dos
          dados do JSON -- a IA ja alterna as lanes por indice). O campo
          `lane` da pool e REESCRITO com o valor reduzido (0..3) para o
          `LaneJudgmentSystem` comparar por igualdade vetorizada.
        - `threat_type`/`strength` ditam o tamanho/brilho da nota.

    Cinematica: `velocidade_y = (linha_julgamento - y_spawn) / tempo_restante`
    (mesma compensacao de atraso de frame dos outros modos: spawn tardio
    cai proporcionalmente mais rapido e cruza a linha na batida).
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        memory_manager: MemoryManager,
        scheduled_spawns: np.ndarray,
        hit_times: np.ndarray,
        threat_archetype_name: str,
        lane_center_xs: np.ndarray,
        spawn_y: float,
        judgment_line_y: float,
        note_half_by_type: np.ndarray,
        lane_tints_rgb: np.ndarray,
        max_threats_per_frame: int,
        min_travel_seconds: float = 0.05,
    ) -> None:
        """`lane_center_xs` (float64, len 4) e `lane_tints_rgb`
        (uint8, shape (4,3)) sao pre-computados na composicao."""
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
        self._lane_center_xs = lane_center_xs
        self._spawn_y = float(spawn_y)
        self._judgment_line_y = float(judgment_line_y)
        self._note_half_by_type = note_half_by_type
        self._lane_tints_rgb = lane_tints_rgb
        self._min_travel_seconds = float(min_travel_seconds)

    def _create_threat_entity(self, world: World, row_index: int) -> PackedEntityId:
        """Materializa a nota do evento `row_index` na sua coluna."""
        packed = super()._create_threat_entity(world, row_index)
        entity_index = unpack_index(packed)

        threat_row = self._threat_pool.dense_row_of(entity_index)
        threat_view = self._threat_pool.active_view()
        threat_type = int(threat_view["threat_type"][threat_row])
        lane = int(threat_view["lane"][threat_row]) % LANE_COUNT_4K
        threat_view["lane"][threat_row] = lane  # coluna 0..3 para o julgamento

        hit_time = float(self._hit_times[row_index])
        time_remaining = hit_time - self._compute_effective_time()
        if time_remaining < self._min_travel_seconds:
            time_remaining = self._min_travel_seconds
        fall_speed = (self._judgment_line_y - self._spawn_y) / time_remaining

        strength = float(self._scheduled_threats["strength"][row_index])
        threat_view["mode_tag"][threat_row] = MODE_TAG_LANES
        threat_view["strength"][threat_row] = strength
        threat_view["target_hit_time_sec"][threat_row] = hit_time
        threat_view["expire_time_sec"][threat_row] = hit_time
        threat_view["spawn_angle_rad"][threat_row] = math.pi / 2.0  # caindo (tela, y para baixo)
        threat_view["is_hit"][threat_row] = False
        threat_view["judgment"][threat_row] = JUDGMENT_PENDING
        threat_view["packed_handle"][threat_row] = packed

        note_half = float(self._note_half_by_type[threat_type])
        transform_row = self._transform_pool.dense_row_of(entity_index)
        transform_view = self._transform_pool.active_view()
        transform_view["position_x"][transform_row] = float(self._lane_center_xs[lane])
        transform_view["position_y"][transform_row] = self._spawn_y
        # notas 1.7x maiores que o meio-tamanho logico: legibilidade da
        # queda importa mais que o volume exato (nao ha colisao no 4K)
        transform_view["scale_x"][transform_row] = note_half * 1.7 / 8.0
        transform_view["scale_y"][transform_row] = note_half * 1.7 / 8.0

        velocity_row = self._velocity_pool.dense_row_of(entity_index)
        velocity_view = self._velocity_pool.active_view()
        velocity_view["linear_x"][velocity_row] = 0.0
        velocity_view["linear_y"][velocity_row] = fall_speed
        velocity_view["angular"][velocity_row] = 0.0

        # sem CollisionSystem neste modo: hitbox neutra (layer/mask 0)
        hitbox_row = self._hitbox_pool.dense_row_of(entity_index)
        hitbox_view = self._hitbox_pool.active_view()
        hitbox_view["half_width"][hitbox_row] = note_half
        hitbox_view["half_height"][hitbox_row] = note_half
        hitbox_view["collision_layer"][hitbox_row] = 0
        hitbox_view["collision_mask"][hitbox_row] = 0

        sprite_row = self._sprite_pool.dense_row_of(entity_index)
        sprite_view = self._sprite_pool.active_view()
        sprite_view["texture_id"][sprite_row] = 0  # circulo procedural na cor da coluna
        sprite_view["tint_r"][sprite_row] = self._lane_tints_rgb[lane, 0]
        sprite_view["tint_g"][sprite_row] = self._lane_tints_rgb[lane, 1]
        sprite_view["tint_b"][sprite_row] = self._lane_tints_rgb[lane, 2]
        sprite_view["tint_a"][sprite_row] = 255
        sprite_view["layer_z"][sprite_row] = 20

        return packed
