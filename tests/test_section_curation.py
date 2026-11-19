"""Curadoria POR SECAO: a densidade do chart segue a estrutura da musica.

Antes, um `min_gap_seconds` global valia da intro ao ultimo compasso, e a
progressao de dificuldade do jogo vinha inteira de EMPILHAR modificadores
entre fases. Com janelas por secao, uma ponte `calm` pode respirar e um
climax `intense` apertar dentro da MESMA faixa -- e o alivio e o que faz
o climax existir como climax.

As duas funcoes puras testadas aqui existem por brechas descobertas
medindo, nao projetando: ver os docstrings de `_build_curation_windows` e
`enforce_minimum_separation`.
"""
import numpy as np
import pytest

from hertzbeats.offline.beatmap_pipeline import (
    _build_curation_windows,
    enforce_minimum_separation,
)

FLAT_SPEC = {"bpm": 120.0, "bars": 8, "style": "standard"}
SECTIONED_SPEC = {
    "bpm": 120.0,  # 1 compasso = 2 s
    "sections": [
        {"name": "intro", "bars": 2},
        {"name": "ponte", "bars": 2, "min_gap_seconds": 0.7, "target_density_per_second": 0.8},
        {"name": "climax", "bars": 4, "min_gap_seconds": 0.32, "target_density_per_second": 2.2},
    ],
}


def _windows(spec, min_start=0.0, max_end=16.0, min_gap=0.45, density=1.4):
    return _build_curation_windows(spec, min_start, max_end, min_gap, density)


# ------------------------------------------------------------- janelas


def test_flat_spec_yields_one_global_window():
    """A garantia de retrocompatibilidade: faixa plana = uma janela com os
    parametros globais, que e' literalmente o codigo antigo."""
    windows = _windows(FLAT_SPEC)
    assert len(windows) == 1
    assert (windows[0].start_seconds, windows[0].end_seconds) == (0.0, 16.0)
    assert windows[0].min_gap_seconds == 0.45
    assert windows[0].density == 1.4


def test_missing_spec_also_yields_one_global_window():
    assert len(_windows(None)) == 1


def test_each_section_becomes_its_own_window():
    windows = _windows(SECTIONED_SPEC)
    assert [w.name for w in windows] == ["intro", "ponte", "climax"]
    assert [(w.start_seconds, w.end_seconds) for w in windows] == [
        (0.0, 4.0),
        (4.0, 8.0),
        (8.0, 16.0),
    ]


def test_sections_inherit_global_params_when_silent():
    """A intro nao declara nada: herda o global. So o que a secao DIZ e'
    que muda -- do contrario cada secao teria de repetir tudo."""
    intro = _windows(SECTIONED_SPEC)[0]
    assert (intro.min_gap_seconds, intro.density) == (0.45, 1.4)


def test_declared_section_params_win():
    _intro, ponte, climax = _windows(SECTIONED_SPEC)
    assert (ponte.min_gap_seconds, ponte.density) == (0.7, 0.8)
    assert (climax.min_gap_seconds, climax.density) == (0.32, 2.2)


def test_windows_are_clipped_to_the_playable_span():
    """A intro antes do primeiro instante jogavel e a cauda depois da
    margem final nao devem gerar janela nenhuma -- uma janela de span zero
    pediria `max_notes=0` e so gastaria trabalho."""
    windows = _windows(SECTIONED_SPEC, min_start=5.0, max_end=9.0)
    assert [w.name for w in windows] == ["ponte", "climax"]
    assert windows[0].start_seconds == 5.0
    assert windows[-1].end_seconds == 9.0


def test_span_reflects_clipping():
    ponte = _windows(SECTIONED_SPEC, min_start=5.0, max_end=9.0)[0]
    assert ponte.span_seconds == pytest.approx(3.0)


# --------------------------------------------- passagem final de espacamento


def _chart(*times):
    return (
        np.array(times, dtype=np.float64),
        np.full(len(times), 0.5),
        ["kick"] * len(times),
    )


def test_separation_drops_notes_that_are_too_close():
    times, strengths, layers = enforce_minimum_separation(*_chart(0.0, 0.1, 0.5, 0.55, 1.0), 0.3)
    assert times.tolist() == [0.0, 0.5, 1.0]
    assert len(strengths) == 3 and len(layers) == 3


def test_separation_keeps_the_earlier_note_of_a_pair():
    """Prioridade TEMPORAL, nunca por forca: manter a nota anterior
    preserva o downbeat, e um chart que perde o downbeat pra manter um
    onset mais forte soa errado mesmo estando 'mais certo' no papel."""
    times = np.array([1.00, 1.05], dtype=np.float64)
    strengths = np.array([0.1, 0.9])  # a SEGUNDA e' muito mais forte
    kept, _, _ = enforce_minimum_separation(times, strengths, ["kick", "vocal"], 0.3)
    assert kept.tolist() == [1.00]


def test_separation_is_a_noop_when_disabled_or_empty():
    times, _, _ = enforce_minimum_separation(*_chart(0.0, 0.01), 0.0)
    assert times.tolist() == [0.0, 0.01]
    empty, _, layers = enforce_minimum_separation(
        np.zeros(0), np.zeros(0), [], 0.3
    )
    assert empty.shape[0] == 0 and layers == []


def test_separation_preserves_layer_alignment():
    """As 3 saidas sao paralelas linha a linha; desalinha-las mandaria uma
    nota de melodia pra coluna de kick no Arcade."""
    times = np.array([0.0, 0.1, 0.6], dtype=np.float64)
    kept, strengths, layers = enforce_minimum_separation(
        times, np.array([0.1, 0.2, 0.3]), ["kick", "vocal", "vocal"], 0.3
    )
    assert kept.tolist() == [0.0, 0.6]
    assert layers == ["kick", "vocal"]
    assert strengths.tolist() == [0.1, 0.3]


def test_separation_closes_the_window_boundary_hole():
    """A brecha que motivou a funcao: a selecao por secao nao ve as
    vizinhas, entao dois kicks legitimos -- um no fim de uma janela, outro
    no comeco da seguinte -- podiam sair colados."""
    times, _, _ = enforce_minimum_separation(*_chart(3.98, 4.01, 4.50), 0.3)
    assert times.tolist() == [3.98, 4.50]
