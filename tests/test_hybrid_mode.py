"""Modo Hibrido: particao do beatmap por secao, dois spawners, juizes isolados por mode_tag."""
import dataclasses

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.components.schemas import MODE_TAG_DEFENDER, MODE_TAG_SURVIVAL

from tests.conftest import make_config, write_beatmap


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _compose_hybrid(tmp_path, null_input, null_clock, threats, section_seconds=10.0):
    beatmap_path = write_beatmap(tmp_path / "h.beatmap.json", threats)
    config = dataclasses.replace(
        make_config(beatmap_path), game_mode="hybrid", mixed_section_seconds=section_seconds
    )
    return compose_world(config, null_input, null_clock), config


def test_beatmap_is_partitioned_by_music_section(tmp_path, null_input, null_clock):
    # secoes de 10s: 4.0 e 8.0 (secao 0 -> radial); 14.0 (secao 1 -> parede); 24.0 (secao 2 -> radial)
    composed, _ = _compose_hybrid(
        tmp_path, null_input, null_clock,
        [_basic(4.0), _basic(8.0), _basic(14.0), _basic(24.0)],
    )
    radial_spawner, wall_spawner = composed.spawner_systems
    assert radial_spawner._hit_times.tolist() == [4.0, 8.0, 24.0]
    assert wall_spawner._hit_times.tolist() == [14.0]


def test_both_kinds_of_threat_coexist_with_their_tags(tmp_path, null_input, null_clock):
    # batidas coladas na fronteira da secao (10s): 9.9 -> radial, 10.1 -> parede;
    # em 9.95 ambas estao vivas e pendentes na MESMA pool
    composed, config = _compose_hybrid(
        tmp_path, null_input, null_clock, [_basic(9.9, lane=0), _basic(10.1, lane=0)]
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    null_clock.set_now_seconds(9.95)
    null_input.poll()
    composed.world.step(0.0)
    assert threat_pool.count == 2

    view = threat_pool.active_view()
    tags = sorted(int(view["mode_tag"][row]) for row in range(2))
    assert tags == [MODE_TAG_DEFENDER, MODE_TAG_SURVIVAL]

    # a parede e full-arena; a radial nao (distincao geometrica)
    hitbox_pool = composed.memory_manager.get_pool("hitbox")
    halves = sorted(
        float(hitbox_pool.active_view()["half_width"][hitbox_pool.dense_row_of(int(idx))])
        for idx in threat_pool.active_entity_indices()
    )
    assert halves[0] < 20.0
    assert halves[1] == config.window_width / 2.0


def test_defender_judge_never_touches_walls(tmp_path, null_input, null_clock):
    """A varredura de MISS do juiz radial nao pode destruir/punir uma
    parede que ja passou do target (paredes vivem ate expirar)."""
    composed, _ = _compose_hybrid(tmp_path, null_input, null_clock, [_basic(14.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    state = composed.game_state

    null_clock.set_now_seconds(12.5)
    null_input.poll()
    composed.world.step(0.0)
    assert threat_pool.count == 1  # parede spawnada

    # neutraliza a colisao do jogador (unidade: só o sweep interessa)
    hitbox_pool = composed.memory_manager.get_pool("hitbox")
    row = hitbox_pool.dense_row_of(composed.player_entity_index)
    hitbox_pool.active_view()["collision_layer"][row] = 0
    hitbox_pool.active_view()["collision_mask"][row] = 0

    null_clock.set_now_seconds(14.3)  # 0.3s alem do target: sweep radial teria destruido
    composed.world.step(0.016)
    assert threat_pool.count == 1  # parede intacta (dono e o juiz de sobrevivencia)
    assert state.miss_count == 0

    null_clock.set_now_seconds(16.6)  # alem do expire (~14 + 2)
    composed.world.step(0.016)
    assert threat_pool.count == 0
    assert state.survive_count == 1  # expirou pendente -> SURVIVED


def test_radial_hit_works_normally_in_hybrid(tmp_path, null_input, null_clock):
    composed, _ = _compose_hybrid(tmp_path, null_input, null_clock, [_basic(4.0, lane=0)])

    null_clock.set_now_seconds(3.98)
    null_input.set_axis("aim_x", 1.0)
    null_input.set_axis("aim_y", 0.0)
    null_input.set_action_held("fire", True)
    null_input.poll()
    composed.world.step(0.016)

    state = composed.game_state
    assert state.perfect_count == 1
    assert state.score == 300


def test_results_requires_both_spawners_finished(tmp_path, null_input, null_clock):
    composed, _ = _compose_hybrid(
        tmp_path, null_input, null_clock, [_basic(4.0, lane=0), _basic(14.0, lane=0)]
    )
    radial_spawner, wall_spawner = composed.spawner_systems

    null_clock.set_now_seconds(3.0)
    null_input.poll()
    composed.world.step(0.0)
    assert radial_spawner.is_finished
    assert not wall_spawner.is_finished
    assert not composed.all_spawners_finished

    null_clock.set_now_seconds(12.5)
    composed.world.step(0.0)
    assert composed.all_spawners_finished
