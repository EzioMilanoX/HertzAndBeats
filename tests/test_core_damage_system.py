"""CoreDamageSystem: punicao via CollisionSystem quando a ameaca passa do ponto; Dash com i-frames."""
from hertzbeats.components.schemas import JUDGMENT_DODGED, JUDGMENT_MISS


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _spawn_and_park_threat_at_core(composed, config, null_clock):
    """Faz o spawn (dt=0, sem fisica) e teleporta a ameaca para o centro,
    simulando 'passou do ponto e bateu no nucleo'."""
    null_clock.set_now_seconds(1.0)
    composed.world.step(0.0)
    memory_manager = composed.memory_manager
    threat_pool = memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 1
    entity_index = int(threat_pool.active_entity_indices()[0])
    transform_pool = memory_manager.get_pool("transform")
    row = transform_pool.dense_row_of(entity_index)
    center_x, center_y = config.center_xy
    transform_pool.active_view()["position_x"][row] = center_x
    transform_pool.active_view()["position_y"][row] = center_y


def test_overdue_collision_damages_and_breaks_combo(compose, null_clock, null_input):
    composed, config = compose([_basic(3.0)])
    _spawn_and_park_threat_at_core(composed, config, null_clock)
    state = composed.game_state
    state.combo_count = 5

    null_clock.set_now_seconds(3.12)  # vencida (0.12 > good 0.10), antes do sweep (0.15)
    null_input.poll()
    composed.world.step(0.0)

    assert state.health == 2
    assert state.miss_count == 1
    assert state.combo_count == 0
    assert state.last_judgment == JUDGMENT_MISS
    assert composed.memory_manager.get_pool("rhythm_threat").count == 0


def test_overdue_collision_triggers_camera_shake(compose, null_clock, null_input):
    composed, config = compose([_basic(3.0)])
    _spawn_and_park_threat_at_core(composed, config, null_clock)

    null_clock.set_now_seconds(3.12)
    null_input.poll()
    composed.world.step(0.0)

    assert composed.game_state.shake_intensity == config.core_damage_shake_px


def test_collision_within_late_hit_window_does_not_punish(compose, null_clock, null_input):
    composed, config = compose([_basic(3.0)])
    _spawn_and_park_threat_at_core(composed, config, null_clock)

    null_clock.set_now_seconds(3.05)  # overlap existe, mas jogador ainda pode acertar
    null_input.poll()
    composed.world.step(0.0)

    state = composed.game_state
    assert state.health == 3
    assert state.miss_count == 0
    assert composed.memory_manager.get_pool("rhythm_threat").count == 1


def test_dash_iframes_dodge_without_damage_or_combo_break(compose, null_clock, null_input):
    composed, config = compose([_basic(3.0)])
    _spawn_and_park_threat_at_core(composed, config, null_clock)
    state = composed.game_state
    state.combo_count = 5

    null_clock.set_now_seconds(3.12)
    null_input.set_action_held("dash", True)
    null_input.poll()  # borda de pressao do dash neste frame
    composed.world.step(0.016)

    assert state.health == 3
    assert state.dodge_count == 1
    assert state.miss_count == 0
    assert state.combo_count == 5
    assert composed.memory_manager.get_pool("rhythm_threat").count == 0
    # Auditoria de Game Design (Tolerancia Organica): antes, um dodge nao
    # dava NENHUM feedback -- `last_judgment` nunca virava DODGED.
    assert state.last_judgment == JUDGMENT_DODGED
