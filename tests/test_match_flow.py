"""HertzGameLoop: menu de fases -> jogando <-> pausa -> derrota/resultados, tudo headless."""
import math

import pytest

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from hertzbeats.bootstrap.hertz_game_loop import (
    FLOW_GAME_OVER,
    FLOW_MENU,
    FLOW_PAUSED,
    FLOW_PLAYING,
    FLOW_RESULTS,
    HertzGameLoop,
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
    ameacas por fase). As faixas sao WAVs minusculos sintetizados no tmp
    para que play/stop do `NullAudioEngine` controlem o clock como o
    backend real faria (reset em 0 a cada inicio de fase)."""

    def _make(stage_threat_lists, overrides_list=None):
        stages = []
        beatmap_path = None
        for i, threats in enumerate(stage_threat_lists):
            beatmap_path = write_beatmap(tmp_path / f"stage{i}.beatmap.json", threats)
            overrides = overrides_list[i] if overrides_list else {}
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


def test_menu_navigation_wraps_and_confirm_starts_stage(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0)], [_basic(3.0)]])
    assert loop.flow == FLOW_MENU
    assert loop.selected_stage == 0

    _press(loop, null_input, "menu_down")
    assert loop.selected_stage == 1
    _press(loop, null_input, "menu_down")
    assert loop.selected_stage == 0  # wrap
    _press(loop, null_input, "menu_up")
    assert loop.selected_stage == 1

    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_PLAYING
    assert loop.loaded_stage == 1
    assert clock.now_seconds() == 0.0  # musica da fase comecou do zero


def test_esc_in_menu_stops_the_loop(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]])
    loop._running = True
    _press(loop, null_input, "pause")
    assert loop._running is False


def test_pause_freezes_simulation_and_resumes(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0)]])
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


def test_pause_to_menu_returns_to_menu(flow_game, null_input):
    loop, _ = flow_game([[_basic(3.0)]])
    _press(loop, null_input, "confirm")
    _press(loop, null_input, "pause")
    _press(loop, null_input, "to_menu")
    assert loop.flow == FLOW_MENU


def test_health_zero_triggers_game_over_and_retry_restarts_fresh(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0)]], overrides_list=[{"max_health": 1}])
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
    loop, clock = flow_game([[_basic(3.0, lane=0)], [_basic(3.0, lane=1)]])
    _press(loop, null_input, "confirm")

    # autoplay: mira na lane 0 e atira no instante exato da batida
    null_input.set_axis("aim_x", math.cos(0.0))
    null_input.set_axis("aim_y", math.sin(0.0))
    clock.set_now_seconds(3.0)
    null_input.set_action_held("fire", True)
    null_input.poll()
    loop.advance_frame(DT)
    null_input.set_action_held("fire", False)
    null_input.poll()
    assert loop.composed.game_state.perfect_count == 1

    # fase limpa: apos a carencia de 1s entra em RESULTS
    for _ in range(80):
        clock.advance(DT)
        loop.advance_frame(DT)
        if loop.flow == FLOW_RESULTS:
            break
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


def _make_selectable_song(tmp_path, threats):
    beatmap_path = write_beatmap(tmp_path / "song.beatmap.json", threats)
    song = StageDef(
        stage_id="user_song", name="SONG", subtitle="sua musica",
        track_path=str(tmp_path / "song.wav"), beatmap_path=str(beatmap_path),
        synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
        tutorial_steps=(), selectable_mode=True,
    )
    return song, beatmap_path


def _make_loop(song, beatmap_path, null_input):
    audio_engine = NullAudioEngine()
    return HertzGameLoop(
        base_config=make_config(beatmap_path), stages=(song,), renderer=NullRenderer(),
        input_provider=null_input, audio_engine=audio_engine, audio_clock=audio_engine.get_clock(),
    )


def test_user_song_starts_unfocused_with_no_modifiers_and_defender_mode(tmp_path, null_input):
    """Musica do jogador: comeca fora do menu de opcoes (so navegando a
    lista de fases), no Defensor, mecanica pesada "Nenhuma" e sem
    nenhum modifier booleano ligado -- o jogador monta a propria
    combinacao a partir do zero."""
    song, beatmap_path = _make_selectable_song(tmp_path, [_basic(3.0)])
    loop = _make_loop(song, beatmap_path, null_input)

    assert loop.options_focused(0) is False
    assert loop.chosen_game_mode(0) == "defender"
    assert loop.chosen_heavy_mechanic(0) == "none"
    assert loop.chosen_modifiers(0) == frozenset()
    assert loop.menu_cursor_index(0) == 0


def test_confirm_on_a_selectable_song_enters_the_options_menu_without_starting(tmp_path, null_input):
    """ESPACO/ENTER numa musica do jogador (fora do menu de opcoes)
    ENTRA no menu -- nunca inicia a fase direto (so `START_ROW` faz
    isso, ver `test_start_row_only_starts_from_the_exact_row`)."""
    song, beatmap_path = _make_selectable_song(tmp_path, [_basic(3.0)])
    loop = _make_loop(song, beatmap_path, null_input)

    _press(loop, null_input, "confirm")
    assert loop.options_focused(0) is True
    assert loop.flow == FLOW_MENU
    assert loop.menu_cursor_index(0) == 0  # GAME_MODE_ROW


def _enter_options(loop, null_input, stage_index: int = 0) -> None:
    _press(loop, null_input, "confirm")
    assert loop.options_focused(stage_index) is True


def _move_cursor_to(loop, null_input, row_name: str, stage_index: int = 0) -> None:
    target = loop.modifier_rows(stage_index).index(row_name)
    while loop.menu_cursor_index(stage_index) != target:
        _press(loop, null_input, "menu_down")


def test_cursor_visits_every_row_in_order_and_wraps(tmp_path, null_input):
    """Dentro do menu de opcoes, W/S (menu_up/menu_down) percorrem TODAS
    as linhas na ordem, sem pular nenhuma, e enrolam nas duas pontas."""
    from hertzbeats.bootstrap.hertz_game_loop import DEFENDER_MODIFIER_ROWS, GAME_MODE_ROW, HEAVY_MECHANIC_ROW, START_ROW

    song, beatmap_path = _make_selectable_song(tmp_path, [_basic(3.0)])
    loop = _make_loop(song, beatmap_path, null_input)
    _enter_options(loop, null_input)
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


def test_left_right_do_nothing_outside_the_options_menu(tmp_path, null_input):
    """A/D so tem efeito DENTRO do menu de opcoes (alterando a linha de
    multipla escolha focada) -- fora dele (so navegando a lista de
    fases), nao fazem nada."""
    song, beatmap_path = _make_selectable_song(tmp_path, [_basic(3.0)])
    loop = _make_loop(song, beatmap_path, null_input)

    _press(loop, null_input, "menu_right")
    _press(loop, null_input, "menu_left")
    assert loop.chosen_game_mode(0) == "defender"
    assert loop.options_focused(0) is False


def test_toggle_modifier_checks_and_unchecks_the_focused_row(tmp_path, null_input):
    """ESPACO/ENTER numa linha de modifier BOOLEANO (nao numa de
    multipla escolha) liga/desliga aquele modifier."""
    song, beatmap_path = _make_selectable_song(tmp_path, [_basic(3.0)])
    loop = _make_loop(song, beatmap_path, null_input)
    _enter_options(loop, null_input)

    _move_cursor_to(loop, null_input, "telegraph_rings")
    _press(loop, null_input, "confirm")
    assert "telegraph_rings" in loop.chosen_modifiers(0)

    _press(loop, null_input, "confirm")
    assert "telegraph_rings" not in loop.chosen_modifiers(0)


def test_confirm_does_nothing_on_multiple_choice_rows(tmp_path, null_input):
    """ESPACO/ENTER numa linha de MULTIPLA ESCOLHA (`GAME_MODE_ROW`/
    `HEAVY_MECHANIC_ROW`) nao faz nada -- so A/D alteram o valor
    dessas linhas."""
    song, beatmap_path = _make_selectable_song(tmp_path, [_basic(3.0)])
    loop = _make_loop(song, beatmap_path, null_input)
    _enter_options(loop, null_input)

    assert loop.menu_cursor_index(0) == 0  # GAME_MODE_ROW
    _press(loop, null_input, "confirm")
    assert loop.chosen_game_mode(0) == "defender"  # intocado
    assert loop.flow == FLOW_MENU  # nao iniciou a fase


def test_left_right_cycle_the_game_mode_row(tmp_path, null_input):
    from hertzbeats.bootstrap.hertz_game_loop import DEFENDER_MODIFIER_ROWS, GAME_MODE_ROW, HEAVY_MECHANIC_ROW, START_ROW

    song, beatmap_path = _make_selectable_song(tmp_path, [_basic(3.0)])
    loop = _make_loop(song, beatmap_path, null_input)
    _enter_options(loop, null_input)

    assert loop.menu_cursor_index(0) == 0  # GAME_MODE_ROW
    _press(loop, null_input, "menu_right")
    assert loop.chosen_game_mode(0) == "lanes"
    assert loop.modifier_rows(0) == (GAME_MODE_ROW, HEAVY_MECHANIC_ROW, START_ROW)  # sem modifiers booleanos

    _press(loop, null_input, "menu_left")
    assert loop.chosen_game_mode(0) == "defender"
    assert loop.modifier_rows(0) == (GAME_MODE_ROW, HEAVY_MECHANIC_ROW) + DEFENDER_MODIFIER_ROWS + (START_ROW,)


def test_left_right_cycle_the_heavy_mechanic_row_through_none_polarity_holds(tmp_path, null_input):
    """A "Mecanica Pesada" e uma MULTIPLA ESCOLHA de 3 valores --
    Polaridade e Holds nunca podem estar ligadas ao mesmo tempo por
    CONSTRUCAO (nao ha 2 checkboxes independentes que precisem de logica
    de exclusao)."""
    song, beatmap_path = _make_selectable_song(tmp_path, [
        {"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_heavy", "lane": 0, "strength": 0.9},
    ])
    loop = _make_loop(song, beatmap_path, null_input)
    _enter_options(loop, null_input)
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


def test_switching_to_lanes_resets_an_invalid_heavy_mechanic(tmp_path, null_input):
    """"polarity" nao existe no Arcade 4K -- trocar pra "lanes" com
    "polarity" escolhida reseta a mecanica pesada pra "none" (nunca
    deixa um valor invalido pro modo atual)."""
    song, beatmap_path = _make_selectable_song(tmp_path, [
        {"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_heavy", "lane": 0, "strength": 0.9},
    ])
    loop = _make_loop(song, beatmap_path, null_input)
    _enter_options(loop, null_input)
    _move_cursor_to(loop, null_input, "heavy_mechanic")
    _press(loop, null_input, "menu_right")
    assert loop.chosen_heavy_mechanic(0) == "polarity"

    _move_cursor_to(loop, null_input, "game_mode")
    _press(loop, null_input, "menu_right")
    assert loop.chosen_game_mode(0) == "lanes"
    assert loop.chosen_heavy_mechanic(0) == "none"


def test_start_row_only_starts_from_the_exact_row(tmp_path, null_input):
    """ESPACO/ENTER so inicia a fase com o cursor EXATAMENTE em
    `START_ROW` -- em qualquer outra linha do menu de opcoes, so age
    sobre AQUELA linha (ou nao faz nada, nas de multipla escolha)."""
    song, beatmap_path = _make_selectable_song(tmp_path, [_basic(3.0)])
    loop = _make_loop(song, beatmap_path, null_input)
    _enter_options(loop, null_input)

    _move_cursor_to(loop, null_input, "telegraph_rings")
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_MENU  # so ligou o modifier, nao iniciou

    _move_cursor_to(loop, null_input, "start")
    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_PLAYING
    assert loop._stage_config.game_mode == "defender"
    assert loop._stage_config.active_modifiers == ("telegraph_rings",)


def test_esc_backs_out_of_the_options_menu_without_starting_or_quitting(tmp_path, null_input):
    song, beatmap_path = _make_selectable_song(tmp_path, [_basic(3.0)])
    loop = _make_loop(song, beatmap_path, null_input)
    _enter_options(loop, null_input)

    _press(loop, null_input, "pause")
    assert loop.options_focused(0) is False
    assert loop.flow == FLOW_MENU  # nao encerrou o jogo, so saiu do menu de opcoes


def test_composing_confirms_with_exactly_the_checked_modifiers_and_heavy_mechanic(tmp_path, null_input):
    song, beatmap_path = _make_selectable_song(tmp_path, [
        {"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_heavy", "lane": 0, "strength": 0.9},
    ])
    loop = _make_loop(song, beatmap_path, null_input)
    _enter_options(loop, null_input)

    for row_name in ("telegraph_rings", "orbital_shields"):
        _move_cursor_to(loop, null_input, row_name)
        _press(loop, null_input, "confirm")
    _move_cursor_to(loop, null_input, "heavy_mechanic")
    _press(loop, null_input, "menu_right")  # -> "polarity"

    _move_cursor_to(loop, null_input, "start")
    _press(loop, null_input, "confirm")
    assert loop._stage_config.game_mode == "defender"
    assert set(loop._stage_config.active_modifiers) == {"telegraph_rings", "orbital_shields", "polarity"}


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
    from hertzbeats.bootstrap.hertz_game_loop import (
        DEFENDER_MODIFIER_ROWS,
        HEAVY_MECHANIC_VALUES_BY_GAME_MODE,
        LANES_MODIFIER_ROWS,
    )

    assert "defender" in _GAME_MODE_ROW_LABELS
    assert "lanes" in _GAME_MODE_ROW_LABELS
    for values in HEAVY_MECHANIC_VALUES_BY_GAME_MODE.values():
        for value in values:
            assert value in _HEAVY_MECHANIC_ROW_LABELS, f"{value!r} sem rotulo em _HEAVY_MECHANIC_ROW_LABELS"
    for row_name in set(DEFENDER_MODIFIER_ROWS) | set(LANES_MODIFIER_ROWS):
        assert row_name in _MODIFIER_ROW_LABELS, f"{row_name!r} sem rotulo em _MODIFIER_ROW_LABELS"


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
    )
    _press(loop, null_input, "confirm")
    assert loop._stage_config.game_mode == "lanes"
    assert loop._stage_config.active_modifiers == ()
    # e realmente o Arcade 4K: o spawner de notas de coluna, nao o radial
    from hertzbeats.systems.lane_note_spawner_system import LaneNoteSpawnerSystem
    assert any(isinstance(s, LaneNoteSpawnerSystem) for s in loop.composed.world._systems)


def test_saved_latency_roundtrip(tmp_path):
    from hertzbeats.user_settings import load_user_latency, save_user_latency

    path = str(tmp_path / "user_settings.json")
    assert load_user_latency(path) is None  # sem arquivo -> default da config
    save_user_latency(0.13, path)
    assert load_user_latency(path) == 0.13
    save_user_latency(9.9, path)  # valores absurdos sao clampados na leitura
    assert load_user_latency(path) == 0.30


def test_game_over_to_menu(flow_game, null_input):
    loop, clock = flow_game([[_basic(3.0)]], overrides_list=[{"max_health": 1}])
    _press(loop, null_input, "confirm")
    for _ in range(240):
        clock.advance(DT)
        loop.advance_frame(DT)
        if loop.flow == FLOW_GAME_OVER:
            break
    assert loop.flow == FLOW_GAME_OVER
    _press(loop, null_input, "to_menu")
    assert loop.flow == FLOW_MENU
