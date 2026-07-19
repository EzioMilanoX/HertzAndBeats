"""Stutter Scroll (Arcade 4K): ruido visual em Y so no draw_batch -- a fisica real (transform.position_y) nunca muda."""
import dataclasses
import math

import numpy as np
import pytest

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from hertzbeats.bootstrap.hertz_game_loop import HertzGameLoop
from hertzbeats.stages import StageDef
from hertzbeats.systems.visual_modifier_system import compute_stutter_offset_y

from tests.conftest import make_config, write_beatmap


def test_compute_stutter_offset_y_is_a_pure_sine_wave():
    assert compute_stutter_offset_y(now_effective=0.0, frequency_hz=9.0, amplitude_px=10.0) == 0.0
    expected = 10.0 * math.sin(1.0 * 9.0)
    assert abs(compute_stutter_offset_y(1.0, 9.0, 10.0) - expected) < 1e-9


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


@pytest.fixture
def stutter_game(tmp_path, null_input):
    beatmap_path = write_beatmap(tmp_path / "stutter.beatmap.json", [_basic(3.0, lane=0)])
    config = dataclasses.replace(
        make_config(beatmap_path),
        game_mode="lanes",
        stutter_scroll_enabled=True,
        stutter_scroll_amplitude_px=25.0,
        stutter_scroll_frequency_hz=9.0,
    )
    stage = StageDef(
        stage_id="stutter_stage", name="STUTTER", subtitle="",
        track_path=str(tmp_path / "stutter.wav"), beatmap_path=str(beatmap_path),
        synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
    )
    audio_engine = NullAudioEngine()
    clock = audio_engine.get_clock()
    clock.set_playing(True)
    renderer = NullRenderer()
    loop = HertzGameLoop(
        base_config=config, stages=(stage,), renderer=renderer,
        input_provider=null_input, audio_engine=audio_engine, audio_clock=clock,
    )
    return loop, clock


def test_apply_lane_stutter_only_offsets_lanes_mode_threat_entities(stutter_game):
    loop, clock = stutter_game
    loop.start_stage(0)
    composed = loop.composed
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    clock.set_now_seconds(1.0)
    loop._input_provider.poll()
    loop._world.step(0.0)
    assert threat_pool.count == 1
    lane_note_entity_index = int(threat_pool.active_entity_indices()[0])
    other_entity_index = composed.player_entity_index  # nao e uma nota do Arcade 4K

    entity_indices = np.array([lane_note_entity_index, other_entity_index], dtype=np.int64)
    positions_xy = np.array([[100.0, 200.0], [500.0, 600.0]], dtype=np.float32)

    loop._apply_lane_stutter(positions_xy, entity_indices, stutter_offset=15.0)

    assert positions_xy[0, 1] == 215.0  # nota do Arcade 4K: deslocada
    assert positions_xy[1, 1] == 600.0  # entidade fora do modo: intocada


def test_real_physics_position_is_unaffected_by_stutter_over_many_frames(stutter_game):
    """A gagueira visual nunca vaza para `transform.position_y` -- a
    posicao REAL avanca exatamente `velocity_y * tempo`, sem nenhuma
    deriva acumulada pelo ruido do Stutter Scroll."""
    loop, clock = stutter_game
    loop.start_stage(0)
    composed = loop.composed
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    transform_pool = composed.memory_manager.get_pool("transform")
    velocity_pool = composed.memory_manager.get_pool("velocity")

    clock.set_now_seconds(1.0)
    loop._input_provider.poll()
    loop._world.step(0.0)
    assert threat_pool.count == 1
    entity_index = int(threat_pool.active_entity_indices()[0])
    t_row = transform_pool.dense_row_of(entity_index)
    v_row = velocity_pool.dense_row_of(entity_index)
    y0 = float(transform_pool.active_view()["position_y"][t_row])
    vy = float(velocity_pool.active_view()["linear_y"][v_row])

    dt = 0.01
    elapsed = 0.0
    for _ in range(50):
        clock.advance(dt)
        elapsed += dt
        loop.advance_frame(dt)
        loop._sync_overlay()
        loop._sync_camera_shake()
        loop._sync_blindness()
        loop._sync_lane_playfield()
        loop._render_frame()

    assert composed.game_state.lane_stutter_offset_y != 0.0  # o efeito esta de fato ativo
    expected_y = y0 + vy * elapsed
    real_y = float(transform_pool.active_view()["position_y"][t_row])
    assert abs(real_y - expected_y) < 1e-3
