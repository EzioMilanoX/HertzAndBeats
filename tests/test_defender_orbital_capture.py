"""Defensor -- Captura Orbital (Escudos Rotativos): Parry Perfeito num tipo especial vira escudo, nao reflexo."""
import dataclasses
import math

from hertzbeats.bootstrap.rhythm_composition_root import THREAT_COLLISION_LAYER, compose_world
from hertzbeats.components.schemas import JUDGMENT_PENDING, PHASE_ORBITING
from hertzbeats.systems.parry_impact_system import SHIELD_COLLISION_LAYER

from tests.conftest import make_config, write_beatmap

_LANE_COUNT = 8  # mesmo default de make_config/HertzConfig.lane_count
_TAU = 2.0 * math.pi


def _basic(timestamp: float, lane: int) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _orbit(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_orbit",
        "lane": lane,
        "strength": 0.9,
    }


def _compose_polarity(tmp_path, null_input, null_clock, threats, **overrides):
    beatmap_path = write_beatmap(tmp_path / "orbit.beatmap.json", threats)
    config = dataclasses.replace(
        make_config(beatmap_path),
        active_modifiers=("telegraph_rings", "polarity", "orbital_shields"),
        **overrides,
    )
    return compose_world(config, null_input, null_clock), config


def _aim_for_lane(lane: int) -> tuple:
    angle = _TAU * (lane % _LANE_COUNT) / _LANE_COUNT
    return math.cos(angle), math.sin(angle)


def _advance_to(composed, null_clock, null_input, target_seconds: float, dt: float = 0.01) -> None:
    remaining = target_seconds - null_clock.now_seconds()
    steps = int(round(remaining / dt))
    for _ in range(steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)


def _fire_at(composed, null_clock, null_input, target_seconds: float, action_name: str, aim_x: float, aim_y: float) -> None:
    dt = target_seconds - null_clock.now_seconds()
    null_input.set_axis("aim_x", aim_x)
    null_input.set_axis("aim_y", aim_y)
    null_input.set_action_held(action_name, True)
    null_clock.advance(dt)
    null_input.poll()
    composed.world.step(dt)


def test_perfect_hit_on_orbit_type_captures_it_instead_of_destroying(tmp_path, null_input, null_clock):
    composed, config = _compose_polarity(tmp_path, null_input, null_clock, [_orbit(3.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    velocity_pool = composed.memory_manager.get_pool("velocity")
    hitbox_pool = composed.memory_manager.get_pool("hitbox")

    _advance_to(composed, null_clock, null_input, 2.98)
    assert threat_pool.count == 1
    entity_index = int(threat_pool.active_entity_indices()[0])

    _fire_at(composed, null_clock, null_input, 2.99, "fire", 1.0, 0.0)  # QUALQUER cor serve, como o Parry

    state = composed.game_state
    assert threat_pool.count == 1  # nao destruida -- capturada
    assert state.orbit_capture_count == 1
    assert state.combo_count == 1

    row = threat_pool.dense_row_of(entity_index)
    assert int(threat_pool.active_view()["phase"][row]) == PHASE_ORBITING
    assert int(threat_pool.active_view()["judgment"][row]) == JUDGMENT_PENDING

    v_row = velocity_pool.dense_row_of(entity_index)
    assert float(velocity_pool.active_view()["linear_x"][v_row]) == 0.0
    assert float(velocity_pool.active_view()["linear_y"][v_row]) == 0.0

    hb_row = hitbox_pool.dense_row_of(entity_index)
    assert int(hitbox_pool.active_view()["collision_layer"][hb_row]) == SHIELD_COLLISION_LAYER
    assert int(hitbox_pool.active_view()["collision_mask"][hb_row]) == THREAT_COLLISION_LAYER


def test_orbit_capture_requires_the_tighter_perfect_window(tmp_path, null_input, null_clock):
    composed, config = _compose_polarity(tmp_path, null_input, null_clock, [_orbit(3.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 1.0)

    _fire_at(composed, null_clock, null_input, 2.92, "fire", 1.0, 0.0)  # delta=0.08: good, fora do perfect(0.05)

    state = composed.game_state
    assert state.orbit_capture_count == 0
    assert state.misfire_count == 1
    assert threat_pool.count == 1


def test_captured_shield_orbits_the_core_over_time(tmp_path, null_input, null_clock):
    composed, config = _compose_polarity(tmp_path, null_input, null_clock, [_orbit(3.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    transform_pool = composed.memory_manager.get_pool("transform")

    _advance_to(composed, null_clock, null_input, 2.98)
    entity_index = int(threat_pool.active_entity_indices()[0])
    _fire_at(composed, null_clock, null_input, 2.99, "fire", 1.0, 0.0)

    _advance_to(composed, null_clock, null_input, 3.5)

    now = null_clock.now_seconds()
    angle = 0.0 + config.orbit_angular_speed_rad_per_sec * now  # spawn_angle_rad da lane 0 == 0.0
    center_x, center_y = config.center_xy
    expected_x = center_x + math.cos(angle) * config.orbit_radius
    expected_y = center_y + math.sin(angle) * config.orbit_radius

    t_row = transform_pool.dense_row_of(entity_index)
    actual_x = float(transform_pool.active_view()["position_x"][t_row])
    actual_y = float(transform_pool.active_view()["position_y"][t_row])
    assert abs(actual_x - expected_x) < 1.0
    assert abs(actual_y - expected_y) < 1.0


def test_orbital_shield_destroys_a_threat_that_crosses_its_path(tmp_path, null_input, null_clock):
    composed, config = _compose_polarity(
        tmp_path, null_input, null_clock,
        [_orbit(3.0, lane=0), _basic(3.6, lane=0)],
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    transform_pool = composed.memory_manager.get_pool("transform")

    _advance_to(composed, null_clock, null_input, 2.98)
    entity_indices = list(threat_pool.active_entity_indices())
    orbit_index, basic_index = None, None
    for entity_index in entity_indices:
        entity_index = int(entity_index)
        row = threat_pool.dense_row_of(entity_index)
        if int(threat_pool.active_view()["threat_type"][row]) == config.threat_type_ids["rhythm_threat_orbit"]:
            orbit_index = entity_index
        else:
            basic_index = entity_index
    assert orbit_index is not None and basic_index is not None

    _fire_at(composed, null_clock, null_input, 2.99, "fire", 1.0, 0.0)  # PERFECT -> captura
    assert threat_pool.count == 2  # ainda nao colidiu

    orbit_t_row = transform_pool.dense_row_of(orbit_index)
    orbit_x = float(transform_pool.active_view()["position_x"][orbit_t_row])
    orbit_y = float(transform_pool.active_view()["position_y"][orbit_t_row])
    basic_t_row = transform_pool.dense_row_of(basic_index)
    transform_pool.active_view()["position_x"][basic_t_row] = orbit_x
    transform_pool.active_view()["position_y"][basic_t_row] = orbit_y

    score_before = composed.game_state.score
    null_input.set_action_held("fire", False)
    null_input.poll()
    composed.world.step(0.0)

    assert threat_pool.count == 1  # o basic foi destruido pelo escudo
    remaining_index = int(threat_pool.active_entity_indices()[0])
    assert remaining_index == orbit_index  # o escudo sobrevive, continua orbitando
    assert composed.game_state.score > score_before


def test_orbiting_shield_is_never_swept_as_overdue_miss(tmp_path, null_input, null_clock):
    composed, config = _compose_polarity(tmp_path, null_input, null_clock, [_orbit(3.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _advance_to(composed, null_clock, null_input, 2.98)
    _fire_at(composed, null_clock, null_input, 2.99, "fire", 1.0, 0.0)
    assert threat_pool.count == 1

    null_input.set_action_held("fire", False)
    _advance_to(composed, null_clock, null_input, 3.5)  # bem alem da janela de miss original

    assert threat_pool.count == 1
    assert composed.game_state.miss_count == 0
