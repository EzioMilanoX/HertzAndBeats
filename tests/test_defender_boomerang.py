"""Defensor -- Ameacas Bumerangue: nascem no nucleo, voam ate a borda e voltam (formula senoidal do raio)."""
import dataclasses
import math

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.components.schemas import JUDGMENT_MISS, JUDGMENT_PENDING, JUDGMENT_PERFECT
from hertzbeats.systems.boomerang_threat_system import BoomerangThreatSystem

from tests.conftest import make_config, write_beatmap


def _boomerang(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_boomerang",
        "lane": lane,
        "strength": 0.7,
    }


def _compose_boomerang(tmp_path, null_input, null_clock, threats, **overrides):
    beatmap_path = write_beatmap(tmp_path / "boomerang.beatmap.json", threats)
    config = dataclasses.replace(
        make_config(beatmap_path), active_modifiers=("boomerang",), **overrides,
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


def test_boomerang_threat_spawns_at_the_core(tmp_path, null_input, null_clock):
    composed, config = _compose_boomerang(tmp_path, null_input, null_clock, [_boomerang(10.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    transform_pool = composed.memory_manager.get_pool("transform")
    velocity_pool = composed.memory_manager.get_pool("velocity")

    spawn_time = 10.0 - config.approach_seconds
    _advance_to(composed, null_clock, null_input, spawn_time + 0.01)
    assert threat_pool.count == 1
    entity_index = int(threat_pool.active_entity_indices()[0])

    center_x, center_y = config.center_xy
    t_row = transform_pool.dense_row_of(entity_index)
    x = float(transform_pool.active_view()["position_x"][t_row])
    y = float(transform_pool.active_view()["position_y"][t_row])
    # tolerancia generosa: o passo discreto de `_advance_to` (dt=0.01) nao
    # pousa EXATAMENTE no instante de nascimento, entao o raio ja cresceu
    # uma fracao mínima (`spawn_radius * sin(pi * fracao)`) -- ainda bem
    # menor que `spawn_radius` (420px), so nao e EXATAMENTE zero.
    assert abs(x - center_x) < 10.0
    assert abs(y - center_y) < 10.0

    v_row = velocity_pool.dense_row_of(entity_index)
    assert float(velocity_pool.active_view()["linear_x"][v_row]) == 0.0
    assert float(velocity_pool.active_view()["linear_y"][v_row]) == 0.0


def test_boomerang_threat_reaches_the_edge_at_the_midpoint(tmp_path, null_input, null_clock):
    composed, config = _compose_boomerang(tmp_path, null_input, null_clock, [_boomerang(10.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    transform_pool = composed.memory_manager.get_pool("transform")

    midpoint = 10.0 - config.boomerang_round_trip_seconds / 2.0
    _advance_to(composed, null_clock, null_input, midpoint)
    entity_index = int(threat_pool.active_entity_indices()[0])
    t_row = transform_pool.dense_row_of(entity_index)
    center_x, center_y = config.center_xy
    x = float(transform_pool.active_view()["position_x"][t_row])
    y = float(transform_pool.active_view()["position_y"][t_row])
    radius = math.hypot(x - center_x, y - center_y)
    assert abs(radius - config.spawn_radius) < 2.0


def test_boomerang_threat_returns_to_the_core_at_the_hit_time(tmp_path, null_input, null_clock):
    composed, config = _compose_boomerang(tmp_path, null_input, null_clock, [_boomerang(10.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    transform_pool = composed.memory_manager.get_pool("transform")

    _advance_to(composed, null_clock, null_input, 9.995)  # bem perto do retorno, mas ainda PENDING
    entity_index = int(threat_pool.active_entity_indices()[0])
    row = threat_pool.dense_row_of(entity_index)
    assert int(threat_pool.active_view()["judgment"][row]) == JUDGMENT_PENDING

    t_row = transform_pool.dense_row_of(entity_index)
    center_x, center_y = config.center_xy
    x = float(transform_pool.active_view()["position_x"][t_row])
    y = float(transform_pool.active_view()["position_y"][t_row])
    assert abs(x - center_x) < 10.0
    assert abs(y - center_y) < 10.0


def test_shooting_a_boomerang_during_outbound_does_not_judge_it(tmp_path, null_input, null_clock):
    """Mirar certo na direcao da ameaca durante a IDA nao a julga -- o
    julgamento so compara tempo contra `target_hit_time_sec` (o
    RETORNO), bem distante durante a ida."""
    composed, config = _compose_boomerang(tmp_path, null_input, null_clock, [_boomerang(10.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    midpoint = 10.0 - config.boomerang_round_trip_seconds / 2.0
    _fire_at(composed, null_clock, null_input, midpoint, 1.0, 0.0)  # lane 0 -> angulo 0

    state = composed.game_state
    assert state.perfect_count == 0
    assert state.good_count == 0
    assert state.misfire_count == 1  # tiro sem candidata na janela de tempo
    assert threat_pool.count == 1  # a ameaca continua viva, intocada


def test_shooting_a_boomerang_at_the_return_moment_scores_perfect(tmp_path, null_input, null_clock):
    composed, config = _compose_boomerang(tmp_path, null_input, null_clock, [_boomerang(10.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _advance_to(composed, null_clock, null_input, 9.98)
    _fire_at(composed, null_clock, null_input, 10.0, 1.0, 0.0)

    state = composed.game_state
    assert state.perfect_count == 1
    row_count_after = threat_pool.count
    assert row_count_after == 0  # destruida no acerto


def test_letting_a_boomerang_return_ungoverned_causes_a_miss(tmp_path, null_input, null_clock):
    composed, config = _compose_boomerang(
        tmp_path, null_input, null_clock, [_boomerang(10.0, lane=0)], max_health=3,
    )
    health_before = composed.game_state.health
    _advance_to(composed, null_clock, null_input, 10.3)  # bem alem da janela de MISS

    state = composed.game_state
    assert state.miss_count == 1
    assert state.health == health_before - 1


def test_boomerang_threat_has_a_distinct_orange_tint(tmp_path, null_input, null_clock):
    composed, config = _compose_boomerang(tmp_path, null_input, null_clock, [_boomerang(10.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    sprite_pool = composed.memory_manager.get_pool("sprite")

    _advance_to(composed, null_clock, null_input, 10.0 - config.approach_seconds + 0.01)
    entity_index = int(threat_pool.active_entity_indices()[0])
    s_row = sprite_pool.dense_row_of(entity_index)
    sprite_view = sprite_pool.active_view()
    assert int(sprite_view["tint_r"][s_row]) == 255
    assert int(sprite_view["tint_g"][s_row]) == 150
    assert int(sprite_view["tint_b"][s_row]) == 40


def test_boomerang_system_only_registers_when_the_modifier_is_active(tmp_path, null_input, null_clock):
    beatmap_path = write_beatmap(tmp_path / "no_boomerang.beatmap.json", [
        {"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.5},
    ])
    config = dataclasses.replace(make_config(beatmap_path), active_modifiers=("telegraph_rings",))
    composed = compose_world(config, null_input, null_clock)
    assert not any(isinstance(s, BoomerangThreatSystem) for s in composed.world._systems)


def test_boomerang_system_registers_when_the_modifier_is_active(tmp_path, null_input, null_clock):
    composed, _config = _compose_boomerang(tmp_path, null_input, null_clock, [_boomerang(10.0, lane=0)])
    assert any(isinstance(s, BoomerangThreatSystem) for s in composed.world._systems)
