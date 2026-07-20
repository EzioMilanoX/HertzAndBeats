"""Defensor -- Gemeos de Polaridade: um evento "twin" nasce como DUAS ameacas opostas no mesmo frame."""
import dataclasses
import math

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.components.schemas import POLARITY_BLUE, POLARITY_PINK

from tests.conftest import make_config, write_beatmap

_LANE_COUNT = 8  # mesmo default de make_config/HertzConfig.lane_count
_TAU = 2.0 * math.pi


def _twin(timestamp: float, lane: int) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_twin",
        "lane": lane,
        "strength": 0.6,
    }


def _basic(timestamp: float, lane: int) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _heavy(timestamp: float, lane: int) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_heavy",
        "lane": lane,
        "strength": 0.9,
    }


def _compose_polarity(tmp_path, null_input, null_clock, threats, **overrides):
    beatmap_path = write_beatmap(tmp_path / "twin.beatmap.json", threats)
    config = dataclasses.replace(
        make_config(beatmap_path),
        active_modifiers=("telegraph_rings", "polarity", "twin_threats"),
        **overrides,
    )
    return compose_world(config, null_input, null_clock), config


def _advance_to(composed, null_clock, null_input, target_seconds: float, dt: float = 0.01) -> None:
    remaining = target_seconds - null_clock.now_seconds()
    steps = int(round(remaining / dt))
    for _ in range(steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)


def test_twin_event_spawns_two_entities_in_diametrically_opposite_lanes(tmp_path, null_input, null_clock):
    composed, config = _compose_polarity(tmp_path, null_input, null_clock, [_twin(3.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _advance_to(composed, null_clock, null_input, 1.01)  # spawn = 3.0 - approach_seconds(2.0)

    assert threat_pool.count == 2
    view = threat_pool.active_view()
    lanes = sorted(int(view["lane"][row]) for row in range(threat_pool.count))
    assert lanes == [0, _LANE_COUNT // 2]


def test_twin_pair_shares_the_same_target_hit_time_and_opposite_angles(tmp_path, null_input, null_clock):
    composed, config = _compose_polarity(tmp_path, null_input, null_clock, [_twin(3.0, lane=1)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _advance_to(composed, null_clock, null_input, 1.01)
    assert threat_pool.count == 2

    view = threat_pool.active_view()
    hit_times = [float(view["target_hit_time_sec"][row]) for row in range(2)]
    assert hit_times[0] == hit_times[1] == 3.0

    angles = sorted(float(view["spawn_angle_rad"][row]) for row in range(2))
    expected_a = _TAU * 1 / _LANE_COUNT
    expected_b = expected_a + math.pi
    assert abs(angles[0] - expected_a) < 1e-5
    assert abs(angles[1] - expected_b) < 1e-5


def test_twin_pair_has_opposite_polarities(tmp_path, null_input, null_clock):
    composed, config = _compose_polarity(tmp_path, null_input, null_clock, [_twin(3.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _advance_to(composed, null_clock, null_input, 1.01)
    assert threat_pool.count == 2

    view = threat_pool.active_view()
    polarities = sorted(int(view["polarity_id"][row]) for row in range(2))
    assert polarities == sorted([POLARITY_PINK, POLARITY_BLUE])


def test_non_twin_threat_type_still_spawns_a_single_entity(tmp_path, null_input, null_clock):
    """Regressao: o novo ramo de Gemeos so dispara para
    `rhythm_threat_twin` -- uma ameaca de outro tipo continua nascendo
    sozinha. Usa uma PESADA (nao uma comum): com "twin_threats" ativo, a
    composicao reinterpreta uma FRACAO das ameacas comuns em Gemeos
    (`_reinterpret_scheduled_for_modifiers`) -- uma pesada nunca e
    elegivel para essa reinterpretacao, entao isola de verdade o
    comportamento do spawner."""
    composed, config = _compose_polarity(tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _advance_to(composed, null_clock, null_input, 1.01)

    assert threat_pool.count == 1


def test_twin_type_is_inert_without_the_polarity_modifier(tmp_path, null_input, null_clock):
    """Sem "polarity" em `active_modifiers`, `twin_threat_type_id` nunca
    e resolvido (fica `None` na composicao) -- um evento "twin" nasce
    como UMA ameaca so, como qualquer outro tipo desconhecido do juiz."""
    beatmap_path = write_beatmap(tmp_path / "twin_off.beatmap.json", [_twin(3.0, lane=0)])
    config = make_config(beatmap_path)  # active_modifiers=("telegraph_rings",) default, sem "polarity"
    composed = compose_world(config, null_input, null_clock)
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _advance_to(composed, null_clock, null_input, 1.01)

    assert threat_pool.count == 1
