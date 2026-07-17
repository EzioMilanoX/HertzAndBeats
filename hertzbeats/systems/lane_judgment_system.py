"""Modo Arcade 4K: julga a tecla da coluna (D/F/J/K) contra a janela temporal da nota."""
from __future__ import annotations

from typing import Tuple

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock
from ouroboros.interfaces.input_provider import IInputProvider

from hertzbeats.components.schemas import (
    JUDGMENT_GOOD,
    JUDGMENT_MISS,
    JUDGMENT_PENDING,
    JUDGMENT_PERFECT,
    MODE_TAG_LANES,
)
from hertzbeats.game_state import GameState

DEFAULT_LANE_ACTIONS: Tuple[str, ...] = ("lane_0", "lane_1", "lane_2", "lane_3")
"""Acoes abstratas das 4 colunas (bindings data-driven: D/F/J/K por padrao)."""


class LaneJudgmentSystem(ISystem):
    """
    Julgamento do modo Arcade 4K: para cada coluna cuja tecla foi
    PRESSIONADA neste frame, avalia
    `delta = target_hit_time_sec - agora_efetivo` (relogio de audio
    compensado de latencia -- a MESMA base de tempo do spawner) contra
    as janelas de tolerancia, exigindo que a nota candidata pertenca a
    MESMA coluna (`lane == coluna da tecla`, igualdade vetorizada).

    Entre as candidatas da coluna vence a de menor |delta|; o veredito
    (PERFECT/GOOD) e um inteiro gravado na linha SoA da nota, a
    destruicao e diferida para o flush e o placar e atualizado por
    aritmetica -- nenhum evento/objeto alocado dinamicamente.

    Notas nao pressionadas vencem por varredura de MISS
    (`delta < -miss_window`), zerando o combo -- identico ao modo
    Defensor. Tecla pressionada SEM nota na janela da coluna (ghost tap)
    nao pune: fiel ao estilo VSRG/FNF.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        input_provider: IInputProvider,
        memory_manager: MemoryManager,
        game_state: GameState,
        perfect_window_seconds: float,
        good_window_seconds: float,
        miss_window_seconds: float,
        score_perfect: int,
        score_good: int,
        judgment_display_seconds: float,
        lane_action_names: Tuple[str, ...] = DEFAULT_LANE_ACTIONS,
        audio_engine=None,
        ghost_tap_sound_id: str = None,
    ) -> None:
        """Buffers pre-alocados pela capacidade da pool (o update nunca
        aloca arrays)."""
        self._audio_clock = audio_clock
        self._input_provider = input_provider
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._game_state = game_state
        self._perfect_window = float(perfect_window_seconds)
        self._good_window = float(good_window_seconds)
        self._miss_window = float(miss_window_seconds)
        self._score_perfect = int(score_perfect)
        self._score_good = int(score_good)
        self._judgment_display_seconds = float(judgment_display_seconds)
        self._lane_action_names = tuple(lane_action_names)
        self._audio_engine = audio_engine
        self._ghost_tap_sound_id = ghost_tap_sound_id

        capacity = self._threat_pool.capacity
        self._delta_buffer = np.zeros(capacity, dtype=np.float64)
        self._abs_delta_buffer = np.zeros(capacity, dtype=np.float64)
        self._candidate_mask = np.zeros(capacity, dtype=bool)
        self._scratch_mask = np.zeros(capacity, dtype=bool)
        self._owned_mask = np.zeros(capacity, dtype=bool)
        self._not_hold_mask = np.zeros(capacity, dtype=bool)
        self._selection_buffer = np.zeros(capacity, dtype=np.float64)

    def update(self, world: World, delta_time: float) -> None:
        """Varre MISSes vencidos e julga as teclas de coluna do frame."""
        del delta_time

        active_count = self._threat_pool.count
        if active_count == 0:
            return

        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )
        threat_view = self._threat_pool.active_view()
        deltas = self._delta_buffer[:active_count]
        np.subtract(threat_view["target_hit_time_sec"], now_effective, out=deltas)

        # dono apenas das NOTAS de coluna (coexistencia multi-modo)
        owned = self._owned_mask[:active_count]
        np.equal(threat_view["mode_tag"], MODE_TAG_LANES, out=owned)

        self._sweep_overdue_misses(world, threat_view, deltas, active_count)

        # 4 checagens escalares de acao por frame; mascaras vetorizadas
        # apenas para as colunas efetivamente pressionadas (raro).
        for lane_index in range(len(self._lane_action_names)):
            if self._input_provider.is_action_pressed(self._lane_action_names[lane_index]):
                self._try_lane_hit(world, threat_view, deltas, active_count, lane_index)

    def _sweep_overdue_misses(
        self,
        world: World,
        threat_view: np.ndarray,
        deltas: np.ndarray,
        active_count: int,
    ) -> None:
        """Nota que passou da linha alem da janela de miss sem tecla:
        MISS, combo zerado (uma vez por frame), destruicao diferida."""
        overdue = self._candidate_mask[:active_count]
        np.less(deltas, -self._miss_window, out=overdue)
        pending = self._scratch_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=pending)
        np.logical_and(overdue, pending, out=overdue)
        np.logical_and(overdue, self._owned_mask[:active_count], out=overdue)
        # notas de Scratch sao do `ScratchJudgmentSystem` -- nunca vencem
        # por esta varredura de tempo (elas tem sua PROPRIA janela/regra)
        not_hold = self._not_hold_mask[:active_count]
        np.logical_not(threat_view["is_hold"], out=not_hold)
        np.logical_and(overdue, not_hold, out=overdue)

        overdue_rows = np.flatnonzero(overdue)
        if overdue_rows.shape[0] == 0:
            return
        for row in overdue_rows:
            row_int = int(row)
            threat_view["judgment"][row_int] = JUDGMENT_MISS
            world.destroy_entity(int(threat_view["packed_handle"][row_int]))
        state = self._game_state
        state.miss_count += int(overdue_rows.shape[0])
        state.combo_count = 0
        state.register_judgment_feedback(JUDGMENT_MISS, self._judgment_display_seconds)

    def _try_lane_hit(
        self,
        world: World,
        threat_view: np.ndarray,
        deltas: np.ndarray,
        active_count: int,
        lane_index: int,
    ) -> None:
        """Melhor candidata (menor |delta|) DENTRO da janela Good E da
        coluna `lane_index`; ghost taps nao punem."""
        abs_deltas = self._abs_delta_buffer[:active_count]
        np.abs(deltas, out=abs_deltas)

        candidates = self._candidate_mask[:active_count]
        np.less_equal(abs_deltas, self._good_window, out=candidates)

        pending = self._scratch_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=pending)
        np.logical_and(candidates, pending, out=candidates)
        np.logical_and(candidates, self._owned_mask[:active_count], out=candidates)

        not_hold = self._not_hold_mask[:active_count]
        np.logical_not(threat_view["is_hold"], out=not_hold)
        np.logical_and(candidates, not_hold, out=candidates)

        np.equal(threat_view["lane"], lane_index, out=self._scratch_mask[:active_count])
        np.logical_and(candidates, self._scratch_mask[:active_count], out=candidates)

        if not np.any(candidates):
            # GHOST TAPPING (FNF moderno): batucar livre sem nota na
            # janela NAO pune -- so um tick discreto para manter o balanco
            if self._audio_engine is not None and self._ghost_tap_sound_id is not None:
                self._audio_engine.play_one_shot(self._ghost_tap_sound_id, 0.3)
            return

        selection = self._selection_buffer[:active_count]
        np.copyto(selection, abs_deltas)
        rejected = self._scratch_mask[:active_count]
        np.logical_not(candidates, out=rejected)
        selection[rejected] = np.inf
        best_row = int(np.argmin(selection))

        judgment = (
            JUDGMENT_PERFECT if float(abs_deltas[best_row]) <= self._perfect_window else JUDGMENT_GOOD
        )
        threat_view["is_hit"][best_row] = True
        threat_view["judgment"][best_row] = judgment
        world.destroy_entity(int(threat_view["packed_handle"][best_row]))

        state = self._game_state
        if judgment == JUDGMENT_PERFECT:
            state.score += self._score_perfect
            state.perfect_count += 1
        else:
            state.score += self._score_good
            state.good_count += 1
        state.combo_count += 1
        if state.combo_count > state.max_combo:
            state.max_combo = state.combo_count
        state.register_judgment_feedback(judgment, self._judgment_display_seconds)
