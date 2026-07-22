"""Estatisticas VITALICIAS do jogador (nao versionadas, gitignored): PERFECTs, tiros e tempo jogado acumulados."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

PLAYER_STATS_PATH = "data/config/player_lifetime_stats.json"
"""Arquivo local, MESMO criterio de `player_progress.py`/`user_settings.py`:
cada maquina acumula seu proprio historico -- nao e um placar competitivo
versionado."""

_DEFAULT_STATS: Dict[str, float] = {
    "lifetime_perfect_count": 0,
    "lifetime_shots_fired": 0,
    "lifetime_playtime_seconds": 0.0,
}


def load_stats(path: str = PLAYER_STATS_PATH) -> Dict[str, float]:
    """Estatisticas acumuladas ate agora, ou os defaults zerados se o
    arquivo ainda nao existir ou estiver corrompido -- uma estatistica
    vitalicia jamais derruba o jogo."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {
            "lifetime_perfect_count": int(raw.get("lifetime_perfect_count", 0)),
            "lifetime_shots_fired": int(raw.get("lifetime_shots_fired", 0)),
            "lifetime_playtime_seconds": float(raw.get("lifetime_playtime_seconds", 0.0)),
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return dict(_DEFAULT_STATS)


def record_match_stats(
    perfect_count: int, shots_fired: int, playtime_seconds: float, path: str = PLAYER_STATS_PATH
) -> Dict[str, float]:
    """Soma os 3 contadores de UMA partida (vencida ou perdida -- um
    PERFECT continua contando mesmo numa tentativa que terminou em Game
    Over) ao total ja salvo, grava de volta e devolve o total ATUALIZADO,
    para o chamador nao precisar reler o arquivo. Chamado UMA vez por
    partida, na transicao pra RESULTS/GAME_OVER, nunca no loop de
    gameplay."""
    stats = load_stats(path)
    stats["lifetime_perfect_count"] += int(perfect_count)
    stats["lifetime_shots_fired"] += int(shots_fired)
    stats["lifetime_playtime_seconds"] += float(playtime_seconds)

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with open(destination, "w", encoding="utf-8") as f:
        json.dump(stats, f)
    return stats
