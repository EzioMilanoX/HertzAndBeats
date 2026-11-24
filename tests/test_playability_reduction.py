"""Reducao ciente do modo: a transcricao e fiel, o chart e jogavel.

A confusao que este modulo desfaz custou toda uma investigacao: o
`beatmap.json` era ao mesmo tempo a transcricao da musica E o chart
jogavel. O piso de jogabilidade era aplicado DENTRO da selecao de notas, o
que destruia informacao irreversivelmente -- e de forma invisivel: pedir
0.24 batidas de espacamento produzia o MESMO chart que pedir 0.75, porque
ambos eram elevados a 300 ms.

Separado, medido num piano solo de 183 s (1051 ataques detectados):

  antes  (transcricao == chart)  216 notas, 56% de cobertura
  agora  transcricao             951 notas, 100% de cobertura
         -> Defensor radial      396 notas (espacamento GLOBAL)
         -> Arcade 4K            951 notas (espacamento POR COLUNA)

E o pulso, que era a reclamacao original ("as notas estao certas mas nao
parece sincronizado"): 87% dos intervalos do chart reduzido sao multiplos
da batida, contra 30% no comeco.
"""
import numpy as np

from hertzbeats.playability_reduction import (
    LANE_MIN_GAP_SECONDS,
    RADIAL_MIN_GAP_SECONDS,
    estimate_beat_phase,
    gap_for_mode,
    metric_salience,
    reduce_for_playability,
)

BPM = 120.0
BEAT = 0.5


# ------------------------------------------------------------ por modo


def test_radial_mode_spaces_globally():
    """Defensor: um cursor, uma mira. Duas ameacas proximas no tempo sao
    fisicamente incompativeis, venham do angulo que vierem."""
    gap, per_lane = gap_for_mode("defender")
    assert gap == RADIAL_MIN_GAP_SECONDS
    assert per_lane is False


def test_lane_mode_spaces_per_column():
    """Arcade 4K: 4 colunas independentes. Notas simultaneas em colunas
    diferentes sao o padrao do genero, nao um problema."""
    gap, per_lane = gap_for_mode("lanes")
    assert gap == LANE_MIN_GAP_SECONDS
    assert per_lane is True


def test_unknown_mode_falls_back_to_the_strictest():
    """Errar para o lado seguro: um modo novo sem entrada aqui nao pode
    gerar um chart injogavel."""
    assert gap_for_mode("modo_que_nao_existe") == gap_for_mode("defender")


def test_lane_gap_is_much_smaller_than_radial():
    assert LANE_MIN_GAP_SECONDS < RADIAL_MIN_GAP_SECONDS / 2.0


# --------------------------------------------------------- saliencia metrica


def test_downbeat_outranks_beat_outranks_offbeat_outranks_subdivision():
    """A ordem que faz a poda preservar o PULSO em vez do volume."""
    tempos = np.array([0.0, BEAT, BEAT * 1.5, BEAT * 1.25])
    pesos = metric_salience(tempos, BPM)
    downbeat, batida, contratempo, subdivisao = pesos
    assert downbeat > batida > contratempo > subdivisao


def test_salience_is_uniform_without_a_reliable_bpm():
    """Sem BPM a poda degrada para 'por forca' -- o comportamento antigo,
    nunca um erro."""
    tempos = np.array([0.0, 0.1, 0.2])
    assert np.all(metric_salience(tempos, 0.0) == 1.0)


def test_beat_phase_uses_a_circular_mean():
    """Instantes a 0.01 e a 0.49 de um periodo de 0.50 estao ambos quase na
    batida; a media ARITMETICA os colocaria em 0.25 -- exatamente entre duas
    batidas, o pior lugar possivel."""
    tempos = np.array([0.01, 0.49, 0.505, 0.995])
    fase = estimate_beat_phase(tempos, BPM)
    assert min(abs(fase), abs(abs(fase) - BEAT)) < 0.05


# ------------------------------------------------------------------ poda


def _chart(tempos, forcas=None, pistas=None):
    tempos = np.asarray(tempos, dtype=np.float64)
    return (
        tempos,
        np.asarray(forcas if forcas is not None else [0.5] * len(tempos), dtype=np.float64),
        np.asarray(pistas if pistas is not None else [0] * len(tempos), dtype=np.int64),
    )


def test_reduction_enforces_the_gap_globally():
    t, f, pistas = _chart([0.0, 0.05, 0.10, 0.40, 0.80])
    mantidos = reduce_for_playability(t, f, pistas, min_gap_seconds=0.30, bpm=BPM)
    sobrou = t[mantidos]
    assert np.all(np.diff(sobrou) >= 0.30 - 1e-9)


def test_reduction_returns_chronological_indices():
    """A poda e gulosa por SALIENCIA, entao a ordem final nao e acidente --
    o jogo exige instantes crescentes."""
    t, f, pistas = _chart([0.0, 0.5, 1.0, 1.5, 2.0])
    mantidos = reduce_for_playability(t, f, pistas, min_gap_seconds=0.30, bpm=BPM)
    assert list(mantidos) == sorted(mantidos)


def test_reduction_keeps_the_beat_and_drops_the_subdivision():
    """O coracao da correcao: entre uma nota FORTE fora do tempo e uma nota
    fraca NA batida, sobrevive a da batida. Podar por volume era o que
    produzia charts que acertavam ataques reais e nao formavam pulso."""
    # Chart com pulso ESTABELECIDO: a fase da grade precisa estar
    # determinada, senao (como num teste de 2 notas) qualquer instante conta
    # como "na batida" e o desempate cai na forca.
    tempos = [0.0, 0.5, 1.0, 1.5, 2.0, 2.12]
    forcas = [0.5, 0.5, 0.5, 0.5, 0.2, 0.95]  # 2.0 = batida FRACA, 2.12 = subdivisao FORTE
    t, f, pistas = _chart(tempos, forcas=forcas)
    mantidos = reduce_for_playability(t, f, pistas, min_gap_seconds=0.30, bpm=BPM)
    sobrou = t[mantidos].tolist()
    assert 2.0 in sobrou, "a batida fraca tem de sobreviver"
    assert 2.12 not in sobrou, "a subdivisao forte tem de cair"


def test_strength_breaks_ties_within_the_same_metric_weight():
    t, f, pistas = _chart([1.0, 1.02], forcas=[0.3, 0.9])  # ambas na mesma batida
    mantidos = reduce_for_playability(t, f, pistas, min_gap_seconds=0.30, bpm=BPM)
    assert t[mantidos].tolist() == [1.02]


def test_per_lane_reduction_allows_simultaneous_notes_in_other_columns():
    """4 notas no MESMO instante em 4 colunas: um acorde de FNF, nao um
    problema. Com espacamento global as 3 ultimas morreriam."""
    t, f, pistas = _chart([0.0, 0.0, 0.0, 0.0], pistas=[0, 1, 2, 3])
    mantidos = reduce_for_playability(t, f, pistas, min_gap_seconds=0.11, bpm=BPM, per_lane=True)
    assert len(mantidos) == 4
    global_ = reduce_for_playability(t, f, pistas, min_gap_seconds=0.11, bpm=BPM, per_lane=False)
    assert len(global_) == 1


def test_per_lane_reduction_still_spaces_inside_a_column():
    """O que a poda por coluna NAO pode virar: 4 notas colidindo na mesma
    tecla."""
    t, f, pistas = _chart([0.0, 0.03, 0.06], pistas=[2, 2, 2])
    mantidos = reduce_for_playability(t, f, pistas, min_gap_seconds=0.11, bpm=BPM, per_lane=True)
    assert len(mantidos) == 1


def test_reduction_is_a_noop_when_the_chart_already_fits():
    t, f, pistas = _chart([0.0, 0.5, 1.0])
    mantidos = reduce_for_playability(t, f, pistas, min_gap_seconds=0.30, bpm=BPM)
    assert len(mantidos) == 3


def test_empty_and_disabled_cases():
    t, f, pistas = _chart([])
    assert reduce_for_playability(t, f, pistas, min_gap_seconds=0.3, bpm=BPM).shape[0] == 0
    t, f, pistas = _chart([0.0, 0.01])
    assert reduce_for_playability(t, f, pistas, min_gap_seconds=0.0, bpm=BPM).shape[0] == 2


# --------------------------------- os charts reais, transcricao -> reduzido


def _user_charts():
    import glob
    import json

    for caminho in sorted(glob.glob("data/beatmaps/user/*.beatmap.json")):
        with open(caminho, encoding="utf-8") as f:
            beatmap = json.load(f)
        yield caminho, beatmap


def test_every_reduced_chart_respects_its_mode_floor():
    """A invariante que substitui a antiga (que media o piso na
    transcricao): o piso vale no chart REDUZIDO, que e' o que se joga."""
    for caminho, beatmap in _user_charts():
        tempos = np.array([t["timestamp_seconds"] for t in beatmap["threats"]])
        forcas = np.array([t["strength"] for t in beatmap["threats"]])
        pistas = np.array([t["lane"] for t in beatmap["threats"]])
        for modo in ("defender", "lanes"):
            gap, per_lane = gap_for_mode(modo)
            mantidos = reduce_for_playability(
                tempos, forcas, pistas, min_gap_seconds=gap, bpm=beatmap["bpm"], per_lane=per_lane
            )
            sobrou = tempos[mantidos]
            if per_lane:
                for pista in np.unique(pistas[mantidos]):
                    da_pista = sobrou[pistas[mantidos] == pista]
                    if da_pista.shape[0] > 1:
                        assert np.diff(da_pista).min() >= gap - 1e-6, f"{caminho} [{modo}] pista {pista}"
            elif sobrou.shape[0] > 1:
                assert np.diff(sobrou).min() >= gap - 1e-6, f"{caminho} [{modo}]"


def test_lane_mode_keeps_more_than_radial():
    """A razao de a poda ser por modo: o Arcade aguenta muito mais. Se os
    dois modos ficassem iguais, a separacao nao estaria valendo nada."""
    for caminho, beatmap in _user_charts():
        tempos = np.array([t["timestamp_seconds"] for t in beatmap["threats"]])
        forcas = np.array([t["strength"] for t in beatmap["threats"]])
        pistas = np.array([t["lane"] for t in beatmap["threats"]])
        radial = reduce_for_playability(
            tempos, forcas, pistas, min_gap_seconds=RADIAL_MIN_GAP_SECONDS, bpm=beatmap["bpm"]
        )
        lanes = reduce_for_playability(
            tempos, forcas, pistas, min_gap_seconds=LANE_MIN_GAP_SECONDS,
            bpm=beatmap["bpm"], per_lane=True,
        )
        assert lanes.shape[0] > radial.shape[0], caminho
