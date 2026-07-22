"""Vignette Flash ("Cegueira Ritmica"): GameState.blindness_timer_sec, decaimento e o overlay pre-renderizado."""
import dataclasses

import pygame
import pytest

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.adapters.texture_bank import build_and_register_vignette_surface
from hertzbeats.bootstrap.hertz_game_loop import HertzGameLoop
from hertzbeats.config import HertzConfig
from hertzbeats.game_state import GameState
from hertzbeats.stages import StageDef
from hertzbeats.systems.camera_shake_system import CameraShakeSystem

from tests.conftest import make_config, write_beatmap


def test_trigger_blindness_takes_the_larger_of_overlapping_triggers():
    state = GameState(max_health=3)
    assert state.is_blinded is False

    state.trigger_blindness(1.0)
    assert state.is_blinded is True
    assert state.blindness_timer_sec == 1.0

    state.trigger_blindness(0.3)  # menor -- nao deve reduzir
    assert state.blindness_timer_sec == 1.0

    state.trigger_blindness(2.0)  # maior -- substitui
    assert state.blindness_timer_sec == 2.0


def test_camera_shake_system_also_decays_blindness_timer():
    state = GameState(max_health=3)
    system = CameraShakeSystem(state, decay_per_second=10.0)
    state.trigger_blindness(1.5)

    system.update(world=None, delta_time=1.0)
    assert abs(state.blindness_timer_sec - 0.5) < 1e-9
    assert state.is_blinded is True

    system.update(world=None, delta_time=1.0)  # nao passa de zero
    assert state.blindness_timer_sec == 0.0
    assert state.is_blinded is False


def test_vignette_surface_is_window_sized_with_a_transparent_hole_at_the_judgment_line():
    renderer = HBPygameRenderer()
    renderer.initialize(200, 200, "test")
    config = HertzConfig.from_json("data/config/hertz_beats.config.json")
    config = dataclasses.replace(config, window_width=200, window_height=200, judgment_line_offset=40.0)

    build_and_register_vignette_surface(renderer, config)

    surface = renderer._vignette_surface
    assert surface is not None
    assert surface.get_size() == (200, 200)

    judgment_y = 200 - 40  # 160
    hole_pixel = surface.get_at((100, judgment_y))
    assert hole_pixel.a == 0  # buraco transparente sobre a linha de julgamento

    corner_pixel = surface.get_at((2, 2))
    assert corner_pixel.a == 255  # resto da tela opaco


class _FakeVignetteRenderer(NullRenderer):
    """NullRenderer + os metodos de Vignette Flash, para testar
    `HertzGameLoop._sync_blindness` sem precisar de pygame real."""

    def __init__(self) -> None:
        super().__init__()
        self.blindness_active_calls = []

    def set_blindness_active(self, active: bool) -> None:
        self.blindness_active_calls.append(bool(active))


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


@pytest.fixture
def vignette_game(tmp_path, null_input):
    beatmap_path = write_beatmap(tmp_path / "vig.beatmap.json", [_basic(3.0, lane=0)])
    config = dataclasses.replace(make_config(beatmap_path), game_mode="lanes")
    stage = StageDef(
        stage_id="vig_stage", name="VIG", subtitle="",
        track_path=str(tmp_path / "vig.wav"), beatmap_path=str(beatmap_path),
        synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
    )
    audio_engine = NullAudioEngine()
    clock = audio_engine.get_clock()
    clock.set_playing(True)
    renderer = _FakeVignetteRenderer()
    loop = HertzGameLoop(
        base_config=config, stages=(stage,), renderer=renderer,
        input_provider=null_input, audio_engine=audio_engine, audio_clock=clock,
        player_progress_path=str(tmp_path / "player_progress.json"),
        player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
        user_settings_path=str(tmp_path / "user_settings.json"),
    )
    return loop, renderer


def test_sync_blindness_publishes_game_state_to_the_renderer(vignette_game):
    loop, renderer = vignette_game
    loop.start_stage(0)
    state = loop.composed.game_state

    loop._sync_blindness()
    assert renderer.blindness_active_calls[-1] is False

    state.trigger_blindness(1.0)
    loop._sync_blindness()
    assert renderer.blindness_active_calls[-1] is True
