"""Fases data-driven: definicoes carregadas de data/stages/stages.json, nunca hardcoded em sistema."""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from hertzbeats.config import HertzConfig
from utils.path_resolver import get_resource_path


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
        campaign_id: agrupa fases CURADAS em progressoes independentes
            (ex.: "defender_core", "arcade_matrix") -- cada uma tranca/
            destranca por si (a posicao 0 de CADA campanha nunca tranca;
            comecar o Arcade nao exige terminar o Defensor). O Carrossel
            filtra por este campo (`HertzGameLoop.campaign_entries_for`);
            a ORDEM de progressao dentro de uma campanha e a ordem em
            que suas fases aparecem em `stages.json` (mesmo criterio de
            antes, so que agora por sub-lista em vez da lista inteira).
            Ignorado por musicas do jogador (`selectable_mode=True`, que
            usam o sentinela fixo "free_play" no Carrossel, nunca este
            campo). Default "default" -- so importa para fases CURADAS,
            que devem sempre declarar o proprio id explicitamente.
        description: frase curta de imersao/lore mostrada no Carrossel
            logo abaixo do nome da fase em foco (pre-renderizada como
            textura na composicao, `stage_{i}_description` -- nunca
            `font.render` por frame). String vazia (default, e o normal
            pras musicas do jogador) so' nao desenha nada.
        thumbnail_path: caminho da miniatura (`cover.jpg`/`thumbnail.webp`)
            baixada junto do audio pelo Pipeline de Importacao Direta
            (`youtube_import.py`) -- `None` (default, o normal pras fases
            curadas do repositorio) desliga toda a Estetica Reativa pra
            essa fase (fundo padrao, sem Paleta Dinamica). Carregada e
            cacheada UMA vez ao entrar no Carrossel
            (`HBPygameRenderer.cache_carousel_visuals`), nunca por frame.
        uploader: nome do canal/uploader do video, so' exibicao (Carrossel).
        known_duration_seconds: duracao EXATA do video (`metadata.json`),
            quando disponivel -- substitui a duracao APROXIMADA que
            `read_stage_bpm_and_duration` estimaria pelo beatmap pra
            musicas sem essa informacao. Tambem e' a base do Audio
            Preview (30% desse tempo, ver `HertzGameLoop._start_carousel_preview`).
            `None` (default) mantem o comportamento antigo (estimativa).
        chapters: capitulos do YouTube (`metadata.json`, `[{"start_time_seconds",
            "title"}, ...]`), 100% GAME-side (nao existe no `beatmap.json`
            da engine, mesmo espirito de `modchart_events`). Convertidos
            em eventos de Modchart sinteticos por
            `modchart.chapters_to_modchart_events` quando o titulo de um
            capitulo contem uma palavra-chave de intensidade
            (`HertzConfig.chapter_event_keywords`) -- ver Eventos de
            Gameplay via Capitulos do YouTube. Tupla vazia (default) e'
            um no-op completo.
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
    campaign_id: str = "default"
    description: str = ""
    thumbnail_path: Optional[str] = None
    uploader: str = ""
    known_duration_seconds: Optional[float] = None
    chapters: Tuple[Dict, ...] = ()


def load_stages(stages_path: str) -> Tuple[StageDef, ...]:
    """Carrega a lista ordenada de fases de `stages_path` (JSON).

    `stages_path` e' recurso SOMENTE LEITURA empacotado com o jogo --
    resolvido aqui via `get_resource_path` (raiz = `sys._MEIPASS` num
    build PyInstaller congelado, senao a raiz do projeto), nao no
    chamador: assim TODO caminho de `stages_path` (config real, teste
    com `tmp_path` absoluto -- idempotente, devolvido sem alteracao)
    passa pelo MESMO ponto antes do `open()`."""
    with open(get_resource_path(stages_path), "r", encoding="utf-8") as f:
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
                campaign_id=entry.get("campaign_id", "default"),
                description=entry.get("description", ""),
                thumbnail_path=entry.get("thumbnail_path"),
                uploader=entry.get("uploader", ""),
                known_duration_seconds=entry.get("known_duration_seconds"),
                chapters=tuple(entry.get("chapters", ())),
            )
        )
    if not stages:
        raise ValueError(f"nenhuma fase definida em {stages_path}")
    return tuple(stages)


def campaign_ids(stages: Tuple[StageDef, ...]) -> Tuple[str, ...]:
    """Ids de campanha distintos entre as fases CURADAS (`not
    selectable_mode`) de `stages`, na ordem de PRIMEIRA aparicao --
    fonte unica compartilhada por `HertzGameLoop.campaign_ids` (Carrossel)
    e `texture_bank.build_and_register_overlay_surfaces` (cabecalhos),
    pra nunca divergirem."""
    seen: list = []
    for stage in stages:
        if not stage.selectable_mode and stage.campaign_id not in seen:
            seen.append(stage.campaign_id)
    return tuple(seen)


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
    """Meta-Jogo -- Carrossel: BPM e duracao da fase, SO a partir de
    dados JA em disco (`beatmap.json` + `synth` spec, ou
    `StageDef.known_duration_seconds` quando vem de metadados reais do
    YouTube) -- nunca abre o audio real (evitaria puxar uma lib de
    decodificacao so pra mostrar duracao numa tela de selecao). Fases
    com `synth` (curadas ou re-sintetizadas): duracao EXATA
    (`bars*4*60/bpm`, a MESMA formula de `synthesize_track`). Musicas
    do jogador (`synth=None`): `known_duration_seconds` (Pipeline de
    Importacao Direta, EXATA -- vem do `metadata.json` do video) se
    disponivel, senao aproximada pelo ultimo instante de ameaca do
    beatmap + uma folga -- em ambos os casos NUNCA usada por nenhum
    calculo de jogabilidade (o `IAudioClock` real e sempre quem manda
    nisso)."""
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
    elif stage.known_duration_seconds is not None:
        duration = float(stage.known_duration_seconds)
    else:
        duration = last_hit + 3.0
    return bpm, duration
