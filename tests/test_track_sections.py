"""Faixas com ESTRUTURA (secoes) e a camada melodica (lead).

O teste mais importante daqui e o de REGRESSAO POR HASH: a forma plana
(`{"bpm","bars","style"}`) tem de continuar bit a bit identica, porque os
`beatmap.json` versionados foram extraidos por IA sobre exatamente esses
samples -- e o beatmap do TUTORIAL e autoral, com timestamps casados a
mao a faixa dele. Mudar o synth sem preservar isso dessincronizaria o
jogo silenciosamente: nenhum teste de logica falharia, o jogo so ficaria
fora do tempo.

O segundo mais importante e o de SEPARACAO DE BANDA: o lead vive acima do
corte do perfil de extracao "groove", e e SO isso que garante que uma
melodia de ataque seco nao seja confundida com batida pela IA offline.
"""
import json

import numpy as np
import pytest

from hertzbeats.audio.demo_track_synth import (
    _LEAD_OCTAVE_MULTIPLIER,
    _PROGRESSIONS,
    ensure_track,
    synthesize_track,
    total_bars,
    wav_fingerprint,
)
from hertzbeats.stages import load_stages

# Hashes capturados da implementacao ANTERIOR as secoes, sobre as 5
# especificacoes planas que o jogo realmente usa (tutorial, fase 1,
# fase 2, fase 3 e o tema de titulo).
LEGACY_HASHES = {
    (80.0, 21, "calm"): "8c04be3361b5a4bae025639b417ddad9",
    (100.0, 16, "calm"): "f3d26e02b7fbbc6f0b49f327cf07424c",
    (128.0, 24, "standard"): "a58df2f986b705933e29e347425c9b4c",
    (150.0, 28, "intense"): "d8ee608ddf095546a189aebb2b840991",
    (96.0, 16, "calm"): "c09c74f1b823be300c9d955f4585e5fb",
}

# Corte do mel grave do perfil "groove" (bumbo + corpo de caixa) e piso
# da banda do "vocal_shred", em Hz -- ver `extraction_profiles` na engine.
GROOVE_BAND_MAX_HZ = 250.0
VOCAL_BAND_MIN_HZ = 300.0

SAMPLE_RATE = 44100


def _sha(samples: np.ndarray) -> str:
    import hashlib

    return hashlib.sha256(samples.tobytes()).hexdigest()[:32]


def _band_energy(samples: np.ndarray, low_hz: float, high_hz: float) -> float:
    """Energia espectral numa banda (Parseval sobre a FFT real)."""
    spectrum = np.abs(np.fft.rfft(samples))
    freqs = np.fft.rfftfreq(samples.shape[0], d=1.0 / SAMPLE_RATE)
    mask = (freqs >= low_hz) & (freqs < high_hz)
    return float(np.sum(spectrum[mask] ** 2))


@pytest.mark.parametrize("spec,expected", sorted(LEGACY_HASHES.items()))
def test_flat_spec_stays_bit_identical(spec, expected):
    """A forma plana nao pode mudar NUNCA: os beatmaps versionados (e o
    autoral do tutorial) foram casados a estes samples exatos."""
    bpm, bars, style = spec
    assert _sha(synthesize_track(bpm=bpm, bars=bars, style=style)) == expected


def test_flat_spec_equals_single_section_of_same_style():
    """Uma faixa plana e, por definicao, UMA secao implicita cobrindo
    todos os compassos -- e e essa equivalencia que da a identidade bit a
    bit de graca, em vez de exigir dois caminhos de codigo."""
    flat = synthesize_track(bpm=128.0, bars=24, style="standard")
    sectioned = synthesize_track(
        bpm=128.0, sections=[{"name": "full", "bars": 24, "style": "standard"}]
    )
    assert np.array_equal(flat, sectioned)


def test_total_bars_agrees_across_both_forms():
    assert total_bars({"bpm": 150.0, "bars": 28, "style": "intense"}) == 28
    assert total_bars({"bpm": 150.0, "sections": [{"bars": 4}, {"bars": 8}, {"bars": 16}]}) == 28


def test_sample_count_follows_summed_sections():
    """A duracao mostrada no Carrossel usa `total_bars`; se a sintese e a
    aritmetica discordassem, a tela mentiria sobre a faixa."""
    sections = [
        {"name": "a", "bars": 4, "style": "calm"},
        {"name": "b", "bars": 6, "style": "intense"},
    ]
    samples = synthesize_track(bpm=120.0, sections=sections)
    expected = int(10 * 4 * (60.0 / 120.0) * SAMPLE_RATE)
    assert samples.shape[0] == expected


def test_synthesis_is_deterministic():
    sections = [{"name": "a", "bars": 4, "style": "intense", "lead": True}]
    first = synthesize_track(bpm=140.0, sections=sections)
    second = synthesize_track(bpm=140.0, sections=sections)
    assert np.array_equal(first, second)


def test_lead_lives_above_the_groove_band():
    """A invariante que protege a IA offline: a melodia soma energia na
    banda do extrator VOCAL (>=300 Hz) e deixa a banda do extrator de
    GROOVE (<250 Hz, bumbo/caixa) praticamente intacta.

    E por isso que o lead pode ter ataque seco (4 ms) sem criar batida
    falsa -- a protecao vem da banda, nao do envelope. Sem esta separacao,
    um lead percussivo empurraria o BPM estimado e o beatmap sairia fora
    do tempo da musica.
    """
    base = [{"name": "x", "bars": 8, "style": "standard", "progression": "base"}]
    with_lead = [dict(base[0], lead=True)]

    quiet = synthesize_track(bpm=128.0, sections=base)
    loud = synthesize_track(bpm=128.0, sections=with_lead)

    low_quiet = _band_energy(quiet, 0.0, GROOVE_BAND_MAX_HZ)
    low_loud = _band_energy(loud, 0.0, GROOVE_BAND_MAX_HZ)
    high_quiet = _band_energy(quiet, VOCAL_BAND_MIN_HZ, 8000.0)
    high_loud = _band_energy(loud, VOCAL_BAND_MIN_HZ, 8000.0)

    assert high_loud > high_quiet * 1.5, "o lead precisa ser audivel pro extrator vocal"
    # a banda do groove so pode variar pela renormalizacao global de pico
    assert 0.75 < low_loud / low_quiet < 1.25, "o lead nao pode invadir a banda do bumbo"


def test_lead_fundamentals_clear_the_vocal_band_floor():
    """Nenhuma nota do lead pode cair abaixo do piso de 300 Hz da banda
    vocal -- foi exatamente o bug da primeira versao (2 oitavas acima do
    baixo punha metade da melodia fora do alcance do extrator)."""
    lowest_bass_root = min(min(p) for p in _PROGRESSIONS.values())
    assert lowest_bass_root * _LEAD_OCTAVE_MULTIPLIER >= VOCAL_BAND_MIN_HZ


def test_every_section_opens_on_its_own_drop():
    """Drops/fills sao contados RELATIVAMENTE ao inicio da secao: e o que
    faz cada virada de secao se anunciar (crash + bumbo pesado) em vez de
    cair no meio de um compasso qualquer da grade global."""
    beat_seconds = 60.0 / 120.0
    samples_per_bar = int(4 * beat_seconds * SAMPLE_RATE)
    sections = [
        {"name": "a", "bars": 4, "style": "standard"},
        {"name": "b", "bars": 4, "style": "standard"},
    ]
    track = synthesize_track(bpm=120.0, sections=sections)

    # O crash do drop e o sinal: energia em 2-8 kHz, nao amplitude de pico
    # (o pico e do BUMBO, que existe em todo compasso -- medir pico nao
    # distingue um drop de um compasso comum).
    def bar_crash_energy(index: int) -> float:
        bar = track[index * samples_per_bar : (index + 1) * samples_per_bar]
        return _band_energy(bar, 2000.0, 8000.0)

    # `standard` = drop a cada 8 compassos: numa grade GLOBAL o compasso 4
    # (inicio da 2a secao) nao teria drop nenhum.
    assert bar_crash_energy(4) > bar_crash_energy(5) * 2.0, (
        "a 2a secao tem de abrir no proprio drop"
    )
    # e a contagem ser relativa a secao significa que as duas secoes, sendo
    # identicas, produzem o MESMO perfil compasso a compasso
    for offset in range(4):
        assert bar_crash_energy(offset) == pytest.approx(bar_crash_energy(4 + offset))


def test_unknown_style_and_progression_are_rejected_by_name():
    with pytest.raises(ValueError, match="estilo desconhecido"):
        synthesize_track(bpm=120.0, sections=[{"bars": 4, "style": "nao_existe"}])
    with pytest.raises(ValueError, match="progressao desconhecida"):
        synthesize_track(bpm=120.0, sections=[{"bars": 4, "progression": "nao_existe"}])


def test_degenerate_specs_are_rejected():
    with pytest.raises(ValueError):
        synthesize_track(bpm=120.0, sections=[])
    with pytest.raises(ValueError):
        synthesize_track(bpm=120.0, sections=[{"bars": 0}])
    with pytest.raises(ValueError):
        synthesize_track(bpm=120.0)  # nem bars nem sections


# ------------------------------------------------------ invariantes de dados


def test_stages_sharing_a_track_declare_the_same_synth_spec():
    """Varias fases apontam pro MESMO .wav (a tese multi-modo: o mesmo
    tempo extraido vira jogos diferentes). Como a faixa e sintetizada
    sob demanda pela PRIMEIRA fase que a pedir, specs divergentes pro
    mesmo caminho fariam a faixa depender de qual fase o jogador abrir
    primeiro -- um bug nao-deterministico e quase impossivel de rastrear.
    """
    by_track = {}
    for stage in load_stages("data/stages/stages.json"):
        if not stage.track_path or stage.synth is None:
            continue
        by_track.setdefault(stage.track_path, []).append((stage.stage_id, stage.synth))

    for track_path, entries in by_track.items():
        reference_id, reference = entries[0]
        for stage_id, spec in entries[1:]:
            assert spec == reference, (
                f"{stage_id} e {reference_id} compartilham {track_path} com specs diferentes: "
                f"{json.dumps(spec, sort_keys=True)} != {json.dumps(reference, sort_keys=True)}"
            )


def test_tutorial_track_spec_stays_flat():
    """O beatmap do tutorial e AUTORAL, com timestamps escritos a mao
    contra esta faixa. Dar estrutura a ela moveria os instantes em que ha
    bateria audivel e as ameacas didaticas passariam a cair no silencio --
    sem nenhum teste de logica falhar. Este e o guarda."""
    tutorial = next(s for s in load_stages("data/stages/stages.json") if s.tutorial_steps)
    assert "sections" not in tutorial.synth
    assert tutorial.synth == {"bpm": 80.0, "bars": 21, "style": "calm"}


def test_every_versioned_beatmap_matches_the_audio_it_came_from():
    """O guarda contra a falha mais traicoeira deste projeto: `.wav` nao e
    versionado, `beatmap.json` e. Mudar a sintese sem regenerar os
    beatmaps deixa o jogo FORA DO TEMPO da musica, e nada quebra -- nenhum
    JSON fica invalido, nenhuma invariante de jogabilidade estoura, o jogo
    so passa a pedir tiros onde nao ha batida.

    `ensure_track` re-sintetiza deterministicamente se o .wav nao existir
    (clone novo/CI), entao este teste nao depende de estado de disco.
    """
    stale = []
    for stage in load_stages("data/stages/stages.json"):
        if not stage.track_path or stage.synth is None:
            continue
        with open(stage.beatmap_path, encoding="utf-8") as f:
            beatmap = json.load(f)
        recorded = beatmap.get("track_fingerprint")
        assert recorded, (
            f"{stage.stage_id}: beatmap sem `track_fingerprint` -- rode "
            f"`python tools/generate_stage_assets.py`"
        )
        ensure_track(stage.track_path, stage.synth)
        actual = wav_fingerprint(stage.track_path)
        if recorded != actual:
            stale.append(f"{stage.stage_id} ({stage.beatmap_path}): {recorded} != {actual}")

    assert not stale, (
        "beatmap(s) extraidos de um audio que nao existe mais -- a faixa foi "
        "re-sintetizada com outra especificacao ou outra matematica de synth. "
        "Rode `python tools/generate_stage_assets.py --force` (requer librosa): "
        + "; ".join(stale)
    )
