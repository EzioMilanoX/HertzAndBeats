"""PygameRenderer estendido com registro de texturas pre-renderizadas e visual radial."""
from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

import numpy as np
import pygame

from ouroboros.adapters.pygame_backend.pygame_renderer import PygameRenderer

from hertzbeats.components.texture_ids import (
    TEX_CONVERGENCE_RING,
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
        self._overlay_selected: int = 0
        self._overlay_stage_count: int = 0
        self._overlay_modifier_panel: Optional[dict] = None
        self._overlay_practice_enabled: Optional[bool] = None
        self._overlay_rank: Optional[str] = None
        self._overlay_medal_counts: tuple = ()
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
        selected_index: int = 0,
        stage_count: int = 0,
        modifier_panel: Optional[dict] = None,
        practice_enabled: Optional[bool] = None,
        rank: Optional[str] = None,
        medal_counts: tuple = (),
    ) -> None:
        """Publica o estado de fluxo a desenhar sobre o frame: `None`
        (jogando, sem overlay), "menu", "paused", "game_over" ou
        "results". `modifier_panel` (fases de musica do jogador, `None`
        em fases curadas) troca a dica fixa da fase pelo painel de
        checkboxes do seletor de minigame -- um dict
        `{"game_mode", "modifiers", "rows", "cursor"}` (ver
        `HertzGameLoop._sync_overlay`). `practice_enabled` (`None` em
        fases curadas, `True`/`False` nas musicas do jogador) mostra o
        estado do Modo Treino junto do painel. `rank` (Meta-Jogo, so
        preenchido em "results"): letra ja calculada por
        `hertzbeats.game_state.compute_rank`, blitada como
        `rank_{letra}`. `medal_counts` (Meta-Jogo): tupla PARALELA a
        lista de fases -- quantos modifiers distintos ja foram vencidos
        em cada uma (`player_progress.json`), desenhada como glifos ao
        lado do rotulo de cada fase visivel no menu. Chamado pelo
        `HertzGameLoop` a cada frame."""
        self._overlay_mode = mode
        self._overlay_selected = int(selected_index)
        self._overlay_stage_count = int(stage_count)
        self._overlay_modifier_panel = modifier_panel
        self._overlay_practice_enabled = practice_enabled
        self._overlay_rank = rank
        self._overlay_medal_counts = medal_counts

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
        super().end_frame()

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

        if self._overlay_mode == "menu":
            y = int(self._height * 0.09)
            y += self._blit_centered("title", center_x, y) + 10
            y += self._blit_centered("subtitle", center_x, y) + 30

            # janela rolavel: com muitas musicas, mostra ate MAX_VISIBLE
            # fases centradas na selecao, com setas de "ha mais"
            MAX_VISIBLE = 8
            count = self._overlay_stage_count
            first = 0
            if count > MAX_VISIBLE:
                first = min(max(self._overlay_selected - MAX_VISIBLE // 2, 0), count - MAX_VISIBLE)
            if first > 0:
                y += self._blit_centered("scroll_up", center_x, y) + 8
            for i in range(first, min(first + MAX_VISIBLE, count)):
                key = f"stage_{i}_sel" if i == self._overlay_selected else f"stage_{i}"
                medal_count = self._overlay_medal_counts[i] if i < len(self._overlay_medal_counts) else 0
                y += self._draw_stage_row(key, medal_count, center_x, y) + 16
            if first + MAX_VISIBLE < count:
                y += self._blit_centered("scroll_down", center_x, y) + 8

            # fase de musica do jogador: menu de opcoes (Mecanicas
            # Modulares, padrao Arcade/RPG) + Modo Treino; fase curada:
            # dica fixa de controles do modo dela
            panel = self._overlay_modifier_panel
            if panel is not None:
                y += 14
                for i, row_name in enumerate(panel["rows"]):
                    # o destaque da linha em foco SO aparece com o
                    # cursor DENTRO do menu de opcoes (`panel["focused"]`)
                    # -- fora dele, o jogador ainda so navega a lista de
                    # fases, nenhuma linha do menu esta "em edicao".
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
                self._blit_centered(practice_key, center_x, y + 6)
            else:
                self._blit_centered(f"stage_{self._overlay_selected}_hint", center_x, y + 16)
            self._blit_centered("hint_menu", center_x, self._height - 54)
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
            self._blit_centered("hint_results", center_x, self._height - 110)

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
