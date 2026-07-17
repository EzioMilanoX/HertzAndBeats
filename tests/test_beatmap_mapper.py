"""Mapeador v2 (funcoes puras, sem librosa): grade de batidas, snap, selecao e lanes por timbre."""
import numpy as np

from hertzbeats.offline.beatmap_pipeline import (
    assign_lanes,
    build_beat_grid,
    select_slots,
    snap_onsets_to_grid,
)


def test_grid_subdivides_beats_into_eighths():
    beats = np.array([1.0, 1.5, 2.0])
    grid, on_beat = build_beat_grid(beats, subdivisions=2)
    assert grid.tolist() == [1.0, 1.25, 1.5, 1.75, 2.0]
    assert on_beat.tolist() == [True, False, True, False, True]


def test_notes_are_quantized_to_grid_never_to_raw_onsets():
    """A CORRECAO central da dessincronia: o onset (backtrackeado,
    adiantado) apenas VOTA; o tempo da nota e o ponto da grade."""
    beats = np.array([1.0, 1.5, 2.0, 2.5, 3.0])
    grid, on_beat = build_beat_grid(beats, subdivisions=2)
    # onsets deslocados -40ms das batidas (vies tipico de backtracking)
    onsets = np.array([0.96, 1.96, 2.96])
    strengths = np.array([0.9, 0.8, 0.7])
    slot_strengths, slot_has_event = snap_onsets_to_grid(grid, onsets, strengths, snap_tolerance=0.08)

    chosen = select_slots(
        grid, on_beat, slot_strengths, slot_has_event,
        min_start_seconds=0.0, max_end_seconds=10.0,
        min_gap_seconds=0.3, target_density_per_second=1.0,
    )
    note_times = grid[chosen].tolist()
    assert note_times == [1.0, 2.0, 3.0]  # cravadas na grade, nao em 0.96/1.96/2.96


def test_offgrid_onsets_beyond_tolerance_are_dropped():
    beats = np.array([1.0, 2.0, 3.0])
    grid, on_beat = build_beat_grid(beats, subdivisions=2)
    onsets = np.array([1.3])  # a 200ms de qualquer ponto (grade: 1.0, 1.5, 2.0...)
    slot_strengths, slot_has_event = snap_onsets_to_grid(grid, onsets, np.array([1.0]), snap_tolerance=0.08)
    assert not slot_has_event.any()


def test_selection_prefers_on_beat_over_stronger_offbeat():
    beats = np.array([1.0, 2.0, 3.0, 4.0])
    grid, on_beat = build_beat_grid(beats, subdivisions=2)
    slot_strengths = np.zeros(grid.shape[0])
    slot_has_event = np.zeros(grid.shape[0], dtype=bool)
    slot_strengths[2] = 0.5; slot_has_event[2] = True   # 2.0 (na batida)
    slot_strengths[3] = 0.7; slot_has_event[3] = True   # 2.5 (colcheia, mais forte mas sem o bonus)
    chosen = select_slots(
        grid, on_beat, slot_strengths, slot_has_event,
        min_start_seconds=0.0, max_end_seconds=10.0,
        min_gap_seconds=0.9, target_density_per_second=0.12,  # espaco para UMA nota
    )
    assert grid[chosen].tolist() == [2.0]


def test_empty_slots_never_become_notes():
    beats = np.array([1.0, 2.0, 3.0])
    grid, on_beat = build_beat_grid(beats, subdivisions=2)
    chosen = select_slots(
        grid, on_beat, np.zeros(grid.shape[0]), np.zeros(grid.shape[0], dtype=bool),
        min_start_seconds=0.0, max_end_seconds=10.0,
        min_gap_seconds=0.3, target_density_per_second=5.0,
    )
    assert chosen == []  # forca 0.9 em slot SEM evento tambem nao entraria


def test_lanes_follow_timbre_and_repeat_for_same_sound():
    times = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    centroids = np.array([200.0, 4000.0, 200.0, 4000.0, 900.0, 2000.0])
    lanes = assign_lanes(times, centroids, lane_count=4, anti_jack_gap_seconds=0.22)
    assert lanes[0] == lanes[2]  # mesmo som grave -> mesma lane
    assert lanes[1] == lanes[3]  # mesmo som agudo -> mesma lane
    assert lanes[0] < lanes[1]   # grave a esquerda do agudo


def test_anti_jack_bumps_impossible_repeats():
    times = np.array([1.0, 1.1])  # 100ms de gap: jack impossivel
    centroids = np.array([200.0, 210.0])  # mesmo timbre -> mesma lane crua
    lanes = assign_lanes(times, centroids, lane_count=4, anti_jack_gap_seconds=0.22)
    assert lanes[0] != lanes[1]
