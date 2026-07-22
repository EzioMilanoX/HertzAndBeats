"""Juice Visual -- Fundo Reativo: visualizer de fundo escalado por quantos eventos vem pela frente."""
import pytest

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.bootstrap.hertz_game_loop import (
    FLOW_HUB,
    REACTIVE_BACKGROUND_LOOKAHEAD_SECONDS,
    REACTIVE_BACKGROUND_MAX_COUNT,
    HertzGameLoop,
)
from hertzbeats.stages import StageDef

from tests.conftest import make_config, write_beatmap


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": timestamp, "threat_type": "rhythm_threat_basic", "lane": lane, "strength": 0.5}


class _FakeBackgroundRenderer(NullRenderer):
    """NullRenderer + `set_background_intensity`, para testar
    `HertzGameLoop._sync_reactive_background` sem pygame real."""

    def __init__(self) -> None:
        super().__init__()
        self.intensity_calls = []

    def set_background_intensity(self, intensity: float) -> None:
        self.intensity_calls.append(float(intensity))


@pytest.fixture
def background_game(tmp_path, null_input):
    def _make(threats):
        beatmap_path = write_beatmap(tmp_path / "bg.beatmap.json", threats)
        config = make_config(beatmap_path)
        stage = StageDef(
            stage_id="bg_stage", name="BG", subtitle="",
            track_path=str(tmp_path / "bg.wav"), beatmap_path=str(beatmap_path),
            synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
        )
        audio_engine = NullAudioEngine()
        clock = audio_engine.get_clock()
        clock.set_playing(True)
        renderer = _FakeBackgroundRenderer()
        loop = HertzGameLoop(
            base_config=config, stages=(stage,), renderer=renderer,
            input_provider=null_input, audio_engine=audio_engine, audio_clock=clock,
            player_progress_path=str(tmp_path / "player_progress.json"),
            player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
            user_settings_path=str(tmp_path / "user_settings.json"),
        )
        return loop, clock, renderer

    return _make


def test_background_is_silent_far_from_any_upcoming_event(background_game):
    loop, clock, renderer = background_game([_basic(10.0)])
    loop.start_stage(0)
    clock.set_now_seconds(0.0)  # o unico evento e' daqui a 10s, bem alem do lookahead
    loop._sync_reactive_background()
    assert renderer.intensity_calls[-1] == 0.0


def test_background_reacts_to_a_single_upcoming_event(background_game):
    loop, clock, renderer = background_game([_basic(10.0)])
    loop.start_stage(0)
    clock.set_now_seconds(10.0 - REACTIVE_BACKGROUND_LOOKAHEAD_SECONDS / 2.0)
    loop._sync_reactive_background()
    assert renderer.intensity_calls[-1] == pytest.approx(1.0 / REACTIVE_BACKGROUND_MAX_COUNT)


def test_background_saturates_at_max_count(background_game):
    threats = [_basic(10.0 + i * 0.01) for i in range(REACTIVE_BACKGROUND_MAX_COUNT * 2)]
    loop, clock, renderer = background_game(threats)
    loop.start_stage(0)
    clock.set_now_seconds(10.0)
    loop._sync_reactive_background()
    assert renderer.intensity_calls[-1] == 1.0


def test_background_is_off_outside_playing(background_game):
    loop, clock, renderer = background_game([_basic(3.0)])
    loop._sync_reactive_background()  # ainda em FLOW_TITLE
    assert renderer.intensity_calls[-1] == 0.0


def test_background_turns_off_when_leaving_playing(background_game):
    loop, clock, renderer = background_game([_basic(10.0)])
    loop.start_stage(0)
    clock.set_now_seconds(10.0 - REACTIVE_BACKGROUND_LOOKAHEAD_SECONDS / 2.0)
    loop._sync_reactive_background()
    assert renderer.intensity_calls[-1] > 0.0

    loop._flow = FLOW_HUB
    loop._sync_reactive_background()
    assert renderer.intensity_calls[-1] == 0.0


# -- Renderer real ------------------------------------------------------


def test_draw_reactive_background_is_a_no_op_when_intensity_is_zero():
    renderer = HBPygameRenderer()
    renderer.initialize(120, 120, "test")
    renderer._surface.fill((8, 6, 20))
    before = [tuple(renderer._surface.get_at((x, 119)))[:3] for x in range(120)]

    renderer.set_background_intensity(0.0)
    renderer._draw_reactive_background()

    after = [tuple(renderer._surface.get_at((x, 119)))[:3] for x in range(120)]
    assert before == after


def test_draw_reactive_background_draws_bars_when_active():
    renderer = HBPygameRenderer()
    renderer.initialize(120, 120, "test")
    renderer._surface.fill((8, 6, 20))

    renderer.set_background_intensity(1.0)
    renderer._draw_reactive_background()

    bottom_row = [tuple(renderer._surface.get_at((x, 119)))[:3] for x in range(120)]
    assert any(pixel != (8, 6, 20) for pixel in bottom_row)
