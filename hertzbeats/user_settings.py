"""Preferencias locais do jogador (nao versionadas): hoje, a latencia de audio calibrada."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

USER_SETTINGS_PATH = "data/config/user_settings.json"
"""Arquivo local (gitignored): cada maquina tem sua propria calibracao."""


def load_user_latency(path: str = USER_SETTINGS_PATH) -> Optional[float]:
    """Latencia calibrada pelo jogador nesta maquina, ou None se ainda
    nao houve calibracao (usa-se entao o default da config)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        value = float(raw["output_latency_seconds"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    return min(max(value, 0.0), 0.30)


def save_user_latency(value: float, path: str = USER_SETTINGS_PATH) -> None:
    """Grava a latencia calibrada (chamado ao sair do jogo)."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with open(destination, "w", encoding="utf-8") as f:
        json.dump({"output_latency_seconds": round(float(value), 3)}, f)
