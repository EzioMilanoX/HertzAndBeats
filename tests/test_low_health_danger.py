"""Juice Visual -- Danger Visual: aberracao cromatica ligada exatamente com 1 de vida (Roleta Russa e afins)."""
import dataclasses

import pytest

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.bootstrap.hertz_game_loop import FLOW_PAUSED, FLOW_PLAYING, HertzGameLoop
from hertzbeats.stages import StageDef

from tests.conftest import make_config, write_beatmap


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": timestamp, "threat_type": "rhythm_threat_basic", "lane": lane, "strength": 0.5}


class _FakeDangerRenderer(NullRenderer):
    """NullRenderer + `set_low_health_danger`, pra testar
    `HertzGameLoop._sync_low_health_danger` sem pygame real."""

    def __init__(self) -> None:
        super().__init__()
        self.danger_calls = []

    def set_low_health_danger(self, active: bool) -> None:
        self.danger_calls.append(bool(active))


@pytest.fixture
def danger_game(tmp_path, null_input):
    beatmap_path = write_beatmap(tmp_path / "danger.beatmap.json", [_basic(3.0, lane=0)])
    config = dataclasses.replace(make_config(beatmap_path), max_health=3)
    stage = StageDef(
        stage_id="danger_stage", name="DANGER", subtitle="",
        track_path=str(tmp_path / "danger.wav"), beatmap_path=str(beatmap_path),
        synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
    )
    audio_engine = NullAudioEngine()
    clock = audio_engine.get_clock()
    clock.set_playing(True)
    renderer = _FakeDangerRenderer()
    loop = HertzGameLoop(
        base_config=config, stages=(stage,), renderer=renderer,
        input_provider=null_input, audio_engine=audio_engine, audio_clock=clock,
        player_progress_path=str(tmp_path / "player_progress.json"),
        player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
        user_settings_path=str(tmp_path / "user_settings.json"),
    )
    return loop, renderer


def test_danger_is_off_at_full_health(danger_game):
    loop, renderer = danger_game
    loop.start_stage(0)
    loop._sync_low_health_danger()
    assert renderer.danger_calls[-1] is False


def test_danger_turns_on_at_exactly_1_hp(danger_game):
    loop, renderer = danger_game
    loop.start_stage(0)
    loop.composed.game_state.health = 1
    loop._sync_low_health_danger()
    assert renderer.danger_calls[-1] is True


def test_danger_stays_off_with_2_or_more_hp(danger_game):
    loop, renderer = danger_game
    loop.start_stage(0)
    loop.composed.game_state.health = 2
    loop._sync_low_health_danger()
    assert renderer.danger_calls[-1] is False


def test_danger_turns_off_once_health_reaches_0(danger_game):
    loop, renderer = danger_game
    loop.start_stage(0)
    loop.composed.game_state.health = 0
    loop._sync_low_health_danger()
    assert renderer.danger_calls[-1] is False


def test_danger_is_off_outside_playing_even_at_1_hp(danger_game):
    loop, renderer = danger_game
    loop.start_stage(0)
    loop.composed.game_state.health = 1
    loop._flow = FLOW_PAUSED
    loop._sync_low_health_danger()
    assert renderer.danger_calls[-1] is False
    loop._flow = FLOW_PLAYING  # restaura pro fixture nao vazar estado


def test_draw_low_health_danger_is_a_no_op_when_inactive():
    renderer = HBPygameRenderer()
    renderer.initialize(64, 64, "test")
    renderer._surface.fill((20, 30, 40))
    before = renderer._surface.get_at((32, 32))

    renderer.set_low_health_danger(False)
    renderer._draw_low_health_danger()

    assert renderer._surface.get_at((32, 32)) == before


def test_draw_low_health_danger_tints_the_frame_when_active():
    renderer = HBPygameRenderer()
    renderer.initialize(64, 64, "test")
    renderer._surface.fill((20, 30, 40))
    before = tuple(renderer._surface.get_at((32, 32)))[:3]

    renderer.set_low_health_danger(True)
    renderer._draw_low_health_danger()

    after = tuple(renderer._surface.get_at((32, 32)))[:3]
    assert after != before  # a franja vermelho/azul mudou o pixel
