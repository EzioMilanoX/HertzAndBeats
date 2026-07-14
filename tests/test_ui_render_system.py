"""UIRenderSystem: extracao de digitos por aritmetica e HUD como sprites comuns."""
from hertzbeats.components.schemas import JUDGMENT_PERFECT
from hertzbeats.components.texture_ids import TEX_DIGIT_BASE, TEX_WORD_PERFECT
from hertzbeats.systems.ui_render_system import UIRenderSystem


def _find_ui_system(composed) -> UIRenderSystem:
    for system in composed.world._systems:
        if isinstance(system, UIRenderSystem):
            return system
    raise AssertionError("UIRenderSystem nao registrado")


def _digit_sprites(composed, ui_system, which: str):
    sprite_pool = composed.memory_manager.get_pool("sprite")
    view = sprite_pool.active_view()
    indices = getattr(ui_system, which)
    rows = sprite_pool.dense_rows_of(indices)
    return view["texture_id"][rows], view["tint_a"][rows]


def test_combo_142_extracts_digits_1_4_2(compose, null_clock, null_input):
    composed, _ = compose([{"timestamp_seconds": 99.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.5}])
    composed.game_state.combo_count = 142
    null_input.poll()
    composed.world.step(0.016)

    ui_system = _find_ui_system(composed)
    texture_ids, alphas = _digit_sprites(composed, ui_system, "_combo_digit_indices")
    # ordem: digito menos significativo primeiro -> 2, 4, 1, (oculto)
    assert int(texture_ids[0]) == TEX_DIGIT_BASE + 2
    assert int(texture_ids[1]) == TEX_DIGIT_BASE + 4
    assert int(texture_ids[2]) == TEX_DIGIT_BASE + 1
    assert list(alphas[:3]) == [255, 255, 255]
    assert int(alphas[3]) == 0  # zero a esquerda oculto


def test_score_zero_shows_single_zero_digit(compose, null_clock, null_input):
    composed, _ = compose([{"timestamp_seconds": 99.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.5}])
    null_input.poll()
    composed.world.step(0.016)

    ui_system = _find_ui_system(composed)
    texture_ids, alphas = _digit_sprites(composed, ui_system, "_score_digit_indices")
    assert int(texture_ids[0]) == TEX_DIGIT_BASE + 0
    assert int(alphas[0]) == 255
    assert all(int(a) == 0 for a in alphas[1:])


def test_judgment_word_shows_and_expires(compose, null_clock, null_input):
    composed, _ = compose([{"timestamp_seconds": 99.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.5}])
    state = composed.game_state
    state.register_judgment_feedback(JUDGMENT_PERFECT, 0.10)

    null_input.poll()
    composed.world.step(0.016)
    ui_system = _find_ui_system(composed)
    sprite_pool = composed.memory_manager.get_pool("sprite")
    view = sprite_pool.active_view()
    word_row = sprite_pool.dense_row_of(ui_system._judgment_word_entity_index)
    assert int(view["texture_id"][word_row]) == TEX_WORD_PERFECT
    assert int(view["tint_a"][word_row]) == 255

    for _ in range(8):  # 8 x 16ms > 100ms: o timer expira
        composed.world.step(0.016)
    assert int(view["tint_a"][sprite_pool.dense_row_of(ui_system._judgment_word_entity_index)]) == 0


def test_health_pips_follow_health(compose, null_clock, null_input):
    composed, _ = compose([{"timestamp_seconds": 99.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.5}])
    composed.game_state.health = 1
    null_input.poll()
    composed.world.step(0.016)

    ui_system = _find_ui_system(composed)
    sprite_pool = composed.memory_manager.get_pool("sprite")
    view = sprite_pool.active_view()
    alphas = [
        int(view["tint_a"][sprite_pool.dense_row_of(int(idx))])
        for idx in ui_system._health_pip_indices
    ]
    assert alphas == [255, 45, 45]
