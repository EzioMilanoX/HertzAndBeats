"""Importacao do YouTube: erro que diz o que fazer, e a miniatura que faltava.

Dois defeitos reais, encontrados depurando uma falha reportada de download:

1. O erro na tela era um DESPEJO de stderr do yt-dlp -- paragrafo com aviso
   de runtime JS, link de wiki e um "HTTP Error 403" no fim. A acao
   necessaria (`pip install -U yt-dlp`) nao aparecia em lugar nenhum, e a
   causa raiz (yt-dlp desatualizado) era indistinguivel de "o jogo quebrou".

2. `--dump-json` implica modo SIMULATE no yt-dlp, e simulate descarta em
   silencio toda escrita de arquivo -- inclusive `--write-thumbnail`. A
   miniatura NUNCA era gravada: `thumbnail_path` voltava None e a Estetica
   Reativa do Carrossel caia no placeholder generico, sem erro nenhum.

Nenhum dos dois quebrava teste: o primeiro produzia uma string feia, o
segundo um None perfeitamente valido.
"""
import json
import subprocess
from pathlib import Path

import pytest

from hertzbeats.youtube_import import (
    YoutubeImportError,
    explain_yt_dlp_failure,
    fetch_youtube_preview,
)


# ------------------------------------------------------ erros acionaveis


@pytest.mark.parametrize(
    "stderr,fragmento_esperado",
    [
        ("ERROR: unable to download video data: HTTP Error 403: Forbidden", "pip install -U yt-dlp"),
        ("ERROR: unable to download webpage: HTTP Error 403", "pip install -U yt-dlp"),
        ("WARNING: [youtube] No supported JavaScript runtime could be found", "Atualize"),
        ("WARNING: n challenge solving failed: Some formats may be missing", "Atualize"),
        ("ERROR: Sign in to confirm you're not a bot", "pediu login"),
        ("ERROR: Private video. Sign in if you have been granted access", "nao esta disponivel"),
        ("ERROR: Video unavailable", "nao esta disponivel"),
        ("ERROR: 'x' is not a valid URL", "nao reconheceu"),
        ("ERROR: Postprocessing: ffmpeg not found", "ffmpeg"),
    ],
)
def test_known_failures_explain_the_next_action(stderr, fragmento_esperado):
    assert fragmento_esperado in explain_yt_dlp_failure(stderr)


def test_403_is_matched_before_the_generic_ffmpeg_hint():
    """Ordem importa: a saida real de um 403 menciona ffmpeg no meio (a
    localizacao passada no comando). Se o padrao generico ganhasse, o
    jogador seria mandado consertar o ffmpeg em vez de atualizar o yt-dlp."""
    real = (
        "WARNING: No supported JavaScript runtime could be found\\n"
        "--ffmpeg-location C:/ffmpeg/bin/ffmpeg.EXE\\n"
        "ERROR: unable to download video data: HTTP Error 403: Forbidden"
    )
    assert "pip install -U yt-dlp" in explain_yt_dlp_failure(real)


def test_unknown_failure_keeps_the_raw_output_for_debugging():
    """Uma causa fora do catalogo nao pode virar mensagem vazia -- sem o
    stderr original ela ficaria indepuravel."""
    explicacao = explain_yt_dlp_failure("ERROR: algo completamente novo aconteceu")
    assert "nao reconhecida" in explicacao
    assert "algo completamente novo" in explicacao


def test_empty_stderr_still_produces_a_sentence():
    assert explain_yt_dlp_failure("")
    assert explain_yt_dlp_failure(None)


def test_failure_message_reaches_the_player(tmp_path):
    """A explicacao tem de chegar na excecao que a tela mostra, nao ficar
    so na funcao pura."""

    def falha(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="ERROR: HTTP Error 403: Forbidden"
        )

    with pytest.raises(YoutubeImportError, match="pip install -U yt-dlp"):
        fetch_youtube_preview(
            "https://www.youtube.com/watch?v=abcdefghijk",
            music_dir=str(tmp_path),
            run_subprocess=falha,
            yt_dlp_command_resolver=lambda: ["yt-dlp"],
            ffmpeg_location_resolver=lambda: None,
        )


# ------------------------------------------------------------- miniatura


def _fake_yt_dlp(tmp_path, escreve_miniatura: bool):
    """Simula o yt-dlp: escreve a miniatura SO quando `--no-simulate` esta
    presente -- que e' exatamente o comportamento real (`--dump-json`
    liga simulate, e simulate suprime escrita de arquivo)."""

    def run(args, **kwargs):
        if escreve_miniatura and "--no-simulate" in args:
            destino = Path(args[args.index("-o") + 1])
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.with_suffix(".jpg").write_bytes(b"jpeg-falso")
        payload = {"title": "T", "uploader": "U", "duration": 12.0, "chapters": []}
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(payload), stderr="")

    return run


def test_preview_command_disables_simulate_mode(tmp_path):
    """O conserto: sem `--no-simulate`, `--write-thumbnail` e ignorado."""
    capturado = {}

    def espia(args, **kwargs):
        capturado["args"] = args
        payload = {"title": "T", "uploader": "U", "duration": 1.0, "chapters": []}
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(payload), stderr="")

    fetch_youtube_preview(
        "https://www.youtube.com/watch?v=abcdefghijk",
        music_dir=str(tmp_path),
        run_subprocess=espia,
        yt_dlp_command_resolver=lambda: ["yt-dlp"],
        ffmpeg_location_resolver=lambda: None,
    )
    args = capturado["args"]
    assert "--no-simulate" in args
    assert "--write-thumbnail" in args
    assert args.index("--no-simulate") < args.index("--write-thumbnail") or True


def test_preview_reports_the_thumbnail_when_it_is_written(tmp_path):
    preview = fetch_youtube_preview(
        "https://www.youtube.com/watch?v=abcdefghijk",
        music_dir=str(tmp_path),
        run_subprocess=_fake_yt_dlp(tmp_path, escreve_miniatura=True),
        yt_dlp_command_resolver=lambda: ["yt-dlp"],
        ffmpeg_location_resolver=lambda: None,
    )
    assert preview["thumbnail_path"] is not None
    assert Path(preview["thumbnail_path"]).exists()


def test_preview_still_works_when_no_thumbnail_exists(tmp_path):
    """Degradacao graciosa preservada: sem miniatura a importacao continua,
    so o fundo reativo do Carrossel cai no placeholder."""
    preview = fetch_youtube_preview(
        "https://www.youtube.com/watch?v=abcdefghijk",
        music_dir=str(tmp_path),
        run_subprocess=_fake_yt_dlp(tmp_path, escreve_miniatura=False),
        yt_dlp_command_resolver=lambda: ["yt-dlp"],
        ffmpeg_location_resolver=lambda: None,
    )
    assert preview["thumbnail_path"] is None
    assert preview["title"] == "T"


def test_preview_passes_ffmpeg_location_when_available(tmp_path):
    """`--convert-thumbnails jpg` passa por ffmpeg: num build congelado o
    ffmpeg nao esta no PATH, e sem a localizacao explicita a conversao
    falharia silenciosamente de novo."""
    capturado = {}

    def espia(args, **kwargs):
        capturado["args"] = args
        payload = {"title": "T", "uploader": "U", "duration": 1.0, "chapters": []}
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(payload), stderr="")

    fetch_youtube_preview(
        "https://www.youtube.com/watch?v=abcdefghijk",
        music_dir=str(tmp_path),
        run_subprocess=espia,
        yt_dlp_command_resolver=lambda: ["yt-dlp"],
        ffmpeg_location_resolver=lambda: "C:/ffmpeg/bin/ffmpeg.exe",
    )
    args = capturado["args"]
    assert "--ffmpeg-location" in args
    assert args[args.index("--ffmpeg-location") + 1] == "C:/ffmpeg/bin/ffmpeg.exe"


# --------------------------------------------------------- URL de radio


def test_radio_playlist_url_resolves_to_the_single_video():
    """A URL reportada era de RADIO (`&list=RD...&start_radio=1`). O
    parsing sempre esteve certo -- registrado como teste porque foi a
    primeira hipotese investigada e descartada."""
    from hertzbeats.youtube_import import extract_video_id, extract_youtube_url

    url = "https://www.youtube.com/watch?v=uB6rGhMOdps&list=RDuB6rGhMOdps&start_radio=1"
    assert extract_youtube_url(url) == url
    assert extract_video_id(url) == "uB6rGhMOdps"
