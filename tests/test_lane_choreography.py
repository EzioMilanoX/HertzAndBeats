"""Pistas Dinamicas: senoide amortecida causal (compute_lane_sway) + reposicionamento de colunas em composicao."""
import dataclasses
import math

import numpy as np

from hertzbeats.bootstrap.rhythm_composition_root import compose_world, lane_center_positions
from hertzbeats.systems.lane_choreography_system import compute_lane_sway

from tests.conftest import make_config, write_beatmap

_HEAVY_TYPE_IDS = {"rhythm_threat_basic": 0, "rhythm_threat_heavy": 1}


def test_zero_sway_with_no_trigger_times():
    assert compute_lane_sway(5.0, np.array([]), amplitude_px=30.0, decay_per_second=2.0) == 0.0


def test_zero_sway_before_any_trigger_fires():
    # o unico evento ainda esta no FUTURO -- a reacao e causal, nunca antecipatoria
    trigger_times = np.array([5.0])
    assert compute_lane_sway(4.0, trigger_times, amplitude_px=30.0, decay_per_second=2.0) == 0.0


def test_matches_the_damped_sine_formula_at_a_known_instant():
    trigger_times = np.array([0.0])
    now = 0.1
    amplitude = 10.0
    decay = 2.0
    frequency = 6.0
    expected = amplitude * math.exp(-decay * now) * math.sin(2.0 * math.pi * frequency * now)
    actual = compute_lane_sway(now, trigger_times, amplitude, decay, frequency)
    assert math.isclose(actual, expected, rel_tol=1e-9)


def test_amplitude_scales_the_result_linearly():
    trigger_times = np.array([0.0])
    base = compute_lane_sway(0.05, trigger_times, amplitude_px=10.0, decay_per_second=2.0)
    doubled = compute_lane_sway(0.05, trigger_times, amplitude_px=20.0, decay_per_second=2.0)
    assert math.isclose(doubled, base * 2.0, rel_tol=1e-9)


def test_contributions_from_multiple_triggers_sum():
    amplitude, decay, freq = 10.0, 2.0, 6.0
    now = 0.5
    trigger_times = np.array([0.0, 0.3])
    combined = compute_lane_sway(now, trigger_times, amplitude, decay, freq)
    individual_a = compute_lane_sway(now, np.array([0.0]), amplitude, decay, freq)
    individual_b = compute_lane_sway(now, np.array([0.3]), amplitude, decay, freq)
    assert math.isclose(combined, individual_a + individual_b, rel_tol=1e-9)


def _compose_lanes(tmp_path, null_input, null_clock, threats):
    beatmap_path = write_beatmap(tmp_path / "l.beatmap.json", threats)
    config = dataclasses.replace(make_config(beatmap_path), game_mode="lanes")
    return compose_world(config, null_input, null_clock), config


def _heavy(t: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": t, "threat_type": "rhythm_threat_heavy", "lane": lane, "strength": 0.9}


def test_lane_choreography_system_is_registered_and_sways_after_a_scratch_cluster(tmp_path, null_input, null_clock):
    """Integracao completa: um cluster de 3+ pesadas vira uma nota de
    Scratch (`lane_scratch_clustering`) cujo INICIO alimenta
    `LaneChoreographySystem` como gatilho de balanco -- a coluna
    correspondente se desloca do centro fixo logo apos o onset."""
    composed, config = _compose_lanes(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0), _heavy(3.1, lane=0), _heavy(3.2, lane=0)]
    )
    from hertzbeats.systems.lane_choreography_system import LaneChoreographySystem
    assert any(isinstance(s, LaneChoreographySystem) for s in composed.world._systems)

    lane_xs = lane_center_positions(config)
    # antes do cluster comecar: sem balanco, colunas na posicao base
    null_clock.set_now_seconds(0.5)
    null_input.poll()
    composed.world.step(0.016)

    transform_pool = composed.memory_manager.get_pool("transform")
    # localiza o receptor da lane 0 pela posicao Y fixa da linha de julgamento
    judgment_line_y = config.window_height - config.judgment_line_offset
    receptor_index = None
    for entity_index in range(1, config.entity_capacity):
        row = transform_pool.dense_row_of(entity_index)
        if row == -1:
            continue
        view = transform_pool.active_view()
        if (
            abs(float(view["position_y"][row]) - judgment_line_y) < 1e-6
            and abs(float(view["position_x"][row]) - float(lane_xs[0])) < 1e-6
        ):
            receptor_index = entity_index
            break
    assert receptor_index is not None

    # logo apos o INICIO do cluster (gatilho de sway em t=3.0): a coluna
    # deve ter se deslocado do centro fixo `lane_xs[0]`
    null_clock.set_now_seconds(3.02)
    null_input.poll()
    composed.world.step(0.016)
    row = transform_pool.dense_row_of(receptor_index)
    displaced_x = float(transform_pool.active_view()["position_x"][row])
    assert abs(displaced_x - float(lane_xs[0])) > 0.5
