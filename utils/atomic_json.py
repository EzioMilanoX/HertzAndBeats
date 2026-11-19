"""Escrita ATOMICA de JSON local (save, estatisticas, preferencias).

Motivacao: os 3 arquivos gravaveis do jogo (`player_progress.json`,
`player_stats.json`, `user_settings.json`) eram escritos com
`open(destino, "w")`, que TRUNCA o arquivo antes de escrever o conteudo
novo. A janela entre o truncamento e o `json.dump` completo e' pequena,
mas nao e' zero -- um crash do jogo, um `kill`, ou uma queda de energia
ali deixa o arquivo existente e VAZIO (ou pela metade). Como todo
carregador do jogo trata JSON invalido como "comeca do zero"
(gracioso, e correto), o efeito pratico e' o progresso do jogador ser
apagado silenciosamente, sem nenhum erro na tela.

A correcao e' o padrao write-and-rename:

  1. escreve o conteudo INTEIRO num arquivo temporario ao lado;
  2. `flush` + `os.fsync` -- forca os bytes ao disco antes de qualquer
     troca de nome (sem isso, o rename pode chegar ao disco ANTES dos
     dados num crash de sistema, e o arquivo "novo" aparece vazio);
  3. `os.replace` -- substituicao ATOMICA, e a razao de nao usar
     `os.rename`: no Windows, `rename` levanta se o destino ja existe,
     enquanto `replace` sobrescreve atomicamente nas duas plataformas.

O arquivo antigo permanece intacto e valido durante todo o processo: se
qualquer passo falhar, o jogador perde a partida recem-terminada, nunca
o historico.

Roda so' na transicao de fim de partida / troca de preferencia -- nunca
dentro de um `ISystem.update()`, entao o `fsync` (custoso) nao toca o
hot-path de gameplay.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def write_json_atomically(destination: Path, payload: Any) -> None:
    """Grava `payload` como JSON em `destination`, atomicamente.

    `destination` precisa ja estar resolvido (via
    `utils.path_resolver.get_writable_data_path`) -- esta funcao nao
    resolve caminhos, so escreve, para nao esconder resolucao de caminho
    dentro de uma primitiva de IO.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # o temporario vive na MESMA pasta do destino de proposito: `os.replace`
    # so e' atomico dentro do mesmo sistema de arquivos, e um %TEMP% em
    # outro volume quebraria essa garantia justamente no Windows.
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(payload, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, destination)
    except BaseException:
        # nunca deixar um .tmp orfao pra tras; o arquivo REAL segue intacto
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
