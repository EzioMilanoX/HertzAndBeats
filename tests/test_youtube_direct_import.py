"""Pipeline de Importacao Direta (Ctrl+V): deteccao de tecla, thread de background, FLOW_IMPORTING e volta ao Carrossel na musica nova."""
import pygame
import pytest

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from hertzbeats.adapters.hb_pygame_input_provider import HBPygameInputProvider
from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.adapters.texture_bank import build_and_register_overlay_surfaces
from hertzbeats.bootstrap.hertz_game_loop import FLOW_CAROUSEL, FLOW_IMPORTING, HertzGameLoop
from hertzbeats.stages import StageDef

from tests.conftest import make_config, write_beatmap
from tests.test_match_flow import DT, _basic, _goto_hub, _press


# -- HBPygameInputProvider: deteccao de Ctrl+V -------------------------------


def test_ctrl_v_sets_the_paste_action(monkeypatch):
    if not pygame.get_init():
        pygame.init()
    provider = HBPygameInputProvider()
    provider.load_bindings("data/input_bindings/default_keyboard.json")

    class _FakeKeys:
        def __init__(self, held):
            self._held = held

        def __getitem__(self, code):
            return self._held.get(code, False)

    monkeypatch.setattr(pygame.event, "get", lambda: [])
    monkeypatch.setattr(pygame.mouse, "get_pressed", lambda: (False, False, False))
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: (0, 0))
    monkeypatch.setattr(pygame.mouse, "get_rel", lambda: (0, 0))
    monkeypatch.setattr(
        pygame.key, "get_pressed", lambda: _FakeKeys({pygame.K_v: True, pygame.K_LCTRL: True}),
    )
    provider.poll()
    assert provider.is_action_pressed("paste") is True


def test_v_alone_without_control_does_not_set_paste(monkeypatch):
    if not pygame.get_init():
        pygame.init()
    provider = HBPygameInputProvider()
    provider.load_bindings("data/input_bindings/default_keyboard.json")

    class _FakeKeys:
        def __init__(self, held):
            self._held = held

        def __getitem__(self, code):
            return self._held.get(code, False)

    monkeypatch.setattr(pygame.event, "get", lambda: [])
    monkeypatch.setattr(pygame.mouse, "get_pressed", lambda: (False, False, False))
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: (0, 0))
    monkeypatch.setattr(pygame.mouse, "get_rel", lambda: (0, 0))
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: _FakeKeys({pygame.K_v: True}))
    provider.poll()
    assert provider.is_action_pressed("paste") is False


# -- HertzGameLoop: fio completo do Ctrl+V ao catalogo atualizado ------------


class _FakeClipboard:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return self.text


def _fake_importer_factory(video_id="newsong", name="Nova Musica", raises=None):
    def _importer(url, music_dir, beatmap_dir):
        if raises is not None:
            raise raises
        stage = StageDef(
            stage_id=f"youtube_{video_id}", name=name, subtitle="Canal Qualquer", track_path="",
            beatmap_path="unused", synth=None, beatmap_params={}, overrides={}, selectable_mode=True,
        )
        return video_id, (stage,)

    return _importer


@pytest.fixture
def import_loop(tmp_path, null_input):
    def _make(clipboard_text, youtube_importer, existing_user_song=True):
        stage_threats = [[_basic(3.0)]]
        beatmap_path = write_beatmap(tmp_path / "stage0.beatmap.json", stage_threats[0])
        stages = [
            StageDef(
                stage_id="stage0", name="FASE CURADA", subtitle="", track_path=str(tmp_path / "stage0.wav"),
                beatmap_path=str(beatmap_path), synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
            ),
        ]
        if existing_user_song:
            stages.append(
                StageDef(
                    stage_id="user_local_song", name="MINHA MUSICA", subtitle="", track_path="",
                    beatmap_path=str(beatmap_path), synth={"bpm": 120.0, "bars": 1}, beatmap_params={},
                    overrides={}, selectable_mode=True,
                )
            )
        audio_engine = NullAudioEngine()
        loop = HertzGameLoop(
            base_config=make_config(beatmap_path),
            stages=tuple(stages),
            renderer=NullRenderer(),
            input_provider=null_input,
            audio_engine=audio_engine,
            audio_clock=audio_engine.get_clock(),
            player_progress_path=str(tmp_path / "player_progress.json"),
            player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
            user_settings_path=str(tmp_path / "user_settings.json"),
            clipboard_reader=_FakeClipboard(clipboard_text),
            youtube_importer=youtube_importer,
        )
        return loop

    return _make


def _goto_free_play_carousel(loop, null_input):
    _goto_hub(loop, null_input)
    _press(loop, null_input, "menu_down")  # HUB cursor -> "free_play"
    _press(loop, null_input, "confirm")


def test_pasting_text_without_a_youtube_url_is_a_no_op(import_loop, null_input):
    loop = import_loop("isso nao e uma URL do youtube", _fake_importer_factory())
    _goto_free_play_carousel(loop, null_input)
    _press(loop, null_input, "paste")
    assert loop.flow == FLOW_CAROUSEL


def test_pasting_a_youtube_url_enters_the_importing_flow_and_starts_a_thread(import_loop, null_input):
    loop = import_loop("https://youtu.be/newsong123", _fake_importer_factory(video_id="newsong123"))
    _goto_free_play_carousel(loop, null_input)
    _press(loop, null_input, "paste")

    assert loop.flow == FLOW_IMPORTING
    assert loop._import_thread is not None
    loop._import_thread.join(timeout=2.0)
    assert not loop._import_thread.is_alive()


def test_a_successful_import_returns_to_the_carousel_pointing_at_the_new_song(import_loop, null_input):
    loop = import_loop(
        "https://youtu.be/newsong123",
        _fake_importer_factory(video_id="newsong123", name="Nova Musica Importada"),
    )
    _goto_free_play_carousel(loop, null_input)
    _press(loop, null_input, "paste")
    assert loop.flow == FLOW_IMPORTING
    loop._import_thread.join(timeout=2.0)

    loop.advance_frame(DT)  # drena a fila (o resultado ja esta pronto)
    assert loop.flow == FLOW_CAROUSEL
    assert loop.carousel_category == "free_play"

    focused_index = loop.carousel_focused_stage_index()
    assert loop._stages[focused_index].stage_id == "youtube_newsong123"
    assert loop._stages[focused_index].name == "Nova Musica Importada"


def test_a_successful_import_preserves_curated_and_other_user_songs(import_loop, null_input):
    loop = import_loop("https://youtu.be/newsong123", _fake_importer_factory(video_id="newsong123"))
    _goto_free_play_carousel(loop, null_input)
    _press(loop, null_input, "paste")
    loop._import_thread.join(timeout=2.0)
    loop.advance_frame(DT)

    stage_ids = {s.stage_id for s in loop._stages}
    assert stage_ids == {"stage0", "user_local_song", "youtube_newsong123"}


def test_a_failed_import_shows_a_notice_and_returns_to_the_carousel(import_loop, null_input):
    loop = import_loop("https://youtu.be/badlink", _fake_importer_factory(raises=RuntimeError("video privado")))
    _goto_free_play_carousel(loop, null_input)
    _press(loop, null_input, "paste")
    assert loop.flow == FLOW_IMPORTING
    loop._import_thread.join(timeout=2.0)

    loop.advance_frame(DT)
    assert loop.flow == FLOW_CAROUSEL
    assert loop._notice_key == "import_failed"


def test_re_importing_the_same_video_replaces_it_instead_of_duplicating(import_loop, null_input):
    loop = import_loop("https://youtu.be/newsong123", _fake_importer_factory(video_id="newsong123", name="V1"))
    _goto_free_play_carousel(loop, null_input)
    _press(loop, null_input, "paste")
    loop._import_thread.join(timeout=2.0)
    loop.advance_frame(DT)
    assert sum(1 for s in loop._stages if s.stage_id == "youtube_newsong123") == 1

    loop._youtube_importer = _fake_importer_factory(video_id="newsong123", name="V2")
    _press(loop, null_input, "paste")
    loop._import_thread.join(timeout=2.0)
    loop.advance_frame(DT)

    matching = [s for s in loop._stages if s.stage_id == "youtube_newsong123"]
    assert len(matching) == 1
    assert matching[0].name == "V2"


# -- Renderer: overlay "importing" + notice de falha -------------------------


def test_importing_overlay_textures_are_registered():
    stage = StageDef(
        stage_id="s", name="FASE", subtitle="", track_path="", beatmap_path="unused",
        synth=None, beatmap_params={}, overrides={},
    )
    renderer = HBPygameRenderer()
    renderer.initialize(320, 240, "test")
    build_and_register_overlay_surfaces(renderer, (stage,))
    assert renderer._overlay_surfaces.get("importing_title") is not None
    assert renderer._overlay_surfaces.get("hint_importing") is not None
    assert renderer._overlay_surfaces.get("import_failed") is not None


def test_draw_overlay_handles_the_importing_mode_without_crashing():
    stage = StageDef(
        stage_id="s", name="FASE", subtitle="", track_path="", beatmap_path="unused",
        synth=None, beatmap_params={}, overrides={},
    )
    renderer = HBPygameRenderer()
    renderer.initialize(320, 240, "test")
    build_and_register_overlay_surfaces(renderer, (stage,))
    renderer.set_overlay("importing")
    renderer._draw_overlay()  # nao deve levantar
