"""Progressao de Campanha -- Ironman: gauntlet de fases curadas em sequencia, sem menu nem cura de vida entre elas."""
from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.adapters.texture_bank import build_and_register_overlay_surfaces
from hertzbeats.bootstrap.hertz_game_loop import (
    FLOW_GAME_OVER,
    FLOW_HUB,
    FLOW_PAUSED,
    FLOW_PLAYING,
    FLOW_RESULTS,
    HUB_CATEGORIES,
    HertzGameLoop,
)
from hertzbeats.stages import StageDef

from tests.test_match_flow import DT, _basic, _goto_hub, _press, flow_game  # noqa: F401


def _goto_ironman(loop, null_input) -> None:
    _goto_hub(loop, null_input)
    target = HUB_CATEGORIES.index("ironman")
    while loop.hub_cursor != target:
        _press(loop, null_input, "menu_down")
    _press(loop, null_input, "confirm")  # HUB -> inicia o gauntlet direto, sem Carrossel/Pre-Voo


def _run_until_results_or_game_over(loop, clock, frames: int = 400) -> None:
    """Sem atirar: a UNICA ameaca de cada fase e perdida (1 MISS = 1 de
    vida), ate a fase fechar (RESULTS) ou a vida zerar (GAME_OVER)."""
    for _ in range(frames):
        clock.advance(DT)
        loop.advance_frame(DT)
        if loop.flow in (FLOW_RESULTS, FLOW_GAME_OVER):
            break


# -- Fila do gauntlet: so fases curadas, exceto o tutorial ------------------


def test_confirming_ironman_in_the_hub_starts_the_first_eligible_stage_directly(flow_game, null_input):
    loop, _ = flow_game(
        [[_basic(3.0)], [_basic(3.0)], [_basic(3.0)], [_basic(3.0)]],
        selectable_list=[False, False, False, True],
        tutorial_list=[True, False, False, False],
    )
    _goto_ironman(loop, null_input)
    assert loop.flow == FLOW_PLAYING
    assert loop.ironman_active is True
    assert loop.loaded_stage == 1  # pula o tutorial (indice 0), comeca na 1a fase curada de verdade
    assert loop.ironman_progress() == (1, 2)  # 2 elegiveis: indices 1 e 2 (a 3 e selectable_mode)


def test_ironman_queue_size_matches_curated_non_tutorial_stages_exactly(flow_game, null_input):
    loop, _ = flow_game(
        [[_basic(3.0)], [_basic(3.0)], [_basic(3.0)], [_basic(3.0)], [_basic(3.0)]],
        selectable_list=[False, False, True, False, False],
        tutorial_list=[True, False, False, False, False],
    )
    expected_total = sum(
        1 for _i, stage in loop.campaign_entries() if not stage.tutorial_steps
    )
    _goto_ironman(loop, null_input)
    assert loop.ironman_progress()[1] == expected_total == 3


def test_a_curated_stage_with_no_tutorial_steps_is_included(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[False], tutorial_list=[False])
    _goto_ironman(loop, null_input)
    assert loop.ironman_active is True
    assert loop.ironman_progress() == (1, 1)


def test_ironman_with_no_eligible_stages_returns_immediately_to_the_hub(flow_game, null_input):
    """So o tutorial + uma musica do jogador em `self._stages` -- fila
    vazia, o gauntlet nao tem NADA pra jogar."""
    loop, _ = flow_game(
        [[_basic(3.0)], [_basic(3.0)]], selectable_list=[False, True], tutorial_list=[True, False],
    )
    _goto_ironman(loop, null_input)
    assert loop.flow == FLOW_HUB
    assert loop.ironman_active is False


# -- Vida acumulada entre fases (sem cura) -----------------------------------


def test_health_carries_over_between_ironman_stages_clamped_to_the_new_max(flow_game, null_input):
    loop, clock = flow_game(
        [[_basic(3.0)], [_basic(3.0)]],
        overrides_list=[{"max_health": 5}, {"max_health": 3}],
    )
    _goto_ironman(loop, null_input)
    assert loop.loaded_stage == 0
    assert loop.composed.game_state.health == 5

    _run_until_results_or_game_over(loop, clock)
    assert loop.flow == FLOW_RESULTS
    assert loop.composed.game_state.health == 4  # 5 - 1 MISS

    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_PLAYING
    assert loop.loaded_stage == 1
    assert loop.composed.game_state.health == 3  # min(4, teto novo de 3) -- nunca curado


def test_health_carries_over_uncapped_when_the_new_stage_allows_more(flow_game, null_input):
    loop, clock = flow_game(
        [[_basic(3.0)], [_basic(3.0)]],
        overrides_list=[{"max_health": 3}, {"max_health": 10}],
    )
    _goto_ironman(loop, null_input)
    _run_until_results_or_game_over(loop, clock)
    assert loop.flow == FLOW_RESULTS
    assert loop.composed.game_state.health == 2  # 3 - 1 MISS

    _press(loop, null_input, "confirm")
    assert loop.loaded_stage == 1
    assert loop.composed.game_state.health == 2  # carregado tal e qual, nunca restaurado ao teto novo (10)


def test_completing_the_last_ironman_stage_returns_to_the_hub(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0)]], overrides_list=[{"max_health": 5}])
    _goto_ironman(loop, null_input)
    _run_until_results_or_game_over(loop, clock)
    assert loop.flow == FLOW_RESULTS

    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_HUB  # fila esgotada -- gauntlet inteiro vencido
    assert loop.ironman_active is False


# -- Derrota reinicia o gauntlet inteiro -------------------------------------


def test_game_over_during_an_ironman_run_keeps_it_marked_active_until_retry_or_menu(flow_game, null_input):
    loop, clock = flow_game(
        [[_basic(3.0)], [_basic(3.0)]], overrides_list=[{"max_health": 1}, {}],
    )
    _goto_ironman(loop, null_input)
    _run_until_results_or_game_over(loop, clock)
    assert loop.flow == FLOW_GAME_OVER
    assert loop.ironman_active is True


def test_retry_after_an_ironman_game_over_restarts_the_whole_gauntlet_from_stage_one(flow_game, null_input):
    loop, clock = flow_game(
        [[_basic(3.0)], [_basic(3.0)]], overrides_list=[{"max_health": 1}, {"max_health": 5}],
    )
    _goto_ironman(loop, null_input)
    _run_until_results_or_game_over(loop, clock)
    assert loop.flow == FLOW_GAME_OVER

    _press(loop, null_input, "retry")
    assert loop.flow == FLOW_PLAYING
    assert loop.loaded_stage == 0  # de volta a PRIMEIRA fase, nunca a que perdeu sozinha
    assert loop.composed.game_state.health == 1  # vida cheia de novo -- reinicio total, nao um retry local
    assert loop.ironman_progress() == (1, 2)


def test_going_to_the_menu_after_an_ironman_game_over_cancels_the_run(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0)]], overrides_list=[{"max_health": 1}])
    _goto_ironman(loop, null_input)
    _run_until_results_or_game_over(loop, clock)
    assert loop.flow == FLOW_GAME_OVER

    _press(loop, null_input, "to_menu")
    assert loop.flow == FLOW_HUB
    assert loop.ironman_active is False


def test_pausing_and_leaving_to_the_menu_during_an_ironman_run_cancels_it(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)], [_basic(3.0)]])
    _goto_ironman(loop, null_input)
    _press(loop, null_input, "pause")
    assert loop.flow == FLOW_PAUSED

    _press(loop, null_input, "to_menu")
    assert loop.flow == FLOW_HUB
    assert loop.ironman_active is False


# -- Renderer real: HUB + aviso de progresso ---------------------------------


def test_hub_category_ironman_has_registered_label_textures():
    stage = StageDef(
        stage_id="s", name="FASE", subtitle="", track_path="", beatmap_path="unused",
        synth=None, beatmap_params={}, overrides={},
    )
    renderer = HBPygameRenderer()
    renderer.initialize(120, 120, "test")
    build_and_register_overlay_surfaces(renderer, (stage,))
    assert renderer._overlay_surfaces.get("hub_category_ironman") is not None
    assert renderer._overlay_surfaces.get("hub_category_ironman_sel") is not None


def test_every_eligible_ironman_stage_number_has_a_registered_notice_texture():
    """Mesma logica de `test_every_curated_stage_with_a_b_side_has_its_two_overlay_textures_registered`
    -- sem a textura, o aviso "IRONMAN: FASE N/M" desenharia em branco."""
    stages = tuple(
        StageDef(
            stage_id=f"s{i}", name=f"FASE {i}", subtitle="", track_path="", beatmap_path="unused",
            synth=None, beatmap_params={}, overrides={},
            selectable_mode=(i == 2),
            tutorial_steps=({"until_seconds": 1.0, "text": "x"},) if i == 3 else (),
        )
        for i in range(4)
    )  # 4 fases: 2 elegiveis (0, 1), uma selectable_mode (2), uma tutorial (3)
    renderer = HBPygameRenderer()
    renderer.initialize(120, 120, "test")
    build_and_register_overlay_surfaces(renderer, stages)
    assert renderer._overlay_surfaces.get("ironman_progress_1") is not None
    assert renderer._overlay_surfaces.get("ironman_progress_2") is not None
    assert renderer._overlay_surfaces.get("ironman_progress_3") is None  # so 2 fases elegiveis nesta lista
