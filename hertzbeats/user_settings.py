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
    """Grava a latencia calibrada (chamado ao sair do jogo). Preserva
    outros campos ja salvos no MESMO arquivo (ex.: `palette_id`) --
    nunca sobrescreve o arquivo inteiro so por causa deste campo."""
    _save_field("output_latency_seconds", round(float(value), 3), path)


def _save_field(key: str, value, path: str) -> None:
    """Merge de UM campo no JSON de preferencias locais -- le o que ja
    existe (recomeca do zero se ausente/corrompido) e grava de volta com
    o campo atualizado, preservando os demais."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(destination, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raw = {}
    except (OSError, ValueError, json.JSONDecodeError):
        raw = {}
    raw[key] = value
    with open(destination, "w", encoding="utf-8") as f:
        json.dump(raw, f)


def load_user_palette_id(path: str = USER_SETTINGS_PATH) -> Optional[str]:
    """Meta-Jogo -- Paletas Cosmeticas: id da paleta escolhida pelo
    jogador nesta maquina, ou `None` se ainda nao escolheu nenhuma
    (usa-se entao `hertzbeats.palettes.DEFAULT_PALETTE_ID`). NAO valida
    contra `PALETTE_CATALOG` aqui (evita import circular -- quem le o
    valor decide o fallback se o id salvo nao existir mais)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return str(raw["palette_id"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def save_user_palette_id(palette_id: str, path: str = USER_SETTINGS_PATH) -> None:
    """Grava a paleta escolhida -- MESMO arquivo da latencia, campo
    INDEPENDENTE (preserva `output_latency_seconds` ja salvo, e
    vice-versa: `save_user_latency` preserva este campo)."""
    _save_field("palette_id", str(palette_id), path)
