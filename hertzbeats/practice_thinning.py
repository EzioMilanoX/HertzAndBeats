"""Modo Treino: reduz a densidade de onsets de uma fase JA MAPEADA, sem tocar a IA/o beatmap.json."""
from __future__ import annotations

from typing import Tuple

import numpy as np


def thin_schedule_for_practice(
    scheduled: np.ndarray,
    hit_times: np.ndarray,
    keep_fraction: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Mantem 1 a cada `round(1/keep_fraction)` eventos, UNIFORMEMENTE
    espacados (stride) -- preserva a sensacao ritmica melhor que
    descarte aleatorio, ja que sobrevive sempre o MESMO onset relativo
    de cada grupo. `keep_fraction >= 1.0` e um no-op (copia identica).

    Pura funcao de interpretacao GAME-side (mesmo espirito de
    `lane_scratch_clustering`/`select_onsets` da engine): roda uma unica
    vez na composicao da fase, sobre dados que a IA ja produziu -- nunca
    reanalisa audio nem muda o beatmap.json versionado. `scheduled`/
    `hit_times` sao os arrays JA CARREGADOS pelo `BeatmapLoader`,
    paralelos linha a linha.
    """
    if keep_fraction >= 1.0 or scheduled.shape[0] == 0:
        return scheduled.copy(), hit_times.copy()
    stride = max(1, round(1.0 / max(keep_fraction, 1e-6)))
    indices = np.arange(0, scheduled.shape[0], stride)
    return scheduled[indices].copy(), hit_times[indices].copy()
