"""HertzConfig: toda a afinacao de gameplay carregada de JSON (data-driven, nunca hardcoded em sistema)."""
from __future__ import annotations

import dataclasses
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
    stages_path: str

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

    # -- modo de jogo (a IA dita o TEMPO; o modo dita a interpretacao
    #    espacial e de input do MESMO beatmap.json). Selecionado por
    #    fase via `overrides` (dataclasses.replace).
    game_mode: str = "defender"
    misfire_breaks_combo: bool = True
    survival_move_speed: float = 320.0
    survival_dash_speed: float = 820.0
    lane_spacing: float = 110.0
    judgment_line_offset: float = 170.0
    mixed_section_seconds: float = 12.0
    misfire_jam_seconds: float = 0.5
    dash_beat_window_seconds: float = 0.15
    survival_strike_seconds: float = 0.30

    # -- Polaridade + Parry Perfeito (Defensor, opt-in por fase) --
    polarity_enabled: bool = False
    fire_alt_action_name: str = "fire_alt"

    # -- Graze + Fever (Sobrevivencia, sempre ativo no modo) --
    graze_margin: float = 15.0
    fever_gain_per_graze: float = 0.12
    fever_decay_per_second: float = 0.05
    fever_score_multiplier: float = 2.0
    graze_score_per_hit: int = 50

    # -- Pulso de Impacto / Shockwave (Sobrevivencia, sempre ativo) --
    shockwave_pool_size: int = 5
    shockwave_duration_seconds: float = 0.2
    shockwave_max_radius: float = 260.0
    shockwave_min_radius: float = 20.0

    # -- Pistas Dinamicas (Arcade 4K, sempre ativo) --
    lane_sway_amplitude_px: float = 34.0
    lane_sway_decay_per_second: float = 2.2

    # -- Notas de Scratch (Arcade 4K, sempre ativo) --
    scratch_cluster_gap_seconds: float = 0.6
    scratch_min_cluster_size: int = 3
    scratch_hold_tail_seconds: float = 0.35
    scratch_min_energy: float = 0.12

    # -- Flow State (Arcade 4K, sempre ativo) --
    flow_combo_threshold: int = 50
    flow_volume_boost: float = 0.15
    flow_shatter_seconds: float = 0.35

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
            stages_path=raw["stages_path"],
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
            game_mode=raw.get("game_mode", "defender"),
            misfire_breaks_combo=raw.get("misfire_breaks_combo", True),
            survival_move_speed=raw.get("survival_move_speed", 320.0),
            survival_dash_speed=raw.get("survival_dash_speed", 820.0),
            lane_spacing=raw.get("lane_spacing", 110.0),
            judgment_line_offset=raw.get("judgment_line_offset", 170.0),
            mixed_section_seconds=raw.get("mixed_section_seconds", 12.0),
            misfire_jam_seconds=raw.get("misfire_jam_seconds", 0.5),
            dash_beat_window_seconds=raw.get("dash_beat_window_seconds", 0.15),
            survival_strike_seconds=raw.get("survival_strike_seconds", 0.30),
            polarity_enabled=raw.get("polarity_enabled", False),
            fire_alt_action_name=raw.get("fire_alt_action_name", "fire_alt"),
            graze_margin=raw.get("graze_margin", 15.0),
            fever_gain_per_graze=raw.get("fever_gain_per_graze", 0.12),
            fever_decay_per_second=raw.get("fever_decay_per_second", 0.05),
            fever_score_multiplier=raw.get("fever_score_multiplier", 2.0),
            graze_score_per_hit=raw.get("graze_score_per_hit", 50),
            shockwave_pool_size=raw.get("shockwave_pool_size", 5),
            shockwave_duration_seconds=raw.get("shockwave_duration_seconds", 0.2),
            shockwave_max_radius=raw.get("shockwave_max_radius", 260.0),
            shockwave_min_radius=raw.get("shockwave_min_radius", 20.0),
            lane_sway_amplitude_px=raw.get("lane_sway_amplitude_px", 34.0),
            lane_sway_decay_per_second=raw.get("lane_sway_decay_per_second", 2.2),
            scratch_cluster_gap_seconds=raw.get("scratch_cluster_gap_seconds", 0.6),
            scratch_min_cluster_size=raw.get("scratch_min_cluster_size", 3),
            scratch_hold_tail_seconds=raw.get("scratch_hold_tail_seconds", 0.35),
            scratch_min_energy=raw.get("scratch_min_energy", 0.12),
            flow_combo_threshold=raw.get("flow_combo_threshold", 50),
            flow_volume_boost=raw.get("flow_volume_boost", 0.15),
            flow_shatter_seconds=raw.get("flow_shatter_seconds", 0.35),
        )


def fit_config_to_display(
    config: HertzConfig,
    display_width: int,
    display_height: int,
    height_margin: int = 90,
    width_margin: int = 20,
) -> HertzConfig:
    """Encolhe a janela (e TODA a geometria de gameplay, na mesma
    proporcao) quando o monitor nao comporta o tamanho configurado --
    uma janela 960x960 numa tela de 768 de altura ficaria cortada, com
    HUD e metade da arena invisiveis.

    Escala uniformemente: janela, raio de spawn, nucleo e meios-tamanhos
    de ameaca. Como as VELOCIDADES derivam de distancia/tempo no spawn,
    a fisica e o julgamento continuam cravados na batida em qualquer
    escala; `approach_seconds` e as janelas temporais nao mudam.
    Retorna a config intocada se ela ja cabe na tela. Funcao PURA
    (testavel sem pygame); quem sonda o tamanho real do display e o
    adapter concreto.
    """
    usable = min(display_width - width_margin, display_height - height_margin)
    if usable <= 0 or usable >= config.window_width:
        return config

    scale = usable / float(config.window_width)
    return dataclasses.replace(
        config,
        window_width=usable,
        window_height=usable,
        spawn_radius=config.spawn_radius * scale,
        core_half_extent=config.core_half_extent * scale,
        threat_half_extents={
            name: half * scale for name, half in config.threat_half_extents.items()
        },
    )
