"""Sistema de Graze (estilo Touhou): raspar perto de uma parede letal sem tocar rende pontos e Fever."""
from __future__ import annotations

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World

from hertzbeats.components.schemas import JUDGMENT_PENDING, MODE_TAG_SURVIVAL, PHASE_LETHAL
from hertzbeats.game_state import GameState


class GrazeSystem(ISystem):
    """
    Segundo raio de deteccao da Sobrevivencia, PARALELO ao
    `CollisionSystem`/`SurvivalDamageSystem`: uma parede letal que o
    jogador cruza sem TOCAR (fora da hitbox real, mas dentro dela +
    `graze_margin`) concede pontos de Graze e carrega a barra de Fever
    -- incentiva o estilo agressivo de "raspar" nas ameacas.

    Zero-GC: AABB vetorizado sobre TODAS as paredes LETAIS ativas contra
    a posicao do jogador (buffers pre-alocados, `out=` em toda ufunc);
    `has_grazed` (campo da propria linha SoA) evita pontuar a mesma
    parede a cada frame enquanto o jogador permanece na faixa -- so
    conta na TRANSICAO para dentro da banda de graze.

    Fever: `fever_meter` (0..1 no `GameState`) enche por Graze e decai
    com o tempo; cheio, dobra a pontuacao de Graze/sobrevivencia
    (`GameState.in_fever`) ate esvaziar de novo.
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        game_state: GameState,
        player_entity_index: int,
        graze_margin: float,
        fever_gain_per_graze: float,
        fever_decay_per_second: float,
        fever_score_multiplier: float,
        graze_score_per_hit: int = 50,
        audio_engine=None,
        graze_sound_id: str = None,
    ) -> None:
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._transform_pool = memory_manager.get_pool("transform")
        self._hitbox_pool = memory_manager.get_pool("hitbox")
        self._game_state = game_state
        self._player_entity_index = int(player_entity_index)
        self._graze_margin = float(graze_margin)
        self._fever_gain = float(fever_gain_per_graze)
        self._fever_decay = float(fever_decay_per_second)
        self._fever_score_multiplier = float(fever_score_multiplier)
        self._graze_score_per_hit = int(graze_score_per_hit)
        self._audio_engine = audio_engine
        self._graze_sound_id = graze_sound_id

        capacity = self._threat_pool.capacity
        self._dx_buffer = np.zeros(capacity, dtype=np.float64)
        self._dy_buffer = np.zeros(capacity, dtype=np.float64)
        self._lethal_mask = np.zeros(capacity, dtype=bool)
        self._graze_band_mask = np.zeros(capacity, dtype=bool)
        self._hit_band_mask = np.zeros(capacity, dtype=bool)
        self._scratch_mask = np.zeros(capacity, dtype=bool)

    def update(self, world: World, delta_time: float) -> None:
        state = self._game_state
        state.fever_meter = max(0.0, state.fever_meter - self._fever_decay * delta_time)

        active_count = self._threat_pool.count
        if active_count == 0:
            return

        player_row = self._transform_pool.dense_row_of(self._player_entity_index)
        player_view = self._transform_pool.active_view()
        player_x = float(player_view["position_x"][player_row])
        player_y = float(player_view["position_y"][player_row])
        player_hitbox_row = self._hitbox_pool.dense_row_of(self._player_entity_index)
        player_half = float(self._hitbox_pool.active_view()["half_width"][player_hitbox_row])

        threat_view = self._threat_pool.active_view()
        entity_indices = self._threat_pool.active_entity_indices()
        hitbox_rows = self._hitbox_pool.dense_rows_of(entity_indices)
        transform_rows = self._transform_pool.dense_rows_of(entity_indices)
        hitbox_view = self._hitbox_pool.active_view()
        transform_view = self._transform_pool.active_view()

        lethal = self._lethal_mask[:active_count]
        np.equal(threat_view["mode_tag"], MODE_TAG_SURVIVAL, out=lethal)
        np.equal(threat_view["phase"], PHASE_LETHAL, out=self._scratch_mask[:active_count])
        np.logical_and(lethal, self._scratch_mask[:active_count], out=lethal)
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=self._scratch_mask[:active_count])
        np.logical_and(lethal, self._scratch_mask[:active_count], out=lethal)
        np.logical_not(threat_view["has_grazed"], out=self._scratch_mask[:active_count])
        np.logical_and(lethal, self._scratch_mask[:active_count], out=lethal)
        # Safe Zone (`duration_sec>0`, opt-in via `holds_enabled`) e um
        # refugio -- nunca uma parede letal para "raspar" por perto,
        # mesma exclusao aplicada ao coletor generico do
        # `SurvivalDamageSystem`.
        np.less_equal(threat_view["duration_sec"], 0.0, out=self._scratch_mask[:active_count])
        np.logical_and(lethal, self._scratch_mask[:active_count], out=lethal)
        if not np.any(lethal):
            return

        dx = self._dx_buffer[:active_count]
        dy = self._dy_buffer[:active_count]
        np.subtract(player_x, transform_view["position_x"][transform_rows], out=dx)
        np.subtract(player_y, transform_view["position_y"][transform_rows], out=dy)
        np.abs(dx, out=dx)
        np.abs(dy, out=dy)

        half_widths = hitbox_view["half_width"][hitbox_rows]
        half_heights = hitbox_view["half_height"][hitbox_rows]

        hit_band = self._hit_band_mask[:active_count]
        np.less_equal(dx, half_widths + player_half, out=hit_band)
        np.less_equal(dy, half_heights + player_half, out=self._scratch_mask[:active_count])
        np.logical_and(hit_band, self._scratch_mask[:active_count], out=hit_band)

        graze_band = self._graze_band_mask[:active_count]
        np.less_equal(dx, half_widths + player_half + self._graze_margin, out=graze_band)
        np.less_equal(
            dy, half_heights + player_half + self._graze_margin, out=self._scratch_mask[:active_count]
        )
        np.logical_and(graze_band, self._scratch_mask[:active_count], out=graze_band)

        # graze = dentro da banda estendida, FORA da hitbox real, sobre
        # uma parede letal ainda nao raspada
        np.logical_not(hit_band, out=self._scratch_mask[:active_count])
        np.logical_and(graze_band, self._scratch_mask[:active_count], out=graze_band)
        np.logical_and(graze_band, lethal, out=graze_band)

        grazed_rows = np.flatnonzero(graze_band)
        if grazed_rows.shape[0] == 0:
            return

        multiplier = self._fever_score_multiplier if state.in_fever else 1.0
        for row in grazed_rows:
            row_int = int(row)
            threat_view["has_grazed"][row_int] = True
            state.graze_score += int(round(self._graze_score_per_hit * multiplier))
            state.fever_meter = min(1.0, state.fever_meter + self._fever_gain)
        if self._audio_engine is not None and self._graze_sound_id is not None:
            self._audio_engine.play_one_shot(self._graze_sound_id, 0.25)
