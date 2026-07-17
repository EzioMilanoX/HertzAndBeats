"""Funde clusters de notas PESADAS (picos/drops) num unico evento de Scratch (nota longa) do Arcade 4K."""
from __future__ import annotations

from typing import Tuple

import numpy as np


def build_lane_schedule_with_scratches(
    scheduled: np.ndarray,
    hit_times: np.ndarray,
    heavy_type_id: int,
    cluster_gap_seconds: float,
    min_cluster_size: int,
    hold_tail_seconds: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Percorre `scheduled`/`hit_times` (SCHEDULED_THREAT_DTYPE, ja
    ordenados por tempo -- garantido pelo `BeatmapLoader`) e funde toda
    sequencia de `min_cluster_size` ou mais ameacas PESADAS consecutivas
    (gap <= `cluster_gap_seconds` entre uma e a proxima) numa UNICA nota
    de Scratch: um cluster e um "solo insano" -- na pratica, a rajada de
    picos de energia que o extrator de onsets ja concentra num trecho
    curto da musica.

    Pura funcao de interpretacao GAME-side sobre dados que a IA/mapeador
    ja produziu -- nao muda o beatmap.json nem chama librosa; roda uma
    unica vez na composicao da fase (fora do loop de gameplay).

    Retorna `(scheduled_out, hit_times_out, is_hold_out, hold_end_out)`,
    mesma ordem temporal, tamanho <= `len(scheduled)`:
        - linhas normais: `is_hold_out=False`, `hold_end_out=0.0`.
        - linhas de scratch: usam a lane/strength/threat_type da PRIMEIRA
          pesada do cluster; `hit_times_out` = inicio do cluster;
          `hold_end_out` = fim do cluster + `hold_tail_seconds` (a
          janela inteira em que o jogador deve manter o mouse em
          movimento).
    """
    n = hit_times.shape[0]
    is_heavy = scheduled["threat_type"] == heavy_type_id

    out_timestamps = []
    out_rows = []
    out_is_hold = []
    out_hold_end = []

    i = 0
    while i < n:
        if not is_heavy[i]:
            out_timestamps.append(float(hit_times[i]))
            out_rows.append(scheduled[i])
            out_is_hold.append(False)
            out_hold_end.append(0.0)
            i += 1
            continue

        cluster_end = i
        while (
            cluster_end + 1 < n
            and is_heavy[cluster_end + 1]
            and (hit_times[cluster_end + 1] - hit_times[cluster_end]) <= cluster_gap_seconds
        ):
            cluster_end += 1

        cluster_size = cluster_end - i + 1
        if cluster_size >= min_cluster_size:
            out_timestamps.append(float(hit_times[i]))
            out_rows.append(scheduled[i])
            out_is_hold.append(True)
            out_hold_end.append(float(hit_times[cluster_end]) + hold_tail_seconds)
        else:
            for k in range(i, cluster_end + 1):
                out_timestamps.append(float(hit_times[k]))
                out_rows.append(scheduled[k])
                out_is_hold.append(False)
                out_hold_end.append(0.0)
        i = cluster_end + 1

    count = len(out_rows)
    scheduled_out = np.zeros(count, dtype=scheduled.dtype)
    for idx, row in enumerate(out_rows):
        scheduled_out[idx] = row
    hit_times_out = np.asarray(out_timestamps, dtype=np.float64)
    is_hold_out = np.asarray(out_is_hold, dtype=bool)
    hold_end_out = np.asarray(out_hold_end, dtype=np.float64)
    return scheduled_out, hit_times_out, is_hold_out, hold_end_out
