"""Pipeline de Importacao Direta (Ctrl+V): baixa um video do YouTube via yt-dlp (subprocess) e devolve o catalogo atualizado.

Chamado INTEIRAMENTE de dentro de uma thread de background
(`HertzGameLoop._run_youtube_import_thread`) -- nunca na thread
principal do jogo, que so deve tocar pygame/ECS. As duas etapas
bloqueantes (a chamada de rede do `yt-dlp` e a analise offline do
beatmap via librosa) acontecem aqui; o resultado (video_id + catalogo
`StageDef` atualizado) e devolvido por uma `queue.Queue` -- NUNCA um
`pygame.Surface`/textura e criado ou tocado neste modulo (SDL/pygame
nao e thread-safe para chamadas de renderizacao).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable, Optional, Tuple

from hertzbeats.music_library import USER_BEATMAP_DIR, USER_MUSIC_DIR, YOUTUBE_IMPORT_SUBDIR, analyze_song
from hertzbeats.stages import StageDef

_YOUTUBE_HOST_PATTERN = (
    r"(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)"
)
_YOUTUBE_URL_PATTERN = re.compile(_YOUTUBE_HOST_PATTERN + r"[A-Za-z0-9_-]{6,}(?:[^\s]*)?")
_YOUTUBE_VIDEO_ID_PATTERN = re.compile(_YOUTUBE_HOST_PATTERN + r"([A-Za-z0-9_-]{6,})")

DEFAULT_YT_DLP_COMMAND = "yt-dlp"


class YoutubeImportError(RuntimeError):
    """URL do YouTube nao reconhecida, ou `yt-dlp`/a analise de beatmap
    falharam durante o Pipeline de Importacao Direta."""


def extract_youtube_url(text: str) -> Optional[str]:
    """Encontra a PRIMEIRA URL do YouTube (watch/shorts/embed/youtu.be)
    num texto arbitrario (ex.: conteudo colado do clipboard via
    Ctrl+V) -- funcao PURA, nenhuma chamada de rede. `None` se nada
    bater. Normaliza pra sempre incluir o esquema (`https://`), mesmo
    se o texto colado nao tiver um (comum ao colar so o dominio sem o
    `https://` na frente)."""
    match = _YOUTUBE_URL_PATTERN.search(text or "")
    if match is None:
        return None
    url = match.group(0)
    return url if url.startswith(("http://", "https://")) else f"https://{url}"


def extract_video_id(url: str) -> Optional[str]:
    """Extrai o ID do video (11+ caracteres) a partir da URL -- usado
    como nome de pasta ESTAVEL (`musicas/youtube/<video_id>/`) sem
    precisar de nenhuma chamada de rede pra decidir onde salvar (o
    titulo real so vem depois, no `metadata.json` baixado)."""
    match = _YOUTUBE_VIDEO_ID_PATTERN.search(url or "")
    return match.group(1) if match else None


def read_system_clipboard() -> str:
    """Leitura REAL do clipboard do sistema (CTRL+V no Carrossel) --
    via `tkinter` (stdlib, disponivel em qualquer instalacao padrao de
    Python) em vez de `pygame.scrap` (exige um modo de video ja ativo e
    tem suporte inconsistente entre plataformas/versoes do SDL). Uma
    janela Tk invisivel (`withdraw`), destruida imediatamente apos ler.
    String vazia se o clipboard estiver vazio ou nao for texto --
    NUNCA levanta, quem chama (`HertzGameLoop._try_import_from_clipboard`)
    so trata "nenhuma URL encontrada" de um jeito, com ou sem essa
    distincao."""
    import tkinter

    root = tkinter.Tk()
    root.withdraw()
    try:
        return root.clipboard_get()
    except tkinter.TclError:
        return ""
    finally:
        root.destroy()


def _rename_if_exists(folder: Path, expected_name: str, final_name: str) -> None:
    """`yt-dlp` deriva os nomes de info-json/miniatura do template de
    saida (`audio.%(ext)s` -> `audio.info.json`/`audio.jpg`) -- renomeia
    pros nomes FIXOS que `music_library.scan_youtube_songs` espera
    (`metadata.json`/`cover.jpg`), sem depender de qual extensao exata o
    yt-dlp escolheu pra miniatura."""
    source = folder / expected_name
    if source.exists():
        source.replace(folder / final_name)


def download_youtube_song(
    url: str,
    music_dir: str = USER_MUSIC_DIR,
    run_subprocess: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
    yt_dlp_command: str = DEFAULT_YT_DLP_COMMAND,
) -> Path:
    """Baixa audio + `metadata.json` + miniatura de UM video via
    `yt-dlp` (subprocess -- NUNCA a biblioteca `yt-dlp` importada
    diretamente, pra manter o processo do jogo livre de qualquer
    travamento/exception interna dela; um subprocess isolado tambem
    sobrevive a uma versao de yt-dlp instalada globalmente, sem
    precisar ser a mesma que o ambiente Python do jogo usa).

    Layout de saida (contrato lido por `music_library.scan_youtube_songs`):
        <music_dir>/youtube/<video_id>/audio.<ext>
        <music_dir>/youtube/<video_id>/metadata.json
        <music_dir>/youtube/<video_id>/cover.jpg

    `video_id` (extraido da URL, SEM chamada de rede) e' o nome de
    pasta -- dispensa uma 1a chamada de rede so pra descobrir o titulo
    antes de decidir onde salvar, e e' estavel/unico por natureza.

    `run_subprocess` e' injetavel (default `subprocess.run`) -- testes
    NUNCA disparam uma chamada de rede de verdade, so verificam que os
    argumentos/comando montados estao corretos contra um FAKE.

    Retorna o `Path` da pasta pronta. Levanta `YoutubeImportError` se a
    URL nao tiver um video ID reconhecivel ou se o subprocess retornar
    codigo de saida diferente de zero."""
    video_id = extract_video_id(url)
    if video_id is None:
        raise YoutubeImportError(f"URL do YouTube nao reconhecida: {url!r}")

    dest_folder = Path(music_dir) / YOUTUBE_IMPORT_SUBDIR / video_id
    dest_folder.mkdir(parents=True, exist_ok=True)
    output_template = str(dest_folder / "audio.%(ext)s")

    result = run_subprocess(
        [
            yt_dlp_command,
            "--extract-audio",
            "--audio-format", "mp3",
            "--write-info-json",
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
        raise YoutubeImportError(f"yt-dlp falhou (codigo {result.returncode}) pra {url!r}: {stderr}")

    _rename_if_exists(dest_folder, "audio.info.json", "metadata.json")
    _rename_if_exists(dest_folder, "audio.jpg", "cover.jpg")
    return dest_folder


def import_youtube_song(
    url: str,
    music_dir: str = USER_MUSIC_DIR,
    beatmap_dir: str = USER_BEATMAP_DIR,
    run_subprocess: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
    analyzer: Callable[[Path, Path, str], None] = analyze_song,
) -> Tuple[str, Tuple[StageDef, ...]]:
    """Ponto de entrada da thread de background: baixa
    (`download_youtube_song`) e IMEDIATAMENTE re-varre
    `musicas/youtube/` (`music_library.scan_youtube_songs`, que analisa
    qualquer pasta nova via a MESMA IA offline usada por musicas
    soltas) -- as duas etapas de I/O bloqueante (rede + librosa) na
    MESMA thread secundaria, nunca na thread principal do jogo.

    Retorna `(video_id, stages)`: `video_id` identifica qual entrada de
    `stages` e' a recem-importada (`stage_id == f"youtube_{video_id}"`);
    `stages` e' a lista COMPLETA e atualizada de musicas do YouTube
    (inclui as ja importadas antes, nao so a nova) -- `HertzGameLoop.
    _apply_youtube_import_result` substitui so essa fatia do catalogo,
    preservando fases curadas e musicas soltas intactas."""
    from hertzbeats.music_library import scan_youtube_songs

    folder = download_youtube_song(url, music_dir=music_dir, run_subprocess=run_subprocess)
    video_id = folder.name
    stages = scan_youtube_songs(music_dir=music_dir, beatmap_dir=beatmap_dir, analyzer=analyzer)
    return video_id, stages
