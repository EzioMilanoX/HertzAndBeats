"""PygameInputProvider estendido: mira 360 via mouse e bindings MULTI-TECLA por acao."""
from __future__ import annotations

import json
import math

import pygame

from ouroboros.adapters.pygame_backend.pygame_input_provider import PygameInputProvider


class HBPygameInputProvider(PygameInputProvider):
    """
    `PygameInputProvider` da engine estendido para o Hertz & Beats com:

    - Eixos de mira 360 (`aim_x`/`aim_y`): vetor unitario do nucleo para
      o cursor do mouse. O gameplay consome apenas `get_axis(...)` --
      nenhum sistema sabe que existe um mouse (Regra 2 da Constituicao).
    - Bindings MULTI-TECLA: no JSON, o valor de uma acao pode ser uma
      LISTA de codigos (`"menu_up": ["KEY_UP", "KEY_W"]`) -- a acao fica
      ativa se QUALQUER tecla estiver pressionada. Praticidade de input
      (setas OU WASD no menu, ENTER OU ESPACO para confirmar) sem tocar
      o contrato da engine, que segue um-codigo-por-acao.
    """

    def __init__(self) -> None:
        super().__init__()
        self._aim_origin_x = 0.0
        self._aim_origin_y = 0.0
        self._multi_bindings = {}

    def configure_aim_origin(self, origin_x: float, origin_y: float) -> None:
        """Define o centro da arena a partir do qual a mira e medida.
        Chamado uma vez na composicao."""
        self._aim_origin_x = float(origin_x)
        self._aim_origin_y = float(origin_y)

    def load_bindings(self, bindings_path: str) -> None:
        """Carrega bindings aceitando string OU lista de strings por
        acao; cada codigo e resolvido pelo mesmo `_resolve_binding` da
        engine."""
        with open(bindings_path, "r", encoding="utf-8") as f:
            raw_bindings = json.load(f)
        self._multi_bindings = {}
        for action_name, codes in raw_bindings.items():
            if isinstance(codes, str):
                codes = [codes]
            self._multi_bindings[action_name] = tuple(
                self._resolve_binding(code) for code in codes
            )

    def poll(self) -> None:
        """Consome eventos nativos e atualiza o estado interno com OR
        sobre todas as teclas de cada acao, mais os eixos de mira."""
        self._previous_held = dict(self._current_held)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._wants_quit = True

        keys = pygame.key.get_pressed()
        mouse_buttons = pygame.mouse.get_pressed()
        current = {}
        for action_name, bindings in self._multi_bindings.items():
            held = False
            for kind, code in bindings:
                if kind == "key":
                    if keys[code]:
                        held = True
                        break
                elif code < len(mouse_buttons) and mouse_buttons[code]:
                    held = True
                    break
            current[action_name] = held
        self._current_held = current

        mouse_x, mouse_y = pygame.mouse.get_pos()
        delta_x = float(mouse_x) - self._aim_origin_x
        delta_y = float(mouse_y) - self._aim_origin_y
        length = math.hypot(delta_x, delta_y)
        if length > 1e-6:
            self._axes["aim_x"] = delta_x / length
            self._axes["aim_y"] = delta_y / length
