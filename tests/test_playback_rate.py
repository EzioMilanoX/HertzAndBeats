"""Escala de Tempo (acessibilidade): tocar a fase mais devagar.

A alavanca de acessibilidade mais usada do genero, e aqui ela e' exata em
vez de aproximada: as faixas curadas sao SINTETIZADAS, entao desacelerar
e' pedir a mesma especificacao com outro BPM -- nenhum resampling, nenhum
artefato. O que estes testes protegem e' a fronteira do que escala e do
que NAO escala: instantes do beatmap escalam, tempo de relogio (voo da
ameaca, janela de julgamento) nao.
"""
import dataclasses

import numpy as np
import pytest

from hertzbeats.audio.demo_track_synth import total_bars
from hertzbeats.rate_scaling import (
    MAX_PLAYBACK_RATE,
    MIN_PLAYBACK_RATE,
    clamp_rate,
    is_scaled,
    rate_variant_track_path,
    scale_schedule_for_rate,
    scaled_synth_spec,
)
from hertzbeats.stages import load_stages, resolve_stage_config
from hertzbeats.config import HertzConfig

SPEC = {
    "bpm": 150.0,
    "sections": [
        {"name": "intro", "bars": 4},
        {"name": "ponte", "bars": 4, "min_gap_seconds": 0.7},
        {"name": "climax", "bars": 12},
    ],
}


def test_rate_one_changes_nothing():
    """Precisa ser um no-op exato: e' o caminho de toda partida normal."""
    assert not is_scaled(1.0)
    assert scaled_synth_spec(SPEC, 1.0) is SPEC
    assert rate_variant_track_path("data/tracks/x.wav", 1.0) == "data/tracks/x.wav"


def test_near_one_rate_is_treated_as_unscaled():
    """A taxa vem de JSON/CLI: `0.9999999` nao deve gerar uma faixa nova
    inteira em disco."""
    assert not is_scaled(0.9999999)


def test_scaled_spec_keeps_the_musical_structure():
    """So o BPM muda. As secoes sobrevivem intactas -- a ponte segue sendo
    4 compassos de respiro, so mais longos. Se as secoes mudassem, a
    estrutura (e o arco de dificuldade) se perderia na desaceleracao."""
    scaled = scaled_synth_spec(SPEC, 0.75)
    assert scaled["bpm"] == pytest.approx(112.5)
    assert scaled["sections"] == SPEC["sections"]
    assert total_bars(scaled) == total_bars(SPEC)


def test_scaled_spec_does_not_mutate_the_original():
    """A spec vem de `stages.json` carregado uma vez e compartilhado por
    varias fases -- mutar aqui contaminaria as outras."""
    before = dict(SPEC)
    scaled_synth_spec(SPEC, 0.5)
    assert SPEC == before
    assert scaled_synth_spec(SPEC, 0.5) is not SPEC


def test_duration_scales_by_the_inverse_of_the_rate():
    def duration(spec):
        return total_bars(spec) * 4 * (60.0 / spec["bpm"])

    assert duration(scaled_synth_spec(SPEC, 0.75)) == pytest.approx(duration(SPEC) / 0.75)


def test_variant_path_is_a_separate_file_per_rate():
    """Nunca sobrescrever a faixa a 1.0x: as taxas coexistem, e alternar a
    taxa nao paga re-sintese de novo a cada troca."""
    assert rate_variant_track_path("data/tracks/x.wav", 0.75).endswith("x@0.75.wav")
    assert rate_variant_track_path("data/tracks/x.wav", 0.5).endswith("x@0.50.wav")
    assert rate_variant_track_path("data/tracks/x.wav", 0.75) != "data/tracks/x.wav"


def test_rate_is_clamped_to_slowing_down_only():
    """Teto 1.0: acelerar nao e' acessibilidade, e quebraria o
    balanceamento (as janelas de julgamento nao escalam)."""
    assert clamp_rate(2.0) == MAX_PLAYBACK_RATE == 1.0
    assert clamp_rate(0.1) == MIN_PLAYBACK_RATE
    assert clamp_rate(0.75) == 0.75


# ---------------------------------------------------------------- schedule


def _schedule(*times):
    scheduled = np.zeros(len(times), dtype=[("timestamp_seconds", np.float64)])
    scheduled["timestamp_seconds"] = times
    return scheduled, np.array(times, dtype=np.float64)


def test_schedule_stretches_by_the_inverse_of_the_rate():
    """Dividir, nao multiplicar: a 0.75x a musica dura 1.33x mais, entao
    cada batida chega 1.33x mais TARDE."""
    scheduled, hit_times = _schedule(3.0, 6.0)
    scaled_schedule, scaled_hits = scale_schedule_for_rate(scheduled, hit_times, 0.75)
    assert scaled_schedule["timestamp_seconds"].tolist() == pytest.approx([4.0, 8.0])
    assert scaled_hits.tolist() == pytest.approx([4.0, 8.0])


def test_schedule_scaling_returns_copies():
    """Mesmo contrato de `practice_thinning`: o beatmap.json versionado (e
    os arrays recem-carregados dele) nunca sao alterados no lugar."""
    scheduled, hit_times = _schedule(3.0)
    scaled_schedule, scaled_hits = scale_schedule_for_rate(scheduled, hit_times, 0.5)
    assert scaled_schedule is not scheduled and scaled_hits is not hit_times
    assert scheduled["timestamp_seconds"].tolist() == [3.0]  # original intacto


def test_unscaled_schedule_still_returns_copies():
    scheduled, hit_times = _schedule(3.0)
    scaled_schedule, scaled_hits = scale_schedule_for_rate(scheduled, hit_times, 1.0)
    assert scaled_schedule is not scheduled and scaled_hits is not hit_times


def test_relative_spacing_grows_so_the_stage_gets_easier():
    """O efeito de acessibilidade, medido: as notas se afastam em segundos
    de relogio, enquanto a janela de julgamento (que NAO escala) continua
    do mesmo tamanho."""
    scheduled, hit_times = _schedule(3.0, 3.4)
    _, scaled_hits = scale_schedule_for_rate(scheduled, hit_times, 0.5)
    assert (scaled_hits[1] - scaled_hits[0]) > (hit_times[1] - hit_times[0])


# ------------------------------------------------------- integracao na fase


def test_stage_config_points_at_the_variant_track():
    base = dataclasses.replace(
        HertzConfig.from_json("data/config/hertz_beats.config.json"), playback_rate=0.75
    )
    stage = next(s for s in load_stages("data/stages/stages.json") if s.synth is not None)
    assert "@0.75" in resolve_stage_config(base, stage).track_path


def test_player_music_ignores_the_rate():
    """Musica do jogador nao tem `synth` spec pra re-sintetizar, e
    resamplear um mp3 seria outra feature -- a taxa e ignorada em vez de
    apontar pra um arquivo que nunca vai existir."""
    base = dataclasses.replace(
        HertzConfig.from_json("data/config/hertz_beats.config.json"), playback_rate=0.75
    )
    stage = next(s for s in load_stages("data/stages/stages.json") if s.synth is not None)
    user_song = dataclasses.replace(stage, synth=None, track_path="musicas/minha.mp3")
    assert resolve_stage_config(base, user_song).track_path == "musicas/minha.mp3"
