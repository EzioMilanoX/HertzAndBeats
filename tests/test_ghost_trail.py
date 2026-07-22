"""Juice Visual -- Ghost Trails: RingBuffer circular das ultimas posicoes da mira (Defensor)."""
import dataclasses
import math

import pytest

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.bootstrap.hertz_game_loop import HertzGameLoop
from hertzbeats.stages import StageDef

from tests.conftest import make_config, write_beatmap


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": timestamp, "threat_type": "rhythm_threat_basic", "lane": lane, "strength": 0.5}


class _FakeTrailRenderer(NullRenderer):
    """NullRenderer + Ghost Trails, para testar `HertzGameLoop._sync_ghost_trail`
    sem pygame real."""

    def __init__(self) -> None:
        super().__init__()
        self.recorded_positions = []
        self.reset_calls = 0

    def record_ghost_trail_position(self, x: float, y: float) -> None:
        self.recorded_positions.append((x, y))

    def reset_ghost_trail(self) -> None:
        self.reset_calls += 1


@pytest.fixture
def trail_game(tmp_path, null_input):
    def _make(game_mode="defender"):
        beatmap_path = write_beatmap(tmp_path / "trail.beatmap.json", [_basic(3.0, lane=0)])
        config = dataclasses.replace(make_config(beatmap_path), game_mode=game_mode)
        stage = StageDef(
            stage_id="trail_stage", name="TRAIL", subtitle="",
            track_path=str(tmp_path / "trail.wav"), beatmap_path=str(beatmap_path),
            synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
        )
        audio_engine = NullAudioEngine()
        clock = audio_engine.get_clock()
        clock.set_playing(True)
        renderer = _FakeTrailRenderer()
        loop = HertzGameLoop(
            base_config=config, stages=(stage,), renderer=renderer,
            input_provider=null_input, audio_engine=audio_engine, audio_clock=clock,
            player_progress_path=str(tmp_path / "player_progress.json"),
            player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
            user_settings_path=str(tmp_path / "user_settings.json"),
        )
        return loop, renderer

    return _make


def test_ghost_trail_records_the_crosshair_position_while_playing_defender(trail_game):
    loop, renderer = trail_game("defender")
    loop.start_stage(0)
    loop._sync_ghost_trail()
    assert len(renderer.recorded_positions) == 1


def test_ghost_trail_does_not_record_outside_playing(trail_game):
    loop, renderer = trail_game("defender")
    loop._sync_ghost_trail()  # ainda em FLOW_TITLE
    assert renderer.recorded_positions == []


def test_ghost_trail_does_not_record_in_lanes_mode(trail_game):
    loop, renderer = trail_game("lanes")
    loop.start_stage(0)
    loop._sync_ghost_trail()
    assert renderer.recorded_positions == []


def test_ghost_trail_resets_on_a_fresh_stage(trail_game):
    loop, renderer = trail_game("defender")
    loop.start_stage(0)
    assert renderer.reset_calls >= 1


# -- RingBuffer do renderer real -------------------------------------------


def test_record_ghost_trail_position_wraps_around_the_fixed_buffer():
    renderer = HBPygameRenderer()
    renderer.initialize(64, 64, "test")
    for i in range(15):  # mais que _GHOST_TRAIL_LENGTH (10) -- deve enrolar, nunca crescer
        renderer.record_ghost_trail_position(float(i), float(i))
    assert renderer._ghost_trail_count == 10
    assert len(renderer._ghost_trail_xs) == 10  # buffer FIXO, nunca cresceu


def test_draw_ghost_trail_is_a_no_op_when_empty():
    renderer = HBPygameRenderer()
    renderer.initialize(64, 64, "test")
    renderer._surface.fill((8, 6, 20))
    before = renderer._surface.get_at((10, 10))

    renderer._draw_ghost_trail()
    assert renderer._surface.get_at((10, 10)) == before


def test_draw_ghost_trail_draws_something_once_positions_are_recorded():
    renderer = HBPygameRenderer()
    renderer.initialize(64, 64, "test")
    renderer._surface.fill((8, 6, 20))
    renderer.record_ghost_trail_position(32, 32)
    renderer.record_ghost_trail_position(34, 32)

    renderer._draw_ghost_trail()
    ring_pixel = renderer._surface.get_at((34 + 8, 32))  # borda do circulo mais recente (raio maximo)
    assert tuple(ring_pixel)[:3] != (8, 6, 20)


def test_reset_ghost_trail_clears_recorded_positions():
    renderer = HBPygameRenderer()
    renderer.initialize(64, 64, "test")
    renderer.record_ghost_trail_position(1.0, 1.0)
    renderer.reset_ghost_trail()
    assert renderer._ghost_trail_count == 0

    renderer._surface.fill((8, 6, 20))
    before = renderer._surface.get_at((1, 1))
    renderer._draw_ghost_trail()
    assert renderer._surface.get_at((1, 1)) == before
