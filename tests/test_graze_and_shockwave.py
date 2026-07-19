"""Sobrevivencia: Graze (raspar sem tocar -> Fever) e Pulso de Impacto (dash no ritmo -> onda expansiva)."""
import dataclasses

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.components.schemas import PHASE_LETHAL
from hertzbeats.systems.shockwave_system import SHOCKWAVE_COLLISION_LAYER

from tests.conftest import make_config, write_beatmap


def _basic(timestamp: float, lane: int = 0, threat_type: str = "rhythm_threat_basic") -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": threat_type,
        "lane": lane,
        "strength": 0.5,
    }


def _heavy(timestamp: float, lane: int = 0) -> dict:
    return _basic(timestamp, lane=lane, threat_type="rhythm_threat_heavy")


def _compose_survival(tmp_path, null_input, null_clock, threats):
    beatmap_path = write_beatmap(tmp_path / "s.beatmap.json", threats)
    config = dataclasses.replace(make_config(beatmap_path), game_mode="survival")
    return compose_world(config, null_input, null_clock), config


def _first_wall(memory_manager):
    threat_pool = memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 1
    entity_index = int(threat_pool.active_entity_indices()[0])
    return threat_pool, entity_index


def _place_wall_and_player(composed, wall_index: int, wall_half: float, player_y: float) -> None:
    """Reescreve a parede para um quadrado PEQUENO e controlado (10x10
    em vez da barra completa da arena) e posiciona jogador/parede no
    mesmo X, variando so Y -- isola a matematica de Graze num unico
    eixo, sem depender da geometria completa do spawner."""
    memory_manager = composed.memory_manager
    transform_pool = memory_manager.get_pool("transform")
    hitbox_pool = memory_manager.get_pool("hitbox")

    wall_t_row = transform_pool.dense_row_of(wall_index)
    transform_pool.active_view()["position_x"][wall_t_row] = 500.0
    transform_pool.active_view()["position_y"][wall_t_row] = 500.0
    wall_h_row = hitbox_pool.dense_row_of(wall_index)
    hitbox_pool.active_view()["half_width"][wall_h_row] = wall_half
    hitbox_pool.active_view()["half_height"][wall_h_row] = wall_half

    player_t_row = transform_pool.dense_row_of(composed.player_entity_index)
    transform_pool.active_view()["position_x"][player_t_row] = 500.0
    transform_pool.active_view()["position_y"][player_t_row] = player_y


def _advance_to(composed, null_clock, null_input, target_seconds: float) -> None:
    dt = target_seconds - null_clock.now_seconds()
    null_clock.set_now_seconds(target_seconds)
    null_input.poll()
    composed.world.step(dt)


def test_grazing_a_lethal_wall_scores_and_builds_fever(tmp_path, null_input, null_clock):
    composed, config = _compose_survival(tmp_path, null_input, null_clock, [_basic(3.0)])
    _advance_to(composed, null_clock, null_input, 1.0)  # spawna (aviso)
    threat_pool, wall_index = _first_wall(composed.memory_manager)

    _advance_to(composed, null_clock, null_input, 3.0)  # onset -> LETAL
    row = threat_pool.dense_row_of(wall_index)
    assert int(threat_pool.active_view()["phase"][row]) == PHASE_LETHAL

    # meio-tamanho da parede=10, meio-tamanho do jogador=core_half_extent=16
    # -> banda de toque = 26, banda de graze = 26 + graze_margin(15) = 41
    _place_wall_and_player(composed, wall_index, wall_half=10.0, player_y=530.0)  # dy=30: graze
    null_input.poll()
    composed.world.step(0.016)

    state = composed.game_state
    assert state.graze_score == config.graze_score_per_hit
    assert state.fever_meter > 0.0
    assert state.health == config.max_health  # graze nao e dano
    assert bool(threat_pool.active_view()["has_grazed"][row]) is True


def test_touching_the_wall_does_not_count_as_graze(tmp_path, null_input, null_clock):
    composed, config = _compose_survival(tmp_path, null_input, null_clock, [_basic(3.0)])
    _advance_to(composed, null_clock, null_input, 1.0)
    threat_pool, wall_index = _first_wall(composed.memory_manager)
    _advance_to(composed, null_clock, null_input, 3.0)

    _place_wall_and_player(composed, wall_index, wall_half=10.0, player_y=520.0)  # dy=20 < 26: toque real
    null_input.poll()
    composed.world.step(0.016)

    assert composed.game_state.graze_score == 0


def test_too_far_from_the_wall_does_not_count_as_graze(tmp_path, null_input, null_clock):
    composed, config = _compose_survival(tmp_path, null_input, null_clock, [_basic(3.0)])
    _advance_to(composed, null_clock, null_input, 1.0)
    threat_pool, wall_index = _first_wall(composed.memory_manager)
    _advance_to(composed, null_clock, null_input, 3.0)

    _place_wall_and_player(composed, wall_index, wall_half=10.0, player_y=560.0)  # dy=60 > 41
    null_input.poll()
    composed.world.step(0.016)

    assert composed.game_state.graze_score == 0


def test_warning_phase_wall_never_grazes(tmp_path, null_input, null_clock):
    """Uma parede ainda em AVISO (nao letal) nao concede Graze -- so as
    letais contam (mesmo criterio do dano real)."""
    composed, config = _compose_survival(tmp_path, null_input, null_clock, [_basic(3.0)])
    _advance_to(composed, null_clock, null_input, 1.0)
    threat_pool, wall_index = _first_wall(composed.memory_manager)
    row = threat_pool.dense_row_of(wall_index)
    from hertzbeats.components.schemas import PHASE_WARNING
    assert int(threat_pool.active_view()["phase"][row]) == PHASE_WARNING

    _place_wall_and_player(composed, wall_index, wall_half=10.0, player_y=530.0)  # dy=30: seria graze
    null_input.poll()
    composed.world.step(0.016)

    assert composed.game_state.graze_score == 0


def test_grazing_only_scores_once_while_lingering(tmp_path, null_input, null_clock):
    composed, config = _compose_survival(tmp_path, null_input, null_clock, [_basic(3.0)])
    _advance_to(composed, null_clock, null_input, 1.0)
    threat_pool, wall_index = _first_wall(composed.memory_manager)
    _advance_to(composed, null_clock, null_input, 3.0)
    _place_wall_and_player(composed, wall_index, wall_half=10.0, player_y=530.0)

    null_input.poll()
    composed.world.step(0.016)
    null_input.poll()
    composed.world.step(0.016)  # continua na mesma faixa no frame seguinte

    assert composed.game_state.graze_score == config.graze_score_per_hit  # so contou uma vez


def test_fever_doubles_graze_score(tmp_path, null_input, null_clock):
    composed, config = _compose_survival(tmp_path, null_input, null_clock, [_basic(3.0)])
    _advance_to(composed, null_clock, null_input, 1.0)
    threat_pool, wall_index = _first_wall(composed.memory_manager)
    _advance_to(composed, null_clock, null_input, 3.0)
    _place_wall_and_player(composed, wall_index, wall_half=10.0, player_y=530.0)

    # dt=0.0: evita que o decaimento do fever (aplicado no TOPO do
    # `GrazeSystem.update` a cada frame) derrube o medidor abaixo de
    # 1.0 antes mesmo da checagem `in_fever` deste mesmo frame.
    composed.game_state.fever_meter = 1.0
    null_input.poll()
    composed.world.step(0.0)

    expected = round(config.graze_score_per_hit * config.fever_score_multiplier)
    assert composed.game_state.graze_score == expected


def test_fever_decays_over_time_without_grazing(tmp_path, null_input, null_clock):
    composed, config = _compose_survival(tmp_path, null_input, null_clock, [_basic(99.0)])  # nunca spawna
    composed.game_state.fever_meter = 0.5

    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(1.0)

    expected = max(0.0, 0.5 - config.fever_decay_per_second * 1.0)
    assert abs(composed.game_state.fever_meter - expected) < 1e-9


def _dash_on_beat(composed, null_clock, null_input, wall_hit_time: float, press_offset: float = 0.05) -> None:
    """Empurra o dash a `press_offset` segundos ANTES do onset de uma
    ameaca viva -- dentro da janela padrao (0.15s) de esquiva ritmica,
    exatamente como em `test_survival_mode.py`. `dt=0.0` no frame do
    aperto: o `ShockwaveSystem.update` ja avanca o slot recem-ativado
    pelo MESMO `delta_time` deste frame (trigger + advance no mesmo
    `update()`) -- dt=0 mantem o raio exatamente em `min_radius` logo
    apos o disparo, sem um frame de crescimento embutido."""
    null_clock.set_now_seconds(wall_hit_time - press_offset)
    null_input.set_action_held("dash", True)
    null_input.poll()
    composed.world.step(0.0)
    null_input.set_action_held("dash", False)
    null_input.poll()


def _shockwave_rows(composed):
    """Itera (entity_index, row) de TODAS as entidades pre-alocadas do
    pool `shockwave` (permanentes, nunca destruidas -- ver `_create_shockwave_pool`)."""
    pool = composed.memory_manager.get_pool("shockwave")
    for entity_index in pool.active_entity_indices():
        entity_index = int(entity_index)
        yield entity_index, pool.dense_row_of(entity_index)


def _active_shockwave(composed):
    pool = composed.memory_manager.get_pool("shockwave")
    view = pool.active_view()
    for entity_index, row in _shockwave_rows(composed):
        if bool(view["active"][row]):
            return entity_index, row
    return None, None


def test_dash_on_beat_activates_a_shockwave_slot_at_the_player(tmp_path, null_input, null_clock):
    composed, config = _compose_survival(tmp_path, null_input, null_clock, [_heavy(3.0)])
    _advance_to(composed, null_clock, null_input, 1.0)  # spawna a pesada (centrada na arena)

    transform_pool = composed.memory_manager.get_pool("transform")
    player_row = transform_pool.dense_row_of(composed.player_entity_index)
    player_x = float(transform_pool.active_view()["position_x"][player_row])
    player_y = float(transform_pool.active_view()["position_y"][player_row])

    _dash_on_beat(composed, null_clock, null_input, 3.0)

    entity_index, row = _active_shockwave(composed)
    assert entity_index is not None

    hitbox_pool = composed.memory_manager.get_pool("hitbox")
    h_row = hitbox_pool.dense_row_of(entity_index)
    assert abs(float(hitbox_pool.active_view()["half_width"][h_row]) - config.shockwave_min_radius) < 1e-6
    assert int(hitbox_pool.active_view()["collision_layer"][h_row]) == SHOCKWAVE_COLLISION_LAYER

    t_row = transform_pool.dense_row_of(entity_index)
    assert abs(float(transform_pool.active_view()["position_x"][t_row]) - player_x) < 1e-6
    assert abs(float(transform_pool.active_view()["position_y"][t_row]) - player_y) < 1e-6


def test_shockwave_trigger_shakes_the_camera(tmp_path, null_input, null_clock):
    composed, config = _compose_survival(tmp_path, null_input, null_clock, [_heavy(3.0)])
    _advance_to(composed, null_clock, null_input, 1.0)

    _dash_on_beat(composed, null_clock, null_input, 3.0)

    assert composed.game_state.shake_intensity == config.shockwave_trigger_shake_px


def test_dash_off_beat_does_not_activate_any_shockwave(tmp_path, null_input, null_clock):
    composed, config = _compose_survival(tmp_path, null_input, null_clock, [_heavy(3.0)])
    # arena silenciosa (nada spawnado ainda) -> dash e sempre "fora do tempo"
    null_clock.set_now_seconds(0.0)
    null_input.set_action_held("dash", True)
    null_input.poll()
    composed.world.step(0.016)

    entity_index, _ = _active_shockwave(composed)
    assert entity_index is None


def test_shockwave_radius_grows_over_its_duration(tmp_path, null_input, null_clock):
    composed, config = _compose_survival(tmp_path, null_input, null_clock, [_heavy(3.0)])
    _advance_to(composed, null_clock, null_input, 1.0)
    _dash_on_beat(composed, null_clock, null_input, 3.0)

    entity_index, _ = _active_shockwave(composed)
    hitbox_pool = composed.memory_manager.get_pool("hitbox")
    h_row = hitbox_pool.dense_row_of(entity_index)
    radius_early = float(hitbox_pool.active_view()["half_width"][h_row])

    half_life = config.shockwave_duration_seconds / 2.0
    null_input.poll()
    composed.world.step(half_life)

    radius_mid = float(hitbox_pool.active_view()["half_width"][h_row])
    assert radius_mid > radius_early


def test_shockwave_deactivates_after_its_duration(tmp_path, null_input, null_clock):
    composed, config = _compose_survival(tmp_path, null_input, null_clock, [_heavy(3.0)])
    _advance_to(composed, null_clock, null_input, 1.0)
    _dash_on_beat(composed, null_clock, null_input, 3.0)

    entity_index, row = _active_shockwave(composed)
    assert entity_index is not None

    null_input.poll()
    composed.world.step(config.shockwave_duration_seconds + 0.01)

    shockwave_pool = composed.memory_manager.get_pool("shockwave")
    assert bool(shockwave_pool.active_view()["active"][row]) is False
    hitbox_pool = composed.memory_manager.get_pool("hitbox")
    h_row = hitbox_pool.dense_row_of(entity_index)
    assert int(hitbox_pool.active_view()["collision_layer"][h_row]) == 0
    sprite_pool = composed.memory_manager.get_pool("sprite")
    s_row = sprite_pool.dense_row_of(entity_index)
    assert int(sprite_pool.active_view()["tint_a"][s_row]) == 0


def test_shockwave_destroys_a_normal_wall_in_its_radius(tmp_path, null_input, null_clock):
    composed, config = _compose_survival(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0), _basic(3.6, lane=2)]
    )
    _advance_to(composed, null_clock, null_input, 1.0)  # spawna a pesada
    _advance_to(composed, null_clock, null_input, 1.6)  # spawna a basica tambem
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 2

    _dash_on_beat(composed, null_clock, null_input, 3.0)
    entity_index, _ = _active_shockwave(composed)
    assert entity_index is not None

    # identifica a parede BASICA (nao-pesada) e a teleporta para dentro
    # do raio da onda (que nasce sobre o proprio jogador)
    transform_pool = composed.memory_manager.get_pool("transform")
    wave_t_row = transform_pool.dense_row_of(entity_index)
    wave_x = float(transform_pool.active_view()["position_x"][wave_t_row])
    wave_y = float(transform_pool.active_view()["position_y"][wave_t_row])

    basic_index = None
    for candidate in threat_pool.active_entity_indices():
        candidate = int(candidate)
        row = threat_pool.dense_row_of(candidate)
        if int(threat_pool.active_view()["threat_type"][row]) == 0:
            basic_index = candidate
    assert basic_index is not None
    basic_t_row = transform_pool.dense_row_of(basic_index)
    transform_pool.active_view()["position_x"][basic_t_row] = wave_x
    transform_pool.active_view()["position_y"][basic_t_row] = wave_y
    # a parede so colide de fato depois de LETAL -- forca isso tambem
    hitbox_pool = composed.memory_manager.get_pool("hitbox")
    from hertzbeats.bootstrap.rhythm_composition_root import PLAYER_COLLISION_LAYER, THREAT_COLLISION_LAYER
    basic_h_row = hitbox_pool.dense_row_of(basic_index)
    hitbox_pool.active_view()["collision_layer"][basic_h_row] = THREAT_COLLISION_LAYER
    hitbox_pool.active_view()["collision_mask"][basic_h_row] = PLAYER_COLLISION_LAYER

    score_before = composed.game_state.score
    null_input.poll()
    composed.world.step(0.0)

    assert threat_pool.count == 1  # a basica foi destruida pelo pulso
    remaining = int(threat_pool.active_entity_indices()[0])
    row = threat_pool.dense_row_of(remaining)
    assert int(threat_pool.active_view()["threat_type"][row]) == 1  # so a pesada sobrou
    assert composed.game_state.score > score_before


def test_shockwave_does_not_destroy_a_heavy_wall(tmp_path, null_input, null_clock):
    """Pesadas resistem ao Pulso de Impacto, assim como resistem ao
    Parry generico -- so o Dash ritmico (i-frames) as atravessa."""
    composed, config = _compose_survival(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0), _heavy(3.6, lane=2)]
    )
    _advance_to(composed, null_clock, null_input, 1.0)
    _advance_to(composed, null_clock, null_input, 1.6)
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 2

    _dash_on_beat(composed, null_clock, null_input, 3.0)
    entity_index, _ = _active_shockwave(composed)
    assert entity_index is not None

    transform_pool = composed.memory_manager.get_pool("transform")
    wave_t_row = transform_pool.dense_row_of(entity_index)
    wave_x = float(transform_pool.active_view()["position_x"][wave_t_row])
    wave_y = float(transform_pool.active_view()["position_y"][wave_t_row])

    # a segunda pesada (hit_time=3.6, ainda pendente) e teleportada para
    # dentro do raio da onda, ja armada como LETAL
    second_heavy = None
    for candidate in threat_pool.active_entity_indices():
        candidate = int(candidate)
        row = threat_pool.dense_row_of(candidate)
        if abs(float(threat_pool.active_view()["target_hit_time_sec"][row]) - 3.6) < 1e-6:
            second_heavy = candidate
    assert second_heavy is not None
    t_row = transform_pool.dense_row_of(second_heavy)
    transform_pool.active_view()["position_x"][t_row] = wave_x
    transform_pool.active_view()["position_y"][t_row] = wave_y
    hitbox_pool = composed.memory_manager.get_pool("hitbox")
    from hertzbeats.bootstrap.rhythm_composition_root import PLAYER_COLLISION_LAYER, THREAT_COLLISION_LAYER
    h_row = hitbox_pool.dense_row_of(second_heavy)
    hitbox_pool.active_view()["collision_layer"][h_row] = THREAT_COLLISION_LAYER
    hitbox_pool.active_view()["collision_mask"][h_row] = PLAYER_COLLISION_LAYER

    null_input.poll()
    composed.world.step(0.0)

    assert threat_pool.count == 2  # nenhuma pesada foi destruida pelo pulso
