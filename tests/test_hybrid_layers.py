"""Perfil hybrid no jogo: fusao kick+vocal com prioridade do kick e roteamento por camada no Arcade."""
import dataclasses

import numpy as np

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.offline.beatmap_pipeline import merge_note_layers, select_strongest_unquantized

from tests.conftest import make_config, write_beatmap


# ------------------------------------------------------------------ puras


def test_merge_gives_kick_priority_and_keeps_order():
    kick_times = np.array([1.0, 2.0, 3.0])
    kick_str = np.array([0.9, 0.8, 0.7])
    vocal_times = np.array([1.1, 1.5, 2.95])   # 1.1 e 2.95 colidem com kicks (sep 0.25)
    vocal_str = np.array([0.6, 0.5, 0.4])

    times, strengths, layers = merge_note_layers(
        kick_times, kick_str, vocal_times, vocal_str, min_separation_seconds=0.25
    )
    assert times.tolist() == [1.0, 1.5, 2.0, 3.0]  # vocais em conflito descartados
    assert layers == ["kick", "vocal", "kick", "kick"]
    assert strengths[1] == 0.5


def test_merge_with_empty_layers():
    empty = np.zeros(0)
    times, _, layers = merge_note_layers(
        np.array([1.0]), np.array([0.5]), empty, empty, 0.2
    )
    assert times.tolist() == [1.0] and layers == ["kick"]
    times, _, layers = merge_note_layers(
        empty, empty, np.array([2.0]), np.array([0.5]), 0.2
    )
    assert times.tolist() == [2.0] and layers == ["vocal"]


def test_unquantized_selection_respects_gap_budget_and_window():
    times = np.array([0.5, 1.0, 1.05, 2.0, 3.0, 9.0])
    strengths = np.array([0.9, 0.8, 0.85, 0.7, 0.6, 0.5])
    chosen = select_strongest_unquantized(
        times, strengths, min_start_seconds=0.8, max_end_seconds=5.0,
        min_gap_seconds=0.3, max_notes=3,
    )
    picked = times[chosen].tolist()
    assert picked == [1.05, 2.0, 3.0]  # 0.5 fora da janela; 1.0 colide com 1.05 (mais forte)


# ------------------------------------------------------- roteamento 4K


def _note(timestamp, lane, layer):
    return {
        "timestamp_seconds": timestamp, "threat_type": "rhythm_threat_basic",
        "lane": lane, "strength": 0.5, "layer": layer,
    }


def test_lanes_mode_routes_kick_to_edges_and_vocal_to_center(tmp_path, null_input, null_clock):
    beatmap_path = write_beatmap(tmp_path / "h.beatmap.json", [
        _note(3.0, 0, "kick"),    # par -> coluna 0
        _note(3.6, 1, "kick"),    # impar -> coluna 3
        _note(4.2, 0, "vocal"),   # par -> coluna 1
        _note(4.8, 1, "vocal"),   # impar -> coluna 2
    ])
    config = dataclasses.replace(make_config(beatmap_path), game_mode="lanes")
    composed = compose_world(config, null_input, null_clock)

    null_clock.set_now_seconds(3.0)  # todas ja spawnadas (spawns 1.0..2.8)
    null_input.poll()
    composed.world.step(0.0)

    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 4
    view = threat_pool.active_view()
    by_time = sorted(
        (float(view["target_hit_time_sec"][row]), int(view["lane"][row]))
        for row in range(4)
    )
    assert [lane for _, lane in by_time] == [0, 3, 1, 2]


def test_single_layer_beatmap_keeps_timbre_lanes(tmp_path, null_input, null_clock):
    """Mapa groove puro (uma camada so): roteamento desligado, colunas
    seguem o timbre 0..3 -- nunca colapsar tudo em 2 colunas."""
    beatmap_path = write_beatmap(tmp_path / "g.beatmap.json", [
        _note(3.0, 0, "kick"), _note(3.6, 1, "kick"),
        _note(4.2, 2, "kick"), _note(4.8, 3, "kick"),
    ])
    config = dataclasses.replace(make_config(beatmap_path), game_mode="lanes")
    composed = compose_world(config, null_input, null_clock)

    null_clock.set_now_seconds(3.0)
    null_input.poll()
    composed.world.step(0.0)

    view = composed.memory_manager.get_pool("rhythm_threat").active_view()
    lanes = sorted(int(view["lane"][row]) for row in range(4))
    assert lanes == [0, 1, 2, 3]