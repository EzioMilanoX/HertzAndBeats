"""UI Bump (Juice Visual): digitos do combo destacam ao cruzar um multiplo de 50, esmaecendo de volta."""
from hertzbeats.components.texture_ids import BUMP_FADE_STEPS, TEX_DIGIT_BASE, TEX_DIGIT_BUMP_BASE

from tests.conftest import make_config, write_beatmap
from hertzbeats.bootstrap.rhythm_composition_root import compose_world


def _find_ui_system(composed):
    from hertzbeats.systems.ui_render_system import UIRenderSystem

    for system in composed.world._systems:
        if isinstance(system, UIRenderSystem):
            return system
    raise AssertionError("UIRenderSystem nao registrado")


def _compose(tmp_path, null_input, null_clock):
    beatmap_path = write_beatmap(tmp_path / "bump.beatmap.json", [])
    config = make_config(beatmap_path)
    return compose_world(config, null_input, null_clock), config


def test_crossing_a_multiple_of_50_arms_the_bump_timer(tmp_path, null_input, null_clock):
    composed, config = _compose(tmp_path, null_input, null_clock)
    ui_system = _find_ui_system(composed)
    state = composed.game_state

    state.combo_count = 49
    composed.world.step(0.016)
    assert ui_system._bump_timer_seconds == 0.0

    state.combo_count = 50
    composed.world.step(0.016)
    # arma no MESMO frame em que ja decai por delta_time (mesmo criterio
    # de todo timer de "game feel" do jogo, ex. Hold Forgiveness).
    assert ui_system._bump_timer_seconds == config.combo_bump_seconds - 0.016


def test_a_piercing_kill_style_jump_that_skips_over_50_still_triggers_the_bump(tmp_path, null_input, null_clock):
    """Overdrive/piercing kill pode somar VARIOS combos no mesmo frame,
    pulando por cima do multiplo exato (ex.: 48 -> 51) -- a deteccao
    compara TIERS (`combo // limiar`), nao `% limiar == 0`."""
    composed, config = _compose(tmp_path, null_input, null_clock)
    ui_system = _find_ui_system(composed)
    state = composed.game_state

    state.combo_count = 48
    composed.world.step(0.016)
    state.combo_count = 51  # pulou o 50 exato
    composed.world.step(0.016)
    assert ui_system._bump_timer_seconds == config.combo_bump_seconds - 0.016


def test_bump_timer_decays_with_delta_time_and_never_retriggers_on_a_miss(tmp_path, null_input, null_clock):
    composed, config = _compose(tmp_path, null_input, null_clock)
    ui_system = _find_ui_system(composed)
    state = composed.game_state

    state.combo_count = 50
    composed.world.step(0.016)
    assert ui_system._bump_timer_seconds == config.combo_bump_seconds - 0.016

    state.combo_count = 0  # MISS zera o combo -- nao deve rearmar o bump
    composed.world.step(0.1)
    assert ui_system._bump_timer_seconds == config.combo_bump_seconds - 0.016 - 0.1


def test_combo_digit_texture_base_is_the_bump_gradient_while_armed_and_default_after(tmp_path, null_input, null_clock):
    composed, config = _compose(tmp_path, null_input, null_clock)
    ui_system = _find_ui_system(composed)
    state = composed.game_state

    state.combo_count = 50
    composed.world.step(0.016)
    base = ui_system._combo_digit_texture_base()
    assert TEX_DIGIT_BUMP_BASE <= base < TEX_DIGIT_BUMP_BASE + BUMP_FADE_STEPS * 10
    assert (base - TEX_DIGIT_BUMP_BASE) % 10 == 0  # sempre a BASE de um estagio, nunca um digito especifico

    # deixa o timer esgotar por completo
    composed.world.step(config.combo_bump_seconds + 0.1)
    assert ui_system._combo_digit_texture_base() == TEX_DIGIT_BASE


def test_score_digits_never_use_the_bump_texture_base(tmp_path, null_input, null_clock):
    composed, config = _compose(tmp_path, null_input, null_clock)
    ui_system = _find_ui_system(composed)
    sprite_pool = composed.memory_manager.get_pool("sprite")

    composed.game_state.combo_count = 50
    composed.game_state.score = 3
    composed.world.step(0.016)

    score_row = sprite_pool.dense_row_of(int(ui_system._score_digit_indices[0]))
    texture_id = int(sprite_pool.active_view()["texture_id"][score_row])
    assert TEX_DIGIT_BASE <= texture_id < TEX_DIGIT_BASE + 10  # SEMPRE branco, nunca dourado
