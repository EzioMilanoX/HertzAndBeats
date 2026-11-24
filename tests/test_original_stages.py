"""As 3 fases com MUSICA ORIGINAL (campanha `trilhas_originais`).

O que se prova aqui, alem das invariantes que ja valem para toda fase
(`test_playability_invariants`, `test_beat_alignment`,
`test_track_sections`):

- as fases carregam e COMPOEM o jogo de verdade (mesma `compose_world`);
- o `beatmap.json` versionado e exatamente a compilacao do chart
  autoral em `charts/` (fonte e saida nao divergiram);
- toda nota cai NA GRADE e em cima de um golpe de bateria real da
  musica -- tolerancia de 1 ms, nao de janela de julgamento: o chart e
  escrito em `compasso:batida` sobre o BPM exato da sintese;
- a musica e deterministica, a verdade fundamental confere com o audio,
  e stems/escala de tempo funcionam como nas faixas historicas.
"""
import json

import numpy as np
import pytest
from ouroboros.interfaces.null.null_audio_clock import NullAudioClock
from ouroboros.interfaces.null.null_input_provider import NullInputProvider

from hertzbeats.audio import original_songs
from hertzbeats.audio.demo_track_synth import (
    STEMS,
    percussive_onset_times,
    section_time_windows,
    synthesize_from_spec,
    total_bars,
)
from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.config import HertzConfig
from hertzbeats.offline.beatmap_assist import _max_lane_step
from hertzbeats.offline.beatmap_dsl import compile_beatmap_source
from hertzbeats.rate_scaling import scaled_synth_spec
from hertzbeats.stages import load_stages, read_stage_bpm_and_duration, resolve_stage_config

CAMPAIGN = "trilhas_originais"
EXPECTED = ("original_1_mare_lenta", "original_2_contratempo", "original_3_hiperpulso")


def _stages():
    return [s for s in load_stages("data/stages/stages.json") if s.campaign_id == CAMPAIGN]


def _beatmap(stage):
    with open(stage.beatmap_path, encoding="utf-8") as f:
        return json.load(f)


def _ids(stages):
    return [s.stage_id for s in stages]


STAGES = _stages()


def test_campaign_has_the_three_stages_in_order():
    """Ordem = progressao (lenta -> sincopada -> rapida), e todas tocam
    musica original."""
    assert tuple(s.stage_id for s in STAGES) == EXPECTED
    bpms = [s.synth["bpm"] for s in STAGES]
    assert bpms == sorted(bpms) and len(set(bpms)) == 3
    assert {s.synth["song"] for s in STAGES} == set(original_songs.SONGS)
    assert all(not s.selectable_mode and s.description for s in STAGES)


def test_difficulty_curve_tightens_across_the_campaign():
    base = HertzConfig.from_json("data/config/hertz_beats.config.json")
    configs = [resolve_stage_config(base, s) for s in STAGES]
    approach = [c.approach_seconds for c in configs]
    perfect = [c.perfect_window_seconds for c in configs]
    assert approach == sorted(approach, reverse=True)
    assert perfect == sorted(perfect, reverse=True)
    densities = []
    for stage in STAGES:
        times = [t["timestamp_seconds"] for t in _beatmap(stage)["threats"]]
        densities.append(len(times) / (times[-1] - times[0]))
    assert densities == sorted(densities), densities


@pytest.mark.parametrize("stage", STAGES, ids=_ids(STAGES))
def test_stage_composes_the_real_game(stage):
    base = HertzConfig.from_json("data/config/hertz_beats.config.json")
    config = resolve_stage_config(base, stage)
    clock = NullAudioClock()
    clock.set_playing(True)
    composed = compose_world(config, NullInputProvider(), clock)
    beatmap = _beatmap(stage)
    expected = np.array([t["timestamp_seconds"] for t in beatmap["threats"]])
    np.testing.assert_allclose(np.sort(np.asarray(composed.hit_times)), expected, atol=1e-9)
    bpm, duration = read_stage_bpm_and_duration(stage)
    assert bpm == stage.synth["bpm"]
    assert duration == pytest.approx(total_bars(stage.synth) * 240.0 / stage.synth["bpm"])


@pytest.mark.parametrize("stage", STAGES, ids=_ids(STAGES))
def test_versioned_beatmap_is_the_compiled_authored_chart(stage):
    source = stage.beatmap_params["authored_source"]
    with open(source, encoding="utf-8") as f:
        compiled = compile_beatmap_source(f.read(), track_id=stage.stage_id)
    beatmap = _beatmap(stage)
    assert beatmap["authored_source"] == source
    assert beatmap["bpm"] == stage.synth["bpm"]
    assert [t for t in beatmap["threats"]] == compiled["threats"], (
        f"{stage.beatmap_path} divergiu de {source} -- rode "
        f"`python tools/generate_stage_assets.py --apenas-autorais`"
    )


@pytest.mark.parametrize("stage", STAGES, ids=_ids(STAGES))
def test_every_note_is_on_the_grid_and_on_a_drum_hit(stage):
    times = np.array([t["timestamp_seconds"] for t in _beatmap(stage)["threats"]])
    sixteenth = 60.0 / stage.synth["bpm"] / 4.0
    off_grid = np.abs(times / sixteenth - np.round(times / sixteenth)) * sixteenth
    assert off_grid.max() < 1e-6

    truth = percussive_onset_times(stage.synth)
    index = np.searchsorted(truth, times).clip(1, truth.shape[0] - 1)
    error = np.minimum(np.abs(times - truth[index - 1]), np.abs(times - truth[index]))
    misses = [f"{t:.3f}s" for t, e in zip(times, error) if e > 0.001]
    assert not misses, f"{stage.stage_id}: nota(s) sem golpe de bateria: {misses}"


@pytest.mark.parametrize("stage", STAGES, ids=_ids(STAGES))
def test_lanes_never_ask_for_an_unfair_sweep(stage):
    """Revisao a mao das lanes: nunca mais setores do que o tempo permite."""
    threats = _beatmap(stage)["threats"]
    for previous, current in zip(threats, threats[1:]):
        gap = current["timestamp_seconds"] - previous["timestamp_seconds"]
        step = min((current["lane"] - previous["lane"]) % 8, (previous["lane"] - current["lane"]) % 8)
        assert step <= _max_lane_step(gap), (stage.stage_id, previous, current)


def test_section_names_are_unique_for_section_practice():
    for stage in STAGES:
        names = [name for name, *_ in section_time_windows(stage.synth)]
        assert len(names) == len(set(names)), stage.stage_id


# ------------------------------------------------------------ a musica


SHORT = {
    "bpm": 112.0,
    "song": "contratempo",
    "sections": [{"name": "verso", "bars": 2}, {"name": "refrao", "bars": 2, "lead": True}],
}


def test_synthesis_is_deterministic():
    assert np.array_equal(synthesize_from_spec(SHORT), synthesize_from_spec(SHORT))


def test_hash_noise_is_reproducible_and_white():
    noise = original_songs._hash_noise(4096, 7)
    assert np.array_equal(noise, original_songs._hash_noise(4096, 7))
    assert -1.0 <= noise.min() and noise.max() < 1.0
    assert abs(float(noise.mean())) < 0.05
    assert not np.array_equal(noise, original_songs._hash_noise(4096, 8))


def test_stems_sum_to_the_full_mix():
    full = synthesize_from_spec(SHORT)
    parts = [synthesize_from_spec(SHORT, stem=stem) for stem in STEMS]
    assert np.max(np.abs(parts[0] + parts[1] - full)) < 1e-9
    assert np.max(np.abs(parts[1])) > 0.01  # o lead existe no refrao


@pytest.mark.parametrize("song", sorted(original_songs.SONGS))
def test_ground_truth_matches_the_synthesized_audio(song):
    """Cada golpe que a verdade fundamental aponta tem transiente no audio:
    se a partitura "seca" divergir da renderizada, os testes de
    alinhamento passariam medindo nada."""
    stage = next(s for s in STAGES if s.synth["song"] == song)
    samples = synthesize_from_spec(stage.synth)
    rate = original_songs.SAMPLE_RATE
    onsets = percussive_onset_times(stage.synth)
    assert onsets.shape[0] >= 40
    weak = 0
    for onset in onsets:
        start = int(onset * rate)
        before = samples[max(0, start - 900) : max(1, start - 150)]
        after = samples[start : start + 900]
        if np.max(np.abs(after)) <= np.max(np.abs(before)) * 1.05:
            weak += 1
    assert weak <= 0.05 * onsets.shape[0], f"{song}: {weak} golpes sem transiente"


def test_rate_scaling_stretches_an_original_song():
    slow = synthesize_from_spec(scaled_synth_spec(SHORT, 0.75))
    normal = synthesize_from_spec(SHORT)
    assert slow.shape[0] == pytest.approx(normal.shape[0] / 0.75, rel=1e-3)


@pytest.mark.parametrize(
    "spec, message",
    [
        ({"bpm": 100.0, "song": "nao_existe", "sections": [{"name": "a", "bars": 1}]}, "musica"),
        ({"bpm": 100.0, "song": "contratempo", "sections": [{"name": "solo", "bars": 1}]}, "parte"),
        ({"bpm": 100.0, "song": "contratempo", "sections": [{"name": "verso", "bars": 1, "estilo": 1}]}, "chave"),
        ({"bpm": 100.0, "song": "contratempo", "sections": [{"name": "verso", "bars": 0}]}, "bars"),
        ({"bpm": 100.0, "song": "contratempo"}, "sections"),
    ],
)
def test_invalid_song_specs_fail_loudly(spec, message):
    with pytest.raises(ValueError, match=message):
        synthesize_from_spec(spec)


def test_curation_keys_are_accepted_in_a_song_section():
    spec = {"bpm": 112.0, "song": "contratempo", "sections": [{"name": "verso", "bars": 1, "min_gap_seconds": 0.4}]}
    assert synthesize_from_spec(spec).shape[0] > 0
