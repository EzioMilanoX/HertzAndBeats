"""Modificador "Corrupcao" (Breakcore/Glitchhop): estatica visual, puramente cosmetica."""
import pytest

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.bootstrap.hertz_game_loop import FLOW_HUB, HertzGameLoop
from hertzbeats.stages import StageDef

from tests.conftest import make_config, write_beatmap


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": timestamp, "threat_type": "rhythm_threat_basic", "lane": lane, "strength": 0.5}


class _FakeGlitchRenderer(NullRenderer):
    """NullRenderer + `set_glitch_intensity`, para testar
    `HertzGameLoop._sync_corruption_glitch` sem pygame real."""

    def __init__(self) -> None:
        super().__init__()
        self.glitch_calls = []

    def set_glitch_intensity(self, intensity: float) -> None:
        self.glitch_calls.append(float(intensity))


@pytest.fixture
def glitch_game(tmp_path, null_input):
    def _make(active_modifiers=()):
        beatmap_path = write_beatmap(tmp_path / "glitch.beatmap.json", [_basic(3.0, lane=0)])
        config = make_config(beatmap_path)
        stage = StageDef(
            stage_id="glitch_stage", name="GLITCH", subtitle="",
            track_path=str(tmp_path / "glitch.wav"), beatmap_path=str(beatmap_path),
            synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
            active_modifiers=active_modifiers,
        )
        audio_engine = NullAudioEngine()
        clock = audio_engine.get_clock()
        clock.set_playing(True)
        renderer = _FakeGlitchRenderer()
        loop = HertzGameLoop(
            base_config=config, stages=(stage,), renderer=renderer,
            input_provider=null_input, audio_engine=audio_engine, audio_clock=clock,
            player_progress_path=str(tmp_path / "player_progress.json"),
            player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
            user_settings_path=str(tmp_path / "user_settings.json"),
        )
        return loop, renderer

    return _make


def test_glitch_is_active_while_playing_with_the_modifier_on(glitch_game):
    loop, renderer = glitch_game(active_modifiers=("corrupcao",))
    loop.start_stage(0)
    loop._sync_corruption_glitch()
    assert renderer.glitch_calls[-1] > 0.0


def test_glitch_is_off_without_the_modifier(glitch_game):
    loop, renderer = glitch_game(active_modifiers=("telegraph_rings",))
    loop.start_stage(0)
    loop._sync_corruption_glitch()
    assert renderer.glitch_calls[-1] == 0.0


def test_glitch_turns_off_when_leaving_playing(glitch_game):
    loop, renderer = glitch_game(active_modifiers=("corrupcao",))
    loop.start_stage(0)
    loop._sync_corruption_glitch()
    assert renderer.glitch_calls[-1] > 0.0

    loop._flow = FLOW_HUB
    loop._sync_corruption_glitch()
    assert renderer.glitch_calls[-1] == 0.0


# -- Renderer real ----------------------------------------------------------


def test_draw_glitch_bars_is_a_no_op_when_intensity_is_zero():
    renderer = HBPygameRenderer()
    renderer.initialize(64, 64, "test")
    renderer._surface.fill((8, 6, 20))
    before = [tuple(renderer._surface.get_at((x, 5)))[:3] for x in range(64)]

    renderer.set_glitch_intensity(0.0)
    renderer._draw_glitch_bars()

    after = [tuple(renderer._surface.get_at((x, 5)))[:3] for x in range(64)]
    assert before == after


def test_draw_glitch_bars_draws_full_width_static_when_active():
    renderer = HBPygameRenderer()
    renderer.initialize(64, 64, "test")
    renderer._surface.fill((8, 6, 20))

    renderer.set_glitch_intensity(1.0)
    renderer._draw_glitch_bars()

    rows = [tuple(renderer._surface.get_at((0, y)))[:3] for y in range(64)]
    assert any(row != (8, 6, 20) for row in rows)  # ao menos uma linha virou barra de estatica
