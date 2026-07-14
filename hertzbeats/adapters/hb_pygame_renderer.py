"""PygameRenderer estendido com registro de texturas pre-renderizadas e visual radial."""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pygame

from ouroboros.adapters.pygame_backend.pygame_renderer import PygameRenderer


class HBPygameRenderer(PygameRenderer):
    """
    `PygameRenderer` da engine estendido para o Hertz & Beats com:

        - `register_texture(texture_id, surface)`: associa um inteiro de
          `sprite.texture_id` a uma Surface PRE-RENDERIZADA na tela de
          carregamento (digitos 0-9, palavras PERFECT/GOOD/MISS, pips).
          `draw_batch` blita a textura registrada; ids sem textura caem
          no desenho procedural (circulos -- nucleo, ameacas, mira).
        - `configure_playfield(...)`: aneis-guia da arena radial (borda
          de spawn e anel de julgamento do nucleo), desenhados em
          `begin_frame`.
        - `tint_a == 0` oculta o sprite (usado pelo HUD para zeros a
          esquerda e palavras expiradas).

    Continua respeitando o contrato `IRenderer`: uma unica chamada
    `draw_batch` por frame cruzando a fronteira core->adapter. O laco
    por sprite vive AQUI no adapter, fora da jurisdicao Zero-GC do
    gameplay (mesma nota honesta do renderer base da engine).
    """

    def __init__(self) -> None:
        super().__init__()
        self._textures: Dict[int, pygame.Surface] = {}
        self._playfield: Optional[Tuple[int, int, int, int]] = None
        self._overlay_surfaces: Dict[str, pygame.Surface] = {}
        self._overlay_mode: Optional[str] = None
        self._overlay_selected: int = 0
        self._overlay_stage_count: int = 0
        self._dim_surface: Optional[pygame.Surface] = None

    def register_texture(self, texture_id: int, surface: "pygame.Surface") -> None:
        """Registra `surface` (ja convertida com alpha) para `texture_id`.
        Chamado apenas na fase de carregamento, nunca no loop."""
        self._textures[int(texture_id)] = surface

    def register_overlay_surface(self, key: str, surface: "pygame.Surface") -> None:
        """Registra uma superficie de overlay de meta-jogo (titulo do
        menu, nomes de fase, PAUSADO, GAME OVER, ...) pre-renderizada na
        composicao. Chaves consumidas por `_draw_overlay`."""
        self._overlay_surfaces[key] = surface

    def set_overlay(self, mode: Optional[str], selected_index: int = 0, stage_count: int = 0) -> None:
        """Publica o estado de fluxo a desenhar sobre o frame: `None`
        (jogando, sem overlay), "menu", "paused", "game_over" ou
        "results". Chamado pelo `HertzGameLoop` a cada frame."""
        self._overlay_mode = mode
        self._overlay_selected = int(selected_index)
        self._overlay_stage_count = int(stage_count)

    def configure_playfield(
        self,
        center_x: float,
        center_y: float,
        spawn_radius: float,
        judgment_radius: float,
    ) -> None:
        """Define os aneis-guia da arena, desenhados a cada `begin_frame`."""
        self._playfield = (int(center_x), int(center_y), int(spawn_radius), int(judgment_radius))

    def initialize(self, width: int, height: int, title: str) -> None:
        super().initialize(width, height, title)
        self._dim_surface = pygame.Surface((width, height), pygame.SRCALPHA)
        self._dim_surface.fill((4, 2, 12, 178))

    def begin_frame(self) -> None:
        self._surface.fill((8, 6, 20))
        if self._playfield is not None:
            center_x, center_y, spawn_radius, judgment_radius = self._playfield
            pygame.draw.circle(self._surface, (36, 28, 70), (center_x, center_y), spawn_radius, 1)
            pygame.draw.circle(self._surface, (90, 70, 160), (center_x, center_y), judgment_radius, 2)

    def end_frame(self) -> None:
        if self._overlay_mode is not None:
            self._draw_overlay()
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

    def _draw_overlay(self) -> None:
        """Desenha o overlay do estado publicado por `set_overlay` usando
        apenas superficies pre-renderizadas (nenhum font.render aqui)."""
        self._surface.blit(self._dim_surface, (0, 0))
        center_x = self._width // 2

        if self._overlay_mode == "menu":
            y = int(self._height * 0.18)
            y += self._blit_centered("title", center_x, y) + 18
            y += self._blit_centered("subtitle", center_x, y) + 60
            for i in range(self._overlay_stage_count):
                key = f"stage_{i}_sel" if i == self._overlay_selected else f"stage_{i}"
                y += self._blit_centered(key, center_x, y) + 26
            self._blit_centered("hint_menu", center_x, self._height - 110)
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
        if count == 0:
            return
        draw_order = np.argsort(layer_z[:count], kind="stable")
        for i in draw_order:
            i = int(i)
            alpha = int(tint_rgba[i, 3])
            if alpha == 0:
                continue
            x, y = float(positions_xy[i, 0]), float(positions_xy[i, 1])
            texture = self._textures.get(int(texture_ids[i]))
            if texture is not None:
                if alpha != 255:
                    texture.set_alpha(alpha)
                else:
                    texture.set_alpha(None)
                self._surface.blit(
                    texture,
                    (int(x - texture.get_width() / 2), int(y - texture.get_height() / 2)),
                )
            else:
                radius = max(1, int(8.0 * max(float(scales_xy[i, 0]), 0.01)))
                color = (int(tint_rgba[i, 0]), int(tint_rgba[i, 1]), int(tint_rgba[i, 2]))
                pygame.draw.circle(self._surface, color, (int(x), int(y)), radius)
