"""Crossfading Vocal: stems de verdade, e o que era esqueleto passa a mudar audio.

Estava documentado como impossivel: "`pygame.mixer.music` e streaming de
canal unico, sem EQ/filtro -- a implementacao de verdade exige uma 2a
camada de audio, que ainda nao existe". A conclusao estava certa, a
premissa nao: nao existe stem numa GRAVACAO, mas estas faixas sao
SINTETIZADAS, e renderizar so a bateria+baixo (ou so a melodia) e' pular
camadas no mesmo laco -- nenhuma separacao de fontes envolvida.

A propriedade que sustenta todo o desenho e a primeira testada aqui:
`instrumental + lead == mixagem completa`. Sem ela, os dois canais tocando
juntos nao soariam como a faixa original.
"""
import numpy as np
import pytest

from hertzbeats.audio.demo_track_synth import (
    STEM_INSTRUMENTAL,
    STEM_LEAD,
    STEMS,
    ensure_stem_tracks,
    stem_track_path,
    synthesize_track,
)

SECTIONS = [
    {"name": "sem_lead", "bars": 4, "style": "standard", "progression": "base"},
    {"name": "com_lead", "bars": 4, "style": "intense", "progression": "lift", "lead": True},
]
BPM = 128.0


@pytest.fixture(scope="module")
def rendered():
    return {
        "full": synthesize_track(bpm=BPM, sections=SECTIONS),
        STEM_INSTRUMENTAL: synthesize_track(bpm=BPM, sections=SECTIONS, stem=STEM_INSTRUMENTAL),
        STEM_LEAD: synthesize_track(bpm=BPM, sections=SECTIONS, stem=STEM_LEAD),
    }


def test_stems_sum_back_to_the_full_mix(rendered):
    """A propriedade central. Ela so vale porque os dois stems dividem a
    normalizacao da mixagem COMPLETA -- normalizado cada um pelo proprio
    pico, o lead sairia altissimo e a soma estouraria. Tolerancia de ponto
    flutuante (a ordem das somas difere), nao de aproximacao musical."""
    recombined = rendered[STEM_INSTRUMENTAL] + rendered[STEM_LEAD]
    assert np.allclose(recombined, rendered["full"], atol=1e-12)


def test_stems_have_the_same_length_as_the_full_mix(rendered):
    """Precisam ser sample-a-sample alinhados: tocam em canais separados,
    e um stem mais curto derivaria a melodia do instrumental."""
    assert rendered[STEM_INSTRUMENTAL].shape == rendered["full"].shape
    assert rendered[STEM_LEAD].shape == rendered["full"].shape


def test_lead_stem_is_silent_where_no_section_has_lead(rendered):
    """A 1a secao (4 de 8 compassos) nao tem `lead`: a metade inicial do
    stem vocal tem de ser silencio absoluto."""
    half = rendered[STEM_LEAD].shape[0] // 2
    assert np.max(np.abs(rendered[STEM_LEAD][:half])) == 0.0
    assert np.max(np.abs(rendered[STEM_LEAD][half:])) > 0.0


def test_instrumental_carries_the_drums_and_the_lead_does_not(rendered):
    """O instrumental precisa ser a faixa jogavel por si (a IA offline
    extrai o ritmo dele), e o vocal precisa NAO ter bateria -- senao
    abafar a voz abafaria o groove junto."""
    assert np.max(np.abs(rendered[STEM_INSTRUMENTAL])) > 0.5  # bumbo/crash
    assert np.max(np.abs(rendered[STEM_LEAD])) < 0.5


def test_unknown_stem_is_rejected():
    with pytest.raises(ValueError, match="stem desconhecido"):
        synthesize_track(bpm=BPM, sections=SECTIONS, stem="vocais")
    with pytest.raises(ValueError, match="stem desconhecido"):
        stem_track_path("data/tracks/x.wav", "vocais")


def test_stem_paths_are_separate_files():
    assert stem_track_path("data/tracks/x.wav", STEM_LEAD).endswith("x@lead.wav")
    assert stem_track_path("data/tracks/x.wav", STEM_INSTRUMENTAL).endswith("x@instrumental.wav")
    assert len({stem_track_path("data/tracks/x.wav", s) for s in STEMS}) == 2


# ------------------------------------------------------ quando NAO ha stems


def test_no_stems_without_a_synth_spec():
    """Musica do jogador: separar stems de um mp3 seria separacao de
    fontes, uma feature inteira a parte."""
    assert ensure_stem_tracks("musicas/minha.mp3", None) is None


def test_no_stems_when_no_section_has_a_lead():
    """Sem melodia nao ha o que abafar -- um stem vocal silencioso so
    gastaria disco e um canal de mixer."""
    assert ensure_stem_tracks("data/tracks/x.wav", {"bpm": 128.0, "bars": 8, "style": "standard"}) is None
    only_backing = {"bpm": 128.0, "sections": [{"name": "a", "bars": 4, "style": "standard"}]}
    assert ensure_stem_tracks("data/tracks/x.wav", only_backing) is None


# ------------------------------------------------------------ motor de audio


def test_muffle_without_a_loaded_stem_only_records_intent():
    """Contrato preservado do esqueleto: a chamada nunca falha por falta
    de stem, so nao muda audio."""
    from hertzbeats.adapters.hb_pygame_audio_engine import HBPygameAudioEngine

    engine = HBPygameAudioEngine()
    assert engine.has_vocal_layer is False
    engine.muffle_vocals(True)
    assert engine.vocals_muffled is True
    engine.muffle_vocals(False)
    assert engine.vocals_muffled is False


def test_muffled_volume_is_quiet_but_not_silent():
    """Zerar a voz soa como bug de audio; abafada soa como punicao."""
    from hertzbeats.adapters.hb_pygame_audio_engine import HBPygameAudioEngine

    assert 0.0 < HBPygameAudioEngine.VOCAL_MUFFLED_VOLUME < 0.5


def test_muffle_follows_the_combo(compose, null_clock, null_input):
    """O gatilho reusa `combo_count` em vez de um temporizador de erro
    proprio: o combo JA e' "errei desde a ultima nota certa", entao a voz
    volta no primeiro acerto sem nenhum estado extra."""

    class FakeEngine:
        def __init__(self):
            self.has_vocal_layer = True
            self.muffled = None

        def muffle_vocals(self, muffled):
            self.muffled = muffled

    from hertzbeats.bootstrap.hertz_game_loop import HertzGameLoop

    composed, _ = compose([{"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_basic",
                            "lane": 0, "strength": 0.5}])
    engine = FakeEngine()
    loop = object.__new__(HertzGameLoop)
    loop._composed = composed
    loop._audio_engine = engine

    composed.game_state.combo_count = 0
    HertzGameLoop._sync_vocal_muffle(loop)
    assert engine.muffled is True

    composed.game_state.combo_count = 7
    HertzGameLoop._sync_vocal_muffle(loop)
    assert engine.muffled is False
