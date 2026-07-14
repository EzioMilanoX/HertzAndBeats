"""Fases data-driven: definicoes carregadas de data/stages/stages.json, nunca hardcoded em sistema."""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from hertzbeats.config import HertzConfig


@dataclass(frozen=True)
class StageDef:
    """
    Definicao imutavel de UMA fase, carregada de `stages.json`.

    Atributos:
        stage_id: identificador logico (tambem usado como track_id no
            `IAudioEngine`).
        name/subtitle: textos exibidos no menu de selecao (pre-
            renderizados como texturas na composicao).
        track_path: caminho do audio da fase. String vazia = fase muda
            (usado por testes headless).
        beatmap_path: beatmap.json correspondente (gerado pela IA
            offline e VERSIONADO no repositorio).
        synth: especificacao de re-sintese deterministica da faixa
            (`{"bpm", "bars", "style"}`) -- permite nao versionar o .wav;
            `None` desabilita a re-sintese (faixa do usuario).
        beatmap_params: parametros da curadoria pos-IA usados por
            `tools/generate_stage_assets.py` (`min_gap_seconds`,
            `min_start_seconds`); ignorados em runtime.
        overrides: campos de `HertzConfig` sobrescritos nesta fase
            (approach_seconds, max_health, aim_tolerance_degrees, ...).
    """

    stage_id: str
    name: str
    subtitle: str
    track_path: str
    beatmap_path: str
    synth: Optional[Dict]
    beatmap_params: Dict
    overrides: Dict


def load_stages(stages_path: str) -> Tuple[StageDef, ...]:
    """Carrega a lista ordenada de fases de `stages_path` (JSON)."""
    with open(stages_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    stages = []
    for entry in raw["stages"]:
        stages.append(
            StageDef(
                stage_id=entry["stage_id"],
                name=entry["name"],
                subtitle=entry.get("subtitle", ""),
                track_path=entry["track_path"],
                beatmap_path=entry["beatmap_path"],
                synth=entry.get("synth"),
                beatmap_params=dict(entry.get("beatmap", {})),
                overrides=dict(entry.get("overrides", {})),
            )
        )
    if not stages:
        raise ValueError(f"nenhuma fase definida em {stages_path}")
    return tuple(stages)


def resolve_stage_config(base_config: HertzConfig, stage: StageDef) -> HertzConfig:
    """Deriva a `HertzConfig` efetiva da fase: caminhos de beatmap/faixa
    da fase + `overrides` aplicados sobre a configuracao base. Um campo
    desconhecido em `overrides` e um erro de dados (TypeError), nunca
    silenciosamente ignorado."""
    return dataclasses.replace(
        base_config,
        beatmap_path=stage.beatmap_path,
        track_path=stage.track_path,
        **stage.overrides,
    )
