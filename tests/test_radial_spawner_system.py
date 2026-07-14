"""RadialRhythmSpawnerSystem: nasce na borda, chega ao anel do nucleo exatamente na batida."""
import math

import numpy as np


def _basic(timestamp: float, lane: int = 0, strength: float = 0.5) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": strength,
    }


def test_spawns_only_when_spawn_time_reached(compose, null_clock):
    composed, _ = compose([_basic(3.0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    # hit em 3.0 com approach 2.0 -> spawn devido em 1.0
    null_clock.set_now_seconds(0.5)
    composed.world.step(0.0)
    assert threat_pool.count == 0

    null_clock.set_now_seconds(1.0)
    composed.world.step(0.0)
    assert threat_pool.count == 1
    assert composed.spawner_system.is_finished


def test_spawn_position_velocity_and_rhythm_fields(compose, null_clock):
    composed, config = compose([_basic(3.0, lane=2)])
    null_clock.set_now_seconds(1.0)
    composed.world.step(0.0)

    memory_manager = composed.memory_manager
    threat_pool = memory_manager.get_pool("rhythm_threat")
    entity_index = int(threat_pool.active_entity_indices()[0])
    threat_row = threat_pool.active_view()[0]

    # lane 2 de 8 -> angulo pi/2 (tela, y para baixo): borda inferior
    center_x, center_y = config.center_xy
    expected_angle = 2.0 * math.pi * 2 / 8
    assert threat_row["target_hit_time_sec"] == 3.0
    assert abs(float(threat_row["spawn_angle_rad"]) - expected_angle) < 1e-5
    assert threat_row["judgment"] == 0
    assert composed.world.is_alive(int(threat_row["packed_handle"]))

    transform_view = memory_manager.get_pool("transform").active_view()
    t_row = memory_manager.get_pool("transform").dense_row_of(entity_index)
    assert abs(float(transform_view["position_x"][t_row]) - center_x) < 1e-3
    assert abs(float(transform_view["position_y"][t_row]) - (center_y + config.spawn_radius)) < 1e-3

    # velocidade: cobre spawn_radius - (nucleo + ameaca) no tempo restante (2.0s)
    travel = config.spawn_radius - (config.core_half_extent + 10.0)
    velocity_view = memory_manager.get_pool("velocity").active_view()
    v_row = memory_manager.get_pool("velocity").dense_row_of(entity_index)
    assert abs(float(velocity_view["linear_y"][v_row]) - (-travel / 2.0)) < 1e-3
    assert abs(float(velocity_view["linear_x"][v_row])) < 1e-3


def test_threat_edge_touches_core_ring_exactly_on_beat(compose, null_clock):
    composed, config = compose([_basic(3.0, lane=0)])
    null_clock.set_now_seconds(1.0)
    composed.world.step(0.0)

    # integra a fisica em passos fixos ate o instante exato da batida
    dt = 0.01
    steps = int(round((3.0 - 1.0) / dt))
    for _ in range(steps):
        null_clock.advance(dt)
        composed.world.step(dt)

    memory_manager = composed.memory_manager
    threat_pool = memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 1  # ainda viva: dentro da janela de acerto
    entity_index = int(threat_pool.active_entity_indices()[0])
    transform_pool = memory_manager.get_pool("transform")
    view = transform_pool.active_view()
    row = transform_pool.dense_row_of(entity_index)
    center_x, center_y = config.center_xy
    distance = math.hypot(
        float(view["position_x"][row]) - center_x, float(view["position_y"][row]) - center_y
    )
    contact_distance = config.core_half_extent + 10.0
    assert abs(distance - contact_distance) < 1.0  # tolerancia de 1px por discretizacao


def test_heavy_threat_uses_heavy_half_extent(compose, null_clock):
    composed, config = compose(
        [
            {
                "timestamp_seconds": 3.0,
                "threat_type": "rhythm_threat_heavy",
                "lane": 0,
                "strength": 0.9,
            }
        ]
    )
    null_clock.set_now_seconds(1.0)
    composed.world.step(0.0)

    memory_manager = composed.memory_manager
    threat_pool = memory_manager.get_pool("rhythm_threat")
    entity_index = int(threat_pool.active_entity_indices()[0])
    hitbox_pool = memory_manager.get_pool("hitbox")
    hitbox_view = hitbox_pool.active_view()
    row = hitbox_pool.dense_row_of(entity_index)
    assert float(hitbox_view["half_width"][row]) == 16.0
    assert float(threat_pool.active_view()["strength"][0]) == np.float32(0.9)
