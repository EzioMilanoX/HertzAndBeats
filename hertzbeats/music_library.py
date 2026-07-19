"""
Biblioteca de musicas do jogador: qualquer audio jogado em `musicas/`
vira uma fase do menu, com o MODO escolhivel na hora de jogar.

Fluxo (tudo em fase de carregamento, nunca no loop de gameplay):
    1. `scan_user_songs` varre `musicas/*.mp3|ogg|wav|flac`.
    2. Musica nova (ou alterada desde a ultima analise) passa pela IA
       offline da engine (librosa, importada LAZY so aqui) e ganha um
       beatmap cacheado em `data/beatmaps/user/<slug>.beatmap.json` --
       as proximas aberturas sao instantaneas.
    3. Cada musica vira um `StageDef` com `selectable_mode=True`: no
       menu, A/D (ou setas) alternam Defensor / Arcade 4K e suas
       variantes antes de comecar.

Sem librosa instalado, musicas ja analisadas continuam jogaveis; novas
sao puladas com aviso no console.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional, Tuple

from hertzbeats.mapper_version import MAPPER_VERSION
from hertzbeats.stages import StageDef

AUDIO_EXTENSIONS = (".mp3", ".ogg", ".wav", ".flac")
USER_MUSIC_DIR = "musicas"
USER_BEATMAP_DIR = "data/beatmaps/user"
MAX_DISPLAY_NAME = 26


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
    return tuple(stages)
