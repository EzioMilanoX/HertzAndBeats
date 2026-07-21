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
"""Mesmo literal de `hertzbeats.bootstrap.hertz_game_loop.GAME_MODE_ROW`
-- duplicado de proposito (este adapter nao importa o game loop, seria
o sentido INVERSO de dependencia adapter->orquestracao) pra reconhecer
a linha especial de Defensor/Arcade 4K do painel de checkboxes e
desenha-la SEM quadrado de marcar."""

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
        self._notice_key: Optional[str] = None
        self._dim_surface: Optional[pygame.Surface] = None
        self._flow_mode_active: bool = False
        self._flow_tier: int = 0
        self._vignette_surface: Optional[pygame.Surface] = None
        self._blindness_active: bool = False
        self._freeze_active: bool = False
        self._color_invert_pending: bool = False
        self._invert_surface: Optional[pygame.Surface] = None

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
    ) -> None:
        """Publica o estado de fluxo a desenhar sobre o frame: `None`
        (jogando, sem overlay), "menu", "paused", "game_over" ou
        "results". `modifier_panel` (fases de musica do jogador, `None`
        em fases curadas) troca a dica fixa da fase pelo painel de
        checkboxes do seletor de minigame -- um dict
        `{"game_mode", "modifiers", "rows", "cursor"}` (ver
        `HertzGameLoop._sync_overlay`). `practice_enabled` (`None` em
        fases curadas, `True`/`False` nas musicas do jogador) mostra o
        estado do Modo Treino junto do painel. Chamado pelo
        `HertzGameLoop` a cada frame."""
        self._overlay_mode = mode
        self._overlay_selected = int(selected_index)
        self._overlay_stage_count = int(stage_count)
        self._overlay_modifier_panel = modifier_panel
        self._overlay_practice_enabled = practice_enabled

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

    def set_playfield(self, kind: Optional[str], **params) -> None:
        """Define a decoracao de arena do MODO ativo, desenhada a cada
        `begin_frame`. Chamado pelo `HertzGameLoop` a cada troca de fase:

            "radial" -- aneis-guia do Defensor (spawn + anel de julgamento):
                center_x, center_y, spawn_radius, judgment_radius
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
        if kind == "radial":
            center = (int(params["center_x"]), int(params["center_y"]))
            pygame.draw.circle(self._surface, (36, 28, 70), center, int(params["spawn_radius"]), 1)
            pygame.draw.circle(self._surface, (90, 70, 160), center, int(params["judgment_radius"]), 2)
        if kind == "lanes":
            height = int(params["height"])
            judgment_y = int(params["judgment_y"])
            lane_half = int(params["lane_half_width"])
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
        if self._blindness_active and self._vignette_surface is not None:
            self._surface.blit(self._vignette_surface, (0, 0))
        if self._overlay_mode is not None:
            self._draw_overlay()
        if self._notice_key is not None:
            self._blit_centered(self._notice_key, self._width // 2, 64)
        super().end_frame()

    def _blit_centered(self, key: str, center_x: int, y: int) -> int:
        """Blita a superficie `key` centrada horizontalmente em
        `center_x`, topo em `y`; retorna a altura consumida (0 se a
        chave nao foi registrada)."""
        surface = self._overlay_surfaces.get(key)
        if surface is None:
            return 0
        self._surface.blit(surface, (center_x - surface.get_width() // 2, y))
        return surface.get_height()

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
                y += self._blit_centered(key, center_x, y) + 16
            if first + MAX_VISIBLE < count:
                y += self._blit_centered("scroll_down", center_x, y) + 8

            # fase de musica do jogador: painel de checkboxes (Mecanicas
            # Modulares) + Modo Treino; fase curada: dica fixa de
            # controles do modo dela
            panel = self._overlay_modifier_panel
            if panel is not None:
                y += 14
                for i, row_name in enumerate(panel["rows"]):
                    is_cursor = i == panel["cursor"]
                    if row_name == _GAME_MODE_ROW:
                        label_key = f"modifier_row_game_mode_{panel['game_mode']}"
                        y += self._draw_modifier_row(label_key, None, is_cursor, center_x, y) + 6
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
            self._blit_centered("results", center_x, int(self._height * 0.40))
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
