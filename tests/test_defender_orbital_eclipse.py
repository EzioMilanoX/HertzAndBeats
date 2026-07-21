"""Defensor -- Eclipses Orbitais: barreiras dinamicas que giram ao redor do nucleo, PERMEAVEIS ao projetil refletido do Parry (Tolerancia Organica)."""
import dataclasses
import math

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.systems.parry_impact_system import REFLECTED_COLLISION_LAYER, SHIELD_COLLISION_LAYER

from tests.conftest import make_config, write_beatmap

_LANE_COUNT = 8  # mesmo default de make_config/HertzConfig.lane_count
_TAU = 2.0 * math.pi


def _heavy(timestamp: float, lane: int = 2) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_heavy",
        "lane": lane,
        "strength": 0.9,
    }


def _compose_with_eclipses(tmp_path, null_input, null_clock, threats, eclipse_count=2, **overrides):
    beatmap_path = write_beatmap(tmp_path / "eclipse.beatmap.json", threats)
    config = dataclasses.replace(
        make_config(beatmap_path),
        active_modifiers=("telegraph_rings", "polarity", "orbital_eclipses"),
        orbital_eclipse_count=eclipse_count,
        **overrides,
    )
    return compose_world(config, null_input, null_clock), config


def _find_eclipse_entity_indices(composed) -> list:
    """Isola os Eclipses entre as entidades com hitbox: sao as UNICAS
    persistentes com `collision_layer == SHIELD_COLLISION_LAYER` que NAO
    vivem na pool `rhythm_threat` (ao contrario de um Escudo Rotativo
    capturado -- Captura Orbital -- que reusa a MESMA camada, mas so
    nasce a partir de uma ameaca julgada)."""
    hitbox_pool = composed.memory_manager.get_pool("hitbox")
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    threat_indices = {int(i) for i in threat_pool.active_entity_indices()}
    view = hitbox_pool.active_view()
    found = []
    for entity_index in hitbox_pool.active_entity_indices():
        entity_index = int(entity_index)
        if entity_index in threat_indices:
            continue
        row = hitbox_pool.dense_row_of(entity_index)
        if int(view["collision_layer"][row]) == SHIELD_COLLISION_LAYER:
            found.append(entity_index)
    return found


def _fire_at(composed, null_clock, null_input, target_seconds: float, action_name: str, aim_x: float, aim_y: float) -> None:
    dt = target_seconds - null_clock.now_seconds()
    null_input.set_axis("aim_x", aim_x)
    null_input.set_axis("aim_y", aim_y)
    null_input.set_action_held(action_name, True)
    null_clock.advance(dt)
    null_input.poll()
    composed.world.step(dt)


def _advance_to(composed, null_clock, null_input, target_seconds: float, dt: float = 0.01) -> None:
    remaining = target_seconds - null_clock.now_seconds()
    steps = int(round(remaining / dt))
    for _ in range(steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)


def _aim_for_lane(lane: int) -> tuple:
    angle = _TAU * (lane % _LANE_COUNT) / _LANE_COUNT
    return math.cos(angle), math.sin(angle)


def test_orbital_eclipse_count_creates_that_many_shield_layer_obstacles(tmp_path, null_input, null_clock):
    composed, config = _compose_with_eclipses(tmp_path, null_input, null_clock, [], eclipse_count=3)
    eclipse_indices = _find_eclipse_entity_indices(composed)
    assert len(eclipse_indices) == 3

    hitbox_pool = composed.memory_manager.get_pool("hitbox")
    view = hitbox_pool.active_view()
    for entity_index in eclipse_indices:
        row = hitbox_pool.dense_row_of(entity_index)
        assert int(view["collision_mask"][row]) == REFLECTED_COLLISION_LAYER


def test_zero_eclipse_count_creates_no_obstacles(tmp_path, null_input, null_clock):
    composed, config = _compose_with_eclipses(tmp_path, null_input, null_clock, [], eclipse_count=0)
    assert _find_eclipse_entity_indices(composed) == []


def test_orbital_eclipse_position_always_matches_its_own_integrated_rotation(tmp_path, null_input, null_clock):
    """O `PhysicsSystem` generico integra `rotation_rad` sozinho a partir
    de `velocity.angular`; o `OrbitalEclipseSystem` so converte esse
    angulo (ja avancado) em posicao cartesiana -- valido em QUALQUER
    instante, nao so no spawn."""
    composed, config = _compose_with_eclipses(tmp_path, null_input, null_clock, [], eclipse_count=2)
    eclipse_indices = _find_eclipse_entity_indices(composed)
    transform_pool = composed.memory_manager.get_pool("transform")
    center_x, center_y = config.center_xy

    for _ in range(30):
        null_clock.advance(0.05)
        null_input.poll()
        composed.world.step(0.05)

    view = transform_pool.active_view()
    for entity_index in eclipse_indices:
        row = transform_pool.dense_row_of(entity_index)
        angle = float(view["rotation_rad"][row])
        expected_x = center_x + math.cos(angle) * config.orbital_eclipse_radius
        expected_y = center_y + math.sin(angle) * config.orbital_eclipse_radius
        assert abs(float(view["position_x"][row]) - expected_x) < 1e-3
        assert abs(float(view["position_y"][row]) - expected_y) < 1e-3


def test_orbital_eclipse_no_longer_blocks_the_reflected_parry_projectile(tmp_path, null_input, null_clock):
    """Tolerancia Organica -- Eclipses Permeaveis: um Parry so pode
    nascer DENTRO da janela PERFECT (ver a janela restrita a `is_special`
    em `JudgmentSystem._try_player_hit`) -- deixar um Eclipse (que gira
    por conta propria, fora do controle do jogador) anular esse tiro
    flawless seria um softlock de habilidade contra sorte de
    posicionamento. O projetil refletido agora atravessa Eclipses
    livremente, mesmo colidindo exatamente com um deles."""
    composed, config = _compose_with_eclipses(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=2)], eclipse_count=2
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    transform_pool = composed.memory_manager.get_pool("transform")
    eclipse_indices = _find_eclipse_entity_indices(composed)
    assert len(eclipse_indices) == 2

    aim_x, aim_y = _aim_for_lane(2)
    _advance_to(composed, null_clock, null_input, 2.98)
    assert threat_pool.count == 1
    reflected_index = int(threat_pool.active_entity_indices()[0])

    _fire_at(composed, null_clock, null_input, 2.99, "fire", aim_x, aim_y)  # PERFECT -> Parry/reflete
    assert threat_pool.count == 1
    assert bool(threat_pool.active_view()["is_reflected"][threat_pool.dense_row_of(reflected_index)])

    # teleporta o refletido para EXATAMENTE onde um Eclipse esta agora
    eclipse_row = transform_pool.dense_row_of(eclipse_indices[0])
    eclipse_x = float(transform_pool.active_view()["position_x"][eclipse_row])
    eclipse_y = float(transform_pool.active_view()["position_y"][eclipse_row])
    reflected_row = transform_pool.dense_row_of(reflected_index)
    transform_pool.active_view()["position_x"][reflected_row] = eclipse_x
    transform_pool.active_view()["position_y"][reflected_row] = eclipse_y

    score_before = composed.game_state.score
    null_input.set_action_held("fire", False)
    null_input.poll()
    composed.world.step(0.0)

    assert threat_pool.count == 1  # o refletido SOBREVIVE, atravessa o Eclipse
    reflected_row = threat_pool.dense_row_of(reflected_index)
    assert bool(threat_pool.active_view()["is_reflected"][reflected_row])
    assert composed.game_state.score == score_before  # atravessar nao pontua sozinho
    assert composed.game_state.miss_count == 0
    assert len(_find_eclipse_entity_indices(composed)) == 2  # os Eclipses sobrevivem, permanentes
