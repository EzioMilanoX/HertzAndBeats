"""Clustering puro de pesadas -> notas de Scratch (fusao game-side, sem tocar o beatmap.json)."""
from pathlib import Path

from ouroboros.rhythm.runtime.beatmap_loader import BeatmapLoader

from hertzbeats.lane_scratch_clustering import build_lane_schedule_with_scratches

from tests.conftest import write_beatmap

_THREAT_TYPE_IDS = {"rhythm_threat_basic": 0, "rhythm_threat_heavy": 1}
_HEAVY_ID = _THREAT_TYPE_IDS["rhythm_threat_heavy"]


def _load(tmp_path: Path, threats: list):
    beatmap_path = write_beatmap(tmp_path / "cluster.beatmap.json", threats)
    scheduled = BeatmapLoader(_THREAT_TYPE_IDS).load(beatmap_path)
    hit_times = scheduled["timestamp_seconds"].copy()
    return scheduled, hit_times


def _heavy(t: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": t, "threat_type": "rhythm_threat_heavy", "lane": lane, "strength": 0.9}


def _basic(t: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": t, "threat_type": "rhythm_threat_basic", "lane": lane, "strength": 0.5}


def test_cluster_of_three_or_more_consecutive_heavies_becomes_one_scratch_note(tmp_path):
    scheduled, hit_times = _load(tmp_path, [_heavy(1.0), _heavy(1.2), _heavy(1.4), _heavy(1.6)])
    scheduled_out, hit_times_out, is_hold_out, hold_end_out = build_lane_schedule_with_scratches(
        scheduled, hit_times, _HEAVY_ID,
        cluster_gap_seconds=0.6, min_cluster_size=3, hold_tail_seconds=0.35,
    )

    assert scheduled_out.shape[0] == 1
    assert bool(is_hold_out[0]) is True
    assert hit_times_out[0] == 1.0  # inicio do cluster
    assert abs(hold_end_out[0] - (1.6 + 0.35)) < 1e-9  # fim do cluster + folga


def test_cluster_smaller_than_minimum_stays_as_individual_notes(tmp_path):
    scheduled, hit_times = _load(tmp_path, [_heavy(1.0), _heavy(1.2)])  # so 2: abaixo do minimo (3)
    scheduled_out, hit_times_out, is_hold_out, hold_end_out = build_lane_schedule_with_scratches(
        scheduled, hit_times, _HEAVY_ID,
        cluster_gap_seconds=0.6, min_cluster_size=3, hold_tail_seconds=0.35,
    )

    assert scheduled_out.shape[0] == 2
    assert not bool(is_hold_out[0])
    assert not bool(is_hold_out[1])
    assert list(hit_times_out) == [1.0, 1.2]


def test_gap_larger_than_threshold_splits_into_two_clusters(tmp_path):
    threats = [
        _heavy(1.0), _heavy(1.1), _heavy(1.2),  # cluster A (gaps de 0.1)
        _heavy(1.9), _heavy(2.0), _heavy(2.1),  # cluster B: gap A->B = 0.7 > 0.6
    ]
    scheduled, hit_times = _load(tmp_path, threats)
    scheduled_out, hit_times_out, is_hold_out, hold_end_out = build_lane_schedule_with_scratches(
        scheduled, hit_times, _HEAVY_ID,
        cluster_gap_seconds=0.6, min_cluster_size=3, hold_tail_seconds=0.35,
    )

    assert scheduled_out.shape[0] == 2
    assert bool(is_hold_out[0]) and bool(is_hold_out[1])
    assert hit_times_out[0] == 1.0
    assert abs(hold_end_out[0] - (1.2 + 0.35)) < 1e-9
    assert hit_times_out[1] == 1.9
    assert abs(hold_end_out[1] - (2.1 + 0.35)) < 1e-9


def test_non_heavy_notes_pass_through_unchanged(tmp_path):
    threats = [_basic(1.0, lane=0), _basic(1.5, lane=1), _basic(2.0, lane=2)]
    scheduled, hit_times = _load(tmp_path, threats)
    scheduled_out, hit_times_out, is_hold_out, hold_end_out = build_lane_schedule_with_scratches(
        scheduled, hit_times, _HEAVY_ID,
        cluster_gap_seconds=0.6, min_cluster_size=3, hold_tail_seconds=0.35,
    )

    assert scheduled_out.shape[0] == 3
    assert not any(is_hold_out)
    assert all(v == 0.0 for v in hold_end_out)
    assert list(hit_times_out) == [1.0, 1.5, 2.0]


def test_basic_notes_around_a_cluster_preserve_temporal_order(tmp_path):
    threats = [
        _basic(0.5, lane=0),
        _heavy(1.0), _heavy(1.1), _heavy(1.2),
        _basic(2.0, lane=3),
    ]
    scheduled, hit_times = _load(tmp_path, threats)
    scheduled_out, hit_times_out, is_hold_out, hold_end_out = build_lane_schedule_with_scratches(
        scheduled, hit_times, _HEAVY_ID,
        cluster_gap_seconds=0.6, min_cluster_size=3, hold_tail_seconds=0.35,
    )

    assert scheduled_out.shape[0] == 3  # basic, scratch-fundida, basic
    assert list(hit_times_out) == [0.5, 1.0, 2.0]
    assert [bool(v) for v in is_hold_out] == [False, True, False]
