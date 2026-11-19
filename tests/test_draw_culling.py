"""Guarda de coordenada em `draw_batch`: um sprite ruim nunca derruba o jogo.

Bug real reproduzido no Arcade 4K (`python -m hertzbeats --stage 7` com
relogio de audio degenerado): a coordenada y de uma nota chegou a 1.2e10,
o SDL rejeitou o valor ("center argument must be a pair of numbers", o
int de 32 bits estourado) e a excecao subiu pelo loop de render, matando
a partida inteira por causa de UM sprite.

O piso de tempo restante dos dois spawners (`min_travel_seconds`) ja
existia e nao era o culpado -- a origem e uma posicao invalida chegando
ao renderer, e a defesa certa e' na fronteira de desenho: sprite fora da
tela nao precisa ser desenhado de qualquer jeito.
"""
import numpy as np
import pygame
import pytest

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.components.texture_ids import TEX_THREAT_BASIC

WIDTH, HEIGHT = 320, 240


@pytest.fixture
def renderer():
    renderer = HBPygameRenderer()
    renderer.initialize(WIDTH, HEIGHT, "test")
    yield renderer
    renderer.shutdown()


def _batch(*positions):
    """Um lote de N sprites-forma (sem textura registrada => caminho de
    `pygame.draw`, o mesmo do bug), todos opacos e visiveis."""
    count = len(positions)
    return {
        "positions_xy": np.array(positions, dtype=np.float64),
        "rotations_rad": np.zeros(count, dtype=np.float64),
        "scales_xy": np.ones((count, 2), dtype=np.float64),
        "texture_ids": np.full(count, TEX_THREAT_BASIC, dtype=np.int32),
        "tint_rgba": np.full((count, 4), 255, dtype=np.int32),
        "layer_z": np.zeros(count, dtype=np.float64),
        "count": count,
    }


def _painted_pixels(renderer) -> int:
    surface = pygame.display.get_surface()
    pixels = pygame.surfarray.array3d(surface)
    return int(np.count_nonzero(pixels.sum(axis=2)))


@pytest.mark.parametrize(
    "bad_position",
    [
        pytest.param((160.0, 1.2e10), id="y_estoura_int32"),
        pytest.param((-1.95e11, 120.0), id="x_negativo_gigante"),
        pytest.param((float("nan"), 120.0), id="x_nan"),
        pytest.param((160.0, float("nan")), id="y_nan"),
        pytest.param((float("inf"), 120.0), id="x_infinito"),
    ],
)
def test_absurd_coordinates_are_skipped_instead_of_crashing(renderer, bad_position):
    renderer.begin_frame()
    renderer.draw_batch(**_batch(bad_position))
    renderer.end_frame()


def test_one_bad_sprite_does_not_stop_the_good_ones(renderer):
    """O que de fato importava no bug: a excecao abortava o lote INTEIRO,
    entao um sprite invalido apagava a tela toda. O sprite bom tem de ser
    desenhado mesmo com um vizinho invalido na mesma leva."""
    renderer.begin_frame()
    renderer.draw_batch(**_batch((160.0, 120.0)))
    renderer.end_frame()
    only_good = _painted_pixels(renderer)
    assert only_good > 0, "o sprite valido precisa pintar algo"

    renderer.begin_frame()
    renderer.draw_batch(**_batch((160.0, 1.2e10), (160.0, 120.0)))
    renderer.end_frame()
    assert _painted_pixels(renderer) == only_good


def test_sprites_just_off_screen_are_still_drawn(renderer):
    """A margem e' enorme de proposito: um sprite grande cujo CENTRO saiu
    da tela mas que ainda a toca precisa continuar sendo desenhado -- o
    culling nao pode virar um bug visual."""
    renderer.begin_frame()
    renderer.draw_batch(**_batch((-20.0, 120.0)))
    renderer.end_frame()
    assert _painted_pixels(renderer) > 0
