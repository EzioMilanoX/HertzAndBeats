"""Acessibilidade a daltonismo na Polaridade: forma (triangulo/quadrado) nunca depende so da cor."""
import dataclasses

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.components.texture_ids import (
    TEX_PLAYER_CORE_BLUE,
    TEX_PLAYER_CORE_PINK,
    TEX_THREAT_BASIC,
    TEX_THREAT_HEAVY,
    TEX_THREAT_POLARITY_BLUE,
    TEX_THREAT_POLARITY_PINK,
)

from tests.conftest import make_config, write_beatmap


def _basic(timestamp: float, lane: int) -> dict:
    return {"timestamp_seconds": timestamp, "threat_type": "rhythm_threat_basic", "lane": lane, "strength": 0.5}


def _heavy(timestamp: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": timestamp, "threat_type": "rhythm_threat_heavy", "lane": lane, "strength": 0.9}


def _compose_polarity(tmp_path, null_input, null_clock, threats):
    beatmap_path = write_beatmap(tmp_path / "p.beatmap.json", threats)
    config = dataclasses.replace(make_config(beatmap_path), polarity_enabled=True)
    return compose_world(config, null_input, null_clock), config


def _spawn(composed, null_clock, null_input, at_seconds: float) -> None:
    null_clock.set_now_seconds(at_seconds)
    null_input.poll()
    composed.world.step(0.0)


def test_blue_lane_threat_gets_blue_shape_and_real_tint(tmp_path, null_input, null_clock):
    composed, _ = _compose_polarity(tmp_path, null_input, null_clock, [_basic(3.0, lane=6)])  # >=4: azul
    _spawn(composed, null_clock, null_input, 1.0)
    sprite_pool = composed.memory_manager.get_pool("sprite")
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    entity_index = int(threat_pool.active_entity_indices()[0])
    row = sprite_pool.dense_row_of(entity_index)
    view = sprite_pool.active_view()

    assert int(view["texture_id"][row]) == TEX_THREAT_POLARITY_BLUE
    assert (int(view["tint_r"][row]), int(view["tint_g"][row]), int(view["tint_b"][row])) == (70, 140, 255)


def test_pink_lane_threat_gets_pink_shape_and_real_tint(tmp_path, null_input, null_clock):
    composed, _ = _compose_polarity(tmp_path, null_input, null_clock, [_basic(3.0, lane=1)])  # <4: rosa
    _spawn(composed, null_clock, null_input, 1.0)
    sprite_pool = composed.memory_manager.get_pool("sprite")
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    entity_index = int(threat_pool.active_entity_indices()[0])
    row = sprite_pool.dense_row_of(entity_index)
    view = sprite_pool.active_view()

    assert int(view["texture_id"][row]) == TEX_THREAT_POLARITY_PINK
    assert (int(view["tint_r"][row]), int(view["tint_g"][row]), int(view["tint_b"][row])) == (255, 90, 190)


def test_heavy_threat_keeps_heavy_visual_even_with_polarity_enabled(tmp_path, null_input, null_clock):
    composed, _ = _compose_polarity(tmp_path, null_input, null_clock, [_heavy(3.0, lane=6)])
    _spawn(composed, null_clock, null_input, 1.0)
    sprite_pool = composed.memory_manager.get_pool("sprite")
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    entity_index = int(threat_pool.active_entity_indices()[0])
    row = sprite_pool.dense_row_of(entity_index)
    assert int(sprite_pool.active_view()["texture_id"][row]) == TEX_THREAT_HEAVY


def test_shapes_are_not_used_when_polarity_is_disabled(tmp_path, null_input, null_clock):
    beatmap_path = write_beatmap(tmp_path / "d.beatmap.json", [_basic(3.0, lane=6)])
    composed = compose_world(make_config(beatmap_path), null_input, null_clock)
    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.0)

    sprite_pool = composed.memory_manager.get_pool("sprite")
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    entity_index = int(threat_pool.active_entity_indices()[0])
    row = sprite_pool.dense_row_of(entity_index)
    assert int(sprite_pool.active_view()["texture_id"][row]) == TEX_THREAT_BASIC


def test_core_shape_changes_to_blue_then_pink_on_fire(tmp_path, null_input, null_clock):
    # misfire_jam_seconds=0.0: um clique sem candidata (arena "vazia" a
    # essa distancia de tempo) NAO pode emperrar a arma entre os dois
    # disparos deste teste -- so nos importa o TROCAR de forma do
    # nucleo, nao o veredito do tiro em si.
    beatmap_path = write_beatmap(tmp_path / "p.beatmap.json", [_basic(99.0, lane=6)])
    config = dataclasses.replace(
        make_config(beatmap_path), polarity_enabled=True, misfire_jam_seconds=0.0
    )
    composed = compose_world(config, null_input, null_clock)
    sprite_pool = composed.memory_manager.get_pool("sprite")
    core_row = sprite_pool.dense_row_of(composed.player_entity_index)

    null_input.set_action_held("fire", True)
    null_input.poll()
    composed.world.step(0.016)
    assert int(sprite_pool.active_view()["texture_id"][core_row]) == TEX_PLAYER_CORE_BLUE

    null_input.set_action_held("fire", False)
    null_input.poll()
    composed.world.step(0.016)
    null_input.set_action_held("fire_alt", True)
    null_input.poll()
    composed.world.step(0.016)
    assert int(sprite_pool.active_view()["texture_id"][core_row]) == TEX_PLAYER_CORE_PINK
