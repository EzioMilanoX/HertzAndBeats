"""Heartbeat (Juice Visual): beat_phase derivado do bpm da fase, pulso decaindo por compasso."""
import math

import pygame
import pytest

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.bootstrap.hertz_game_loop import HertzGameLoop
from hertzbeats.stages import StageDef

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from tests.conftest import make_config, write_beatmap


class _BeatPhaseTrackingRenderer(NullRenderer):
    """`NullRenderer` (sem `set_beat_phase`) estendido so o suficiente
    pra gravar cada chamada -- o `HertzGameLoop` so publica via
    `hasattr(...)`, entao um `NullRenderer` puro nunca seria exercitado."""

    def __init__(self) -> None:
        self.phases = []

    def set_beat_phase(self, phase: float) -> None:
        self.phases.append(phase)


@pytest.fixture
def renderer():
    renderer = HBPygameRenderer()
    renderer.initialize(320, 240, "test")
    yield renderer
    renderer.shutdown()


# -- HBPygameRenderer._heartbeat_pulse: funcao pura sobre beat_phase -----


def test_heartbeat_pulse_is_maximum_exactly_at_the_start_of_the_beat(renderer):
    renderer.set_beat_phase(0.0)
    assert renderer._heartbeat_pulse() == pytest.approx(1.0)


def test_heartbeat_pulse_decays_as_the_phase_advances(renderer):
    renderer.set_beat_phase(0.0)
    pulse_start = renderer._heartbeat_pulse()
    renderer.set_beat_phase(0.5)
    pulse_mid = renderer._heartbeat_pulse()
    renderer.set_beat_phase(0.99)
    pulse_end = renderer._heartbeat_pulse()
    assert pulse_start > pulse_mid > pulse_end
    assert pulse_end == pytest.approx(0.0, abs=0.01)  # quase totalmente assentado antes da proxima batida


def test_heartbeat_pulse_never_goes_negative(renderer):
    for phase in (0.0, 0.25, 0.5, 0.75, 0.999):
        renderer.set_beat_phase(phase)
        assert renderer._heartbeat_pulse() >= 0.0


# -- HertzGameLoop._sync_beat_phase: aritmetica de now_seconds % beat_duration --


@pytest.fixture
def flow_game(tmp_path, null_input):
    def _make(threats):
        # `write_beatmap` (conftest.py) sempre grava "bpm": 120.0 no
        # beatmap.json -- e' de la que `GameState.bpm` le (nao de
        # `synth`, so usado pra re-sintetizar o audio).
        beatmap_path = write_beatmap(tmp_path / "beat.beatmap.json", threats)
        stage = StageDef(
            stage_id="stage0", name="FASE 0", subtitle="", track_path=str(tmp_path / "stage.wav"),
            beatmap_path=str(beatmap_path), synth={"bpm": 120.0, "bars": 4}, beatmap_params={},
            overrides={},
        )
        audio_engine = NullAudioEngine()
        clock = audio_engine.get_clock()
        renderer = _BeatPhaseTrackingRenderer()
        loop = HertzGameLoop(
            base_config=make_config(beatmap_path), stages=(stage,), renderer=renderer,
            input_provider=null_input, audio_engine=audio_engine, audio_clock=clock,
            player_progress_path=str(tmp_path / "player_progress.json"),
            player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
            user_settings_path=str(tmp_path / "user_settings.json"),
        )
        return loop, clock, renderer

    return _make


def test_sync_beat_phase_reflects_now_seconds_modulo_beat_duration(flow_game):
    loop, clock, renderer = flow_game([{"timestamp_seconds": 99.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.5}])
    loop.start_stage(0)
    beat_duration = 60.0 / 120.0  # 0.5s por batida a 120 BPM

    clock.set_now_seconds(0.2)
    loop._sync_beat_phase()
    assert renderer.phases[-1] == pytest.approx(0.2 / beat_duration)  # 0.4

    clock.set_now_seconds(0.5)  # exatamente no inicio da PROXIMA batida
    loop._sync_beat_phase()
    assert renderer.phases[-1] == pytest.approx(0.0, abs=1e-9)

    clock.set_now_seconds(1.3)  # 2 batidas e meio -> fase 0.6
    loop._sync_beat_phase()
    assert renderer.phases[-1] == pytest.approx(0.6)


def test_sync_beat_phase_uses_the_beatmaps_own_bpm(tmp_path, null_input):
    import json

    from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine

    # `bpm` lido aqui vem do PROPRIO beatmap.json (`GameState.bpm`,
    # `_read_beatmap_bpm`) -- diferente do `synth["bpm"]` da fase (so
    # usado pra re-sintetizar o audio), por isso escrito a mao.
    beatmap_path = tmp_path / "custom_bpm.beatmap.json"
    with open(beatmap_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "version": 1, "track_id": "t", "bpm": 150.0,
                "threats": [{"timestamp_seconds": 99.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.5}],
            },
            f,
        )
    stage = StageDef(
        stage_id="stage0", name="FASE 0", subtitle="", track_path=str(tmp_path / "stage.wav"),
        beatmap_path=str(beatmap_path), synth={"bpm": 150.0, "bars": 4}, beatmap_params={}, overrides={},
    )
    audio_engine = NullAudioEngine()
    clock = audio_engine.get_clock()
    renderer = _BeatPhaseTrackingRenderer()
    loop = HertzGameLoop(
        base_config=make_config(beatmap_path), stages=(stage,), renderer=renderer,
        input_provider=null_input, audio_engine=audio_engine, audio_clock=clock,
        player_progress_path=str(tmp_path / "player_progress.json"),
        player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
        user_settings_path=str(tmp_path / "user_settings.json"),
    )
    loop.start_stage(0)
    assert loop._composed.game_state.bpm == pytest.approx(150.0)

    beat_duration = 60.0 / 150.0
    clock.set_now_seconds(0.1)
    loop._sync_beat_phase()
    assert renderer.phases[-1] == pytest.approx(0.1 / beat_duration)
