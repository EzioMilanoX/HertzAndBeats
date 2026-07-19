"""Defensor -- Colapso do Anel de Julgamento: raio dinamico via evento do beatmap, lido por mira/spawner/renderer."""
import dataclasses
import math

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.modchart import compute_collapsed_radius, parse_radius_collapse_events

from tests.conftest import make_config, write_beatmap


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _compose_defender(tmp_path, null_input, null_clock, threats, collapse_events, **overrides):
    beatmap_path = write_beatmap(tmp_path / "collapse.beatmap.json", threats)
    config = dataclasses.replace(make_config(beatmap_path), **overrides)
    return (
        compose_world(config, null_input, null_clock, modchart_events=collapse_events),
        config,
    )


def _advance_to(composed, null_clock, null_input, target_seconds: float, dt: float = 0.01) -> None:
    remaining = target_seconds - null_clock.now_seconds()
    steps = int(round(remaining / dt))
    for _ in range(steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)


# -- funcoes puras -------------------------------------------------------


def test_parse_radius_collapse_events_sorts_by_time_and_filters_other_types():
    raw = [
        {"type": "radius_collapse", "time_seconds": 5.0, "duration_seconds": 1.0, "target_radius": 50.0},
        {"type": "radius_collapse", "time_seconds": 1.0, "duration_seconds": 2.0, "target_radius": 20.0},
        {"type": "swap", "time_seconds": 0.5, "lane_a": 0, "lane_b": 3},
    ]
    events = parse_radius_collapse_events(raw)
    assert events == ((1.0, 2.0, 20.0), (5.0, 1.0, 50.0))


def test_compute_collapsed_radius_before_during_and_after():
    events = ((10.0, 2.0, 50.0),)
    assert compute_collapsed_radius(5.0, 150.0, events) == 150.0  # antes do evento
    assert abs(compute_collapsed_radius(11.0, 150.0, events) - 100.0) < 1e-9  # metade do caminho
    assert compute_collapsed_radius(50.0, 150.0, events) == 50.0  # bem depois -- congelado no alvo


def test_compute_collapsed_radius_chains_a_sequence_of_events():
    events = ((10.0, 1.0, 50.0), (20.0, 1.0, 150.0))
    assert compute_collapsed_radius(15.0, 150.0, events) == 50.0  # colapsado apos o 1o evento
    assert compute_collapsed_radius(50.0, 150.0, events) == 150.0  # expandido de volta apos o 2o


# -- regressao: sem eventos, o raio permanece na base -------------------


def test_no_collapse_events_keeps_the_base_radius_forever(tmp_path, null_input, null_clock):
    composed, config = _compose_defender(tmp_path, null_input, null_clock, [], collapse_events=[])
    base_radius = config.core_half_extent + config.threat_half_extents["rhythm_threat_basic"]
    assert abs(composed.game_state.current_judgment_radius - base_radius) < 1e-9

    _advance_to(composed, null_clock, null_input, 5.0)
    assert abs(composed.game_state.current_judgment_radius - base_radius) < 1e-9


# -- integracao: GameState reage ao evento do beatmap --------------------


def test_radius_collapse_event_shrinks_current_judgment_radius_over_time(tmp_path, null_input, null_clock):
    composed, config = _compose_defender(
        tmp_path, null_input, null_clock, [],
        collapse_events=[{"type": "radius_collapse", "time_seconds": 1.0, "duration_seconds": 1.0, "target_radius": 10.0}],
    )
    base_radius = config.core_half_extent + config.threat_half_extents["rhythm_threat_basic"]
    state = composed.game_state
    assert abs(state.current_judgment_radius - base_radius) < 1e-9

    _advance_to(composed, null_clock, null_input, 0.5)
    assert abs(state.current_judgment_radius - base_radius) < 1e-6  # antes do evento comecar

    _advance_to(composed, null_clock, null_input, 1.5)  # metade do caminho (1.0 + duration/2)
    expected_mid = base_radius + (10.0 - base_radius) * 0.5
    assert abs(state.current_judgment_radius - expected_mid) < 0.5

    _advance_to(composed, null_clock, null_input, 5.0)  # bem depois -- congelado no alvo
    assert abs(state.current_judgment_radius - 10.0) < 1e-6


def test_crosshair_orbits_at_the_collapsed_radius(tmp_path, null_input, null_clock):
    composed, config = _compose_defender(
        tmp_path, null_input, null_clock, [],
        collapse_events=[{"type": "radius_collapse", "time_seconds": 0.0, "duration_seconds": 0.2, "target_radius": 10.0}],
    )
    null_input.set_axis("aim_x", 1.0)
    null_input.set_axis("aim_y", 0.0)
    _advance_to(composed, null_clock, null_input, 5.0)  # bem depois -- colapso ja completo

    transform_pool = composed.memory_manager.get_pool("transform")
    row = transform_pool.dense_row_of(composed.crosshair_entity_index)
    center_x, _ = config.center_xy
    x = float(transform_pool.active_view()["position_x"][row])
    assert abs(x - (center_x + 10.0)) < 0.5


def test_new_threat_speed_uses_the_collapsed_radius_not_the_base_one(tmp_path, null_input, null_clock):
    collapsed_radius = 10.0
    composed, config = _compose_defender(
        tmp_path, null_input, null_clock, [_basic(3.0, lane=0)],
        collapse_events=[
            {"type": "radius_collapse", "time_seconds": 0.0, "duration_seconds": 0.1, "target_radius": collapsed_radius}
        ],
    )
    _advance_to(composed, null_clock, null_input, 1.0)  # spawn = 3.0 - approach_seconds(2.0); colapso ja completo
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 1
    velocity_pool = composed.memory_manager.get_pool("velocity")
    entity_index = int(threat_pool.active_entity_indices()[0])
    v_row = velocity_pool.dense_row_of(entity_index)
    speed = math.hypot(
        float(velocity_pool.active_view()["linear_x"][v_row]),
        float(velocity_pool.active_view()["linear_y"][v_row]),
    )

    time_remaining = 3.0 - null_clock.now_seconds()
    expected_speed = (config.spawn_radius - collapsed_radius) / time_remaining
    assert abs(speed - expected_speed) < 1.0
