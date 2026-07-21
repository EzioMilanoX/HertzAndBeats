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


def test_user_song_starts_with_no_modifiers_checked_and_defender_mode(tmp_path, null_input):
    """Musica do jogador: painel de checkboxes (Mecanicas Modulares)
    comeca no Defensor SEM nenhum modifier ligado -- o jogador monta a
    propria combinacao a partir do zero."""
    song, beatmap_path = _make_selectable_song(tmp_path, [_basic(3.0)])
    loop = _make_loop(song, beatmap_path, null_input)

    assert loop.chosen_game_mode(0) == "defender"
    assert loop.chosen_modifiers(0) == frozenset()
    assert loop.modifier_cursor(0) == 0

    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_PLAYING
    assert loop._stage_config.game_mode == "defender"
    assert loop._stage_config.active_modifiers == ()


def test_cursor_visits_every_row_in_order_and_wraps(tmp_path, null_input):
    """A/D percorrem o painel de checkboxes inteiro, na ordem, sem
    pular nenhuma linha, e enrolam nas duas pontas."""
    from hertzbeats.bootstrap.hertz_game_loop import DEFENDER_MODIFIER_ROWS, GAME_MODE_ROW

    song, beatmap_path = _make_selectable_song(tmp_path, [_basic(3.0)])
    loop = _make_loop(song, beatmap_path, null_input)
    rows = (GAME_MODE_ROW,) + DEFENDER_MODIFIER_ROWS
    assert loop.modifier_rows(0) == rows

    assert loop.modifier_cursor(0) == 0
    for i, _ in enumerate(rows[1:], start=1):
        _press(loop, null_input, "menu_right")
        assert loop.modifier_cursor(0) == i
    _press(loop, null_input, "menu_right")  # um passo alem do fim -- enrola de volta
    assert loop.modifier_cursor(0) == 0
    _press(loop, null_input, "menu_left")  # e o inverso tambem enrola
    assert loop.modifier_cursor(0) == len(rows) - 1


def _move_cursor_to(loop, null_input, row_name: str) -> None:
    target = loop.modifier_rows(0).index(row_name)
    while loop.modifier_cursor(0) != target:
        _press(loop, null_input, "menu_right")


def test_toggle_modifier_checks_and_unchecks_the_focused_row(tmp_path, null_input):
    song, beatmap_path = _make_selectable_song(tmp_path, [_basic(3.0)])
    loop = _make_loop(song, beatmap_path, null_input)

    _move_cursor_to(loop, null_input, "polarity")
    _press(loop, null_input, "toggle_modifier")
    assert "polarity" in loop.chosen_modifiers(0)

    _press(loop, null_input, "toggle_modifier")
    assert "polarity" not in loop.chosen_modifiers(0)


def test_toggling_the_game_mode_row_switches_between_defender_and_lanes(tmp_path, null_input):
    """A linha `GAME_MODE_ROW` (sempre a primeira, indice 0) alterna
    Defensor<->Arcade 4K -- so alcancavel com o cursor JA nela (toggle
    em qualquer outra linha liga/desliga um modifier, nao o modo).
    Arcade 4K tem BEM menos linhas (so "holds"); o cursor (sempre 0
    neste fluxo) continua valido nas duas listas."""
    from hertzbeats.bootstrap.hertz_game_loop import DEFENDER_MODIFIER_ROWS, GAME_MODE_ROW, LANES_MODIFIER_ROWS

    song, beatmap_path = _make_selectable_song(tmp_path, [_basic(3.0)])
    loop = _make_loop(song, beatmap_path, null_input)

    assert loop.modifier_cursor(0) == 0  # GAME_MODE_ROW, default
    _press(loop, null_input, "toggle_modifier")
    assert loop.chosen_game_mode(0) == "lanes"
    assert loop.modifier_rows(0) == (GAME_MODE_ROW,) + LANES_MODIFIER_ROWS

    # a lista encolheu pra 2 linhas -- andar 2x pra direita enrola de
    # volta na propria GAME_MODE_ROW
    _press(loop, null_input, "menu_right")
    assert loop.modifier_cursor(0) == 1  # "holds"
    _press(loop, null_input, "menu_right")
    assert loop.modifier_cursor(0) == 0  # enrolou

    _press(loop, null_input, "toggle_modifier")
    assert loop.chosen_game_mode(0) == "defender"
    assert loop.modifier_rows(0) == (GAME_MODE_ROW,) + DEFENDER_MODIFIER_ROWS


def test_holds_and_polarity_are_mutually_exclusive(tmp_path, null_input):
    """Ligar "holds" desliga "polarity" automaticamente e vice-versa --
    os dois reusam o mesmo `threat_type` "pesada" com significados
    incompativeis (Hold-Start vs Parry)."""
    song, beatmap_path = _make_selectable_song(tmp_path, [
        {"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_heavy", "lane": 0, "strength": 0.9},
    ])
    loop = _make_loop(song, beatmap_path, null_input)

    _move_cursor_to(loop, null_input, "polarity")
    _press(loop, null_input, "toggle_modifier")
    assert loop.chosen_modifiers(0) == frozenset({"polarity"})

    _move_cursor_to(loop, null_input, "holds")
    _press(loop, null_input, "toggle_modifier")
    assert loop.chosen_modifiers(0) == frozenset({"holds"})  # polarity foi desligada

    _press(loop, null_input, "toggle_modifier")  # desliga holds de novo
    _move_cursor_to(loop, null_input, "polarity")
    _press(loop, null_input, "toggle_modifier")
    _move_cursor_to(loop, null_input, "holds")
    _press(loop, null_input, "toggle_modifier")
    assert "polarity" not in loop.chosen_modifiers(0)  # o sentido inverso tambem exclui


def test_composing_confirms_with_exactly_the_checked_modifiers(tmp_path, null_input):
    song, beatmap_path = _make_selectable_song(tmp_path, [
        {"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_heavy", "lane": 0, "strength": 0.9},
    ])
    loop = _make_loop(song, beatmap_path, null_input)

    for row_name in ("telegraph_rings", "polarity", "orbital_shields"):
        _move_cursor_to(loop, null_input, row_name)
        _press(loop, null_input, "toggle_modifier")

    _press(loop, null_input, "confirm")
    assert loop._stage_config.game_mode == "defender"
    assert set(loop._stage_config.active_modifiers) == {"telegraph_rings", "polarity", "orbital_shields"}


def test_every_modifier_row_has_a_registered_label_texture():
    """Toda linha possivel do painel (`GAME_MODE_ROW` + cada modifier de
    `DEFENDER_MODIFIER_ROWS`/`LANES_MODIFIER_ROWS`) PRECISA de uma
    textura `modifier_row_*` registrada em `texture_bank.py` -- senao
    `_blit_centered`/`_draw_modifier_row` desenham a linha em BRANCO
    silenciosamente (nenhum teste de composicao pega isso sozinho, usam
    `NullRenderer`, que nunca toca essas texturas)."""
    from hertzbeats.adapters.texture_bank import _GAME_MODE_ROW_LABELS, _MODIFIER_ROW_LABELS
    from hertzbeats.bootstrap.hertz_game_loop import (
        DEFENDER_MODIFIER_ROWS,
        LANES_MODIFIER_ROWS,
    )

    assert "defender" in _GAME_MODE_ROW_LABELS
    assert "lanes" in _GAME_MODE_ROW_LABELS
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
