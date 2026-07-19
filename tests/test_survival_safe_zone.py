"""Sobrevivencia: Safe Zone estacionaria + Ancora -- fique dentro do raio e segure a tecla ate o fim."""
import dataclasses

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.components.schemas import JUDGMENT_MISS, JUDGMENT_PENDING, PHASE_LETHAL

from tests.conftest import make_config, write_beatmap


def _heavy(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_heavy",
        "lane": lane,
        "strength": 0.9,
    }


def _compose_safe_zone(tmp_path, null_input, null_clock, threats, **overrides):
    beatmap_path = write_beatmap(tmp_path / "sz.beatmap.json", threats)
    config = dataclasses.replace(
        make_config(beatmap_path), game_mode="survival", holds_enabled=True, **overrides
    )
    return compose_world(config, null_input, null_clock), config


def _advance_to(composed, null_clock, null_input, target_seconds: float) -> None:
    """Mesmo helper de `test_graze_and_shockwave.py`: as ameacas da
    Sobrevivencia sao ESTATICAS (velocidade sempre zero), entao um
    unico salto de relogio nao arrisca nenhuma matematica de viagem."""
    dt = target_seconds - null_clock.now_seconds()
    null_clock.set_now_seconds(target_seconds)
    null_input.poll()
    composed.world.step(dt)


def _zone_position(config, lane: int) -> tuple:
    """Mesma grade 4x2 deterministica do `SurvivalSpawnerSystem`."""
    x_frac = ((lane % 4) + 0.5) / 4.0
    y_frac = 0.3 if (lane // 4) % 2 == 0 else 0.7
    return config.window_width * x_frac, config.window_height * y_frac


def _place_player_at(composed, x: float, y: float) -> None:
    transform_pool = composed.memory_manager.get_pool("transform")
    row = transform_pool.dense_row_of(composed.player_entity_index)
    transform_pool.active_view()["position_x"][row] = x
    transform_pool.active_view()["position_y"][row] = y


def _anchor(null_input, held: bool) -> None:
    null_input.set_action_held("anchor", held)
    null_input.poll()


def _first_threat(memory_manager):
    threat_pool = memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 1
    entity_index = int(threat_pool.active_entity_indices()[0])
    return threat_pool, entity_index


def test_heavy_threat_becomes_a_stationary_safe_zone_with_inert_hitbox(tmp_path, null_input, null_clock):
    composed, config = _compose_safe_zone(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=1.0
    )
    _advance_to(composed, null_clock, null_input, 1.0)  # spawn devido (aviso)

    memory_manager = composed.memory_manager
    threat_pool, entity_index = _first_threat(memory_manager)
    view = threat_pool.active_view()
    row = threat_pool.dense_row_of(entity_index)
    assert abs(float(view["duration_sec"][row]) - 1.0) < 1e-6

    transform_pool = memory_manager.get_pool("transform")
    t_row = transform_pool.dense_row_of(entity_index)
    zone_x, zone_y = _zone_position(config, lane=0)
    assert abs(float(transform_pool.active_view()["position_x"][t_row]) - zone_x) < 1e-6
    assert abs(float(transform_pool.active_view()["position_y"][t_row]) - zone_y) < 1e-6

    velocity_pool = memory_manager.get_pool("velocity")
    v_row = velocity_pool.dense_row_of(entity_index)
    assert float(velocity_pool.active_view()["linear_x"][v_row]) == 0.0
    assert float(velocity_pool.active_view()["linear_y"][v_row]) == 0.0

    hitbox_pool = memory_manager.get_pool("hitbox")
    h_row = hitbox_pool.dense_row_of(entity_index)
    assert int(hitbox_pool.active_view()["collision_layer"][h_row]) == 0
    assert int(hitbox_pool.active_view()["collision_mask"][h_row]) == 0


def test_safe_zone_hitbox_never_arms_even_after_turning_lethal(tmp_path, null_input, null_clock):
    composed, config = _compose_safe_zone(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=1.0
    )
    _advance_to(composed, null_clock, null_input, 1.0)
    memory_manager = composed.memory_manager
    threat_pool, entity_index = _first_threat(memory_manager)
    hitbox_pool = memory_manager.get_pool("hitbox")
    h_row = hitbox_pool.dense_row_of(entity_index)

    zone_x, zone_y = _zone_position(config, lane=0)
    _place_player_at(composed, zone_x, zone_y)
    _anchor(null_input, True)

    _advance_to(composed, null_clock, null_input, 3.0)  # onset: vira LETAL, ancorando

    assert threat_pool.count == 1  # ainda sustentando, nao resolveu
    row = threat_pool.dense_row_of(entity_index)
    assert int(threat_pool.active_view()["phase"][row]) == PHASE_LETHAL
    assert int(hitbox_pool.active_view()["collision_layer"][h_row]) == 0
    assert int(hitbox_pool.active_view()["collision_mask"][h_row]) == 0


def test_anchoring_inside_the_zone_through_duration_scores_survived(tmp_path, null_input, null_clock):
    composed, config = _compose_safe_zone(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=1.0
    )
    _advance_to(composed, null_clock, null_input, 1.0)
    threat_pool, entity_index = _first_threat(composed.memory_manager)

    zone_x, zone_y = _zone_position(config, lane=0)
    _place_player_at(composed, zone_x, zone_y)
    _anchor(null_input, True)

    state = composed.game_state
    _advance_to(composed, null_clock, null_input, 4.05)  # 3.0 + 1.0 = 4.0, passou do fim

    assert threat_pool.count == 0
    assert state.survive_count == 1
    assert state.score == config.score_good
    assert state.combo_count == 1
    assert state.miss_count == 0


def test_safe_zone_survives_past_generic_expire_time_while_anchored(tmp_path, null_input, null_clock):
    """`expire_time_sec` (hit + strike_seconds=0.30) vence bem ANTES do
    fim do Hold (hit + duration=1.0) -- o coletor generico de expiracao
    do `SurvivalDamageSystem` NAO pode destruir a zona so por isso
    (mesma licao de exclusao aplicada ao Hold do Defensor/Arcade)."""
    composed, config = _compose_safe_zone(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=1.0
    )
    _advance_to(composed, null_clock, null_input, 1.0)
    threat_pool, entity_index = _first_threat(composed.memory_manager)

    zone_x, zone_y = _zone_position(config, lane=0)
    _place_player_at(composed, zone_x, zone_y)
    _anchor(null_input, True)

    # bem alem de expire_time_sec (3.3) mas ainda dentro da sustentacao (ate 4.0)
    _advance_to(composed, null_clock, null_input, 3.9)

    assert threat_pool.count == 1
    assert composed.game_state.miss_count == 0
    row = threat_pool.dense_row_of(entity_index)
    assert int(threat_pool.active_view()["judgment"][row]) == JUDGMENT_PENDING


def test_leaving_the_zone_mid_anchor_is_immediate_miss_with_shake_and_rumble(tmp_path, null_input, null_clock):
    composed, config = _compose_safe_zone(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=1.0
    )
    _advance_to(composed, null_clock, null_input, 1.0)
    threat_pool, entity_index = _first_threat(composed.memory_manager)
    state = composed.game_state
    state.combo_count = 5

    zone_x, zone_y = _zone_position(config, lane=0)
    _place_player_at(composed, zone_x, zone_y)
    _anchor(null_input, True)
    _advance_to(composed, null_clock, null_input, 3.5)  # sustentando bem antes do fim (4.0)
    assert threat_pool.count == 1

    # sai do raio (bem alem de safe_zone_radius) mas continua ancorando
    _place_player_at(composed, zone_x + 500.0, zone_y)
    null_input.poll()
    composed.world.step(0.0)

    assert threat_pool.count == 0
    assert state.miss_count == 1
    assert state.combo_count == 0
    assert state.last_judgment == JUDGMENT_MISS
    assert state.health == config.max_health - 1
    assert state.shake_intensity == config.safe_zone_break_shake_px
    assert null_input._last_rumble == (
        config.rumble_low_freq, config.rumble_high_freq, config.rumble_duration_seconds
    )


def test_releasing_anchor_inside_the_zone_is_also_an_immediate_miss(tmp_path, null_input, null_clock):
    composed, config = _compose_safe_zone(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=1.0
    )
    _advance_to(composed, null_clock, null_input, 1.0)
    threat_pool, entity_index = _first_threat(composed.memory_manager)

    zone_x, zone_y = _zone_position(config, lane=0)
    _place_player_at(composed, zone_x, zone_y)
    _anchor(null_input, True)
    _advance_to(composed, null_clock, null_input, 3.5)
    assert threat_pool.count == 1

    _anchor(null_input, False)  # continua DENTRO do raio, mas soltou a tecla
    composed.world.step(0.0)

    assert threat_pool.count == 0
    assert composed.game_state.miss_count == 1


def test_graze_system_ignores_safe_zones(tmp_path, null_input, null_clock):
    """Safe Zone nunca vira PHASE_LETHAL "letal de verdade" para o
    `GrazeSystem` -- e um refugio, nao uma parede para raspar por
    perto (mesma exclusao de `duration_sec>0` aplicada ao coletor de
    expiracao)."""
    composed, config = _compose_safe_zone(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=1.0
    )
    _advance_to(composed, null_clock, null_input, 1.0)
    memory_manager = composed.memory_manager
    threat_pool, entity_index = _first_threat(memory_manager)

    hitbox_pool = memory_manager.get_pool("hitbox")
    h_row = hitbox_pool.dense_row_of(entity_index)
    radius = float(hitbox_pool.active_view()["half_width"][h_row])
    player_hitbox_row = hitbox_pool.dense_row_of(composed.player_entity_index)
    player_half = float(hitbox_pool.active_view()["half_width"][player_hitbox_row])

    zone_x, zone_y = _zone_position(config, lane=0)
    # bem perto da borda (dentro da banda de graze, fora do raio de anchor)
    _place_player_at(composed, zone_x + radius + player_half + 5.0, zone_y)

    _advance_to(composed, null_clock, null_input, 3.0)  # vira LETAL

    assert composed.game_state.graze_score == 0
