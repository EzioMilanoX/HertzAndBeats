"""PygameInputProvider estendido com os eixos de mira 360 derivados do mouse."""
from __future__ import annotations

import math

import pygame

from ouroboros.adapters.pygame_backend.pygame_input_provider import PygameInputProvider


class HBPygameInputProvider(PygameInputProvider):
    """
    `PygameInputProvider` da engine estendido para publicar a mira 360
    como os eixos abstratos `aim_x`/`aim_y` (vetor unitario do nucleo
    para o cursor do mouse, coordenadas de tela). O gameplay consome
    apenas `get_axis("aim_x")`/`get_axis("aim_y")` -- nenhum codigo de
    sistema sabe que existe um mouse (Regra 2 da Constituicao: nada de
    pygame fora dos adapters).
    """

    def __init__(self) -> None:
        super().__init__()
        self._aim_origin_x = 0.0
        self._aim_origin_y = 0.0

    def configure_aim_origin(self, origin_x: float, origin_y: float) -> None:
        """Define o centro da arena a partir do qual a mira e medida.
        Chamado uma vez na composicao."""
        self._aim_origin_x = float(origin_x)
        self._aim_origin_y = float(origin_y)

    def poll(self) -> None:
        super().poll()
        mouse_x, mouse_y = pygame.mouse.get_pos()
        delta_x = float(mouse_x) - self._aim_origin_x
        delta_y = float(mouse_y) - self._aim_origin_y
        length = math.hypot(delta_x, delta_y)
        if length > 1e-6:
            self._axes["aim_x"] = delta_x / length
            self._axes["aim_y"] = delta_y / length
