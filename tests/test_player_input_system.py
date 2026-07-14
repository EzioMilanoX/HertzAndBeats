"""PlayerInputSystem e afinacoes de mira: crosshair NO anel de julgamento, dash com cooldown, latencia."""
import math

from hertzbeats.components.schemas import JUDGMENT_PERFECT


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def test_crosshair_orbits_exactly_on_the_judgment_ring(compose, null_clock, null_input):
    """'Atire quando a ameaca tocar a sua mira' e literal: o raio de
    orbita do crosshair == raio de contato (nucleo + ameaca basica)."""
    composed, config = compose([_basic(99.0)])
    null_input.set_axis("aim_x", 0.0)
    null_input.set_axis("aim_y", 1.0)  # mirando para baixo (tela, y cresce para baixo)
    null_input.poll()
    composed.world.step(0.016)

    transform_pool = composed.memory_manager.get_pool("transform")
    row = transform_pool.dense_row_of(composed.crosshair_entity_index)
    view = transform_pool.active_view()
    center_x, center_y = config.center_xy
    ring_radius = config.core_half_extent + config.threat_half_extents["rhythm_threat_basic"]
    assert abs(float(view["position_x"][row]) - center_x) < 1e-3
    assert abs(float(view["position_y"][row]) - (center_y + ring_radius)) < 1e-3


def test_dash_cooldown_blocks_immediate_second_dash(compose, null_clock, null_input):
    composed, config = compose([_basic(99.0)])
    player_pool = composed.memory_manager.get_pool("player_state")
    row = player_pool.dense_row_of(composed.player_entity_index)

    null_input.set_action_held("dash", True)
    null_input.poll()
    composed.world.step(0.016)
    assert float(player_pool.active_view()["iframe_timer_sec"][row]) > 0.0

    # solta, espera os i-frames acabarem (mas nao o cooldown) e tenta de novo
    null_input.set_action_held("dash", False)
    null_input.poll()
    for _ in range(20):  # 0.32s > dash_duration 0.25s; cooldown 0.8s ainda ativo
        composed.world.step(0.016)
    assert float(player_pool.active_view()["iframe_timer_sec"][row]) == 0.0

    null_input.set_action_held("dash", True)
    null_input.poll()
    composed.world.step(0.016)
    assert float(player_pool.active_view()["iframe_timer_sec"][row]) == 0.0  # bloqueado pelo cooldown


def test_output_latency_compensation_shifts_judgment_window(compose, null_clock, null_input):
    """Com latencia de saida calibrada, o instante EFETIVO e
    `now - latencia`: um clique em now=3.03 com latencia 0.06 julga a
    batida de 3.0 como delta -0.03 -> PERFECT."""
    composed, _ = compose([_basic(3.0, lane=0)])
    null_clock.calibrate_latency(0.06)

    null_clock.set_now_seconds(3.03)
    null_input.set_axis("aim_x", 1.0)
    null_input.set_axis("aim_y", 0.0)
    null_input.set_action_held("fire", True)
    null_input.poll()
    composed.world.step(0.016)

    assert composed.game_state.last_judgment == JUDGMENT_PERFECT
    assert composed.game_state.perfect_count == 1
