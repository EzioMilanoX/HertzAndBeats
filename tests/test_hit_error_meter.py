"""Acessibilidade -- Hit-Error Meter: RingBuffer de deltas assinados por acerto, e a barra de rodape."""
import dataclasses
import math

import pytest

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.bootstrap.hertz_game_loop import FLOW_HUB, HertzGameLoop
from hertzbeats.game_state import HIT_ERROR_BUFFER_CAPACITY, GameState
from hertzbeats.stages import StageDef

from tests.conftest import make_config, write_beatmap


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": timestamp, "threat_type": "rhythm_threat_basic", "lane": lane, "strength": 0.5}


# -- GameState.record_hit_delta (puro) --------------------------------------


def test_record_hit_delta_stores_the_signed_value():
    state = GameState(max_health=3)
    state.record_hit_delta(-0.02)
    state.record_hit_delta(0.05)
    assert state.hit_delta_filled_count == 2
    assert state.hit_delta_buffer[0] == pytest.approx(-0.02)
    assert state.hit_delta_buffer[1] == pytest.approx(0.05)


def test_record_hit_delta_saturates_the_filled_count_at_capacity():
    state = GameState(max_health=3)
    for i in range(HIT_ERROR_BUFFER_CAPACITY + 10):
        state.record_hit_delta(0.001 * i)
    assert state.hit_delta_filled_count == HIT_ERROR_BUFFER_CAPACITY


def test_record_hit_delta_wraps_around_without_growing_the_buffer():
    state = GameState(max_health=3)
    for i in range(HIT_ERROR_BUFFER_CAPACITY + 3):
        state.record_hit_delta(float(i))
    assert state.hit_delta_buffer.shape[0] == HIT_ERROR_BUFFER_CAPACITY
    # os 3 primeiros slots foram sobrescritos pelas 3 voltas extras
    assert state.hit_delta_buffer[0] == float(HIT_ERROR_BUFFER_CAPACITY)


# -- Integracao com o julgamento real ----------------------------------------


def test_a_perfect_defender_hit_records_a_small_signed_delta(tmp_path, null_input, null_clock):
    from hertzbeats.bootstrap.rhythm_composition_root import compose_world

    beatmap_path = write_beatmap(tmp_path / "hiterr.beatmap.json", [_basic(3.0, lane=0)])
    config = make_config(beatmap_path)
    composed = compose_world(config, null_input, null_clock)

    null_input.set_axis("aim_x", math.cos(0.0))
    null_input.set_axis("aim_y", math.sin(0.0))
    null_clock.set_now_seconds(3.02)  # 20ms tarde, ainda dentro do PERFECT
    null_input.set_action_held("fire", True)
    null_input.poll()
    composed.world.step(0.0)

    state = composed.game_state
    assert state.perfect_count == 1
    assert state.hit_delta_filled_count == 1
    assert state.hit_delta_buffer[0] == pytest.approx(0.02, abs=1e-6)


def test_a_perfect_lanes_hit_records_a_small_signed_delta(tmp_path, null_input, null_clock):
    from hertzbeats.bootstrap.rhythm_composition_root import compose_world

    beatmap_path = write_beatmap(tmp_path / "hiterr_lanes.beatmap.json", [_basic(3.0, lane=0)])
    config = dataclasses.replace(make_config(beatmap_path), game_mode="lanes")
    composed = compose_world(config, null_input, null_clock)

    null_clock.set_now_seconds(2.98)  # 20ms cedo
    null_input.set_action_held("lane_0", True)
    null_input.poll()
    composed.world.step(0.0)

    state = composed.game_state
    assert state.perfect_count == 1
    assert state.hit_delta_filled_count == 1
    assert state.hit_delta_buffer[0] == pytest.approx(-0.02, abs=1e-6)


# -- HertzGameLoop -> renderer -----------------------------------------------


class _FakeHitErrorRenderer(NullRenderer):
    def __init__(self) -> None:
        super().__init__()
        self.calls = []

    def set_hit_error_data(self, buffer, write_index, filled_count) -> None:
        self.calls.append((buffer, write_index, filled_count))


@pytest.fixture
def hit_error_game(tmp_path, null_input):
    beatmap_path = write_beatmap(tmp_path / "sync.beatmap.json", [_basic(3.0, lane=0)])
    config = make_config(beatmap_path)
    stage = StageDef(
        stage_id="sync_stage", name="SYNC", subtitle="",
        track_path=str(tmp_path / "sync.wav"), beatmap_path=str(beatmap_path),
        synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
    )
    audio_engine = NullAudioEngine()
    clock = audio_engine.get_clock()
    clock.set_playing(True)
    renderer = _FakeHitErrorRenderer()
    loop = HertzGameLoop(
        base_config=config, stages=(stage,), renderer=renderer,
        input_provider=null_input, audio_engine=audio_engine, audio_clock=clock,
        player_progress_path=str(tmp_path / "player_progress.json"),
        player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
        user_settings_path=str(tmp_path / "user_settings.json"),
    )
    return loop, renderer


def test_sync_publishes_the_live_buffer_while_playing(hit_error_game):
    loop, renderer = hit_error_game
    loop.start_stage(0)
    loop._sync_hit_error_meter()
    buffer, write_index, filled_count = renderer.calls[-1]
    assert buffer is loop.composed.game_state.hit_delta_buffer
    assert filled_count == 0


def test_sync_clears_the_buffer_outside_playing(hit_error_game):
    loop, renderer = hit_error_game
    loop.start_stage(0)
    loop._flow = FLOW_HUB
    loop._sync_hit_error_meter()
    buffer, write_index, filled_count = renderer.calls[-1]
    assert buffer is None
    assert filled_count == 0


# -- Renderer real ------------------------------------------------------


def test_draw_hit_error_meter_is_a_no_op_without_data():
    renderer = HBPygameRenderer()
    renderer.initialize(120, 120, "test")
    renderer._surface.fill((8, 6, 20))
    before = renderer._surface.get_at((60, 86))

    renderer.set_hit_error_data(None, 0, 0)
    renderer._draw_hit_error_meter()
    assert renderer._surface.get_at((60, 86)) == before


def test_draw_hit_error_meter_draws_the_center_tick_and_a_hit_mark():
    import numpy as np

    renderer = HBPygameRenderer()
    renderer.initialize(120, 120, "test")
    renderer._surface.fill((8, 6, 20))

    buffer = np.zeros(8, dtype=np.float64)
    buffer[0] = 0.10  # bem tarde -- deve aparecer deslocado a DIREITA do centro
    renderer.set_hit_error_data(buffer, write_index=1, filled_count=1)
    renderer._draw_hit_error_meter()

    y = renderer._height - 34
    center_x = renderer._width // 2
    center_pixel = tuple(renderer._surface.get_at((center_x, y - 7)))[:3]
    assert center_pixel != (8, 6, 20)  # a marca dourada do centro foi desenhada
