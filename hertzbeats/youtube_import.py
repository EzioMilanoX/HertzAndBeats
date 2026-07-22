"""Pipeline de Importacao Direta (FLOW_DOWNLOAD_HUB): busca uma previa (titulo/canal/miniatura) via yt-dlp, so baixa o audio de verdade apos o jogador confirmar.

Chamado INTEIRAMENTE de dentro da thread de background PERSISTENTE
(`HertzGameLoop._download_worker_loop`) -- nunca na thread principal do
jogo, que so deve tocar pygame/ECS. NUNCA cria/toca um `pygame.Surface`
aqui (SDL/pygame nao e thread-safe para chamadas de renderizacao) -- as
funcoes deste modulo so devolvem dicts/tuplas simples, postados na
`queue.Queue` de resultados pelo chamador.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from hertzbeats.music_library import (
    USER_BEATMAP_DIR,
    USER_MUSIC_DIR,
    YOUTUBE_IMPORT_SUBDIR,
    analyze_song,
    scan_youtube_songs,
)
from hertzbeats.stages import StageDef

_YOUTUBE_HOST_PATTERN = (
    r"(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)"
)
_YOUTUBE_URL_PATTERN = re.compile(_YOUTUBE_HOST_PATTERN + r"[A-Za-z0-9_-]{6,}(?:[^\s]*)?")
_YOUTUBE_VIDEO_ID_PATTERN = re.compile(_YOUTUBE_HOST_PATTERN + r"([A-Za-z0-9_-]{6,})")

DEFAULT_YT_DLP_COMMAND = "yt-dlp"
PREVIEW_THUMBNAIL_FILENAME = "preview.jpg"


class YoutubeImportError(RuntimeError):
    """URL do YouTube nao reconhecida, ou `yt-dlp`/a analise de beatmap
    falharam durante o Pipeline de Importacao Direta."""


class FFmpegNotFoundError(YoutubeImportError):
    """`ffmpeg` nao encontrado no PATH -- `yt-dlp --extract-audio`
    depende dele pra converter o audio baixado. Verificado PROATIVAMENTE
    na Etapa 2 (Download), antes de chamar o subprocess, pra dar um
    erro CLARO em vez de deixar o yt-dlp falhar com uma mensagem
    interna criptica."""


def extract_youtube_url(text: str) -> Optional[str]:
    """Encontra a PRIMEIRA URL do YouTube (watch/shorts/embed/youtu.be)
    num texto arbitrario (ex.: conteudo colado do clipboard via
    Ctrl+V) -- funcao PURA, nenhuma chamada de rede. `None` se nada
    bater. Normaliza pra sempre incluir o esquema (`https://`), mesmo
    se o texto colado nao tiver um (comum ao colar so o dominio sem o
    `https://` na frente). Chamada SEMPRE antes de qualquer thread
    (`HertzGameLoop._advance_download_hub`) -- uma URL invalida nunca
    chega perto de `yt-dlp`."""
    match = _YOUTUBE_URL_PATTERN.search(text or "")
    if match is None:
        return None
    url = match.group(0)
    return url if url.startswith(("http://", "https://")) else f"https://{url}"


def extract_video_id(url: str) -> Optional[str]:
    """Extrai o ID do video (11+ caracteres) a partir da URL -- usado
    como nome de pasta ESTAVEL (`musicas/youtube/<video_id>/`) sem
    precisar de nenhuma chamada de rede pra decidir onde salvar (o
    titulo real so vem da Previa, ETAPA 1)."""
    match = _YOUTUBE_VIDEO_ID_PATTERN.search(url or "")
    return match.group(1) if match else None


def read_system_clipboard() -> str:
    """Leitura REAL do clipboard do sistema (CTRL+V em FLOW_DOWNLOAD_HUB)
    -- via `tkinter` (stdlib, disponivel em qualquer instalacao padrao
    de Python) em vez de `pygame.scrap` (exige um modo de video ja
    ativo e tem suporte inconsistente entre plataformas/versoes do
    SDL). Uma janela Tk invisivel (`withdraw`), destruida imediatamente
    apos ler. String vazia se o clipboard estiver vazio ou nao for
    texto -- NUNCA levanta, quem chama
    (`HertzGameLoop._advance_download_hub`) so trata "nenhuma URL
    encontrada" de um jeito, com ou sem essa distincao."""
    import tkinter

    root = tkinter.Tk()
    root.withdraw()
    try:
        return root.clipboard_get()
    except tkinter.TclError:
        return ""
    finally:
        root.destroy()


def ffmpeg_available(which_fn: Callable[[str], Optional[str]] = shutil.which) -> bool:
    """Presenca do `ffmpeg` no sistema (`shutil.which`, injetavel pra
    testes) -- checado PROATIVAMENTE na Etapa 2 (Download), antes de
    `yt-dlp --extract-audio`."""
    return which_fn("ffmpeg") is not None


def _rename_if_exists(folder: Path, expected_name: str, final_name: str) -> None:
    """`yt-dlp` deriva os nomes de info-json/miniatura do template de
    saida (`audio.%(ext)s` -> `audio.info.json`) -- renomeia pro nome
    FIXO que `music_library.scan_youtube_songs` espera
    (`metadata.json`), sem depender de detalhes do template."""
    source = folder / expected_name
    if source.exists():
        source.replace(folder / final_name)


def _destination_folder(url: str, music_dir: str) -> Path:
    """Pasta ESTAVEL (`musicas/youtube/<video_id>/`) compartilhada
    pelas 2 etapas -- o `video_id` vem da URL sem nenhuma chamada de
    rede, entao a Previa (Etapa 1) e o Download (Etapa 2, rodando numa
    invocacao SEPARADA da thread) sempre concordam em onde salvar."""
    video_id = extract_video_id(url)
    if video_id is None:
        raise YoutubeImportError(f"URL do YouTube nao reconhecida: {url!r}")
    folder = Path(music_dir) / YOUTUBE_IMPORT_SUBDIR / video_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def fetch_youtube_preview(
    url: str,
    music_dir: str = USER_MUSIC_DIR,
    run_subprocess: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
    yt_dlp_command: str = DEFAULT_YT_DLP_COMMAND,
) -> Dict:
    """ETAPA 1 (Previa): SO metadados + miniatura, NUNCA audio
    (`--skip-download`) -- `--dump-json` imprime o JSON no STDOUT
    (nenhum arquivo `.info.json` precisa existir so pra isso);
    `--write-thumbnail` grava JUNTO a miniatura (`preview.jpg`, apos
    `--convert-thumbnails jpg`) na MESMA pasta estavel que a Etapa 2 vai
    reusar -- um UNICO subprocess faz as 2 coisas, nenhuma chamada de
    rede repetida.

    Retorna um dict pronto pra exibir (`title`/`uploader`/
    `duration_seconds`/`chapters`/`thumbnail_path`) MAIS o que a Etapa 2
    precisa pra continuar exatamente daqui (`video_id`/`url`/
    `preview_folder`).

    Levanta `YoutubeImportError` se a URL nao tiver um video ID
    reconhecivel, se o subprocess falhar, ou se a saida nao for um JSON
    valido (yt-dlp desatualizado/pagina de erro capturada por engano)."""
    folder = _destination_folder(url, music_dir)
    output_template = str(folder / "preview.%(ext)s")

    result = run_subprocess(
        [
            yt_dlp_command,
            "--dump-json",
            "--skip-download",
            "--write-thumbnail",
            "--convert-thumbnails", "jpg",
            "--no-playlist",
            "-o", output_template,
            url,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise YoutubeImportError(f"yt-dlp (previa) falhou (codigo {result.returncode}) pra {url!r}: {stderr}")

    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise YoutubeImportError(f"yt-dlp nao devolveu um JSON valido pra {url!r}: {exc}") from exc

    chapters = tuple(
        {
            "start_time_seconds": float(chapter.get("start_time", 0.0)),
            "title": str(chapter.get("title", "")),
        }
        for chapter in (metadata.get("chapters") or ())
    )
    duration = metadata.get("duration")
    thumbnail_path = folder / PREVIEW_THUMBNAIL_FILENAME

    return {
        "video_id": folder.name,
        "url": url,
        "preview_folder": str(folder),
        "title": str(metadata.get("title") or ""),
        "uploader": str(metadata.get("uploader") or metadata.get("channel") or ""),
        "duration_seconds": float(duration) if duration is not None else None,
        "chapters": chapters,
        "thumbnail_path": str(thumbnail_path) if thumbnail_path.exists() else None,
    }


def download_and_analyze_youtube_song(
    preview: Dict,
    music_dir: str = USER_MUSIC_DIR,
    beatmap_dir: str = USER_BEATMAP_DIR,
    run_subprocess: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
    yt_dlp_command: str = DEFAULT_YT_DLP_COMMAND,
    ffmpeg_checker: Callable[[], bool] = ffmpeg_available,
    analyzer: Callable[[Path, Path, str], None] = analyze_song,
) -> Tuple[str, Tuple[StageDef, ...]]:
    """ETAPA 2 (Download): so' chamada depois que o jogador CONFIRMA a
    Previa (ENTER) -- baixa o audio de verdade (`--extract-audio`) na
    MESMA pasta da Previa (reusa `preview["preview_folder"]`, nunca
    busca a miniatura de novo) e IMEDIATAMENTE analisa o beatmap
    (`music_library.scan_youtube_songs`, mesma IA offline de sempre).

    Verifica `ffmpeg_checker()` (default `ffmpeg_available`, ou seja
    `shutil.which("ffmpeg")`) PROATIVAMENTE antes do subprocess --
    `yt-dlp --extract-audio` depende dele pra converter o audio
    baixado; sem isso, levanta `FFmpegNotFoundError` com uma mensagem
    clara em vez de deixar o yt-dlp falhar com um erro interno
    criptico.

    Retorna `(video_id, stages)`: `stages` e' a lista COMPLETA e
    atualizada de musicas do YouTube (inclui importacoes anteriores,
    nao so a nova) -- `HertzGameLoop._apply_download_success` substitui
    so essa fatia do catalogo, preservando fases curadas e musicas
    soltas intactas."""
    if not ffmpeg_checker():
        raise FFmpegNotFoundError("FFmpeg nao encontrado no sistema -- instale e garanta que esta no PATH")

    folder = Path(preview["preview_folder"])
    output_template = str(folder / "audio.%(ext)s")

    result = run_subprocess(
        [
            yt_dlp_command,
            "--extract-audio",
            "--audio-format", "mp3",
            "--write-info-json",
            "--no-playlist",
            "-o", output_template,
            preview["url"],
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise YoutubeImportError(f"yt-dlp (download) falhou (codigo {result.returncode}): {stderr}")

    _rename_if_exists(folder, "audio.info.json", "metadata.json")
    preview_thumbnail = folder / PREVIEW_THUMBNAIL_FILENAME
    cover_path = folder / "cover.jpg"
    if preview_thumbnail.exists() and not cover_path.exists():
        preview_thumbnail.replace(cover_path)

    stages = scan_youtube_songs(music_dir=music_dir, beatmap_dir=beatmap_dir, analyzer=analyzer)
    return preview["video_id"], stages
