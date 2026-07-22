"""Developer Tools (Cheats): Auto-Play (Modo Deus), Unlock All e Reset de Save."""
import os

from ouroboros.interfaces.null.null_renderer import NullRenderer

from hertzbeats.audio.sfx_synth import SFX_BOMB, SFX_UNLOCK_ALL
from hertzbeats.bootstrap.hertz_game_loop import (
    FLOW_HUB,
    FLOW_PLAYING,
    FLOW_PREFLIGHT,
    FLOW_TITLE,
)
from hertzbeats.player_progress import delete_progress

from tests.test_match_flow import _basic, _goto_carousel, _goto_hub, _goto_preflight, _press, flow_game


# -- Auto-Play (Modo Deus): JudgmentSystem.bot_mode, Zero-GC -----------------


def test_bot_mode_is_off_by_default(compose):
    composed, _config = compose([_basic(3.0, lane=0)])
    assert composed.game_state.bot_mode is False


def test_bot_mode_auto_hits_perfect_without_any_input(compose, null_clock, null_input):
    """Nenhuma tecla de fogo/mira e pressionada -- prova que
    `JudgmentSystem` ignora o `PlayerInputSystem` por completo enquanto
    `bot_mode` estiver ligado."""
    composed, _config = compose([_basic(3.0, lane=0)])
    composed.game_state.bot_mode = True
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    null_clock.set_now_seconds(3.0)  # delta = 0.0, dentro da janela PERFECT
    null_input.poll()
    composed.world.step(0.016)

    state = composed.game_state
    assert state.perfect_count == 1
    assert state.score == 300
    assert state.combo_count == 1
    assert threat_pool.count == 0


def test_bot_mode_ignores_player_fire_with_wrong_aim(compose, null_clock, null_input):
    """Mesmo com o jogador atirando pra fora do cone/tempo errado, o
    bot ainda resolve a ameaca -- confirma que `_try_player_hit`/mira
    nunca sao consultados em modo bot."""
    composed, _config = compose([_basic(3.0, lane=0)])
    composed.game_state.bot_mode = True

    null_clock.set_now_seconds(3.0)
    null_input.set_axis("aim_x", 0.0)
    null_input.set_axis("aim_y", -1.0)  # 90 graus fora
    null_input.set_action_held("fire", True)
    null_input.poll()
    composed.world.step(0.016)

    assert composed.game_state.perfect_count == 1


def test_bot_mode_leaves_a_future_threat_untouched(compose, null_clock, null_input):
    composed, _config = compose([_basic(3.0, lane=0)])
    composed.game_state.bot_mode = True
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    null_clock.set_now_seconds(1.0)  # delta = 2.0, bem fora da janela PERFECT
    null_input.poll()
    composed.world.step(0.016)

    assert composed.game_state.perfect_count == 0
    assert threat_pool.count == 1


def test_bot_mode_resolves_an_already_overdue_threat_too(compose, null_clock, null_input):
    """Ligar o modo com uma ameaca ja MUITO atrasada (delta bem
    negativo) nao deixa nada preso PENDING pra sempre -- ainda resolve
    como PERFECT."""
    composed, _config = compose([_basic(3.0, lane=0)])
    composed.game_state.bot_mode = True

    null_clock.set_now_seconds(10.0)
    null_input.poll()
    composed.world.step(0.016)

    assert composed.game_state.perfect_count == 1


def test_bot_mode_resolves_multiple_ready_threats_in_the_same_frame(compose, null_clock, null_input):
    composed, _config = compose([_basic(3.0, lane=0), _basic(3.01, lane=1)])
    composed.game_state.bot_mode = True

    null_clock.set_now_seconds(3.0)
    null_input.poll()
    composed.world.step(0.016)

    state = composed.game_state
    assert state.perfect_count == 2
    assert state.combo_count == 2
    assert state.max_combo == 2
    assert state.score == 600


def test_bot_mode_with_no_active_threats_does_not_crash(compose, null_clock, null_input):
    composed, _config = compose([_basic(99.0, lane=0)])  # nada spawnado ainda
    composed.game_state.bot_mode = True

    null_clock.set_now_seconds(1.0)
    null_input.poll()
    composed.world.step(0.016)  # nao deve levantar

    assert composed.game_state.perfect_count == 0


# -- Auto-Play: HertzGameLoop (F12 no Pre-Voo, indicador do HUD) -------------


def test_f12_in_preflight_toggles_bot_mode_enabled(flow_game, null_input):
    loop, _clock = flow_game([[_basic(3.0)]])
    _goto_preflight(loop, null_input, "campaign")
    assert loop.flow == FLOW_PREFLIGHT
    assert loop._bot_mode_enabled is False

    _press(loop, null_input, "toggle_bot_mode")
    assert loop._bot_mode_enabled is True

    _press(loop, null_input, "toggle_bot_mode")
    assert loop._bot_mode_enabled is False


def test_f12_toggles_bot_mode_in_selectable_preflight_too(flow_game, null_input):
    """Musica do jogador (Free Play) tambem tem o painel de opcoes
    completo -- F12 precisa funcionar ANTES daquele branch, nao so nas
    fases curadas."""
    loop, _clock = flow_game([[_basic(3.0)]], selectable_list=[True])
    _goto_preflight(loop, null_input, "free_play")
    assert loop.flow == FLOW_PREFLIGHT

    _press(loop, null_input, "toggle_bot_mode")
    assert loop._bot_mode_enabled is True


def test_starting_a_stage_copies_bot_mode_enabled_into_game_state(flow_game, null_input):
    loop, _clock = flow_game([[_basic(3.0)]])
    _goto_preflight(loop, null_input, "campaign")
    _press(loop, null_input, "toggle_bot_mode")
    assert loop._bot_mode_enabled is True

    _press(loop, null_input, "confirm")  # PREFLIGHT (curada) -> START
    assert loop.flow == FLOW_PLAYING
    assert loop._composed.game_state.bot_mode is True


def test_bot_mode_enabled_stays_off_by_default_when_starting_a_stage(flow_game, null_input):
    loop, _clock = flow_game([[_basic(3.0)]])
    _goto_preflight(loop, null_input, "campaign")
    _press(loop, null_input, "confirm")
    assert loop._composed.game_state.bot_mode is False


def test_sync_bot_mode_indicator_reflects_playing_state(flow_game, null_input):
    calls = []

    class _RecordingRenderer(NullRenderer):
        def set_bot_mode_active(self, active):
            calls.append(active)

    loop, _clock = flow_game([[_basic(3.0)]])
    loop._renderer = _RecordingRenderer()
    _goto_preflight(loop, null_input, "campaign")
    _press(loop, null_input, "toggle_bot_mode")
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_PLAYING

    loop._sync_bot_mode_indicator()
    assert calls[-1] is True

    loop._composed.game_state.bot_mode = False
    loop._sync_bot_mode_indicator()
    assert calls[-1] is False


def test_draw_bot_mode_indicator_renders_without_crashing():
    from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
    from hertzbeats.adapters.texture_bank import build_and_register_overlay_surfaces
    from hertzbeats.stages import StageDef

    stage = StageDef(
        stage_id="s", name="FASE", subtitle="", track_path="", beatmap_path="unused",
        synth=None, beatmap_params={}, overrides={},
    )
    renderer = HBPygameRenderer()
    renderer.initialize(320, 240, "test")
    build_and_register_overlay_surfaces(renderer, (stage,))

    renderer.set_bot_mode_active(True)
    renderer.end_frame()  # nao deve levantar, mesmo com o overlay/notice ausentes

    renderer.set_bot_mode_active(False)
    renderer.end_frame()


# -- Unlock All: Konami Code na Tela de Titulo -------------------------------


def _press_sequence(loop, null_input, actions) -> None:
    for action in actions:
        _press(loop, null_input, action)


def test_correct_sequence_unlocks_all_and_plays_a_confirmation_sfx(flow_game, null_input):
    loop, _clock = flow_game([[_basic(3.0)]])
    assert loop.flow == FLOW_TITLE
    assert loop._debug_unlock_all is False

    _press_sequence(
        loop, null_input,
        ("menu_up", "menu_up", "menu_down", "menu_down", "menu_left", "menu_right"),
    )

    assert loop._debug_unlock_all is True
    assert any(sound_id == SFX_UNLOCK_ALL for sound_id, _ in loop._audio_engine._one_shots_played)


def test_wrong_key_in_the_sequence_resets_progress(flow_game, null_input):
    loop, _clock = flow_game([[_basic(3.0)]])
    _press(loop, null_input, "menu_up")
    assert loop._unlock_code_progress == 1

    _press(loop, null_input, "menu_right")  # errado -- reinicia do zero
    assert loop._unlock_code_progress == 0
    assert loop._debug_unlock_all is False

    # a sequencia completa AINDA funciona depois do erro
    _press_sequence(
        loop, null_input,
        ("menu_up", "menu_up", "menu_down", "menu_down", "menu_left", "menu_right"),
    )
    assert loop._debug_unlock_all is True


def test_unrelated_actions_do_not_disturb_the_buffer(flow_game, null_input):
    loop, _clock = flow_game([[_basic(3.0)]])
    _press(loop, null_input, "menu_up")
    _press(loop, null_input, "pause")  # ESC: nao mexe no progresso do buffer
    assert loop._unlock_code_progress == 1
    assert loop.flow == FLOW_TITLE  # ESC so chama stop() (_running=False), nunca muda _flow


def test_unlock_all_persists_after_leaving_the_title_screen(flow_game, null_input):
    loop, _clock = flow_game([[_basic(3.0)]])
    _press_sequence(
        loop, null_input,
        ("menu_up", "menu_up", "menu_down", "menu_down", "menu_left", "menu_right"),
    )
    assert loop._debug_unlock_all is True

    _goto_hub(loop, null_input)
    assert loop.flow == FLOW_HUB
    assert loop._debug_unlock_all is True  # nenhuma tela desliga de novo


def test_is_campaign_entry_locked_bypassed_by_unlock_all(flow_game, null_input):
    loop, _clock = flow_game(
        [[_basic(3.0)], [_basic(3.0)]], campaign_id_list=["default", "default"],
    )
    assert loop.is_campaign_entry_locked("default", 1) is True  # stage0 nunca vencida

    loop._debug_unlock_all = True
    assert loop.is_campaign_entry_locked("default", 1) is False


def test_confirming_a_locked_stage_with_unlock_all_enters_preflight(flow_game, null_input):
    loop, _clock = flow_game(
        [[_basic(3.0)], [_basic(3.0)]], campaign_id_list=["default", "default"],
    )
    loop._debug_unlock_all = True
    _goto_carousel(loop, null_input, "campaign")
    _press(loop, null_input, "menu_down")  # posicao 1 (trancada sem Unlock All)
    _press(loop, null_input, "confirm")

    assert loop.flow == FLOW_PREFLIGHT
    assert loop._notice_key != "stage_locked"


# -- Reset de Save (Ctrl+Shift+Del) -------------------------------------------


def test_delete_progress_is_idempotent_on_a_missing_file(tmp_path):
    path = str(tmp_path / "does_not_exist.json")
    delete_progress(path)  # nao deve levantar
    delete_progress(path)  # 2x seguidas tambem nao


def test_wipe_save_in_hub_deletes_the_file_and_clears_memory_and_plays_bomb_sfx(flow_game, null_input):
    loop, _clock = flow_game([[_basic(3.0)]])
    progress_path = loop._player_progress_path
    with open(progress_path, "w", encoding="utf-8") as f:
        f.write('{"stage0": {"modifiers": [], "best_rank": "S"}}')
    loop._player_progress = {"stage0": {"modifiers": frozenset(), "best_rank": "S"}}

    _goto_hub(loop, null_input)
    _press(loop, null_input, "wipe_save")

    assert loop._player_progress == {}
    assert not os.path.exists(progress_path)
    assert any(sound_id == SFX_BOMB for sound_id, _ in loop._audio_engine._one_shots_played)
    assert loop.flow == FLOW_HUB  # continua no HUB, nao navega pra outro lugar


def test_wipe_save_in_vault_also_works(flow_game, null_input):
    from hertzbeats.bootstrap.hertz_game_loop import FLOW_VAULT

    loop, _clock = flow_game([[_basic(3.0)]])
    progress_path = loop._player_progress_path
    with open(progress_path, "w", encoding="utf-8") as f:
        f.write('{"stage0": {"modifiers": [], "best_rank": "S"}}')
    loop._player_progress = {"stage0": {"modifiers": frozenset(), "best_rank": "S"}}

    _goto_hub(loop, null_input)
    from hertzbeats.bootstrap.hertz_game_loop import HUB_CATEGORIES
    target = HUB_CATEGORIES.index("vault")
    while loop.hub_cursor != target:
        _press(loop, null_input, "menu_down")
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_VAULT

    _press(loop, null_input, "wipe_save")

    assert loop._player_progress == {}
    assert not os.path.exists(progress_path)
    assert loop.flow == FLOW_VAULT
