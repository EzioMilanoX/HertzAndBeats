"""Modo Arcade 4K: notas nas colunas certas, julgamento por tecla, ghost tap livre, MISS por varredura."""
import dataclasses

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.components.schemas import JUDGMENT_MISS

from tests.conftest import make_config, write_beatmap


def _note(timestamp: float, lane: int) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _compose_lanes(tmp_path, null_input, null_clock, threats):
    beatmap_path = write_beatmap(tmp_path / "l.beatmap.json", threats)
    config = dataclasses.replace(make_config(beatmap_path), game_mode="lanes")
    return compose_world(config, null_input, null_clock), config


def _press_lane(null_input, lane_index: int) -> None:
    null_input.set_action_held(f"lane_{lane_index}", True)
    null_input.poll()


def test_note_spawns_in_its_lane_and_reaches_judgment_line_on_beat(tmp_path, null_input, null_clock):
    composed, config = _compose_lanes(
        tmp_path, null_input, null_clock, [_note(3.0, lane=6)]  # lane 6 % 4 -> coluna 2
    )
    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.0)

    memory_manager = composed.memory_manager
    threat_pool = memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 1
    assert int(threat_pool.active_view()["lane"][0]) == 2  # reescrita para a coluna 0..3

    expected_x = config.center_xy[0] + (2 - 1.5) * config.lane_spacing
    entity_index = int(threat_pool.active_entity_indices()[0])
    transform_pool = memory_manager.get_pool("transform")
    row = transform_pool.dense_row_of(entity_index)
    assert abs(float(transform_pool.active_view()["position_x"][row]) - expected_x) < 1e-3

    # integra a queda ate a batida: o centro da nota cruza a linha de julgamento
    dt = 0.01
    for _ in range(int(round(2.0 / dt))):
        null_clock.advance(dt)
        composed.world.step(dt)
    judgment_line_y = config.window_height - config.judgment_line_offset
    row = transform_pool.dense_row_of(entity_index)
    assert abs(float(transform_pool.active_view()["position_y"][row]) - judgment_line_y) < 2.0


def test_correct_lane_key_on_beat_scores_perfect(tmp_path, null_input, null_clock):
    composed, _ = _compose_lanes(tmp_path, null_input, null_clock, [_note(3.0, lane=1)])
    null_clock.set_now_seconds(2.98)
    _press_lane(null_input, 1)
    composed.world.step(0.016)

    state = composed.game_state
    assert state.perfect_count == 1
    assert state.score == 300
    assert state.combo_count == 1
    assert composed.memory_manager.get_pool("rhythm_threat").count == 0


def test_wrong_lane_key_is_a_ghost_tap_without_penalty(tmp_path, null_input, null_clock):
    composed, _ = _compose_lanes(tmp_path, null_input, null_clock, [_note(3.0, lane=1)])
    state = composed.game_state
    state.combo_count = 7

    null_clock.set_now_seconds(2.98)
    _press_lane(null_input, 3)  # coluna errada
    composed.world.step(0.016)

    assert state.score == 0
    assert state.combo_count == 7  # ghost tap nao pune (estilo VSRG/FNF)
    assert composed.memory_manager.get_pool("rhythm_threat").count == 1


def test_two_simultaneous_lanes_need_two_keys(tmp_path, null_input, null_clock):
    composed, _ = _compose_lanes(
        tmp_path, null_input, null_clock, [_note(3.0, lane=0), _note(3.0, lane=2)]
    )
    null_clock.set_now_seconds(2.99)
    null_input.set_action_held("lane_0", True)
    null_input.set_action_held("lane_2", True)
    null_input.poll()
    composed.world.step(0.016)

    state = composed.game_state
    assert state.perfect_count == 2  # um acerto por coluna no mesmo frame
    assert state.combo_count == 2
    assert composed.memory_manager.get_pool("rhythm_threat").count == 0


def test_unpressed_note_becomes_miss_and_breaks_combo(tmp_path, null_input, null_clock):
    composed, _ = _compose_lanes(tmp_path, null_input, null_clock, [_note(3.0, lane=0)])
    state = composed.game_state
    state.combo_count = 5

    null_clock.set_now_seconds(3.2)  # 0.2s alem: janela de miss (0.15) vencida
    null_input.poll()
    composed.world.step(0.016)

    assert state.miss_count == 1
    assert state.combo_count == 0
    assert state.last_judgment == JUDGMENT_MISS
    assert composed.memory_manager.get_pool("rhythm_threat").count == 0
    assert state.health == 3  # arcade nao tira vida (combo e a punicao)
