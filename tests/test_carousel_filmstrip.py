"""Carrossel Horizontal + Audio Preview: janela de vizinhos, cache de miniaturas/fundo/paleta, e o timer de repouso do cursor."""
import pygame
import pytest

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.bootstrap.hertz_game_loop import (
    FLOW_CAROUSEL,
    FLOW_PREFLIGHT,
    HertzGameLoop,
    carousel_neighbor_window,
)
from hertzbeats.stages import StageDef

from tests.conftest import make_config, write_beatmap
from tests.test_match_flow import DT, _basic, _goto_hub, _press


# -- carousel_neighbor_window (pura) -----------------------------------------


def test_neighbor_window_with_a_single_entry_shows_only_the_focus():
    assert carousel_neighbor_window(("a",), 0) == ("a",)


def test_neighbor_window_with_two_entries_shows_only_the_focus_to_avoid_duplicates():
    # half_window = (2-1)//2 = 0 -- mostrar so o foco evita repetir a
    # UNICA outra musica nos 2 lados ao mesmo tempo
    assert carousel_neighbor_window(("a", "b"), 0) == ("a",)
    assert carousel_neighbor_window(("a", "b"), 1) == ("b",)


def test_neighbor_window_with_three_entries_shows_both_immediate_neighbors():
    assert carousel_neighbor_window(("a", "b", "c"), 0) == ("c", "a", "b")


def test_neighbor_window_with_four_entries_avoids_the_opposite_duplicate():
    # half_window = (4-1)//2 = 1 -- NAO usa +-2 (que bateria na mesma
    # musica oposta dos dois lados por wraparound)
    result = carousel_neighbor_window(("a", "b", "c", "d"), 0)
    assert result == ("d", "a", "b")
    assert len(set(result)) == len(result)


def test_neighbor_window_with_five_or_more_entries_shows_the_full_window():
    result = carousel_neighbor_window(("a", "b", "c", "d", "e"), 2)
    assert result == ("a", "b", "c", "d", "e")
    assert len(set(result)) == 5


def test_neighbor_window_wraps_around_both_edges():
    entries = ("a", "b", "c", "d", "e")
    assert carousel_neighbor_window(entries, 0) == ("d", "e", "a", "b", "c")
    assert carousel_neighbor_window(entries, 4) == ("c", "d", "e", "a", "b")


def test_neighbor_window_is_empty_for_an_empty_catalog():
    assert carousel_neighbor_window((), 0) == ()


# -- HertzGameLoop: timer de repouso + Audio Preview -------------------------


class _FakePreviewAudioEngine(NullAudioEngine):
    def __init__(self) -> None:
        super().__init__()
        self.preview_calls = []
        self.stop_calls = []

    def play_preview(self, track_id: str, start_offset_seconds: float, fade_ms: int = 1000) -> None:
        self.preview_calls.append((track_id, start_offset_seconds, fade_ms))

    def stop_track(self, track_id: str) -> None:
        self.stop_calls.append(track_id)
        super().stop_track(track_id)


@pytest.fixture
def preview_loop(tmp_path, null_input):
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
                    selectable_mode=True,
                )
            )
        audio_engine = _FakePreviewAudioEngine()
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
        return loop, audio_engine

    return _make


def _goto_free_play_carousel(loop, null_input):
    _goto_hub(loop, null_input)
    _press(loop, null_input, "menu_down")  # HUB cursor -> "free_play"
    _press(loop, null_input, "confirm")


def test_preview_does_not_start_before_the_hover_threshold(preview_loop, null_input):
    loop, engine = preview_loop([[_basic(3.0)], [_basic(3.0)]])
    _goto_free_play_carousel(loop, null_input)
    assert loop.flow == FLOW_CAROUSEL

    for _ in range(10):  # bem menos que carousel_preview_hover_seconds (0.5s)
        loop.advance_frame(DT)
    assert engine.preview_calls == []


def test_preview_starts_after_resting_on_a_song_past_the_hover_threshold(preview_loop, null_input):
    loop, engine = preview_loop([[_basic(3.0)]], overrides_list=[{}])
    _goto_free_play_carousel(loop, null_input)

    frames_needed = int(loop._base_config.carousel_preview_hover_seconds / DT) + 2
    for _ in range(frames_needed):
        loop.advance_frame(DT)

    assert len(engine.preview_calls) == 1
    track_id, start_offset, fade_ms = engine.preview_calls[0]
    assert track_id == "stage0"
    assert fade_ms == loop._base_config.carousel_preview_fade_ms
    assert start_offset >= 0.0


def test_moving_the_cursor_resets_the_hover_timer_and_stops_a_playing_preview(preview_loop, null_input):
    loop, engine = preview_loop([[_basic(3.0)], [_basic(3.0)]])
    _goto_free_play_carousel(loop, null_input)

    frames_needed = int(loop._base_config.carousel_preview_hover_seconds / DT) + 2
    for _ in range(frames_needed):
        loop.advance_frame(DT)
    assert len(engine.preview_calls) == 1

    _press(loop, null_input, "menu_down")  # foco muda pra fase1
    loop.advance_frame(DT)
    assert engine.stop_calls == ["stage0"]


def test_leaving_the_carousel_stops_any_playing_preview(preview_loop, null_input):
    loop, engine = preview_loop([[_basic(3.0)]])
    _goto_free_play_carousel(loop, null_input)
    frames_needed = int(loop._base_config.carousel_preview_hover_seconds / DT) + 2
    for _ in range(frames_needed):
        loop.advance_frame(DT)
    assert len(engine.preview_calls) == 1

    _press(loop, null_input, "confirm")  # Carrossel -> Pre-Voo
    assert loop.flow == FLOW_PREFLIGHT
    loop.advance_frame(DT)
    assert engine.stop_calls == ["stage0"]


def test_preview_uses_thirty_percent_of_the_known_duration_when_available(tmp_path, null_input):
    # `synth=None` (musica REAL, nao re-sintetizada) e' o unico jeito de
    # `read_stage_bpm_and_duration` considerar `known_duration_seconds`
    # -- com `synth` presente (fixture `preview_loop`), a formula EXATA
    # do synth sempre vence de proposito (ver `stages.read_stage_bpm_and_duration`).
    beatmap_path = write_beatmap(tmp_path / "yt.beatmap.json", [_basic(3.0)])
    (tmp_path / "yt.wav").write_bytes(b"fake audio")  # synth=None exige o arquivo no disco
    stage = StageDef(
        stage_id="youtube_song", name="MUSICA DO YOUTUBE", subtitle="", track_path=str(tmp_path / "yt.wav"),
        beatmap_path=str(beatmap_path), synth=None, beatmap_params={}, overrides={},
        selectable_mode=True, known_duration_seconds=100.0,
    )
    audio_engine = _FakePreviewAudioEngine()
    clock = audio_engine.get_clock()
    loop = HertzGameLoop(
        base_config=make_config(beatmap_path), stages=(stage,), renderer=NullRenderer(),
        input_provider=null_input, audio_engine=audio_engine, audio_clock=clock,
        player_progress_path=str(tmp_path / "player_progress.json"),
        player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
        user_settings_path=str(tmp_path / "user_settings.json"),
    )

    _goto_free_play_carousel(loop, null_input)
    frames_needed = int(loop._base_config.carousel_preview_hover_seconds / DT) + 2
    for _ in range(frames_needed):
        loop.advance_frame(DT)

    _track_id, start_offset, _fade_ms = audio_engine.preview_calls[0]
    assert start_offset == pytest.approx(100.0 * loop._base_config.carousel_preview_start_fraction)


# -- HBPygameRenderer: cache de miniaturas/fundo/paleta ----------------------


def _make_thumbnail_file(path, color, size=(64, 64)):
    surface = pygame.Surface(size)
    surface.fill(color)
    pygame.image.save(surface, str(path))
    return str(path)


def test_cache_carousel_visuals_builds_focused_and_neighbor_variants(tmp_path):
    thumbnail_path = _make_thumbnail_file(tmp_path / "cover.png", (200, 40, 40))
    stage = StageDef(
        stage_id="yt1", name="FASE", subtitle="", track_path="", beatmap_path="unused",
        synth=None, beatmap_params={}, overrides={}, selectable_mode=True, thumbnail_path=thumbnail_path,
    )
    renderer = HBPygameRenderer()
    renderer.initialize(320, 240, "test")
    renderer.cache_carousel_visuals((stage,))

    entry = renderer._thumbnail_cache["yt1"]
    assert entry["focused"].get_size() != entry["neighbor"].get_size()
    assert entry["background"].get_size() == (320, 240)
    assert renderer.thumbnail_average_color("yt1") != (255, 255, 255)
    assert renderer.thumbnail_average_color("nao_existe") == (255, 255, 255)
    assert renderer.thumbnail_background("nao_existe") is None


def test_cache_carousel_visuals_skips_stages_without_a_thumbnail(tmp_path):
    stage = StageDef(
        stage_id="curated", name="FASE", subtitle="", track_path="", beatmap_path="unused",
        synth=None, beatmap_params={}, overrides={},
    )
    renderer = HBPygameRenderer()
    renderer.initialize(320, 240, "test")
    renderer.cache_carousel_visuals((stage,))
    assert renderer._thumbnail_cache == {}


def test_cache_carousel_visuals_is_idempotent_for_an_already_cached_stage(tmp_path):
    thumbnail_path = _make_thumbnail_file(tmp_path / "cover.png", (10, 200, 10))
    stage = StageDef(
        stage_id="yt1", name="FASE", subtitle="", track_path="", beatmap_path="unused",
        synth=None, beatmap_params={}, overrides={}, selectable_mode=True, thumbnail_path=thumbnail_path,
    )
    renderer = HBPygameRenderer()
    renderer.initialize(320, 240, "test")
    renderer.cache_carousel_visuals((stage,))
    first_entry = renderer._thumbnail_cache["yt1"]
    renderer.cache_carousel_visuals((stage,))
    assert renderer._thumbnail_cache["yt1"] is first_entry  # nao recalculado


def test_draw_carousel_filmstrip_blits_the_focused_and_neighbor_surfaces(tmp_path):
    thumbnail_path = _make_thumbnail_file(tmp_path / "cover.png", (40, 40, 220))
    stage = StageDef(
        stage_id="yt1", name="FASE", subtitle="", track_path="", beatmap_path="unused",
        synth=None, beatmap_params={}, overrides={}, selectable_mode=True, thumbnail_path=thumbnail_path,
    )
    renderer = HBPygameRenderer()
    renderer.initialize(640, 480, "test")
    renderer.cache_carousel_visuals((stage,))
    renderer._overlay_carousel_neighbor_stage_ids = ("yt1",)

    height = renderer._draw_carousel_filmstrip(320, 10)
    assert height == renderer._thumbnail_cache["yt1"]["focused"].get_height()


def test_draw_carousel_filmstrip_is_a_no_op_without_any_neighbor_ids():
    renderer = HBPygameRenderer()
    renderer.initialize(320, 240, "test")
    assert renderer._draw_carousel_filmstrip(160, 10) == 0


# -- HBPygameAudioEngine.play_preview -----------------------------------------


def test_play_preview_uses_pygame_mixer_with_start_and_fade(tmp_path, monkeypatch):
    from hertzbeats.adapters.hb_pygame_audio_engine import HBPygameAudioEngine

    engine = HBPygameAudioEngine()
    calls = {}
    monkeypatch.setattr(pygame.mixer.music, "load", lambda path: calls.setdefault("load", path))
    monkeypatch.setattr(
        pygame.mixer.music, "play",
        lambda loops=0, start=0.0, fade_ms=0: calls.setdefault("play", (loops, start, fade_ms)),
    )
    engine.load_track("song", "fake/path.mp3")
    engine.play_preview("song", start_offset_seconds=12.5, fade_ms=750)

    assert calls["load"] == "fake/path.mp3"
    assert calls["play"] == (0, 12.5, 750)
