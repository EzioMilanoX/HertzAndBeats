"""Meta-Jogo -- Announcer: stinger sintetizado (nao fala real) em marcos de combo e Rank."""
import math

import pytest

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from hertzbeats.audio.sfx_synth import SFX_ANNOUNCER_COMBO, SFX_ANNOUNCER_RANK
from hertzbeats.bootstrap.hertz_game_loop import (
    ANNOUNCER_COMBO_THRESHOLD,
    FLOW_HUB,
    FLOW_RESULTS,
    HertzGameLoop,
)
from hertzbeats.stages import StageDef

from tests.conftest import make_config, write_beatmap

DT = 0.016


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": timestamp, "threat_type": "rhythm_threat_basic", "lane": lane, "strength": 0.5}


@pytest.fixture
def flow_game(tmp_path, null_input):
    def _make(stage_threat_lists, overrides_list=None):
        stages = []
        beatmap_path = None
        for i, threats in enumerate(stage_threat_lists):
            beatmap_path = write_beatmap(tmp_path / f"stage{i}.beatmap.json", threats)
            overrides = overrides_list[i] if overrides_list else {}
            stages.append(
                StageDef(
                    stage_id=f"stage{i}", name=f"FASE {i}", subtitle="",
                    track_path=str(tmp_path / f"stage{i}.wav"), beatmap_path=str(beatmap_path),
                    synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides=overrides,
                )
            )
        audio_engine = NullAudioEngine()
        clock = audio_engine.get_clock()
        loop = HertzGameLoop(
            base_config=make_config(beatmap_path), stages=tuple(stages), renderer=NullRenderer(),
            input_provider=null_input, audio_engine=audio_engine, audio_clock=clock,
            player_progress_path=str(tmp_path / "player_progress.json"),
            player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
            user_settings_path=str(tmp_path / "user_settings.json"),
        )
        return loop, clock, audio_engine

    return _make


def _press(loop, null_input, action: str) -> None:
    null_input.set_action_held(action, True)
    null_input.poll()
    loop.advance_frame(DT)
    null_input.set_action_held(action, False)
    null_input.poll()


def _start(loop, null_input) -> None:
    _press(loop, null_input, "confirm")  # TITLE -> HUB
    _press(loop, null_input, "confirm")  # HUB -> CAROUSEL (campaign, cursor 0)
    _press(loop, null_input, "confirm")  # CAROUSEL -> PREFLIGHT
    _press(loop, null_input, "confirm")  # PREFLIGHT curada -> START


# -- Marco de combo -------------------------------------------------------


def test_combo_announcer_fires_when_crossing_the_threshold(flow_game, null_input):
    loop, clock, audio_engine = flow_game([[_basic(3.0)]])
    _start(loop, null_input)

    loop.composed.game_state.combo_count = ANNOUNCER_COMBO_THRESHOLD
    loop._sync_announcer()
    assert any(sound_id == SFX_ANNOUNCER_COMBO for sound_id, _ in audio_engine._one_shots_played)


def test_combo_announcer_does_not_fire_below_the_threshold(flow_game, null_input):
    loop, clock, audio_engine = flow_game([[_basic(3.0)]])
    _start(loop, null_input)

    loop.composed.game_state.combo_count = ANNOUNCER_COMBO_THRESHOLD - 1
    loop._sync_announcer()
    assert audio_engine._one_shots_played == []


def test_combo_announcer_never_refires_within_the_same_tier(flow_game, null_input):
    loop, clock, audio_engine = flow_game([[_basic(3.0)]])
    _start(loop, null_input)

    loop.composed.game_state.combo_count = ANNOUNCER_COMBO_THRESHOLD
    loop._sync_announcer()
    loop.composed.game_state.combo_count = ANNOUNCER_COMBO_THRESHOLD + 5
    loop._sync_announcer()
    count = sum(1 for sound_id, _ in audio_engine._one_shots_played if sound_id == SFX_ANNOUNCER_COMBO)
    assert count == 1


def test_combo_announcer_fires_again_at_the_next_tier(flow_game, null_input):
    loop, clock, audio_engine = flow_game([[_basic(3.0)]])
    _start(loop, null_input)

    loop.composed.game_state.combo_count = ANNOUNCER_COMBO_THRESHOLD
    loop._sync_announcer()
    loop.composed.game_state.combo_count = ANNOUNCER_COMBO_THRESHOLD * 2
    loop._sync_announcer()
    count = sum(1 for sound_id, _ in audio_engine._one_shots_played if sound_id == SFX_ANNOUNCER_COMBO)
    assert count == 2


def test_combo_announcer_is_silent_outside_playing(flow_game, null_input):
    loop, clock, audio_engine = flow_game([[_basic(3.0)]])
    # ainda em FLOW_TITLE, nunca entrou em PLAYING
    loop._sync_announcer()
    assert audio_engine._one_shots_played == []


def test_combo_announcer_tier_resets_on_a_fresh_stage(flow_game, null_input):
    loop, clock, audio_engine = flow_game([[_basic(3.0)], [_basic(3.0)]], overrides_list=[{}, {}])
    _start(loop, null_input)
    loop.composed.game_state.combo_count = ANNOUNCER_COMBO_THRESHOLD
    loop._sync_announcer()
    assert loop._last_announcer_combo_tier == 1

    loop.start_stage(1)
    assert loop._last_announcer_combo_tier == 0


# -- Rank nos Resultados ----------------------------------------------------


def test_rank_ss_clear_triggers_the_rank_stinger(flow_game, null_input):
    loop, clock, audio_engine = flow_game([[_basic(3.0, lane=0)]])
    _start(loop, null_input)

    null_input.set_axis("aim_x", math.cos(0.0))
    null_input.set_axis("aim_y", math.sin(0.0))
    clock.set_now_seconds(3.0)
    _press(loop, null_input, "fire")
    for _ in range(80):
        clock.advance(DT)
        loop.advance_frame(DT)
        if loop.flow == FLOW_RESULTS:
            break
    assert loop.flow == FLOW_RESULTS
    assert loop._results_rank == "SS"
    assert any(sound_id == SFX_ANNOUNCER_RANK for sound_id, _ in audio_engine._one_shots_played)


def test_a_low_rank_clear_never_triggers_the_rank_stinger(flow_game, null_input):
    loop, clock, audio_engine = flow_game([[_basic(3.0)]])
    _start(loop, null_input)

    # sem atirar: a ameaca vence, MISS -- rank bem abaixo de S
    for _ in range(240):
        clock.advance(DT)
        loop.advance_frame(DT)
        if loop.flow in (FLOW_RESULTS, FLOW_HUB):
            break
        if loop.composed.game_state.health <= 0:
            break
    assert loop._results_rank not in ("S", "SS")
    assert not any(sound_id == SFX_ANNOUNCER_RANK for sound_id, _ in audio_engine._one_shots_played)
