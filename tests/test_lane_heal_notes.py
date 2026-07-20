"""Arcade 4K: Notas de Cura -- PERFECT recupera vida (clamp em max_health), GOOD pontua mas nao cura, deixar passar e MISS normal."""
import dataclasses

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.components.schemas import JUDGMENT_MISS

from tests.conftest import make_config, write_beatmap


def _heal(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_heal",
        "lane": lane,
        "strength": 0.5,
    }


def _compose_lane_heal(tmp_path, null_input, null_clock, threats, **overrides):
    beatmap_path = write_beatmap(tmp_path / "heal.beatmap.json", threats)
    config = dataclasses.replace(
        make_config(beatmap_path), game_mode="lanes", active_modifiers=("heal",), **overrides
    )
    return compose_world(config, null_input, null_clock), config


def _press_lane(null_input, lane_index: int) -> None:
    null_input.set_action_held(f"lane_{lane_index}", True)
    null_input.poll()


def test_perfect_hit_on_heal_note_restores_one_health(tmp_path, null_input, null_clock):
    composed, config = _compose_lane_heal(tmp_path, null_input, null_clock, [_heal(3.0, lane=0)])
    state = composed.game_state
    state.health = config.max_health - 1

    null_clock.set_now_seconds(2.98)  # dentro da janela PERFECT (0.05)
    _press_lane(null_input, 0)
    composed.world.step(0.016)

    assert state.health == config.max_health
    assert state.perfect_count == 1
    assert state.score == config.score_perfect


def test_heal_never_exceeds_max_health(tmp_path, null_input, null_clock):
    composed, config = _compose_lane_heal(tmp_path, null_input, null_clock, [_heal(3.0, lane=0)])
    state = composed.game_state
    assert state.health == config.max_health

    null_clock.set_now_seconds(2.98)
    _press_lane(null_input, 0)
    composed.world.step(0.016)

    assert state.health == config.max_health  # ja estava no teto, nao passa


def test_good_hit_on_heal_note_scores_but_does_not_heal(tmp_path, null_input, null_clock):
    composed, config = _compose_lane_heal(tmp_path, null_input, null_clock, [_heal(3.0, lane=0)])
    state = composed.game_state
    state.health = config.max_health - 1

    null_clock.set_now_seconds(2.92)  # delta=0.08: dentro do Good (0.10), fora do Perfect (0.05)
    _press_lane(null_input, 0)
    composed.world.step(0.016)

    assert state.good_count == 1
    assert state.score == config.score_good
    assert state.health == config.max_health - 1  # nao curou -- so PERFECT cura


def test_missing_a_heal_note_is_a_normal_miss_with_no_health_penalty(tmp_path, null_input, null_clock):
    composed, config = _compose_lane_heal(tmp_path, null_input, null_clock, [_heal(3.0, lane=0)])
    state = composed.game_state
    state.combo_count = 5

    null_clock.set_now_seconds(3.2)  # alem da janela de miss (0.15)
    null_input.poll()
    composed.world.step(0.016)

    assert state.miss_count == 1
    assert state.combo_count == 0
    assert state.last_judgment == JUDGMENT_MISS
    assert state.health == config.max_health  # MISS normal do Arcade -- sem dano de vida
