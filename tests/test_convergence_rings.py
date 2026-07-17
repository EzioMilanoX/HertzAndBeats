"""Aneis de Convergencia do Defensor: encolhem matematicamente ate o anel de julgamento no ms do hit."""
from hertzbeats.components.texture_ids import TEX_CONVERGENCE_RING


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def test_ring_spawns_alongside_threat_at_spawn_radius(compose, null_clock, null_input):
    composed, config = compose([_basic(3.0)])
    null_clock.set_now_seconds(1.0)  # spawn devido (approach 2.0)
    null_input.poll()
    composed.world.step(0.0)

    ring_pool = composed.memory_manager.get_pool("convergence_ring")
    assert ring_pool.count == 1
    row = ring_pool.active_view()[0]
    assert row["target_hit_time_sec"] == 3.0
    assert abs(float(row["travel_seconds"]) - 2.0) < 1e-6

    entity_index = int(ring_pool.active_entity_indices()[0])
    transform_pool = composed.memory_manager.get_pool("transform")
    t_row = transform_pool.dense_row_of(entity_index)
    view = transform_pool.active_view()
    assert abs(float(view["scale_x"][t_row]) - config.spawn_radius / 8.0) < 1e-3

    sprite_pool = composed.memory_manager.get_pool("sprite")
    sprite_row = sprite_pool.dense_row_of(entity_index)
    assert int(sprite_pool.active_view()["texture_id"][sprite_row]) == TEX_CONVERGENCE_RING


def test_ring_radius_shrinks_linearly_to_the_judgment_ring(compose, null_clock, null_input):
    composed, config = compose([_basic(3.0)])
    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.0)

    ring_pool = composed.memory_manager.get_pool("convergence_ring")
    entity_index = int(ring_pool.active_entity_indices()[0])
    transform_pool = composed.memory_manager.get_pool("transform")
    t_row = transform_pool.dense_row_of(entity_index)

    judgment_ring_radius = config.core_half_extent + config.threat_half_extents["rhythm_threat_basic"]

    null_clock.set_now_seconds(2.0)  # metade do caminho (1.0 de 2.0s restantes)
    composed.world.step(0.016)
    expected_mid_radius = (config.spawn_radius + judgment_ring_radius) / 2.0
    actual = float(transform_pool.active_view()["scale_x"][t_row]) * 8.0
    assert abs(actual - expected_mid_radius) < 3.0


def test_ring_self_destructs_at_the_hit_instant(compose, null_clock, null_input):
    composed, _ = compose([_basic(3.0)])
    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.0)

    ring_pool = composed.memory_manager.get_pool("convergence_ring")
    assert ring_pool.count == 1

    null_clock.set_now_seconds(3.0)
    composed.world.step(0.016)
    assert ring_pool.count == 0  # convergiu: autodestruido no mesmo instante do hit


def test_ring_tint_matches_the_threat_it_warns_about(compose, null_clock, null_input):
    composed, _ = compose([
        {"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_heavy", "lane": 0, "strength": 0.9},
    ])
    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.0)

    memory_manager = composed.memory_manager
    ring_pool = memory_manager.get_pool("convergence_ring")
    threat_pool = memory_manager.get_pool("rhythm_threat")
    sprite_pool = memory_manager.get_pool("sprite")

    ring_entity = int(ring_pool.active_entity_indices()[0])
    threat_entity = int(threat_pool.active_entity_indices()[0])
    ring_sprite = sprite_pool.active_view()[sprite_pool.dense_row_of(ring_entity)]
    threat_sprite = sprite_pool.active_view()[sprite_pool.dense_row_of(threat_entity)]

    assert int(ring_sprite["tint_r"]) == int(threat_sprite["tint_r"])
    assert int(ring_sprite["tint_g"]) == int(threat_sprite["tint_g"])
    assert int(ring_sprite["tint_a"]) < int(threat_sprite["tint_a"])  # anel translucido, ameaca opaca
