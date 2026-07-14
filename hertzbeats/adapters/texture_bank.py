"""
Pre-renderizacao das texturas de HUD na tela de carregamento: os
digitos 0-9 e as palavras PERFECT/GOOD/MISS viram Surfaces ESTATICAS
registradas no renderer UMA unica vez. Nenhum `font.render` acontece
depois disso -- o `UIRenderSystem` so escolhe `texture_id` por
aritmetica e o `draw_batch` blita as Surfaces ja prontas.
"""
from __future__ import annotations

import pygame

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.components.texture_ids import (
    TEX_CROSSHAIR,
    TEX_DIGIT_BASE,
    TEX_HEALTH_PIP,
    TEX_LABEL_COMBO,
    TEX_LABEL_SCORE,
    TEX_WORD_GOOD,
    TEX_WORD_MISS,
    TEX_WORD_PERFECT,
)

_DIGIT_COLOR = (235, 235, 255)
_LABEL_COLOR = (130, 125, 170)
_PERFECT_COLOR = (255, 214, 64)
_GOOD_COLOR = (64, 255, 214)
_MISS_COLOR = (255, 80, 96)


def build_and_register_hud_textures(renderer: HBPygameRenderer) -> None:
    """Renderiza e registra todas as texturas de HUD. Chamado UMA vez na
    composicao, depois de `renderer.initialize` (precisa do display
    ativo para `convert_alpha`)."""
    if not pygame.font.get_init():
        pygame.font.init()

    digit_font = pygame.font.Font(None, 46)
    word_font = pygame.font.Font(None, 64)
    label_font = pygame.font.Font(None, 28)

    for digit in range(10):
        surface = digit_font.render(str(digit), True, _DIGIT_COLOR).convert_alpha()
        renderer.register_texture(TEX_DIGIT_BASE + digit, surface)

    renderer.register_texture(TEX_WORD_PERFECT, word_font.render("PERFECT", True, _PERFECT_COLOR).convert_alpha())
    renderer.register_texture(TEX_WORD_GOOD, word_font.render("GOOD", True, _GOOD_COLOR).convert_alpha())
    renderer.register_texture(TEX_WORD_MISS, word_font.render("MISS", True, _MISS_COLOR).convert_alpha())
    renderer.register_texture(TEX_LABEL_SCORE, label_font.render("SCORE", True, _LABEL_COLOR).convert_alpha())
    renderer.register_texture(TEX_LABEL_COMBO, label_font.render("COMBO", True, _LABEL_COLOR).convert_alpha())

    crosshair = pygame.Surface((22, 22), pygame.SRCALPHA)
    pygame.draw.circle(crosshair, (255, 255, 255), (11, 11), 10, 2)
    pygame.draw.circle(crosshair, (255, 214, 64), (11, 11), 3)
    renderer.register_texture(TEX_CROSSHAIR, crosshair.convert_alpha())

    pip = pygame.Surface((18, 18), pygame.SRCALPHA)
    pygame.draw.circle(pip, (255, 80, 96), (9, 9), 8)
    pygame.draw.circle(pip, (255, 180, 190), (9, 9), 8, 2)
    renderer.register_texture(TEX_HEALTH_PIP, pip.convert_alpha())
