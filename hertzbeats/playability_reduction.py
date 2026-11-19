"""Reducao do chart FIEL para o que e' jogavel, ciente do modo.

Este modulo existe por causa de uma confusao que custou caro: o
`beatmap.json` era ao mesmo tempo a transcricao da musica E o chart
jogavel. Nao pode ser as duas coisas. O piso de jogabilidade era aplicado
DENTRO da selecao de notas, o que destruia informacao de forma
irreversivel -- e, pior, de forma invisivel: pedir 0.24 batidas de
espacamento produzia exatamente o mesmo chart que pedir 0.75, porque ambos
eram elevados ao piso de 300 ms.

Agora o beatmap em disco e' a transcricao mais fiel que a IA consegue
(medido num piano solo: de 56% para 100% de cobertura dos ataques reais), e
a poda para o que cada MODO aguenta acontece aqui, na composicao.

A diferenca entre os modos nao e' de grau, e' de natureza:

- **Defensor radial**: um cursor, uma mira. Duas ameacas proximas no tempo
  sao fisicamente incompativeis, nao importa de que angulo venham -- o
  espacamento vale GLOBALMENTE.
- **Arcade 4K**: 4 colunas independentes, uma tecla por coluna. Notas
  simultaneas em colunas diferentes sao o padrao do genero (acordes de
  FNF). O espacamento vale POR COLUNA, o que multiplica a densidade
  possivel por 4 sem exigir nada de sobre-humano do jogador.

Modelar isso como "um piso menor no Arcade" seria errado: permitiria 4
notas colidindo na MESMA coluna. Por isso a poda e por fluxo.

Prioridade da poda -- e onde a licao de "notas certas sem ritmo nenhum"
foi aprendida: a nota que sobrevive nao e' a mais FORTE, e a
metricamente mais SALIENTE (tempo forte > batida > contratempo >
subdivisao), com a forca como desempate. Podar por volume produzia um
chart que acertava ataques reais e nao formava pulso -- exatamente a
reclamacao que originou este trabalho.
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

RADIAL_MIN_GAP_SECONDS = 0.30
"""Defensor: um cursor. Mesmo piso que `tests/test_playability_invariants`
protege, e o valor que a jogabilidade radial ja demonstrou aguentar."""

LANE_MIN_GAP_SECONDS = 0.11
"""Arcade 4K, POR COLUNA. 110 ms na mesma coluna sao ~16 avos a 136 BPM --
o teto de repeticao de uma tecla so. Notas simultaneas em colunas
diferentes nao sao afetadas, que e' justamente o ponto."""


def metric_salience(
    times: np.ndarray, bpm: float, phase_seconds: float = 0.0
) -> np.ndarray:
    """Peso metrico de cada instante: quanto mais forte o tempo, maior.

    4.0 = tempo forte do compasso (1o de 4 batidas)
    3.0 = outra batida inteira
    2.0 = contratempo de colcheia
    1.0 = subdivisao mais fina

    Serve para a poda preservar o PULSO em vez do volume. Sem BPM confiavel
    devolve peso uniforme -- a poda degrada para "por forca", que e' o
    comportamento antigo, nunca um erro.
    """
    count = times.shape[0]
    if bpm <= 0.0 or count == 0:
        return np.ones(count, dtype=np.float64)

    beat = 60.0 / float(bpm)
    position = (times - phase_seconds) / beat  # em batidas
    from_beat = np.abs(position - np.round(position))
    from_half = np.abs(position * 2.0 - np.round(position * 2.0)) / 2.0
    beat_index = np.round(position).astype(np.int64)

    tolerance = 0.12  # em batidas
    salience = np.ones(count, dtype=np.float64)
    is_beat = from_beat <= tolerance
    salience[is_beat] = 3.0
    salience[is_beat & (beat_index % 4 == 0)] = 4.0
    salience[(~is_beat) & (from_half <= tolerance)] = 2.0
    return salience


def estimate_beat_phase(times: np.ndarray, bpm: float) -> float:
    """Fase da grade de batidas, pela media CIRCULAR dos instantes.

    Media circular e nao aritmetica: instantes a 0.01 e a 0.39 de um periodo
    de 0.40 estao ambos "quase na batida", e a media aritmetica os colocaria
    no meio, exatamente entre duas batidas."""
    if bpm <= 0.0 or times.shape[0] == 0:
        return 0.0
    beat = 60.0 / float(bpm)
    angles = 2.0 * np.pi * (times % beat) / beat
    return float(np.angle(np.mean(np.exp(1j * angles))) / (2.0 * np.pi) * beat)


def reduce_for_playability(
    times: np.ndarray,
    strengths: np.ndarray,
    lanes: Optional[np.ndarray],
    min_gap_seconds: float,
    bpm: float = 0.0,
    per_lane: bool = False,
) -> np.ndarray:
    """Indices das notas que SOBREVIVEM a poda, em ordem temporal.

    Guloso por saliencia metrica (desempate pela forca), aceitando uma nota
    apenas quando ela respeita `min_gap_seconds` das ja aceitas -- no fluxo
    inteiro (`per_lane=False`, Defensor) ou dentro da propria coluna
    (`per_lane=True`, Arcade 4K).

    Guloso pela saliencia e nao cronologico de proposito: varrer em ordem de
    tempo aceitaria a primeira nota de cada aglomerado, que costuma ser uma
    subdivisao antes do tempo forte -- e o tempo forte, que e' o que o
    jogador sente, seria o descartado.
    """
    count = times.shape[0]
    if count == 0 or min_gap_seconds <= 0.0:
        return np.arange(count, dtype=np.int64)

    phase = estimate_beat_phase(times, bpm)
    salience = metric_salience(times, bpm, phase)
    order = np.lexsort((-strengths, -salience))  # saliencia desc, forca desc

    if per_lane and lanes is not None:
        streams = {int(lane): [] for lane in np.unique(lanes)}
    else:
        streams = {0: []}

    accepted = []
    for index in order:
        key = int(lanes[index]) if (per_lane and lanes is not None) else 0
        stream = streams[key]
        moment = float(times[index])
        if any(abs(moment - kept) < min_gap_seconds for kept in stream):
            continue
        stream.append(moment)
        accepted.append(int(index))

    return np.asarray(sorted(accepted), dtype=np.int64)


def gap_for_mode(game_mode: str) -> Tuple[float, bool]:
    """`(gap_minimo, por_coluna)` do modo. Modo desconhecido cai no radial,
    que e' o mais restritivo -- errar para o lado seguro."""
    if game_mode == "lanes":
        return LANE_MIN_GAP_SECONDS, True
    return RADIAL_MIN_GAP_SECONDS, False
