"""PygameRenderer estendido com registro de texturas pre-renderizadas e visual radial."""
from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

import numpy as np
import pygame

from ouroboros.adapters.pygame_backend.pygame_renderer import PygameRenderer

from hertzbeats.components.texture_ids import (
    TEX_CONVERGENCE_RING,
    TEX_DIGIT_BASE,
    TEX_PLAYER_CORE_BLUE,
    TEX_PLAYER_CORE_PINK,
    TEX_THREAT_POLARITY_BLUE,
    TEX_THREAT_POLARITY_PINK,
)

_INNER_MARK_COLOR = (250, 250, 255)
"""Cor FIXA do simbolo interno azul/rosa (quase-branco) -- contraste
alto contra QUALQUER tom de fundo, o mesmo criterio de icone que
funciona sem depender do matiz (acessibilidade a daltonismo)."""

_FLOW_TIER_PALETTE = (
    (90, 70, 160), (64, 200, 255), (255, 180, 64), (255, 90, 190), (140, 255, 120),
)
"""Paleta ciclica da linha de julgamento no Flow State -- cada tier de
50 combos extras avanca uma cor (`tier % len(paleta)`)."""

_GAME_MODE_ROW = "game_mode"
_HEAVY_MECHANIC_ROW = "heavy_mechanic"
_START_ROW = "start"
"""Mesmos literais de `hertzbeats.bootstrap.hertz_game_loop.GAME_MODE_ROW`/
`HEAVY_MECHANIC_ROW`/`START_ROW` -- duplicados de proposito (este
adapter nao importa o game loop, seria o sentido INVERSO de dependencia
adapter->orquestracao) pra reconhecer as 3 linhas especiais do menu de
opcoes (as 2 primeiras sao multipla escolha -- Defensor/Arcade 4K e
Nenhuma/Polaridade/Holds -- a ultima e o botao de Acao "Iniciar Fase")
e desenha-las SEM quadrado de marcar."""

_GLITCH_BAR_COLOR = (5, 5, 8)
_GLITCH_MAX_BARS = 4
"""Modificador "Corrupcao" (Breakcore/Glitchhop): barras de estatica
horizontais cruzando a tela enquanto o modifier esta ativo -- posicao/
altura PSEUDO-aleatorias mas deterministicas (hash aritmetico simples
sobre `pygame.time.get_ticks()`, nunca `random` de verdade), puramente
COSMETICO -- mesma categoria de `_judgment_line_color`'s pulso (fora da
disciplina Zero-GC/determinismo do gameplay, que continua 100%
`IAudioClock`)."""

_RESULTS_HISTOGRAM_BAR_WIDTH = 14
_RESULTS_HISTOGRAM_BAR_GAP = 4
_RESULTS_HISTOGRAM_MAX_HEIGHT = 50
_RESULTS_HISTOGRAM_COLOR = (140, 130, 200)
_RESULTS_HISTOGRAM_CENTER_COLOR = (255, 214, 64)
"""Acessibilidade -- Histograma de Resultados: barras verticais sobre
`HertzGameLoop._results_histogram` (`compute_hit_error_histogram`,
`game_state.py`) -- a barra do MEIO (faixa mais proxima do tempo exato)
vem destacada em dourado, o resto em lilás neutro."""

_HIT_ERROR_METER_WIDTH = 220
_HIT_ERROR_METER_RANGE_SECONDS = 0.15
_HIT_ERROR_METER_RECENT_TICKS = 20
_HIT_ERROR_METER_COLOR = (200, 195, 240)
"""Acessibilidade -- Hit-Error Meter: barra fixa perto do rodape
mostrando os ULTIMOS `_HIT_ERROR_METER_RECENT_TICKS` acertos como riscos
(esquerda=cedo, direita=tarde, centro=no tempo exato) -- ensina o
jogador a corrigir o proprio ritmo visualmente (classico do Osu!/
StepMania). `_HIT_ERROR_METER_RANGE_SECONDS` e a escala da barra inteira
(mesma ordem de grandeza da janela de MISS)."""

_REACTIVE_BG_BAR_COUNT = 12
_REACTIVE_BG_MAX_HEIGHT = 60
_REACTIVE_BG_COLOR = (60, 45, 110)
"""Fundo Reativo (Juice Visual): fileira de barras tipo equalizador na
borda de baixo da tela, altura proporcional a `_background_intensity`
(publicada pelo `HertzGameLoop` -- quantos eventos ritmicos vem por ai,
olhando `ComposedGame.hit_times` a frente). Cada barra usa uma fase
DIFERENTE de seno (sobre o relogio de parede) pra nao subir/descer tudo
em bloco -- puramente cosmetico, decorativo, nunca parte do
julgamento."""

_GHOST_TRAIL_LENGTH = 10
_GHOST_TRAIL_COLOR = (140, 220, 255)
_GHOST_TRAIL_MAX_RADIUS = 9
"""Ghost Trails (Defensor -- mira): quantas posicoes passadas da mira
ficam no rastro (`RingBuffer` circular, tamanho FIXO -- nunca cresce) e
a cor/raio maximo do rastro mais recente, esmaecendo ate quase
invisivel na posicao mais antiga."""

_HEARTBEAT_DECAY_RATE = 6.0
"""Heartbeat: quao rapido o pulso decai apos o inicio do compasso (maior
= "thump" mais curto e seco). Ver `_heartbeat_pulse`."""

_HEARTBEAT_RING_ZOOM = 0.05
"""Heartbeat: variacao MAXIMA (fracao) do raio do Anel de Julgamento no
pico do pulso -- +5%, sutil o bastante para nao atrapalhar a leitura da
mira."""

_HEARTBEAT_LANE_WARP = 0.05
"""Heartbeat: mesma variacao MAXIMA, aplicada a meia-largura das pistas
do Arcade 4K (Grid Warp)."""

_METRONOME_BAR_WIDTH = 10
_METRONOME_COLOR = (140, 120, 220)
"""Metronomo Periferico: 2 barras finas nas bordas esquerda/direita da
tela, cujo alfa pulsa com `beat_phase` -- um metronomo visual que nao
compete com a leitura da arena (fica na periferia da visao)."""

_SPARK_COLOR = (255, 214, 64)
"""Dourado -- mesmo tom de PERFECT (`_PERFECT_COLOR` em `texture_bank.py`),
reforcando a mesma associacao "isso foi impecavel"."""

_ARENA_BG_COLOR = (8, 6, 20)
"""MESMO tom de fundo de `begin_frame` (fora do Flow State) -- as
Sparks nao tem uma Surface `SRCALPHA` propria (series 128 linhas por
frame nao valeria o custo de outra Surface so pra alfa real), entao o
"sumir" e aproximado interpolando a cor RUMO ao fundo da arena em vez de
um alfa de verdade -- visualmente identico (funde com o fundo) sem
precisar de blit extra por faisca."""

_TUNNEL_COLOR = (2, 1, 6, 255)
"""Cor opaca do overlay do Colapso de Visao -- mesmo tom base da arena
(`begin_frame`, modo Defensor fora do Flow State) para nao criar um
contraste artificial nas bordas do campo de luz."""

_MEDAL_GLYPH_SIZE = 10
_MEDAL_GLYPH_GAP = 4
_MEDAL_GLYPH_COLOR = (255, 214, 64)
_MEDAL_MAX_GLYPHS = 6
"""Meta-Jogo -- Medalhas: quadrados pequenos desenhados em TEMPO REAL
(mesmo criterio de `_CHECKBOX_SIZE`/`_draw_modifier_row`, nunca uma
textura pre-renderizada) ao lado do rotulo de cada fase no menu, um por
modifier distinto ja vencido nela (`player_progress.json`)."""

_CHECKBOX_SIZE = 18
_CHECKBOX_GAP = 12
_CHECKBOX_COLOR = (250, 250, 255)
_CURSOR_HIGHLIGHT_COLOR = (255, 214, 64)
_CURSOR_HIGHLIGHT_PADDING = 10
"""Painel de checkboxes do seletor de minigame (Mecanicas Modulares):
o quadrado de marcar e o retangulo de destaque da linha em foco sao
desenhados em TEMPO REAL (`pygame.draw.rect`), nunca pre-renderizados
-- mesmo criterio de `_draw_inner_square`/`_draw_inner_triangle` (um
retangulo simples nao precisa de `font.render`, so o ROTULO de texto de
cada linha e uma Surface pronta)."""

_HUB_CATEGORIES = ("campaign", "free_play", "vault", "calibration", "ironman")
"""Duplicado de proposito de `hertz_game_loop.HUB_CATEGORIES` (mesmo
criterio de `_GAME_MODE_ROW` acima -- adapter nao importa o game loop):
ordem das 5 categorias grandes do HUB, indexada por `hub_cursor`."""

_CAROUSEL_DOT_RADIUS = 4
_CAROUSEL_DOT_GAP = 14
_CAROUSEL_DOT_COLOR = (110, 100, 150)
_CAROUSEL_DOT_FOCUSED_COLOR = (255, 214, 64)
"""Indicador de posicao do Carrossel ("2 de 5"): fileira de pontos
procedurais (mesmo criterio dos glifos de medalha -- um numero pequeno
e variavel de itens nao pede uma textura pre-renderizada por contagem),
o ponto da entrada em foco pintado em destaque."""

_CALIBRATION_ONTIME_THRESHOLD_SECONDS = 0.02
"""Tela de Calibracao: um toque com desvio absoluto ate isso do tempo do
metronomo mostra o feedback "NO TEMPO" em vez de "CEDO"/"TARDE" -- so 3
texturas discretas de feedback, nunca o valor continuo do desvio."""

_SCORE_MULTIPLIER_STEP = 0.05
_SCORE_MULTIPLIER_MIN = 0.10
_SCORE_MULTIPLIER_STEPS = 40
"""Previa do Multiplicador de Pontuacao no Pre-Voo: MESMO criterio da
calibracao de latencia ao vivo (`latency_{step}`, passos de 10 ms) --
uma textura por passo discreto de 0.05 entre 0.10 e 2.10 (`MIN_SCORE_
MULTIPLIER` ate acima de qualquer combinacao real de bonus), nunca
`font.render` no loop. `_draw_overlay` so ARREDONDA o float continuo
(`compute_score_multiplier`) pro passo mais proximo."""


class HBPygameRenderer(PygameRenderer):
    """
    `PygameRenderer` da engine estendido para o Hertz & Beats com:

        - `register_texture(texture_id, surface)`: associa um inteiro de
          `sprite.texture_id` a uma Surface PRE-RENDERIZADA na tela de
          carregamento (digitos 0-9, palavras PERFECT/GOOD/MISS, pips).
          `draw_batch` blita a textura registrada; ids sem textura caem
          no desenho procedural (circulos -- nucleo, ameacas, mira).
        - `set_playfield(...)`: decoracao de arena POR MODO (aneis do
          Defensor, colunas + linha do Arcade), desenhada em
          `begin_frame` e sincronizada pelo `HertzGameLoop` a cada
          troca de fase.
        - Barras procedurais quando a escala e anisotropica (Notas
          Longas/Scratch do Arcade 4K).
        - `tint_a == 0` oculta o sprite (usado pelo HUD para zeros a
          esquerda e palavras expiradas).
        - Juice de Parry (Hitlag Visual Simulado, Defensor): `begin_frame`/
          `draw_batch` viram NO-OP enquanto `set_freeze_active(True)`
          estiver ligado -- a Surface simplesmente nao e tocada, entao o
          ultimo frame desenhado continua na tela ("congelado") sem
          nenhum custo extra de copia. `end_frame` aplica um filtro de
          cor invertida quando `set_color_invert(True)` -- publicado
          pelo `HertzGameLoop` por EXATAMENTE 1 frame, no instante em
          que o congelamento termina. `BLEND_RGB_SUB` em pygame calcula
          `destino = destino - fonte` (nao o inverso), entao um negativo
          de verdade (`resultado = 255 - original`) exige DOIS passos:
          `scratch = branco - frame_atual` (SUB), depois `frame_atual =
          scratch` (blit opaco simples) -- ver `_invert_surface`.
        - Screen Shake: `draw_batch` soma `self._cam_dx`/`self._cam_dy`
          a CADA posicao antes de desenhar -- campos JA EXISTENTES na
          `PygameRenderer` base (ROADMAP M1/M2, `set_camera_offset`,
          default no-op na ABC). Nao inventamos um mecanismo novo aqui,
          so passamos a LER o que a base ja guarda (o override completo
          de `draw_batch` deste adapter, por causa do registro de
          texturas, nao chamava `super().draw_batch()` e por isso
          ignorava o offset ate agora). Quem ESCREVE o offset a cada
          frame e o `HertzGameLoop`, lendo `GameState.shake_intensity`
          (mesmo padrao ja usado por `set_overlay`/`set_notice`/
          `set_flow_mode` -- sincronizacao de apresentacao vive no game
          loop, nunca dentro de um `ISystem`).

    Continua respeitando o contrato `IRenderer`: uma unica chamada
    `draw_batch` por frame cruzando a fronteira core->adapter. O laco
    por sprite vive AQUI no adapter, fora da jurisdicao Zero-GC do
    gameplay (mesma nota honesta do renderer base da engine).
    """

    def __init__(self) -> None:
        super().__init__()
        self._textures: Dict[int, pygame.Surface] = {}
        self._playfield_kind: Optional[str] = None
        self._playfield_params: Dict = {}
        self._overlay_surfaces: Dict[str, pygame.Surface] = {}
        self._overlay_mode: Optional[str] = None
        self._overlay_modifier_panel: Optional[dict] = None
        self._overlay_practice_enabled: Optional[bool] = None
        self._overlay_rank: Optional[str] = None
        self._overlay_hub_cursor: int = 0
        self._overlay_carousel_category: Optional[str] = None
        self._overlay_carousel_stage_index: Optional[int] = None
        self._overlay_carousel_position: int = 0
        self._overlay_carousel_count: int = 0
        self._overlay_carousel_locked: bool = False
        self._overlay_carousel_progress: Optional[dict] = None
        self._overlay_carousel_bpm: float = 0.0
        self._overlay_carousel_duration_seconds: float = 0.0
        self._overlay_preflight_stage_index: Optional[int] = None
        self._overlay_score_multiplier: float = 1.0
        self._overlay_vault_stats: Optional[dict] = None
        self._overlay_calibration_progress: Optional[tuple] = None
        self._overlay_hit_error_histogram: Optional[tuple] = None
        self._overlay_b_side_info: Optional[dict] = None
        self._notice_key: Optional[str] = None
        self._dim_surface: Optional[pygame.Surface] = None
        self._flow_mode_active: bool = False
        self._flow_tier: int = 0
        self._vignette_surface: Optional[pygame.Surface] = None
        self._blindness_active: bool = False
        self._tunnel_surface: Optional[pygame.Surface] = None
        self._freeze_active: bool = False
        self._color_invert_pending: bool = False
        self._invert_surface: Optional[pygame.Surface] = None
        self._low_health_danger_active: bool = False
        self._danger_red_surface: Optional[pygame.Surface] = None
        self._danger_blue_surface: Optional[pygame.Surface] = None
        # Ghost Trails (Defensor -- mira): RingBuffer circular de tamanho
        # FIXO (nunca cresce/aloca por frame) com as ULTIMAS posicoes da
        # mira -- `_ghost_trail_count` satura em `_GHOST_TRAIL_LENGTH`.
        self._ghost_trail_xs = [0.0] * _GHOST_TRAIL_LENGTH
        self._ghost_trail_ys = [0.0] * _GHOST_TRAIL_LENGTH
        self._ghost_trail_write_index: int = 0
        self._ghost_trail_count: int = 0
        self._glitch_intensity: float = 0.0
        self._background_intensity: float = 0.0
        self._hit_error_buffer = None
        self._hit_error_write_index: int = 0
        self._hit_error_filled_count: int = 0
        self._spark_xs = None
        self._spark_ys = None
        self._spark_angles = None
        self._spark_lengths = None
        self._spark_alphas = None
        self._spark_count: int = 0
        self._beat_phase: float = 0.0

    def register_texture(self, texture_id: int, surface: "pygame.Surface") -> None:
        """Registra `surface` (ja convertida com alpha) para `texture_id`.
        Chamado apenas na fase de carregamento, nunca no loop."""
        self._textures[int(texture_id)] = surface

    def register_overlay_surface(self, key: str, surface: "pygame.Surface") -> None:
        """Registra uma superficie de overlay de meta-jogo (titulo do
        menu, nomes de fase, PAUSADO, GAME OVER, ...) pre-renderizada na
        composicao. Chaves consumidas por `_draw_overlay`."""
        self._overlay_surfaces[key] = surface

    def set_overlay(
        self,
        mode: Optional[str],
        modifier_panel: Optional[dict] = None,
        practice_enabled: Optional[bool] = None,
        rank: Optional[str] = None,
        hub_cursor: int = 0,
        carousel_category: Optional[str] = None,
        carousel_stage_index: Optional[int] = None,
        carousel_position: int = 0,
        carousel_count: int = 0,
        carousel_locked: bool = False,
        carousel_progress: Optional[dict] = None,
        carousel_bpm: float = 0.0,
        carousel_duration_seconds: float = 0.0,
        preflight_stage_index: Optional[int] = None,
        score_multiplier: float = 1.0,
        vault_stats: Optional[dict] = None,
        calibration_progress: Optional[tuple] = None,
        hit_error_histogram: Optional[tuple] = None,
        b_side_info: Optional[dict] = None,
    ) -> None:
        """Publica o estado do Novo Fluxo de Menus (Experiencia Arcade) a
        desenhar sobre o frame: `None` (jogando, sem overlay) ou uma das
        `FLOW_*` de `hertz_game_loop.py` ("title", "hub", "carousel",
        "preflight", "vault", "calibration", "paused", "game_over",
        "results"). `modifier_panel`/`practice_enabled` (Pre-Voo, so
        musicas do jogador -- `None` em fase curada) sao o MESMO painel
        de checkboxes de sempre. `rank` (Meta-Jogo, so em "results").
        `hub_cursor` (indice em `HUB_CATEGORIES`). `carousel_*` (Meta-Jogo
        -- Carrossel): SO a entrada em FOCO (posicao/contagem/indice
        original/trancada/progresso salvo), nunca a lista inteira -- o
        Carrossel mostra uma musica de cada vez no centro da tela.
        `preflight_stage_index` + `score_multiplier` (Meta-Jogo --
        Multiplicador de Pontuacao, previa ao vivo). `vault_stats`/
        `calibration_progress`: dados agregados das telas dedicadas.
        `hit_error_histogram` (Acessibilidade, so em "results"): tupla de
        `RESULTS_HISTOGRAM_BIN_COUNT` contagens ja prontas
        (`compute_hit_error_histogram`, calculada 1x na transicao).
        Chamado pelo `HertzGameLoop` a cada frame."""
        self._overlay_mode = mode
        self._overlay_modifier_panel = modifier_panel
        self._overlay_practice_enabled = practice_enabled
        self._overlay_rank = rank
        self._overlay_hub_cursor = int(hub_cursor)
        self._overlay_carousel_category = carousel_category
        self._overlay_carousel_stage_index = carousel_stage_index
        self._overlay_carousel_position = int(carousel_position)
        self._overlay_carousel_count = int(carousel_count)
        self._overlay_carousel_locked = bool(carousel_locked)
        self._overlay_carousel_progress = carousel_progress
        self._overlay_carousel_bpm = float(carousel_bpm)
        self._overlay_carousel_duration_seconds = float(carousel_duration_seconds)
        self._overlay_preflight_stage_index = preflight_stage_index
        self._overlay_score_multiplier = float(score_multiplier)
        self._overlay_vault_stats = vault_stats
        self._overlay_calibration_progress = calibration_progress
        self._overlay_hit_error_histogram = hit_error_histogram
        self._overlay_b_side_info = b_side_info

    def set_notice(self, key: Optional[str]) -> None:
        """Aviso transiente (superficie de overlay pre-registrada, ex.
        calibracao de latencia), desenhado no topo em QUALQUER estado --
        inclusive durante o gameplay. `None` oculta."""
        self._notice_key = key

    def set_flow_mode(self, active: bool) -> None:
        """Flow State (Arcade 4K): escurece o fundo da arena enquanto o
        combo se mantiver acima do limiar -- a "imersao total" que resta
        no lado puramente visual depois que o `UIRenderSystem` ja apagou
        todo o HUD. Chamado pelo `HertzGameLoop` na transicao de combo."""
        self._flow_mode_active = bool(active)

    def set_flow_tier(self, tier: int) -> None:
        """Sem HUD, o jogador perde a nocao de quanto o combo avancou
        alem do limiar do Flow -- este `tier` (`combo // limiar`, 0 fora
        do Flow) avanca a cor E o pulso da linha de julgamento a cada 50
        acertos adicionais (`begin_frame`), uma dica visual sutil que
        nao exige nenhum texto/HUD de volta. Chamado pelo
        `HertzGameLoop` todo frame (nao so na transicao -- o tier muda
        DENTRO do Flow, sem cruzar o limiar de novo)."""
        self._flow_tier = int(tier)

    def set_vignette_surface(self, surface: "pygame.Surface") -> None:
        """Registra a Surface do Vignette Flash (preta, com um buraco
        circular transparente focado na linha de julgamento) --
        pre-renderizada UMA vez em `texture_bank.build_and_register_vignette_surface`,
        nunca reconstruida por frame."""
        self._vignette_surface = surface

    def set_blindness_active(self, active: bool) -> None:
        """Liga/desliga o blit do Vignette Flash -- publicado pelo
        `HertzGameLoop` a cada frame a partir de `GameState.is_blinded`
        (mesmo padrao de `set_flow_mode`/`set_overlay`: sincronizacao de
        apresentacao vive no game loop, nunca dentro de um `ISystem`)."""
        self._blindness_active = bool(active)

    def set_freeze_active(self, active: bool) -> None:
        """Juice de Parry (Hitlag): liga/desliga a suspensao de
        `begin_frame`/`draw_batch` -- publicado pelo `HertzGameLoop` a
        cada frame a partir de `GameState.visual_freeze_frames > 0`."""
        self._freeze_active = bool(active)

    def set_color_invert(self, active: bool) -> None:
        """Juice de Parry: arma o flash de cor invertida para o PROXIMO
        `end_frame` -- o `HertzGameLoop` so publica `True` por exatamente
        1 frame (o instante em que o congelamento termina), entao nao ha
        necessidade de auto-consumo aqui: o proximo `set_color_invert(False)`
        do frame seguinte ja desarma."""
        self._color_invert_pending = bool(active)

    def record_ghost_trail_position(self, x: float, y: float) -> None:
        """Ghost Trails (Defensor -- mira): grava a posicao ATUAL da mira
        no RingBuffer circular (`_ghost_trail_write_index` avanca 1 slot
        por chamada, voltando ao inicio ao encher -- nenhuma lista
        cresce). Chamado pelo `HertzGameLoop` todo frame de `FLOW_PLAYING`
        no Defensor."""
        self._ghost_trail_xs[self._ghost_trail_write_index] = float(x)
        self._ghost_trail_ys[self._ghost_trail_write_index] = float(y)
        self._ghost_trail_write_index = (self._ghost_trail_write_index + 1) % _GHOST_TRAIL_LENGTH
        self._ghost_trail_count = min(self._ghost_trail_count + 1, _GHOST_TRAIL_LENGTH)

    def reset_ghost_trail(self) -> None:
        """Esvazia o rastro -- chamado pelo `HertzGameLoop` a cada troca
        de fase, pra um rastro da fase ANTERIOR nao "vazar" pro inicio
        da proxima (mesmo criterio de `_last_miss_count_seen` zerado em
        `_start_stage`)."""
        self._ghost_trail_count = 0
        self._ghost_trail_write_index = 0

    def _draw_ghost_trail(self) -> None:
        """Desenha os slots PREENCHIDOS do rastro, do mais ANTIGO (quase
        invisivel) ao mais RECENTE (raio/alfa maximo) -- em `begin_frame`,
        ANTES do `draw_batch` real desenhar a mira na posicao atual por
        cima, pra parecer uma esteira deixada para tras. Sem alfa real
        (a Surface principal nao tem `SRCALPHA`), o "esmaecer" e
        aproximado interpolando RUMO ao fundo da arena -- mesmo truque
        ja usado pelas Sparks."""
        count = self._ghost_trail_count
        if count == 0:
            return
        background = (2, 1, 6) if self._flow_mode_active else (8, 6, 20)
        for i in range(count):
            # i=0 e o slot mais ANTIGO ainda vivo, i=count-1 e o mais RECENTE
            slot = (self._ghost_trail_write_index - count + i) % _GHOST_TRAIL_LENGTH
            fraction = (i + 1) / count
            x = int(self._ghost_trail_xs[slot])
            y = int(self._ghost_trail_ys[slot])
            radius = max(1, int(_GHOST_TRAIL_MAX_RADIUS * fraction))
            color = tuple(
                int(bg + (fg - bg) * fraction) for bg, fg in zip(background, _GHOST_TRAIL_COLOR)
            )
            pygame.draw.circle(self._surface, color, (x, y), radius, 1)

    def set_background_intensity(self, intensity: float) -> None:
        """Fundo Reativo: `0.0..1.0` publicado pelo `HertzGameLoop`
        (quantos eventos ritmicos vem nos proximos instantes, olhando
        `ComposedGame.hit_times` a frente) -- desenhado em `begin_frame`,
        antes de qualquer decoracao de arena."""
        self._background_intensity = float(intensity)

    def _draw_reactive_background(self) -> None:
        """Fileira de barras tipo equalizador na borda de baixo,
        altura escalada por `_background_intensity` -- cada barra usa
        uma fase de seno DIFERENTE (indice * offset fixo) sobre o
        relogio de parede, pra nao subirem/descerem todas em bloco.
        Puramente cosmetico (mesma categoria de `_judgment_line_color`),
        desenhado ANTES da decoracao de arena (fundo, nunca por cima do
        gameplay)."""
        if self._background_intensity <= 0.0:
            return
        ticks = pygame.time.get_ticks() / 1000.0
        bar_width = self._width / _REACTIVE_BG_BAR_COUNT
        for i in range(_REACTIVE_BG_BAR_COUNT):
            wobble = 0.5 + 0.5 * math.sin(ticks * 6.0 + i * 0.8)
            height = int(_REACTIVE_BG_MAX_HEIGHT * self._background_intensity * wobble)
            if height <= 0:
                continue
            rect = pygame.Rect(int(i * bar_width), self._height - height, int(bar_width) + 1, height)
            pygame.draw.rect(self._surface, _REACTIVE_BG_COLOR, rect)

    def set_hit_error_data(self, buffer, write_index: int, filled_count: int) -> None:
        """Acessibilidade -- Hit-Error Meter: publica a MESMA referencia
        do RingBuffer de `GameState.hit_delta_buffer` (nunca uma copia)
        mais o cursor de escrita e quantos slots ja tem dado de verdade.
        `buffer=None` (fora de `FLOW_PLAYING`) desliga o desenho."""
        self._hit_error_buffer = buffer
        self._hit_error_write_index = int(write_index)
        self._hit_error_filled_count = int(filled_count)

    def _draw_hit_error_meter(self) -> None:
        """Barra fixa perto do rodape com os ULTIMOS acertos como riscos
        verticais -- esquerda=cedo, direita=tarde, o risco dourado no
        centro marca "no tempo exato". So os `_HIT_ERROR_METER_RECENT_TICKS`
        mais recentes aparecem, esmaecendo do mais novo (opaco) ao mais
        antigo (quase invisivel)."""
        if self._hit_error_buffer is None or self._hit_error_filled_count == 0:
            return
        center_x = self._width // 2
        y = self._height - 34
        half_width = _HIT_ERROR_METER_WIDTH // 2
        pygame.draw.line(self._surface, (90, 85, 120), (center_x - half_width, y), (center_x + half_width, y), 2)
        pygame.draw.line(self._surface, (255, 214, 64), (center_x, y - 7), (center_x, y + 7), 2)

        capacity = self._hit_error_buffer.shape[0]
        count = min(self._hit_error_filled_count, _HIT_ERROR_METER_RECENT_TICKS)
        for i in range(count):
            slot = (self._hit_error_write_index - 1 - i) % capacity
            delta = float(self._hit_error_buffer[slot])
            clamped = max(-_HIT_ERROR_METER_RANGE_SECONDS, min(_HIT_ERROR_METER_RANGE_SECONDS, delta))
            x = center_x + int((clamped / _HIT_ERROR_METER_RANGE_SECONDS) * half_width)
            fade = 1.0 - (i / count)
            color = tuple(int(c * (0.25 + 0.75 * fade)) for c in _HIT_ERROR_METER_COLOR)
            pygame.draw.line(self._surface, color, (x, y - 9), (x, y + 9), 2)

    def _draw_hit_error_histogram(self, center_x: int, y: int) -> int:
        """Acessibilidade -- Histograma de Resultados: barras verticais
        sobre `_overlay_hit_error_histogram` (contagens JA prontas,
        `compute_hit_error_histogram` -- nenhum bucketing aqui). A barra
        do MEIO (faixa mais proxima do tempo exato) fica destacada em
        dourado. `None`/tudo zerado (fase sem PERFECT/GOOD nenhum) e um
        no-op silencioso."""
        histogram = self._overlay_hit_error_histogram
        if not histogram:
            return 0
        peak = max(histogram)
        if peak <= 0:
            return 0
        bin_count = len(histogram)
        center_bin = bin_count // 2
        total_width = bin_count * _RESULTS_HISTOGRAM_BAR_WIDTH + (bin_count - 1) * _RESULTS_HISTOGRAM_BAR_GAP
        start_x = center_x - total_width // 2
        for i, count in enumerate(histogram):
            height = int(_RESULTS_HISTOGRAM_MAX_HEIGHT * (count / peak))
            if height <= 0:
                continue
            color = _RESULTS_HISTOGRAM_CENTER_COLOR if i == center_bin else _RESULTS_HISTOGRAM_COLOR
            x = start_x + i * (_RESULTS_HISTOGRAM_BAR_WIDTH + _RESULTS_HISTOGRAM_BAR_GAP)
            rect = pygame.Rect(x, y + (_RESULTS_HISTOGRAM_MAX_HEIGHT - height), _RESULTS_HISTOGRAM_BAR_WIDTH, height)
            pygame.draw.rect(self._surface, color, rect)
        return _RESULTS_HISTOGRAM_MAX_HEIGHT

    def set_glitch_intensity(self, intensity: float) -> None:
        """Modificador "Corrupcao": `0.0` (desligado, `_draw_glitch_bars`
        vira no-op) ou um valor `> 0.0` (mais barras/mais grossas quanto
        maior) enquanto o modifier estiver ativo -- publicado pelo
        `HertzGameLoop`, nunca decidido aqui."""
        self._glitch_intensity = float(intensity)

    def _draw_glitch_bars(self) -> None:
        """Barras de estatica horizontais, posicao/altura PSEUDO-
        aleatorias (hash aritmetico deterministico sobre o relogio de
        parede -- nunca `random` de verdade, e puramente cosmetico,
        fora da jurisdicao Zero-GC/determinismo do gameplay)."""
        if self._glitch_intensity <= 0.0:
            return
        tick_seed = pygame.time.get_ticks() // 60
        bar_count = min(_GLITCH_MAX_BARS, max(1, int(_GLITCH_MAX_BARS * self._glitch_intensity)))
        for i in range(bar_count):
            seed = (tick_seed * 2654435761 + i * 97) & 0xFFFFFFFF
            y = seed % self._height
            bar_height = 2 + (seed // 997) % 6
            pygame.draw.rect(self._surface, _GLITCH_BAR_COLOR, pygame.Rect(0, y, self._width, bar_height))

    def set_low_health_danger(self, active: bool) -> None:
        """Danger Visual (Meta-Jogo -- Roleta Russa/1 de vida): liga/
        desliga a aberracao cromatica desenhada TODO frame em
        `end_frame` enquanto ativo -- publicado pelo `HertzGameLoop`
        (`GameState.health == 1`), nunca decidido aqui."""
        self._low_health_danger_active = bool(active)

    def set_sparks(self, xs, ys, angles, lengths, alphas, count: int) -> None:
        """Juice Visual -- Sparks: publica os buffers do `SparkSystem`
        (Zero-GC, nenhuma copia -- so guarda as REFERENCIAS) para o
        proximo `end_frame` desenhar via `pygame.draw.line`. Chamado
        TODO frame pelo `HertzGameLoop` (`_sync_sparks`), mesma familia
        de `_sync_camera_shake`/`_sync_blindness`."""
        self._spark_xs = xs
        self._spark_ys = ys
        self._spark_angles = angles
        self._spark_lengths = lengths
        self._spark_alphas = alphas
        self._spark_count = int(count)

    def set_beat_phase(self, phase: float) -> None:
        """Heartbeat: fase `[0, 1)` do compasso ATUAL (`now_seconds %
        beat_duration / beat_duration`, calculada pelo `HertzGameLoop` a
        partir de `GameState.bpm`) -- usada para pulsar o Anel de
        Julgamento/pistas (`begin_frame`) e o Metronomo Periferico
        (`end_frame`). Publicada TODO frame, mesma familia de
        sincronizacao de `_sync_camera_shake`."""
        self._beat_phase = float(phase)

    def set_playfield(self, kind: Optional[str], **params) -> None:
        """Define a decoracao de arena do MODO ativo, desenhada a cada
        `begin_frame`. Chamado pelo `HertzGameLoop` a cada troca de fase:

            "radial" -- aneis-guia do Defensor (spawn + anel de julgamento):
                center_x, center_y, spawn_radius, judgment_radius,
                tunnel_radius (Colapso de Visao -- opcional, `None`/
                ausente = sem overlay, ver `_draw_vision_tunnel`)
            "lanes"  -- colunas + linha de julgamento do Arcade 4K:
                lane_xs (iteravel), lane_half_width, judgment_y, height
            None     -- sem decoracao.
        """
        self._playfield_kind = kind
        self._playfield_params = params

    @staticmethod
    def probe_display_size() -> Tuple[int, int]:
        """Resolucao do monitor atual, consultada ANTES de criar a
        janela (para `fit_config_to_display`). Inicializa apenas o
        subsistema de video do pygame, sem abrir janela."""
        if not pygame.display.get_init():
            pygame.display.init()
        info = pygame.display.Info()
        return int(info.current_w), int(info.current_h)

    def initialize(self, width: int, height: int, title: str) -> None:
        super().initialize(width, height, title)
        self._dim_surface = pygame.Surface((width, height), pygame.SRCALPHA)
        self._dim_surface.fill((4, 2, 12, 216))
        # Surface de RASCUNHO (nao pre-renderizada -- reescrita a cada
        # flash) para o filtro de cor invertida: `BLEND_RGB_SUB` calcula
        # `destino - fonte`, entao para obter `255 - original` e preciso
        # preencher de branco e SUBTRAIR o frame atual (a ordem inversa
        # do que se poderia supor) -- ver `end_frame`.
        self._invert_surface = pygame.Surface((width, height))
        # Colapso de Visao: ao contrario do Vignette Flash (buraco de
        # tamanho FIXO, pre-renderizado uma vez), o raio do campo de luz
        # interpola continuamente -- precisa ser redesenhado (fill +
        # circulo transparente) a CADA frame sobre esta Surface
        # persistente (nunca uma nova por frame).
        self._tunnel_surface = pygame.Surface((width, height), pygame.SRCALPHA).convert_alpha()
        # Danger Visual (Roleta Russa/1 de vida): 2 Surfaces de RASCUNHO
        # persistentes (nunca criadas por frame) para a aberracao
        # cromatica -- ver `_draw_low_health_danger`.
        self._danger_red_surface = pygame.Surface((width, height))
        self._danger_blue_surface = pygame.Surface((width, height))

    def show_loading_message(self, message: str) -> None:
        """Tela de carregamento imediata (ex.: 'analisando musica nova').
        Renderizacao direta com font.render -- permitido: roda na fase de
        carregamento, nunca no loop de gameplay."""
        if not pygame.font.get_init():
            pygame.font.init()
        font = pygame.font.Font(None, 40)
        self._surface.fill((8, 6, 20))
        text = font.render(message, True, (235, 235, 255))
        self._surface.blit(
            text,
            (self._width // 2 - text.get_width() // 2, self._height // 2 - text.get_height() // 2),
        )
        pygame.display.flip()

    def set_window_icon(self, icon_path: str) -> None:
        """Define o icone da janela/barra de tarefas a partir de um PNG.
        No-op silencioso se o arquivo nao existir (icone e opcional)."""
        try:
            pygame.display.set_icon(pygame.image.load(icon_path))
        except (FileNotFoundError, pygame.error):
            pass

    def begin_frame(self) -> None:
        if self._freeze_active:
            return  # Juice de Parry: repete o ultimo frame desenhado, pixel por pixel
        self._surface.fill((2, 1, 6) if self._flow_mode_active else (8, 6, 20))
        self._draw_reactive_background()
        kind = self._playfield_kind
        if kind is None:
            return
        params = self._playfield_params
        pulse = self._heartbeat_pulse()
        if kind == "radial":
            center = (int(params["center_x"]), int(params["center_y"]))
            judgment_radius = float(params["judgment_radius"]) * (1.0 + _HEARTBEAT_RING_ZOOM * pulse)
            pygame.draw.circle(self._surface, (36, 28, 70), center, int(params["spawn_radius"]), 1)
            pygame.draw.circle(self._surface, (90, 70, 160), center, int(judgment_radius), 2)
            self._draw_ghost_trail()
        if kind == "lanes":
            height = int(params["height"])
            judgment_y = int(params["judgment_y"])
            lane_half = int(float(params["lane_half_width"]) * (1.0 + _HEARTBEAT_LANE_WARP * pulse))
            for lane_x in params["lane_xs"]:
                column = pygame.Rect(int(lane_x) - lane_half, 0, lane_half * 2, height)
                pygame.draw.rect(self._surface, (16, 13, 36), column)
                pygame.draw.line(self._surface, (36, 28, 70), (column.left, 0), (column.left, height))
                pygame.draw.line(self._surface, (36, 28, 70), (column.right, 0), (column.right, height))
            pygame.draw.line(
                self._surface, self._judgment_line_color(),
                (0, judgment_y), (int(params.get("width", self._width)), judgment_y),
                4 if self._flow_tier > 0 else 2,
            )

    def _heartbeat_pulse(self) -> float:
        """Heartbeat (Juice Visual): 1.0 EXATAMENTE no inicio do
        compasso, decaindo exponencialmente ate quase 0 na proxima
        batida (`beat_phase` publicado por `set_beat_phase` todo frame)
        -- um "thump" ritmico, nao uma oscilacao simetrica (que deixaria
        o anel/pistas MENORES que o normal na metade do compasso, o
        oposto do efeito pedido)."""
        return math.exp(-self._beat_phase * _HEARTBEAT_DECAY_RATE)

    def _judgment_line_color(self) -> Tuple[int, int, int]:
        """Cor da linha de julgamento: neutra fora do Flow State; dentro
        dele, avanca por `_FLOW_TIER_PALETTE` a cada tier de 50 combos
        extras e PULSA em brilho (seno sobre o relogio de parede --
        puramente cosmetico, sem nenhuma decisao de jogabilidade aqui,
        entao fora da disciplina Zero-GC do gameplay)."""
        if self._flow_tier <= 0:
            return (90, 70, 160)
        base = _FLOW_TIER_PALETTE[self._flow_tier % len(_FLOW_TIER_PALETTE)]
        pulse = 0.7 + 0.3 * math.sin(pygame.time.get_ticks() / 180.0)
        return tuple(min(255, int(channel * pulse)) for channel in base)

    def end_frame(self) -> None:
        if self._color_invert_pending and self._invert_surface is not None:
            self._invert_surface.fill((255, 255, 255))
            self._invert_surface.blit(self._surface, (0, 0), special_flags=pygame.BLEND_RGB_SUB)
            self._surface.blit(self._invert_surface, (0, 0))
        self._draw_sparks()
        self._draw_peripheral_metronome()
        self._draw_vision_tunnel()
        if self._blindness_active and self._vignette_surface is not None:
            self._surface.blit(self._vignette_surface, (0, 0))
        if self._overlay_mode is not None:
            self._draw_overlay()
        if self._notice_key is not None:
            self._blit_centered(self._notice_key, self._width // 2, 64)
        self._draw_hit_error_meter()
        self._draw_glitch_bars()
        self._draw_low_health_danger()
        super().end_frame()

    def _draw_low_health_danger(self) -> None:
        """Danger Visual (1 de vida): aberracao cromatica -- uma copia
        VERMELHA do frame ja pronto (overlay incluso) desloca 2px pra
        ESQUERDA, uma copia AZUL desloca 2px pra DIREITA, ambas somadas
        (`BLEND_RGB_ADD`) por cima do original -- "panico visual
        induzido" no ultimo ponto de vida. `BLEND_RGB_MULT` por
        (255,40,40)/(40,40,255) isola cada canal ANTES do deslocamento
        (zera os outros 2 quase por completo), entao a soma só acrescenta
        uma franja de cor nas bordas dos elementos em movimento, nunca
        escurece a tela. 2 Surfaces de rascunho persistentes (criadas 1x
        em `initialize`), nenhuma alocacao por frame."""
        if not self._low_health_danger_active:
            return
        if self._danger_red_surface is None or self._danger_blue_surface is None:
            return
        self._danger_red_surface.blit(self._surface, (0, 0))
        self._danger_red_surface.fill((255, 40, 40), special_flags=pygame.BLEND_RGB_MULT)
        self._surface.blit(self._danger_red_surface, (-2, 0), special_flags=pygame.BLEND_RGB_ADD)

        self._danger_blue_surface.blit(self._surface, (0, 0))
        self._danger_blue_surface.fill((40, 40, 255), special_flags=pygame.BLEND_RGB_MULT)
        self._surface.blit(self._danger_blue_surface, (2, 0), special_flags=pygame.BLEND_RGB_ADD)

    def _draw_sparks(self) -> None:
        """Juice Visual -- Sparks: laco escalar sobre o pool fixo (128
        por padrao) publicado por `set_sparks`, desenhando cada faisca
        VIVA (alfa > 0) como uma linha reta que parte de `(x, y)` no
        angulo armazenado, comprimento e alfa ja resolvidos pelo
        `SparkSystem` (nunca recalculados aqui). `pygame.draw.line` nao
        alfa-mescla numa Surface opaca, entao o "sumir" e aproximado
        interpolando a cor RUMO ao fundo da arena (ver `_ARENA_BG_COLOR`)
        -- visualmente equivalente a um fade, sem precisar de outra
        Surface `SRCALPHA` so para 128 linhas curtas."""
        count = self._spark_count
        if count == 0:
            return
        xs, ys, angles, lengths, alphas = (
            self._spark_xs, self._spark_ys, self._spark_angles, self._spark_lengths, self._spark_alphas
        )
        bg_r, bg_g, bg_b = _ARENA_BG_COLOR
        spark_r, spark_g, spark_b = _SPARK_COLOR
        cam_dx, cam_dy = self._cam_dx, self._cam_dy
        for i in range(count):
            alpha = float(alphas[i])
            if alpha <= 1.0:
                continue
            length = float(lengths[i])
            if length <= 0.5:
                continue
            fraction = alpha / 255.0
            color = (
                int(bg_r + (spark_r - bg_r) * fraction),
                int(bg_g + (spark_g - bg_g) * fraction),
                int(bg_b + (spark_b - bg_b) * fraction),
            )
            x = float(xs[i]) + cam_dx
            y = float(ys[i]) + cam_dy
            angle = float(angles[i])
            end_x = x + math.cos(angle) * length
            end_y = y + math.sin(angle) * length
            pygame.draw.line(self._surface, color, (x, y), (end_x, end_y), 2)

    def _draw_peripheral_metronome(self) -> None:
        """Metronomo Periferico (Heartbeat): 2 barras finas nas bordas
        esquerda/direita da tela, cujo brilho pulsa com `beat_phase` --
        um metronomo visual na PERIFERIA da visao, que nunca compete com
        a leitura da arena central. MESMO truque de "fade" por
        interpolacao de cor RUMO ao fundo (ver `_draw_sparks`) em vez de
        alfa de verdade -- sem Surface extra. No-op antes do primeiro
        playfield (menu inicial sem fase carregada ainda)."""
        if self._playfield_kind is None:
            return
        pulse = self._heartbeat_pulse()
        bg_r, bg_g, bg_b = _ARENA_BG_COLOR
        m_r, m_g, m_b = _METRONOME_COLOR
        color = (
            int(bg_r + (m_r - bg_r) * pulse),
            int(bg_g + (m_g - bg_g) * pulse),
            int(bg_b + (m_b - bg_b) * pulse),
        )
        bar_width = _METRONOME_BAR_WIDTH
        pygame.draw.rect(self._surface, color, pygame.Rect(0, 0, bar_width, self._height))
        pygame.draw.rect(
            self._surface, color, pygame.Rect(self._width - bar_width, 0, bar_width, self._height)
        )

    def _draw_vision_tunnel(self) -> None:
        """Colapso de Visao (Defensor -- "vision_tunnel", Tolerancia
        Organica): cobre a arena com um overlay opaco quase-preto, com
        um furo circular TOTALMENTE TRANSPARENTE (raio = `tunnel_radius`
        publicado via `set_playfield`, reinterpolado todo frame pelo
        `VisionTunnelSystem`) centrado no nucleo -- esconde o spawn de
        ameacas fora do campo de luz sem tocar NENHUMA fisica/velocidade
        (essas continuam lendo `GameState.current_judgment_radius`, fixo
        desde a composicao). Redesenhado a cada frame sobre a Surface
        persistente `_tunnel_surface` (nunca uma nova por frame) porque,
        ao contrario do Vignette Flash de tamanho fixo, o raio aqui
        interpola continuamente -- nao da pra pre-renderizar uma vez so.
        No-op fora do playfield radial, sem `tunnel_radius` publicado, ou
        quando o campo ja cobre a janela inteira (nada a esconder)."""
        if self._playfield_kind != "radial":
            return
        radius = self._playfield_params.get("tunnel_radius")
        if radius is None or radius >= max(self._width, self._height):
            return
        params = self._playfield_params
        surface = self._tunnel_surface
        surface.fill(_TUNNEL_COLOR)
        pygame.draw.circle(
            surface, (0, 0, 0, 0), (int(params["center_x"]), int(params["center_y"])), int(radius)
        )
        self._surface.blit(surface, (0, 0))

    def _blit_centered(self, key: str, center_x: int, y: int) -> int:
        """Blita a superficie `key` centrada horizontalmente em
        `center_x`, topo em `y`; retorna a altura consumida (0 se a
        chave nao foi registrada)."""
        surface = self._overlay_surfaces.get(key)
        if surface is None:
            return 0
        self._surface.blit(surface, (center_x - surface.get_width() // 2, y))
        return surface.get_height()

    def _digit_surface(self, digit: int) -> Optional["pygame.Surface"]:
        return self._textures.get(TEX_DIGIT_BASE + digit)

    def _measure_number(self, value: int) -> Tuple[int, int]:
        """Largura/altura que `_blit_number(value, ...)` vai consumir,
        SEM desenhar -- pro chamador centralizar um grupo (numero + rotulo
        + separador) antes de blitar qualquer coisa."""
        width = 0
        height = 0
        for char in str(max(0, int(value))):
            surface = self._digit_surface(int(char))
            if surface is not None:
                width += surface.get_width()
                height = max(height, surface.get_height())
        return width, height

    def _blit_number(self, value: int, x: int, y: int) -> int:
        """Blita `value` (inteiro >= 0) digito a digito com os MESMOS
        sprites 0-9 do HUD de jogo (`TEX_DIGIT_BASE`, ja registrados por
        `build_and_register_hud_textures`) -- nenhuma textura nova por
        numero exibido nos menus, so aritmetica sobre os 10 digitos que
        ja existem (mesma preferencia de "aritmetica sobre arrays" do
        pacote de Juice/Meta-Jogo anterior). Desenha a partir de `x`
        (esquerda) e retorna a largura total consumida."""
        cursor_x = x
        for char in str(max(0, int(value))):
            surface = self._digit_surface(int(char))
            if surface is not None:
                self._surface.blit(surface, (cursor_x, y))
                cursor_x += surface.get_width()
        return cursor_x - x

    def _blit_seconds_padded(self, seconds: int, x: int, y: int) -> int:
        """MESMO `_blit_number`, mas com um "0" a esquerda se `seconds`
        tiver 1 digito -- um relogio mm:ss sempre mostra 2 digitos de
        segundos (`3:05`, nunca `3:5`)."""
        seconds = max(0, int(seconds))
        cursor_x = x
        if seconds < 10:
            zero = self._digit_surface(0)
            if zero is not None:
                self._surface.blit(zero, (cursor_x, y))
                cursor_x += zero.get_width()
        cursor_x += self._blit_number(seconds, cursor_x, y)
        return cursor_x - x

    def _blit_fraction_centered(self, numerator: int, denominator: int, center_x: int, y: int) -> int:
        """`numerador / denominador` centralizado em `center_x` (Meta-
        Jogo -- Arquivos/Calibracao: fases vencidas de quantas existem,
        toques dados de quantos faltam) -- o separador "/" e a UNICA
        Surface pre-renderizada aqui, os numeros vem do atlas de digitos
        do HUD (`_blit_number`)."""
        num_w, num_h = self._measure_number(numerator)
        den_w, den_h = self._measure_number(denominator)
        slash = self._overlay_surfaces.get("slash")
        slash_w = slash.get_width() if slash is not None else 0
        slash_h = slash.get_height() if slash is not None else 0
        total_width = num_w + slash_w + den_w
        x = center_x - total_width // 2
        x += self._blit_number(numerator, x, y)
        if slash is not None:
            self._surface.blit(slash, (x, y))
            x += slash_w
        self._blit_number(denominator, x, y)
        return max(num_h, slash_h, den_h)

    def _blit_label_and_number_centered(self, label_key: str, value: int, center_x: int, y: int, gap: int = 8) -> int:
        """`rotulo NUMERO` centralizado (ex.: "BPM 128") -- rotulo
        pre-renderizado, numero pelo atlas de digitos do HUD."""
        label = self._overlay_surfaces.get(label_key)
        label_w = label.get_width() if label is not None else 0
        label_h = label.get_height() if label is not None else 0
        num_w, num_h = self._measure_number(value)
        total_gap = gap if label is not None else 0
        x = center_x - (label_w + total_gap + num_w) // 2
        if label is not None:
            self._surface.blit(label, (x, y))
            x += label_w + total_gap
        self._blit_number(value, x, y)
        return max(label_h, num_h)

    def _blit_duration_centered(self, label_key: str, total_seconds: float, center_x: int, y: int, gap: int = 8) -> int:
        """`rotulo mm:ss` centralizado (ex.: "DURACAO 2:45") -- MESMO
        criterio de `_blit_label_and_number_centered`, com os segundos
        sempre em 2 digitos (`_blit_seconds_padded`)."""
        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        label = self._overlay_surfaces.get(label_key)
        colon = self._overlay_surfaces.get("colon")
        label_w = label.get_width() if label is not None else 0
        label_h = label.get_height() if label is not None else 0
        min_w, min_h = self._measure_number(minutes)
        colon_w = colon.get_width() if colon is not None else 0
        sec_w, sec_h = self._measure_number(seconds if seconds >= 10 else seconds + 10)
        total_gap = gap if label is not None else 0
        x = center_x - (label_w + total_gap + min_w + colon_w + sec_w) // 2
        if label is not None:
            self._surface.blit(label, (x, y))
            x += label_w + total_gap
        x += self._blit_number(minutes, x, y)
        if colon is not None:
            self._surface.blit(colon, (x, y))
            x += colon_w
        self._blit_seconds_padded(seconds, x, y)
        return max(label_h, min_h, sec_h)

    def _draw_dot_row(self, count: int, focused_index: int, center_x: int, y: int) -> int:
        """Meta-Jogo -- Carrossel: fileira de pontos procedurais
        indicando "posicao N de `count`" -- desenhados em TEMPO REAL
        (mesmo criterio dos glifos de medalha), nunca uma textura por
        contagem possivel."""
        if count <= 1:
            return 0
        total_width = (count - 1) * _CAROUSEL_DOT_GAP
        start_x = center_x - total_width // 2
        radius = _CAROUSEL_DOT_RADIUS
        for i in range(count):
            color = _CAROUSEL_DOT_FOCUSED_COLOR if i == focused_index else _CAROUSEL_DOT_COLOR
            pygame.draw.circle(self._surface, color, (start_x + i * _CAROUSEL_DOT_GAP, y + radius), radius)
        return radius * 2

    def _draw_stage_row(self, key: str, medal_count: int, center_x: int, y: int) -> int:
        """Meta-Jogo -- Medalhas: blita o rotulo de UMA fase (mesmo
        `_blit_centered` de sempre) e, se `medal_count > 0`, desenha uma
        fileira de pequenos quadrados dourados a DIREITA dele -- um por
        modifier distinto ja vencido nessa fase/musica
        (`player_progress.json`), capada em `_MEDAL_MAX_GLYPHS` (mais
        que isso na tela vira ruido, nao informacao). Procedural
        (`pygame.draw.rect`), mesmo criterio de `_draw_modifier_row` --
        um quadrado simples nao precisa de textura pre-renderizada."""
        surface = self._overlay_surfaces.get(key)
        if surface is None:
            return 0
        label_width = surface.get_width()
        height = surface.get_height()
        self._surface.blit(surface, (center_x - label_width // 2, y))

        glyph_count = min(medal_count, _MEDAL_MAX_GLYPHS)
        if glyph_count > 0:
            glyph_x = center_x + label_width // 2 + _MEDAL_GLYPH_GAP
            glyph_y = y + height // 2 - _MEDAL_GLYPH_SIZE // 2
            for i in range(glyph_count):
                rect = pygame.Rect(
                    glyph_x + i * (_MEDAL_GLYPH_SIZE + _MEDAL_GLYPH_GAP),
                    glyph_y, _MEDAL_GLYPH_SIZE, _MEDAL_GLYPH_SIZE,
                )
                pygame.draw.rect(self._surface, _MEDAL_GLYPH_COLOR, rect)
        return height

    def _draw_medal_glyphs_centered(self, medal_count: int, center_x: int, y: int) -> int:
        """MESMOS glifos de `_draw_stage_row`, mas centralizados sozinhos
        (sem rotulo ao lado) -- usado pelo Carrossel, que ja mostra o
        nome da fase em foco numa linha propria acima."""
        glyph_count = min(medal_count, _MEDAL_MAX_GLYPHS)
        if glyph_count <= 0:
            return 0
        total_width = glyph_count * _MEDAL_GLYPH_SIZE + (glyph_count - 1) * _MEDAL_GLYPH_GAP
        glyph_x = center_x - total_width // 2
        for i in range(glyph_count):
            rect = pygame.Rect(
                glyph_x + i * (_MEDAL_GLYPH_SIZE + _MEDAL_GLYPH_GAP), y, _MEDAL_GLYPH_SIZE, _MEDAL_GLYPH_SIZE,
            )
            pygame.draw.rect(self._surface, _MEDAL_GLYPH_COLOR, rect)
        return _MEDAL_GLYPH_SIZE

    def _draw_modifier_row(self, label_key: str, checked, is_cursor: bool, center_x: int, y: int) -> int:
        """Desenha UMA linha do painel de checkboxes do seletor de
        minigame (Mecanicas Modulares): um pequeno quadrado desenhado em
        TEMPO REAL (preenchido se `checked`, so contorno se nao -- mesmo
        padrao de `_draw_inner_square`, nenhum `font.render`) a esquerda
        do rotulo pre-renderizado `label_key`. `checked=None` (linha
        especial `_GAME_MODE_ROW`) omite o quadrado -- o rotulo ja vem
        com as setas "< DEFENSOR >"/"< ARCADE 4K >" prontas. A linha em
        FOCO (`is_cursor`) ganha um retangulo de destaque ao redor.
        Retorna a altura consumida (0 se o rotulo nao foi registrado),
        mesmo contrato de `_blit_centered`, pra encadear no `y` do
        chamador."""
        surface = self._overlay_surfaces.get(label_key)
        if surface is None:
            return 0
        label_width = surface.get_width()
        height = surface.get_height()
        has_checkbox = checked is not None
        box_span = (_CHECKBOX_SIZE + _CHECKBOX_GAP) if has_checkbox else 0
        total_width = label_width + box_span
        left = center_x - total_width // 2

        if has_checkbox:
            box_rect = pygame.Rect(left, y + height // 2 - _CHECKBOX_SIZE // 2, _CHECKBOX_SIZE, _CHECKBOX_SIZE)
            pygame.draw.rect(self._surface, _CHECKBOX_COLOR, box_rect, 0 if checked else 2)
            label_x = left + box_span
        else:
            label_x = left
        self._surface.blit(surface, (label_x, y))

        if is_cursor:
            highlight_rect = pygame.Rect(
                left - _CURSOR_HIGHLIGHT_PADDING, y - _CURSOR_HIGHLIGHT_PADDING // 2,
                total_width + _CURSOR_HIGHLIGHT_PADDING * 2, height + _CURSOR_HIGHLIGHT_PADDING,
            )
            pygame.draw.rect(self._surface, _CURSOR_HIGHLIGHT_COLOR, highlight_rect, 2)
        return height

    def _draw_overlay(self) -> None:
        """Desenha o overlay do estado publicado por `set_overlay` usando
        apenas superficies pre-renderizadas (nenhum font.render aqui)."""
        self._surface.blit(self._dim_surface, (0, 0))
        center_x = self._width // 2

        if self._overlay_mode == "title":
            self._draw_title_overlay(center_x)
        elif self._overlay_mode == "hub":
            self._draw_hub_overlay(center_x)
        elif self._overlay_mode == "carousel":
            self._draw_carousel_overlay(center_x)
        elif self._overlay_mode == "preflight":
            self._draw_preflight_overlay(center_x)
        elif self._overlay_mode == "vault":
            self._draw_vault_overlay(center_x)
        elif self._overlay_mode == "calibration":
            self._draw_calibration_overlay(center_x)
        elif self._overlay_mode == "paused":
            self._blit_centered("paused", center_x, int(self._height * 0.40))
            self._blit_centered("hint_paused", center_x, self._height - 110)
        elif self._overlay_mode == "game_over":
            self._blit_centered("game_over", center_x, int(self._height * 0.40))
            self._blit_centered("hint_end", center_x, self._height - 110)
        elif self._overlay_mode == "results":
            y = int(self._height * 0.40)
            y += self._blit_centered("results", center_x, y) + 10
            # Meta-Jogo -- Rank: so preenchido pelo HertzGameLoop na
            # transicao pra resultados (calculado 1x, nunca por frame).
            if self._overlay_rank is not None:
                y += self._blit_centered(f"rank_{self._overlay_rank}", center_x, y) + 10
            y += self._draw_hit_error_histogram(center_x, y + 8)
            self._blit_centered("hint_results", center_x, self._height - 110)

    # -- O Novo Fluxo de Menus (Experiencia Arcade) -----------------------

    def _draw_title_overlay(self, center_x: int) -> None:
        """Tela de Titulo: logo pulsando no `beat_phase` (MESMO
        `_heartbeat_pulse` do Anel de Julgamento/Grid Warp -- um "thump"
        seco no inicio de cada compasso, nunca uma oscilacao simetrica) e
        "PRESSIONE ESPACO" piscando (alfa em seno sobre o relogio de
        parede, mesmo criterio de `_judgment_line_color`)."""
        y = int(self._height * 0.32)
        title = self._overlay_surfaces.get("title")
        if title is not None:
            scale = 1.0 + _HEARTBEAT_RING_ZOOM * self._heartbeat_pulse()
            size = (max(1, int(title.get_width() * scale)), max(1, int(title.get_height() * scale)))
            scaled = pygame.transform.smoothscale(title, size)
            self._surface.blit(scaled, (center_x - size[0] // 2, y - (size[1] - title.get_height()) // 2))
            y += title.get_height() + 14
        y += self._blit_centered("subtitle", center_x, y) + 60

        press_space = self._overlay_surfaces.get("press_space")
        if press_space is not None:
            blink = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 260.0)
            press_space.set_alpha(int(90 + blink * 165))
            self._surface.blit(press_space, (center_x - press_space.get_width() // 2, y))
            press_space.set_alpha(255)

    def _draw_hub_overlay(self, center_x: int) -> None:
        """HUB Principal: as 4 categorias grandes (`_HUB_CATEGORIES`),
        a em foco (`hub_cursor`) destacada pela MESMA variante "_sel"
        (setas + dourado) das linhas de fase do antigo menu unico."""
        y = int(self._height * 0.22)
        y += self._blit_centered("title", center_x, y) + 70
        for i, category in enumerate(_HUB_CATEGORIES):
            key = f"hub_category_{category}_sel" if i == self._overlay_hub_cursor else f"hub_category_{category}"
            y += self._blit_centered(key, center_x, y) + 26
        self._blit_centered("hint_hub", center_x, self._height - 54)

    def _draw_carousel_overlay(self, center_x: int) -> None:
        """Carrossel: SO a entrada em foco toma o centro da tela (nunca a
        lista inteira) -- nome, a frase de lore/imersao da fase
        (`StageDef.description`), BPM/duracao, Rank Maximo e Medalhas
        dessa musica especifica, mais a fileira de pontos "N de M". Uma
        fase de Campanha ainda trancada troca o resumo de progresso por
        um aviso (nao ha rank/medalha relevante numa fase nunca jogada).
        `cycle_view_next`/`cycle_view_prev` (TAB/Q/E) trocam a campanha
        em foco sem sair daqui -- ver `HertzGameLoop._cycle_carousel_view`."""
        category = self._overlay_carousel_category or "free_play"
        y = int(self._height * 0.10)
        y += self._blit_centered(f"carousel_category_{category}", center_x, y) + 30

        stage_index = self._overlay_carousel_stage_index
        if stage_index is None:
            self._blit_centered("carousel_empty", center_x, y + 20)
            self._blit_centered("hint_carousel_switch_view", center_x, self._height - 78)
            self._blit_centered("hint_carousel", center_x, self._height - 54)
            return

        y += self._blit_centered(f"stage_{stage_index}_sel", center_x, y) + 34
        y += self._blit_centered(f"stage_{stage_index}_description", center_x, y) + 16
        if self._overlay_carousel_locked:
            self._blit_centered("carousel_locked_badge", center_x, y)
            y += 40
        else:
            progress = self._overlay_carousel_progress or {}
            best_rank = progress.get("best_rank") or "-"
            medal_count = len(progress.get("modifiers", ()))
            y += self._blit_centered(f"rank_{best_rank}", center_x, y) + 8
            if medal_count > 0:
                y += self._draw_medal_glyphs_centered(medal_count, center_x, y) + 10
            y += self._blit_label_and_number_centered("label_bpm", int(round(self._overlay_carousel_bpm)), center_x, y) + 6
            y += self._blit_duration_centered("label_duration", self._overlay_carousel_duration_seconds, center_x, y) + 20

        self._draw_dot_row(self._overlay_carousel_count, self._overlay_carousel_position, center_x, y)
        self._blit_centered("hint_carousel_switch_view", center_x, self._height - 78)
        self._blit_centered("hint_carousel", center_x, self._height - 54)

    def _draw_preflight_overlay(self, center_x: int) -> None:
        """Pre-Voo: o Multiplicador de Pontuacao ao vivo no topo (MESMA
        formula `compute_score_multiplier` da composicao real, nunca uma
        conta paralela) seguido do painel de opcoes completo (musicas do
        jogador) ou dos modifiers FIXOS em modo leitura (fases curadas da
        Campanha -- a dificuldade curada e o ponto da Campanha, entao so
        o botao START e interativo aqui)."""
        y = int(self._height * 0.14)
        step = int(round((self._overlay_score_multiplier - _SCORE_MULTIPLIER_MIN) / _SCORE_MULTIPLIER_STEP))
        step = max(0, min(_SCORE_MULTIPLIER_STEPS, step))
        y += self._blit_centered(f"score_multiplier_{step}", center_x, y) + 40

        panel = self._overlay_modifier_panel
        if panel is not None:
            for i, row_name in enumerate(panel["rows"]):
                is_cursor = panel["focused"] and i == panel["cursor"]
                if row_name == _GAME_MODE_ROW:
                    label_key = f"modifier_row_game_mode_{panel['game_mode']}"
                    y += self._draw_modifier_row(label_key, None, is_cursor, center_x, y) + 6
                elif row_name == _HEAVY_MECHANIC_ROW:
                    label_key = f"modifier_row_heavy_mechanic_{panel['heavy_mechanic']}"
                    y += self._draw_modifier_row(label_key, None, is_cursor, center_x, y) + 6
                elif row_name == _START_ROW:
                    y += self._draw_modifier_row("modifier_row_start", None, is_cursor, center_x, y) + 6
                else:
                    checked = row_name in panel["modifiers"]
                    y += self._draw_modifier_row(f"modifier_row_{row_name}", checked, is_cursor, center_x, y) + 6
            practice_key = "practice_on" if self._overlay_practice_enabled else "practice_off"
            y += self._blit_centered(practice_key, center_x, y + 6) + 10
            self._blit_centered("hint_preflight_options", center_x, self._height - 54)
        else:
            stage_index = self._overlay_preflight_stage_index
            if stage_index is not None:
                y += self._blit_centered(f"stage_{stage_index}_hint", center_x, y + 10) + 10
                b_side = self._overlay_b_side_info
                if b_side is not None:
                    if b_side["chosen"]:
                        y += self._blit_centered(f"stage_{stage_index}_b_side_name", center_x, y + 6) + 10
                    else:
                        y += self._blit_centered(f"stage_{stage_index}_b_side_hint", center_x, y + 6) + 10
            self._blit_centered("hint_preflight_curated", center_x, self._height - 54)

    def _draw_vault_overlay(self, center_x: int) -> None:
        """Arquivos (Vault): agregados globais de `player_progress.json`
        (fases vencidas de quantas existem, medalhas totais, quantas
        vezes cada Rank ja foi o MELHOR alcancado nalguma fase) mais as
        Estatisticas Globais VITALICIAS de `player_lifetime_stats.json`
        (PERFECTs/tiros/tempo jogado, nunca zeradas por fase). Todo
        numero vem do atlas de digitos do HUD (`_blit_number`), nunca de
        uma textura nova por valor possivel."""
        stats = self._overlay_vault_stats or {}
        y = int(self._height * 0.10)
        y += self._blit_centered("vault_title", center_x, y) + 40
        y += self._blit_centered("label_cleared", center_x, y) + 6
        y += self._blit_fraction_centered(
            stats.get("stages_cleared", 0), stats.get("total_stages", 0), center_x, y
        ) + 20
        y += self._blit_label_and_number_centered("label_medals", stats.get("total_medals", 0), center_x, y) + 26

        for rank, count in stats.get("rank_counts", {}).items():
            y += self._blit_label_and_number_centered(f"rank_{rank}", count, center_x, y) + 8
        y += 18
        y += self._blit_label_and_number_centered(
            "label_lifetime_perfect", stats.get("lifetime_perfect_count", 0), center_x, y
        ) + 8
        y += self._blit_label_and_number_centered(
            "label_lifetime_shots", stats.get("lifetime_shots_fired", 0), center_x, y
        ) + 8
        y += self._blit_duration_centered(
            "label_lifetime_playtime", stats.get("lifetime_playtime_seconds", 0.0), center_x, y
        ) + 20

        # Meta-Jogo -- Paletas Cosmeticas: nome da paleta ATUAL + quantas
        # ja foram desbloqueadas (Rank ja alcancado nalguma fase/musica) --
        # A/D cicla so entre as desbloqueadas, ver `HertzGameLoop._cycle_palette`.
        palette_id = stats.get("palette_id", "classic")
        y += self._blit_centered("label_palette", center_x, y) + 6
        self._blit_centered(f"palette_name_{palette_id}", center_x, y)
        self._blit_centered("hint_vault", center_x, self._height - 54)

    def _draw_calibration_overlay(self, center_x: int) -> None:
        """Calibracao: instrucao fixa + contador `toques dados/alvo` +
        feedback de cedo/tarde/no tempo do ULTIMO toque (3 texturas
        discretas -- nunca o valor continuo do desvio em segundos, que
        exigiria `font.render` no loop)."""
        y = int(self._height * 0.20)
        y += self._blit_centered("calibration_hint", center_x, y) + 40

        taps_given, taps_target, last_offset = self._overlay_calibration_progress or (0, 0, None)
        y += self._blit_centered("label_taps", center_x, y) + 6
        y += self._blit_fraction_centered(taps_given, taps_target, center_x, y) + 30

        if last_offset is not None:
            if last_offset < -_CALIBRATION_ONTIME_THRESHOLD_SECONDS:
                feedback_key = "calibration_early"
            elif last_offset > _CALIBRATION_ONTIME_THRESHOLD_SECONDS:
                feedback_key = "calibration_late"
            else:
                feedback_key = "calibration_ontime"
            self._blit_centered(feedback_key, center_x, y)
        self._blit_centered("hint_calibration", center_x, self._height - 54)

    def draw_batch(
        self,
        positions_xy: np.ndarray,
        rotations_rad: np.ndarray,
        scales_xy: np.ndarray,
        texture_ids: np.ndarray,
        tint_rgba: np.ndarray,
        layer_z: np.ndarray,
        count: int,
    ) -> None:
        if self._freeze_active:
            return  # Juice de Parry: nao desenha nada -- begin_frame ja preservou a Surface anterior
        if count == 0:
            return
        draw_order = np.argsort(layer_z[:count], kind="stable")
        cam_dx, cam_dy = self._cam_dx, self._cam_dy
        for i in draw_order:
            i = int(i)
            alpha = int(tint_rgba[i, 3])
            if alpha == 0:
                continue
            x = float(positions_xy[i, 0]) + cam_dx
            y = float(positions_xy[i, 1]) + cam_dy
            texture = self._textures.get(int(texture_ids[i]))
            if texture is not None:
                # NUNCA set_alpha(None): em pygame isso DESLIGA o alpha
                # por pixel e o texto blitaria como um bloco solido da
                # cor da fonte. 255 = opaco preservando o canal alpha.
                texture.set_alpha(alpha)
                self._surface.blit(
                    texture,
                    (int(x - texture.get_width() / 2), int(y - texture.get_height() / 2)),
                )
            else:
                scale_x = max(float(scales_xy[i, 0]), 0.01)
                scale_y = max(float(scales_xy[i, 1]), 0.01)
                color = (int(tint_rgba[i, 0]), int(tint_rgba[i, 1]), int(tint_rgba[i, 2]))
                shape_id = int(texture_ids[i])
                if shape_id == TEX_CONVERGENCE_RING:  # contorno
                    pygame.draw.circle(
                        self._surface, color, (int(x), int(y)), max(2, int(8.0 * scale_x)), 2
                    )
                elif shape_id in (TEX_THREAT_POLARITY_BLUE, TEX_PLAYER_CORE_BLUE):
                    # Polaridade -- acessibilidade a daltonismo: TRIANGULO
                    # interno alem da cor (Azul), fixo independente do tint.
                    radius = max(2, int(8.0 * scale_x))
                    pygame.draw.circle(self._surface, color, (int(x), int(y)), radius)
                    self._draw_inner_triangle(x, y, radius)
                elif shape_id in (TEX_THREAT_POLARITY_PINK, TEX_PLAYER_CORE_PINK):
                    # mesma logica, QUADRADO interno (Rosa).
                    radius = max(2, int(8.0 * scale_x))
                    pygame.draw.circle(self._surface, color, (int(x), int(y)), radius)
                    self._draw_inner_square(x, y, radius)
                elif abs(scale_x - scale_y) > 0.01:
                    # escala anisotropica = barra (Notas Longas/Scratch, Arcade 4K)
                    width = max(1, int(16.0 * scale_x))
                    height = max(1, int(16.0 * scale_y))
                    rect = pygame.Rect(int(x - width / 2), int(y - height / 2), width, height)
                    pygame.draw.rect(self._surface, color, rect)
                else:
                    pygame.draw.circle(self._surface, color, (int(x), int(y)), max(1, int(8.0 * scale_x)))

    def _draw_inner_triangle(self, x: float, y: float, radius: int) -> None:
        """Simbolo interno FIXO da Polaridade Azul (acessibilidade a
        daltonismo -- nunca depende so da cor). Tamanho proporcional ao
        raio do circulo externo."""
        side = max(2, int(radius * 0.62))
        points = [
            (x, y - side),
            (x - side * 0.87, y + side * 0.5),
            (x + side * 0.87, y + side * 0.5),
        ]
        pygame.draw.polygon(self._surface, _INNER_MARK_COLOR, points)

    def _draw_inner_square(self, x: float, y: float, radius: int) -> None:
        """Simbolo interno FIXO da Polaridade Rosa."""
        side = max(2, int(radius * 0.9))
        rect = pygame.Rect(0, 0, side, side)
        rect.center = (int(x), int(y))
        pygame.draw.rect(self._surface, _INNER_MARK_COLOR, rect)
