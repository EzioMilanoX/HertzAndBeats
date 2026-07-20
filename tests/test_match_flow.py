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


def test_user_song_mode_cycles_and_composes_chosen_mode(tmp_path, null_input):
    """Musica do jogador: A/D alternam o minigame no menu e a fase
    compoe com o modo escolhido (o MESMO beatmap, outra interpretacao)."""
    beatmap_path = write_beatmap(tmp_path / "song.beatmap.json", [
        {"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.5},
    ])
    song = StageDef(
        stage_id="user_song", name="SONG", subtitle="sua musica",
        track_path=str(tmp_path / "song.wav"), beatmap_path=str(beatmap_path),
        synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
        tutorial_steps=(), selectable_mode=True,
    )
    audio_engine = NullAudioEngine()
    loop = HertzGameLoop(
        base_config=make_config(beatmap_path),
        stages=(song,),
        renderer=NullRenderer(),
        input_provider=null_input,
        audio_engine=audio_engine,
        audio_clock=audio_engine.get_clock(),
    )

    assert loop.chosen_mode(0) == "defender"
    _press(loop, null_input, "menu_right")
    assert loop.chosen_mode(0) == "lanes"
    _press(loop, null_input, "menu_right")
    assert loop.chosen_mode(0) == "polarity"
    _press(loop, null_input, "menu_left")
    assert loop.chosen_mode(0) == "lanes"

    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_PLAYING
    assert loop._stage_config.game_mode == "lanes"


def test_user_song_can_reach_the_polarity_and_holds_variants(tmp_path, null_input):
    """As duas variantes finais do ciclo ("polarity"/"holds") sao o
    Defensor por baixo, com os modifiers "polarity"/"holds" ligados via
    `active_modifiers` -- as MESMAS mecanicas das fases curadas 7/8,
    agora escolhiveis para qualquer musica do jogador."""
    beatmap_path = write_beatmap(tmp_path / "song.beatmap.json", [
        {"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_heavy", "lane": 0, "strength": 0.9},
    ])
    song = StageDef(
        stage_id="user_song", name="SONG", subtitle="sua musica",
        track_path=str(tmp_path / "song.wav"), beatmap_path=str(beatmap_path),
        synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
        tutorial_steps=(), selectable_mode=True,
    )
    audio_engine = NullAudioEngine()
    loop = HertzGameLoop(
        base_config=make_config(beatmap_path),
        stages=(song,),
        renderer=NullRenderer(),
        input_provider=null_input,
        audio_engine=audio_engine,
        audio_clock=audio_engine.get_clock(),
    )

    # defender -> lanes -> polarity (2 passos)
    for _ in range(2):
        _press(loop, null_input, "menu_right")
    assert loop.chosen_mode(0) == "polarity"
    _press(loop, null_input, "confirm")
    assert loop._stage_config.game_mode == "defender"
    assert "polarity" in loop._stage_config.active_modifiers
    assert "holds" not in loop._stage_config.active_modifiers


def test_user_song_holds_variant_enables_only_holds(tmp_path, null_input):
    beatmap_path = write_beatmap(tmp_path / "song.beatmap.json", [
        {"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_heavy", "lane": 0, "strength": 0.9},
    ])
    song = StageDef(
        stage_id="user_song", name="SONG", subtitle="sua musica",
        track_path=str(tmp_path / "song.wav"), beatmap_path=str(beatmap_path),
        synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
        tutorial_steps=(), selectable_mode=True,
    )
    audio_engine = NullAudioEngine()
    loop = HertzGameLoop(
        base_config=make_config(beatmap_path),
        stages=(song,),
        renderer=NullRenderer(),
        input_provider=null_input,
        audio_engine=audio_engine,
        audio_clock=audio_engine.get_clock(),
    )

    # defender -> lanes -> polarity -> holds (3 passos)
    for _ in range(3):
        _press(loop, null_input, "menu_right")
    assert loop.chosen_mode(0) == "holds"
    _press(loop, null_input, "confirm")
    assert loop._stage_config.game_mode == "defender"
    assert "holds" in loop._stage_config.active_modifiers
    assert "polarity" not in loop._stage_config.active_modifiers


def test_user_song_mode_cycle_visits_every_entry_in_order_and_wraps(tmp_path, null_input):
    """A/D percorrem `MODE_CYCLE` inteiro, na ordem, sem pular nenhuma
    entrada -- prova que o indice modulo `len(MODE_CYCLE)` continua
    coerente mesmo com o ciclo estendido pelo 3o pacote hardcore do
    Defensor (`orbital_shields`/`twin_threats`/`orbital_eclipses`/
    `overload`/`nightmare`, acrescentados no FIM da tupla)."""
    from hertzbeats.bootstrap.hertz_game_loop import MODE_CYCLE

    beatmap_path = write_beatmap(tmp_path / "song.beatmap.json", [_basic(3.0)])
    song = StageDef(
        stage_id="user_song", name="SONG", subtitle="sua musica",
        track_path=str(tmp_path / "song.wav"), beatmap_path=str(beatmap_path),
        synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
        tutorial_steps=(), selectable_mode=True,
    )
    audio_engine = NullAudioEngine()
    loop = HertzGameLoop(
        base_config=make_config(beatmap_path), stages=(song,), renderer=NullRenderer(),
        input_provider=null_input, audio_engine=audio_engine, audio_clock=audio_engine.get_clock(),
    )

    assert loop.chosen_mode(0) == MODE_CYCLE[0]
    for expected in MODE_CYCLE[1:]:
        _press(loop, null_input, "menu_right")
        assert loop.chosen_mode(0) == expected
    _press(loop, null_input, "menu_right")  # um passo alem do fim -- enrola de volta
    assert loop.chosen_mode(0) == MODE_CYCLE[0]
    _press(loop, null_input, "menu_left")  # e o inverso tambem enrola
    assert loop.chosen_mode(0) == MODE_CYCLE[-1]


@pytest.mark.parametrize(
    "mode_name,expected_modifiers",
    [
        ("orbital_shields", {"telegraph_rings", "polarity", "orbital_shields"}),
        ("twin_threats", {"telegraph_rings", "polarity", "twin_threats"}),
        ("orbital_eclipses", {"telegraph_rings", "polarity", "orbital_eclipses"}),
        ("overload", {"telegraph_rings", "polarity", "overload"}),
        (
            "nightmare",
            {"telegraph_rings", "polarity", "orbital_shields", "twin_threats", "orbital_eclipses", "overload"},
        ),
    ],
)
def test_user_song_can_reach_each_new_hardcore_variant(tmp_path, null_input, mode_name, expected_modifiers):
    """As 5 variantes novas do 3o pacote hardcore do Defensor sao
    escolhiveis pra qualquer musica do jogador, cada uma compondo com
    exatamente os modifiers esperados (sempre com "polarity" junto --
    todas dependem dela)."""
    from hertzbeats.bootstrap.hertz_game_loop import MODE_CYCLE

    beatmap_path = write_beatmap(tmp_path / "song.beatmap.json", [
        {"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_heavy", "lane": 0, "strength": 0.9},
    ])
    song = StageDef(
        stage_id="user_song", name="SONG", subtitle="sua musica",
        track_path=str(tmp_path / "song.wav"), beatmap_path=str(beatmap_path),
        synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
        tutorial_steps=(), selectable_mode=True,
    )
    audio_engine = NullAudioEngine()
    loop = HertzGameLoop(
        base_config=make_config(beatmap_path), stages=(song,), renderer=NullRenderer(),
        input_provider=null_input, audio_engine=audio_engine, audio_clock=audio_engine.get_clock(),
    )

    for _ in range(MODE_CYCLE.index(mode_name)):
        _press(loop, null_input, "menu_right")
    assert loop.chosen_mode(0) == mode_name

    _press(loop, null_input, "confirm")
    assert loop._stage_config.game_mode == "defender"
    assert set(loop._stage_config.active_modifiers) == expected_modifiers


def test_every_mode_cycle_entry_has_an_override_display_name_and_hint():
    """Toda entrada de `MODE_CYCLE` PRECISA de uma chave correspondente
    em `MODE_VARIANT_OVERRIDES` (senao `KeyError` em `_compose_stage` ao
    confirmar) e em `_MODE_DISPLAY_NAMES`/`_MODE_CONTROL_HINTS` (senao
    nome/dica em branco, ou `KeyError` no carregamento do jogo) --
    consistencia entre `hertz_game_loop.py` e `texture_bank.py` que
    nenhum teste de composicao pega sozinho (usam `NullRenderer`, que
    nunca toca essas texturas)."""
    from hertzbeats.adapters.texture_bank import _MODE_CONTROL_HINTS, _MODE_DISPLAY_NAMES
    from hertzbeats.bootstrap.hertz_game_loop import MODE_CYCLE, MODE_VARIANT_OVERRIDES

    for mode_name in MODE_CYCLE:
        assert mode_name in MODE_VARIANT_OVERRIDES, f"{mode_name!r} sem override em MODE_VARIANT_OVERRIDES"
        assert mode_name in _MODE_DISPLAY_NAMES, f"{mode_name!r} sem nome em _MODE_DISPLAY_NAMES"
        assert mode_name in _MODE_CONTROL_HINTS, f"{mode_name!r} sem dica em _MODE_CONTROL_HINTS"


def test_a_curated_stage_is_never_affected_by_the_variant_cycle(tmp_path, null_input):
    """Fases curadas (`selectable_mode=False`) ignoram `MODE_VARIANT_OVERRIDES`
    por completo -- so usam os `overrides` do proprio `stages.json`."""
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
