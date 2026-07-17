"""Modo Sobrevivencia: paredes TELEGRAFADAS (aviso->letal no onset); dano so no toque letal; dash so protege NA BATIDA."""
import dataclasses

from hertzbeats.bootstrap.rhythm_composition_root import (
    PLAYER_COLLISION_LAYER,
    THREAT_COLLISION_LAYER,
    compose_world,
)
from hertzbeats.components.schemas import JUDGMENT_MISS, PHASE_LETHAL, PHASE_WARNING

from tests.conftest import make_config, write_beatmap


def _basic(timestamp: float, lane: int = 0, strength: float = 0.5, threat_type: str = "rhythm_threat_basic") -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": threat_type,
        "lane": lane,
        "strength": strength,
    }


def _heavy(timestamp: float, lane: int = 0) -> dict:
    """Ameaca PESADA: cai no CENTRO da arena (anti-camping), coincidindo
    com a posicao de spawn do jogador -- usada para testar colisao sem
    precisar reposicionar ninguem."""
    return _basic(timestamp, lane=lane, strength=0.9, threat_type="rhythm_threat_heavy")


def _compose_survival(tmp_path, null_input, null_clock, threats):
    beatmap_path = write_beatmap(tmp_path / "s.beatmap.json", threats)
    config = dataclasses.replace(make_config(beatmap_path), game_mode="survival")
    return compose_world(config, null_input, null_clock), config


def _threat_row_view(memory_manager):
    threat_pool = memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 1
    entity_index = int(threat_pool.active_entity_indices()[0])
    return threat_pool, entity_index, threat_pool.active_view()[threat_pool.dense_row_of(entity_index)]


def test_wall_spawns_in_warning_phase_with_collision_disarmed(tmp_path, null_input, null_clock):
    composed, _ = _compose_survival(tmp_path, null_input, null_clock, [_basic(3.0, lane=0)])
    null_clock.set_now_seconds(1.0)  # spawn devido (hit 3.0 - approach 2.0)
    null_input.poll()
    composed.world.step(0.0)

    memory_manager = composed.memory_manager
    threat_pool, entity_index, row = _threat_row_view(memory_manager)
    assert int(row["phase"]) == PHASE_WARNING

    hitbox_pool = memory_manager.get_pool("hitbox")
    hb_row = hitbox_pool.dense_row_of(entity_index)
    hb_view = hitbox_pool.active_view()
    assert int(hb_view["collision_layer"][hb_row]) == 0
    assert int(hb_view["collision_mask"][hb_row]) == 0

    sprite_pool = memory_manager.get_pool("sprite")
    sprite_row = sprite_pool.dense_row_of(entity_index)
    assert int(sprite_pool.active_view()["tint_a"][sprite_row]) < 255  # translucida piscando


def test_wall_becomes_lethal_exactly_on_the_onset(tmp_path, null_input, null_clock):
    composed, _ = _compose_survival(tmp_path, null_input, null_clock, [_basic(3.0, lane=0)])
    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.0)

    memory_manager = composed.memory_manager
    threat_pool, entity_index, _ = _threat_row_view(memory_manager)
    hitbox_pool = memory_manager.get_pool("hitbox")
    hb_row = hitbox_pool.dense_row_of(entity_index)

    null_clock.set_now_seconds(2.99)
    composed.world.step(0.016)
    assert int(threat_pool.active_view()[threat_pool.dense_row_of(entity_index)]["phase"]) == PHASE_WARNING
    assert int(hitbox_pool.active_view()["collision_layer"][hb_row]) == 0

    null_clock.set_now_seconds(3.0)
    composed.world.step(0.016)
    row = threat_pool.active_view()[threat_pool.dense_row_of(entity_index)]
    assert int(row["phase"]) == PHASE_LETHAL
    assert int(hitbox_pool.active_view()["collision_layer"][hb_row]) == THREAT_COLLISION_LAYER
    assert int(hitbox_pool.active_view()["collision_mask"][hb_row]) == PLAYER_COLLISION_LAYER

    sprite_pool = memory_manager.get_pool("sprite")
    sprite_row = sprite_pool.dense_row_of(entity_index)
    assert int(sprite_pool.active_view()["tint_a"][sprite_row]) == 255  # solida


def test_touch_during_warning_phase_is_ignored(tmp_path, null_input, null_clock):
    """Mesmo com o jogador exatamente sobre o lugar da parede (ameaca
    PESADA cai no centro), o toque durante o AVISO nao pune -- a colisao
    esta desarmada por construcao."""
    composed, _ = _compose_survival(tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)])
    state = composed.game_state

    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.0)
    null_clock.set_now_seconds(2.9)  # ainda em aviso; jogador ja esta no centro
    composed.world.step(0.016)

    assert state.miss_count == 0
    assert state.health == 3
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    assert int(threat_pool.active_view()[0]["judgment"]) == 0  # PENDING


def test_touching_lethal_wall_damages_and_breaks_combo(tmp_path, null_input, null_clock):
    composed, _ = _compose_survival(tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)])
    state = composed.game_state
    state.combo_count = 4

    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.0)

    null_clock.set_now_seconds(3.0)  # onset: vira letal e colide no MESMO frame
    composed.world.step(0.016)

    assert state.miss_count == 1
    assert state.health == 2
    assert state.combo_count == 0
    assert state.last_judgment == JUDGMENT_MISS


def test_dash_on_beat_grants_iframes_and_survives_the_strike(tmp_path, null_input, null_clock):
    composed, config = _compose_survival(tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)])
    state = composed.game_state
    state.combo_count = 4

    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.0)

    # aperta o dash a 0.05s do onset -- dentro da janela (default 0.15s)
    null_clock.set_now_seconds(3.0 - 0.05)
    null_input.set_action_held("dash", True)
    null_input.poll()
    composed.world.step(0.016)

    player_pool = composed.memory_manager.get_pool("player_state")
    row = player_pool.dense_row_of(composed.player_entity_index)
    assert float(player_pool.active_view()["iframe_timer_sec"][row]) > 0.0  # esquiva RITMICA concedida

    null_input.set_action_held("dash", False)
    null_input.poll()
    null_clock.set_now_seconds(3.0)  # onset: vira letal, colide durante os i-frames
    composed.world.step(0.016)

    assert state.miss_count == 0
    assert state.dodge_count == 1
    assert state.health == 3
    assert state.combo_count == 5  # atravessar no ritmo estende o combo


def test_dash_off_beat_grants_no_protection_and_still_costs_cooldown(tmp_path, null_input, null_clock):
    """Dash no desespero (sem nenhuma ameaca viva na tela -- silencio):
    o corpo consome o cooldown mas NAO ganha i-frames."""
    composed, _ = _compose_survival(tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)])
    state = composed.game_state

    null_clock.set_now_seconds(0.0)  # nada spawnado ainda: arena silenciosa
    null_input.set_action_held("dash", True)
    null_input.poll()
    composed.world.step(0.016)

    player_pool = composed.memory_manager.get_pool("player_state")
    row = player_pool.dense_row_of(composed.player_entity_index)
    assert float(player_pool.active_view()["iframe_timer_sec"][row]) == 0.0
    assert float(player_pool.active_view()["dash_cooldown_sec"][row]) > 0.0  # cooldown gasto mesmo assim

    null_input.set_action_held("dash", False)
    null_input.poll()
    null_clock.set_now_seconds(1.0)
    composed.world.step(0.0)  # spawn devido
    null_clock.set_now_seconds(3.0)  # onset: vira letal e colide sem protecao
    composed.world.step(0.016)

    assert state.miss_count == 1
    assert state.health == 2


def test_expired_wall_scores_survival(tmp_path, null_input, null_clock):
    """Parede fora do caminho do jogador (posicao por timbre, nao
    centralizada) que expira sem tocar ninguem -> SURVIVED: pontua,
    estende o combo e e destruida pelo coletor de expiracao."""
    composed, _ = _compose_survival(tmp_path, null_input, null_clock, [_basic(3.0, lane=1)])
    state = composed.game_state

    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.0)
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 1

    null_clock.set_now_seconds(5.2)  # alem de expire (~3.0 + strike_seconds)
    composed.world.step(0.016)

    assert state.survive_count == 1
    assert state.score == 100
    assert state.combo_count == 1
    assert threat_pool.count == 0  # coletor de expiracao destruiu a parede


def test_heavy_threat_wall_is_centered_normal_wall_is_offset(tmp_path, null_input, null_clock):
    composed, config = _compose_survival(tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)])
    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.0)

    memory_manager = composed.memory_manager
    _, entity_index, _ = _threat_row_view(memory_manager)
    transform_pool = memory_manager.get_pool("transform")
    row = transform_pool.dense_row_of(entity_index)
    view = transform_pool.active_view()
    center_x, center_y = config.center_xy
    assert abs(float(view["position_x"][row]) - center_x) < 1e-6
    assert abs(float(view["position_y"][row]) - center_y) < 1e-6
