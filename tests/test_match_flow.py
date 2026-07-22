"""HertzGameLoop: O Novo Fluxo de Menus (Experiencia Arcade), headless.

TITLE -> HUB -> CAROUSEL (campanha/free play) -> PREFLIGHT -> PLAYING
<-> PAUSED -> GAME_OVER/RESULTS -> HUB; HUB tambem alcanca VAULT
(so-leitura) e CALIBRATION (metronomo + tecla no tempo) como telas-fim.
"""
import math

import pytest

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from hertzbeats.bootstrap.hertz_game_loop import (
    DEFENDER_MODIFIER_ROWS,
    FLOW_CALIBRATION,
    FLOW_CAROUSEL,
    FLOW_GAME_OVER,
    FLOW_HUB,
    FLOW_PAUSED,
    FLOW_PLAYING,
    FLOW_PREFLIGHT,
    FLOW_RESULTS,
    FLOW_TITLE,
    FLOW_VAULT,
    GAME_MODE_ROW,
    HEAVY_MECHANIC_ROW,
    HEAVY_MECHANIC_VALUES_BY_GAME_MODE,
    HUB_CATEGORIES,
    LANES_MODIFIER_ROWS,
    MIN_SCORE_MULTIPLIER,
    MODIFIER_SCORE_BONUS,
    START_ROW,
    HertzGameLoop,
    compute_score_multiplier,
)
from hertzbeats.stages import StageDef

from tests.conftest import make_config, write_beatmap

DT = 0.016


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


@pytest.fixture
def flow_game(tmp_path, null_input):
    """Fabrica um `HertzGameLoop` headless com N fases (uma lista de
    ameacas por fase), progresso do jogador isolado em `tmp_path` (nunca
    o save real). `selectable_list[i]` marca a fase `i` como musica do
    jogador (Free Play) -- por padrao todas sao curadas (Campanha)."""

    def _make(stage_threat_lists, overrides_list=None, selectable_list=None, active_modifiers_list=None):
        stages = []
        beatmap_path = None
        for i, threats in enumerate(stage_threat_lists):
            beatmap_path = write_beatmap(tmp_path / f"stage{i}.beatmap.json", threats)
            overrides = overrides_list[i] if overrides_list else {}
            selectable = selectable_list[i] if selectable_list else False
            active_modifiers = active_modifiers_list[i] if active_modifiers_list else ()
            stages.append(
                StageDef(
                    stage_id=f"stage{i}",
                    name=f"FASE {i}",
                    subtitle="",
                    track_path=str(tmp_path / f"stage{i}.wav"),
                    beatmap_path=str(beatmap_path),
                    synth={"bpm": 120.0, "bars": 1},
                    beatmap_params={},
                    overrides=overrides,
                    selectable_mode=selectable,
                    active_modifiers=active_modifiers,
                )
            )
        audio_engine = NullAudioEngine()
        clock = audio_engine.get_clock()
        loop = HertzGameLoop(
            base_config=make_config(beatmap_path),
            stages=tuple(stages),
            renderer=NullRenderer(),
            input_provider=null_input,
            audio_engine=audio_engine,
            audio_clock=clock,
            player_progress_path=str(tmp_path / "player_progress.json"),
            player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
            user_settings_path=str(tmp_path / "user_settings.json"),
        )
        return loop, clock

    return _make


def _press(loop, null_input, action: str) -> None:
    """Um frame com a borda de pressao de `action`, seguido da soltura."""
    null_input.set_action_held(action, True)
    null_input.poll()
    loop.advance_frame(DT)
    null_input.set_action_held(action, False)
    null_input.poll()


def _goto_hub(loop, null_input) -> None:
    _press(loop, null_input, "confirm")  # TITLE -> HUB


def _goto_carousel(loop, null_input, category: str) -> None:
    _goto_hub(loop, null_input)
    target = HUB_CATEGORIES.index(category)
    while loop.hub_cursor != target:
        _press(loop, null_input, "menu_down")
    _press(loop, null_input, "confirm")  # HUB -> CAROUSEL


def _goto_preflight(loop, null_input, category: str, position: int = 0) -> None:
    _goto_carousel(loop, null_input, category)
    while loop.carousel_index() != position:
        _press(loop, null_input, "menu_down")
    _press(loop, null_input, "confirm")  # CAROUSEL -> PREFLIGHT


def _goto_vault(loop, null_input) -> None:
    _goto_hub(loop, null_input)
    target = HUB_CATEGORIES.index("vault")
    while loop.hub_cursor != target:
        _press(loop, null_input, "menu_down")
    _press(loop, null_input, "confirm")  # HUB -> VAULT


def _goto_calibration(loop, null_input) -> None:
    _goto_hub(loop, null_input)
    target = HUB_CATEGORIES.index("calibration")
    while loop.hub_cursor != target:
        _press(loop, null_input, "menu_down")
    _press(loop, null_input, "confirm")  # HUB -> CALIBRATION


def _move_cursor_to(loop, null_input, row_name: str, stage_index: int = 0) -> None:
    target = loop.modifier_rows(stage_index).index(row_name)
    while loop.menu_cursor_index(stage_index) != target:
        _press(loop, null_input, "menu_down")


def _play_to_results(loop, clock, null_input, timestamp: float = 3.0, lane: int = 0) -> None:
    """Autoplay: mira na `lane` (MESMA formula do spawner radial --
    `angulo = TAU * lane / lane_count`, `lane_count=8` em `make_config`)
    e atira EXATAMENTE no instante da unica ameaca da fase, depois deixa
    os frames rodarem ate a carencia de resultados esgotar."""
    angle = 2.0 * math.pi * lane / 8.0
    null_input.set_axis("aim_x", math.cos(angle))
    null_input.set_axis("aim_y", math.sin(angle))
    clock.set_now_seconds(timestamp)
    _press(loop, null_input, "fire")
    for _ in range(80):
        clock.advance(DT)
        loop.advance_frame(DT)
        if loop.flow == FLOW_RESULTS:
            break


# -- Tela de Titulo ----------------------------------------------------


def test_starts_at_title(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]])
    assert loop.flow == FLOW_TITLE


def test_confirm_at_title_enters_hub(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]])
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_HUB


def test_esc_at_title_stops_the_loop(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]])
    loop._running = True
    _press(loop, null_input, "pause")
    assert loop._running is False


# -- HUB Principal -------------------------------------------------------


def test_hub_navigation_wraps_through_all_categories(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]])
    _goto_hub(loop, null_input)
    assert loop.hub_cursor == 0
    for i in range(1, len(HUB_CATEGORIES)):
        _press(loop, null_input, "menu_down")
        assert loop.hub_cursor == i
    _press(loop, null_input, "menu_down")
    assert loop.hub_cursor == 0  # enrola
    _press(loop, null_input, "menu_up")
    assert loop.hub_cursor == len(HUB_CATEGORIES) - 1


def test_esc_in_hub_returns_to_title(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]])
    _goto_hub(loop, null_input)
    _press(loop, null_input, "pause")
    assert loop.flow == FLOW_TITLE


# -- Carrossel + progressao da Campanha ----------------------------------


def test_campaign_category_lists_only_curated_stages_in_order(flow_game, null_input):
    loop, _ = flow_game(
        [[_basic(3.0)], [_basic(3.0)], [_basic(3.0)]], selectable_list=[False, True, False],
    )
    _goto_carousel(loop, null_input, "campaign")
    assert [i for i, _ in loop.carousel_entries()] == [0, 2]


def test_free_play_category_lists_only_selectable_stages(flow_game, null_input):
    loop, _ = flow_game(
        [[_basic(3.0)], [_basic(3.0)], [_basic(3.0)]], selectable_list=[False, True, False],
    )
    _goto_carousel(loop, null_input, "free_play")
    assert [i for i, _ in loop.carousel_entries()] == [1]


def test_carousel_navigation_wraps(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]] * 3, selectable_list=[False, False, False])
    _goto_carousel(loop, null_input, "campaign")
    assert loop.carousel_index() == 0
    _press(loop, null_input, "menu_down")
    assert loop.carousel_index() == 1
    _press(loop, null_input, "menu_down")
    assert loop.carousel_index() == 2
    _press(loop, null_input, "menu_down")
    assert loop.carousel_index() == 0  # enrola
    _press(loop, null_input, "menu_up")
    assert loop.carousel_index() == 2


def test_esc_in_carousel_returns_to_hub(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]])
    _goto_carousel(loop, null_input, "campaign")
    _press(loop, null_input, "pause")
    assert loop.flow == FLOW_HUB


def test_free_play_carousel_with_no_songs_shows_empty_state_and_esc_still_works(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[False])
    _goto_carousel(loop, null_input, "free_play")
    assert loop.flow == FLOW_CAROUSEL
    assert loop.carousel_entries() == []
    _press(loop, null_input, "pause")
    assert loop.flow == FLOW_HUB


def test_campaign_first_stage_is_never_locked(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)], [_basic(3.0)]], selectable_list=[False, False])
    assert loop.is_campaign_entry_locked(0) is False


def test_a_later_campaign_stage_is_locked_until_the_previous_one_clears(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)], [_basic(3.0)]], selectable_list=[False, False])
    assert loop.is_campaign_entry_locked(1) is True


def test_confirm_on_a_locked_campaign_stage_shows_a_notice_and_stays_in_carousel(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)], [_basic(3.0)]], selectable_list=[False, False])
    _goto_carousel(loop, null_input, "campaign")
    _press(loop, null_input, "menu_down")  # posicao 1, ainda trancada
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_CAROUSEL
    assert loop._notice_key == "stage_locked"


def test_confirm_on_an_unlocked_campaign_stage_enters_preflight(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[False])
    _goto_carousel(loop, null_input, "campaign")
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_PREFLIGHT


def test_clearing_a_campaign_stage_unlocks_the_next_one(flow_game, null_input):
    loop, clock = flow_game(
        [[_basic(3.0, lane=0)], [_basic(3.0, lane=1)]], selectable_list=[False, False],
    )
    assert loop.is_campaign_entry_locked(1) is True

    _goto_preflight(loop, null_input, "campaign", 0)
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_PLAYING

    _play_to_results(loop, clock, null_input)
    assert loop.flow == FLOW_RESULTS
    assert loop.is_campaign_entry_locked(1) is False


# -- Pre-Voo: fase curada (so-leitura + START) ---------------------------


def test_curated_stage_preflight_confirm_starts_the_stage(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[False])
    _goto_preflight(loop, null_input, "campaign", 0)
    assert loop.flow == FLOW_PREFLIGHT
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_PLAYING
    assert loop.loaded_stage == 0


def test_curated_stage_preflight_esc_returns_to_carousel(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[False])
    _goto_preflight(loop, null_input, "campaign", 0)
    _press(loop, null_input, "pause")
    assert loop.flow == FLOW_CAROUSEL


def test_a_curated_stage_is_never_affected_by_the_modifier_panel(tmp_path, null_input):
    """Fases curadas (`selectable_mode=False`) ignoram o painel de
    checkboxes por completo -- so usam os `overrides`/`active_modifiers`
    do proprio `stages.json`."""
    beatmap_path = write_beatmap(tmp_path / "curated.beatmap.json", [
        {"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.5},
    ])
    stage = StageDef(
        stage_id="curated", name="FASE CURADA", subtitle="", track_path=str(tmp_path / "c.wav"),
        beatmap_path=str(beatmap_path), synth={"bpm": 120.0, "bars": 1}, beatmap_params={},
        overrides={"game_mode": "lanes"}, selectable_mode=False,
    )
    audio_engine = NullAudioEngine()
    loop = HertzGameLoop(
        base_config=make_config(beatmap_path), stages=(stage,), renderer=NullRenderer(),
        input_provider=null_input, audio_engine=audio_engine, audio_clock=audio_engine.get_clock(),
        player_progress_path=str(tmp_path / "player_progress.json"),
        player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
        user_settings_path=str(tmp_path / "user_settings.json"),
    )
    _goto_preflight(loop, null_input, "campaign", 0)
    _press(loop, null_input, "confirm")
    assert loop._stage_config.game_mode == "lanes"
    assert loop._stage_config.active_modifiers == ()
    # e realmente o Arcade 4K: o spawner de notas de coluna, nao o radial
    from hertzbeats.systems.lane_note_spawner_system import LaneNoteSpawnerSystem
    assert any(isinstance(s, LaneNoteSpawnerSystem) for s in loop.composed.world._systems)


# -- Pre-Voo: musica do jogador (painel de opcoes completo) --------------


def test_selectable_song_starts_with_defender_mode_no_modifiers_and_practice_off(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[True])
    assert loop.chosen_game_mode(0) == "defender"
    assert loop.chosen_heavy_mechanic(0) == "none"
    assert loop.chosen_modifiers(0) == frozenset()
    assert loop.menu_cursor_index(0) == 0
    assert loop.practice_mode_on(0) is False


def test_confirm_on_a_selectable_song_in_carousel_enters_preflight_without_starting(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[True])
    _goto_carousel(loop, null_input, "free_play")
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_PREFLIGHT
    assert loop.menu_cursor_index(0) == 0  # GAME_MODE_ROW


def test_left_right_do_nothing_in_the_carousel(flow_game, null_input):
    """A/D so alteram algo DENTRO do Pre-Voo -- no Carrossel (so
    navegando a lista de musicas), nao fazem nada."""
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[True])
    _goto_carousel(loop, null_input, "free_play")
    _press(loop, null_input, "menu_right")
    _press(loop, null_input, "menu_left")
    assert loop.chosen_game_mode(0) == "defender"
    assert loop.flow == FLOW_CAROUSEL


def test_cursor_visits_every_row_in_order_and_wraps(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[True])
    _goto_preflight(loop, null_input, "free_play", 0)
    rows = (GAME_MODE_ROW, HEAVY_MECHANIC_ROW) + DEFENDER_MODIFIER_ROWS + (START_ROW,)
    assert loop.modifier_rows(0) == rows

    assert loop.menu_cursor_index(0) == 0
    for i, _ in enumerate(rows[1:], start=1):
        _press(loop, null_input, "menu_down")
        assert loop.menu_cursor_index(0) == i
    _press(loop, null_input, "menu_down")  # um passo alem do fim -- enrola de volta
    assert loop.menu_cursor_index(0) == 0
    _press(loop, null_input, "menu_up")  # e o inverso tambem enrola
    assert loop.menu_cursor_index(0) == len(rows) - 1


def test_toggle_modifier_checks_and_unchecks_the_focused_row(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[True])
    _goto_preflight(loop, null_input, "free_play", 0)

    _move_cursor_to(loop, null_input, "telegraph_rings")
    _press(loop, null_input, "confirm")
    assert "telegraph_rings" in loop.chosen_modifiers(0)

    _press(loop, null_input, "confirm")
    assert "telegraph_rings" not in loop.chosen_modifiers(0)


def test_confirm_does_nothing_on_multiple_choice_rows(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[True])
    _goto_preflight(loop, null_input, "free_play", 0)

    assert loop.menu_cursor_index(0) == 0  # GAME_MODE_ROW
    _press(loop, null_input, "confirm")
    assert loop.chosen_game_mode(0) == "defender"  # intocado
    assert loop.flow == FLOW_PREFLIGHT  # nao iniciou a fase


def test_left_right_cycle_the_game_mode_row(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[True])
    _goto_preflight(loop, null_input, "free_play", 0)

    assert loop.menu_cursor_index(0) == 0  # GAME_MODE_ROW
    _press(loop, null_input, "menu_right")
    assert loop.chosen_game_mode(0) == "lanes"
    assert loop.modifier_rows(0) == (GAME_MODE_ROW, HEAVY_MECHANIC_ROW) + LANES_MODIFIER_ROWS + (START_ROW,)

    _press(loop, null_input, "menu_left")
    assert loop.chosen_game_mode(0) == "defender"
    assert loop.modifier_rows(0) == (GAME_MODE_ROW, HEAVY_MECHANIC_ROW) + DEFENDER_MODIFIER_ROWS + (START_ROW,)


def test_left_right_cycle_the_heavy_mechanic_row_through_none_polarity_holds(flow_game, null_input):
    loop, _ = flow_game(
        [[{"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_heavy", "lane": 0, "strength": 0.9}]],
        selectable_list=[True],
    )
    _goto_preflight(loop, null_input, "free_play", 0)
    _move_cursor_to(loop, null_input, "heavy_mechanic")

    assert loop.chosen_heavy_mechanic(0) == "none"
    _press(loop, null_input, "menu_right")
    assert loop.chosen_heavy_mechanic(0) == "polarity"
    _press(loop, null_input, "menu_right")
    assert loop.chosen_heavy_mechanic(0) == "holds"
    _press(loop, null_input, "menu_right")
    assert loop.chosen_heavy_mechanic(0) == "none"  # enrolou

    _press(loop, null_input, "menu_left")
    assert loop.chosen_heavy_mechanic(0) == "holds"  # o inverso tambem enrola


def test_switching_to_lanes_resets_an_invalid_heavy_mechanic(flow_game, null_input):
    loop, _ = flow_game(
        [[{"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_heavy", "lane": 0, "strength": 0.9}]],
        selectable_list=[True],
    )
    _goto_preflight(loop, null_input, "free_play", 0)
    _move_cursor_to(loop, null_input, "heavy_mechanic")
    _press(loop, null_input, "menu_right")
    assert loop.chosen_heavy_mechanic(0) == "polarity"

    _move_cursor_to(loop, null_input, "game_mode")
    _press(loop, null_input, "menu_right")
    assert loop.chosen_game_mode(0) == "lanes"
    assert loop.chosen_heavy_mechanic(0) == "none"


def test_start_row_only_starts_from_the_exact_row(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[True])
    _goto_preflight(loop, null_input, "free_play", 0)

    _move_cursor_to(loop, null_input, "telegraph_rings")
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_PREFLIGHT  # so ligou o modifier, nao iniciou

    _move_cursor_to(loop, null_input, "start")
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_PLAYING
    assert loop._stage_config.game_mode == "defender"
    assert loop._stage_config.active_modifiers == ("telegraph_rings",)


def test_esc_in_preflight_options_returns_to_carousel_without_starting_or_quitting(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[True])
    _goto_preflight(loop, null_input, "free_play", 0)
    _press(loop, null_input, "pause")
    assert loop.flow == FLOW_CAROUSEL


def test_composing_confirms_with_exactly_the_checked_modifiers_and_heavy_mechanic(flow_game, null_input):
    loop, _ = flow_game(
        [[{"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_heavy", "lane": 0, "strength": 0.9}]],
        selectable_list=[True],
    )
    _goto_preflight(loop, null_input, "free_play", 0)

    for row_name in ("telegraph_rings", "orbital_shields"):
        _move_cursor_to(loop, null_input, row_name)
        _press(loop, null_input, "confirm")
    _move_cursor_to(loop, null_input, "heavy_mechanic")
    _press(loop, null_input, "menu_right")  # -> "polarity"

    _move_cursor_to(loop, null_input, "start")
    _press(loop, null_input, "confirm")
    assert loop._stage_config.game_mode == "defender"
    assert set(loop._stage_config.active_modifiers) == {"telegraph_rings", "orbital_shields", "polarity"}


def test_toggle_practice_mode_in_preflight(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[True])
    _goto_preflight(loop, null_input, "free_play", 0)
    assert loop.practice_mode_on(0) is False
    _press(loop, null_input, "toggle_practice")
    assert loop.practice_mode_on(0) is True
    _press(loop, null_input, "toggle_practice")
    assert loop.practice_mode_on(0) is False


def test_every_menu_row_has_a_registered_label_texture():
    """Toda linha possivel do menu de opcoes (`GAME_MODE_ROW`,
    `HEAVY_MECHANIC_ROW` com seus 3 valores, cada modifier booleano de
    `DEFENDER_MODIFIER_ROWS`/`LANES_MODIFIER_ROWS`, e `START_ROW`)
    PRECISA de uma textura `modifier_row_*` registrada em
    `texture_bank.py` -- senao `_blit_centered`/`_draw_modifier_row`
    desenham a linha em BRANCO silenciosamente (nenhum teste de
    composicao pega isso sozinho, usam `NullRenderer`, que nunca toca
    essas texturas)."""
    from hertzbeats.adapters.texture_bank import (
        _GAME_MODE_ROW_LABELS,
        _HEAVY_MECHANIC_ROW_LABELS,
        _MODIFIER_ROW_LABELS,
    )
    from hertzbeats.bootstrap.hertz_game_loop import LANES_MODIFIER_ROWS

    assert "defender" in _GAME_MODE_ROW_LABELS
    assert "lanes" in _GAME_MODE_ROW_LABELS
    for values in HEAVY_MECHANIC_VALUES_BY_GAME_MODE.values():
        for value in values:
            assert value in _HEAVY_MECHANIC_ROW_LABELS, f"{value!r} sem rotulo em _HEAVY_MECHANIC_ROW_LABELS"
    for row_name in set(DEFENDER_MODIFIER_ROWS) | set(LANES_MODIFIER_ROWS):
        assert row_name in _MODIFIER_ROW_LABELS, f"{row_name!r} sem rotulo em _MODIFIER_ROW_LABELS"


# -- Meta-Jogo -- Multiplicador de Pontuacao ------------------------------


def test_score_multiplier_with_no_modifiers_and_no_practice_is_1():
    assert compute_score_multiplier(frozenset(), False) == 1.0


def test_score_multiplier_sums_each_active_modifier_bonus():
    mods = frozenset({"orbital_eclipses", "twin_threats"})  # +0.20 cada
    assert compute_score_multiplier(mods, False) == pytest.approx(1.40)


def test_score_multiplier_telegraph_rings_gives_no_bonus():
    assert compute_score_multiplier(frozenset({"telegraph_rings"}), False) == pytest.approx(1.0)


def test_score_multiplier_practice_mode_applies_the_flat_penalty():
    assert compute_score_multiplier(frozenset(), True) == pytest.approx(0.5)


def test_score_multiplier_practice_and_bonuses_combine():
    assert compute_score_multiplier(frozenset({"orbital_eclipses"}), True) == pytest.approx(0.7)


def test_score_multiplier_worst_realistic_case_stays_above_the_floor():
    # pior combinacao real do catalogo atual: "heal" (unico bonus
    # negativo) + Modo Treino -- ainda bem acima de MIN_SCORE_MULTIPLIER
    assert compute_score_multiplier(frozenset({"heal"}), True) == pytest.approx(0.45)
    assert compute_score_multiplier(frozenset({"heal"}), True) > MIN_SCORE_MULTIPLIER


def test_score_multiplier_roleta_russa_is_the_biggest_bonus_in_the_catalog():
    assert compute_score_multiplier(frozenset({"roleta_russa"}), False) == pytest.approx(1.30)
    all_others = [b for m, b in MODIFIER_SCORE_BONUS.items() if m != "roleta_russa"]
    assert MODIFIER_SCORE_BONUS["roleta_russa"] > max(all_others)


# -- Meta-Jogo -- Roleta Russa (1 de vida, qualquer erro e Game Over) ----


def test_roleta_russa_forces_max_health_to_1_overriding_a_higher_config_value(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[True], overrides_list=[{"max_health": 5}])
    _goto_preflight(loop, null_input, "free_play", 0)
    _move_cursor_to(loop, null_input, "roleta_russa")
    _press(loop, null_input, "confirm")  # liga o modifier
    assert "roleta_russa" in loop.chosen_modifiers(0)

    _move_cursor_to(loop, null_input, "start")
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_PLAYING
    assert loop._stage_config.max_health == 1
    assert loop.composed.game_state.health == 1


def test_roleta_russa_off_keeps_the_configured_max_health(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[True], overrides_list=[{"max_health": 5}])
    _goto_preflight(loop, null_input, "free_play", 0)
    _move_cursor_to(loop, null_input, "start")
    _press(loop, null_input, "confirm")
    assert loop._stage_config.max_health == 5


def test_roleta_russa_on_a_curated_stage_also_forces_1_hp(flow_game, null_input):
    loop, _ = flow_game(
        [[_basic(3.0)]], selectable_list=[False], overrides_list=[{"max_health": 3}],
        active_modifiers_list=[("roleta_russa",)],
    )
    _goto_preflight(loop, null_input, "campaign", 0)
    _press(loop, null_input, "confirm")
    assert loop._stage_config.max_health == 1


def test_roleta_russa_any_miss_is_instant_game_over(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0)]], selectable_list=[True])
    _goto_preflight(loop, null_input, "free_play", 0)
    _move_cursor_to(loop, null_input, "roleta_russa")
    _press(loop, null_input, "confirm")
    _move_cursor_to(loop, null_input, "start")
    _press(loop, null_input, "confirm")
    assert loop.composed.game_state.health == 1

    # sem atirar: a ameaca viaja, colide vencida com o nucleo -- 1 MISS basta
    for _ in range(240):
        clock.advance(DT)
        loop.advance_frame(DT)
        if loop.flow == FLOW_GAME_OVER:
            break
    assert loop.flow == FLOW_GAME_OVER
    assert loop.composed.game_state.miss_count == 1
    assert loop.composed.game_state.health == 0


def test_score_multiplier_preview_in_preflight_matches_what_gets_composed(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[True])
    _goto_preflight(loop, null_input, "free_play", 0)
    _move_cursor_to(loop, null_input, "orbital_eclipses")
    _press(loop, null_input, "confirm")  # liga o modifier (+0.20)

    preview = loop._current_score_multiplier(0)
    assert preview == pytest.approx(compute_score_multiplier(frozenset({"orbital_eclipses"}), False))

    _move_cursor_to(loop, null_input, "start")
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_PLAYING
    assert loop._stage_config.score_multiplier == pytest.approx(preview)


def test_score_multiplier_preview_for_a_curated_stage_uses_its_fixed_overrides(flow_game, null_input):
    loop, _ = flow_game(
        [[_basic(3.0)]], selectable_list=[False],
        active_modifiers_list=[("orbital_eclipses",)],
    )
    expected = compute_score_multiplier(frozenset({"orbital_eclipses"}), False)
    assert loop._current_score_multiplier(0) == pytest.approx(expected)

    _goto_preflight(loop, null_input, "campaign", 0)
    _press(loop, null_input, "confirm")
    assert loop._stage_config.score_multiplier == pytest.approx(expected)


# -- Jogando / Pausa / Derrota / Resultados -------------------------------


def test_pause_freezes_simulation_and_resumes(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0)]])
    _goto_preflight(loop, null_input, "campaign", 0)
    _press(loop, null_input, "confirm")

    clock.set_now_seconds(1.0)
    loop.advance_frame(DT)
    threat_pool = loop.composed.memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 1  # ameaca ja spawnada

    _press(loop, null_input, "pause")
    assert loop.flow == FLOW_PAUSED
    spawner_cursor = loop.composed.spawner_system.next_pending_index
    for _ in range(20):
        loop.advance_frame(DT)  # frames pausados: nada avanca
    assert loop.composed.spawner_system.next_pending_index == spawner_cursor
    assert threat_pool.count == 1

    _press(loop, null_input, "pause")
    assert loop.flow == FLOW_PLAYING


def test_pause_to_hub_returns_to_hub(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]])
    _goto_preflight(loop, null_input, "campaign", 0)
    _press(loop, null_input, "confirm")
    _press(loop, null_input, "pause")
    _press(loop, null_input, "to_menu")
    assert loop.flow == FLOW_HUB


def test_health_zero_triggers_game_over_and_retry_restarts_fresh(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0)]], overrides_list=[{"max_health": 1}])
    _goto_preflight(loop, null_input, "campaign", 0)
    _press(loop, null_input, "confirm")
    assert loop.composed.game_state.health == 1

    # sem atirar: a ameaca viaja, colide vencida com o nucleo e zera a vida
    for _ in range(240):
        clock.advance(DT)
        loop.advance_frame(DT)
        if loop.flow == FLOW_GAME_OVER:
            break
    assert loop.flow == FLOW_GAME_OVER
    assert loop.composed.game_state.health == 0
    assert clock.is_playing() is False  # musica parou na derrota

    _press(loop, null_input, "retry")
    assert loop.flow == FLOW_PLAYING
    state = loop.composed.game_state
    assert state.health == 1  # GameState zerado (max_health da fase)
    assert state.score == 0 and state.miss_count == 0
    assert loop.composed.spawner_system.next_pending_index == 0
    assert loop.composed.memory_manager.get_pool("rhythm_threat").count == 0
    assert clock.now_seconds() == 0.0  # musica reiniciada do zero


def test_clearing_stage_reaches_results_then_next_stage(flow_game, null_input):
    loop, clock = flow_game(
        [[_basic(3.0, lane=0)], [_basic(3.0, lane=1)]], selectable_list=[False, False],
    )
    _goto_preflight(loop, null_input, "campaign", 0)
    _press(loop, null_input, "confirm")

    _play_to_results(loop, clock, null_input)
    assert loop.composed.game_state.perfect_count == 1
    assert loop.flow == FLOW_RESULTS

    _press(loop, null_input, "confirm")  # proxima fase
    assert loop.flow == FLOW_PLAYING
    assert loop.loaded_stage == 1
    assert clock.now_seconds() == 0.0


def test_music_end_with_leftover_threats_still_reaches_results(flow_game, null_input):
    """Guard anti-softlock: se a musica acaba com ameacas ainda vivas
    (o relogio congela e elas nunca receberiam veredito), a fase encerra
    mesmo assim pela carencia em tempo real."""
    loop, clock = flow_game([[_basic(3.0)]])
    _goto_preflight(loop, null_input, "campaign", 0)
    _press(loop, null_input, "confirm")

    clock.set_now_seconds(1.5)  # spawna a ameaca (spawner termina o beatmap)
    loop.advance_frame(DT)
    threat_pool = loop.composed.memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 1
    assert loop.composed.spawner_system.is_finished

    clock.set_playing(False)  # a faixa terminou; get_pos congelaria em 0
    for _ in range(80):  # > 1s de carencia em dt de frame
        loop.advance_frame(DT)
        if loop.flow == FLOW_RESULTS:
            break
    assert loop.flow == FLOW_RESULTS


def test_live_latency_calibration_with_plus_minus(flow_game, null_input):
    """Teclas +/- ajustam a latencia em passos de 10 ms durante o jogo,
    com clamp em [0, 0.30] -- a resposta pratica ao 'parece
    desincronizado': o jogador calibra sentindo a musica."""
    loop, clock = flow_game([[_basic(3.0)]])
    _goto_preflight(loop, null_input, "campaign", 0)
    _press(loop, null_input, "confirm")
    clock.calibrate_latency(0.06)

    _press(loop, null_input, "latency_up")
    assert abs(clock.get_output_latency_seconds() - 0.07) < 1e-9
    assert loop._notice_key == "latency_7"
    assert loop._notice_timer > 0.0

    for _ in range(9):
        _press(loop, null_input, "latency_down")
    assert clock.get_output_latency_seconds() == 0.0  # clamp no zero

    # tambem funciona pausado; e o aviso expira sozinho
    _press(loop, null_input, "pause")
    _press(loop, null_input, "latency_up")
    assert abs(clock.get_output_latency_seconds() - 0.01) < 1e-9
    for _ in range(120):
        loop.advance_frame(DT)
    assert loop._notice_timer <= 0.0


def test_game_over_to_hub(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0)]], overrides_list=[{"max_health": 1}])
    _goto_preflight(loop, null_input, "campaign", 0)
    _press(loop, null_input, "confirm")
    for _ in range(240):
        clock.advance(DT)
        loop.advance_frame(DT)
        if loop.flow == FLOW_GAME_OVER:
            break
    assert loop.flow == FLOW_GAME_OVER
    _press(loop, null_input, "to_menu")
    assert loop.flow == FLOW_HUB


def test_saved_latency_roundtrip(tmp_path):
    from hertzbeats.user_settings import load_user_latency, save_user_latency

    path = str(tmp_path / "user_settings.json")
    assert load_user_latency(path) is None  # sem arquivo -> default da config
    save_user_latency(0.13, path)
    assert load_user_latency(path) == 0.13
    save_user_latency(9.9, path)  # valores absurdos sao clampados na leitura
    assert load_user_latency(path) == 0.30


def test_saved_palette_id_roundtrip(tmp_path):
    from hertzbeats.user_settings import load_user_palette_id, save_user_palette_id

    path = str(tmp_path / "user_settings.json")
    assert load_user_palette_id(path) is None  # sem escolha ainda -> DEFAULT_PALETTE_ID
    save_user_palette_id("neon", path)
    assert load_user_palette_id(path) == "neon"


def test_saving_latency_and_palette_never_erase_each_other(tmp_path):
    """Os 2 campos vivem no MESMO arquivo, mas sao INDEPENDENTES -- salvar
    um nao pode apagar o outro (mesmo arquivo tocado ao sair do jogo)."""
    from hertzbeats.user_settings import (
        load_user_latency, load_user_palette_id, save_user_latency, save_user_palette_id,
    )

    path = str(tmp_path / "user_settings.json")
    save_user_latency(0.05, path)
    save_user_palette_id("gold_silver", path)
    assert load_user_latency(path) == 0.05
    assert load_user_palette_id(path) == "gold_silver"

    save_user_latency(0.08, path)  # simula o save de saida do jogo
    assert load_user_palette_id(path) == "gold_silver"  # ainda la


# -- Arquivos (Vault) ------------------------------------------------------


def test_entering_vault_from_hub_and_back(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]])
    _goto_vault(loop, null_input)
    assert loop.flow == FLOW_VAULT
    _press(loop, null_input, "pause")
    assert loop.flow == FLOW_HUB


def test_vault_starts_with_nothing_cleared(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)], [_basic(3.0)]], selectable_list=[False, False])
    stats = loop.vault_stats()
    assert stats == {
        "stages_cleared": 0, "total_stages": 2, "total_medals": 0,
        "rank_counts": {"SS": 0, "S": 0, "A": 0, "B": 0, "C": 0, "D": 0},
        "lifetime_perfect_count": 0, "lifetime_shots_fired": 0, "lifetime_playtime_seconds": 0.0,
        "palette_id": "classic", "unlocked_palettes": ("classic", "colorblind", "monochrome"),
    }


def test_vault_reflects_a_stage_cleared_just_now(flow_game, null_input):
    loop, clock = flow_game(
        [[_basic(3.0, lane=0)], [_basic(3.0, lane=1)]], selectable_list=[False, False],
    )
    _goto_preflight(loop, null_input, "campaign", 0)
    _press(loop, null_input, "confirm")
    _play_to_results(loop, clock, null_input)
    assert loop.flow == FLOW_RESULTS

    stats = loop.vault_stats()
    assert stats["stages_cleared"] == 1
    assert stats["total_stages"] == 2
    assert stats["rank_counts"][loop._results_rank] == 1


# -- Meta-Jogo -- Estatisticas Globais (vitalicias) -----------------------


def test_clearing_a_stage_accumulates_lifetime_stats(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0, lane=0)]], selectable_list=[False])
    _goto_preflight(loop, null_input, "campaign", 0)
    _press(loop, null_input, "confirm")
    _play_to_results(loop, clock, null_input)
    assert loop.flow == FLOW_RESULTS

    stats = loop.vault_stats()
    assert stats["lifetime_perfect_count"] == 1
    assert stats["lifetime_shots_fired"] == 1
    assert stats["lifetime_playtime_seconds"] > 0.0


def test_a_lost_stage_still_accumulates_lifetime_stats(flow_game, null_input):
    """Estatisticas vitalicias nao dependem de vencer a fase -- um MISS
    continua contando como tiro disparado mesmo num Game Over."""
    loop, clock = flow_game([[_basic(3.0)]], overrides_list=[{"max_health": 1}])
    _goto_preflight(loop, null_input, "campaign", 0)
    _press(loop, null_input, "confirm")
    for _ in range(240):
        clock.advance(DT)
        loop.advance_frame(DT)
        if loop.flow == FLOW_GAME_OVER:
            break
    assert loop.flow == FLOW_GAME_OVER

    stats = loop.vault_stats()
    assert stats["lifetime_shots_fired"] == 1  # o MISS que zerou a vida
    assert stats["lifetime_perfect_count"] == 0
    assert stats["lifetime_playtime_seconds"] > 0.0


def test_lifetime_stats_accumulate_across_multiple_matches(flow_game, null_input):
    loop, clock = flow_game(
        [[_basic(3.0, lane=0)], [_basic(3.0, lane=1)]], selectable_list=[False, False],
    )
    _goto_preflight(loop, null_input, "campaign", 0)
    _press(loop, null_input, "confirm")
    _play_to_results(loop, clock, null_input)
    _press(loop, null_input, "confirm")  # proxima fase
    assert loop.flow == FLOW_PLAYING

    _play_to_results(loop, clock, null_input, lane=1)
    assert loop.flow == FLOW_RESULTS

    stats = loop.vault_stats()
    assert stats["lifetime_perfect_count"] == 2
    assert stats["lifetime_shots_fired"] == 2


# -- Meta-Jogo -- Paletas Cosmeticas --------------------------------------


def test_vault_cycling_never_reaches_a_reward_palette_with_no_progress(flow_game, null_input):
    """Sem NENHUM progresso salvo, "classic" + as 2 paletas de
    Acessibilidade (sempre desbloqueadas) sao as UNICAS no ciclo --
    "gold_silver"/"neon" (recompensas por Rank) nunca aparecem."""
    loop, _ = flow_game([[_basic(3.0)]])
    _goto_vault(loop, null_input)
    for _ in range(6):  # varias voltas completas
        _press(loop, null_input, "menu_right")
        assert loop.palette_id in ("classic", "colorblind", "monochrome")


def test_vault_cycling_wraps_through_unlocked_palettes(flow_game, null_input):
    from hertzbeats.palettes import unlocked_palette_ids

    loop, _ = flow_game([[_basic(3.0)]])
    loop._player_progress = {"external": {"modifiers": frozenset(), "best_rank": "SS"}}
    _goto_vault(loop, null_input)

    unlocked = unlocked_palette_ids(loop._player_progress)
    assert loop.palette_id == unlocked[0] == "classic"
    for expected_id in unlocked[1:]:
        _press(loop, null_input, "menu_right")
        assert loop.palette_id == expected_id
    _press(loop, null_input, "menu_right")
    assert loop.palette_id == "classic"  # enrola

    _press(loop, null_input, "menu_left")
    assert loop.palette_id == unlocked[-1]  # o inverso tambem enrola


def test_vault_only_cycles_through_palettes_actually_unlocked(flow_game, null_input):
    """Com apenas Rank S alcancado, "neon" (exige SS) nunca aparece no
    ciclo -- so as sempre-desbloqueadas + "gold_silver"."""
    from hertzbeats.palettes import unlocked_palette_ids

    loop, _ = flow_game([[_basic(3.0)]])
    loop._player_progress = {"external": {"modifiers": frozenset(), "best_rank": "S"}}
    _goto_vault(loop, null_input)

    unlocked = unlocked_palette_ids(loop._player_progress)
    assert "neon" not in unlocked
    for expected_id in unlocked[1:]:
        _press(loop, null_input, "menu_right")
        assert loop.palette_id == expected_id
    _press(loop, null_input, "menu_right")
    assert loop.palette_id == "classic"  # enrola sem passar por "neon"


def test_cycling_palette_in_vault_applies_to_the_next_stage_composed(flow_game, null_input):
    """`_goto_vault`/`_goto_preflight` (que comecam sempre de FLOW_TITLE)
    nao dao pra encadear direto aqui -- depois do Vault o fluxo ja esta
    no HUB (nao TITLE), entao a navegacao pro Carrossel/Pre-Voo e feita
    manualmente a partir do estado real em que o loop ja esta."""
    from hertzbeats.palettes import PALETTE_CATALOG
    from hertzbeats.user_settings import load_user_palette_id

    loop, _ = flow_game([[_basic(3.0)]])
    loop._player_progress = {"external": {"modifiers": frozenset(), "best_rank": "SS"}}
    _goto_vault(loop, null_input)
    _press(loop, null_input, "menu_right")
    assert loop.palette_id == "gold_silver"
    _press(loop, null_input, "pause")  # volta ao HUB -- a escolha persiste
    assert loop.flow == FLOW_HUB

    target = HUB_CATEGORIES.index("campaign")
    while loop.hub_cursor != target:
        _press(loop, null_input, "menu_up")
    _press(loop, null_input, "confirm")  # HUB -> CAROUSEL
    _press(loop, null_input, "confirm")  # CAROUSEL -> PREFLIGHT (unica fase, nunca trancada)
    _press(loop, null_input, "confirm")  # PREFLIGHT curada -> START
    assert loop.flow == FLOW_PLAYING
    assert loop._stage_config.threat_blue_rgb == PALETTE_CATALOG["gold_silver"]["threat_blue_rgb"]
    assert loop._stage_config.threat_pink_rgb == PALETTE_CATALOG["gold_silver"]["threat_pink_rgb"]
    assert load_user_palette_id(loop._user_settings_path) == "gold_silver"


# -- Calibracao (metronomo + tecla no tempo) ------------------------------


def test_entering_calibration_from_hub_and_esc_back(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]])
    _goto_calibration(loop, null_input)
    assert loop.flow == FLOW_CALIBRATION
    _press(loop, null_input, "pause")
    assert loop.flow == FLOW_HUB


def test_calibration_progress_reports_taps_given_and_last_offset(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0)]])
    _goto_calibration(loop, null_input)
    clock.set_now_seconds(0.02)
    _press(loop, null_input, "fire")

    given, target, last_offset = loop.calibration_progress()
    assert given == 1
    assert target == loop._base_config.calibration_target_taps
    assert last_offset == pytest.approx(0.02)


def test_calibration_averages_consistent_late_taps_into_a_latency_correction(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0)]])
    _goto_calibration(loop, null_input)
    clock.calibrate_latency(0.0)

    beat_duration = 60.0 / loop._base_config.calibration_bpm
    target_taps = loop._base_config.calibration_target_taps
    for i in range(target_taps):
        clock.set_now_seconds(i * beat_duration + 0.05)  # sempre 0.05s DEPOIS da batida (tarde, consistente)
        _press(loop, null_input, "fire")

    assert loop.flow == FLOW_HUB  # a calibracao se auto-encerra ao atingir o alvo de toques
    assert abs(clock.get_output_latency_seconds() - 0.05) < 1e-6


def test_calibration_averages_consistent_early_taps_the_other_direction(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0)]])
    _goto_calibration(loop, null_input)
    clock.calibrate_latency(0.08)

    beat_duration = 60.0 / loop._base_config.calibration_bpm
    target_taps = loop._base_config.calibration_target_taps
    for i in range(target_taps):
        clock.set_now_seconds(i * beat_duration - 0.03)  # 0.03s ANTES da batida (cedo)
        _press(loop, null_input, "fire")

    assert loop.flow == FLOW_HUB
    assert abs(clock.get_output_latency_seconds() - 0.05) < 1e-6
