"""Pipeline de Importacao Direta (FLOW_DOWNLOAD_HUB): deteccao de Ctrl+V, tela dedicada em 2 etapas (Previa -> Download), thread persistente e tratamento de erros."""
import time

import pygame
import pytest

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from hertzbeats.adapters.hb_pygame_input_provider import HBPygameInputProvider
from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.adapters.texture_bank import build_and_register_overlay_surfaces
from hertzbeats.bootstrap.hertz_game_loop import (
    FLOW_CAROUSEL,
    FLOW_DOWNLOAD_HUB,
    FLOW_HUB,
    HUB_CATEGORIES,
    HertzGameLoop,
)
from hertzbeats.stages import StageDef
from hertzbeats.youtube_import import FFmpegNotFoundError, YoutubeImportError

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


# -- HertzGameLoop: HUB -> FLOW_DOWNLOAD_HUB, Previa -> Download -------------


class _FakeClipboard:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return self.text


def _fake_preview_fetcher(video_id="newsong123", title="Nova Musica", uploader="Canal Qualquer", raises=None):
    def _fetch(url, music_dir):
        if raises is not None:
            raise raises
        return {
            "video_id": video_id,
            "url": url,
            "preview_folder": f"{music_dir}/youtube/{video_id}",
            "title": title,
            "uploader": uploader,
            "duration_seconds": 42.0,
            "chapters": (),
            "thumbnail_path": None,
        }

    return _fetch


def _fake_song_downloader(video_id="newsong123", name="Nova Musica Importada", raises=None):
    def _download(preview, music_dir, beatmap_dir):
        if raises is not None:
            raise raises
        stage = StageDef(
            stage_id=f"youtube_{video_id}", name=name, subtitle="Canal Qualquer", track_path="",
            beatmap_path="unused", synth=None, beatmap_params={}, overrides={}, selectable_mode=True,
        )
        return video_id, (stage,)

    return _download


@pytest.fixture
def import_loop(tmp_path, null_input):
    def _make(
        clipboard_text="",
        preview_fetcher=None,
        song_downloader=None,
        existing_user_song=True,
        renderer=None,
    ):
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
            renderer=renderer if renderer is not None else NullRenderer(),
            input_provider=null_input,
            audio_engine=audio_engine,
            audio_clock=audio_engine.get_clock(),
            player_progress_path=str(tmp_path / "player_progress.json"),
            player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
            user_settings_path=str(tmp_path / "user_settings.json"),
            clipboard_reader=_FakeClipboard(clipboard_text),
            preview_fetcher=preview_fetcher or _fake_preview_fetcher(),
            song_downloader=song_downloader or _fake_song_downloader(),
        )
        return loop

    return _make


def _goto_download_hub(loop, null_input) -> None:
    _goto_hub(loop, null_input)
    target = HUB_CATEGORIES.index("download_music")
    while loop.hub_cursor != target:
        _press(loop, null_input, "menu_down")
    _press(loop, null_input, "confirm")  # HUB -> FLOW_DOWNLOAD_HUB


def _wait_for_worker_result(loop, timeout=2.0):
    """A thread de background e PERSISTENTE (`_download_worker_loop` roda
    `while True`, nunca termina sozinha) -- espera a MENSAGEM aparecer na
    fila de resultado (postada pelo worker) em vez de tentar `join()` a
    thread, entao drena UM frame pra `_poll_download_worker` aplicar o
    resultado ao estado (mesma leitura non-blocking do jogo real)."""
    deadline = time.monotonic() + timeout
    while loop._download_result_queue.empty():
        if time.monotonic() >= deadline:
            raise AssertionError("worker de download nao produziu um resultado a tempo")
        time.sleep(0.01)
    loop.advance_frame(DT)


def test_download_music_category_reaches_the_dedicated_screen(import_loop, null_input):
    loop = import_loop()
    _goto_download_hub(loop, null_input)
    assert loop.flow == FLOW_DOWNLOAD_HUB
    assert loop._download_stage == "waiting"


def test_esc_from_waiting_returns_to_the_hub(import_loop, null_input):
    loop = import_loop()
    _goto_download_hub(loop, null_input)
    _press(loop, null_input, "pause")
    assert loop.flow == FLOW_HUB


def test_pasting_text_without_a_youtube_url_shows_a_notice_and_starts_no_thread(import_loop, null_input):
    loop = import_loop(clipboard_text="isso nao e uma URL do youtube")
    _goto_download_hub(loop, null_input)
    _press(loop, null_input, "paste")

    assert loop.flow == FLOW_DOWNLOAD_HUB
    assert loop._download_stage == "waiting"
    assert loop._notice_key == "invalid_url_notice"
    assert loop._download_worker_thread is None


def test_pasting_a_valid_url_enters_fetching_preview_and_starts_the_worker(import_loop, null_input):
    loop = import_loop(clipboard_text="https://youtu.be/newsong123")
    _goto_download_hub(loop, null_input)
    _press(loop, null_input, "paste")

    assert loop._download_stage == "fetching_preview"
    assert loop._download_worker_thread is not None
    _wait_for_worker_result(loop)


def test_a_successful_preview_transitions_to_preview_ready_and_notifies_the_renderer(import_loop, null_input):
    calls = []

    class _RecordingRenderer(NullRenderer):
        def set_download_preview(self, title, uploader, thumbnail_path):
            calls.append((title, uploader, thumbnail_path))

    loop = import_loop(
        clipboard_text="https://youtu.be/newsong123",
        preview_fetcher=_fake_preview_fetcher(video_id="newsong123", title="Nova Musica", uploader="Canal X"),
        renderer=_RecordingRenderer(),
    )
    _goto_download_hub(loop, null_input)
    _press(loop, null_input, "paste")
    _wait_for_worker_result(loop)  # drena a fila -- resultado ja esta pronto

    assert loop.flow == FLOW_DOWNLOAD_HUB
    assert loop._download_stage == "preview_ready"
    assert loop._download_preview["title"] == "Nova Musica"
    assert calls == [("Nova Musica", "Canal X", None)]


def test_enter_from_preview_ready_starts_the_download_stage(import_loop, null_input):
    loop = import_loop(clipboard_text="https://youtu.be/newsong123")
    _goto_download_hub(loop, null_input)
    _press(loop, null_input, "paste")
    _wait_for_worker_result(loop)
    assert loop._download_stage == "preview_ready"

    _press(loop, null_input, "confirm")
    assert loop._download_stage == "downloading"
    _wait_for_worker_result(loop)


def test_a_successful_download_merges_the_catalog_and_enter_navigates_to_the_new_song(import_loop, null_input):
    loop = import_loop(
        clipboard_text="https://youtu.be/newsong123",
        song_downloader=_fake_song_downloader(video_id="newsong123", name="Nova Musica Importada"),
    )
    _goto_download_hub(loop, null_input)
    _press(loop, null_input, "paste")
    _wait_for_worker_result(loop)
    _press(loop, null_input, "confirm")
    _wait_for_worker_result(loop)  # drena o resultado do download

    assert loop._download_stage == "success"
    assert loop.flow == FLOW_DOWNLOAD_HUB

    _press(loop, null_input, "confirm")
    assert loop.flow == FLOW_CAROUSEL
    assert loop.carousel_category == "free_play"

    focused_index = loop.carousel_focused_stage_index()
    assert loop._stages[focused_index].stage_id == "youtube_newsong123"
    assert loop._stages[focused_index].name == "Nova Musica Importada"

    stage_ids = {s.stage_id for s in loop._stages}
    assert stage_ids == {"stage0", "user_local_song", "youtube_newsong123"}


def test_esc_from_success_returns_to_the_hub_without_navigating(import_loop, null_input):
    loop = import_loop(clipboard_text="https://youtu.be/newsong123")
    _goto_download_hub(loop, null_input)
    _press(loop, null_input, "paste")
    _wait_for_worker_result(loop)
    _press(loop, null_input, "confirm")
    _wait_for_worker_result(loop)
    assert loop._download_stage == "success"

    _press(loop, null_input, "pause")
    assert loop.flow == FLOW_HUB


def test_esc_from_preview_ready_cancels_and_removes_the_partial_folder(import_loop, null_input, tmp_path):
    preview_folder = tmp_path / "musicas" / "youtube" / "newsong123"

    def _fetch(url, music_dir):
        preview_folder.mkdir(parents=True, exist_ok=True)
        (preview_folder / "preview.jpg").write_bytes(b"fake")
        return {
            "video_id": "newsong123", "url": url, "preview_folder": str(preview_folder),
            "title": "T", "uploader": "U", "duration_seconds": None, "chapters": (), "thumbnail_path": None,
        }

    loop = import_loop(clipboard_text="https://youtu.be/newsong123", preview_fetcher=_fetch)
    _goto_download_hub(loop, null_input)
    _press(loop, null_input, "paste")
    _wait_for_worker_result(loop)
    assert loop._download_stage == "preview_ready"
    assert preview_folder.exists()

    _press(loop, null_input, "pause")
    assert loop._download_stage == "waiting"
    assert loop._download_preview is None
    assert not preview_folder.exists()


def test_a_failed_preview_transitions_to_error_and_notifies_the_renderer(import_loop, null_input):
    calls = []

    class _RecordingRenderer(NullRenderer):
        def set_download_error(self, message):
            calls.append(message)

    loop = import_loop(
        clipboard_text="https://youtu.be/badlink",
        preview_fetcher=_fake_preview_fetcher(raises=YoutubeImportError("video privado")),
        renderer=_RecordingRenderer(),
    )
    _goto_download_hub(loop, null_input)
    _press(loop, null_input, "paste")
    _wait_for_worker_result(loop)

    assert loop.flow == FLOW_DOWNLOAD_HUB
    assert loop._download_stage == "error"
    assert loop._download_error_message == "video privado"
    assert calls == ["video privado"]


def test_a_failed_download_transitions_to_error_including_ffmpeg_missing(import_loop, null_input):
    loop = import_loop(
        clipboard_text="https://youtu.be/newsong123",
        song_downloader=_fake_song_downloader(raises=FFmpegNotFoundError("FFmpeg nao encontrado no sistema")),
    )
    _goto_download_hub(loop, null_input)
    _press(loop, null_input, "paste")
    _wait_for_worker_result(loop)
    _press(loop, null_input, "confirm")
    _wait_for_worker_result(loop)

    assert loop._download_stage == "error"
    assert loop._download_error_message == "FFmpeg nao encontrado no sistema"


def test_enter_or_esc_from_error_returns_to_waiting_for_a_retry(import_loop, null_input):
    loop = import_loop(
        clipboard_text="https://youtu.be/badlink",
        preview_fetcher=_fake_preview_fetcher(raises=RuntimeError("falha de rede")),
    )
    _goto_download_hub(loop, null_input)
    _press(loop, null_input, "paste")
    _wait_for_worker_result(loop)
    assert loop._download_stage == "error"

    _press(loop, null_input, "confirm")
    assert loop._download_stage == "waiting"
    assert loop._download_error_message is None


def test_fetching_preview_and_downloading_ignore_esc(import_loop, null_input):
    """FETCHING_PREVIEW/DOWNLOADING sao NAO-cancelaveis -- ESC nao deve
    fazer o fluxo sair de FLOW_DOWNLOAD_HUB nem mudar o sub-estado
    enquanto a thread ainda nao respondeu (usa um preview_fetcher que
    bloqueia ate um evento ser liberado, simulando I/O em andamento)."""
    import threading

    release = threading.Event()

    def _blocking_fetch(url, music_dir):
        release.wait(timeout=2.0)
        return {
            "video_id": "newsong123", "url": url, "preview_folder": f"{music_dir}/youtube/newsong123",
            "title": "T", "uploader": "U", "duration_seconds": None, "chapters": (), "thumbnail_path": None,
        }

    loop = import_loop(clipboard_text="https://youtu.be/newsong123", preview_fetcher=_blocking_fetch)
    _goto_download_hub(loop, null_input)
    _press(loop, null_input, "paste")
    assert loop._download_stage == "fetching_preview"

    _press(loop, null_input, "pause")  # ESC nao cancela um estado nao-cancelavel
    assert loop.flow == FLOW_DOWNLOAD_HUB
    assert loop._download_stage == "fetching_preview"

    release.set()
    _wait_for_worker_result(loop)
    assert loop._download_stage == "preview_ready"


def test_reentering_the_download_hub_resets_to_waiting(import_loop, null_input):
    loop = import_loop(clipboard_text="https://youtu.be/newsong123")
    _goto_download_hub(loop, null_input)
    _press(loop, null_input, "paste")
    _wait_for_worker_result(loop)
    assert loop._download_stage == "preview_ready"

    _press(loop, null_input, "pause")  # cancela -> WAITING
    _press(loop, null_input, "pause")  # WAITING -> HUB
    assert loop.flow == FLOW_HUB

    _goto_download_hub(loop, null_input)
    assert loop._download_stage == "waiting"
    assert loop._download_preview is None


# -- Renderer: overlay "download_hub" + textos fixos -------------------------


def test_download_hub_overlay_textures_are_registered():
    stage = StageDef(
        stage_id="s", name="FASE", subtitle="", track_path="", beatmap_path="unused",
        synth=None, beatmap_params={}, overrides={},
    )
    renderer = HBPygameRenderer()
    renderer.initialize(320, 240, "test")
    build_and_register_overlay_surfaces(renderer, (stage,))
    for key in (
        "download_hub_title",
        "download_hub_waiting",
        "download_hub_fetching_preview",
        "download_hub_downloading",
        "download_hub_success",
        "download_hub_error_title",
        "hint_download_hub_waiting",
        "hint_download_hub_confirm",
        "hint_download_hub_back",
        "invalid_url_notice",
    ):
        assert renderer._overlay_surfaces.get(key) is not None, key


@pytest.mark.parametrize(
    "stage", ["waiting", "fetching_preview", "preview_ready", "downloading", "success", "error"],
)
def test_draw_overlay_handles_every_download_hub_stage_without_crashing(stage):
    game_stage = StageDef(
        stage_id="s", name="FASE", subtitle="", track_path="", beatmap_path="unused",
        synth=None, beatmap_params={}, overrides={},
    )
    renderer = HBPygameRenderer()
    renderer.initialize(320, 240, "test")
    build_and_register_overlay_surfaces(renderer, (game_stage,))
    if stage == "preview_ready":
        renderer.set_download_preview("Titulo", "Canal", None)
    elif stage == "error":
        renderer.set_download_error("Falha qualquer")
    renderer.set_overlay("download_hub", download_stage=stage)
    renderer._draw_overlay()  # nao deve levantar
