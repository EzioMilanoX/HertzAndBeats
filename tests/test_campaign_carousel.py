"""Tags de Campanha/Lore + Filtro do Carrossel: `StageDef.campaign_id`/`description`, visoes alternaveis (TAB/Q/E)."""
from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.adapters.texture_bank import build_and_register_overlay_surfaces
from hertzbeats.bootstrap.hertz_game_loop import FLOW_CAROUSEL, FLOW_HUB, FLOW_PREFLIGHT, HertzGameLoop
from hertzbeats.stages import StageDef, campaign_ids

from tests.test_match_flow import _basic, _goto_hub, _press, flow_game  # noqa: F401


# -- StageDef/campaign_ids (puro) --------------------------------------------


def test_stage_def_defaults_campaign_id_to_default_and_description_to_empty():
    stage = StageDef(
        stage_id="s", name="FASE", subtitle="", track_path="", beatmap_path="unused",
        synth=None, beatmap_params={}, overrides={},
    )
    assert stage.campaign_id == "default"
    assert stage.description == ""


def _stage(stage_id: str, campaign_id: str, selectable: bool = False) -> StageDef:
    return StageDef(
        stage_id=stage_id, name=stage_id, subtitle="", track_path="", beatmap_path="unused",
        synth=None, beatmap_params={}, overrides={}, selectable_mode=selectable, campaign_id=campaign_id,
    )


def test_campaign_ids_returns_distinct_ids_in_first_appearance_order():
    stages = (
        _stage("a", "defender_core"),
        _stage("b", "arcade_matrix"),
        _stage("c", "defender_core"),
        _stage("d", "arcade_matrix"),
    )
    assert campaign_ids(stages) == ("defender_core", "arcade_matrix")


def test_campaign_ids_ignores_selectable_stages():
    stages = (
        _stage("a", "defender_core"),
        _stage("user_song", "whatever_the_song_carries", selectable=True),
    )
    assert campaign_ids(stages) == ("defender_core",)


# -- HertzGameLoop: filtro do Carrossel por campanha -------------------------


def _two_campaigns_loop(flow_game, null_input):
    """3 fases curadas (2 em "camp_a", 1 em "camp_b") + 1 musica do
    jogador -- o suficiente para exercitar filtro/troca de visao e
    travamento independente por campanha."""
    loop, clock = flow_game(
        [[_basic(3.0)], [_basic(3.0)], [_basic(3.0)], [_basic(3.0)]],
        selectable_list=[False, False, False, True],
        campaign_id_list=["camp_a", "camp_a", "camp_b", "default"],
    )
    return loop, clock


def test_campaign_entries_for_filters_by_campaign_id(flow_game, null_input):
    loop, _ = _two_campaigns_loop(flow_game, null_input)
    assert [i for i, _s in loop.campaign_entries_for("camp_a")] == [0, 1]
    assert [i for i, _s in loop.campaign_entries_for("camp_b")] == [2]
    assert loop.campaign_entries_for("nao_existe") == []


def test_campaign_entries_unfiltered_still_returns_every_curated_stage(flow_game, null_input):
    """`campaign_entries()` (sem argumento) continua servindo quem
    precisa da Campanha INTEIRA de uma vez (ex.: Ironman) -- cruzando
    qualquer `campaign_id`."""
    loop, _ = _two_campaigns_loop(flow_game, null_input)
    assert [i for i, _s in loop.campaign_entries()] == [0, 1, 2]


def test_campaign_ids_and_carousel_views_reflect_the_stage_list(flow_game, null_input):
    loop, _ = _two_campaigns_loop(flow_game, null_input)
    assert loop.campaign_ids() == ("camp_a", "camp_b")
    assert loop.carousel_views() == ("camp_a", "camp_b", "free_play")


def test_confirming_campaign_from_hub_enters_the_first_campaigns_carousel(flow_game, null_input):
    loop, _ = _two_campaigns_loop(flow_game, null_input)
    _goto_hub(loop, null_input)
    _press(loop, null_input, "confirm")  # HUB cursor comeca em "campaign" (indice 0)
    assert loop.flow == FLOW_CAROUSEL
    assert loop.carousel_category == "camp_a"


def test_cycle_view_next_visits_every_view_in_order_and_wraps(flow_game, null_input):
    loop, _ = _two_campaigns_loop(flow_game, null_input)
    _goto_hub(loop, null_input)
    _press(loop, null_input, "confirm")
    assert loop.carousel_category == "camp_a"

    _press(loop, null_input, "cycle_view_next")
    assert loop.carousel_category == "camp_b"
    _press(loop, null_input, "cycle_view_next")
    assert loop.carousel_category == "free_play"
    _press(loop, null_input, "cycle_view_next")
    assert loop.carousel_category == "camp_a"  # enrolou


def test_cycle_view_prev_moves_backward_and_wraps(flow_game, null_input):
    loop, _ = _two_campaigns_loop(flow_game, null_input)
    _goto_hub(loop, null_input)
    _press(loop, null_input, "confirm")
    assert loop.carousel_category == "camp_a"

    _press(loop, null_input, "cycle_view_prev")
    assert loop.carousel_category == "free_play"  # enrolou pro outro lado
    _press(loop, null_input, "cycle_view_prev")
    assert loop.carousel_category == "camp_b"


def test_switching_view_preserves_each_views_own_cursor_position(flow_game, null_input):
    loop, _ = _two_campaigns_loop(flow_game, null_input)
    _goto_hub(loop, null_input)
    _press(loop, null_input, "confirm")
    assert loop.carousel_category == "camp_a"
    _press(loop, null_input, "menu_down")  # posicao 1 em camp_a
    assert loop.carousel_index() == 1

    _press(loop, null_input, "cycle_view_next")  # camp_b -- so 1 fase, posicao 0
    assert loop.carousel_index() == 0

    _press(loop, null_input, "cycle_view_prev")  # de volta a camp_a
    assert loop.carousel_index() == 1  # lembrada, nao reiniciada


def test_locking_is_independent_per_campaign(flow_game, null_input):
    """Comecar "camp_b" nao exige terminar "camp_a" antes -- progressoes
    de campanhas diferentes nunca se travam entre si."""
    loop, _ = _two_campaigns_loop(flow_game, null_input)
    assert loop.is_campaign_entry_locked("camp_a", 0) is False
    assert loop.is_campaign_entry_locked("camp_a", 1) is True  # 2a fase de camp_a, 1a nunca vencida
    assert loop.is_campaign_entry_locked("camp_b", 0) is False  # 1a fase da OUTRA campanha, sempre livre


def test_free_play_is_never_reported_as_locked(flow_game, null_input):
    loop, _ = _two_campaigns_loop(flow_game, null_input)
    _goto_hub(loop, null_input)
    _press(loop, null_input, "menu_down")  # HUB cursor -> "free_play"
    _press(loop, null_input, "confirm")
    assert loop.carousel_category == "free_play"
    _press(loop, null_input, "confirm")  # entra na unica musica do jogador
    assert loop.flow == FLOW_PREFLIGHT


def test_a_stage_view_with_zero_entries_stays_empty_after_cycling_into_it(flow_game, null_input):
    """`campaign_entries_for` de uma campanha SEM nenhuma fase (ex.: uma
    lista com so 1 campanha, cruzando pra uma visao vazia) nunca quebra
    -- so' fica vazia, mesmo tratamento do Free Play sem musicas."""
    loop, _ = flow_game([[_basic(3.0)]], selectable_list=[False], campaign_id_list=["camp_a"])
    _goto_hub(loop, null_input)
    _press(loop, null_input, "confirm")
    assert loop.carousel_category == "camp_a"
    _press(loop, null_input, "cycle_view_next")  # so' existe "camp_a" + "free_play" -- vai pro Free Play vazio
    assert loop.carousel_category == "free_play"
    assert loop.carousel_entries() == []
    assert loop.carousel_focused_stage_index() is None


# -- Renderer/texturas: cabecalho por campanha + descricao por fase ----------


def test_every_campaign_id_has_a_registered_carousel_header_texture():
    stages = (_stage("a", "defender_core"), _stage("b", "arcade_matrix"))
    renderer = HBPygameRenderer()
    renderer.initialize(160, 120, "test")
    build_and_register_overlay_surfaces(renderer, stages)
    assert renderer._overlay_surfaces.get("carousel_category_defender_core") is not None
    assert renderer._overlay_surfaces.get("carousel_category_arcade_matrix") is not None
    assert renderer._overlay_surfaces.get("carousel_category_free_play") is not None
    assert renderer._overlay_surfaces.get("hint_carousel_switch_view") is not None


def test_every_stage_has_a_registered_description_texture_even_when_empty():
    stages = (
        StageDef(
            stage_id="s0", name="FASE", subtitle="", track_path="", beatmap_path="unused",
            synth=None, beatmap_params={}, overrides={}, description="Uma frase de lore.",
        ),
        StageDef(
            stage_id="s1", name="FASE", subtitle="", track_path="", beatmap_path="unused",
            synth=None, beatmap_params={}, overrides={},
        ),
    )
    renderer = HBPygameRenderer()
    renderer.initialize(160, 120, "test")
    build_and_register_overlay_surfaces(renderer, stages)
    assert renderer._overlay_surfaces.get("stage_0_description") is not None
    assert renderer._overlay_surfaces.get("stage_1_description") is not None
