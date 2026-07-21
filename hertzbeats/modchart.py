"""Modcharts: eventos globais do beatmap que alteram a coreografia do Arcade 4K (Swap, Reverse Scroll) ou o Defensor (Colapso do Anel)."""
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


def parse_reverse_scroll_events(raw_events: Sequence[Dict]) -> Tuple[Tuple[float, float, float], ...]:
    """Normaliza a lista crua de `stages.json`
    (`{"type": "reverse_scroll", "time_seconds", "duration_seconds",
    "reversed": true|false}`) em tuplas
    `(time_seconds, duration_seconds, target_fraction)` ORDENADAS por
    tempo -- `target_fraction` e 1.0 (invertido) ou 0.0 (normal).
    Eventos de outro tipo (swap, distraction) sao ignorados aqui."""
    events = []
    for raw in raw_events:
        if raw.get("type") != "reverse_scroll":
            continue
        events.append(
            (
                float(raw["time_seconds"]),
                float(raw.get("duration_seconds", 1.0)),
                1.0 if raw.get("reversed", True) else 0.0,
            )
        )
    events.sort(key=lambda event: event[0])
    return tuple(events)


def compute_scroll_flip_fraction(
    now_effective: float,
    reverse_events: Tuple[Tuple[float, float, float], ...],
) -> float:
    """0.0 = scroll normal (notas caem PARA BAIXO), 1.0 = totalmente
    invertido (notas sobem PARA CIMA rumo a uma linha de julgamento no
    topo). Cada evento faz um Lerp a partir de onde a fracao ACUMULADA
    dos eventos anteriores parou ate `target_fraction`, ao longo de
    `duration_seconds` -- diferente do swap (que sempre faz Lerp entre
    dois valores FIXOS), aqui cada evento e um TOGGLE relativo ao
    estado atual, entao o encadeamento precisa carregar o valor
    anterior adiante (funciona corretamente desde que os eventos nao se
    sobreponham no tempo, o uso normal de um Modchart escrito a mao).

    Pura e sem estado -- nao possui `out=` porque e um ESCALAR, nao um
    array; testavel sem ECS/pygame."""
    fraction = 0.0
    for time_seconds, duration_seconds, target_fraction in reverse_events:
        if now_effective < time_seconds:
            break
        progress = (
            1.0 if duration_seconds <= 0.0 else min(1.0, (now_effective - time_seconds) / duration_seconds)
        )
        fraction = fraction + (target_fraction - fraction) * progress
    return fraction


def parse_vision_tunnel_events(raw_events: Sequence[Dict]) -> Tuple[Tuple[float, float, float], ...]:
    """Normaliza a lista crua de `stages.json`
    (`{"type": "vision_tunnel", "time_seconds", "duration_seconds",
    "target_radius"}`) em tuplas `(time_seconds, duration_seconds,
    target_radius)` ORDENADAS por tempo. Eventos de outro tipo (swap,
    reverse_scroll, distraction) sao ignorados aqui -- cada feature
    filtra so o que lhe interessa da MESMA lista de `modchart_events`."""
    events = []
    for raw in raw_events:
        if raw.get("type") != "vision_tunnel":
            continue
        events.append(
            (
                float(raw["time_seconds"]),
                float(raw.get("duration_seconds", 1.0)),
                float(raw["target_radius"]),
            )
        )
    events.sort(key=lambda event: event[0])
    return tuple(events)


def compute_tunnel_radius(
    now_effective: float,
    base_radius: float,
    collapse_events: Tuple[Tuple[float, float, float], ...],
) -> float:
    """Raio ATUAL (px) do campo de luz do Colapso de Visao (Defensor,
    puramente cosmetico -- ver `GameState.tunnel_radius`). MESMO idioma
    de encadeamento de `compute_scroll_flip_fraction`: cada evento faz
    um Lerp a partir de onde o raio ACUMULADO dos eventos anteriores
    parou ate `target_radius` (nao entre dois valores fixos), ao longo
    de `duration_seconds` -- permite uma SEQUENCIA de colapsos/expansoes
    ao longo da musica (ex.: encolhe no Drop, expande de volta depois),
    desde que os eventos nao se sobreponham no tempo.

    Pura e sem estado -- escalar, testavel sem ECS/pygame."""
    radius = base_radius
    for time_seconds, duration_seconds, target_radius in collapse_events:
        if now_effective < time_seconds:
            break
        progress = (
            1.0 if duration_seconds <= 0.0 else min(1.0, (now_effective - time_seconds) / duration_seconds)
        )
        radius = radius + (target_radius - radius) * progress
    return radius
