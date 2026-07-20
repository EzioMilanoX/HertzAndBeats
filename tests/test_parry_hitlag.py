"""Defensor -- Juice Extremo de Parry (Hitlag Visual Simulado): congelamento de apresentacao + flash de retorno."""
import dataclasses

import numpy as np

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.bootstrap.hertz_game_loop import HertzGameLoop
from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.game_state import GameState
from hertzbeats.stages import StageDef
from hertzbeats.systems.camera_shake_system import CameraShakeSystem

from tests.conftest import make_config, write_beatmap


def _heavy(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_heavy",
        "lane": lane,
        "strength": 0.9,
    }


def _compose_polarity(tmp_path, null_input, null_clock, threats, **overrides):
    beatmap_path = write_beatmap(tmp_path / "hitlag.beatmap.json", threats)
    config = dataclasses.replace(
        make_config(beatmap_path), active_modifiers=("telegraph_rings", "polarity"), **overrides
    )
    return compose_world(config, null_input, null_clock), config


def _advance_to(composed, null_clock, null_input, target_seconds: float, dt: float = 0.01) -> None:
    remaining = target_seconds - null_clock.now_seconds()
    steps = int(round(remaining / dt))
    for _ in range(steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)


def _fire_at(composed, null_clock, null_input, target_seconds: float, aim_x: float, aim_y: float) -> None:
    dt = target_seconds - null_clock.now_seconds()
    null_input.set_axis("aim_x", aim_x)
    null_input.set_axis("aim_y", aim_y)
    null_input.set_action_held("fire", True)
    null_clock.advance(dt)
    null_input.poll()
    composed.world.step(dt)


# -- GameState / CameraShakeSystem (unitarios) --------------------------


def test_trigger_hitlag_takes_the_larger_freeze_and_always_arms_the_flash():
    state = GameState(max_health=3)
    assert state.visual_freeze_frames == 0
    assert state.invert_colors is False

    state.trigger_hitlag(3)
    assert state.visual_freeze_frames == 3
    assert state.invert_colors is True

    state.invert_colors = False  # simula consumo pelo _sync_hitlag
    state.trigger_hitlag(1)  # menor -- nao deve reduzir o congelamento
    assert state.visual_freeze_frames == 3
    assert state.invert_colors is True  # SEMPRE rearma o flash

    state.trigger_hitlag(5)  # maior -- substitui
    assert state.visual_freeze_frames == 5


def test_camera_shake_system_decays_freeze_frames_by_one_per_update_not_by_delta_time():
    state = GameState(max_health=3)
    system = CameraShakeSystem(state, decay_per_second=10.0)
    state.trigger_hitlag(3)

    system.update(world=None, delta_time=0.001)  # dt minusculo -- ainda decai exatamente 1
    assert state.visual_freeze_frames == 2
    system.update(world=None, delta_time=5.0)  # dt enorme -- ainda decai exatamente 1
    assert state.visual_freeze_frames == 1
    system.update(world=None, delta_time=1.0)
    assert state.visual_freeze_frames == 0
    system.update(world=None, delta_time=1.0)  # nao passa de zero
    assert state.visual_freeze_frames == 0


# -- integracao real: Parry Perfeito dispara o Hitlag -------------------


def test_parry_perfect_triggers_hitlag_freeze_and_invert_flash(tmp_path, null_input, null_clock):
    composed, config = _compose_polarity(tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)])
    state = composed.game_state
    _advance_to(composed, null_clock, null_input, 2.98)

    _fire_at(composed, null_clock, null_input, 2.99, 1.0, 0.0)  # PERFECT -> Parry

    assert state.parry_count == 1
    # `CameraShakeSystem` roda DEPOIS do `JudgmentSystem` no MESMO
    # `world.step` -- ja decai 1 quadro no proprio frame do Parry.
    assert state.visual_freeze_frames == config.parry_hitlag_freeze_frames - 1
    assert state.invert_colors is True


# -- HertzGameLoop._sync_hitlag (renderer fake, sem pygame real) --------


class _FakeHitlagRenderer(NullRenderer):
    def __init__(self) -> None:
        super().__init__()
        self.freeze_active_calls = []
        self.color_invert_calls = []

    def set_freeze_active(self, active: bool) -> None:
        self.freeze_active_calls.append(bool(active))

    def set_color_invert(self, active: bool) -> None:
        self.color_invert_calls.append(bool(active))


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _hitlag_game(tmp_path, null_input):
    beatmap_path = write_beatmap(tmp_path / "hitlag_loop.beatmap.json", [_basic(3.0, lane=0)])
    config = make_config(beatmap_path)
    stage = StageDef(
        stage_id="hitlag_stage", name="HITLAG", subtitle="",
        track_path=str(tmp_path / "hitlag.wav"), beatmap_path=str(beatmap_path),
        synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
    )
    audio_engine = NullAudioEngine()
    clock = audio_engine.get_clock()
    clock.set_playing(True)
    renderer = _FakeHitlagRenderer()
    loop = HertzGameLoop(
        base_config=config, stages=(stage,), renderer=renderer,
        input_provider=null_input, audio_engine=audio_engine, audio_clock=clock,
    )
    return loop, renderer


def test_sync_hitlag_freezes_then_flashes_invert_exactly_on_the_return_frame(tmp_path, null_input):
    loop, renderer = _hitlag_game(tmp_path, null_input)
    loop.start_stage(0)
    state = loop.composed.game_state

    loop._sync_hitlag()
    assert renderer.freeze_active_calls[-1] is False
    assert renderer.color_invert_calls[-1] is False

    state.trigger_hitlag(3)
    loop._sync_hitlag()
    assert renderer.freeze_active_calls[-1] is True
    assert renderer.color_invert_calls[-1] is False  # ainda congelado -- sem flash

    for _ in range(3):  # 3 `world.step` reais decaem `visual_freeze_frames` ate 0
        loop.composed.world.step(0.016)

    loop._sync_hitlag()
    assert renderer.freeze_active_calls[-1] is False  # "a tela volta"
    assert renderer.color_invert_calls[-1] is True  # flash de retorno, exatamente aqui
    assert state.invert_colors is False  # consumido

    loop._sync_hitlag()
    assert renderer.color_invert_calls[-1] is False  # nunca mais que 1 frame de flash


# -- HBPygameRenderer real (driver dummy) -- os Surfaces sao de VERDADE --


def test_end_frame_applies_a_true_negative_color_filter_when_invert_pending():
    renderer = HBPygameRenderer()
    renderer.initialize(64, 64, "test")
    renderer.begin_frame()
    renderer.end_frame()
    pixel_before = renderer._surface.get_at((5, 5))

    renderer.set_color_invert(True)
    renderer.begin_frame()
    renderer.end_frame()
    pixel_after = renderer._surface.get_at((5, 5))

    assert pixel_after.r == 255 - pixel_before.r
    assert pixel_after.g == 255 - pixel_before.g
    assert pixel_after.b == 255 - pixel_before.b

    # publicado por exatamente 1 frame pelo HertzGameLoop -- desarmado
    # aqui simula o proximo `set_color_invert(False)` do loop real.
    renderer.set_color_invert(False)
    renderer.begin_frame()
    renderer.end_frame()
    assert renderer._surface.get_at((5, 5)) == pixel_before


def test_freeze_active_suspends_begin_frame_and_draw_batch():
    renderer = HBPygameRenderer()
    renderer.initialize(64, 64, "test")
    renderer.begin_frame()
    renderer.draw_batch(
        np.array([[32.0, 32.0]]), np.array([0.0]), np.array([[1.0, 1.0]]),
        np.array([999]), np.array([[255, 0, 0, 255]]), np.array([0]), 1,
    )
    renderer.end_frame()
    frozen_reference = renderer._surface.copy()

    renderer.set_freeze_active(True)
    renderer.begin_frame()  # no-op -- NAO limpa a Surface
    renderer.draw_batch(
        np.array([[10.0, 10.0]]), np.array([0.0]), np.array([[1.0, 1.0]]),
        np.array([999]), np.array([[0, 255, 0, 255]]), np.array([0]), 1,
    )  # no-op -- nao desenha o novo sprite verde
    renderer.end_frame()

    assert renderer._surface.get_at((5, 5)) == frozen_reference.get_at((5, 5))
    assert renderer._surface.get_at((32, 32)) == frozen_reference.get_at((32, 32))  # o vermelho antigo persiste
