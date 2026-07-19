"""Modo Treino (musicas do jogador): densidade de onsets reduzida + vida infinita, tudo opt-in."""
import dataclasses

import numpy as np
import pytest

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer
from ouroboros.rhythm.runtime.beatmap_loader import BeatmapLoader

from hertzbeats.bootstrap.hertz_game_loop import HertzGameLoop
from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.practice_thinning import thin_schedule_for_practice
from hertzbeats.stages import StageDef

from tests.conftest import make_config, write_beatmap

DT = 0.016


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": timestamp, "threat_type": "rhythm_threat_basic", "lane": lane, "strength": 0.5}


def _heavy(timestamp: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": timestamp, "threat_type": "rhythm_threat_heavy", "lane": lane, "strength": 0.9}


def _load(tmp_path, threats):
    beatmap_path = write_beatmap(tmp_path / "t.beatmap.json", threats)
    scheduled = BeatmapLoader({"rhythm_threat_basic": 0, "rhythm_threat_heavy": 1}).load(beatmap_path)
    return scheduled, scheduled["timestamp_seconds"].copy()


def test_keep_fraction_one_is_a_lossless_copy(tmp_path):
    scheduled, hit_times = _load(tmp_path, [_basic(1.0), _basic(2.0), _basic(3.0)])
    out_scheduled, out_hits = thin_schedule_for_practice(scheduled, hit_times, keep_fraction=1.0)
    assert out_scheduled.shape[0] == 3
    assert list(out_hits) == [1.0, 2.0, 3.0]
    assert out_scheduled is not scheduled  # copia, nao a mesma referencia


def test_keep_fraction_half_keeps_every_other_uniformly(tmp_path):
    threats = [_basic(float(i)) for i in range(1, 9)]  # 8 notas, t=1..8
    scheduled, hit_times = _load(tmp_path, threats)
    out_scheduled, out_hits = thin_schedule_for_practice(scheduled, hit_times, keep_fraction=0.5)
    assert out_scheduled.shape[0] == 4
    assert list(out_hits) == [1.0, 3.0, 5.0, 7.0]  # stride 2, sempre a primeira de cada par


def test_keep_fraction_handles_empty_schedule(tmp_path):
    scheduled, hit_times = _load(tmp_path, [_basic(1.0)])
    empty_scheduled = scheduled[:0]
    empty_hits = hit_times[:0]
    out_scheduled, out_hits = thin_schedule_for_practice(empty_scheduled, empty_hits, keep_fraction=0.5)
    assert out_scheduled.shape[0] == 0
    assert out_hits.shape[0] == 0


def test_practice_mode_thins_the_beatmap_before_any_spawner_sees_it(tmp_path, null_input, null_clock):
    threats = [_basic(3.0 + i * 0.5) for i in range(10)]  # 10 notas
    beatmap_path = write_beatmap(tmp_path / "p.beatmap.json", threats)
    config = dataclasses.replace(
        make_config(beatmap_path), practice_mode=True, practice_density_keep_fraction=0.5
    )
    composed = compose_world(config, null_input, null_clock)
    assert composed.spawner_system._scheduled_threats.shape[0] == 5  # metade


def test_practice_mode_does_not_touch_the_beatmap_when_disabled(tmp_path, null_input, null_clock):
    threats = [_basic(3.0 + i * 0.5) for i in range(10)]
    beatmap_path = write_beatmap(tmp_path / "p.beatmap.json", threats)
    composed = compose_world(make_config(beatmap_path), null_input, null_clock)
    assert composed.spawner_system._scheduled_threats.shape[0] == 10


def test_practice_mode_suppresses_health_damage_in_defender(tmp_path, null_input, null_clock):
    beatmap_path = write_beatmap(tmp_path / "d.beatmap.json", [_basic(3.0, lane=0)])
    config = dataclasses.replace(make_config(beatmap_path), practice_mode=True)
    composed = compose_world(config, null_input, null_clock)
    state = composed.game_state
    state.combo_count = 5

    null_clock.set_now_seconds(3.2)  # passou da janela de miss -> atinge o nucleo
    null_input.poll()
    composed.world.step(0.016)

    assert state.miss_count == 1  # o veredito continua contando
    assert state.combo_count == 0  # combo ainda quebra
    assert state.health == config.max_health  # so a VIDA e poupada


def test_practice_mode_suppresses_health_damage_in_survival(tmp_path, null_input, null_clock):
    beatmap_path = write_beatmap(tmp_path / "s.beatmap.json", [_heavy(3.0, lane=0)])
    config = dataclasses.replace(make_config(beatmap_path), practice_mode=True, game_mode="survival")
    composed = compose_world(config, null_input, null_clock)
    state = composed.game_state

    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.0)
    null_clock.set_now_seconds(3.0)  # onset: parede pesada centralizada toca o jogador
    composed.world.step(0.016)

    assert state.miss_count == 1
    assert state.health == config.max_health


@pytest.fixture
def selectable_loop(tmp_path, null_input):
    beatmap_path = write_beatmap(tmp_path / "u.beatmap.json", [_basic(99.0)])
    stage = StageDef(
        stage_id="user_song", name="MUSICA", subtitle="sua musica", track_path=str(tmp_path / "u.wav"),
        beatmap_path=str(beatmap_path), synth={"bpm": 120.0, "bars": 1}, beatmap_params={},
        overrides={}, selectable_mode=True,
    )
    audio_engine = NullAudioEngine()
    loop = HertzGameLoop(
        base_config=make_config(beatmap_path), stages=(stage,), renderer=NullRenderer(),
        input_provider=null_input, audio_engine=audio_engine, audio_clock=audio_engine.get_clock(),
    )
    return loop


def _press(loop, null_input, action: str) -> None:
    null_input.set_action_held(action, True)
    null_input.poll()
    loop.advance_frame(DT)
    null_input.set_action_held(action, False)
    null_input.poll()


def test_toggling_practice_mode_in_the_menu_carries_into_the_composed_stage(selectable_loop, null_input):
    assert selectable_loop.practice_mode_on(0) is False
    _press(selectable_loop, null_input, "toggle_practice")
    assert selectable_loop.practice_mode_on(0) is True

    _press(selectable_loop, null_input, "confirm")
    assert selectable_loop.flow == "playing"
    assert selectable_loop._stage_config.practice_mode is True


def test_toggling_practice_mode_off_again_restores_normal_config(selectable_loop, null_input):
    _press(selectable_loop, null_input, "toggle_practice")
    _press(selectable_loop, null_input, "toggle_practice")
    assert selectable_loop.practice_mode_on(0) is False

    _press(selectable_loop, null_input, "confirm")
    assert selectable_loop._stage_config.practice_mode is False
