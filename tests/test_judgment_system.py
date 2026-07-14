"""JudgmentSystem: janelas PERFECT/GOOD/MISS, cone de mira 360 e placar zero-GC."""
from hertzbeats.components.schemas import JUDGMENT_MISS, JUDGMENT_PERFECT


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _aim_and_fire(null_input, aim_x: float, aim_y: float, fire: bool) -> None:
    null_input.set_axis("aim_x", aim_x)
    null_input.set_axis("aim_y", aim_y)
    null_input.set_action_held("fire", fire)
    null_input.poll()


def test_perfect_hit_within_50ms(compose, null_clock, null_input):
    composed, _ = compose([_basic(3.0, lane=0)])  # lane 0 -> angulo 0 (borda direita)
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    null_clock.set_now_seconds(2.97)  # delta = 0.03 < 0.05
    _aim_and_fire(null_input, 1.0, 0.0, fire=True)
    composed.world.step(0.016)

    state = composed.game_state
    assert state.score == 300
    assert state.combo_count == 1
    assert state.perfect_count == 1
    assert state.last_judgment == JUDGMENT_PERFECT
    assert threat_pool.count == 0  # destruida no flush do mesmo step


def test_good_hit_within_100ms(compose, null_clock, null_input):
    composed, _ = compose([_basic(3.0, lane=0)])

    null_clock.set_now_seconds(2.92)  # delta = 0.08: Good
    _aim_and_fire(null_input, 1.0, 0.0, fire=True)
    composed.world.step(0.016)

    state = composed.game_state
    assert state.score == 100
    assert state.good_count == 1
    assert state.combo_count == 1


def test_fire_outside_aim_cone_does_not_hit(compose, null_clock, null_input):
    composed, _ = compose([_basic(3.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    null_clock.set_now_seconds(2.97)
    _aim_and_fire(null_input, 0.0, -1.0, fire=True)  # mira 90 graus fora
    composed.world.step(0.016)

    assert composed.game_state.score == 0
    assert threat_pool.count == 1  # continua viva


def test_fire_outside_time_window_does_not_hit(compose, null_clock, null_input):
    composed, _ = compose([_basic(3.0, lane=0)])

    null_clock.set_now_seconds(2.80)  # delta = 0.20 > good window
    _aim_and_fire(null_input, 1.0, 0.0, fire=True)
    composed.world.step(0.016)

    assert composed.game_state.score == 0


def test_overdue_threat_becomes_miss_and_breaks_combo(compose, null_clock, null_input):
    composed, _ = compose([_basic(3.0, lane=0), _basic(3.5, lane=1)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    state = composed.game_state
    state.combo_count = 9  # combo previo qualquer

    null_clock.set_now_seconds(3.16)  # 3.0 venceu (0.16 > 0.15); 3.5 ainda viva
    null_input.poll()
    composed.world.step(0.016)

    assert state.miss_count == 1
    assert state.combo_count == 0
    assert state.last_judgment == JUDGMENT_MISS
    assert threat_pool.count == 1


def test_two_hits_build_combo_and_pick_closest_threat(compose, null_clock, null_input):
    composed, _ = compose([_basic(3.0, lane=0), _basic(3.4, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    null_clock.set_now_seconds(3.01)
    _aim_and_fire(null_input, 1.0, 0.0, fire=True)
    composed.world.step(0.016)
    assert composed.game_state.perfect_count == 1
    assert threat_pool.count == 1
    # a ameaca restante e a de 3.4 (a mais proxima foi consumida)
    assert float(threat_pool.active_view()["target_hit_time_sec"][0]) == 3.4

    _aim_and_fire(null_input, 1.0, 0.0, fire=False)  # solta o botao
    null_clock.set_now_seconds(3.38)
    composed.world.step(0.016)
    _aim_and_fire(null_input, 1.0, 0.0, fire=True)
    null_clock.set_now_seconds(3.42)
    composed.world.step(0.016)

    state = composed.game_state
    assert state.perfect_count == 2
    assert state.combo_count == 2
    assert state.max_combo == 2
    assert state.score == 600
