"""Biblioteca de musicas do jogador: scan, cache de analise e escolha de minigame no menu."""
import json
import os
import time
from pathlib import Path

from hertzbeats.music_library import display_name, needs_analysis, scan_user_songs, song_slug

from tests.conftest import write_beatmap


def _fake_audio(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFFfake")
    return path


def _fake_analyzer_writing_beatmap(calls):
    def _analyze(audio_path, beatmap_path, track_id):
        calls.append(audio_path.name)
        write_beatmap(Path(beatmap_path), [
            {"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.5},
        ])
    return _analyze


def test_slug_and_display_name():
    assert song_slug("Minha Música (Remix)!") == "minha_m_sica_remix"
    assert display_name("minha_musica-favorita") == "MINHA MUSICA FAVORITA"
    assert len(display_name("x" * 60)) <= 26


def test_scan_analyzes_new_songs_and_uses_cache(tmp_path):
    music_dir = tmp_path / "musicas"
    beatmap_dir = tmp_path / "user_beatmaps"
    _fake_audio(music_dir / "trilha.mp3")
    calls = []

    stages = scan_user_songs(
        music_dir=str(music_dir), beatmap_dir=str(beatmap_dir),
        analyzer=_fake_analyzer_writing_beatmap(calls),
    )
    assert calls == ["trilha.mp3"]
    assert len(stages) == 1
    stage = stages[0]
    assert stage.stage_id == "user_trilha"
    assert stage.selectable_mode is True
    assert stage.synth is None
    assert Path(stage.beatmap_path).exists()

    # segunda varredura: cache valido, NENHUMA nova analise
    stages = scan_user_songs(
        music_dir=str(music_dir), beatmap_dir=str(beatmap_dir),
        analyzer=_fake_analyzer_writing_beatmap(calls),
    )
    assert calls == ["trilha.mp3"]
    assert len(stages) == 1


def test_replaced_song_triggers_reanalysis(tmp_path):
    music_dir = tmp_path / "musicas"
    beatmap_dir = tmp_path / "user_beatmaps"
    audio = _fake_audio(music_dir / "trilha.ogg")
    calls = []
    scan_user_songs(music_dir=str(music_dir), beatmap_dir=str(beatmap_dir),
                    analyzer=_fake_analyzer_writing_beatmap(calls))
    assert len(calls) == 1

    # substitui o audio por versao mais nova que o beatmap cacheado
    future = time.time() + 60
    os.utime(audio, (future, future))
    assert needs_analysis(audio, Path(beatmap_dir) / "trilha.beatmap.json")
    scan_user_songs(music_dir=str(music_dir), beatmap_dir=str(beatmap_dir),
                    analyzer=_fake_analyzer_writing_beatmap(calls))
    assert len(calls) == 2


def test_failed_analysis_skips_song_without_crashing(tmp_path):
    music_dir = tmp_path / "musicas"
    beatmap_dir = tmp_path / "user_beatmaps"
    _fake_audio(music_dir / "corrompida.wav")

    def _broken(audio_path, beatmap_path, track_id):
        raise ValueError("audio ilegivel")

    stages = scan_user_songs(music_dir=str(music_dir), beatmap_dir=str(beatmap_dir), analyzer=_broken)
    assert stages == ()


def test_non_audio_files_and_missing_dir_are_ignored(tmp_path):
    music_dir = tmp_path / "musicas"
    _fake_audio(music_dir / "capa.jpg")
    (music_dir / "LEIA-ME.txt").write_text("oi", encoding="utf-8")
    assert scan_user_songs(music_dir=str(music_dir), beatmap_dir=str(tmp_path / "b")) == ()
    assert scan_user_songs(music_dir=str(tmp_path / "nao_existe"), beatmap_dir=str(tmp_path / "b")) == ()
