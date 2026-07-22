"""GameLoop da engine estendido com o fluxo de partida: menu de fases, pausa, derrota e resultados."""
from __future__ import annotations

import dataclasses
import random
import time
from typing import Optional, Tuple

import numpy as np

from ouroboros.bootstrap.game_loop import (
    _EMPTY_F32,
    _EMPTY_I16,
    _EMPTY_RGBA,
    _EMPTY_U32,
    _EMPTY_XY,
    GameLoop,
)
from ouroboros.core.memory.component_pool import intersect_entity_indices
from ouroboros.interfaces.audio_clock import IAudioClock
from ouroboros.interfaces.audio_engine import IAudioEngine
from ouroboros.interfaces.input_provider import IInputProvider
from ouroboros.interfaces.renderer import IRenderer

from hertzbeats.audio.demo_track_synth import ensure_track
from hertzbeats.bootstrap.rhythm_composition_root import (
    ComposedGame,
    compose_world,
    lane_center_positions,
)
from hertzbeats.components.schemas import MODE_TAG_LANES
from hertzbeats.config import HertzConfig
from hertzbeats.game_state import RANK_ORDER, compute_rank
from hertzbeats.player_progress import PLAYER_PROGRESS_PATH, load_progress, record_stage_cleared
from hertzbeats.player_stats import PLAYER_STATS_PATH, load_stats, record_match_stats
from hertzbeats.stages import StageDef, read_stage_bpm_and_duration, resolve_stage_config
from hertzbeats.palettes import DEFAULT_PALETTE_ID, PALETTE_CATALOG, unlocked_palette_ids
from hertzbeats.user_settings import USER_SETTINGS_PATH, save_user_latency, save_user_palette_id

FLOW_TITLE = "title"
FLOW_HUB = "hub"
FLOW_CAROUSEL = "carousel"
FLOW_PREFLIGHT = "preflight"
FLOW_VAULT = "vault"
FLOW_CALIBRATION = "calibration"
FLOW_PLAYING = "playing"
FLOW_PAUSED = "paused"
FLOW_GAME_OVER = "game_over"
FLOW_RESULTS = "results"

HUB_CATEGORIES = ("campaign", "free_play", "vault", "calibration")
"""O Novo Fluxo de Menus (Experiencia Arcade): 4 categorias grandes do
HUB principal, nesta ORDEM fixa -- `HertzGameLoop._hub_cursor` e um
indice nesta tupla. "campaign"/"free_play" levam ao Carrossel
(`FLOW_CAROUSEL`, filtrado por `StageDef.selectable_mode`); "vault" e
"calibration" sao telas dedicadas proprias."""

_RESULTS_GRACE_SECONDS = 1.0
"""Pausa dramatica entre a ultima ameaca resolvida e a tela de resultados."""

_LATENCY_STEP_SECONDS = 0.01
_LATENCY_MAX_SECONDS = 0.30
_NOTICE_SECONDS = 1.6


def compute_duck_multiplier(
    duck_timer_seconds: float, duck_duration_seconds: float, duck_volume_fraction: float
) -> float:
    """Audio Ducking: fracao MULTIPLICATIVA do volume da faixa (1.0 =
    normal). `duck_timer_seconds` (contagem regressiva, MESMO idioma dos
    outros timers do jogo) em `duck_duration_seconds`: `duck_volume_fraction`
    (MINIMO) no instante do erro, subindo linearmente ate `1.0` conforme
    o timer esgota. Fora da janela de ducking (`duck_timer_seconds <= 0`),
    e sempre `1.0` -- um no-op transparente. Pura e sem estado, testavel
    sem `HertzGameLoop`/audio real."""
    if duck_timer_seconds <= 0.0 or duck_duration_seconds <= 0.0:
        return 1.0
    recovered_fraction = 1.0 - (duck_timer_seconds / duck_duration_seconds)
    return duck_volume_fraction + (1.0 - duck_volume_fraction) * recovered_fraction

MODIFIER_SCORE_BONUS = {
    "roleta_russa": 0.30,
    "orbital_eclipses": 0.20,
    "twin_threats": 0.20,
    "orbital_shields": 0.15,
    "overload": 0.15,
    "vision_tunnel": 0.15,
    "bombs": 0.15,
    "polarity": 0.10,
    "holds": 0.10,
    "telegraph_rings": 0.0,
    "heal": -0.05,
}
"""Meta-Jogo -- Multiplicador de Pontuacao (tela de Pre-Voo): bonus
FRACIONARIO por modifier ligado, somado a 1.0. Modifiers mais cruéis
(Eclipses, Gemeos, Overload, Colapso de Visao, Bombas) valem mais --
incentiva o jogador a ligar as mecanicas dificeis pra tentar um Rank SS
com pontuacao maior. "roleta_russa" (1 de vida, Game Over no primeiro
erro) e' o MAIOR bonus do catalogo -- o risco mais alto tambem. "heal"
reduz levemente (ajuda o jogador, entao vale menos); "telegraph_rings" e
puramente decorativo (0). Modifiers ausentes daqui (ex.: nenhum -- todo
modifier do catalogo tem uma entrada) valem 0 por seguranca
(`dict.get(m, 0.0)`)."""

PRACTICE_MODE_SCORE_PENALTY = 0.5
"""Meta-Jogo: Modo Treino ("Facil / Dano Reduzido") custa -50% na
pontuacao -- ele já reduz densidade E remove risco de vida, um desafio
bem menor merece uma pontuacao bem menor."""

MIN_SCORE_MULTIPLIER = 0.1
"""Piso do multiplicador -- nunca deixa a pontuacao cair a zero/negativa
mesmo empilhando Modo Treino com poucos modifiers."""


def compute_score_multiplier(active_modifiers, practice_mode: bool) -> float:
    """Meta-Jogo -- Multiplicador de Pontuacao: pura e sem estado,
    testavel sem `HertzGameLoop`. Chamada tanto para a PREVIA ao vivo na
    tela de Pre-Voo (`HertzGameLoop._current_score_multiplier`) quanto
    para o valor final aplicado na composicao (`HertzConfig.
    score_multiplier`, resolvido em `_compose_stage`) -- a MESMA formula
    em ambos os lugares, nunca calculada duas vezes de jeitos diferentes."""
    multiplier = 1.0 + sum(MODIFIER_SCORE_BONUS.get(m, 0.0) for m in active_modifiers)
    if practice_mode:
        multiplier -= PRACTICE_MODE_SCORE_PENALTY
    return max(MIN_SCORE_MULTIPLIER, multiplier)


GAME_MODE_ROW = "game_mode"
"""Sentinela: SEMPRE a PRIMEIRA linha do menu de opcoes do seletor de
minigame (`modifier_rows_for_game_mode`) -- linha de MULTIPLA ESCOLHA
(A/D alternam Defensor/Arcade 4K), nao um modifier booleano. Nao e uma
string de `HertzConfig.active_modifiers` de verdade (nunca aparece
dentro de `chosen_modifiers(...)`), so um marcador de linha consumido
por `_advance_menu_options`/`hb_pygame_renderer._draw_overlay` -- os
dois precisam concordar no MESMO literal (`hb_pygame_renderer.py` nao
importa este modulo pra evitar dependencia invertida adapter->loop, so
duplica a string com um comentario cruzado)."""

HEAVY_MECHANIC_ROW = "heavy_mechanic"
"""Sentinela: SEMPRE a SEGUNDA linha -- outra de MULTIPLA ESCOLHA (A/D
alternam `HEAVY_MECHANIC_VALUES_BY_GAME_MODE[game_mode]`). Substitui os
antigos checkboxes independentes "polarity"/"holds": as duas mecanicas
sao MUTUAMENTE EXCLUSIVAS (reusam o mesmo `threat_type` "pesada" com
significados incompativeis -- Hold-Start vs Parry -- e o
`JudgmentSystem` checa Hold ANTES de Parry, entao os dois ligados ao
mesmo tempo fariam toda pesada virar Hold silenciosamente, nunca Parry)
-- uma multipla escolha de 3 valores torna a exclusividade estrutural
(nunca dá pra escolher os dois), em vez de dois booleanos com logica de
"desliga o outro" escondida."""

START_ROW = "start"
"""Sentinela: SEMPRE a ULTIMA linha -- o botao de ACAO "Iniciar Fase".
So inicia a fase (`_start_stage`) quando ESPACO/ENTER e pressionado com
o cursor EXATAMENTE aqui -- em qualquer outra linha, ESPACO/ENTER agem
sobre AQUELA linha (liga/desliga um modifier booleano; nas linhas de
multipla escolha, ESPACO/ENTER nao fazem nada, so A/D alteram o valor)."""

DEFENDER_MODIFIER_ROWS = (
    "telegraph_rings",
    "orbital_shields",
    "twin_threats",
    "orbital_eclipses",
    "overload",
    "roleta_russa",
)
LANES_MODIFIER_ROWS = ("roleta_russa",)
"""Linhas de modifier BOOLEANO (checkbox) mostradas por `game_mode`,
ENTRE `HEAVY_MECHANIC_ROW` e `START_ROW` -- "holds"/"polarity" NAO
aparecem aqui (viraram a multipla escolha `HEAVY_MECHANIC_ROW`).
"vision_tunnel", "bombs" e "heal" ficam de fora: so fazem algo
visivel em cima de dado especifico de fase CURADA (eventos
`modchart_events`; ameacas desses tipos no beatmap) que uma musica do
jogador nunca tem (`music_library.py` sempre cria
`StageDef(modchart_events=())` e o mapeador offline nunca emite
`rhythm_threat_bomb`/`rhythm_threat_heal`) -- ligar so o modifier seria
um checkbox que nao muda NADA na tela. "roleta_russa" (Meta-Jogo) e' a
excecao: nao depende de nenhum dado de fase, so forca `max_health=1` na
composicao (ver `_compose_stage`) -- funciona identico nos 2 modos,
entao e' a UNICA linha booleana que o Arcade 4K tem hoje."""

HEAVY_MECHANIC_VALUES_BY_GAME_MODE = {
    "defender": ("none", "polarity", "holds"),
    "lanes": ("none", "holds"),
}
"""Valores ciclaveis (A/D) de `HEAVY_MECHANIC_ROW` por `game_mode` --
"polarity" so existe no Defensor (Arcade 4K nunca teve a mecanica)."""

_HEAVY_MECHANIC_DISPLAY_ORDER = ("none", "polarity", "holds")
"""Ordem FIXA de ciclagem (independente do `game_mode` atual) -- usada
por `_cycle_heavy_mechanic` pra sempre andar na mesma direcao logica
(Nenhuma -> Polaridade -> Holds -> Nenhuma), mesmo quando o subconjunto
valido do modo atual pula "polarity" (Arcade 4K)."""


def modifier_rows_for_game_mode(game_mode: str) -> Tuple[str, ...]:
    """Linhas do menu de opcoes pro `game_mode` dado: SEMPRE
    `GAME_MODE_ROW`, `HEAVY_MECHANIC_ROW`, os modifiers booleanos
    daquele modo, e por fim `START_ROW`."""
    rows = LANES_MODIFIER_ROWS if game_mode == "lanes" else DEFENDER_MODIFIER_ROWS
    return (GAME_MODE_ROW, HEAVY_MECHANIC_ROW) + rows + (START_ROW,)


class HertzGameLoop(GameLoop):
    """
    `GameLoop` da engine estendido com a maquina de estados da partida --
    O Novo Fluxo de Menus (Experiencia Arcade):

        TITLE -> (confirmar) -> HUB -> CAMPANHA/FREE PLAY -> CAROUSEL
        CAROUSEL -> (confirmar) -> PREFLIGHT -> (START) -> PLAYING <-> PAUSED
        HUB -> ARQUIVOS -> VAULT (so-leitura)
        HUB -> CALIBRACAO -> CALIBRATION (metronomo + tecla no tempo)
        PLAYING -> vida zerada -> GAME_OVER -> (R) repete / (M) HUB
        PLAYING -> fase limpa  -> RESULTS  -> (ENTER) proxima fase /
                                              (R) repete / (M) HUB

    Papel arquitetural: o fluxo NAO vive em nenhum `ISystem` -- sistemas
    julgam UMA fase em andamento; trocar/reiniciar fase e recomposicao
    (fase de carregamento, onde alocar e permitido). Cada
    `_start_stage` recompoe o `World` inteiro via `compose_world` (pools
    novas, `GameState` zerado, cursor do spawner em 0) e reinicia a
    faixa do zero -- nenhum estado de partida anterior sobrevive por
    acidente.

    PAUSA SEM DRIFT: pausar congela a musica (`pause_track`, quando o
    backend oferece -- `pygame.mixer.music.pause` congela `get_pos`).
    Como TODOS os sistemas ritmicos leem exclusivamente o `IAudioClock`,
    o gameplay inteiro congela em sincronia; ao retomar, nada precisa
    ser re-calibrado. `world.step` simplesmente nao e chamado enquanto
    pausado/menu/telas finais -- mas o frame continua sendo renderizado
    (arena visivel ao fundo dos overlays).

    Os overlays (title/hub/carousel/preflight/vault/calibration/
    paused/game_over/results) sao desenhados pelo adapter concreto via
    `set_overlay` (superficies pre-renderizadas na composicao); com um
    renderer sem esse metodo (ex.: `NullRenderer` nos testes headless),
    o fluxo roda identico, apenas sem apresentacao.
    """

    def __init__(
        self,
        base_config: HertzConfig,
        stages: Tuple[StageDef, ...],
        renderer: IRenderer,
        input_provider: IInputProvider,
        audio_engine: IAudioEngine,
        audio_clock: IAudioClock,
        title_track_path: Optional[str] = None,
        calibration_track_path: Optional[str] = None,
        player_progress_path: str = PLAYER_PROGRESS_PATH,
        player_stats_path: str = PLAYER_STATS_PATH,
        user_settings_path: str = USER_SETTINGS_PATH,
        palette_id: str = DEFAULT_PALETTE_ID,
    ) -> None:
        """Compoe a fase 0 imediatamente (sem tocar musica) para que a
        Tela de Titulo ja tenha uma arena renderizavel ao fundo.
        `title_track_path`/`calibration_track_path` (opcionais -- `None`
        e um no-op gracioso, usado pelos testes headless) sao faixas
        JA GARANTIDAS em disco por `RhythmCompositionRoot.build()`.
        `player_progress_path`/`player_stats_path`/`user_settings_path`
        (default os saves reais do jogador) existem para os testes
        isolarem em `tmp_path` -- sem isso, qualquer teste que completa
        uma fase OU calibra a latencia (Calibracao dedicada) escreveria
        nos saves de VERDADE do jogo. `palette_id` (Meta-Jogo -- Paletas
        Cosmeticas) e' a escolha JA RESOLVIDA pelo `RhythmCompositionRoot.
        build()` a partir de `user_settings.load_user_palette_id` -- as
        cores em si ja vem prontas em `base_config.threat_blue_rgb`/
        `threat_pink_rgb`, este parametro so serve para o Vault
        mostrar/ciclar QUAL id esta selecionado."""
        self._base_config = base_config
        self._stages = stages
        self._audio_clock = audio_clock
        self._input_provider = input_provider  # tambem setado por GameLoop.__init__
        self._audio_engine = audio_engine  # idem -- precisa existir ANTES de _compose_stage(0) abaixo
        self._title_track_path = title_track_path
        self._calibration_track_path = calibration_track_path
        self._loaded_stage = 0
        self._flow = FLOW_TITLE
        self._results_grace = 0.0
        self._notice_key: Optional[str] = None
        self._notice_timer = 0.0
        self._chosen_game_mode: dict = {}  # fase selectable_mode -> "defender"/"lanes"
        self._chosen_heavy_mechanic: dict = {}  # fase selectable_mode -> "none"/"polarity"/"holds"
        self._chosen_modifiers: dict = {}  # fase selectable_mode -> frozenset dos modifiers booleanos ligados
        self._menu_cursor_index: dict = {}  # fase selectable_mode -> indice da linha em foco no Pre-Voo
        self._practice_mode: dict = {}  # fase selectable_mode -> Modo Treino ligado?
        self._composed: Optional[ComposedGame] = None
        self._was_in_flow = False
        self._was_frozen = False
        self._last_miss_count_seen = 0  # Audio Ducking: baseline pra detectar um NOVO miss/dano
        self._duck_timer_seconds = 0.0
        self._results_rank = "-"  # Meta-Jogo -- Rank: calculado ao entrar em FLOW_RESULTS
        self._player_progress_path = player_progress_path
        self._player_progress = load_progress(player_progress_path)  # lido 1x, atualizado in-memory
        self._player_stats_path = player_stats_path
        self._player_stats = load_stats(player_stats_path)  # Meta-Jogo -- Estatisticas Globais, idem
        self._session_playtime_seconds = 0.0  # tempo desta tentativa, zerado a cada RESULTS/GAME_OVER
        self._user_settings_path = user_settings_path
        self._palette_id = palette_id if palette_id in PALETTE_CATALOG else DEFAULT_PALETTE_ID

        # O Novo Fluxo de Menus (Experiencia Arcade)
        self._hub_cursor = 0
        self._carousel_category: Optional[str] = None  # "campaign" | "free_play"
        self._carousel_index_by_category = {"campaign": 0, "free_play": 0}
        self._preflight_stage_index: Optional[int] = None
        self._calibration_taps: list = []
        self._calibration_last_offset_seconds: Optional[float] = None

        composed = self._compose_stage(0)
        super().__init__(
            composed.world,
            renderer,
            input_provider,
            audio_engine,
            target_fps=base_config.target_fps,
        )
        self._apply_playfield()
        self._enter_title()

    @property
    def flow(self) -> str:
        """Estado atual do fluxo de partida (telemetria/testes)."""
        return self._flow

    @property
    def composed(self) -> ComposedGame:
        """Composicao da fase atualmente carregada."""
        return self._composed

    @property
    def loaded_stage(self) -> int:
        """Indice da fase atualmente composta/carregada."""
        return self._loaded_stage

    @property
    def hub_cursor(self) -> int:
        """Categoria em foco no HUB principal (indice em `HUB_CATEGORIES`)."""
        return self._hub_cursor

    @property
    def carousel_category(self) -> Optional[str]:
        """Categoria do Carrossel ATUAL ("campaign"/"free_play"), ou
        `None` fora do Carrossel."""
        return self._carousel_category

    # -- carga/troca de fase (fase de carregamento: alocacao permitida) --

    def chosen_game_mode(self, stage_index: int) -> str:
        """Modo (Defensor/Arcade 4K) escolhido no menu pra uma fase
        `selectable_mode` (as musicas do jogador); fases curadas usam o
        modo dos `overrides` do `stages.json`. Default "defender"."""
        return self._chosen_game_mode.get(stage_index, "defender")

    def chosen_heavy_mechanic(self, stage_index: int) -> str:
        """Valor ATUAL da multipla escolha `HEAVY_MECHANIC_ROW":
        "none"/"polarity"/"holds". Default "none" -- nenhuma mecanica
        pesada ligada."""
        return self._chosen_heavy_mechanic.get(stage_index, "none")

    def chosen_modifiers(self, stage_index: int) -> frozenset:
        """`active_modifiers` efetivos pro seletor de minigame: os
        modifiers booleanos marcados MAIS o que `chosen_heavy_mechanic`
        resolver (se nao for "none") -- a leitura publica ja funde os 2,
        `_compose_stage` nao precisa saber que "polarity"/"holds" vem de
        uma multipla escolha em vez de um checkbox independente."""
        modifiers = set(self._chosen_modifiers.get(stage_index, frozenset()))
        heavy_mechanic = self.chosen_heavy_mechanic(stage_index)
        if heavy_mechanic != "none":
            modifiers.add(heavy_mechanic)
        return frozenset(modifiers)

    def modifier_rows(self, stage_index: int) -> Tuple[str, ...]:
        """Linhas do menu de opcoes pro `game_mode` ATUAL dessa fase
        (muda se o jogador alternar Defensor/Arcade 4K)."""
        return modifier_rows_for_game_mode(self.chosen_game_mode(stage_index))

    def menu_cursor_index(self, stage_index: int) -> int:
        """Indice da linha em foco no menu de opcoes (0 =
        `GAME_MODE_ROW`), sempre dentro dos limites da lista ATUAL de
        linhas (que pode ter menos linhas no Arcade 4K que no Defensor)
        -- o `% len(rows)` AQUI e a unica reenquadracao necessaria, ja
        que so e possivel trocar de `game_mode` com o cursor JA em
        `GAME_MODE_ROW` (indice 0, presente em qualquer lista)."""
        rows = self.modifier_rows(stage_index)
        return self._menu_cursor_index.get(stage_index, 0) % len(rows)

    def _cycle_game_mode(self, stage_index: int, direction: int) -> None:
        """A/D na linha `GAME_MODE_ROW`: alterna Defensor<->Arcade 4K.
        Se a mecanica pesada escolhida deixar de existir no modo novo
        (ex.: "polarity" nao existe no Arcade 4K), reseta pra "none" --
        nunca deixa `chosen_heavy_mechanic` num valor invalido pro modo
        atual."""
        modes = ("defender", "lanes")
        current = modes.index(self.chosen_game_mode(stage_index))
        new_mode = modes[(current + direction) % len(modes)]
        self._chosen_game_mode[stage_index] = new_mode
        if self.chosen_heavy_mechanic(stage_index) not in HEAVY_MECHANIC_VALUES_BY_GAME_MODE[new_mode]:
            self._chosen_heavy_mechanic[stage_index] = "none"

    def _cycle_heavy_mechanic(self, stage_index: int, direction: int) -> None:
        """A/D na linha `HEAVY_MECHANIC_ROW`: percorre so os valores
        validos pro `game_mode` ATUAL (`_HEAVY_MECHANIC_DISPLAY_ORDER`
        filtrada), entao "polarity" nunca aparece ciclando no Arcade
        4K."""
        stage_index_mode = self.chosen_game_mode(stage_index)
        order = [v for v in _HEAVY_MECHANIC_DISPLAY_ORDER if v in HEAVY_MECHANIC_VALUES_BY_GAME_MODE[stage_index_mode]]
        current = self.chosen_heavy_mechanic(stage_index)
        if current not in order:
            current = order[0]
        index = order.index(current)
        self._chosen_heavy_mechanic[stage_index] = order[(index + direction) % len(order)]

    def _toggle_modifier(self, stage_index: int, modifier_name: str) -> None:
        """Liga/desliga UM modifier booleano (nunca "polarity"/"holds",
        que agora sao a multipla escolha `HEAVY_MECHANIC_ROW` -- ver
        `_cycle_heavy_mechanic`)."""
        current = set(self._chosen_modifiers.get(stage_index, frozenset()))
        if modifier_name in current:
            current.discard(modifier_name)
        else:
            current.add(modifier_name)
        self._chosen_modifiers[stage_index] = frozenset(current)

    def practice_mode_on(self, stage_index: int) -> bool:
        """Modo Treino ligado para uma fase `selectable_mode` (musicas
        do jogador) -- densidade de onsets reduzida e sem dano de vida.
        Fases curadas do repositorio nunca tem Modo Treino (so a fase
        escolhida no menu, tecla T)."""
        return self._practice_mode.get(stage_index, False)

    def _compose_stage(self, stage_index: int) -> ComposedGame:
        """Recompoe o `World` inteiro para a fase `stage_index` e garante
        que a faixa exista (re-sintese deterministica se necessario)."""
        stage = self._stages[stage_index]
        stage_config = resolve_stage_config(self._base_config, stage)
        if stage.selectable_mode:
            stage_config = dataclasses.replace(
                stage_config,
                practice_mode=self._practice_mode.get(stage_index, False),
                game_mode=self.chosen_game_mode(stage_index),
                active_modifiers=tuple(self.chosen_modifiers(stage_index)),
            )
        # Meta-Jogo -- Multiplicador de Pontuacao: resolvido AQUI, depois
        # que `active_modifiers`/`practice_mode` ja estao no valor FINAL
        # (curada ou escolhida no Pre-Voo) -- a MESMA formula da previa
        # ao vivo (`_current_score_multiplier`), nunca calculada por
        # acerto em tempo real (so uma vez, na composicao). "roleta_russa"
        # forca 1 de vida MAXIMA aqui -- nenhum sistema novo precisa saber
        # do modifier, MISS ja custa exatamente 1 de vida nos 2 modos.
        max_health = 1 if "roleta_russa" in stage_config.active_modifiers else stage_config.max_health
        stage_config = dataclasses.replace(
            stage_config,
            max_health=max_health,
            score_multiplier=compute_score_multiplier(
                frozenset(stage_config.active_modifiers), stage_config.practice_mode
            ),
        )
        if stage.track_path:
            ensure_track(stage.track_path, stage.synth)
        composed = compose_world(
            stage_config,
            self._input_provider,
            self._audio_clock,
            tutorial_steps=stage.tutorial_steps,
            stage_ordinal=stage_index,
            audio_engine=self._audio_engine,
            modchart_events=stage.modchart_events,
        )
        self._composed = composed
        self._stage_config = stage_config
        self._loaded_stage = stage_index
        self._world = composed.world  # GameLoop renderiza sempre o world da fase carregada
        return composed

    def _apply_playfield(self) -> None:
        """Sincroniza a decoracao de arena do renderer com o MODO da fase
        carregada (no-op com renderer sem suporte, ex. NullRenderer)."""
        renderer = getattr(self, "_renderer", None)
        if renderer is None or not hasattr(renderer, "set_playfield"):
            return
        config = self._stage_config
        mode = config.game_mode
        if mode == "defender":
            center_x, center_y = config.center_xy
            renderer.set_playfield(
                "radial",
                center_x=center_x,
                center_y=center_y,
                spawn_radius=config.spawn_radius,
                judgment_radius=config.core_half_extent
                + config.threat_half_extents.get("rhythm_threat_basic", 10.0),
                width=config.window_width,
                height=config.window_height,
            )
        elif mode == "lanes":
            renderer.set_playfield(
                "lanes",
                lane_xs=lane_center_positions(config).tolist(),
                lane_half_width=config.lane_spacing * 0.42,
                judgment_y=config.window_height - config.judgment_line_offset,
                width=config.window_width,
                height=config.window_height,
            )
        else:
            renderer.set_playfield(None)

    def _sync_defender_playfield(self) -> None:
        """Colapso de Visao (Defensor, "vision_tunnel"): mantem o campo
        de luz desenhado (`renderer.set_playfield("radial", ...,
        tunnel_radius=...)`) em sincronia com `GameState.tunnel_radius`
        -- sem isso, o overlay ficaria parado no raio ORIGINAL enquanto
        o Colapso ja encolheu o campo de verdade. `judgment_radius`
        continua publicado aqui tambem por conveniencia (identico ao
        valor FIXO desde a composicao -- ver `GameState.
        current_judgment_radius`, que nenhum sistema muta mais). Mesma
        familia de `_sync_lane_playfield` (Modcharts do Arcade 4K).
        No-op fora do Defensor ou com um renderer sem suporte a
        playfield."""
        if self._composed is None or self._stage_config.game_mode != "defender":
            return
        renderer = getattr(self, "_renderer", None)
        if renderer is None or not hasattr(renderer, "set_playfield"):
            return
        config = self._stage_config
        center_x, center_y = config.center_xy
        renderer.set_playfield(
            "radial",
            center_x=center_x,
            center_y=center_y,
            spawn_radius=config.spawn_radius,
            judgment_radius=self._composed.game_state.current_judgment_radius,
            tunnel_radius=self._composed.game_state.tunnel_radius,
            width=config.window_width,
            height=config.window_height,
        )

    def _sync_lane_playfield(self) -> None:
        """Modcharts (Arcade 4K): mantem a decoracao de fundo das
        colunas (`renderer.set_playfield("lanes", ...)`) em sincronia
        com a posicao ATUAL calculada pelo `LaneChoreographySystem`
        (Swap com Lerp + Pistas Dinamicas) e, no eixo Y, pelo
        `ReverseScrollSystem` (Inversao de Gravidade) -- sem isso, a
        decoracao de fundo ficaria parada enquanto notas/receptores se
        movem por cima dela. No-op fora do modo Arcade 4K ou com um
        renderer sem suporte a playfield (ex. NullRenderer)."""
        if self._composed is None or self._stage_config.game_mode != "lanes":
            return
        choreography = self._composed.lane_choreography_system
        renderer = getattr(self, "_renderer", None)
        if choreography is None or renderer is None or not hasattr(renderer, "set_playfield"):
            return
        config = self._stage_config
        geometry_y = self._composed.lane_geometry_y
        judgment_y = (
            float(geometry_y[1]) if geometry_y is not None
            else config.window_height - config.judgment_line_offset
        )
        renderer.set_playfield(
            "lanes",
            lane_xs=choreography.current_lane_xs.tolist(),
            lane_half_width=config.lane_spacing * 0.42,
            judgment_y=judgment_y,
            width=config.window_width,
            height=config.window_height,
        )

    def _flow_base_volume(self) -> float:
        """Volume 'normal' da faixa fora do Flow State: um pouco abaixo
        do maximo, para que a entrada no Flow tenha um SWELL real ate
        1.0 (ver `HBPygameAudioEngine.set_track_volume`)."""
        return max(0.0, 1.0 - self._stage_config.flow_volume_boost)

    def _start_stage(self, stage_index: int) -> None:
        """Recompoe a fase e inicia a musica do zero -> PLAYING."""
        self._compose_stage(stage_index)
        self._apply_playfield()
        stage = self._stages[stage_index]
        if stage.track_path:
            self._audio_engine.load_track(stage.stage_id, stage.track_path)
            self._audio_engine.play_track(stage.stage_id)
        self._was_in_flow = False
        # Audio Ducking: fase nova, GameState.miss_count novo -- nunca
        # carrega um "erro" da fase ANTERIOR para a de agora (o valor
        # real e recalculado no proximo `_sync_track_volume`, chamado
        # ainda neste mesmo frame).
        self._last_miss_count_seen = 0
        self._duck_timer_seconds = 0.0
        if hasattr(self._renderer, "set_flow_mode"):
            self._renderer.set_flow_mode(False)
        self._flow = FLOW_PLAYING
        self._results_grace = 0.0

    def start_stage(self, stage_index: int) -> None:
        """Entrada publica: pula direto pra `stage_index` (usada pelo
        atalho de CLI `--stage`), sem passar por Titulo/HUB/Carrossel/
        Pre-Voo."""
        self._start_stage(stage_index % len(self._stages))

    def _stop_music(self) -> None:
        stage = self._stages[self._loaded_stage]
        if stage.track_path:
            self._audio_engine.stop_track(stage.stage_id)

    def _pause_music(self) -> None:
        if hasattr(self._audio_engine, "pause_track"):
            self._audio_engine.pause_track()

    def _resume_music(self) -> None:
        if hasattr(self._audio_engine, "resume_track"):
            self._audio_engine.resume_track()

    # -- maquina de estados por frame ------------------------------------

    def _adjust_latency(self, direction: int) -> None:
        """Calibracao AO VIVO da latencia de audio (teclas +/-): se as
        ameacas parecem chegar ANTES do som, aumente; DEPOIS, diminua.
        O novo valor vale imediatamente (spawner/julgamento leem o
        relogio compensado) e e persistido ao sair do jogo."""
        current = self._audio_clock.get_output_latency_seconds()
        new_value = current + direction * _LATENCY_STEP_SECONDS
        new_value = min(max(round(new_value, 2), 0.0), _LATENCY_MAX_SECONDS)
        self._audio_clock.calibrate_latency(new_value)
        self._notice_key = f"latency_{int(round(new_value * 100))}"
        self._notice_timer = _NOTICE_SECONDS

    def _handle_latency_keys(self) -> None:
        inp = self._input_provider
        if inp.is_action_pressed("latency_up"):
            self._adjust_latency(+1)
        if inp.is_action_pressed("latency_down"):
            self._adjust_latency(-1)

    def advance_frame(self, delta_time: float) -> None:
        """Um frame do fluxo: trata as acoes de meta-jogo do estado atual
        e, apenas em PLAYING, avanca a simulacao (`world.step`)."""
        if self._notice_timer > 0.0:
            self._notice_timer -= delta_time
        if self._flow in (FLOW_PLAYING, FLOW_PAUSED):
            self._handle_latency_keys()
        if self._flow == FLOW_TITLE:
            self._advance_title()
        elif self._flow == FLOW_HUB:
            self._advance_hub()
        elif self._flow == FLOW_CAROUSEL:
            self._advance_carousel()
        elif self._flow == FLOW_PREFLIGHT:
            self._advance_preflight()
        elif self._flow == FLOW_VAULT:
            self._advance_vault()
        elif self._flow == FLOW_CALIBRATION:
            self._advance_calibration()
        elif self._flow == FLOW_PLAYING:
            self._advance_playing(delta_time)
        elif self._flow == FLOW_PAUSED:
            self._advance_paused()
        elif self._flow == FLOW_GAME_OVER:
            self._advance_game_over()
        elif self._flow == FLOW_RESULTS:
            self._advance_results()

    # -- Tela de Titulo ---------------------------------------------------

    def _enter_title(self) -> None:
        """Titulo pulsando com `beat_phase` + BGM em loop (faixa JA
        garantida por `RhythmCompositionRoot.build()`, opcional -- `None`
        e um no-op gracioso, o caso comum dos testes headless)."""
        self._flow = FLOW_TITLE
        if self._title_track_path and hasattr(self._audio_engine, "load_track"):
            self._audio_engine.load_track("title", self._title_track_path)
            self._audio_engine.play_track("title", loop=True)

    def _advance_title(self) -> None:
        inp = self._input_provider
        if inp.is_action_pressed("confirm") or inp.is_action_pressed("fire"):
            if self._title_track_path and hasattr(self._audio_engine, "stop_track"):
                self._audio_engine.stop_track("title")
            self._flow = FLOW_HUB
        elif inp.is_action_pressed("pause"):
            self.stop()  # ESC na Tela de Titulo encerra o jogo (e a tela mais externa)

    # -- HUB Principal ------------------------------------------------------

    def _advance_hub(self) -> None:
        inp = self._input_provider
        if inp.is_action_pressed("menu_down"):
            self._hub_cursor = (self._hub_cursor + 1) % len(HUB_CATEGORIES)
        if inp.is_action_pressed("menu_up"):
            self._hub_cursor = (self._hub_cursor - 1) % len(HUB_CATEGORIES)

        if inp.is_action_pressed("confirm") or inp.is_action_pressed("fire"):
            category = HUB_CATEGORIES[self._hub_cursor]
            if category in ("campaign", "free_play"):
                self._carousel_category = category
                self._flow = FLOW_CAROUSEL
            elif category == "vault":
                self._flow = FLOW_VAULT
            elif category == "calibration":
                self._enter_calibration()
        elif inp.is_action_pressed("pause"):
            self._enter_title()  # ESC no HUB volta pra Tela de Titulo (nunca encerra o jogo daqui)

    # -- Carrossel de Musicas ------------------------------------------------

    def campaign_entries(self):
        """Lista `(indice_original, StageDef)` das fases CURADAS
        (`not selectable_mode`), na mesma ordem de `self._stages` -- a
        ordem em que aparecem em `stages.json` E a ordem de progressao
        da Campanha."""
        return [(i, s) for i, s in enumerate(self._stages) if not s.selectable_mode]

    def free_play_entries(self):
        """Lista `(indice_original, StageDef)` das musicas do jogador
        (`selectable_mode`)."""
        return [(i, s) for i, s in enumerate(self._stages) if s.selectable_mode]

    def carousel_entries(self):
        """Entradas da categoria do Carrossel ATUAL (`campaign`/`free_play`)."""
        if self._carousel_category == "campaign":
            return self.campaign_entries()
        return self.free_play_entries()

    def carousel_index(self) -> int:
        """Posicao em foco DENTRO da lista filtrada da categoria atual
        (nao um indice de `self._stages`)."""
        return self._carousel_index_by_category.get(self._carousel_category, 0)

    def carousel_focused_stage_index(self) -> Optional[int]:
        """Indice ORIGINAL em `self._stages` da entrada em foco no
        Carrossel, ou `None` se a categoria estiver vazia (ex.: nenhuma
        musica ainda em `musicas/`)."""
        entries = self.carousel_entries()
        if not entries:
            return None
        return entries[self.carousel_index() % len(entries)][0]

    def is_campaign_entry_locked(self, position: int) -> bool:
        """Progressao da Campanha: a fase curada na posicao `position`
        (dentro da lista SO de fases curadas) fica trancada ate a
        ANTERIOR ter sido vencida ao menos uma vez
        (`stage_id in player_progress`) -- a primeira posicao (o
        tutorial) nunca tranca."""
        if position <= 0:
            return False
        entries = self.campaign_entries()
        previous_stage_id = entries[position - 1][1].stage_id
        return previous_stage_id not in self._player_progress

    def _advance_carousel(self) -> None:
        inp = self._input_provider
        entries = self.carousel_entries()
        if not entries:
            if inp.is_action_pressed("pause"):
                self._flow = FLOW_HUB
            return

        index = self.carousel_index() % len(entries)
        if inp.is_action_pressed("menu_down"):
            index = (index + 1) % len(entries)
        if inp.is_action_pressed("menu_up"):
            index = (index - 1) % len(entries)
        self._carousel_index_by_category[self._carousel_category] = index

        if inp.is_action_pressed("confirm") or inp.is_action_pressed("fire"):
            if self._carousel_category == "campaign" and self.is_campaign_entry_locked(index):
                self._notice_key = "stage_locked"
                self._notice_timer = _NOTICE_SECONDS
            else:
                original_index, _stage = entries[index]
                self._preflight_stage_index = original_index
                self._flow = FLOW_PREFLIGHT
        elif inp.is_action_pressed("pause"):
            self._flow = FLOW_HUB

    # -- Pre-Voo (Modificadores + Multiplicador de Pontuacao) ----------------

    def _current_score_multiplier(self, stage_index: int) -> float:
        """Previa AO VIVO do Multiplicador de Pontuacao pra tela de
        Pre-Voo -- MESMA formula (`compute_score_multiplier`) aplicada de
        verdade na composicao (`_compose_stage`), nunca recalculada de
        um jeito diferente."""
        stage = self._stages[stage_index]
        if stage.selectable_mode:
            modifiers = self.chosen_modifiers(stage_index)
            practice = self.practice_mode_on(stage_index)
        else:
            stage_config = resolve_stage_config(self._base_config, stage)
            modifiers = frozenset(stage_config.active_modifiers)
            practice = stage_config.practice_mode
        return compute_score_multiplier(modifiers, practice)

    def _advance_preflight(self) -> None:
        """Tela de Pre-Voo: musicas do jogador (`selectable_mode`) tem o
        painel de opcoes completo e interativo (`_advance_preflight_options`,
        o antigo "menu de opcoes" -- MESMA logica, agora sua PROPRIA tela
        em vez de aninhada); fases curadas mostram os modifiers FIXOS
        (so leitura -- a Campanha existe justamente pela dificuldade
        curada e crescente) com um unico botao interativo, START."""
        inp = self._input_provider
        stage_index = self._preflight_stage_index
        stage = self._stages[stage_index]

        if stage.selectable_mode:
            if inp.is_action_pressed("toggle_practice"):
                self._practice_mode[stage_index] = not self.practice_mode_on(stage_index)
            self._advance_preflight_options(stage_index)
        else:
            if inp.is_action_pressed("confirm") or inp.is_action_pressed("fire"):
                self._start_stage(stage_index)
            elif inp.is_action_pressed("pause"):
                self._flow = FLOW_CAROUSEL

    def _advance_preflight_options(self, stage_index: int) -> None:
        """W/S navegam as linhas do painel; A/D alteram a linha de
        multipla escolha focada (`GAME_MODE_ROW`/`HEAVY_MECHANIC_ROW`,
        nao fazem nada nas demais); ESPACO/ENTER agem sobre a linha
        focada (liga/desliga um modifier booleano, ou inicia a fase se
        for `START_ROW` -- SO nesse caso, nunca em outra linha); ESC
        volta pro Carrossel sem iniciar nada."""
        inp = self._input_provider
        rows = self.modifier_rows(stage_index)

        if inp.is_action_pressed("menu_down"):
            self._menu_cursor_index[stage_index] = (self.menu_cursor_index(stage_index) + 1) % len(rows)
        if inp.is_action_pressed("menu_up"):
            self._menu_cursor_index[stage_index] = (self.menu_cursor_index(stage_index) - 1) % len(rows)

        row = rows[self.menu_cursor_index(stage_index)]
        direction = 0
        if inp.is_action_pressed("menu_right"):
            direction = 1
        if inp.is_action_pressed("menu_left"):
            direction = -1
        if direction != 0:
            if row == GAME_MODE_ROW:
                self._cycle_game_mode(stage_index, direction)
            elif row == HEAVY_MECHANIC_ROW:
                self._cycle_heavy_mechanic(stage_index, direction)

        if inp.is_action_pressed("confirm") or inp.is_action_pressed("fire"):
            if row == START_ROW:
                self._start_stage(stage_index)
            elif row not in (GAME_MODE_ROW, HEAVY_MECHANIC_ROW):
                self._toggle_modifier(stage_index, row)
        elif inp.is_action_pressed("pause"):
            self._flow = FLOW_CAROUSEL  # ESC volta pro Carrossel, sem iniciar nada

    # -- Arquivos (Vault) -----------------------------------------------------

    def vault_stats(self) -> dict:
        """Meta-Jogo -- Arquivos (Vault): agregados simples sobre
        `player_progress.json` -- quantas fases distintas ja foram
        vencidas (de quantas existem ao todo), quantas medalhas de
        modificador ao todo, e quantas vezes cada Rank ja foi o MELHOR
        alcancado nalguma fase -- mais as Estatisticas Globais VITALICIAS
        (`player_lifetime_stats.json`, cache em `self._player_stats`)."""
        rank_counts = {rank: 0 for rank in RANK_ORDER}
        total_medals = 0
        for entry in self._player_progress.values():
            total_medals += len(entry["modifiers"])
            if entry["best_rank"] in rank_counts:
                rank_counts[entry["best_rank"]] += 1
        return {
            "stages_cleared": len(self._player_progress),
            "total_stages": len(self._stages),
            "total_medals": total_medals,
            "rank_counts": rank_counts,
            "lifetime_perfect_count": self._player_stats["lifetime_perfect_count"],
            "lifetime_shots_fired": self._player_stats["lifetime_shots_fired"],
            "lifetime_playtime_seconds": self._player_stats["lifetime_playtime_seconds"],
            "palette_id": self._palette_id,
            "unlocked_palettes": unlocked_palette_ids(self._player_progress),
        }

    @property
    def palette_id(self) -> str:
        """Meta-Jogo -- Paletas Cosmeticas: id ATUALMENTE selecionado
        (`hertzbeats.palettes.PALETTE_CATALOG`)."""
        return self._palette_id

    def _cycle_palette(self, direction: int) -> None:
        """A/D no Vault: percorre so as paletas JA DESBLOQUEADAS
        (`unlocked_palette_ids`, Rank ja alcancado nalguma fase/musica) --
        aplica as cores em `self._base_config` (vale a partir da PROXIMA
        fase carregada, nunca muda a fase em andamento) e persiste
        IMEDIATAMENTE, mesmo criterio da Calibracao dedicada."""
        unlocked = unlocked_palette_ids(self._player_progress)
        if not unlocked:
            return
        current = self._palette_id if self._palette_id in unlocked else unlocked[0]
        index = (unlocked.index(current) + direction) % len(unlocked)
        self._palette_id = unlocked[index]
        palette = PALETTE_CATALOG[self._palette_id]
        self._base_config = dataclasses.replace(
            self._base_config,
            threat_blue_rgb=palette["threat_blue_rgb"],
            threat_pink_rgb=palette["threat_pink_rgb"],
        )
        save_user_palette_id(self._palette_id, path=self._user_settings_path)

    def _advance_vault(self) -> None:
        inp = self._input_provider
        if inp.is_action_pressed("menu_right"):
            self._cycle_palette(+1)
        if inp.is_action_pressed("menu_left"):
            self._cycle_palette(-1)
        if inp.is_action_pressed("confirm") or inp.is_action_pressed("fire") or inp.is_action_pressed("pause"):
            self._flow = FLOW_HUB

    # -- Calibracao (metronomo + tecla no tempo) -----------------------------

    def _enter_calibration(self) -> None:
        self._calibration_taps = []
        self._calibration_last_offset_seconds = None
        self._flow = FLOW_CALIBRATION
        if self._calibration_track_path and hasattr(self._audio_engine, "load_track"):
            self._audio_engine.load_track("calibration", self._calibration_track_path)
            self._audio_engine.play_track("calibration", loop=True)

    def _stop_calibration_track(self) -> None:
        if self._calibration_track_path and hasattr(self._audio_engine, "stop_track"):
            self._audio_engine.stop_track("calibration")

    def calibration_progress(self) -> Tuple[int, int, Optional[float]]:
        """`(taps_dados, taps_alvo, ultimo_offset_segundos)` -- pro
        renderer mostrar um contador `N/alvo` e um feedback de
        cedo/tarde por tecla."""
        return (
            len(self._calibration_taps),
            self._base_config.calibration_target_taps,
            self._calibration_last_offset_seconds,
        )

    def _advance_calibration(self) -> None:
        """Bate a tecla `confirm`/`fire` no tempo do metronomo
        (`calibration_bpm`, faixa dedicada) -- cada aperto grava o
        DESVIO assinado ate a batida mais proxima (negativo = cedo,
        positivo = tarde). Apos `calibration_target_taps` batidas, a
        MEDIA dos desvios ajusta `IAudioClock.calibrate_latency` (clamp
        em `[0, _LATENCY_MAX_SECONDS]`, mesmo limite de `_adjust_latency`)
        e persiste via `save_user_latency` IMEDIATAMENTE -- uma tela
        dedicada de calibracao deve confirmar o resultado na hora, nao
        so ao fechar o jogo."""
        inp = self._input_provider
        if inp.is_action_pressed("pause"):
            self._stop_calibration_track()
            self._flow = FLOW_HUB
            return
        if not (inp.is_action_pressed("confirm") or inp.is_action_pressed("fire")):
            return

        beat_duration = 60.0 / self._base_config.calibration_bpm
        now_seconds = self._audio_clock.now_seconds()
        phase = now_seconds % beat_duration
        offset = phase if phase <= beat_duration / 2.0 else phase - beat_duration
        self._calibration_taps.append(offset)
        self._calibration_last_offset_seconds = offset

        if len(self._calibration_taps) < self._base_config.calibration_target_taps:
            return
        average_offset = sum(self._calibration_taps) / len(self._calibration_taps)
        current_latency = self._audio_clock.get_output_latency_seconds()
        new_latency = min(max(round(current_latency + average_offset, 3), 0.0), _LATENCY_MAX_SECONDS)
        self._audio_clock.calibrate_latency(new_latency)
        save_user_latency(new_latency, path=self._user_settings_path)
        self._notice_key = f"latency_{int(round(new_latency * 100))}"
        self._notice_timer = _NOTICE_SECONDS
        self._stop_calibration_track()
        self._calibration_taps = []
        self._flow = FLOW_HUB

    def _advance_playing(self, delta_time: float) -> None:
        inp = self._input_provider
        if inp.is_action_pressed("pause"):
            self._flow = FLOW_PAUSED
            self._pause_music()
            return

        # Meta-Jogo -- Estatisticas Globais: tempo REAL de gameplay desta
        # tentativa, acumulado so enquanto PLAYING de verdade avanca (nao
        # soma tempo pausado) -- dobrado ao total vitalicio em
        # `_accumulate_lifetime_stats`, no instante exato em que a
        # tentativa termina (RESULTS ou GAME_OVER), nunca por frame.
        self._session_playtime_seconds += delta_time

        self._world.step(delta_time)

        state = self._composed.game_state
        self._advance_flow_state(state)
        if state.health <= 0:
            self._accumulate_lifetime_stats()
            self._flow = FLOW_GAME_OVER
            self._stop_music()
            return

        # Fase concluida quando TODOS os spawners consumiram seus
        # beatmaps (o Hibrido tem dois) E (todas as ameacas foram
        # resolvidas OU a musica acabou). O segundo caso e o guard
        # anti-softlock: quando a faixa termina, o relogio de audio
        # congela (pygame get_pos() volta -1 -> 0) e qualquer ameaca
        # restante ficaria eternamente sem veredito -- a fase encerra
        # mesmo assim, pela carencia em tempo real de frame.
        threat_pool = self._composed.memory_manager.get_pool("rhythm_threat")
        music_over = not self._audio_clock.is_playing()
        if self._composed.all_spawners_finished and (threat_pool.count == 0 or music_over):
            self._results_grace += delta_time
            if self._results_grace >= _RESULTS_GRACE_SECONDS:
                # Meta-Jogo -- Rank: calculado UMA vez aqui, no instante
                # exato da transicao (nao a cada frame na tela de
                # resultados -- os contadores ja pararam de mudar).
                self._results_rank = compute_rank(state.perfect_count, state.good_count, state.miss_count)
                self._save_stage_medal()
                self._accumulate_lifetime_stats()
                self._flow = FLOW_RESULTS
        else:
            self._results_grace = 0.0

    def _accumulate_lifetime_stats(self) -> None:
        """Meta-Jogo -- Estatisticas Globais: soma os contadores desta
        tentativa (vencida OU perdida -- um PERFECT continua contando
        mesmo num Game Over) ao total vitalicio em `player_lifetime_stats.
        json`, e zera o acumulador de tempo desta tentativa. "Tiros
        Disparados" reusa os contadores JA existentes do julgamento
        (`perfect_count`/`good_count`/`miss_count`/`misfire_count`) em vez
        de instrumentar um contador novo no caminho de input -- todo tiro
        disparado numa ameaca de verdade vira PERFECT/GOOD/MISS, e todo
        tiro fora do tempo vira misfire; a soma dos 4 e' exatamente
        "quantas vezes o jogador atirou"."""
        state = self._composed.game_state
        shots_fired = state.perfect_count + state.good_count + state.miss_count + state.misfire_count
        self._player_stats = record_match_stats(
            perfect_count=state.perfect_count,
            shots_fired=shots_fired,
            playtime_seconds=self._session_playtime_seconds,
            path=self._player_stats_path,
        )
        self._session_playtime_seconds = 0.0

    def _save_stage_medal(self) -> None:
        """Meta-Jogo -- Medalhas + Rank Maximo: registra os
        `active_modifiers` da fase RECEM-CONCLUIDA e o `_results_rank`
        desta partida em `player_progress.json` (uniao de modifiers,
        Rank so melhora -- ver `record_stage_cleared`) -- chamado UMA
        vez, no instante exato da transicao pra resultados. Atualiza o
        cache em-memoria (`self._player_progress`) na mesma chamada, pro
        Carrossel/Vault ja mostrarem o glifo/rank novo sem precisar reler
        o arquivo."""
        stage = self._stages[self._loaded_stage]
        self._player_progress = record_stage_cleared(
            stage.stage_id, self._stage_config.active_modifiers,
            rank=self._results_rank, path=self._player_progress_path,
        )

    def _advance_flow_state(self, state) -> None:
        """Flow State ("vidro quebrado", Arcade 4K): detecta a
        TRANSICAO de combo cruzando `flow_combo_threshold` (o
        `UIRenderSystem` ja decide isso por conta propria a cada frame
        para o HUD -- aqui so replicamos a mesma condicao para acionar os
        efeitos que vivem FORA do ECS: escurecimento de fundo do
        renderer; a saida (um Miss zera o combo) dispara o aviso de
        "vidro quebrado". O VOLUME da faixa (swell do Flow + Audio
        Ducking) e recalculado TODO frame por `_sync_track_volume`, nao
        aqui -- so a transicao dispara o resto (fundo/aviso).

        Sem HUD, o jogador perde a nocao de progresso alem do limiar --
        `tier` (`combo // limiar`, 0 fora do Flow) e sincronizado com o
        renderer TODO frame (nao so na transicao: o tier sobe DENTRO do
        Flow, sem cruzar o limiar de novo), pulsando a linha de
        julgamento a cada 50 acertos extras."""
        config = self._stage_config
        if config.game_mode != "lanes":
            return
        in_flow_now = state.combo_count >= config.flow_combo_threshold
        if hasattr(self._renderer, "set_flow_tier"):
            tier = (state.combo_count // config.flow_combo_threshold) if in_flow_now else 0
            self._renderer.set_flow_tier(tier)
        if in_flow_now == self._was_in_flow:
            return
        if hasattr(self._renderer, "set_flow_mode"):
            self._renderer.set_flow_mode(in_flow_now)
        if not in_flow_now:
            self._notice_key = "flow_shatter"
            self._notice_timer = config.flow_shatter_seconds
        self._was_in_flow = in_flow_now

    def _advance_paused(self) -> None:
        inp = self._input_provider
        if inp.is_action_pressed("pause"):
            self._flow = FLOW_PLAYING
            self._resume_music()
        elif inp.is_action_pressed("to_menu"):
            self._stop_music()
            self._flow = FLOW_HUB

    def _advance_game_over(self) -> None:
        inp = self._input_provider
        if inp.is_action_pressed("retry"):
            self._start_stage(self._loaded_stage)
        elif inp.is_action_pressed("to_menu") or inp.is_action_pressed("pause"):
            self._flow = FLOW_HUB

    def _advance_results(self) -> None:
        inp = self._input_provider
        if inp.is_action_pressed("confirm"):
            self._start_stage((self._loaded_stage + 1) % len(self._stages))
        elif inp.is_action_pressed("retry"):
            self._start_stage(self._loaded_stage)
        elif inp.is_action_pressed("to_menu") or inp.is_action_pressed("pause"):
            self._stop_music()
            self._flow = FLOW_HUB

    # -- laco principal ---------------------------------------------------

    def _sync_overlay(self) -> None:
        """Publica o estado do fluxo no renderer concreto (no-op com um
        renderer sem suporte a overlay, ex. NullRenderer). O Carrossel
        so publica a entrada EM FOCO (o "carrossel" mostra uma musica
        por vez no centro da tela, ver o pedido) -- nunca a lista
        inteira."""
        if hasattr(self._renderer, "set_overlay"):
            overlay_mode = None if self._flow == FLOW_PLAYING else self._flow

            modifier_panel = None
            practice_enabled = None
            score_multiplier = 1.0
            if self._flow == FLOW_PREFLIGHT:
                stage_index = self._preflight_stage_index
                stage = self._stages[stage_index]
                if stage.selectable_mode:
                    modifier_panel = {
                        "game_mode": self.chosen_game_mode(stage_index),
                        "heavy_mechanic": self.chosen_heavy_mechanic(stage_index),
                        "modifiers": self.chosen_modifiers(stage_index),
                        "rows": self.modifier_rows(stage_index),
                        "cursor": self.menu_cursor_index(stage_index),
                        "focused": True,
                    }
                    practice_enabled = self.practice_mode_on(stage_index)
                score_multiplier = self._current_score_multiplier(stage_index)

            carousel_stage_index = None
            carousel_position = 0
            carousel_count = 0
            carousel_locked = False
            carousel_progress = None
            carousel_bpm = 0.0
            carousel_duration_seconds = 0.0
            if self._flow == FLOW_CAROUSEL:
                entries = self.carousel_entries()
                carousel_count = len(entries)
                if entries:
                    carousel_position = self.carousel_index() % len(entries)
                    carousel_stage_index = entries[carousel_position][0]
                    carousel_locked = (
                        self._carousel_category == "campaign"
                        and self.is_campaign_entry_locked(carousel_position)
                    )
                    stage = self._stages[carousel_stage_index]
                    carousel_progress = self._player_progress.get(stage.stage_id)
                    carousel_bpm, carousel_duration_seconds = read_stage_bpm_and_duration(stage)

            self._renderer.set_overlay(
                overlay_mode,
                modifier_panel=modifier_panel,
                practice_enabled=practice_enabled,
                rank=(self._results_rank if self._flow == FLOW_RESULTS else None),
                hub_cursor=self._hub_cursor,
                carousel_category=self._carousel_category,
                carousel_stage_index=carousel_stage_index,
                carousel_position=carousel_position,
                carousel_count=carousel_count,
                carousel_locked=carousel_locked,
                carousel_progress=carousel_progress,
                carousel_bpm=carousel_bpm,
                carousel_duration_seconds=carousel_duration_seconds,
                preflight_stage_index=(
                    self._preflight_stage_index if self._flow == FLOW_PREFLIGHT else None
                ),
                score_multiplier=score_multiplier,
                vault_stats=(self.vault_stats() if self._flow == FLOW_VAULT else None),
                calibration_progress=(
                    self.calibration_progress() if self._flow == FLOW_CALIBRATION else None
                ),
            )
        if hasattr(self._renderer, "set_notice"):
            self._renderer.set_notice(self._notice_key if self._notice_timer > 0.0 else None)

    def _sync_camera_shake(self) -> None:
        """Traduz `GameState.shake_intensity` (decaido pelo
        `CameraShakeSystem` a cada `world.step`, comum aos 3 modos) num
        offset ALEATORIO real via `IRenderer.set_camera_offset` -- metodo
        JA EXISTENTE na engine (ROADMAP M1/M2), so nunca tinha um
        chamador no jogo ate agora. Mesma familia de sincronizacao
        apresentacao<-estado de `_sync_overlay` (nunca dentro de um
        `ISystem`); `random.uniform` aqui e puramente cosmetico -- nao
        decide nenhum veredito de jogabilidade, entao nao esta sob a
        disciplina Zero-GC do gameplay."""
        if not hasattr(self._renderer, "set_camera_offset") or self._composed is None:
            return
        intensity = self._composed.game_state.shake_intensity
        if intensity <= 0.0:
            self._renderer.set_camera_offset(0.0, 0.0)
            return
        self._renderer.set_camera_offset(
            random.uniform(-intensity, intensity), random.uniform(-intensity, intensity)
        )

    def _sync_sparks(self) -> None:
        """Juice Visual -- Sparks: publica os buffers do `SparkSystem`
        da fase (`ComposedGame.spark_system`, so no Defensor) no
        renderer todo frame -- mesma familia de sincronizacao de
        `_sync_camera_shake`. No-op fora do Defensor, sem `SparkSystem`
        (Arcade 4K) ou com um renderer sem suporte."""
        if not hasattr(self._renderer, "set_sparks") or self._composed is None:
            return
        spark_system = self._composed.spark_system
        if spark_system is None:
            self._renderer.set_sparks(None, None, None, None, None, 0)
            return
        xs, ys, angles, lengths, alphas, count = spark_system.render_arrays()
        self._renderer.set_sparks(xs, ys, angles, lengths, alphas, count)

    def _sync_track_volume(self, delta_time: float) -> None:
        """Audio Ducking: UM unico lugar decide o volume real da faixa
        a cada frame, combinando o swell do Flow State (`_flow_base_volume`/
        `1.0` dentro do Flow -- `_was_in_flow` ja mantido por
        `_advance_flow_state`) com o abaixamento temporario apos um
        MISS/dano. `GameState.miss_count` e o MESMO contador incrementado
        por QUALQUER erro nos 2 modos (timing do Defensor, dano no
        nucleo, nota perdida do Arcade, Bomba, Hold quebrado) -- compara-lo
        quadro a quadro detecta "um erro nasceu agora" sem precisar de um
        evento/callback dedicado. `duck_timer_seconds` decai por
        `delta_time` de FRAME (game feel); o volume sobe de
        `duck_volume_fraction` (MINIMO, no instante do erro) de volta ao
        normal ao longo de `duck_duration_seconds`."""
        if not hasattr(self._audio_engine, "set_track_volume") or self._composed is None:
            return
        state = self._composed.game_state
        config = self._stage_config

        if state.miss_count > self._last_miss_count_seen:
            self._duck_timer_seconds = config.duck_duration_seconds
        self._last_miss_count_seen = state.miss_count
        if self._duck_timer_seconds > 0.0:
            self._duck_timer_seconds = max(0.0, self._duck_timer_seconds - delta_time)

        base_volume = 1.0 if self._was_in_flow else self._flow_base_volume()
        duck_multiplier = compute_duck_multiplier(
            self._duck_timer_seconds, config.duck_duration_seconds, config.duck_volume_fraction
        )
        self._audio_engine.set_track_volume(base_volume * duck_multiplier)

    def _sync_beat_phase(self) -> None:
        """Heartbeat (Juice Visual): publica `beat_phase` (`[0, 1)`, a
        fracao ja percorrida do compasso ATUAL) no renderer todo frame
        -- mesma familia de sincronizacao de `_sync_camera_shake`.
        `GameState.bpm` e fixo (lido uma unica vez na composicao), entao
        so o `now_seconds()` do relogio de audio muda a fase quadro a
        quadro. Zero-GC trivial: aritmetica escalar, nenhum array."""
        if not hasattr(self._renderer, "set_beat_phase"):
            return
        bpm = self._composed.game_state.bpm if self._composed is not None else 120.0
        beat_duration = 60.0 / max(bpm, 1.0)
        now_seconds = self._audio_clock.now_seconds()
        phase = (now_seconds % beat_duration) / beat_duration
        self._renderer.set_beat_phase(phase)

    def _sync_blindness(self) -> None:
        """Vignette Flash: traduz `GameState.is_blinded` (decaido pelo
        `CameraShakeSystem` a cada `world.step`) num liga/desliga real
        via `IRenderer.set_blindness_active` -- mesma familia de
        sincronizacao apresentacao<-estado de `_sync_camera_shake`."""
        if not hasattr(self._renderer, "set_blindness_active") or self._composed is None:
            return
        self._renderer.set_blindness_active(self._composed.game_state.is_blinded)

    def _sync_hitlag(self) -> None:
        """Juice de Parry (Hitlag Visual Simulado): traduz
        `GameState.visual_freeze_frames` (decaido pelo `CameraShakeSystem`
        a cada `world.step`, comum aos 3 modos) num liga/desliga real via
        `IRenderer.set_freeze_active` -- mesma familia de sincronizacao
        de `_sync_camera_shake`/`_sync_blindness`. A TRANSICAO de
        congelado->normal e detectada AQUI (`_was_frozen`, mesmo padrao
        ja usado por `_was_in_flow` no Flow State) para armar o flash de
        cor invertida por EXATAMENTE 1 frame -- o instante em que "a
        tela volta". `GameState.invert_colors` e consumido (resetado a
        `False`) no exato momento em que o flash e armado, nunca por
        nenhum `ISystem`."""
        if self._composed is None:
            return
        state = self._composed.game_state
        freeze_active = state.visual_freeze_frames > 0
        if hasattr(self._renderer, "set_freeze_active"):
            self._renderer.set_freeze_active(freeze_active)

        just_unfroze = self._was_frozen and not freeze_active
        flash = just_unfroze and state.invert_colors
        if hasattr(self._renderer, "set_color_invert"):
            self._renderer.set_color_invert(flash)
        if flash:
            state.invert_colors = False
        self._was_frozen = freeze_active

    def _render_frame(self) -> None:
        """Override do `GameLoop` da engine: MESMA coleta SoA de
        `transform`+`sprite`, mas aplicando o Stutter Scroll (ruido
        visual em Y, Arcade 4K) so NESTE array temporario, no momento
        do `draw_batch` -- `transform.position_y` (a fisica real que o
        `PhysicsSystem`/`LaneJudgmentSystem` usam) nunca e escrito
        aqui, entao nao ha deriva acumulada frame a frame (o mesmo
        cuidado pedido para o efeito)."""
        transform_pool = self._world.get_pool("transform")
        sprite_pool = self._world.get_pool("sprite")
        entity_indices = intersect_entity_indices(transform_pool, sprite_pool)
        count = int(entity_indices.shape[0])

        self._renderer.begin_frame()
        if count == 0:
            self._renderer.draw_batch(_EMPTY_XY, _EMPTY_F32, _EMPTY_XY, _EMPTY_U32, _EMPTY_RGBA, _EMPTY_I16, 0)
        else:
            t_rows = transform_pool.dense_rows_of(entity_indices)
            s_rows = sprite_pool.dense_rows_of(entity_indices)
            t_view = transform_pool.active_view()
            s_view = sprite_pool.active_view()

            positions_xy = np.stack([t_view["position_x"][t_rows], t_view["position_y"][t_rows]], axis=1)
            stutter_offset = 0.0
            if self._composed is not None:
                stutter_offset = self._composed.game_state.lane_stutter_offset_y
            if stutter_offset != 0.0:
                self._apply_lane_stutter(positions_xy, entity_indices, stutter_offset)
            rotations_rad = t_view["rotation_rad"][t_rows]
            scales_xy = np.stack([t_view["scale_x"][t_rows], t_view["scale_y"][t_rows]], axis=1)
            texture_ids = s_view["texture_id"][s_rows]
            tint_rgba = np.stack(
                [s_view["tint_r"][s_rows], s_view["tint_g"][s_rows], s_view["tint_b"][s_rows], s_view["tint_a"][s_rows]],
                axis=1,
            )
            layer_z = s_view["layer_z"][s_rows]
            self._renderer.draw_batch(positions_xy, rotations_rad, scales_xy, texture_ids, tint_rgba, layer_z, count)
        self._renderer.end_frame()

    def _apply_lane_stutter(self, positions_xy, entity_indices, stutter_offset: float) -> None:
        """Soma `stutter_offset` na coluna Y so das entidades que SAO
        notas do Arcade 4K (`rhythm_threat`, `mode_tag==MODE_TAG_LANES`)
        dentro do batch de renderizacao -- HUD/receptores/nucleo ficam
        de fora. `positions_xy` e o array TEMPORARIO montado por
        `_render_frame` para este frame (nunca a pool)."""
        threat_pool = self._world.get_pool("rhythm_threat")
        active_count = threat_pool.count
        if active_count == 0:
            return
        threat_view = threat_pool.active_view()
        is_lanes = threat_view["mode_tag"] == MODE_TAG_LANES
        if not np.any(is_lanes):
            return
        lanes_entity_indices = threat_pool.active_entity_indices()[is_lanes]
        mask = np.isin(entity_indices, lanes_entity_indices)
        positions_xy[mask, 1] += stutter_offset

    def run(self) -> None:
        """Mesmo timing do `GameLoop.run` da engine (perf_counter + cap
        de fps), com `advance_frame` no lugar do `world.step`
        incondicional. A renderizacao acontece em TODO estado -- a arena
        fica visivel ao fundo dos overlays."""
        self._running = True
        min_frame_seconds = 1.0 / self._target_fps if self._target_fps > 0 else 0.0
        last_time = time.perf_counter()

        while self._running and not self._input_provider.wants_quit():
            self._input_provider.poll()

            now = time.perf_counter()
            delta_time = now - last_time
            last_time = now

            self.advance_frame(delta_time)
            self._sync_overlay()
            self._sync_camera_shake()
            self._sync_blindness()
            self._sync_hitlag()
            self._sync_lane_playfield()
            self._sync_defender_playfield()
            self._sync_sparks()
            self._sync_beat_phase()
            self._sync_track_volume(delta_time)
            self._render_frame()

            elapsed = time.perf_counter() - now
            if min_frame_seconds > elapsed:
                time.sleep(min_frame_seconds - elapsed)
