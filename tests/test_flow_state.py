"""Flow State ("vidro quebrado"): 50 PERFECTs seguidos apaga o HUD; um Miss o restaura."""
import dataclasses

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.systems.ui_render_system import UIRenderSystem

from tests.conftest import make_config, write_beatmap


def _compose_lanes(tmp_path, null_input, null_clock, threats):
    beatmap_path = write_beatmap(tmp_path / "l.beatmap.json", threats)
    config = dataclasses.replace(make_config(beatmap_path), game_mode="lanes")
    return compose_world(config, null_input, null_clock), config


def _find_ui_system(composed) -> UIRenderSystem:
    for system in composed.world._systems:
        if isinstance(system, UIRenderSystem):
            return system
    raise AssertionError("UIRenderSystem nao registrado")


def _alpha_of(composed, entity_index: int) -> int:
    sprite_pool = composed.memory_manager.get_pool("sprite")
    row = sprite_pool.dense_row_of(int(entity_index))
    return int(sprite_pool.active_view()["tint_a"][row])


def test_flow_combo_threshold_is_wired_only_for_lanes_mode(tmp_path, null_input, null_clock):
    lanes_composed, lanes_config = _compose_lanes(
        tmp_path, null_input, null_clock,
        [{"timestamp_seconds": 99.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.5}],
    )
    assert _find_ui_system(lanes_composed)._flow_combo_threshold == lanes_config.flow_combo_threshold

    beatmap_path = write_beatmap(tmp_path / "d.beatmap.json", [
        {"timestamp_seconds": 99.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.5},
    ])
    defender_composed = compose_world(make_config(beatmap_path), null_input, null_clock)
    assert _find_ui_system(defender_composed)._flow_combo_threshold is None


def test_flow_state_hides_score_combo_and_labels_at_the_threshold(tmp_path, null_input, null_clock):
    composed, config = _compose_lanes(
        tmp_path, null_input, null_clock,
        [{"timestamp_seconds": 99.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.5}],
    )
    ui_system = _find_ui_system(composed)
    state = composed.game_state
    state.score = 12345
    state.combo_count = config.flow_combo_threshold

    null_input.poll()
    composed.world.step(0.016)

    for entity_index in ui_system._score_digit_indices:
        assert _alpha_of(composed, entity_index) == 0
    for entity_index in ui_system._combo_digit_indices:
        assert _alpha_of(composed, entity_index) == 0
    assert _alpha_of(composed, ui_system._judgment_word_entity_index) == 0
    assert _alpha_of(composed, ui_system._score_label_entity_index) == 0
    assert _alpha_of(composed, ui_system._combo_label_entity_index) == 0


def test_flow_state_restores_the_hud_after_a_miss_resets_combo(tmp_path, null_input, null_clock):
    composed, config = _compose_lanes(
        tmp_path, null_input, null_clock,
        [{"timestamp_seconds": 99.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.5}],
    )
    ui_system = _find_ui_system(composed)
    state = composed.game_state
    state.score = 300
    state.combo_count = config.flow_combo_threshold

    null_input.poll()
    composed.world.step(0.016)
    assert _alpha_of(composed, ui_system._score_label_entity_index) == 0  # escondido em Flow

    # um Miss (simulado diretamente -- o mecanismo real e o
    # JudgmentSystem/LaneJudgmentSystem zerando o combo) tira o jogador
    # do Flow: a interface (feia) volta no proximo frame.
    state.combo_count = 0
    null_input.poll()
    composed.world.step(0.016)

    assert _alpha_of(composed, ui_system._score_label_entity_index) == 255
    assert _alpha_of(composed, ui_system._combo_label_entity_index) == 255
    # score=300 -> apenas o digito das centenas/dezenas/unidades visivel
    score_alphas = [_alpha_of(composed, idx) for idx in ui_system._score_digit_indices]
    assert score_alphas[0] == 255  # unidades (0) sempre visivel
    assert score_alphas[:3] == [255, 255, 255]  # 3,0,0
