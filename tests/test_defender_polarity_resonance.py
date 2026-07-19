"""Defensor -- Ressonancia de Polaridade (Combos Monocromaticos): corrente por cor e Overdrive perfurante."""
import dataclasses
import math

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.components.schemas import POLARITY_BLUE, POLARITY_PINK

from tests.conftest import make_config, write_beatmap

_LANE_COUNT = 8  # mesmo default de make_config/HertzConfig.lane_count
_TAU = 2.0 * math.pi


def _basic(timestamp: float, lane: int) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _heavy(timestamp: float, lane: int = 2) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_heavy",
        "lane": lane,
        "strength": 0.9,
    }


def _compose_polarity(tmp_path, null_input, null_clock, threats, **overrides):
    beatmap_path = write_beatmap(tmp_path / "res.beatmap.json", threats)
    config = dataclasses.replace(make_config(beatmap_path), polarity_enabled=True, **overrides)
    return compose_world(config, null_input, null_clock), config


def _aim_for_lane(lane: int) -> tuple:
    angle = _TAU * (lane % _LANE_COUNT) / _LANE_COUNT
    return math.cos(angle), math.sin(angle)


def _aim_between_lanes(lane_a: int, lane_b: int) -> tuple:
    """Mira EXATAMENTE no meio angular entre duas lanes -- dentro do
    cone de mira (35 graus) de AMBAS quando elas sao adjacentes (45
    graus de separacao com `lane_count=8`)."""
    angle_a = _TAU * (lane_a % _LANE_COUNT) / _LANE_COUNT
    angle_b = _TAU * (lane_b % _LANE_COUNT) / _LANE_COUNT
    mid = (angle_a + angle_b) / 2.0
    return math.cos(mid), math.sin(mid)


def _advance_to(composed, null_clock, null_input, target_seconds: float, dt: float = 0.01) -> None:
    remaining = target_seconds - null_clock.now_seconds()
    steps = int(round(remaining / dt))
    for _ in range(steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)


def _fire_at(composed, null_clock, null_input, target_seconds: float, action_name: str, aim_x: float, aim_y: float) -> None:
    dt = target_seconds - null_clock.now_seconds()
    null_input.set_axis("aim_x", aim_x)
    null_input.set_axis("aim_y", aim_y)
    null_input.set_action_held(action_name, True)
    null_clock.advance(dt)
    null_input.poll()
    composed.world.step(dt)


def test_destroying_same_color_threats_in_sequence_builds_the_chain(tmp_path, null_input, null_clock):
    # lanes 6 e 7 (>= lane_count/2=4) -> POLARITY_BLUE, destruidas por "fire"
    composed, config = _compose_polarity(
        tmp_path, null_input, null_clock, [_basic(3.0, lane=6), _basic(4.0, lane=7)]
    )
    state = composed.game_state
    assert state.resonance_chain == 0

    aim_x, aim_y = _aim_for_lane(6)
    _advance_to(composed, null_clock, null_input, 2.96)
    _fire_at(composed, null_clock, null_input, 2.97, "fire", aim_x, aim_y)
    assert state.resonance_color == POLARITY_BLUE
    assert state.resonance_chain == 1

    aim_x, aim_y = _aim_for_lane(7)
    null_input.set_action_held("fire", False)
    null_input.poll()
    _advance_to(composed, null_clock, null_input, 3.96)
    _fire_at(composed, null_clock, null_input, 3.97, "fire", aim_x, aim_y)
    assert state.resonance_color == POLARITY_BLUE
    assert state.resonance_chain == 2


def test_destroying_a_different_color_threat_resets_the_chain_to_one(tmp_path, null_input, null_clock):
    composed, config = _compose_polarity(
        tmp_path, null_input, null_clock, [_basic(3.0, lane=6), _basic(4.0, lane=1)]
    )
    state = composed.game_state
    state.resonance_color = POLARITY_BLUE
    state.resonance_chain = 5

    # lane 1 (< lane_count/2) -> POLARITY_PINK: cor DIFERENTE da corrente atual
    aim_x, aim_y = _aim_for_lane(1)
    _advance_to(composed, null_clock, null_input, 3.96)
    _fire_at(composed, null_clock, null_input, 3.97, "fire_alt", aim_x, aim_y)

    assert state.resonance_color == POLARITY_PINK
    assert state.resonance_chain == 1


def test_in_overdrive_becomes_true_only_at_the_configured_threshold(tmp_path, null_input, null_clock):
    composed, config = _compose_polarity(
        tmp_path, null_input, null_clock,
        [_basic(3.0, lane=6), _basic(4.0, lane=7)],
        resonance_chain_threshold=2,
    )
    state = composed.game_state

    aim_x, aim_y = _aim_for_lane(6)
    _advance_to(composed, null_clock, null_input, 2.96)
    _fire_at(composed, null_clock, null_input, 2.97, "fire", aim_x, aim_y)
    assert state.resonance_chain == 1
    assert state.in_overdrive is False

    aim_x, aim_y = _aim_for_lane(7)
    null_input.set_action_held("fire", False)
    null_input.poll()
    _advance_to(composed, null_clock, null_input, 3.96)
    _fire_at(composed, null_clock, null_input, 3.97, "fire", aim_x, aim_y)
    assert state.resonance_chain == 2
    assert state.in_overdrive is True


def test_overdrive_shot_pierces_and_destroys_every_matching_color_candidate_at_once(tmp_path, null_input, null_clock):
    # lanes 0 e 1 (< lane_count/2=4) -> ambas POLARITY_PINK, MESMO instante de impacto
    composed, config = _compose_polarity(
        tmp_path, null_input, null_clock,
        [_basic(3.0, lane=0), _basic(3.0, lane=1)],
        resonance_chain_threshold=2,
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    state = composed.game_state
    state.resonance_color = POLARITY_PINK
    state.resonance_chain = 2  # ja em Overdrive antes do disparo

    _advance_to(composed, null_clock, null_input, 2.99)
    assert threat_pool.count == 2

    aim_x, aim_y = _aim_between_lanes(0, 1)
    _fire_at(composed, null_clock, null_input, 3.0, "fire_alt", aim_x, aim_y)

    assert threat_pool.count == 0  # as DUAS foram abatidas num unico disparo
    assert state.perfect_count == 2
    assert state.combo_count == 2
    assert state.resonance_chain == 4  # cada abate estende a corrente


def test_overdrive_piercing_never_consumes_a_heavy_parry_candidate(tmp_path, null_input, null_clock):
    """Mesmo em Overdrive, uma pesada (Parry) segue sua PROPRIA rota --
    nunca e abatida em lote junto com candidatas comuns."""
    composed, config = _compose_polarity(
        tmp_path, null_input, null_clock,
        [_heavy(3.0, lane=2)],
        resonance_chain_threshold=2,
    )
    state = composed.game_state
    state.resonance_color = POLARITY_PINK
    state.resonance_chain = 2

    aim_x, aim_y = _aim_for_lane(2)
    _advance_to(composed, null_clock, null_input, 2.98)
    _fire_at(composed, null_clock, null_input, 2.99, "fire_alt", aim_x, aim_y)  # QUALQUER cor faz parry

    assert state.parry_count == 1
    assert composed.memory_manager.get_pool("rhythm_threat").count == 1  # refletida, nao destruida
