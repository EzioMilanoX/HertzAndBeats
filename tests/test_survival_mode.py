"""Modo Sobrevivencia: paredes cruzam o centro na batida; dano por toque, DODGED no dash, SURVIVED na expiracao."""
import dataclasses

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.components.schemas import JUDGMENT_MISS

from tests.conftest import make_config, write_beatmap


def _basic(timestamp: float, lane: int = 0, strength: float = 0.5) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": strength,
    }


def _compose_survival(tmp_path, null_input, null_clock, threats):
    beatmap_path = write_beatmap(tmp_path / "s.beatmap.json", threats)
    config = dataclasses.replace(make_config(beatmap_path), game_mode="survival")
    return compose_world(config, null_input, null_clock), config


def test_wall_crosses_arena_center_exactly_on_beat(tmp_path, null_input, null_clock):
    composed, config = _compose_survival(
        tmp_path, null_input, null_clock, [_basic(3.0, lane=0)]  # lane 0: horizontal, desce do topo
    )
    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.0)

    memory_manager = composed.memory_manager
    threat_pool = memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 1
    threat_row = threat_pool.active_view()[0]
    assert threat_row["target_hit_time_sec"] == 3.0
    assert float(threat_row["expire_time_sec"]) > 3.0

    # integra a fisica ate a batida: o centro da barra cruza o centro da arena
    dt = 0.01
    for _ in range(int(round(2.0 / dt))):
        null_clock.advance(dt)
        composed.world.step(dt)
    entity_index = int(threat_pool.active_entity_indices()[0])
    transform_pool = memory_manager.get_pool("transform")
    row = transform_pool.dense_row_of(entity_index)
    center_y = config.center_xy[1]
    assert abs(float(transform_pool.active_view()["position_y"][row]) - center_y) < 2.0

    # barra horizontal: hitbox cobre a largura toda da arena
    hitbox_pool = memory_manager.get_pool("hitbox")
    hb_row = hitbox_pool.dense_row_of(entity_index)
    assert float(hitbox_pool.active_view()["half_width"][hb_row]) == config.window_width / 2.0


def test_touching_wall_damages_and_breaks_combo(tmp_path, null_input, null_clock):
    composed, config = _compose_survival(tmp_path, null_input, null_clock, [_basic(3.0, lane=0)])
    state = composed.game_state
    state.combo_count = 4

    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.0)

    # jogador parado no centro: a barra o atinge ao cruzar na batida
    dt = 0.016
    for _ in range(200):
        null_clock.advance(dt)
        composed.world.step(dt)
        if state.miss_count > 0:
            break
    assert state.miss_count == 1
    assert state.health == 2
    assert state.combo_count == 0
    assert state.last_judgment == JUDGMENT_MISS


def test_dash_through_wall_scores_dodge_and_keeps_combo(tmp_path, null_input, null_clock):
    composed, _ = _compose_survival(tmp_path, null_input, null_clock, [_basic(3.0, lane=0)])
    state = composed.game_state
    state.combo_count = 4

    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.0)

    dt = 0.016
    dashed = False
    for _ in range(220):
        # dasha antes do overlap comecar (borda da barra toca o jogador
        # ~23px antes do centro: t = 3.0 - 23/258 ~= 2.91)
        if not dashed and null_clock.now_seconds() >= 2.85:
            null_input.set_action_held("dash", True)
            dashed = True
        null_input.poll()
        null_clock.advance(dt)
        composed.world.step(dt)
        if state.dodge_count > 0 or state.miss_count > 0:
            break

    assert state.miss_count == 0
    assert state.dodge_count == 1
    assert state.health == 3
    assert state.combo_count == 5  # atravessar no ritmo estende o combo


def test_expired_wall_scores_survival(tmp_path, null_input, null_clock):
    """Parede que expira sem tocar ninguem -> SURVIVED: pontua, estende
    o combo e e destruida pelo coletor de expiracao. (Isolamento de
    unidade: a colisao do jogador e neutralizada via layer/mask 0,
    pois as varreduras cobrem a arena inteira por design.)"""
    composed, _ = _compose_survival(tmp_path, null_input, null_clock, [_basic(3.0, lane=1)])
    state = composed.game_state

    hitbox_pool = composed.memory_manager.get_pool("hitbox")
    row = hitbox_pool.dense_row_of(composed.player_entity_index)
    hitbox_pool.active_view()["collision_layer"][row] = 0
    hitbox_pool.active_view()["collision_mask"][row] = 0

    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.0)
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 1

    null_clock.set_now_seconds(5.2)  # alem de expire (~3.0 + 2.0)
    composed.world.step(0.016)

    assert state.survive_count == 1
    assert state.score == 100
    assert state.combo_count == 1
    assert threat_pool.count == 0  # coletor de expiracao destruiu a parede
