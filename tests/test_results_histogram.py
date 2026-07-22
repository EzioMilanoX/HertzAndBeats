"""Acessibilidade -- Histograma de Resultados: distribuicao de precisao sobre o RingBuffer de deltas."""
import math

import numpy as np
import pytest

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.bootstrap.hertz_game_loop import FLOW_RESULTS
from hertzbeats.game_state import (
    RESULTS_HISTOGRAM_BIN_COUNT,
    RESULTS_HISTOGRAM_RANGE_SECONDS,
    compute_hit_error_histogram,
)

from tests.test_match_flow import _basic, _goto_preflight, _play_to_results, _press, flow_game  # noqa: F401


def test_empty_buffer_returns_all_zero_bins():
    buffer = np.zeros(16, dtype=np.float64)
    histogram = compute_hit_error_histogram(buffer, filled_count=0)
    assert histogram == (0,) * RESULTS_HISTOGRAM_BIN_COUNT


def test_a_single_on_time_hit_lands_in_the_center_bin():
    buffer = np.zeros(16, dtype=np.float64)
    buffer[0] = 0.0
    histogram = compute_hit_error_histogram(buffer, filled_count=1)
    assert sum(histogram) == 1
    assert histogram[RESULTS_HISTOGRAM_BIN_COUNT // 2] == 1


def test_hits_out_of_range_are_clamped_into_the_edge_bins():
    buffer = np.zeros(16, dtype=np.float64)
    buffer[0] = -10.0  # bem cedo, muito alem da faixa
    buffer[1] = 10.0  # bem tarde, idem
    histogram = compute_hit_error_histogram(buffer, filled_count=2)
    assert sum(histogram) == 2
    assert histogram[0] == 1  # extremo cedo
    assert histogram[-1] == 1  # extremo tarde


def test_only_the_filled_slots_are_counted_never_the_rest_of_the_ring_buffer():
    buffer = np.zeros(16, dtype=np.float64)
    buffer[0] = 0.0
    buffer[1] = 0.05  # fora de filled_count -- nao deve contar
    histogram = compute_hit_error_histogram(buffer, filled_count=1)
    assert sum(histogram) == 1


def test_bin_count_matches_the_declared_constant():
    buffer = np.zeros(4, dtype=np.float64)
    histogram = compute_hit_error_histogram(buffer, filled_count=0)
    assert len(histogram) == RESULTS_HISTOGRAM_BIN_COUNT


# -- Integracao real via HertzGameLoop ---------------------------------------


def test_a_perfect_clear_produces_a_histogram_with_one_hit_in_the_center(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0, lane=0)]])
    _goto_preflight(loop, null_input, "campaign", 0)
    _press(loop, null_input, "confirm")

    _play_to_results(loop, clock, null_input)
    assert loop.flow == FLOW_RESULTS

    assert sum(loop._results_histogram) == 1
    assert loop._results_histogram[RESULTS_HISTOGRAM_BIN_COUNT // 2] == 1


# -- Renderer real ------------------------------------------------------


def test_draw_hit_error_histogram_is_a_no_op_when_empty():
    renderer = HBPygameRenderer()
    renderer.initialize(160, 160, "test")
    renderer._surface.fill((8, 6, 20))
    y = 60
    before = [tuple(renderer._surface.get_at((x, y + 20)))[:3] for x in range(160)]

    renderer._overlay_hit_error_histogram = (0,) * RESULTS_HISTOGRAM_BIN_COUNT
    renderer._draw_hit_error_histogram(80, y)

    after = [tuple(renderer._surface.get_at((x, y + 20)))[:3] for x in range(160)]
    assert before == after


def test_draw_hit_error_histogram_draws_bars_when_populated():
    renderer = HBPygameRenderer()
    renderer.initialize(160, 160, "test")
    renderer._surface.fill((8, 6, 20))
    y = 60

    histogram = [0] * RESULTS_HISTOGRAM_BIN_COUNT
    histogram[RESULTS_HISTOGRAM_BIN_COUNT // 2] = 5
    renderer._overlay_hit_error_histogram = tuple(histogram)
    renderer._draw_hit_error_histogram(80, y)

    row = [tuple(renderer._surface.get_at((x, y + 40)))[:3] for x in range(160)]
    assert any(pixel != (8, 6, 20) for pixel in row)
