"""Eventos de Gameplay via Capitulos do YouTube: bridge chapters -> Modchart sintetico + ChapterEventSystem (Deformacao de Arena)."""
import pytest

from hertzbeats.bootstrap.hertz_game_loop import HertzGameLoop
from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.modchart import chapters_to_modchart_events, parse_arena_warp_events
from hertzbeats.stages import StageDef
from hertzbeats.systems.chapter_event_system import ChapterEventSystem

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from tests.conftest import make_config, write_beatmap
from tests.test_match_flow import _basic


# -- parse_arena_warp_events (pura) ------------------------------------------


def test_parse_arena_warp_events_filters_by_type_and_sorts():
    raw = [
        {"type": "reverse_scroll", "time_seconds": 1.0},
        {"type": "arena_warp", "time_seconds": 10.0, "shake_px": 30.0},
        {"type": "arena_warp", "time_seconds": 2.0},
    ]
    events = parse_arena_warp_events(raw)
    assert events == ((2.0, 24.0), (10.0, 30.0))  # 24.0 = default shake_px


def test_parse_arena_warp_events_is_empty_without_any_matching_type():
    assert parse_arena_warp_events([{"type": "swap", "time_seconds": 1.0}]) == ()


# -- chapters_to_modchart_events (pura) --------------------------------------


def test_chapters_to_modchart_events_matches_keywords_case_insensitively():
    chapters = [
        {"start_time_seconds": 0.0, "title": "Intro"},
        {"start_time_seconds": 85.0, "title": "THE DROP"},
    ]
    events = chapters_to_modchart_events(chapters, ("drop", "chorus"), game_mode="defender")
    assert events == ({"type": "arena_warp", "time_seconds": 85.0, "shake_px": 24.0},)


def test_chapters_to_modchart_events_adds_reverse_scroll_only_in_lanes_mode():
    chapters = [{"start_time_seconds": 40.0, "title": "Chorus"}]
    defender_events = chapters_to_modchart_events(chapters, ("chorus",), game_mode="defender")
    lanes_events = chapters_to_modchart_events(chapters, ("chorus",), game_mode="lanes")

    assert defender_events == ({"type": "arena_warp", "time_seconds": 40.0, "shake_px": 24.0},)
    assert lanes_events == (
        {"type": "arena_warp", "time_seconds": 40.0, "shake_px": 24.0},
        {"type": "reverse_scroll", "time_seconds": 40.0, "duration_seconds": 1.0, "reversed": True},
    )


def test_chapters_to_modchart_events_ignores_chapters_without_a_keyword():
    chapters = [{"start_time_seconds": 0.0, "title": "Intro"}, {"start_time_seconds": 60.0, "title": "Outro"}]
    assert chapters_to_modchart_events(chapters, ("drop", "chorus"), game_mode="defender") == ()


def test_chapters_to_modchart_events_is_empty_without_any_chapters():
    assert chapters_to_modchart_events((), ("drop",), game_mode="defender") == ()


def test_chapters_to_modchart_events_uses_the_custom_shake_px():
    chapters = [{"start_time_seconds": 5.0, "title": "Drop"}]
    events = chapters_to_modchart_events(chapters, ("drop",), game_mode="defender", shake_px=99.0)
    assert events == ({"type": "arena_warp", "time_seconds": 5.0, "shake_px": 99.0},)


# -- ChapterEventSystem (unitario, com um NullAudioClock real) --------------


def test_chapter_event_system_triggers_shake_once_per_crossed_event(null_clock):
    from hertzbeats.game_state import GameState

    state = GameState(max_health=3)
    system = ChapterEventSystem(null_clock, state, warp_events=((5.0, 30.0), (10.0, 50.0)))

    null_clock.set_now_seconds(1.0)
    system.update(world=None, delta_time=0.016)
    assert state.shake_intensity == 0.0

    null_clock.set_now_seconds(6.0)
    system.update(world=None, delta_time=0.016)
    assert state.shake_intensity == pytest.approx(30.0)

    state.shake_intensity = 0.0  # simula o decaimento do CameraShakeSystem
    null_clock.set_now_seconds(6.5)
    system.update(world=None, delta_time=0.016)
    assert state.shake_intensity == 0.0  # ja disparou, nao dispara de novo

    null_clock.set_now_seconds(11.0)
    system.update(world=None, delta_time=0.016)
    assert state.shake_intensity == pytest.approx(50.0)


def test_chapter_event_system_never_fires_before_its_timestamp(null_clock):
    from hertzbeats.game_state import GameState

    state = GameState(max_health=3)
    system = ChapterEventSystem(null_clock, state, warp_events=((100.0, 30.0),))
    null_clock.set_now_seconds(0.0)
    for _ in range(5):
        system.update(world=None, delta_time=0.016)
    assert state.shake_intensity == 0.0


# -- compose_world: registro condicional do ChapterEventSystem --------------


def test_compose_world_registers_chapter_event_system_only_with_arena_warp_events(tmp_path, null_input, null_clock):
    beatmap_path = write_beatmap(tmp_path / "b.beatmap.json", [_basic(3.0)])
    config = make_config(beatmap_path)

    without_events = compose_world(config, null_input, null_clock, modchart_events=())
    assert not any(isinstance(s, ChapterEventSystem) for s in without_events.world._systems)

    with_events = compose_world(
        config, null_input, null_clock,
        modchart_events=({"type": "arena_warp", "time_seconds": 5.0, "shake_px": 20.0},),
    )
    assert any(isinstance(s, ChapterEventSystem) for s in with_events.world._systems)


# -- HertzGameLoop._compose_stage: StageDef.chapters -> ChapterEventSystem --


def test_compose_stage_wires_stage_chapters_into_a_chapter_event_system(tmp_path, null_input):
    beatmap_path = write_beatmap(tmp_path / "s.beatmap.json", [_basic(3.0)])
    stage = StageDef(
        stage_id="s", name="FASE", subtitle="", track_path="", beatmap_path=str(beatmap_path),
        synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
        chapters=({"start_time_seconds": 5.0, "title": "Epic Drop"},),
    )
    audio_engine = NullAudioEngine()
    loop = HertzGameLoop(
        base_config=make_config(beatmap_path), stages=(stage,), renderer=NullRenderer(),
        input_provider=null_input, audio_engine=audio_engine, audio_clock=audio_engine.get_clock(),
        player_progress_path=str(tmp_path / "player_progress.json"),
        player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
        user_settings_path=str(tmp_path / "user_settings.json"),
    )
    assert any(isinstance(s, ChapterEventSystem) for s in loop.composed.world._systems)


def test_compose_stage_ignores_chapters_without_any_matching_keyword(tmp_path, null_input):
    beatmap_path = write_beatmap(tmp_path / "s.beatmap.json", [_basic(3.0)])
    stage = StageDef(
        stage_id="s", name="FASE", subtitle="", track_path="", beatmap_path=str(beatmap_path),
        synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
        chapters=({"start_time_seconds": 5.0, "title": "Intro"},),
    )
    audio_engine = NullAudioEngine()
    loop = HertzGameLoop(
        base_config=make_config(beatmap_path), stages=(stage,), renderer=NullRenderer(),
        input_provider=null_input, audio_engine=audio_engine, audio_clock=audio_engine.get_clock(),
        player_progress_path=str(tmp_path / "player_progress.json"),
        player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
        user_settings_path=str(tmp_path / "user_settings.json"),
    )
    assert not any(isinstance(s, ChapterEventSystem) for s in loop.composed.world._systems)
