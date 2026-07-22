"""Fases data-driven: definicoes carregadas de data/stages/stages.json, nunca hardcoded em sistema."""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
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
        tutorial_steps: passos de instrucao exibidos durante o gameplay
            (`{"until_seconds", "text"}`, ordenados). Nao-vazio marca a
            fase como tutorial: o beatmap e AUTORAL (didatico) e
            `tools/generate_stage_assets.py` nao o sobrescreve com IA.
        selectable_mode: True nas musicas do jogador -- o MODO de jogo e
            escolhido no menu (A/D alternam) em vez de fixado por
            `overrides`; fases construidas do repositorio mantem a
            afinacao curada por modo.
        modchart_events: eventos GLOBAIS de coreografia (`{"type": ...}`,
            ordem livre -- cada `parse_*_events` filtra e ordena so o seu
            proprio tipo por tempo). Dado 100% GAME-side (nao existe no
            `beatmap.json` da engine). Arcade 4K (`game_mode == "lanes"`):
            "swap"/"reverse_scroll"/"distraction". Defensor
            (`game_mode == "defender"`): "vision_tunnel" (Colapso de
            Visao, puramente cosmetico, `VisionTunnelSystem`), lido so
            quando "vision_tunnel" esta em `active_modifiers`.
        active_modifiers: lista de Mecanicas Modulares ligadas nesta fase
            (`{"polarity", "telegraph_rings", "orbital_shields",
            "twin_threats", "orbital_eclipses", "overload",
            "vision_tunnel", "holds", "bombs", "heal", ...}` --
            catalogo completo em `HertzConfig.active_modifiers`).
            SUBSTITUI a lista inteira da fase base a cada
            `resolve_stage_config` (nunca mesclada com nenhum default) --
            uma fase que quer 3 mecanicas lista as 3 explicitamente.
        b_side_name: Progressao de Campanha -- Lado B/Remix: `None`
            (default) significa que esta fase NAO tem uma variante mais
            cruel; uma string (ex.: "LADO B: RUPTURA") habilita o toggle
            no Pre-Voo (so fases CURADAS -- `selectable_mode=False`) e
            vira o subtitulo mostrado quando o Lado B esta escolhido.
            NAO reprocessa a musica pela IA (o beatmap.json e o MESMO em
            disco) -- reusa a MESMA tese ja demonstrada pela campanha
            (fases 3-5 reaproveitam o beatmap com overrides/modifiers
            cada vez mais duros): o Lado B e so outra composicao em cima
            do mesmo tempo extraido.
        b_side_overrides: campos de `HertzConfig` aplicados SOMENTE
            quando o Lado B esta escolhido (substitui `overrides`, nunca
            mesclado com ele).
        b_side_active_modifiers: `active_modifiers` aplicados SOMENTE
            quando o Lado B esta escolhido (substitui `active_modifiers`,
            mesmo criterio -- nunca mesclado).
    """

    stage_id: str
    name: str
    subtitle: str
    track_path: str
    beatmap_path: str
    synth: Optional[Dict]
    beatmap_params: Dict
    overrides: Dict
    tutorial_steps: Tuple[Dict, ...] = ()
    selectable_mode: bool = False
    modchart_events: Tuple[Dict, ...] = ()
    active_modifiers: Tuple[str, ...] = ()
    b_side_name: Optional[str] = None
    b_side_overrides: Dict = field(default_factory=dict)
    b_side_active_modifiers: Tuple[str, ...] = ()


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
                tutorial_steps=tuple(entry.get("tutorial_steps", ())),
                modchart_events=tuple(entry.get("modchart_events", ())),
                active_modifiers=tuple(entry.get("active_modifiers", ())),
                b_side_name=entry.get("b_side_name"),
                b_side_overrides=dict(entry.get("b_side_overrides", {})),
                b_side_active_modifiers=tuple(entry.get("b_side_active_modifiers", ())),
            )
        )
    if not stages:
        raise ValueError(f"nenhuma fase definida em {stages_path}")
    return tuple(stages)


def resolve_stage_config(base_config: HertzConfig, stage: StageDef) -> HertzConfig:
    """Deriva a `HertzConfig` efetiva da fase: caminhos de beatmap/faixa
    da fase + `active_modifiers` da fase (substitui por completo o valor
    base -- nunca mesclado) + `overrides` aplicados sobre a configuracao
    base. Um campo desconhecido em `overrides` e um erro de dados
    (TypeError), nunca silenciosamente ignorado. `overrides` NAO deve
    conter `active_modifiers` (usar o campo dedicado da fase) -- faria
    `dataclasses.replace` reclamar de argumento duplicado."""
    return dataclasses.replace(
        base_config,
        beatmap_path=stage.beatmap_path,
        track_path=stage.track_path,
        active_modifiers=stage.active_modifiers,
        **stage.overrides,
    )


def read_stage_bpm_and_duration(stage: StageDef) -> Tuple[float, float]:
    """Meta-Jogo -- Carrossel: BPM e duracao aproximada da fase, SO a
    partir de dados JA em disco (`beatmap.json` + `synth` spec) -- nunca
    abre o audio real (evitaria puxar uma lib de decodificacao so pra
    mostrar duracao numa tela de selecao). Fases com `synth` (curadas ou
    re-sintetizadas): duracao EXATA (`bars*4*60/bpm`, a MESMA formula de
    `synthesize_track`). Musicas do jogador (`synth=None`): aproximada
    pelo ultimo instante de ameaca do beatmap + uma folga -- boa o
    bastante pra exibicao, NUNCA usada por nenhum calculo de
    jogabilidade (o `IAudioClock` real e sempre quem manda nisso)."""
    try:
        with open(stage.beatmap_path, "r", encoding="utf-8") as f:
            beatmap = json.load(f)
        bpm = float(beatmap.get("bpm", 120.0))
        threats = beatmap.get("threats", [])
        last_hit = max((float(t["timestamp_seconds"]) for t in threats), default=0.0)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        bpm = 120.0
        last_hit = 0.0

    if stage.synth is not None:
        synth_bpm = float(stage.synth.get("bpm", bpm))
        bars = int(stage.synth.get("bars", 0))
        duration = bars * 4 * (60.0 / synth_bpm) if bars > 0 else last_hit + 3.0
    else:
        duration = last_hit + 3.0
    return bpm, duration
