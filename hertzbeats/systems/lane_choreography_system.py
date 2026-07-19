"""Pistas Dinamicas: as colunas do Arcade balancam quando um pico de energia (Scratch/pesada) acontece."""
from __future__ import annotations

import math

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock

from hertzbeats.components.schemas import MODE_TAG_LANES
from hertzbeats.modchart import compute_swapped_lane_xs

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
    "Pistas Dinamicas" + Modcharts: em vez de coordenadas fixas, a
    posicao X de cada coluna do Arcade 4K (e das notas amarradas a ela)
    e `swapped_lane_xs[k] + sway_offset(k)`, onde:
        - `sway_offset` vem de `compute_lane_sway` sobre os instantes de
          pico/scratch da fase -- colunas pares e impares balancam em
          direcoes opostas (efeito de "cisalhamento" visivel), reagindo
          aos mesmos momentos que os Scratches marcam;
        - `swapped_lane_xs` vem de `compute_swapped_lane_xs` sobre os
          eventos "swap" do Modchart da fase (`StageDef.modchart_events`)
          -- Lerp suave trocando duas colunas de lugar ao longo de N
          segundos, SEMPRE recalculado a partir de `base_lane_xs`
          (nunca do resultado do frame anterior, para nao acumular
          deriva).

    `current_lane_xs` (buffer MUTAVEL, pre-alocado, escrito todo frame)
    e a MESMA identidade de array passada ao `LaneNoteSpawnerSystem` --
    uma nota nova nasce exatamente onde sua coluna esta VISUALMENTE
    agora (mid-swap inclusive), e notas ja caindo acompanham a curva em
    tempo real porque este sistema reescreve `position_x` de TODAS as
    notas ativas a cada frame, nao so das recem-criadas.

    Zero-GC: um escalar (`compute_lane_sway`) e um array de 4 elementos
    (`compute_swapped_lane_xs`) por frame; reescrita vetorizada de
    `position_x` para TODAS as notas ativas do modo (via indexacao por
    `lane` -- fancy indexing, sem laco por nota) mais um laco escalar
    minusculo (4 iteracoes) para os receptores/rotulos fixos da linha
    de julgamento.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        memory_manager: MemoryManager,
        base_lane_xs: np.ndarray,
        current_lane_xs: np.ndarray,
        trigger_times: np.ndarray,
        amplitude_px: float,
        decay_per_second: float,
        receptor_entity_indices: np.ndarray,
        key_label_entity_indices: np.ndarray,
        swap_events: tuple = (),
    ) -> None:
        """`base_lane_xs`: snapshot IMUTAVEL das 4 posicoes originais
        (referencia para todo calculo de offset, nunca escrito).
        `current_lane_xs`: buffer MUTAVEL compartilhado por IDENTIDADE
        com o `LaneNoteSpawnerSystem` -- este sistema o reescreve por
        inteiro todo frame; o spawner so o LE no momento do spawn."""
        self._audio_clock = audio_clock
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._transform_pool = memory_manager.get_pool("transform")
        self._base_lane_xs = np.array(base_lane_xs, dtype=np.float64, copy=True)
        self._current_lane_xs = current_lane_xs
        self._trigger_times = np.asarray(trigger_times, dtype=np.float64)
        self._amplitude_px = float(amplitude_px)
        self._decay_per_second = float(decay_per_second)
        self._receptor_entity_indices = receptor_entity_indices
        self._key_label_entity_indices = key_label_entity_indices
        self._swap_events = tuple(swap_events)

        lane_count = self._base_lane_xs.shape[0]
        self._sign_by_lane = np.array(
            [1.0 if lane % 2 == 0 else -1.0 for lane in range(lane_count)], dtype=np.float64
        )
        self._owned_mask = np.zeros(self._threat_pool.capacity, dtype=bool)

    @property
    def current_lane_xs(self) -> np.ndarray:
        """Posicao X ATUAL (swap + sway ja aplicados) de cada coluna --
        lida pelo `HertzGameLoop` para manter a decoracao de fundo
        (`renderer.set_playfield`) em sincronia com o Modchart."""
        return self._current_lane_xs

    def update(self, world: World, delta_time: float) -> None:
        del delta_time

        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )
        swapped_lane_xs = (
            compute_swapped_lane_xs(self._base_lane_xs, self._swap_events, now_effective)
            if self._swap_events
            else self._base_lane_xs
        )
        sway = compute_lane_sway(
            now_effective, self._trigger_times, self._amplitude_px, self._decay_per_second
        )
        if sway == 0.0:
            np.copyto(self._current_lane_xs, swapped_lane_xs)
        else:
            np.add(swapped_lane_xs, self._sign_by_lane * sway, out=self._current_lane_xs)
        target_x_by_lane = self._current_lane_xs

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
        for lane in range(self._base_lane_xs.shape[0]):
            for entity_index in (
                int(self._receptor_entity_indices[lane]),
                int(self._key_label_entity_indices[lane]),
            ):
                row = self._transform_pool.dense_row_of(entity_index)
                transform_view["position_x"][row] = float(target_x_by_lane[lane])
