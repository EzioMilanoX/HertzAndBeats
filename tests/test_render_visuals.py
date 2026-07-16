"""Regressao VISUAL do renderer (pygame headless): textos blitam como glifos, nunca blocos solidos.

Contexto: `Surface.set_alpha(None)` DESLIGA o alpha por pixel no pygame;
uma textura de fonte blitada assim vira um retangulo cheio da cor do
texto (bug visto em producao: 'MISS' como bloco vermelho, 'SCORE' como
barra lilas). Estes testes desenham pelo caminho REAL do `draw_batch` e
medem a fracao de pixels pintados dentro do bounding box da textura --
um glifo tem buracos; um bloco solido nao.
"""
import numpy as np
import pygame
import pytest

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.adapters.texture_bank import build_and_register_hud_textures
from hertzbeats.components.texture_ids import TEX_DIGIT_BASE, TEX_WORD_MISS


@pytest.fixture
def renderer():
    renderer = HBPygameRenderer()
    renderer.initialize(320, 240, "test")
    build_and_register_hud_textures(renderer)
    yield renderer
    renderer.shutdown()


def _draw_texture(renderer, texture_id: int, alpha: int) -> float:
    """Desenha `texture_id` centrado via draw_batch e retorna a fracao de
    pixels NAO-fundo dentro do bounding box da textura."""
    positions = np.array([[160.0, 120.0]], dtype=np.float32)
    rotations = np.zeros(1, dtype=np.float32)
    scales = np.ones((1, 2), dtype=np.float32)
    texture_ids = np.array([texture_id], dtype=np.uint32)
    tints = np.array([[255, 255, 255, alpha]], dtype=np.uint8)
    layers = np.zeros(1, dtype=np.int16)

    renderer.begin_frame()
    renderer.draw_batch(positions, rotations, scales, texture_ids, tints, layers, 1)

    texture = renderer._textures[texture_id]
    width, height = texture.get_width(), texture.get_height()
    pixels = pygame.surfarray.array3d(renderer._surface)
    box = pixels[160 - width // 2 : 160 + width // 2, 120 - height // 2 : 120 + height // 2]
    background = np.array([8, 6, 20])
    painted = np.any(box != background, axis=2)
    return float(painted.mean())


def test_word_texture_has_glyph_holes(renderer):
    painted_ratio = _draw_texture(renderer, TEX_WORD_MISS, alpha=255)
    assert 0.05 < painted_ratio < 0.85, (
        f"'MISS' pintou {painted_ratio:.0%} do bounding box -- ~100% significa "
        "bloco solido (alpha por pixel perdido), ~0% significa nada desenhado"
    )


def test_word_texture_survives_alpha_roundtrip(renderer):
    """O caminho alpha<255 (set_alpha numerico) nao pode degradar o blit
    opaco seguinte -- era exatamente o roundtrip que quebrava com
    set_alpha(None)."""
    _draw_texture(renderer, TEX_WORD_MISS, alpha=120)
    painted_ratio = _draw_texture(renderer, TEX_WORD_MISS, alpha=255)
    assert 0.05 < painted_ratio < 0.85


def test_digit_texture_has_glyph_holes(renderer):
    painted_ratio = _draw_texture(renderer, TEX_DIGIT_BASE + 0, alpha=255)
    assert 0.05 < painted_ratio < 0.9  # o '0' tem um buraco no meio


def test_hidden_sprite_paints_nothing(renderer):
    painted_ratio = _draw_texture(renderer, TEX_WORD_MISS, alpha=0)
    assert painted_ratio == 0.0
