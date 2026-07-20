"""Arcade 4K: Notas Toxicas (Bombas) -- pressionar pune sem pontuar; deixar passar sem tocar e o jogo correto."""
import dataclasses

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.components.schemas import JUDGMENT_MISS

from tests.conftest import make_config, write_beatmap


def _bomb(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_bomb",
        "lane": lane,
        "strength": 0.7,
    }


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _compose_lane_bombs(tmp_path, null_input, null_clock, threats, **overrides):
    beatmap_path = write_beatmap(tmp_path / "bomb.beatmap.json", threats)
    config = dataclasses.replace(
        make_config(beatmap_path), game_mode="lanes", active_modifiers=("bombs",), **overrides
    )
    return compose_world(config, null_input, null_clock), config


def _press_lane(null_input, lane_index: int) -> None:
    null_input.set_action_held(f"lane_{lane_index}", True)
    null_input.poll()


def test_pressing_a_bomb_never_scores_and_damages_health(tmp_path, null_input, null_clock):
    composed, config = _compose_lane_bombs(tmp_path, null_input, null_clock, [_bomb(3.0, lane=0)])
    state = composed.game_state
    state.combo_count = 5

    null_clock.set_now_seconds(2.98)
    _press_lane(null_input, 0)
    composed.world.step(0.016)

    assert state.score == 0
    assert state.perfect_count == 0
    assert state.good_count == 0
    assert state.combo_count == 0
    assert state.last_judgment == JUDGMENT_MISS
    assert state.health == config.max_health - 1
    assert composed.memory_manager.get_pool("rhythm_threat").count == 0


def test_pressing_a_bomb_triggers_shake_and_blindness(tmp_path, null_input, null_clock):
    composed, config = _compose_lane_bombs(tmp_path, null_input, null_clock, [_bomb(3.0, lane=0)])

    null_clock.set_now_seconds(2.98)
    _press_lane(null_input, 0)
    composed.world.step(0.0)  # dt=0 isola do decaimento do MESMO frame

    state = composed.game_state
    assert state.shake_intensity == config.bomb_hit_shake_px
    assert state.blindness_timer_sec == config.bomb_blindness_seconds
    assert state.is_blinded is True


def test_letting_a_bomb_pass_untouched_is_survived_without_penalty(tmp_path, null_input, null_clock):
    """O jogo CORRETO com uma Bomba e NAO tocar -- ela some sozinha sem
    punir nada, o oposto do MISS comum de uma nota normal ignorada."""
    composed, config = _compose_lane_bombs(tmp_path, null_input, null_clock, [_bomb(3.0, lane=0)])
    state = composed.game_state
    state.combo_count = 5

    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    null_clock.set_now_seconds(2.5)
    null_input.poll()
    composed.world.step(0.0)
    assert threat_pool.count == 1

    null_clock.set_now_seconds(3.2)  # 0.2s alem da janela de miss (0.15) -- vencida
    null_input.poll()
    composed.world.step(0.016)

    assert threat_pool.count == 0
    assert state.miss_count == 0
    assert state.combo_count == 5  # nao pune
    assert state.health == config.max_health
    assert state.shake_intensity == 0.0


def test_basic_note_is_unaffected_by_bombs_present_in_config(tmp_path, null_input, null_clock):
    composed, config = _compose_lane_bombs(tmp_path, null_input, null_clock, [_basic(3.0, lane=0)])
    null_clock.set_now_seconds(2.98)
    _press_lane(null_input, 0)
    composed.world.step(0.016)

    assert composed.game_state.perfect_count == 1
    assert composed.game_state.health == config.max_health
