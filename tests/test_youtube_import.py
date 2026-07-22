"""Pipeline de Importacao Direta: deteccao de URL, download via yt-dlp (subprocess FAKE, nunca rede de verdade) e scan de musicas/youtube/."""
import json
from pathlib import Path

import pytest

from hertzbeats.music_library import parse_youtube_metadata, scan_user_songs, scan_youtube_songs
from hertzbeats.youtube_import import (
    YoutubeImportError,
    download_youtube_song,
    extract_video_id,
    extract_youtube_url,
    import_youtube_song,
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


# -- download_youtube_song (subprocess FAKE, nunca chamada de rede) ----------


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stderr: str = ""):
        self.returncode = returncode
        self.stderr = stderr


def test_download_youtube_song_rejects_an_unrecognized_url(tmp_path):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return _FakeCompletedProcess(0)

    with pytest.raises(YoutubeImportError):
        download_youtube_song("https://vimeo.com/12345", music_dir=str(tmp_path), run_subprocess=fake_run)
    assert calls == []  # nunca chega a chamar o subprocess com uma URL invalida


def test_download_youtube_song_builds_the_expected_yt_dlp_command(tmp_path):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return _FakeCompletedProcess(0)

    folder = download_youtube_song(
        "https://youtu.be/dQw4w9WgXcQ", music_dir=str(tmp_path), run_subprocess=fake_run,
    )
    assert folder == tmp_path / "youtube" / "dQw4w9WgXcQ"
    assert folder.is_dir()  # pasta de destino ja criada antes do subprocess rodar

    command = captured["command"]
    assert command[0] == "yt-dlp"
    assert "https://youtu.be/dQw4w9WgXcQ" in command
    assert "-o" in command
    output_index = command.index("-o") + 1
    assert command[output_index] == str(folder / "audio.%(ext)s")
    assert captured["kwargs"]["capture_output"] is True


def test_download_youtube_song_raises_on_a_nonzero_exit_code(tmp_path):
    def failing_run(*args, **kwargs):
        return _FakeCompletedProcess(1, stderr="ERROR: video unavailable")

    with pytest.raises(YoutubeImportError, match="video unavailable"):
        download_youtube_song("https://youtu.be/dQw4w9WgXcQ", music_dir=str(tmp_path), run_subprocess=failing_run)


def test_download_youtube_song_renames_info_json_and_thumbnail_to_canonical_names(tmp_path):
    def fake_run(command, **kwargs):
        output_index = command.index("-o") + 1
        folder = Path(command[output_index]).parent
        (folder / "audio.mp3").write_bytes(b"fake audio")
        (folder / "audio.info.json").write_text(json.dumps({"title": "Fake Song"}), encoding="utf-8")
        (folder / "audio.jpg").write_bytes(b"fake jpg")
        return _FakeCompletedProcess(0)

    folder = download_youtube_song(
        "https://youtu.be/dQw4w9WgXcQ", music_dir=str(tmp_path), run_subprocess=fake_run,
    )
    assert (folder / "audio.mp3").exists()
    assert (folder / "metadata.json").exists()
    assert not (folder / "audio.info.json").exists()
    assert (folder / "cover.jpg").exists()
    assert not (folder / "audio.jpg").exists()


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


def _fake_analyzer(audio_path, beatmap_path, track_id):
    beatmap_path.parent.mkdir(parents=True, exist_ok=True)
    beatmap_path.write_text(
        json.dumps({"bpm": 120.0, "threats": [{"timestamp_seconds": 1.0}], "mapper_version": 1}),
        encoding="utf-8",
    )


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


# -- import_youtube_song (download FAKE + scan combinados) -------------------


def test_import_youtube_song_downloads_then_scans_and_returns_the_new_stage(tmp_path):
    music_dir = tmp_path / "musicas"
    beatmap_dir = tmp_path / "beatmaps"

    def fake_run(command, **kwargs):
        output_index = command.index("-o") + 1
        folder = Path(command[output_index]).parent
        (folder / "audio.mp3").write_bytes(b"fake audio")
        (folder / "audio.info.json").write_text(
            json.dumps({"title": "Brand New Song", "uploader": "Someone", "duration": 99.0}),
            encoding="utf-8",
        )
        return _FakeCompletedProcess(0)

    video_id, stages = import_youtube_song(
        "https://youtu.be/newsong123",
        music_dir=str(music_dir),
        beatmap_dir=str(beatmap_dir),
        run_subprocess=fake_run,
        analyzer=_fake_analyzer,
    )
    assert video_id == "newsong123"
    assert len(stages) == 1
    assert stages[0].stage_id == "youtube_newsong123"
    assert stages[0].name == "Brand New Song"
