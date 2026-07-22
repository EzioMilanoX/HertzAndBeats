"""Progresso do jogador (nao versionado): quais modificadores ja foram vencidos em cada fase/musica."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, FrozenSet

PLAYER_PROGRESS_PATH = "data/config/player_progress.json"
"""Arquivo local (gitignored, mesmo criterio de `user_settings.json`):
cada maquina guarda seu proprio progresso -- nao e um placar competitivo
versionado, so uma lembranca local de "o que voce ja venceu"."""


def load_progress(path: str = PLAYER_PROGRESS_PATH) -> Dict[str, FrozenSet[str]]:
    """Modificadores ja vencidos por `stage_id` (`StageDef.stage_id`,
    estavel tanto para fases curadas quanto para musicas do jogador --
    ver `music_library.song_slug`). Dict vazio se o arquivo ainda nao
    existir ou estiver corrompido -- uma medalha jamais derruba o jogo."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {stage_id: frozenset(modifiers) for stage_id, modifiers in raw.items()}
    except (OSError, ValueError, AttributeError, TypeError, json.JSONDecodeError):
        return {}


def record_stage_cleared(
    stage_id: str, active_modifiers, path: str = PLAYER_PROGRESS_PATH
) -> Dict[str, FrozenSet[str]]:
    """Registra que `stage_id` foi concluida com `active_modifiers`
    ligados -- UNIAO com o que ja estava salvo (nunca substitui: uma
    medalha ja ganha nao some so porque a fase foi rejogada com uma
    combinacao diferente da vez anterior). Grava de volta no disco
    (chamado UMA vez por fase concluida, na transicao para a tela de
    resultados -- nunca no loop de gameplay) e devolve o progresso
    ATUALIZADO inteiro, para o chamador nao precisar reler o arquivo."""
    progress = load_progress(path)
    merged = set(progress.get(stage_id, frozenset()))
    merged.update(active_modifiers)
    progress[stage_id] = frozenset(merged)

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with open(destination, "w", encoding="utf-8") as f:
        json.dump({sid: sorted(mods) for sid, mods in progress.items()}, f)
    return progress
