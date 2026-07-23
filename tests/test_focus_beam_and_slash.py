"""Raio de Foco (Microondas) e A Lamina (Radial Slash): 2 mecanicas que trocam o clique por sustentacao de mira / arrasto fisico."""
import dataclasses
import math

import numpy as np
import pytest
from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine

from hertzbeats.audio.sfx_synth import SFX_SLASH
from hertzbeats.bootstrap.rhythm_composition_root import compose_world

from tests.conftest import make_config, write_beatmap


def _threat(timestamp: float, lane: int = 0, threat_type: str = "rhythm_threat_basic") -> dict:
    return {"timestamp_seconds": timestamp, "threat_type": threat_type, "lane": lane, "strength": 0.5}


def _compose(tmp_path, null_input, null_clock, threats, active_modifiers, audio_engine=None, **overrides):
    beatmap_path = write_beatmap(tmp_path / "focus_slash.beatmap.json", threats)
    config = dataclasses.replace(
        make_config(beatmap_path), active_modifiers=active_modifiers, **overrides,
    )
    return compose_world(config, null_input, null_clock, audio_engine=audio_engine), config


def _aim_at(null_input, angle: float) -> None:
    null_input.set_axis("aim_x", math.cos(angle))
    null_input.set_axis("aim_y", math.sin(angle))


def _advance(composed, null_clock, null_input, steps: int, dt: float = 0.01) -> None:
    for _ in range(steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)


def _advance_to(composed, null_clock, null_input, target_seconds: float, dt: float = 0.01) -> None:
    remaining = target_seconds - null_clock.now_seconds()
    steps = max(0, int(round(remaining / dt)))
    _advance(composed, null_clock, null_input, steps, dt)


def _advance_until_resolved(composed, threat_pool, null_clock, null_input, max_steps: int, dt: float = 0.01) -> None:
    """Mesmo helper de `test_phalanx_mode.py`: para EXATAMENTE no instante
    em que a UNICA ameaca da pool nasce e depois e' resolvida (perfeita OU
    perdida), sem continuar avancando alem disso."""
    has_spawned = False
    for _ in range(max_steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)
        if threat_pool.count > 0:
            has_spawned = True
        elif has_spawned:
            return


# lane_count=8 (make_config): lane % 3 == 1 -> Raio de Foco; lane % 3 == 2 -> Lamina.
_FOCUS_LANE = 1
_SLASH_LANE = 2
_FOCUS_ANGLE = 2.0 * math.pi * _FOCUS_LANE / 8
_SLASH_ANGLE = 2.0 * math.pi * _SLASH_LANE / 8


# -- Atribuicao de flags/texturas no spawn (fracao deterministica) --------


def test_focus_and_slash_flags_assigned_by_lane_fraction(tmp_path, null_input, null_clock):
    threats = [_threat(10.0, lane=lane) for lane in range(8)]
    composed, _config = _compose(tmp_path, null_input, null_clock, threats, ("focus_beam", "radial_slash"))
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 8.5)
    assert threat_pool.count == 8

    view = threat_pool.active_view()
    for row in range(threat_pool.count):
        lane = int(view["lane"][row])
        assert bool(view["is_focus_target"][row]) == (lane % 3 == 1)
        assert bool(view["is_slash_target"][row]) == (lane % 3 == 2)


def test_focus_and_slash_flags_stay_off_without_their_modifiers(tmp_path, null_input, null_clock):
    threats = [_threat(10.0, lane=_FOCUS_LANE), _threat(10.0, lane=_SLASH_LANE)]
    composed, _config = _compose(tmp_path, null_input, null_clock, threats, ("telegraph_rings",))
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 8.5)
    assert threat_pool.count == 2

    view = threat_pool.active_view()
    for row in range(threat_pool.count):
        assert bool(view["is_focus_target"][row]) is False
        assert bool(view["is_slash_target"][row]) is False


def test_boomerang_threats_never_get_focus_or_slash_flags(tmp_path, null_input, null_clock):
    threats = [
        _threat(10.0, lane=_FOCUS_LANE, threat_type="rhythm_threat_boomerang"),
        _threat(10.0, lane=_SLASH_LANE, threat_type="rhythm_threat_boomerang"),
    ]
    composed, _config = _compose(
        tmp_path, null_input, null_clock, threats, ("focus_beam", "radial_slash", "boomerang"),
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 8.5)
    assert threat_pool.count == 2

    view = threat_pool.active_view()
    for row in range(threat_pool.count):
        assert bool(view["is_focus_target"][row]) is False
        assert bool(view["is_slash_target"][row]) is False


# -- Raio de Foco (Microondas): sustentacao de mira ------------------------


def test_focus_beam_resolves_perfect_when_sustained_aim_through_impact(tmp_path, null_input, null_clock):
    composed, _config = _compose(tmp_path, null_input, null_clock, [_threat(10.0, lane=_FOCUS_LANE)], ("focus_beam",))
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _aim_at(null_input, _FOCUS_ANGLE)
    _advance_until_resolved(composed, threat_pool, null_clock, null_input, max_steps=1200)

    assert threat_pool.count == 0
    state = composed.game_state
    assert state.perfect_count == 1
    assert state.miss_count == 0
    assert state.combo_count == 1


def test_focus_beam_never_aimed_correctly_results_in_a_miss(tmp_path, null_input, null_clock):
    composed, config = _compose(
        tmp_path, null_input, null_clock, [_threat(10.0, lane=_FOCUS_LANE)], ("focus_beam",), max_health=3,
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _aim_at(null_input, _FOCUS_ANGLE + math.pi)  # sempre olhando pro lado oposto
    _advance_until_resolved(composed, threat_pool, null_clock, null_input, max_steps=1200)

    assert threat_pool.count == 0
    state = composed.game_state
    assert state.perfect_count == 0
    assert state.miss_count == 1
    assert state.health == config.max_health - 1


def test_focus_beam_resets_health_to_max_the_instant_aim_leaves_the_cone(tmp_path, null_input, null_clock):
    composed, config = _compose(tmp_path, null_input, null_clock, [_threat(10.0, lane=_FOCUS_LANE)], ("focus_beam",))
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _advance_to(composed, null_clock, null_input, 8.5)  # nasce, mira parada em (0,0) -- fora do cone
    assert threat_pool.count == 1

    _aim_at(null_input, _FOCUS_ANGLE)
    _advance(composed, null_clock, null_input, 20)  # 0.2s de sustentacao correta, de um total de 0.6s

    row = int(threat_pool.active_entity_indices()[0])
    row = threat_pool.dense_row_of(row)
    health_after_sustain = float(threat_pool.active_view()["focus_health"][row])
    assert health_after_sustain == pytest.approx(config.focus_target_seconds - 0.2, abs=1e-3)

    _aim_at(null_input, _FOCUS_ANGLE + math.pi)  # afasta a mira -- punicao maxima
    _advance(composed, null_clock, null_input, 1)

    row = threat_pool.dense_row_of(int(threat_pool.active_entity_indices()[0]))
    health_after_reset = float(threat_pool.active_view()["focus_health"][row])
    assert health_after_reset == pytest.approx(config.focus_target_seconds)


def test_focus_beam_ignores_click_and_registers_a_misfire_instead(tmp_path, null_input, null_clock):
    composed, _config = _compose(tmp_path, null_input, null_clock, [_threat(10.0, lane=_FOCUS_LANE)], ("focus_beam",))
    _advance_to(composed, null_clock, null_input, 9.99)

    _aim_at(null_input, _FOCUS_ANGLE)
    null_input.set_action_held("fire", True)
    null_clock.advance(0.01)
    null_input.poll()
    composed.world.step(0.01)

    state = composed.game_state
    assert state.perfect_count == 0
    assert state.misfire_count == 1


def test_focus_beam_hexagon_pulses_scale_over_time(tmp_path, null_input, null_clock):
    composed, _config = _compose(tmp_path, null_input, null_clock, [_threat(10.0, lane=_FOCUS_LANE)], ("focus_beam",))
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    transform_pool = composed.memory_manager.get_pool("transform")

    _advance_to(composed, null_clock, null_input, 8.5)
    assert threat_pool.count == 1

    scales_seen = set()
    for _ in range(40):
        null_clock.advance(0.01)
        null_input.poll()
        composed.world.step(0.01)
        row = transform_pool.dense_row_of(int(threat_pool.active_entity_indices()[0]))
        scales_seen.add(round(float(transform_pool.active_view()["scale_x"][row]), 4))

    assert len(scales_seen) > 1  # oscila -- nao fica preso num unico valor


# -- A Lamina (Radial Slash): arrasto fisico -------------------------------


def _swipe(composed, null_clock, null_input, from_angle: float, to_angle: float, dt: float = 0.01) -> None:
    """Um golpe = UM `world.step`: a mira JA estava em `from_angle` (vira
    `mouse_angle_previous` dentro do `PlayerInputSystem`) e passa a
    `to_angle` NESTE frame -- exatamente como um arrasto fisico rapido do
    mouse entre 2 frames consecutivos."""
    _aim_at(null_input, from_angle)
    null_clock.advance(dt)
    null_input.poll()
    composed.world.step(dt)
    _aim_at(null_input, to_angle)
    null_clock.advance(dt)
    null_input.poll()
    composed.world.step(dt)


def test_slash_resolves_perfect_on_a_fast_swipe_crossing_the_target(tmp_path, null_input, null_clock):
    engine = NullAudioEngine()
    composed, _config = _compose(
        tmp_path, null_input, null_clock, [_threat(10.0, lane=_SLASH_LANE)], ("radial_slash",), audio_engine=engine,
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _aim_at(null_input, _SLASH_ANGLE - 1.0)
    _advance_to(composed, null_clock, null_input, 9.97)  # dentro da janela PERFECT (0.05s)

    _swipe(composed, null_clock, null_input, _SLASH_ANGLE - 0.3, _SLASH_ANGLE + 0.3)

    assert threat_pool.count == 0
    state = composed.game_state
    assert state.perfect_count == 1
    assert (SFX_SLASH, 1.0) in engine._one_shots_played


def test_slash_ignores_a_swipe_that_is_too_slow_even_if_it_crosses(tmp_path, null_input, null_clock):
    composed, config = _compose(
        tmp_path, null_input, null_clock, [_threat(10.0, lane=_SLASH_LANE)], ("radial_slash",), max_health=3,
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _aim_at(null_input, _SLASH_ANGLE - 1.0)
    _advance_to(composed, null_clock, null_input, 9.97)

    _swipe(composed, null_clock, null_input, _SLASH_ANGLE - 0.005, _SLASH_ANGLE + 0.005)  # cruza, mas devagar

    assert threat_pool.count == 1  # continua pendente -- velocidade nao bateu o limiar
    assert composed.game_state.perfect_count == 0

    _advance_until_resolved(composed, threat_pool, null_clock, null_input, max_steps=100)
    state = composed.game_state
    assert state.perfect_count == 0
    assert state.miss_count == 1
    assert state.health == config.max_health - 1


def test_slash_ignores_a_fast_swipe_that_never_crosses_the_target(tmp_path, null_input, null_clock):
    composed, config = _compose(
        tmp_path, null_input, null_clock, [_threat(10.0, lane=_SLASH_LANE)], ("radial_slash",), max_health=3,
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _aim_at(null_input, _SLASH_ANGLE - 2.0)
    _advance_to(composed, null_clock, null_input, 9.97)

    _swipe(composed, null_clock, null_input, _SLASH_ANGLE - 1.0, _SLASH_ANGLE - 0.4)  # rapido, mas nunca chega la

    assert threat_pool.count == 1
    assert composed.game_state.perfect_count == 0

    _advance_until_resolved(composed, threat_pool, null_clock, null_input, max_steps=100)
    state = composed.game_state
    assert state.perfect_count == 0
    assert state.miss_count == 1
    assert state.health == config.max_health - 1


def test_slash_ignores_click_even_when_aimed_squarely_without_a_swipe(tmp_path, null_input, null_clock):
    composed, _config = _compose(tmp_path, null_input, null_clock, [_threat(10.0, lane=_SLASH_LANE)], ("radial_slash",))
    _aim_at(null_input, _SLASH_ANGLE)
    _advance_to(composed, null_clock, null_input, 9.99)

    null_input.set_action_held("fire", True)
    null_clock.advance(0.01)
    null_input.poll()
    composed.world.step(0.01)

    state = composed.game_state
    assert state.perfect_count == 0
    assert state.misfire_count == 1


# -- Renderer real: rotulo do checkbox, dica de controles, desenho --------


def test_focus_beam_checkbox_row_has_a_registered_label_texture():
    from hertzbeats.adapters.texture_bank import _MODIFIER_ROW_LABELS
    from hertzbeats.bootstrap.hertz_game_loop import DEFENDER_MODIFIER_ROWS

    assert "focus_beam" in DEFENDER_MODIFIER_ROWS
    assert "focus_beam" in _MODIFIER_ROW_LABELS


def test_radial_slash_checkbox_row_has_a_registered_label_texture():
    from hertzbeats.adapters.texture_bank import _MODIFIER_ROW_LABELS
    from hertzbeats.bootstrap.hertz_game_loop import DEFENDER_MODIFIER_ROWS

    assert "radial_slash" in DEFENDER_MODIFIER_ROWS
    assert "radial_slash" in _MODIFIER_ROW_LABELS


def test_focus_beam_and_slash_control_hint_textures_are_registered_for_curated_stages():
    from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
    from hertzbeats.adapters.texture_bank import build_and_register_overlay_surfaces
    from hertzbeats.stages import StageDef

    stages = (
        StageDef(
            stage_id="f", name="FOCO", subtitle="", track_path="", beatmap_path="unused",
            synth=None, beatmap_params={}, overrides={}, active_modifiers=("focus_beam",),
        ),
        StageDef(
            stage_id="s", name="LAMINA", subtitle="", track_path="", beatmap_path="unused",
            synth=None, beatmap_params={}, overrides={}, active_modifiers=("radial_slash",),
        ),
    )
    renderer = HBPygameRenderer()
    renderer.initialize(120, 120, "test")
    build_and_register_overlay_surfaces(renderer, stages)
    assert renderer._overlay_surfaces.get("stage_0_hint") is not None
    assert renderer._overlay_surfaces.get("stage_1_hint") is not None


def test_focus_hexagon_and_slash_bar_draw_without_crashing_via_real_renderer():
    """Mesmo criterio de `test_phalanx_shield_draws_without_crashing_via_real_renderer`
    -- `draw_batch` com os 2 novos `shape_id` procedurais nao pode levantar."""
    from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
    from hertzbeats.components.texture_ids import TEX_THREAT_FOCUS_HEXAGON, TEX_THREAT_SLASH

    renderer = HBPygameRenderer()
    renderer.initialize(200, 200, "test")
    renderer.begin_frame()

    positions = np.array([[100.0, 100.0], [120.0, 80.0]], dtype=np.float64)
    rotations = np.array([0.3, 1.1], dtype=np.float64)
    scales = np.array([[1.0, 1.0], [1.1, 1.1]], dtype=np.float64)
    texture_ids = np.array([TEX_THREAT_FOCUS_HEXAGON, TEX_THREAT_SLASH], dtype=np.int32)
    tints = np.array([[255, 210, 90, 255], [235, 245, 255, 255]], dtype=np.int32)
    layers = np.array([0, 0], dtype=np.int32)

    renderer.draw_batch(positions, rotations, scales, texture_ids, tints, layers, 2)
    renderer.end_frame()
