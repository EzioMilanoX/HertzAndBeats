"""Rogue-lite Endgame: HUB -> Mapa -> Fase -> Recompensa -> Mapa, vida persistente, corrida encerra na derrota/saida."""
import math

import pytest

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.adapters.texture_bank import build_and_register_overlay_surfaces
from hertzbeats.bootstrap.hertz_game_loop import (
    FLOW_GAME_OVER,
    FLOW_HUB,
    FLOW_PAUSED,
    FLOW_PLAYING,
    FLOW_ROGUELITE_MAP,
    FLOW_ROGUELITE_REWARD,
    HUB_CATEGORIES,
)
from hertzbeats.rogue_lite import PERK_PERFECT_WINDOW_MULTIPLIER, PERK_VAMPIRISM_THRESHOLD, ROGUE_PERK_CATALOG
from hertzbeats.stages import StageDef

from tests.test_match_flow import DT, _basic, _goto_hub, _press, flow_game  # noqa: F401


def _goto_roguelite(loop, null_input) -> None:
    _goto_hub(loop, null_input)
    target = HUB_CATEGORIES.index("roguelite")
    while loop.hub_cursor != target:
        _press(loop, null_input, "menu_down")
    _press(loop, null_input, "confirm")  # HUB -> inicia a corrida direto, sem Carrossel/Pre-Voo


def _win_current_stage(loop, clock, null_input, timestamp: float, lane: int) -> None:
    """Mira na `lane` e atira exatamente no instante da unica ameaca da
    fase (mesma formula/criterio de `test_match_flow._play_to_results`),
    depois deixa os frames rodarem ate a carencia de resultados esgotar
    -- serve tanto pra FLOW_RESULTS quanto pra FLOW_ROGUELITE_REWARD
    (o chamador decide o que checar depois)."""
    angle = 2.0 * math.pi * lane / 8.0
    null_input.set_axis("aim_x", math.cos(angle))
    null_input.set_axis("aim_y", math.sin(angle))
    clock.set_now_seconds(timestamp)
    _press(loop, null_input, "fire")
    for _ in range(80):
        clock.advance(DT)
        loop.advance_frame(DT)
        if loop.flow != FLOW_PLAYING:
            break


def _lose_current_stage(loop, clock) -> None:
    """Sem atirar: a ameaca viaja e colide vencida com o nucleo -- 1 MISS
    (com `max_health=1`) basta pra Game Over."""
    for _ in range(400):
        clock.advance(DT)
        loop.advance_frame(DT)
        if loop.flow == FLOW_GAME_OVER:
            break


# -- HUB -> Mapa --------------------------------------------------------


def test_confirming_roguelite_in_the_hub_starts_a_run_and_shows_the_map(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0, lane=0)], [_basic(3.0, lane=1)]], selectable_list=[True, True])
    _goto_roguelite(loop, null_input)
    assert loop.flow == FLOW_ROGUELITE_MAP
    assert loop.rogue_run_active is True
    assert loop.rogue_run_state().health == loop._base_config.max_health
    assert loop.rogue_run_state().stage_level == 1
    choices = loop.rogue_map_choices()
    assert len(choices) == 2
    for stage_index, modifiers in choices:
        assert loop._stages[stage_index].selectable_mode is True
        assert modifiers[0] in ("wormholes", "mirages", "rubber_band")


def test_roguelite_map_with_no_player_songs_shows_empty_and_esc_cancels(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[False])
    _goto_roguelite(loop, null_input)
    assert loop.flow == FLOW_ROGUELITE_MAP
    assert loop.rogue_map_choices() == ((), ())
    _press(loop, null_input, "pause")
    assert loop.flow == FLOW_HUB
    assert loop.rogue_run_active is False


def test_esc_at_the_map_cancels_the_run_and_returns_to_the_hub(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0, lane=0)], [_basic(3.0, lane=1)]], selectable_list=[True, True])
    _goto_roguelite(loop, null_input)
    _press(loop, null_input, "pause")
    assert loop.flow == FLOW_HUB
    assert loop.rogue_run_active is False


def test_picking_a_map_song_starts_it_with_the_forced_modifier_and_no_preflight(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0, lane=0)], [_basic(3.0, lane=1)]], selectable_list=[True, True])
    _goto_roguelite(loop, null_input)
    stage_index, forced_modifiers = loop.rogue_map_choices()[0]

    _press(loop, null_input, "confirm")  # cursor comeca em 0 -- pula Pre-Voo, comeca direto
    assert loop.flow == FLOW_PLAYING
    assert loop.loaded_stage == stage_index
    assert loop._stage_config.active_modifiers == forced_modifiers
    assert loop._stage_config.game_mode == "defender"


def test_menu_left_right_toggles_the_map_cursor_between_the_two_choices(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0, lane=0)], [_basic(3.0, lane=1)]], selectable_list=[True, True])
    _goto_roguelite(loop, null_input)
    assert loop._rogue_map_cursor == 0
    _press(loop, null_input, "menu_right")
    assert loop._rogue_map_cursor == 1
    _press(loop, null_input, "menu_left")
    assert loop._rogue_map_cursor == 0


def test_a_forced_map_modifier_never_leaks_into_the_normal_free_play_menu(flow_game, null_input):
    """`_rogue_map_active_modifiers` e' um campo PROPRIO (nao
    `_chosen_modifiers`, o dict compartilhado com o Pre-Voo normal) --
    jogar essa musica de novo pelo Free Play comum nao deveria mostrar
    o modifier forcado ainda "ligado"."""
    loop, _ = flow_game([[_basic(3.0, lane=0)], [_basic(3.0, lane=1)]], selectable_list=[True, True])
    _goto_roguelite(loop, null_input)
    stage_index, _forced = loop.rogue_map_choices()[0]
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_PLAYING

    assert loop.chosen_modifiers(stage_index) == frozenset()  # nunca gravado no dict compartilhado


# -- Vitoria -> Recompensa (nunca Resultados) -----------------------------


def test_winning_a_roguelite_stage_goes_to_reward_not_results(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0, lane=0)], [_basic(3.0, lane=1)]], selectable_list=[True, True])
    _goto_roguelite(loop, null_input)
    stage_index, _mods = loop.rogue_map_choices()[0]
    lane = 0 if stage_index == 0 else 1
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_PLAYING

    _win_current_stage(loop, clock, null_input, 3.0, lane)
    assert loop.flow == FLOW_ROGUELITE_REWARD
    choices = loop.rogue_reward_choices()
    assert len(choices) == 2
    assert set(choices) <= set(ROGUE_PERK_CATALOG)


def test_picking_a_reward_perk_adds_it_and_returns_to_a_fresh_map(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0, lane=0)], [_basic(3.0, lane=1)]], selectable_list=[True, True])
    _goto_roguelite(loop, null_input)
    stage_index, _mods = loop.rogue_map_choices()[0]
    lane = 0 if stage_index == 0 else 1
    _press(loop, null_input, "confirm")
    _win_current_stage(loop, clock, null_input, 3.0, lane)
    assert loop.flow == FLOW_ROGUELITE_REWARD

    picked_perk = loop.rogue_reward_choices()[0]
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_ROGUELITE_MAP
    assert picked_perk in loop.rogue_run_state().perks
    assert loop.rogue_run_state().stage_level == 2
    assert len(loop.rogue_map_choices()) == 2  # um novo sorteio de mapa ja pronto


def test_reward_menu_left_right_toggles_the_perk_cursor(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0, lane=0)], [_basic(3.0, lane=1)]], selectable_list=[True, True])
    _goto_roguelite(loop, null_input)
    stage_index, _mods = loop.rogue_map_choices()[0]
    lane = 0 if stage_index == 0 else 1
    _press(loop, null_input, "confirm")
    _win_current_stage(loop, clock, null_input, 3.0, lane)

    assert loop._rogue_reward_cursor == 0
    _press(loop, null_input, "menu_right")
    assert loop._rogue_reward_cursor == 1
    _press(loop, null_input, "menu_left")
    assert loop._rogue_reward_cursor == 0


def test_esc_at_the_reward_screen_cancels_the_run(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0, lane=0)], [_basic(3.0, lane=1)]], selectable_list=[True, True])
    _goto_roguelite(loop, null_input)
    stage_index, _mods = loop.rogue_map_choices()[0]
    lane = 0 if stage_index == 0 else 1
    _press(loop, null_input, "confirm")
    _win_current_stage(loop, clock, null_input, 3.0, lane)
    assert loop.flow == FLOW_ROGUELITE_REWARD

    _press(loop, null_input, "pause")
    assert loop.flow == FLOW_HUB
    assert loop.rogue_run_active is False


# -- Vida persistente entre fases -----------------------------------------


def test_health_carries_over_between_roguelite_stages_clamped_to_the_new_max(flow_game, null_input):
    # indice 0 tem teto 5 de vida, indice 1 tem teto 1 -- o teste
    # NAVEGA o cursor ate cada uma explicitamente (em vez de confirmar
    # cego na posicao sorteada) pra nao depender de qual das 2 o Mapa
    # colocou em foco primeiro.
    loop, clock = flow_game(
        [[_basic(3.0, lane=1)], [_basic(3.0, lane=2)]],
        selectable_list=[True, True],
        overrides_list=[{"max_health": 5}, {"max_health": 1}],
    )
    _goto_roguelite(loop, null_input)
    base_health = loop._base_config.max_health  # 3, no HertzConfig de teste (make_config)
    assert loop.rogue_run_state().health == base_health

    choices = loop.rogue_map_choices()
    cursor_for_high_cap = 0 if choices[0][0] == 0 else 1
    while loop._rogue_map_cursor != cursor_for_high_cap:
        _press(loop, null_input, "menu_right")
    _press(loop, null_input, "confirm")
    assert loop.loaded_stage == 0
    assert loop.composed.game_state.health == base_health  # min(3, 5) -- clampado ao rogue_run, nao ao teto da fase

    _win_current_stage(loop, clock, null_input, 3.0, 1)
    assert loop.flow == FLOW_ROGUELITE_REWARD
    assert loop.rogue_run_state().health == base_health  # venceu sem tomar dano -- vida intacta

    _press(loop, null_input, "confirm")  # escolhe o Perk em foco -> novo Mapa
    assert loop.flow == FLOW_ROGUELITE_MAP

    # forca a proxima fase a ser a OUTRA musica (teto = 1 de vida) --
    # navega o cursor ate ela, seja qual for a posicao sorteada.
    new_choices = loop.rogue_map_choices()
    cursor_for_low_cap = 0 if new_choices[0][0] == 1 else 1
    while loop._rogue_map_cursor != cursor_for_low_cap:
        _press(loop, null_input, "menu_right")
    _press(loop, null_input, "confirm")
    assert loop.loaded_stage == 1
    assert loop.composed.game_state.health == 1  # min(vida carregada, teto novo) -- nunca curado ao entrar


# -- Derrota encerra a corrida ---------------------------------------------


def test_losing_a_roguelite_stage_ends_the_run(flow_game, null_input):
    # lane=1/2 (nunca `lane % 4 == 0`) de proposito: se o Mapa sortear
    # "mirages" pra qualquer uma das 2 musicas, uma ameaca elegivel
    # (lane%4==0) sumiria em SILENCIO perto do impacto (sem dano) em vez
    # de vencer o jogador -- este teste quer SEMPRE um MISS de verdade,
    # independente de qual dos 3 modifiers de Mind Games for sorteado.
    loop, clock = flow_game(
        [[_basic(3.0, lane=1)], [_basic(3.0, lane=2)]],
        selectable_list=[True, True],
        overrides_list=[{"max_health": 1}, {"max_health": 1}],
    )
    _goto_roguelite(loop, null_input)
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_PLAYING
    assert loop.rogue_run_active is True

    _lose_current_stage(loop, clock)
    assert loop.flow == FLOW_GAME_OVER
    assert loop.rogue_run_active is False  # a corrida acabou -- Perks/nivel perdidos


def test_pausing_and_leaving_to_the_menu_during_a_roguelite_stage_cancels_it(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0, lane=0)], [_basic(3.0, lane=1)]], selectable_list=[True, True])
    _goto_roguelite(loop, null_input)
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_PLAYING

    _press(loop, null_input, "pause")
    assert loop.flow == FLOW_PAUSED
    _press(loop, null_input, "to_menu")
    assert loop.flow == FLOW_HUB
    assert loop.rogue_run_active is False


# -- Perks: multiplicadores puros, resolvidos na composicao ---------------


def test_vampirism_perk_threads_a_nonzero_combo_threshold_into_the_next_stage(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0, lane=0)], [_basic(3.0, lane=1)]], selectable_list=[True, True])
    _goto_roguelite(loop, null_input)
    stage_index, _mods = loop.rogue_map_choices()[0]
    lane = 0 if stage_index == 0 else 1
    _press(loop, null_input, "confirm")
    assert loop._stage_config.vampirism_combo_threshold == 0  # sem Perk ainda -- desligado

    _win_current_stage(loop, clock, null_input, 3.0, lane)
    reward_choices = loop.rogue_reward_choices()
    target_cursor = reward_choices.index(PERK_VAMPIRISM_THRESHOLD)
    while loop._rogue_reward_cursor != target_cursor:
        _press(loop, null_input, "menu_right")
    _press(loop, null_input, "confirm")
    assert PERK_VAMPIRISM_THRESHOLD in loop.rogue_run_state().perks

    _press(loop, null_input, "confirm")  # proxima musica do Mapa
    assert loop.flow == FLOW_PLAYING
    expected = ROGUE_PERK_CATALOG[PERK_VAMPIRISM_THRESHOLD]["vampirism_combo_threshold"]
    assert loop._stage_config.vampirism_combo_threshold == expected
    assert loop._stage_config.vampirism_max_health == loop._stage_config.max_health


def test_perfect_window_multiplier_perk_widens_the_window_for_the_next_stage(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0, lane=0)], [_basic(3.0, lane=1)]], selectable_list=[True, True])
    _goto_roguelite(loop, null_input)
    stage_index, _mods = loop.rogue_map_choices()[0]
    lane = 0 if stage_index == 0 else 1
    base_window = loop._base_config.perfect_window_seconds
    _press(loop, null_input, "confirm")
    assert loop._stage_config.perfect_window_seconds == pytest.approx(base_window)

    _win_current_stage(loop, clock, null_input, 3.0, lane)
    reward_choices = loop.rogue_reward_choices()
    target_cursor = reward_choices.index(PERK_PERFECT_WINDOW_MULTIPLIER)
    while loop._rogue_reward_cursor != target_cursor:
        _press(loop, null_input, "menu_right")
    _press(loop, null_input, "confirm")
    _press(loop, null_input, "confirm")  # proxima musica
    assert loop.flow == FLOW_PLAYING

    expected_multiplier = ROGUE_PERK_CATALOG[PERK_PERFECT_WINDOW_MULTIPLIER]["perfect_window_multiplier"]
    assert loop._stage_config.perfect_window_seconds == pytest.approx(base_window * expected_multiplier)


# -- Renderer real: HUB + Mapa/Recompensa ----------------------------------


def test_hub_category_roguelite_has_registered_label_textures():
    stage = StageDef(
        stage_id="s", name="FASE", subtitle="", track_path="", beatmap_path="unused",
        synth=None, beatmap_params={}, overrides={},
    )
    renderer = HBPygameRenderer()
    renderer.initialize(120, 120, "test")
    build_and_register_overlay_surfaces(renderer, (stage,))
    assert renderer._overlay_surfaces.get("hub_category_roguelite") is not None
    assert renderer._overlay_surfaces.get("hub_category_roguelite_sel") is not None


def test_roguelite_map_and_reward_overlay_textures_are_registered():
    stage = StageDef(
        stage_id="s", name="FASE", subtitle="", track_path="", beatmap_path="unused",
        synth=None, beatmap_params={}, overrides={},
    )
    renderer = HBPygameRenderer()
    renderer.initialize(120, 120, "test")
    build_and_register_overlay_surfaces(renderer, (stage,))
    assert renderer._overlay_surfaces.get("roguelite_map_title") is not None
    assert renderer._overlay_surfaces.get("roguelite_reward_title") is not None
    assert renderer._overlay_surfaces.get("label_rogue_health") is not None
    assert renderer._overlay_surfaces.get("label_rogue_level") is not None
    for modifier_name in ("wormholes", "mirages", "rubber_band"):
        assert renderer._overlay_surfaces.get(f"roguelite_modifier_{modifier_name}") is not None
    for perk_id in ROGUE_PERK_CATALOG:
        assert renderer._overlay_surfaces.get(f"roguelite_perk_{perk_id}") is not None
        assert renderer._overlay_surfaces.get(f"roguelite_perk_{perk_id}_sel") is not None


def test_roguelite_map_overlay_draws_without_error_via_null_choices():
    """`set_overlay`/`_draw_overlay` com `roguelite_info=None` (fora das
    2 telas) e com listas VAZIAS (sem musicas de jogador) nao pode
    lancar excecao -- cobre o caminho `song_choices=()` do
    `_draw_roguelite_map_overlay`."""
    stage = StageDef(
        stage_id="s", name="FASE", subtitle="", track_path="", beatmap_path="unused",
        synth=None, beatmap_params={}, overrides={},
    )
    renderer = HBPygameRenderer()
    renderer.initialize(200, 200, "test")
    build_and_register_overlay_surfaces(renderer, (stage,))
    renderer.begin_frame()
    renderer.set_overlay("roguelite_map", roguelite_info={"screen": "map", "song_choices": (), "cursor": 0})
    renderer.end_frame()
    renderer.begin_frame()
    renderer.set_overlay(
        "roguelite_reward",
        roguelite_info={"screen": "reward", "perk_choices": (), "cursor": 0},
    )
    renderer.end_frame()
