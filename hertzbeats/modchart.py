"""Modcharts: eventos globais do beatmap que alteram a coreografia das colunas do Arcade 4K (ex.: Swap com Lerp)."""
from __future__ import annotations

from typing import Dict, Sequence, Tuple

import numpy as np


def parse_swap_events(raw_events: Sequence[Dict]) -> Tuple[Tuple[float, float, int, int], ...]:
    """Normaliza a lista crua de `stages.json`
    (`{"type": "swap", "time_seconds", "duration_seconds", "lane_a", "lane_b"}`)
    em tuplas `(time_seconds, duration_seconds, lane_a, lane_b)`
    ORDENADAS por tempo -- eventos posteriores sobre o MESMO par
    naturalmente sobrescrevem os anteriores em `compute_swapped_lane_xs`
    (ver docstring la). Eventos de tipo desconhecido sao ignorados
    (schema aberto para futuros tipos de Modchart)."""
    events = []
    for raw in raw_events:
        if raw.get("type") != "swap":
            continue
        events.append(
            (
                float(raw["time_seconds"]),
                float(raw.get("duration_seconds", 1.0)),
                int(raw["lane_a"]),
                int(raw["lane_b"]),
            )
        )
    events.sort(key=lambda event: event[0])
    return tuple(events)


def compute_swapped_lane_xs(
    base_lane_xs: np.ndarray,
    swap_events: Tuple[Tuple[float, float, int, int], ...],
    now_effective: float,
) -> np.ndarray:
    """Posicao X ATUAL de cada coluna, aplicando toda troca ("swap") de
    `swap_events` cujo `time_seconds` ja chegou: interpolacao LINEAR
    (Lerp) entre `base_lane_xs[lane_a]` e `base_lane_xs[lane_b]` ao
    longo de `duration_seconds`, congelada em 1.0 (troca completa) apos
    o fim. Eventos com `time_seconds` ainda futuro nao tem efeito
    algum.

    Multiplos eventos no MESMO par de colunas se sobrepoem
    corretamente CONTANTO que `swap_events` esteja ordenada por tempo
    (`parse_swap_events` ja garante isso): cada evento e aplicado em
    sequencia sobre o resultado do anterior, entao um evento mais
    recente naturalmente prevalece assim que o seu proprio instante
    chega.

    Pura e sem estado -- retorna um array NOVO a cada chamada (o
    chamador decide se persiste o resultado); testavel sem ECS/pygame.
    """
    current = np.array(base_lane_xs, dtype=np.float64, copy=True)
    for time_seconds, duration_seconds, lane_a, lane_b in swap_events:
        if now_effective < time_seconds:
            continue
        progress = (
            1.0 if duration_seconds <= 0.0 else min(1.0, (now_effective - time_seconds) / duration_seconds)
        )
        base_a = float(base_lane_xs[lane_a])
        base_b = float(base_lane_xs[lane_b])
        current[lane_a] = base_a + (base_b - base_a) * progress
        current[lane_b] = base_b + (base_a - base_b) * progress
    return current
