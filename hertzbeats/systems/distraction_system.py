"""Obstrucoes Visuais (jumpscares): manchas que cobrem a tela por um instante, sobre um pool fixo pre-alocado."""
from __future__ import annotations

from typing import Dict, Sequence, Tuple

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock

from hertzbeats.components.texture_ids import TEX_DISTRACTION_SPLAT

DISTRACTION_DTYPE = np.dtype(
    [
        ("expire_time_sec", np.float64),
        ("active", np.bool_),
    ]
)
"""Ciclo de vida de UMA entidade de obstrucao visual (pool de tamanho
fixo, pre-alocada uma unica vez -- mesma disciplina do `SHOCKWAVE_DTYPE`:
nunca criada/destruida, so ligada/desligada em round-robin)."""


def parse_distraction_events(
    raw_events: Sequence[Dict],
) -> Tuple[Tuple[float, float, float, float], ...]:
    """Normaliza a lista crua de `stages.json`
    (`{"type": "distraction", "time_seconds", "duration_seconds",
    "x_fraction", "y_fraction"}`) em tuplas
    `(time_seconds, duration_seconds, x_fraction, y_fraction)` ORDENADAS
    por tempo -- `x_fraction`/`y_fraction` (0..1) posicionam a mancha
    como fracao da janela, independente de resolucao. Eventos de outro
    tipo (swap, reverse_scroll) sao ignorados aqui -- cada feature filtra
    so o que lhe interessa da MESMA lista de `modchart_events`."""
    events = []
    for raw in raw_events:
        if raw.get("type") != "distraction":
            continue
        events.append(
            (
                float(raw["time_seconds"]),
                float(raw.get("duration_seconds", 0.6)),
                float(raw.get("x_fraction", 0.5)),
                float(raw.get("y_fraction", 0.5)),
            )
        )
    events.sort(key=lambda event: event[0])
    return tuple(events)


class DistractionSystem(ISystem):
    """
    "Obstrucoes Visuais": um cursor MONOTONICO (mesmo idioma do
    `RhythmSpawnerSystem` da engine) avanca sobre `distraction_events`
    (ordenados por tempo); ao cruzar o instante de um evento, ativa o
    PROXIMO slot do pool fixo de `distraction_entity_indices`
    (round-robin, nunca cria/destroi entidade -- mesma disciplina Zero-GC
    do `ShockwaveSystem`), posicionando-o em `(x_fraction*width,
    y_fraction*height)` com a textura pre-registrada
    (`TEX_DISTRACTION_SPLAT`) e `layer_z` acima do HUD -- cobre TUDO na
    tela por `duration_sec`. Um coletor de expiracao escalar (5
    iteracoes, no maximo) desliga o slot (`tint_a=0`) quando o tempo
    acaba.

    Zero-GC: nenhuma alocacao por frame -- o cursor e um inteiro
    primitivo, o round-robin e aritmetica de modulo, e o coletor de
    expiracao itera so sobre os poucos slots do pool fixo.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        memory_manager: MemoryManager,
        distraction_events: Tuple[Tuple[float, float, float, float], ...],
        distraction_entity_indices: np.ndarray,
        window_width: float,
        window_height: float,
        layer_z: int = 0,
    ) -> None:
        self._audio_clock = audio_clock
        self._transform_pool = memory_manager.get_pool("transform")
        self._sprite_pool = memory_manager.get_pool("sprite")
        self._distraction_pool = memory_manager.get_pool("distraction")
        self._events = tuple(distraction_events)
        self._entity_indices = distraction_entity_indices
        self._window_width = float(window_width)
        self._window_height = float(window_height)
        self._layer_z = int(layer_z)
        self._next_event_index = 0
        self._next_slot = 0

    def update(self, world: World, delta_time: float) -> None:
        del world, delta_time
        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )

        while (
            self._next_event_index < len(self._events)
            and self._events[self._next_event_index][0] <= now_effective
        ):
            self._trigger_next_slot(self._events[self._next_event_index], now_effective)
            self._next_event_index += 1

        self._sweep_expired(now_effective)

    def _trigger_next_slot(
        self, event: Tuple[float, float, float, float], now_effective: float
    ) -> None:
        _time_seconds, duration_seconds, x_fraction, y_fraction = event
        entity_index = int(self._entity_indices[self._next_slot])
        self._next_slot = (self._next_slot + 1) % self._entity_indices.shape[0]

        distraction_row = self._distraction_pool.dense_row_of(entity_index)
        distraction_view = self._distraction_pool.active_view()
        distraction_view["expire_time_sec"][distraction_row] = now_effective + duration_seconds
        distraction_view["active"][distraction_row] = True

        transform_row = self._transform_pool.dense_row_of(entity_index)
        transform_view = self._transform_pool.active_view()
        transform_view["position_x"][transform_row] = x_fraction * self._window_width
        transform_view["position_y"][transform_row] = y_fraction * self._window_height

        sprite_row = self._sprite_pool.dense_row_of(entity_index)
        sprite_view = self._sprite_pool.active_view()
        sprite_view["texture_id"][sprite_row] = TEX_DISTRACTION_SPLAT
        sprite_view["tint_a"][sprite_row] = 255
        sprite_view["layer_z"][sprite_row] = self._layer_z

    def _sweep_expired(self, now_effective: float) -> None:
        distraction_view = self._distraction_pool.active_view()
        for row in range(self._entity_indices.shape[0]):
            entity_index = int(self._entity_indices[row])
            distraction_row = self._distraction_pool.dense_row_of(entity_index)
            if not bool(distraction_view["active"][distraction_row]):
                continue
            if now_effective >= float(distraction_view["expire_time_sec"][distraction_row]):
                distraction_view["active"][distraction_row] = False
                sprite_row = self._sprite_pool.dense_row_of(entity_index)
                self._sprite_pool.active_view()["tint_a"][sprite_row] = 0
