"""Pistas Dinamicas: as colunas do Arcade balancam quando um pico de energia (Scratch/pesada) acontece."""
from __future__ import annotations

import math

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock

from hertzbeats.components.schemas import MODE_TAG_LANES

_SWAY_FREQUENCY_HZ = 6.0
"""Frequencia da oscilacao amortecida de balanco -- game feel fixo, nao
afinacao de dificuldade (por isso nao esta no `HertzConfig`)."""


def compute_lane_sway(
    now_effective: float,
    trigger_times: np.ndarray,
    amplitude_px: float,
    decay_per_second: float,
    frequency_hz: float = _SWAY_FREQUENCY_HZ,
) -> float:
    """Soma de senoides amortecidas CAUSAIS (uma por evento em
    `trigger_times`, tipicamente os poucos picos/pesadas da fase): cada
    evento em `t0` contribui `exp(-decay*(now-t0)) * sin(2*pi*freq*(now-t0))`
    para `now >= t0` (zero antes -- e reacao ao impacto, nao antecipacao).
    Pura, sem estado -- testavel sem ECS."""
    trigger_times = np.asarray(trigger_times, dtype=np.float64)
    if trigger_times.shape[0] == 0:
        return 0.0
    elapsed = now_effective - trigger_times
    active = elapsed >= 0.0
    if not np.any(active):
        return 0.0
    envelope = np.where(
        active,
        np.exp(-decay_per_second * np.clip(elapsed, 0.0, None))
        * np.sin(2.0 * math.pi * frequency_hz * elapsed),
        0.0,
    )
    return float(amplitude_px * np.sum(envelope))


class LaneChoreographySystem(ISystem):
    """
    "Pistas Dinamicas": em vez de coordenadas fixas, a posicao X de
    cada coluna do Arcade 4K (e das notas amarradas a ela) e
    `lane_center_xs[k] + sway_offset(k)`, onde `sway_offset` vem de
    `compute_lane_sway` sobre os instantes de pico/scratch da fase --
    colunas pares e impares balancam em direcoes opostas (efeito de
    "cisalhamento" visivel), reagindo aos mesmos momentos que os
    Scratches marcam.

    Zero-GC: um escalar (`compute_lane_sway`) por frame; reescrita
    vetorizada de `position_x` para TODAS as notas ativas do modo (via
    indexacao por `lane` -- fancy indexing, sem laco por nota) mais um
    laco escalar minusculo (4 iteracoes) para os receptores/rotulos fixos
    da linha de julgamento.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        memory_manager: MemoryManager,
        lane_center_xs: np.ndarray,
        trigger_times: np.ndarray,
        amplitude_px: float,
        decay_per_second: float,
        receptor_entity_indices: np.ndarray,
        key_label_entity_indices: np.ndarray,
    ) -> None:
        self._audio_clock = audio_clock
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._transform_pool = memory_manager.get_pool("transform")
        self._lane_center_xs = np.asarray(lane_center_xs, dtype=np.float64)
        self._trigger_times = np.asarray(trigger_times, dtype=np.float64)
        self._amplitude_px = float(amplitude_px)
        self._decay_per_second = float(decay_per_second)
        self._receptor_entity_indices = receptor_entity_indices
        self._key_label_entity_indices = key_label_entity_indices

        lane_count = self._lane_center_xs.shape[0]
        self._sign_by_lane = np.array(
            [1.0 if lane % 2 == 0 else -1.0 for lane in range(lane_count)], dtype=np.float64
        )
        self._owned_mask = np.zeros(self._threat_pool.capacity, dtype=bool)

    def update(self, world: World, delta_time: float) -> None:
        del delta_time

        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )
        sway = compute_lane_sway(
            now_effective, self._trigger_times, self._amplitude_px, self._decay_per_second
        )
        if sway == 0.0:
            offsets_by_lane = np.zeros_like(self._lane_center_xs)
        else:
            offsets_by_lane = self._sign_by_lane * sway
        target_x_by_lane = self._lane_center_xs + offsets_by_lane

        active_count = self._threat_pool.count
        if active_count > 0:
            threat_view = self._threat_pool.active_view()
            owned = self._owned_mask[:active_count]
            np.equal(threat_view["mode_tag"], MODE_TAG_LANES, out=owned)
            owned_rows = np.flatnonzero(owned)
            if owned_rows.shape[0] > 0:
                entity_indices = self._threat_pool.active_entity_indices()[owned_rows]
                transform_rows = self._transform_pool.dense_rows_of(entity_indices)
                lanes = threat_view["lane"][owned_rows]
                self._transform_pool.active_view()["position_x"][transform_rows] = target_x_by_lane[lanes]

        transform_view = self._transform_pool.active_view()
        for lane in range(self._lane_center_xs.shape[0]):
            for entity_index in (
                int(self._receptor_entity_indices[lane]),
                int(self._key_label_entity_indices[lane]),
            ):
                row = self._transform_pool.dense_row_of(entity_index)
                transform_view["position_x"][row] = float(target_x_by_lane[lane])
