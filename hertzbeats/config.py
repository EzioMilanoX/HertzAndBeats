"""HertzConfig: toda a afinacao de gameplay carregada de JSON (data-driven, nunca hardcoded em sistema)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class HertzConfig:
    """
    Configuracao imutavel do Hertz & Beats, carregada de
    `data/config/hertz_beats.config.json` ANTES da composicao -- mesmo
    papel da `EngineConfig` da engine, estendida com a afinacao do
    gameplay radial/ritmico. Sistemas recebem valores primitivos ja
    resolvidos no construtor; nenhum sistema le JSON em runtime.
    """

    window_width: int
    window_height: int
    window_title: str
    entity_capacity: int
    max_threats: int
    max_threats_per_frame: int
    target_fps: int

    beatmap_path: str
    track_path: str
    input_bindings_path: str

    threat_type_ids: Dict[str, int]
    threat_half_extents: Dict[str, float]
    lane_count: int

    approach_seconds: float
    spawn_radius: float
    core_half_extent: float

    perfect_window_seconds: float
    good_window_seconds: float
    miss_window_seconds: float
    aim_tolerance_degrees: float

    score_perfect: int
    score_good: int
    max_health: int
    judgment_display_seconds: float

    dash_duration_seconds: float
    dash_cooldown_seconds: float

    output_latency_seconds: float

    @property
    def center_xy(self) -> Tuple[float, float]:
        """Centro da arena (posicao do nucleo), derivado da janela."""
        return (self.window_width / 2.0, self.window_height / 2.0)

    @staticmethod
    def from_json(config_path: str) -> "HertzConfig":
        """Carrega e valida uma `HertzConfig` a partir de um arquivo JSON."""
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return HertzConfig(
            window_width=raw["window_width"],
            window_height=raw["window_height"],
            window_title=raw["window_title"],
            entity_capacity=raw["entity_capacity"],
            max_threats=raw["max_threats"],
            max_threats_per_frame=raw["max_threats_per_frame"],
            target_fps=raw["target_fps"],
            beatmap_path=raw["beatmap_path"],
            track_path=raw["track_path"],
            input_bindings_path=raw["input_bindings_path"],
            threat_type_ids=dict(raw["threat_type_ids"]),
            threat_half_extents=dict(raw["threat_half_extents"]),
            lane_count=raw["lane_count"],
            approach_seconds=raw["approach_seconds"],
            spawn_radius=raw["spawn_radius"],
            core_half_extent=raw["core_half_extent"],
            perfect_window_seconds=raw["perfect_window_seconds"],
            good_window_seconds=raw["good_window_seconds"],
            miss_window_seconds=raw["miss_window_seconds"],
            aim_tolerance_degrees=raw["aim_tolerance_degrees"],
            score_perfect=raw["score_perfect"],
            score_good=raw["score_good"],
            max_health=raw["max_health"],
            judgment_display_seconds=raw["judgment_display_seconds"],
            dash_duration_seconds=raw["dash_duration_seconds"],
            dash_cooldown_seconds=raw["dash_cooldown_seconds"],
            output_latency_seconds=raw["output_latency_seconds"],
        )
