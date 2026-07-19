"""Arcade 4K: Notas Fantasmas (Hidden mod) -- tint_a decai linearmente perto do julgamento, a janela de acerto nunca muda."""
import dataclasses

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.systems.visual_modifier_system import compute_hidden_alpha

from tests.conftest import make_config, write_beatmap


def test_compute_hidden_alpha_is_opaque_far_from_the_hit_and_transparent_at_it():
    assert compute_hidden_alpha(delta_seconds=1.0, fade_seconds=0.5) == 255
    assert compute_hidden_alpha(delta_seconds=0.5, fade_seconds=0.5) == 255
    assert compute_hidden_alpha(delta_seconds=0.25, fade_seconds=0.5) == 128
    assert compute_hidden_alpha(delta_seconds=0.0, fade_seconds=0.5) == 0
    assert compute_hidden_alpha(delta_seconds=-0.2, fade_seconds=0.5) == 0


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _compose_hidden(tmp_path, null_input, null_clock, threats, **overrides):
    beatmap_path = write_beatmap(tmp_path / "hidden.beatmap.json", threats)
    config = dataclasses.replace(
        make_config(beatmap_path), game_mode="lanes",
        hidden_notes_enabled=True, hidden_fade_seconds=0.5, **overrides
    )
    return compose_world(config, null_input, null_clock), config


def _advance_to(composed, null_clock, null_input, target_seconds: float, dt: float = 0.01) -> None:
    remaining = target_seconds - null_clock.now_seconds()
    steps = int(round(remaining / dt))
    for _ in range(steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)


def _note_tint_a(composed, entity_index):
    sprite_pool = composed.memory_manager.get_pool("sprite")
    row = sprite_pool.dense_row_of(entity_index)
    return int(sprite_pool.active_view()["tint_a"][row])


def test_note_is_fully_opaque_before_entering_the_fade_window(tmp_path, null_input, null_clock):
    composed, config = _compose_hidden(tmp_path, null_input, null_clock, [_basic(3.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 2.0)  # 1.0s antes do hit -- fora da janela (0.5)
    assert threat_pool.count == 1
    entity_index = int(threat_pool.active_entity_indices()[0])
    assert _note_tint_a(composed, entity_index) == 255


def test_note_fades_out_linearly_approaching_the_judgment_line(tmp_path, null_input, null_clock):
    composed, config = _compose_hidden(tmp_path, null_input, null_clock, [_basic(3.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 2.75)  # 0.25s antes do hit -- metade da janela
    assert threat_pool.count == 1
    entity_index = int(threat_pool.active_entity_indices()[0])
    alpha = _note_tint_a(composed, entity_index)
    assert 100 < alpha < 156  # ~50% (128), com folga para os passos de 0.01s


def test_hidden_fade_never_changes_the_judgment_window(tmp_path, null_input, null_clock):
    """A nota fica invisivel, mas a janela PERFECT/GOOD continua
    EXATAMENTE igual -- o Hidden e 100% visual."""
    composed, config = _compose_hidden(tmp_path, null_input, null_clock, [_basic(3.0, lane=0)])
    _advance_to(composed, null_clock, null_input, 2.99)  # dentro da janela PERFECT (0.05), ja invisivel
    null_input.set_action_held("lane_0", True)
    null_input.poll()
    composed.world.step(0.016)

    state = composed.game_state
    assert state.perfect_count == 1
    assert state.score == config.score_perfect


def test_hidden_disabled_by_default_keeps_notes_always_opaque(tmp_path, null_input, null_clock):
    beatmap_path = write_beatmap(tmp_path / "no_hidden.beatmap.json", [_basic(3.0, lane=0)])
    config = dataclasses.replace(make_config(beatmap_path), game_mode="lanes")
    composed = compose_world(config, null_input, null_clock)
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    remaining = 2.99 - null_clock.now_seconds()
    dt = 0.01
    for _ in range(int(round(remaining / dt))):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)

    assert threat_pool.count == 1
    entity_index = int(threat_pool.active_entity_indices()[0])
    assert _note_tint_a(composed, entity_index) == 255
