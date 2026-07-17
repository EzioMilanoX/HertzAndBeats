"""Notas de Scratch: exige energia continua de mouse (a 'mesa do DJ') do inicio ao fim do hold."""
from __future__ import annotations

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock
from ouroboros.interfaces.input_provider import IInputProvider

from hertzbeats.components.schemas import (
    JUDGMENT_MISS,
    JUDGMENT_PENDING,
    JUDGMENT_PERFECT,
    MODE_TAG_LANES,
)
from hertzbeats.game_state import GameState


class ScratchJudgmentSystem(ISystem):
    """
    Julga as notas de Scratch (`is_hold=True`, clusters de pesadas
    fundidos por `lane_scratch_clustering`) -- donas exclusivas deste
    juiz, o `LaneJudgmentSystem` as ignora por completo.

    Regra: entre `target_hit_time_sec` (inicio do cluster) e
    `expire_time_sec` (fim + folga), o eixo `scratch_energy` do
    `IInputProvider` (magnitude do movimento do mouse no frame,
    normalizada -- ver `HBPygameInputProvider`) precisa se manter acima
    de `scratch_min_energy` A CADA FRAME. Parar de "raspar" durante o
    hold e MISS imediato (sem esperar o fim); manter o movimento ate o
    fim e um acerto PERFECT.

    Zero-GC: mascara vetorizada sobre a pool inteira para achar o hold
    ativo (tipicamente 0 ou 1 por vez); a decisao de energia e um unico
    escalar por frame, aplicada por indice nas poucas linhas achadas.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        input_provider: IInputProvider,
        memory_manager: MemoryManager,
        game_state: GameState,
        min_energy: float,
        judgment_display_seconds: float,
        score_perfect: int,
        scratch_energy_axis_name: str = "scratch_energy",
    ) -> None:
        self._audio_clock = audio_clock
        self._input_provider = input_provider
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._game_state = game_state
        self._min_energy = float(min_energy)
        self._judgment_display_seconds = float(judgment_display_seconds)
        self._score_perfect = int(score_perfect)
        self._axis_name = scratch_energy_axis_name

        capacity = self._threat_pool.capacity
        self._owned_mask = np.zeros(capacity, dtype=bool)
        self._started_mask = np.zeros(capacity, dtype=bool)
        self._finished_mask = np.zeros(capacity, dtype=bool)

    def update(self, world: World, delta_time: float) -> None:
        del delta_time

        active_count = self._threat_pool.count
        if active_count == 0:
            return

        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )
        threat_view = self._threat_pool.active_view()

        owned = self._owned_mask[:active_count]
        np.equal(threat_view["mode_tag"], MODE_TAG_LANES, out=owned)
        np.logical_and(owned, threat_view["is_hold"], out=owned)
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=self._finished_mask[:active_count])
        np.logical_and(owned, self._finished_mask[:active_count], out=owned)
        if not np.any(owned):
            return

        started = self._started_mask[:active_count]
        np.less_equal(threat_view["target_hit_time_sec"], now_effective, out=started)
        np.logical_and(owned, started, out=started)
        if not np.any(started):
            return  # nenhum hold comecou ainda

        active_rows = np.flatnonzero(started)
        energy = self._input_provider.get_axis(self._axis_name)

        if energy < self._min_energy:
            # parou de raspar durante o hold: MISS imediato, nao espera
            # o fim do cluster
            state = self._game_state
            for row in active_rows:
                row_int = int(row)
                threat_view["judgment"][row_int] = JUDGMENT_MISS
                world.destroy_entity(int(threat_view["packed_handle"][row_int]))
            state.miss_count += int(active_rows.shape[0])
            state.combo_count = 0
            state.register_judgment_feedback(JUDGMENT_MISS, self._judgment_display_seconds)
            return

        finished = self._finished_mask[:active_count]
        np.less_equal(threat_view["expire_time_sec"], now_effective, out=finished)
        np.logical_and(started, finished, out=finished)
        finished_rows = np.flatnonzero(finished)
        if finished_rows.shape[0] == 0:
            return

        state = self._game_state
        for row in finished_rows:
            row_int = int(row)
            threat_view["is_hit"][row_int] = True
            threat_view["judgment"][row_int] = JUDGMENT_PERFECT
            world.destroy_entity(int(threat_view["packed_handle"][row_int]))
            state.score += self._score_perfect
            state.perfect_count += 1
            state.combo_count += 1
            if state.combo_count > state.max_combo:
                state.max_combo = state.combo_count
        state.register_judgment_feedback(JUDGMENT_PERFECT, self._judgment_display_seconds)
