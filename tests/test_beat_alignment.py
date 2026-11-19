"""A promessa central do jogo, medida: as ameacas caem NA batida.

O README abre dizendo que a ameaca toca o anel "exatamente no milissegundo
da batida extraida pela IA". Isso nunca tinha sido verificado -- e estava
errado: 98% das ameacas caiam ATRASADAS, media +18.4 ms, porque o extrator
de onsets deriva o instante do PICO do envelope de fluxo espectral, que
acontece 1-2 frames depois do transiente (11.6 ms por frame a 44.1 kHz com
hop 512). Numa janela PERFECT de 50 ms, 18 ms de vies consomem 40% da
janela antes de o jogador tocar em nada.

Estes testes existem porque o sintoma era invisivel de todos os lados: o
jogo nao quebra, nenhum JSON fica invalido, nenhuma invariante estoura --
so parece "quase certo" pra quem joga, o que e' indistinguivel de latencia
de audio nao calibrada. Sem verdade fundamental nao havia como um humano
separar as duas causas.

A verdade fundamental existe SO porque as faixas curadas sao sintetizadas:
`percussive_onset_times` sabe onde cada bumbo esta pela mesma aritmetica
que os posicionou. Musica do jogador nao tem isso -- ali vale a constante
`DEFAULT_ONSET_LAG_SECONDS`, derivada destas medicoes.
"""
import json

import numpy as np
import pytest

from hertzbeats.audio.demo_track_synth import (
    measure_onset_lag_seconds,
    percussive_onset_times,
)
from hertzbeats.stages import load_stages

MATCH_WINDOW_SECONDS = 0.06
"""Alem disto a nota nao casa com batida nenhuma (cauda de crash, ataque de
baixo): entra na contagem de nao-casadas, nunca no calculo de desvio."""

MAX_MEDIAN_ABS_ERROR_SECONDS = 0.012
"""Medido apos a correcao: 5.7-7.4 ms por faixa. Teto com folga, mas bem
abaixo da janela PERFECT de 50 ms -- se voltar a passar disto, o chart
deixou de estar no ritmo."""

MAX_P90_ABS_ERROR_SECONDS = 0.030
MAX_RESIDUAL_BIAS_SECONDS = 0.003
"""O teste mais importante do arquivo. Erro ALEATORIO de alguns ms e a
resolucao do DSP; erro SISTEMATICO na mesma direcao e bug, e e' exatamente
o que passou despercebido."""

MIN_MATCHED_FRACTION = 0.85


def _curated_stages():
    """Fases com faixa sintetizada e beatmap da IA. O tutorial fica fora: o
    beatmap dele e AUTORAL (timing didatico de proposito, notas a cada 3 s
    que nao seguem a bateria)."""
    return [
        stage
        for stage in load_stages("data/stages/stages.json")
        if stage.synth is not None and not stage.tutorial_steps and stage.track_path
    ]


def _signed_errors(stage):
    """Desvio assinado de cada ameaca ate a batida mais proxima.
    Positivo = a ameaca chega DEPOIS da bateria real."""
    truth = percussive_onset_times(stage.synth)
    with open(stage.beatmap_path, encoding="utf-8") as f:
        times = np.array(
            [t["timestamp_seconds"] for t in json.load(f)["threats"]], dtype=np.float64
        )
    index = np.searchsorted(truth, times).clip(1, truth.shape[0] - 1)
    before, after = truth[index - 1], truth[index]
    nearest = np.where(np.abs(times - before) < np.abs(times - after), before, after)
    delta = times - nearest
    return delta, delta[np.abs(delta) <= MATCH_WINDOW_SECONDS]


def _ids(stages):
    return [stage.stage_id for stage in stages]


@pytest.mark.parametrize("stage", _curated_stages(), ids=_ids(_curated_stages()))
def test_no_systematic_bias(stage):
    """Nenhuma direcao preferida: as ameacas nao chegam consistentemente
    atrasadas nem adiantadas em relacao a bateria."""
    _all_errors, matched = _signed_errors(stage)
    bias = float(np.median(matched))
    assert abs(bias) <= MAX_RESIDUAL_BIAS_SECONDS, (
        f"{stage.stage_id}: vies de {bias * 1000:+.1f} ms -- o chart esta "
        f"sistematicamente {'atrasado' if bias > 0 else 'adiantado'}. "
        f"Rode `python tools/generate_stage_assets.py --force`."
    )


@pytest.mark.parametrize("stage", _curated_stages(), ids=_ids(_curated_stages()))
def test_median_error_is_a_small_fraction_of_the_perfect_window(stage):
    errors, _matched = _signed_errors(stage)
    median = float(np.median(np.abs(errors)))
    assert median <= MAX_MEDIAN_ABS_ERROR_SECONDS, (
        f"{stage.stage_id}: erro mediano de {median * 1000:.1f} ms "
        f"(teto {MAX_MEDIAN_ABS_ERROR_SECONDS * 1000:.0f} ms)"
    )


@pytest.mark.parametrize("stage", _curated_stages(), ids=_ids(_curated_stages()))
def test_the_tail_stays_inside_the_perfect_window(stage):
    """Nao basta a mediana: uma cauda gorda faz o jogador errar notas
    especificas sem entender por que."""
    errors, _matched = _signed_errors(stage)
    p90 = float(np.percentile(np.abs(errors), 90))
    assert p90 <= MAX_P90_ABS_ERROR_SECONDS, (
        f"{stage.stage_id}: p90 de {p90 * 1000:.1f} ms "
        f"(teto {MAX_P90_ABS_ERROR_SECONDS * 1000:.0f} ms)"
    )


@pytest.mark.parametrize("stage", _curated_stages(), ids=_ids(_curated_stages()))
def test_most_notes_land_on_an_actual_drum_hit(stage):
    """Guarda contra o caso oposto: um chart perfeitamente alinhado a
    batidas que nao existem. Se a maioria das notas nao casa com nenhum
    golpe real, a IA esta achando onset em cauda de crash ou ataque de
    baixo, e as medidas acima ficariam otimas medindo a coisa errada."""
    errors, matched = _signed_errors(stage)
    fraction = matched.shape[0] / max(1, errors.shape[0])
    assert fraction >= MIN_MATCHED_FRACTION, (
        f"{stage.stage_id}: so {fraction:.0%} das ameacas casam com um golpe de "
        f"bateria real (minimo {MIN_MATCHED_FRACTION:.0%})"
    )


@pytest.mark.parametrize("stage", _curated_stages(), ids=_ids(_curated_stages()))
def test_the_correction_is_recorded_in_the_beatmap(stage):
    """`onset_lag_correction_seconds` fica gravado pra a correcao ser
    auditavel: sem isso, um chart alinhado e indistinguivel de um chart que
    nunca precisou de correcao."""
    with open(stage.beatmap_path, encoding="utf-8") as f:
        beatmap = json.load(f)
    recorded = beatmap.get("onset_lag_correction_seconds")
    assert recorded is not None, (
        f"{stage.stage_id}: beatmap sem registro de correcao -- rode "
        f"`python tools/generate_stage_assets.py --force`"
    )
    assert 0.0 <= recorded < 0.1, f"{stage.stage_id}: correcao implausivel de {recorded * 1000:.1f} ms"


def test_measurement_agrees_with_the_correction_that_was_applied():
    """Fecha o ciclo: medir o vies do chart JA CORRIGIDO tem de dar ~zero.
    Se o gerador aplicasse a correcao no lugar errado (ou duas vezes), isto
    pegaria."""
    for stage in _curated_stages():
        with open(stage.beatmap_path, encoding="utf-8") as f:
            times = np.array(
                [t["timestamp_seconds"] for t in json.load(f)["threats"]], dtype=np.float64
            )
        residual = measure_onset_lag_seconds(times, stage.synth)
        assert abs(residual) <= MAX_RESIDUAL_BIAS_SECONDS, (
            f"{stage.stage_id}: vies residual de {residual * 1000:+.1f} ms"
        )


def test_ground_truth_matches_the_synthesized_audio():
    """A verdade fundamental precisa ser verdade. Confere que cada instante
    que `percussive_onset_times` aponta tem, de fato, um pico de energia
    grave no audio sintetizado -- se a aritmetica divergir da sintese, TODAS
    as medidas deste arquivo passam a medir nada."""
    from hertzbeats.audio.demo_track_synth import synthesize_track

    spec = {
        "bpm": 120.0,
        "sections": [{"name": "a", "bars": 4, "style": "standard", "progression": "base"}],
    }
    samples = synthesize_track(bpm=spec["bpm"], sections=spec["sections"])
    sample_rate = 44100
    onsets = percussive_onset_times(spec)
    assert onsets.shape[0] >= 16

    # energia numa janela curta a partir do instante apontado, contra uma
    # janela imediatamente ANTES dele: um golpe de bateria tem de ser mais
    # alto que o silencio/decay que o precede
    for onset in onsets:
        start = int(onset * sample_rate)
        before = samples[max(0, start - 1200) : max(1, start - 200)]
        after = samples[start : start + 1200]
        assert np.max(np.abs(after)) > np.max(np.abs(before)) * 1.2, (
            f"nenhum transiente em {onset:.3f}s -- a verdade fundamental "
            f"divergiu da sintese"
        )
