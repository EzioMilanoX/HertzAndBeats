"""Diagnostico por secao: ONDE o jogador perdeu, nao so quanto.

O Hit-Error Meter e o Histograma ja dizem *como* o jogador erra (cedo,
tarde, disperso). O que faltava era *onde*: uma fase de 45 s com 77
ameacas terminava em "12 misses" sem nenhuma pista de que 9 deles foram
no mesmo trecho. Com as faixas seccionadas isso passa a ser derivavel --
cada miss cai numa secao nomeada.

Fecha o ciclo com o Treino por Secao: a tela de resultados aponta a secao
e o jogador pratica exatamente aquela (`--section climax`), em vez de
repetir a musica inteira pra chegar no trecho que falhou.

Puro, sem estado: recebe as janelas e os instantes, devolve contagens.
Nada aqui roda dentro de um `ISystem` -- a atribuicao acontece no
`HertzGameLoop`, no mesmo ponto do frame onde o Audio Ducking ja detecta
um miss novo.
"""
from __future__ import annotations

from typing import Dict, Optional, Sequence, Tuple


def section_for_time(
    windows: Sequence[Tuple[str, float, float]], time_seconds: float
) -> Optional[str]:
    """Nome da secao que contem `time_seconds`, ou `None`.

    `None` tambem para faixa plana (nenhuma janela) -- e' o caso da maioria
    das musicas do jogador, e ali o diagnostico simplesmente nao se aplica.
    """
    for name, start, end in windows:
        if start <= time_seconds < end:
            return name
    return None


def accumulate_section_misses(
    counts: Dict[str, int],
    windows: Sequence[Tuple[str, float, float]],
    time_seconds: float,
    new_misses: int,
) -> Dict[str, int]:
    """Soma `new_misses` a secao que contem `time_seconds`, no lugar.

    Atribui pelo instante ATUAL do relogio de audio, nao pelo instante
    agendado da ameaca. E deliberado: um miss acontece quando a ameaca
    passa da janela (ou toca o nucleo), e e' esse momento -- o que o
    jogador viveu -- que interessa pro diagnostico. Perto de uma fronteira
    de secao as duas leituras podem discordar por alguns centesimos, o que
    e' irrelevante para "em que trecho eu falho".
    """
    if new_misses <= 0:
        return counts
    name = section_for_time(windows, time_seconds)
    if name is not None:
        counts[name] = counts.get(name, 0) + new_misses
    return counts


def worst_section(counts: Dict[str, int]) -> Optional[Tuple[str, int]]:
    """`(nome, misses)` da secao com mais misses, ou `None` se nao houve
    nenhum.

    Empate resolve pela secao MAIS CEDO da faixa (`counts` preserva a ordem
    de insercao, que e' a ordem em que o jogador as encontrou): mandar o
    jogador praticar o primeiro trecho problematico e melhor conselho do
    que mandar pro ultimo, porque um erro cedo costuma custar o combo de
    tudo que vem depois.
    """
    worst_name = None
    worst_count = 0
    for name, count in counts.items():
        if count > worst_count:
            worst_name, worst_count = name, count
    return None if worst_name is None else (worst_name, worst_count)


def format_section_report(counts: Dict[str, int]) -> str:
    """Linha unica para o resumo de fim de partida no console."""
    worst = worst_section(counts)
    if worst is None:
        return "nenhum miss por secao"
    detail = " ".join(f"{name}={count}" for name, count in counts.items() if count)
    return f"pior secao: {worst[0]} ({worst[1]} misses) | {detail}"
