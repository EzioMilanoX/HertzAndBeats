"""
Biblioteca de musicas do jogador: qualquer audio jogado em `musicas/`
vira uma fase do menu, com o MODO escolhivel na hora de jogar.

Fluxo (tudo em fase de carregamento, nunca no loop de gameplay):
    1. `scan_user_songs` varre `musicas/*.mp3|ogg|wav|flac` (arquivos
       soltos, arrastados manualmente) E `musicas/youtube/<video_id>/`
       (Pipeline de Importacao Direta -- `youtube_import.py`, cada
       pasta com `audio.<ext>`/`metadata.json`/`cover.jpg`).
    2. Musica nova (ou alterada desde a ultima analise) passa pela IA
       offline da engine (librosa, importada LAZY so aqui) e ganha um
       beatmap cacheado em `data/beatmaps/user/<slug>.beatmap.json` --
       as proximas aberturas sao instantaneas.
    3. Cada musica vira um `StageDef` com `selectable_mode=True`: no
       menu, A/D (ou setas) alternam Defensor / Arcade 4K e suas
       variantes antes de comecar. Musicas do YouTube vem com
       `uploader`/`known_duration_seconds`/`chapters`/`thumbnail_path`
       reais (de `metadata.json`); musicas soltas ficam com os defaults
       (so' o nome do arquivo).

Sem librosa instalado, musicas ja analisadas continuam jogaveis; novas
sao puladas com aviso no console.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from hertzbeats.mapper_version import MAPPER_VERSION
from hertzbeats.stages import StageDef

AUDIO_EXTENSIONS = (".mp3", ".ogg", ".wav", ".flac")
USER_MUSIC_DIR = "musicas"
USER_BEATMAP_DIR = "data/beatmaps/user"
MAX_DISPLAY_NAME = 26

YOUTUBE_IMPORT_SUBDIR = "youtube"
"""Pipeline de Importacao Direta: `youtube_import.download_youtube_song`
baixa cada video pra `<music_dir>/youtube/<video_id>/` -- nome de pasta
ESTAVEL (o ID do video, extraido da URL sem chamada de rede), nunca
derivado do titulo (que pode mudar/ter caracteres invalidos pra
filesystem)."""

METADATA_FILENAME = "metadata.json"
THUMBNAIL_FILENAMES = ("cover.jpg", "thumbnail.webp", "thumbnail.jpg", "cover.png", "cover.webp")
"""Nomes de miniatura aceitos, em ordem de preferencia -- `cover.jpg` e'
o nome CANONICO que `youtube_import.download_youtube_song` escreve; os
demais cobrem miniaturas colocadas manualmente numa pasta sem passar
pelo downloader."""


def song_slug(stem: str) -> str:
    """Identificador estavel derivado do nome do arquivo (minusculas,
    alfanumerico e '_')."""
    slug = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")
    return slug or "musica"


def display_name(stem: str) -> str:
    """Nome exibido no menu: limpo, maiusculo e truncado."""
    name = re.sub(r"[_\-]+", " ", stem).strip().upper()
    if len(name) > MAX_DISPLAY_NAME:
        name = name[: MAX_DISPLAY_NAME - 3].rstrip() + "..."
    return name


def needs_analysis(audio_path: Path, beatmap_path: Path) -> bool:
    """True se o beatmap cacheado nao existe, esta mais velho que o
    arquivo de audio (musica substituida/alterada) ou foi gerado por um
    MAPEADOR antigo (melhorias de geracao re-analisam a biblioteca
    automaticamente)."""
    if not beatmap_path.exists():
        return True
    if beatmap_path.stat().st_mtime < audio_path.stat().st_mtime:
        return True
    try:
        with open(beatmap_path, "r", encoding="utf-8") as f:
            cached_version = json.load(f).get("mapper_version", 0)
    except (OSError, json.JSONDecodeError):
        return True
    return cached_version != MAPPER_VERSION


def analyze_song(audio_path: Path, beatmap_path: Path, track_id: str) -> None:
    """Roda a IA offline sobre a musica (import LAZY: librosa so entra
    na memoria se houver musica nova para analisar). Perfil "hybrid":
    esqueleto de kick quantizado + melodia vocal por cima, com tags de
    camada -- o melhor padrao para musica arbitraria do jogador."""
    from hertzbeats.offline.beatmap_pipeline import generate_beatmap

    generate_beatmap(
        audio_path=audio_path, output_path=beatmap_path, track_id=track_id, profile="hybrid"
    )


def scan_user_songs(
    music_dir: str = USER_MUSIC_DIR,
    beatmap_dir: str = USER_BEATMAP_DIR,
    on_progress: Optional[Callable[[str], None]] = None,
    analyzer: Callable[[Path, Path, str], None] = analyze_song,
) -> Tuple[StageDef, ...]:
    """Varre a pasta de musicas do jogador e retorna as fases prontas
    (analisando as novas). `on_progress(nome)` e chamado antes de cada
    analise (tela de carregamento); `analyzer` e injetavel para testes.
    """
    music_path = Path(music_dir)
    if not music_path.is_dir():
        return ()

    stages = []
    for audio_path in sorted(music_path.iterdir(), key=lambda p: p.name.lower()):
        if audio_path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        slug = song_slug(audio_path.stem)
        beatmap_path = Path(beatmap_dir) / f"{slug}.beatmap.json"

        if needs_analysis(audio_path, beatmap_path):
            if on_progress is not None:
                on_progress(audio_path.name)
            try:
                analyzer(audio_path, beatmap_path, slug)
            except ImportError:
                print(
                    f"[musicas] librosa nao instalado -- pulando analise de "
                    f"{audio_path.name} (pip install librosa)"
                )
                continue
            except Exception as exc:  # musica corrompida/formato exotico: nao derruba o jogo
                print(f"[musicas] falha ao analisar {audio_path.name}: {exc}")
                continue
        if not beatmap_path.exists():
            continue

        stages.append(
            StageDef(
                stage_id=f"user_{slug}",
                name=display_name(audio_path.stem),
                subtitle="sua musica",
                track_path=str(audio_path),
                beatmap_path=str(beatmap_path),
                synth=None,
                beatmap_params={},
                overrides={},
                tutorial_steps=(),
                selectable_mode=True,
            )
        )
    return tuple(stages) + scan_youtube_songs(music_dir, beatmap_dir, on_progress, analyzer)


def _find_first_existing(folder: Path, candidate_names: Tuple[str, ...]) -> Optional[Path]:
    for name in candidate_names:
        candidate = folder / name
        if candidate.exists():
            return candidate
    return None


def parse_youtube_metadata(metadata_path: Path) -> Dict:
    """Le `metadata.json` (info-json do yt-dlp, ja renomeado pelo
    downloader -- ver `youtube_import.download_youtube_song`) e devolve
    so os campos que o jogo usa, com defaults graciosos pra qualquer
    campo ausente (metadados de video sao inconsistentes entre uploads/
    versoes do yt-dlp). Capitulos (`chapters`) sao normalizados pra
    `{"start_time_seconds", "title"}` -- ver `StageDef.chapters` e
    `modchart.chapters_to_modchart_events`."""
    with open(metadata_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    chapters = tuple(
        {
            "start_time_seconds": float(chapter.get("start_time", 0.0)),
            "title": str(chapter.get("title", "")),
        }
        for chapter in (raw.get("chapters") or ())
    )
    duration = raw.get("duration")
    return {
        "title": str(raw.get("title") or ""),
        "uploader": str(raw.get("uploader") or raw.get("channel") or ""),
        "duration_seconds": float(duration) if duration is not None else None,
        "chapters": chapters,
    }


def scan_youtube_songs(
    music_dir: str = USER_MUSIC_DIR,
    beatmap_dir: str = USER_BEATMAP_DIR,
    on_progress: Optional[Callable[[str], None]] = None,
    analyzer: Callable[[Path, Path, str], None] = analyze_song,
) -> Tuple[StageDef, ...]:
    """Varre `<music_dir>/youtube/<video_id>/` (Pipeline de Importacao
    Direta): cada subpasta tem `audio.<ext>` + `metadata.json` (opcional
    -- se faltar, cai pros defaults do nome da pasta) + uma miniatura
    (opcional). MESMO fluxo de analise/cache de beatmap de
    `scan_user_songs` (a IA offline nao se importa se o audio veio de um
    arquivo solto ou de um download), so' com metadados REAIS (titulo,
    uploader, duracao exata, capitulos do YouTube) em vez de so o nome
    do arquivo -- ver `StageDef.uploader`/`known_duration_seconds`/
    `chapters`/`thumbnail_path`. Chamada tanto pelo scan inicial
    (`scan_user_songs`) quanto de dentro da thread de background do
    Pipeline de Importacao Direta, apos um download novo terminar
    (`HertzGameLoop._apply_youtube_import_result`)."""
    youtube_root = Path(music_dir) / YOUTUBE_IMPORT_SUBDIR
    if not youtube_root.is_dir():
        return ()

    stages = []
    for folder in sorted(youtube_root.iterdir(), key=lambda p: p.name.lower()):
        if not folder.is_dir():
            continue
        audio_path = _find_first_existing(folder, tuple(f"audio{ext}" for ext in AUDIO_EXTENSIONS))
        if audio_path is None:
            continue
        slug = song_slug(folder.name)
        beatmap_path = Path(beatmap_dir) / f"youtube_{slug}.beatmap.json"

        if needs_analysis(audio_path, beatmap_path):
            if on_progress is not None:
                on_progress(audio_path.name)
            try:
                analyzer(audio_path, beatmap_path, f"youtube_{slug}")
            except ImportError:
                print(
                    f"[musicas] librosa nao instalado -- pulando analise de "
                    f"{folder.name} (pip install librosa)"
                )
                continue
            except Exception as exc:  # musica corrompida/formato exotico: nao derruba o jogo
                print(f"[musicas] falha ao analisar {folder.name}: {exc}")
                continue
        if not beatmap_path.exists():
            continue

        title = display_name(folder.name)
        uploader = ""
        known_duration_seconds = None
        chapters: Tuple[Dict, ...] = ()
        metadata_path = folder / METADATA_FILENAME
        if metadata_path.exists():
            try:
                metadata = parse_youtube_metadata(metadata_path)
            except (OSError, ValueError, json.JSONDecodeError):
                metadata = None
            if metadata is not None:
                if metadata["title"]:
                    title = metadata["title"][:MAX_DISPLAY_NAME]
                uploader = metadata["uploader"]
                known_duration_seconds = metadata["duration_seconds"]
                chapters = metadata["chapters"]

        thumbnail_path = _find_first_existing(folder, THUMBNAIL_FILENAMES)

        stages.append(
            StageDef(
                stage_id=f"youtube_{slug}",
                name=title,
                subtitle=uploader or "sua musica (YouTube)",
                track_path=str(audio_path),
                beatmap_path=str(beatmap_path),
                synth=None,
                beatmap_params={},
                overrides={},
                tutorial_steps=(),
                selectable_mode=True,
                uploader=uploader,
                known_duration_seconds=known_duration_seconds,
                chapters=chapters,
                thumbnail_path=str(thumbnail_path) if thumbnail_path is not None else None,
                description=uploader,
            )
        )
    return tuple(stages)
