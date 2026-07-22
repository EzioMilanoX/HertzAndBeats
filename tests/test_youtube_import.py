"""Pipeline de Importacao Direta: deteccao de URL, Previa (Etapa 1) e Download (Etapa 2) via yt-dlp (subprocess FAKE, nunca rede de verdade)."""
import json
from pathlib import Path

import pytest

from hertzbeats.music_library import parse_youtube_metadata, scan_user_songs, scan_youtube_songs
from hertzbeats.youtube_import import (
    FFmpegNotFoundError,
    YoutubeImportError,
    YtDlpNotFoundError,
    download_and_analyze_youtube_song,
    extract_video_id,
    extract_youtube_url,
    fetch_youtube_preview,
    ffmpeg_available,
    resolve_yt_dlp_command,
    yt_dlp_available,
)


# -- extract_youtube_url / extract_video_id (puras, sem rede) ---------------


@pytest.mark.parametrize(
    "text,expected_id",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("http://youtube.com/watch?v=dQw4w9WgXcQ&list=PL123", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?t=30", "dQw4w9WgXcQ"),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("olha essa musica: youtube.com/watch?v=dQw4w9WgXcQ demais", "dQw4w9WgXcQ"),
    ],
)
def test_extract_youtube_url_recognizes_common_formats(text, expected_id):
    url = extract_youtube_url(text)
    assert url is not None
    assert url.startswith(("http://", "https://"))
    assert extract_video_id(url) == expected_id


def test_extract_youtube_url_normalizes_a_schemeless_link():
    url = extract_youtube_url("youtube.com/watch?v=dQw4w9WgXcQ")
    assert url == "https://youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.parametrize("text", ["", "nada aqui", "https://vimeo.com/12345", "http://example.com"])
def test_extract_youtube_url_returns_none_without_a_match(text):
    assert extract_youtube_url(text) is None
    assert extract_video_id(text) is None


def test_extract_video_id_returns_none_for_a_non_youtube_url():
    assert extract_video_id("https://vimeo.com/12345") is None


# -- ffmpeg_available (injetavel, nunca toca o sistema de verdade) ----------


def test_ffmpeg_available_reflects_which_fn_result():
    assert ffmpeg_available(which_fn=lambda name: "/usr/bin/ffmpeg") is True
    assert ffmpeg_available(which_fn=lambda name: None) is False


def test_yt_dlp_available_reflects_which_fn_result():
    assert yt_dlp_available(which_fn=lambda name: "/usr/bin/yt-dlp") is True
    assert yt_dlp_available(which_fn=lambda name: None) is False


# -- resolve_yt_dlp_command (executavel no PATH > fallback "python -m yt_dlp") --


def test_resolve_yt_dlp_command_prefers_the_path_executable():
    command = resolve_yt_dlp_command(
        which_fn=lambda name: "/usr/bin/yt-dlp",
        module_finder=lambda name: object(),  # nem chega a ser consultado
        python_executable="/usr/bin/python3",
    )
    assert command == ["/usr/bin/yt-dlp"]


def test_resolve_yt_dlp_command_falls_back_to_python_dash_m_when_only_the_package_is_installed():
    """Caso real: `pip install yt-dlp` (ou `--user`) instala o PACOTE,
    mas o script de entrada (`yt-dlp.exe`/`yt-dlp`) pode acabar numa
    pasta fora do PATH -- `shutil.which` corretamente nao acha nada,
    mas o pacote esta la, entao `python -m yt_dlp` funciona (nao
    depende do PATH, so' do pacote ser importavel no MESMO
    interprete)."""
    command = resolve_yt_dlp_command(
        which_fn=lambda name: None,
        module_finder=lambda name: object(),
        python_executable="/usr/bin/python3",
    )
    assert command == ["/usr/bin/python3", "-m", "yt_dlp"]


def test_resolve_yt_dlp_command_returns_none_when_neither_is_available():
    command = resolve_yt_dlp_command(which_fn=lambda name: None, module_finder=lambda name: None)
    assert command is None


# -- fetch_youtube_preview (ETAPA 1 -- subprocess FAKE, nunca rede) ----------


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_fetch_youtube_preview_rejects_an_unrecognized_url(tmp_path):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return _FakeCompletedProcess(0)

    with pytest.raises(YoutubeImportError):
        fetch_youtube_preview("https://vimeo.com/12345", music_dir=str(tmp_path), run_subprocess=fake_run)
    assert calls == []  # nunca chega a chamar o subprocess com uma URL invalida


def test_fetch_youtube_preview_raises_yt_dlp_not_found_before_touching_the_subprocess(tmp_path):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return _FakeCompletedProcess(0)

    with pytest.raises(YtDlpNotFoundError):
        fetch_youtube_preview(
            "https://youtu.be/dQw4w9WgXcQ", music_dir=str(tmp_path),
            run_subprocess=fake_run, yt_dlp_command_resolver=lambda: None,
        )
    assert calls == []  # nunca chega a chamar o subprocess sem yt-dlp


def test_fetch_youtube_preview_spreads_a_multi_token_command_prefix(tmp_path):
    """Caso real (Windows, `pip install --user yt-dlp`): so' o pacote
    esta instalado, sem o executavel no PATH -- `resolve_yt_dlp_command`
    resolve pra `[python, "-m", "yt_dlp"]` (3 tokens), que precisa virar
    os 3 PRIMEIROS elementos do comando do subprocess, nao um unico
    argumento colado."""
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return _FakeCompletedProcess(0, stdout=json.dumps({"title": "T", "uploader": "U"}))

    fetch_youtube_preview(
        "https://youtu.be/dQw4w9WgXcQ", music_dir=str(tmp_path), run_subprocess=fake_run,
        yt_dlp_command_resolver=lambda: ["/usr/bin/python3", "-m", "yt_dlp"],
    )

    command = captured["command"]
    assert command[:3] == ["/usr/bin/python3", "-m", "yt_dlp"]
    assert "--dump-json" in command


def test_fetch_youtube_preview_builds_a_skip_download_command(tmp_path):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return _FakeCompletedProcess(0, stdout=json.dumps({"title": "T", "uploader": "U"}))

    fetch_youtube_preview(
        "https://youtu.be/dQw4w9WgXcQ", music_dir=str(tmp_path), run_subprocess=fake_run,
        yt_dlp_command_resolver=lambda: ["yt-dlp"],
    )

    command = captured["command"]
    assert command[0] == "yt-dlp"
    assert "--dump-json" in command
    assert "--skip-download" in command  # ETAPA 1 NUNCA baixa audio
    assert "--extract-audio" not in command
    assert "https://youtu.be/dQw4w9WgXcQ" in command
    assert captured["kwargs"]["capture_output"] is True


def test_fetch_youtube_preview_parses_metadata_and_locates_the_thumbnail(tmp_path):
    def fake_run(command, **kwargs):
        output_index = command.index("-o") + 1
        folder = Path(command[output_index]).parent
        (folder / "preview.jpg").write_bytes(b"fake jpg")
        metadata = {
            "title": "Cool Song",
            "uploader": "Cool Channel",
            "duration": 187.5,
            "chapters": [{"start_time": 85.0, "title": "Drop"}],
        }
        return _FakeCompletedProcess(0, stdout=json.dumps(metadata))

    preview = fetch_youtube_preview(
        "https://youtu.be/dQw4w9WgXcQ", music_dir=str(tmp_path), run_subprocess=fake_run,
        yt_dlp_command_resolver=lambda: ["yt-dlp"],
    )
    assert preview["video_id"] == "dQw4w9WgXcQ"
    assert preview["url"] == "https://youtu.be/dQw4w9WgXcQ"
    assert preview["title"] == "Cool Song"
    assert preview["uploader"] == "Cool Channel"
    assert preview["duration_seconds"] == pytest.approx(187.5)
    assert preview["chapters"] == ({"start_time_seconds": 85.0, "title": "Drop"},)
    assert preview["thumbnail_path"] == str(Path(tmp_path) / "youtube" / "dQw4w9WgXcQ" / "preview.jpg")


def test_fetch_youtube_preview_thumbnail_is_none_when_not_written(tmp_path):
    def fake_run(command, **kwargs):
        return _FakeCompletedProcess(0, stdout=json.dumps({"title": "T", "uploader": "U"}))

    preview = fetch_youtube_preview(
        "https://youtu.be/dQw4w9WgXcQ", music_dir=str(tmp_path), run_subprocess=fake_run,
        yt_dlp_command_resolver=lambda: ["yt-dlp"],
    )
    assert preview["thumbnail_path"] is None


def test_fetch_youtube_preview_raises_on_a_nonzero_exit_code(tmp_path):
    def failing_run(*args, **kwargs):
        return _FakeCompletedProcess(1, stderr="ERROR: video unavailable")

    with pytest.raises(YoutubeImportError, match="video unavailable"):
        fetch_youtube_preview(
            "https://youtu.be/dQw4w9WgXcQ", music_dir=str(tmp_path), run_subprocess=failing_run,
            yt_dlp_command_resolver=lambda: ["yt-dlp"],
        )


def test_fetch_youtube_preview_raises_on_invalid_json(tmp_path):
    def fake_run(*args, **kwargs):
        return _FakeCompletedProcess(0, stdout="isso nao e um json")

    with pytest.raises(YoutubeImportError):
        fetch_youtube_preview(
            "https://youtu.be/dQw4w9WgXcQ", music_dir=str(tmp_path), run_subprocess=fake_run,
            yt_dlp_command_resolver=lambda: ["yt-dlp"],
        )


def test_fetch_youtube_preview_falls_back_to_channel_field(tmp_path):
    def fake_run(*args, **kwargs):
        return _FakeCompletedProcess(0, stdout=json.dumps({"title": "T", "channel": "Canal Via Channel"}))

    preview = fetch_youtube_preview(
        "https://youtu.be/dQw4w9WgXcQ", music_dir=str(tmp_path), run_subprocess=fake_run,
        yt_dlp_command_resolver=lambda: ["yt-dlp"],
    )
    assert preview["uploader"] == "Canal Via Channel"


# -- download_and_analyze_youtube_song (ETAPA 2) -----------------------------


def _make_preview(tmp_path, video_id="newsong123", with_thumbnail=True):
    folder = tmp_path / "musicas" / "youtube" / video_id
    folder.mkdir(parents=True)
    if with_thumbnail:
        (folder / "preview.jpg").write_bytes(b"fake preview jpg")
    return {
        "video_id": video_id,
        "url": f"https://youtu.be/{video_id}",
        "preview_folder": str(folder),
        "title": "Brand New Song",
        "uploader": "Someone",
        "duration_seconds": 99.0,
        "chapters": (),
        "thumbnail_path": str(folder / "preview.jpg") if with_thumbnail else None,
    }


def _fake_analyzer(audio_path, beatmap_path, track_id):
    beatmap_path.parent.mkdir(parents=True, exist_ok=True)
    beatmap_path.write_text(
        json.dumps({"bpm": 120.0, "threats": [{"timestamp_seconds": 1.0}], "mapper_version": 1}),
        encoding="utf-8",
    )


def test_download_and_analyze_raises_yt_dlp_not_found_before_touching_the_subprocess(tmp_path):
    preview = _make_preview(tmp_path)
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return _FakeCompletedProcess(0)

    with pytest.raises(YtDlpNotFoundError):
        download_and_analyze_youtube_song(
            preview,
            music_dir=str(tmp_path / "musicas"),
            beatmap_dir=str(tmp_path / "beatmaps"),
            run_subprocess=fake_run,
            yt_dlp_command_resolver=lambda: None,
            ffmpeg_checker=lambda: True,
            analyzer=_fake_analyzer,
        )
    assert calls == []  # nunca chega a chamar o subprocess sem yt-dlp


def test_download_and_analyze_raises_ffmpeg_not_found_before_touching_the_subprocess(tmp_path):
    preview = _make_preview(tmp_path)
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return _FakeCompletedProcess(0)

    with pytest.raises(FFmpegNotFoundError):
        download_and_analyze_youtube_song(
            preview,
            music_dir=str(tmp_path / "musicas"),
            beatmap_dir=str(tmp_path / "beatmaps"),
            run_subprocess=fake_run,
            yt_dlp_command_resolver=lambda: ["yt-dlp"],
            ffmpeg_checker=lambda: False,
            analyzer=_fake_analyzer,
        )
    assert calls == []  # nunca chega a chamar yt-dlp sem ffmpeg


def test_download_and_analyze_builds_an_extract_audio_command_reusing_the_preview_folder(tmp_path):
    preview = _make_preview(tmp_path)
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        output_index = command.index("-o") + 1
        folder = Path(command[output_index]).parent
        (folder / "audio.mp3").write_bytes(b"fake audio")
        (folder / "audio.info.json").write_text(json.dumps({"title": "Brand New Song"}), encoding="utf-8")
        return _FakeCompletedProcess(0)

    download_and_analyze_youtube_song(
        preview,
        music_dir=str(tmp_path / "musicas"),
        beatmap_dir=str(tmp_path / "beatmaps"),
        run_subprocess=fake_run,
        yt_dlp_command_resolver=lambda: ["yt-dlp"],
        ffmpeg_checker=lambda: True,
        analyzer=_fake_analyzer,
    )
    command = captured["command"]
    assert "--extract-audio" in command
    assert "--write-thumbnail" not in command  # reusa a miniatura da Previa, nao busca de novo
    output_index = command.index("-o") + 1
    assert Path(command[output_index]).parent == Path(preview["preview_folder"])


def test_download_and_analyze_renames_files_and_reuses_the_preview_thumbnail_as_cover(tmp_path):
    preview = _make_preview(tmp_path)
    folder = Path(preview["preview_folder"])

    def fake_run(command, **kwargs):
        (folder / "audio.mp3").write_bytes(b"fake audio")
        (folder / "audio.info.json").write_text(json.dumps({"title": "Brand New Song"}), encoding="utf-8")
        return _FakeCompletedProcess(0)

    video_id, stages = download_and_analyze_youtube_song(
        preview,
        music_dir=str(tmp_path / "musicas"),
        beatmap_dir=str(tmp_path / "beatmaps"),
        run_subprocess=fake_run,
        yt_dlp_command_resolver=lambda: ["yt-dlp"],
        ffmpeg_checker=lambda: True,
        analyzer=_fake_analyzer,
    )
    assert video_id == "newsong123"
    assert (folder / "metadata.json").exists()
    assert not (folder / "audio.info.json").exists()
    assert (folder / "cover.jpg").exists()
    assert not (folder / "preview.jpg").exists()
    assert len(stages) == 1
    assert stages[0].stage_id == "youtube_newsong123"
    assert stages[0].name == "Brand New Song"


def test_download_and_analyze_raises_on_a_nonzero_exit_code(tmp_path):
    preview = _make_preview(tmp_path)

    def failing_run(*args, **kwargs):
        return _FakeCompletedProcess(1, stderr="ERROR: video unavailable")

    with pytest.raises(YoutubeImportError, match="video unavailable"):
        download_and_analyze_youtube_song(
            preview,
            music_dir=str(tmp_path / "musicas"),
            beatmap_dir=str(tmp_path / "beatmaps"),
            run_subprocess=failing_run,
            yt_dlp_command_resolver=lambda: ["yt-dlp"],
            ffmpeg_checker=lambda: True,
            analyzer=_fake_analyzer,
        )


# -- parse_youtube_metadata ---------------------------------------------------


def test_parse_youtube_metadata_normalizes_chapters(tmp_path):
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "title": "Cool Song",
                "uploader": "Cool Channel",
                "duration": 187.5,
                "chapters": [
                    {"start_time": 0, "title": "Intro"},
                    {"start_time": 85.0, "title": "Drop"},
                ],
            }
        ),
        encoding="utf-8",
    )
    metadata = parse_youtube_metadata(metadata_path)
    assert metadata["title"] == "Cool Song"
    assert metadata["uploader"] == "Cool Channel"
    assert metadata["duration_seconds"] == pytest.approx(187.5)
    assert metadata["chapters"] == (
        {"start_time_seconds": 0.0, "title": "Intro"},
        {"start_time_seconds": 85.0, "title": "Drop"},
    )


def test_parse_youtube_metadata_falls_back_gracefully_on_missing_fields(tmp_path):
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps({}), encoding="utf-8")
    metadata = parse_youtube_metadata(metadata_path)
    assert metadata == {"title": "", "uploader": "", "duration_seconds": None, "chapters": ()}


# -- scan_youtube_songs / scan_user_songs (com um analyzer FAKE, sem librosa) --


def _make_youtube_song_folder(music_dir, video_id: str, with_metadata: bool = True, with_thumbnail: bool = True):
    folder = music_dir / "youtube" / video_id
    folder.mkdir(parents=True)
    (folder / "audio.mp3").write_bytes(b"fake audio")
    if with_metadata:
        (folder / "metadata.json").write_text(
            json.dumps(
                {
                    "title": "Imported Song",
                    "uploader": "Imported Channel",
                    "duration": 42.0,
                    "chapters": [{"start_time": 10.0, "title": "Drop"}],
                }
            ),
            encoding="utf-8",
        )
    if with_thumbnail:
        (folder / "cover.jpg").write_bytes(b"fake jpg")
    return folder


def test_scan_youtube_songs_builds_a_stage_with_real_metadata(tmp_path):
    music_dir = tmp_path / "musicas"
    _make_youtube_song_folder(music_dir, "abc123XYZ_-")
    beatmap_dir = tmp_path / "beatmaps"

    stages = scan_youtube_songs(str(music_dir), str(beatmap_dir), analyzer=_fake_analyzer)
    assert len(stages) == 1
    stage = stages[0]
    assert stage.stage_id == "youtube_abc123xyz"  # song_slug tira "_-" nao-alfanumerico das pontas
    assert stage.name == "Imported Song"
    assert stage.uploader == "Imported Channel"
    assert stage.known_duration_seconds == pytest.approx(42.0)
    assert stage.chapters == ({"start_time_seconds": 10.0, "title": "Drop"},)
    assert stage.thumbnail_path == str(music_dir / "youtube" / "abc123XYZ_-" / "cover.jpg")
    assert stage.selectable_mode is True


def test_scan_youtube_songs_falls_back_to_folder_name_without_metadata(tmp_path):
    music_dir = tmp_path / "musicas"
    _make_youtube_song_folder(music_dir, "novideo123", with_metadata=False, with_thumbnail=False)
    beatmap_dir = tmp_path / "beatmaps"

    stages = scan_youtube_songs(str(music_dir), str(beatmap_dir), analyzer=_fake_analyzer)
    assert len(stages) == 1
    stage = stages[0]
    assert stage.uploader == ""
    assert stage.known_duration_seconds is None
    assert stage.thumbnail_path is None


def test_scan_youtube_songs_skips_a_folder_without_audio(tmp_path):
    music_dir = tmp_path / "musicas"
    folder = music_dir / "youtube" / "empty_folder"
    folder.mkdir(parents=True)
    (folder / "metadata.json").write_text("{}", encoding="utf-8")

    stages = scan_youtube_songs(str(music_dir), str(tmp_path / "beatmaps"), analyzer=_fake_analyzer)
    assert stages == ()


def test_scan_youtube_songs_returns_empty_without_the_youtube_subfolder(tmp_path):
    music_dir = tmp_path / "musicas"
    music_dir.mkdir()
    assert scan_youtube_songs(str(music_dir), str(tmp_path / "beatmaps")) == ()


def test_scan_user_songs_combines_flat_files_and_youtube_folders(tmp_path):
    music_dir = tmp_path / "musicas"
    music_dir.mkdir()
    (music_dir / "minha_musica.mp3").write_bytes(b"fake flat file")
    _make_youtube_song_folder(music_dir, "yt1")
    beatmap_dir = tmp_path / "beatmaps"

    stages = scan_user_songs(str(music_dir), str(beatmap_dir), analyzer=_fake_analyzer)
    stage_ids = {s.stage_id for s in stages}
    assert stage_ids == {"user_minha_musica", "youtube_yt1"}
    assert all(s.selectable_mode for s in stages)
