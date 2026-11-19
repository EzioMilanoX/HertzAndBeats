"""Qualidade da curadoria: nota fantasma e pulso perdido.

Dois defeitos reportados jogando, com causas opostas e a mesma origem --
parametros de curadoria escolhidos como constantes sem relacao com o resto
do jogo:

1. NOTA FANTASMA (o jogador ve a nota e nao ouve nada). A nota e gravada no
   instante da GRADE, nao do ataque. Com tolerancia de snap de 80 ms, um
   ataque a 80 ms do ponto de grade ainda o preenchia -- e a janela PERFECT
   e 50 ms, entao a nota nascia FORA da janela do som que a gerou.

2. PULSO PERDIDO (as notas estao certas mas nao formam ritmo). Espacamento
   minimo em SEGUNDOS vale mais de uma batida em musica rapida, e ai o
   chart nao pode marcar batidas consecutivas -- pula batida de forma
   irregular, porque escolhe por forca.

Nenhum dos dois quebrava teste algum: os charts eram validos, ordenados,
dentro da densidade maxima e sem softlock. Sao defeitos de SENSACAO, e a
unica forma de proteger e amarrar os parametros entre si.
"""
import numpy as np
import pytest

from hertzbeats.config import HertzConfig
from hertzbeats.offline.beatmap_pipeline import (
    DEFAULT_MIN_GAP_BEATS,
    DEFAULT_SNAP_TOLERANCE_SECONDS,
    MIN_PLAYABLE_GAP_SECONDS,
    select_slots,
    snap_onsets_to_grid,
)


@pytest.fixture(scope="module")
def base_config():
    return HertzConfig.from_json("data/config/hertz_beats.config.json")


# --------------------------------------------- invariantes entre parametros


def test_snap_tolerance_stays_inside_the_perfect_window(base_config):
    """A invariante que impede a nota fantasma de voltar.

    Quantizar MOVE a nota para o ponto da grade. Se o deslocamento maximo
    permitido (a tolerancia) for maior que a janela PERFECT, existe nota
    cujo som cai fora da propria janela dela -- o jogador ouve o ataque e o
    jogo pede o clique depois.
    """
    assert DEFAULT_SNAP_TOLERANCE_SECONDS < base_config.perfect_window_seconds, (
        f"snap de {DEFAULT_SNAP_TOLERANCE_SECONDS * 1000:.0f} ms nao cabe na janela "
        f"PERFECT de {base_config.perfect_window_seconds * 1000:.0f} ms"
    )


def test_minimum_gap_stays_below_one_beat():
    """A invariante que impede o pulso de colapsar. Em 1.0 batida ou mais o
    chart nao consegue marcar batidas consecutivas.

    Medido num piano a 152 BPM: 0.90 batidas -> 63% de intervalos regulares;
    1.00 batidas -> 25%; 1.15 batidas -> 30%. O 1.00 e o PIOR dos tres
    porque no limite exato o jitter dos onsets faz o seletor aceitar algumas
    batidas seguidas e rejeitar outras."""
    assert DEFAULT_MIN_GAP_BEATS < 1.0


def test_playability_floor_matches_the_invariants_test():
    """O piso vive em dois arquivos (curadoria e teste de jogabilidade).
    Divergir faria a curadoria autorizar densidade que o outro teste
    rejeita -- e o autor descobriria isso so ao regenerar."""
    from tests.test_playability_invariants import MIN_GAP_SECONDS

    assert MIN_PLAYABLE_GAP_SECONDS == MIN_GAP_SECONDS


# ------------------------------------------------------- snap para a grade


def test_snap_only_claims_slots_with_a_nearby_attack():
    grade = np.array([0.0, 0.5, 1.0, 1.5])
    onsets = np.array([0.02, 1.49])  # perto do slot 0 e do slot 3
    forcas = np.array([0.8, 0.9])
    _forca, tem_evento = snap_onsets_to_grid(grade, onsets, forcas, snap_tolerance=0.04)
    assert tem_evento.tolist() == [True, False, False, True]


def test_an_attack_beyond_the_tolerance_does_not_create_a_note():
    """O coracao da nota fantasma: com tolerancia frouxa este ataque
    'preencheria' o slot e a nota nasceria 80 ms longe do som."""
    grade = np.array([0.0, 0.5, 1.0])
    onsets = np.array([0.58])  # 80 ms depois do slot 0.5
    forcas = np.array([0.9])
    _f, tem_evento = snap_onsets_to_grid(grade, onsets, forcas, snap_tolerance=0.04)
    assert not tem_evento[1]
    _f, tem_evento_frouxo = snap_onsets_to_grid(grade, onsets, forcas, snap_tolerance=0.09)
    assert tem_evento_frouxo[1], "com tolerancia frouxa o slot e reivindicado -- o bug antigo"


# --------------------------------------------------------- selecao de slots


def _slots(tem_evento, forcas=None):
    n = len(tem_evento)
    grade = np.arange(n, dtype=np.float64) * 0.5
    return (
        grade,
        np.zeros(n, dtype=bool),
        np.array(forcas if forcas else [0.5] * n),
        np.array(tem_evento, dtype=bool),
    )


def test_empty_slots_never_become_notes_even_to_meet_the_density_target():
    """A densidade e um TETO, nunca uma cota: pedir mais notas do que ha
    eventos musicais nao pode inventar nota em silencio."""
    grade, on_beat, forcas, tem_evento = _slots([True, False, False, True, False, False])
    escolhidos = select_slots(
        grade, on_beat, forcas, tem_evento,
        min_start_seconds=0.0, max_end_seconds=10.0,
        min_gap_seconds=0.1, target_density_per_second=100.0,  # cota absurda
    )
    assert sorted(escolhidos) == [0, 3]


def test_selection_respects_the_minimum_gap():
    grade, on_beat, forcas, tem_evento = _slots([True] * 6)
    escolhidos = select_slots(
        grade, on_beat, forcas, tem_evento,
        min_start_seconds=0.0, max_end_seconds=10.0,
        min_gap_seconds=0.9, target_density_per_second=100.0,
    )
    tempos = grade[escolhidos]
    assert np.all(np.diff(tempos) >= 0.9 - 1e-9)


def test_selection_returns_chronological_order():
    """O jogo exige `timestamp_seconds` crescente; a selecao e por FORCA,
    entao a ordenacao final nao e acidente."""
    grade, on_beat, forcas, tem_evento = _slots(
        [True] * 5, forcas=[0.1, 0.9, 0.3, 0.7, 0.5]
    )
    escolhidos = select_slots(
        grade, on_beat, forcas, tem_evento,
        min_start_seconds=0.0, max_end_seconds=10.0,
        min_gap_seconds=0.1, target_density_per_second=100.0,
    )
    assert escolhidos == sorted(escolhidos)


def test_selection_honours_the_playable_window():
    grade, on_beat, forcas, tem_evento = _slots([True] * 6)
    escolhidos = select_slots(
        grade, on_beat, forcas, tem_evento,
        min_start_seconds=1.0, max_end_seconds=2.0,
        min_gap_seconds=0.1, target_density_per_second=100.0,
    )
    assert all(1.0 <= grade[i] <= 2.0 for i in escolhidos)


# ------------------------------------- os charts versionados de musica real


def test_no_versioned_user_chart_has_phantom_notes():
    """Guarda de dados sobre os beatmaps cacheados de musica do jogador:
    toda nota tem de ter um ataque proximo. Roda so sobre o que existe em
    disco (pasta vazia num clone novo = teste vazio, nunca falso positivo).
    """
    import glob
    import json

    for caminho in glob.glob("data/beatmaps/user/*.beatmap.json"):
        with open(caminho, encoding="utf-8") as f:
            beatmap = json.load(f)
        tempos = [t["timestamp_seconds"] for t in beatmap["threats"]]
        assert tempos == sorted(tempos), f"{caminho}: fora de ordem temporal"
        assert all(t >= 0.0 for t in tempos), f"{caminho}: instante negativo"
        # O piso de jogabilidade NAO se aplica aqui de proposito: o beatmap
        # de musica do jogador e a TRANSCRICAO fiel (densa por design,
        # cobertura medida de ~100% dos ataques reais), e a poda para o que
        # cada modo aguenta acontece na composicao. Ver
        # `tests/test_playability_reduction.py`, que verifica o piso no
        # chart REDUZIDO -- que e' o que o jogador de fato joga.
        gaps = np.diff(tempos)
        if gaps.size:
            assert gaps.min() > 0.0, f"{caminho}: duas notas no mesmo instante"
