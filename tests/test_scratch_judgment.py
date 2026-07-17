"""Notas de Scratch (Arcade 4K): energia continua de mouse mantem o hold; parar e MISS imediato."""
import dataclasses

from hertzbeats.bootstrap.rhythm_composition_root import compose_world

from tests.conftest import make_config, write_beatmap


def _heavy(t: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": t, "threat_type": "rhythm_threat_heavy", "lane": lane, "strength": 0.9}


def _compose_lanes(tmp_path, null_input, null_clock, threats):
    beatmap_path = write_beatmap(tmp_path / "l.beatmap.json", threats)
    config = dataclasses.replace(make_config(beatmap_path), game_mode="lanes")
    return compose_world(config, null_input, null_clock), config


def _scratch_cluster_threats():
    # 3 pesadas consecutivas (gaps de 0.1s) -- min_cluster_size=3,
    # cluster_gap_seconds=0.6 (defaults) -> vira UMA nota de Scratch
    # com inicio em 3.0 e fim em 3.2 + hold_tail_seconds(0.35) = 3.55.
    return [_heavy(3.0), _heavy(3.1), _heavy(3.2)]


def test_holding_energy_through_the_whole_scratch_scores_perfect(tmp_path, null_input, null_clock):
    composed, config = _compose_lanes(tmp_path, null_input, null_clock, _scratch_cluster_threats())
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    null_clock.set_now_seconds(1.0)  # spawn devido (3.0 - approach 2.0)
    null_input.poll()
    composed.world.step(0.0)
    assert threat_pool.count == 1
    row = threat_pool.dense_row_of(int(threat_pool.active_entity_indices()[0]))
    assert bool(threat_pool.active_view()["is_hold"][row]) is True

    # mantem energia acima do minimo do inicio (3.0) ate o fim (3.55) do hold
    null_input.set_axis("scratch_energy", 1.0)
    for now in (3.0, 3.2, 3.4, 3.56):
        null_clock.set_now_seconds(now)
        null_input.poll()
        composed.world.step(0.016)

    state = composed.game_state
    assert state.perfect_count == 1
    assert state.score == config.score_perfect
    assert threat_pool.count == 0


def test_stopping_mid_hold_is_an_immediate_miss(tmp_path, null_input, null_clock):
    composed, config = _compose_lanes(tmp_path, null_input, null_clock, _scratch_cluster_threats())
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    state = composed.game_state
    state.combo_count = 4

    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.0)
    assert threat_pool.count == 1

    null_input.set_axis("scratch_energy", 1.0)
    null_clock.set_now_seconds(3.0)  # hold comeca
    null_input.poll()
    composed.world.step(0.016)
    assert threat_pool.count == 1  # ainda em andamento

    null_input.set_axis("scratch_energy", 0.0)  # parou de raspar A MEIO do hold
    null_clock.set_now_seconds(3.2)  # bem antes do fim (3.55)
    null_input.poll()
    composed.world.step(0.016)

    assert threat_pool.count == 0  # MISS imediato -- nao esperou o fim do cluster
    assert state.miss_count == 1
    assert state.combo_count == 0


def test_scratch_note_ignores_lane_key_presses(tmp_path, null_input, null_clock):
    """So o `ScratchJudgmentSystem` julga notas `is_hold` -- apertar a
    tecla da coluna nao faz nada (nem acerta, nem conta como ghost tap
    que quebraria algo)."""
    composed, config = _compose_lanes(tmp_path, null_input, null_clock, _scratch_cluster_threats())
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.0)
    assert threat_pool.count == 1

    null_input.set_axis("scratch_energy", 0.0)  # sem raspar -- so a tecla
    null_clock.set_now_seconds(3.0)
    null_input.set_action_held("lane_0", True)
    null_input.poll()
    composed.world.step(0.016)

    # a tecla nao resgata a nota do MISS por energia zero (o hold ja comecou)
    assert composed.game_state.perfect_count == 0
    assert threat_pool.count == 0
    assert composed.game_state.miss_count == 1
