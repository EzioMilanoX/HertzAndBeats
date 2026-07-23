"""Resolucao de caminhos de disco pro empacotamento PyInstaller.

Chamado SO na fase de carga/inicializacao (composicao do World, tela de
Titulo/Loading) -- nunca de dentro de um `ISystem.update()` durante o
gameplay (Zero-GC: nenhuma destas funcoes e' vetorizada nem pensada pra
rodar por frame, so' uma vez por recurso ao carregar).

DOIS recursos, DOIS resolvedores (nunca o mesmo para os dois):

- `get_resource_path` -- recurso SOMENTE LEITURA empacotado DENTRO do
  executavel (`assets/`, `data/stages/stages.json`, `bin/ffmpeg*`, JSON
  curado). Frozen: raiz = `sys._MEIPASS` (pasta de extracao do
  PyInstaller -- em `--onefile`, recriada e apagada a cada execucao).

- `get_writable_data_path` -- dado GRAVAVEL que precisa sobreviver
  ENTRE execucoes (save games, `user_settings.json`) ou ser
  regenerado sob demanda (SFX/faixas sintetizadas por
  `sfx_synth.ensure_sfx`/`demo_track_synth.ensure_track`). Usar
  `get_resource_path` aqui seria um bug real: `sys._MEIPASS` e'
  apagado ao sair (perderia o progresso salvo) ou, na melhor
  hipotese, so' economizaria a re-sintese uma unica execucao. Frozen:
  raiz = a pasta que CONTEM o `.exe` (`os.path.dirname(sys.executable)`),
  a mesma pasta que o jogador ve no Explorer/Finder -- persiste e e'
  gravavel em qualquer instalacao "portable" padrao.

Ambas devolvem o `relative_path` INALTERADO se ja for absoluto (idempotentes --
seguro chamar 2x sobre o mesmo valor, e testes que ja passam caminhos
absolutos de `tmp_path` continuam funcionando sem nenhum caso especial).
"""
from __future__ import annotations

import os
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
"""Raiz do projeto quando RODANDO DO CODIGO-FONTE (nao congelado): um
nivel acima deste arquivo (`utils/path_resolver.py` -> raiz do repo) --
mesmo resultado de `os.path.abspath(...)` a partir de `__file__` pedido
no briefing, calculado uma unica vez no import (custo zero por chamada)."""


def get_resource_path(relative_path: str) -> str:
    """Resolve `relative_path` contra a raiz de um recurso EMPACOTADO
    somente-leitura: `sys._MEIPASS` se congelado (`hasattr(sys, "frozen")`),
    senao a raiz do projeto (`os.path.abspath` a partir deste arquivo)."""
    if os.path.isabs(relative_path):
        return relative_path
    if hasattr(sys, "frozen"):
        base_path = sys._MEIPASS  # atributo injetado pelo bootloader do PyInstaller
    else:
        base_path = _PROJECT_ROOT
    return os.path.join(base_path, relative_path)


def get_writable_data_path(relative_path: str) -> str:
    """Resolve `relative_path` contra a raiz de um dado GRAVAVEL que
    precisa persistir entre execucoes: a pasta do proprio `.exe` se
    congelado, senao a raiz do projeto (identico a `get_resource_path`
    fora do modo congelado -- so' diverge dele quando empacotado)."""
    if os.path.isabs(relative_path):
        return relative_path
    if hasattr(sys, "frozen"):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = _PROJECT_ROOT
    return os.path.join(base_path, relative_path)
