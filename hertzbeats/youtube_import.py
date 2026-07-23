"""Pipeline de Importacao Direta (FLOW_DOWNLOAD_HUB): busca uma previa (titulo/canal/miniatura) via yt-dlp, so baixa o audio de verdade apos o jogador confirmar.

Chamado INTEIRAMENTE de dentro da thread de background PERSISTENTE
(`HertzGameLoop._download_worker_loop`) -- nunca na thread principal do
jogo, que so deve tocar pygame/ECS. NUNCA cria/toca um `pygame.Surface`
aqui (SDL/pygame nao e thread-safe para chamadas de renderizacao) -- as
funcoes deste modulo so devolvem dicts/tuplas simples, postados na
`queue.Queue` de resultados pelo chamador.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from hertzbeats.music_library import (
    USER_BEATMAP_DIR,
    USER_MUSIC_DIR,
    YOUTUBE_IMPORT_SUBDIR,
    analyze_song,
    scan_youtube_songs,
)
from hertzbeats.stages import StageDef
from utils.path_resolver import get_resource_path

_YOUTUBE_HOST_PATTERN = (
    r"(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)"
)
_YOUTUBE_URL_PATTERN = re.compile(_YOUTUBE_HOST_PATTERN + r"[A-Za-z0-9_-]{6,}(?:[^\s]*)?")
_YOUTUBE_VIDEO_ID_PATTERN = re.compile(_YOUTUBE_HOST_PATTERN + r"([A-Za-z0-9_-]{6,})")

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


class YtDlpNotFoundError(YoutubeImportError):
    """`yt-dlp` nao encontrado no PATH -- dependencia OPCIONAL do
    Pipeline de Importacao Direta (`pip install yt-dlp` ou
    `pip install "hertz-and-beats[youtube]"`). Verificado PROATIVAMENTE
    em AMBAS as etapas (Previa e Download), antes de chamar o
    subprocess -- sem essa checagem, `subprocess.run(["yt-dlp", ...])`
    levanta um `FileNotFoundError`/`OSError` do sistema operacional
    (ex.: "[WinError 2] O sistema nao pode encontrar o arquivo
    especificado" no Windows) que nao diz ao jogador QUAL dependencia
    falta nem como resolver."""


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


def _default_bundled_ffmpeg_path() -> str:
    """Caminho do `ffmpeg` EMBUTIDO na pasta `bin/` do projeto/build
    PyInstaller -- `.exe` no Windows, sem extensao nos demais SOs
    (`os.name == "nt"` e' a MESMA checagem que o resto da stdlib usa
    pra essa distincao)."""
    return get_resource_path("bin/ffmpeg.exe" if os.name == "nt" else "bin/ffmpeg")


def resolve_ffmpeg_path(
    which_fn: Callable[[str], Optional[str]] = shutil.which,
    bundled_path_resolver: Callable[[], str] = _default_bundled_ffmpeg_path,
) -> Optional[str]:
    """Resolve o caminho ABSOLUTO do `ffmpeg` a usar (nunca so' um
    booleano) -- mesmo espirito de `resolve_yt_dlp_command`: prefere o
    `ffmpeg` do PATH do sistema (`shutil.which`, respeita uma instalacao
    real do jogador), e so' cai pro binario EMBUTIDO em `bin/` (pasta
    includа no PyInstaller via `hertz_build.spec`) se nada for
    encontrado no PATH -- o jogador comum, sem `ffmpeg` instalado, nunca
    precisa saber que essa dependencia existe. `None` se nenhum dos 2
    existir de verdade (bundled_path_resolver() aponta pra um arquivo
    que so existe DEPOIS de empacotado -- rodando do codigo-fonte sem um
    `bin/ffmpeg*` local, cai aqui, e' o comportamento correto)."""
    which_path = which_fn("ffmpeg")
    if which_path is not None:
        return which_path
    bundled = Path(bundled_path_resolver())
    if bundled.exists():
        return str(bundled)
    return None


def ffmpeg_available(which_fn: Callable[[str], Optional[str]] = shutil.which) -> bool:
    """Presenca do `ffmpeg` no sistema OU embutido em `bin/`
    (`resolve_ffmpeg_path`, injetavel via `which_fn` pra testes) --
    checado PROATIVAMENTE na Etapa 2 (Download), antes de
    `yt-dlp --extract-audio`."""
    return resolve_ffmpeg_path(which_fn=which_fn) is not None


def resolve_yt_dlp_command(
    which_fn: Callable[[str], Optional[str]] = shutil.which,
    module_finder: Callable[[str], Optional[object]] = importlib.util.find_spec,
    python_executable: str = sys.executable,
) -> Optional[List[str]]:
    """Resolve os argumentos INICIAIS pra invocar yt-dlp (uma LISTA,
    nunca uma string unica -- vira o prefixo do comando do subprocess).

    Prefere o executavel no PATH (`shutil.which("yt-dlp")`); se ausente,
    cai pra `<python_executable> -m yt_dlp` quando o PACOTE pip esta
    instalado no MESMO interpretador rodando o jogo mas seu script de
    entrada (`yt-dlp.exe`/`yt-dlp`) nao esta no PATH -- caso MUITO comum
    no Windows com `pip install --user` (o pip so' AVISA que o script
    ficou fora do PATH, nao falha a instalacao, e o jogador raramente le
    esse aviso no meio da saida do pip). `python -m yt_dlp` funciona
    INDEPENDENTE do PATH -- so precisa do pacote ser importavel.

    `None` se nem o executavel nem o pacote existirem -- so' entao
    `YtDlpNotFoundError` e' realmente justificado."""
    which_path = which_fn("yt-dlp")
    if which_path is not None:
        return [which_path]
    if module_finder("yt_dlp") is not None:
        return [python_executable, "-m", "yt_dlp"]
    return None


def yt_dlp_available(which_fn: Callable[[str], Optional[str]] = shutil.which) -> bool:
    """Conveniencia booleana sobre `resolve_yt_dlp_command` (so' o
    `which_fn`, sem checar o pacote importavel) -- usada por quem so
    precisa saber "existe o executavel no PATH?", nao o comando
    completo pra rodar."""
    return which_fn("yt-dlp") is not None


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
    yt_dlp_command_resolver: Callable[[], Optional[List[str]]] = resolve_yt_dlp_command,
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

    Resolve `yt_dlp_command_resolver()` (default `resolve_yt_dlp_command`
    -- executavel no PATH, ou `python -m yt_dlp` se so o pacote pip
    estiver instalado) PROATIVAMENTE antes do subprocess -- `None` vira
    `YtDlpNotFoundError` com uma mensagem clara em vez do
    `FileNotFoundError`/`OSError` criptico do sistema operacional.

    Levanta `YoutubeImportError` se a URL nao tiver um video ID
    reconhecivel, se o subprocess falhar, ou se a saida nao for um JSON
    valido (yt-dlp desatualizado/pagina de erro capturada por engano)."""
    command_prefix = yt_dlp_command_resolver()
    if command_prefix is None:
        raise YtDlpNotFoundError("yt-dlp nao encontrado no sistema -- instale com 'pip install yt-dlp'")
    folder = _destination_folder(url, music_dir)
    output_template = str(folder / "preview.%(ext)s")

    result = run_subprocess(
        [
            *command_prefix,
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
    yt_dlp_command_resolver: Callable[[], Optional[List[str]]] = resolve_yt_dlp_command,
    ffmpeg_checker: Callable[[], bool] = ffmpeg_available,
    ffmpeg_location_resolver: Callable[[], Optional[str]] = resolve_ffmpeg_path,
    analyzer: Callable[[Path, Path, str], None] = analyze_song,
) -> Tuple[str, Tuple[StageDef, ...]]:
    """ETAPA 2 (Download): so' chamada depois que o jogador CONFIRMA a
    Previa (ENTER) -- baixa o audio de verdade (`--extract-audio`) na
    MESMA pasta da Previa (reusa `preview["preview_folder"]`, nunca
    busca a miniatura de novo) e IMEDIATAMENTE analisa o beatmap
    (`music_library.scan_youtube_songs`, mesma IA offline de sempre).

    Resolve `yt_dlp_command_resolver()`/checa `ffmpeg_checker()`
    PROATIVAMENTE antes do subprocess (nessa ordem -- `yt-dlp` e' a
    dependencia mais fundamental) -- `yt-dlp --extract-audio` depende do
    `ffmpeg` pra converter o audio baixado; sem qualquer um dos dois,
    levanta `YtDlpNotFoundError`/`FFmpegNotFoundError` com uma mensagem
    clara em vez de deixar o subprocess falhar com um erro interno
    criptico.

    `ffmpeg_location_resolver` e' um parametro NOVO e SEPARADO de
    `ffmpeg_checker` (nao reaproveita o mesmo -- `ffmpeg_checker`
    continua um booleano puro, mesma assinatura de sempre, pra nao
    quebrar quem ja injeta `lambda: True/False` em teste): devolve o
    CAMINHO ABSOLUTO do `ffmpeg` resolvido (sistema OU embutido em
    `bin/`, ver `resolve_ffmpeg_path`), repassado a `yt-dlp` via
    `--ffmpeg-location` -- sem isso, um `yt-dlp` que so' encontra o
    `ffmpeg` embutido (nao no PATH do sistema) nao saberia onde procurar.

    Retorna `(video_id, stages)`: `stages` e' a lista COMPLETA e
    atualizada de musicas do YouTube (inclui importacoes anteriores,
    nao so a nova) -- `HertzGameLoop._apply_download_success` substitui
    so essa fatia do catalogo, preservando fases curadas e musicas
    soltas intactas."""
    command_prefix = yt_dlp_command_resolver()
    if command_prefix is None:
        raise YtDlpNotFoundError("yt-dlp nao encontrado no sistema -- instale com 'pip install yt-dlp'")
    if not ffmpeg_checker():
        raise FFmpegNotFoundError("FFmpeg nao encontrado no sistema -- instale e garanta que esta no PATH")

    folder = Path(preview["preview_folder"])
    output_template = str(folder / "audio.%(ext)s")

    ffmpeg_location_args = []
    ffmpeg_path = ffmpeg_location_resolver()
    if ffmpeg_path is not None:
        ffmpeg_location_args = ["--ffmpeg-location", ffmpeg_path]

    result = run_subprocess(
        [
            *command_prefix,
            "--extract-audio",
            "--audio-format", "mp3",
            "--write-info-json",
            "--no-playlist",
            *ffmpeg_location_args,
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
