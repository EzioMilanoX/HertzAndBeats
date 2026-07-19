"""Modcharts (Arcade 4K): evento 'swap' troca duas colunas de lugar suavemente (Lerp) -- notas caindo acompanham."""
import dataclasses

import numpy as np

from hertzbeats.bootstrap.rhythm_composition_root import compose_world, lane_center_positions
from hertzbeats.modchart import compute_swapped_lane_xs, parse_swap_events

from tests.conftest import make_config, write_beatmap


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _compose_lane_modchart(tmp_path, null_input, null_clock, threats, modchart_events, **overrides):
    beatmap_path = write_beatmap(tmp_path / "mc.beatmap.json", threats)
    config = dataclasses.replace(make_config(beatmap_path), game_mode="lanes", **overrides)
    return (
        compose_world(config, null_input, null_clock, modchart_events=modchart_events),
        config,
    )


def _advance_to(composed, null_clock, null_input, target_seconds: float, dt: float = 0.01) -> None:
    remaining = target_seconds - null_clock.now_seconds()
    steps = int(round(remaining / dt))
    for _ in range(steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)


# -- funcoes puras -----------------------------------------------------


def test_parse_swap_events_sorts_by_time_and_ignores_unknown_types():
    raw = [
        {"type": "swap", "time_seconds": 5.0, "duration_seconds": 1.0, "lane_a": 0, "lane_b": 3},
        {"type": "swap", "time_seconds": 1.0, "duration_seconds": 2.0, "lane_a": 1, "lane_b": 2},
        {"type": "future_effect_nao_suportado", "time_seconds": 0.5},
    ]
    events = parse_swap_events(raw)
    assert events == ((1.0, 2.0, 1, 2), (5.0, 1.0, 0, 3))


def test_compute_swapped_lane_xs_before_event_is_unaffected():
    base = np.array([0.0, 100.0, 200.0, 300.0])
    events = ((10.0, 2.0, 0, 3),)
    result = compute_swapped_lane_xs(base, events, now_effective=5.0)
    assert np.array_equal(result, base)


def test_compute_swapped_lane_xs_lerps_halfway_through_the_swap():
    base = np.array([0.0, 100.0, 200.0, 300.0])
    events = ((10.0, 2.0, 0, 3),)
    result = compute_swapped_lane_xs(base, events, now_effective=11.0)  # 50% do caminho
    assert abs(result[0] - 150.0) < 1e-9  # lane 0: 0 -> 300
    assert abs(result[3] - 150.0) < 1e-9  # lane 3: 300 -> 0
    assert result[1] == 100.0 and result[2] == 200.0  # colunas fora do swap, intocadas


def test_compute_swapped_lane_xs_freezes_fully_swapped_after_duration():
    base = np.array([0.0, 100.0, 200.0, 300.0])
    events = ((10.0, 2.0, 0, 3),)
    result = compute_swapped_lane_xs(base, events, now_effective=50.0)  # bem depois do fim
    assert result[0] == 300.0
    assert result[3] == 0.0


def test_compute_swapped_lane_xs_never_mutates_the_base_array():
    base = np.array([0.0, 100.0, 200.0, 300.0])
    base_copy = base.copy()
    compute_swapped_lane_xs(base, ((10.0, 2.0, 0, 3),), now_effective=50.0)
    assert np.array_equal(base, base_copy)


# -- integracao (composicao real) --------------------------------------


def test_falling_note_position_x_follows_the_swap_curve_in_real_time(tmp_path, null_input, null_clock):
    """A nota ja caindo (nascida ANTES do swap comecar) precisa
    acompanhar a curva -- nao so notas novas."""
    composed, config = _compose_lane_modchart(
        tmp_path, null_input, null_clock,
        [_basic(20.0, lane=0)],  # hit_time=20, approach=20 -> spawna em t=0, cai por 20s inteiros
        modchart_events=[{"type": "swap", "time_seconds": 2.0, "duration_seconds": 4.0, "lane_a": 0, "lane_b": 3}],
        approach_seconds=20.0,
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    transform_pool = composed.memory_manager.get_pool("transform")

    _advance_to(composed, null_clock, null_input, 1.0)  # spawnada, MUITO antes do swap comecar
    assert threat_pool.count == 1
    entity_index = int(threat_pool.active_entity_indices()[0])
    t_row = transform_pool.dense_row_of(entity_index)

    base_xs = lane_center_positions(config)
    x_before = float(transform_pool.active_view()["position_x"][t_row])
    assert abs(x_before - base_xs[0]) < 1e-6  # ainda na posicao base (swap nao comecou)

    _advance_to(composed, null_clock, null_input, 4.0)  # metade do swap (2.0 + 4.0/2)
    x_mid = float(transform_pool.active_view()["position_x"][t_row])
    expected_mid = base_xs[0] + (base_xs[3] - base_xs[0]) * 0.5
    assert abs(x_mid - expected_mid) < 2.0  # tolerancia por causa dos passos de 0.01s

    _advance_to(composed, null_clock, null_input, 6.5)  # bem depois do fim (2.0+4.0=6.0)
    x_after = float(transform_pool.active_view()["position_x"][t_row])
    assert abs(x_after - base_xs[3]) < 1e-6  # totalmente trocada para a posicao da lane 3


def test_receptor_follows_the_swap_too(tmp_path, null_input, null_clock):
    composed, config = _compose_lane_modchart(
        tmp_path, null_input, null_clock, [],
        modchart_events=[{"type": "swap", "time_seconds": 1.0, "duration_seconds": 1.0, "lane_a": 0, "lane_b": 3}],
    )
    choreography = composed.lane_choreography_system
    assert choreography is not None

    _advance_to(composed, null_clock, null_input, 2.5)  # bem depois do fim do swap

    base_xs = lane_center_positions(config)
    assert abs(float(choreography.current_lane_xs[0]) - base_xs[3]) < 1e-6
    assert abs(float(choreography.current_lane_xs[3]) - base_xs[0]) < 1e-6


def test_no_modchart_events_behaves_exactly_like_before(tmp_path, null_input, null_clock):
    composed, config = _compose_lane_modchart(
        tmp_path, null_input, null_clock, [_basic(3.0, lane=1)], modchart_events=[],
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 1.0)
    assert threat_pool.count == 1
    entity_index = int(threat_pool.active_entity_indices()[0])
    transform_pool = composed.memory_manager.get_pool("transform")
    t_row = transform_pool.dense_row_of(entity_index)

    base_xs = lane_center_positions(config)
    x = float(transform_pool.active_view()["position_x"][t_row])
    assert abs(x - base_xs[1]) < 1e-6
