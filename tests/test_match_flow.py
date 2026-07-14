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
