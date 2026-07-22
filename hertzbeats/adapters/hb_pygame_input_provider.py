"""PygameInputProvider estendido: mira 360 via mouse e bindings MULTI-TECLA por acao."""
from __future__ import annotations

import json
import math

import pygame

from ouroboros.adapters.pygame_backend.pygame_input_provider import PygameInputProvider

_SCRATCH_ENERGY_DIVISOR = 40.0
"""Pixels de movimento de mouse por frame que já saturam o eixo
`scratch_energy` em 1.0 -- referencia empirica para "raspar" a mesa do
DJ sem exigir um sensor fisico calibrado."""

_WHEEL_ENERGY_PER_NOTCH = 0.55
"""Quanto UM clique da roda do mouse (`event.y = +-1`) contribui para
`scratch_energy` -- 2 cliques seguidos ja saturam em 1.0."""

_WHEEL_ENERGY_DECAY_PER_POLL = 0.35
"""Decaimento do "impulso" da roda por `poll()` (nao por segundo -- a
roda e um evento discreto, nao continuo como o mouse/teclas, entao o
decaimento e medido em CHAMADAS de poll, nao em tempo real)."""

_ALT_KEY_ENERGY = 1.0
"""Energia injetada a cada alternancia valida entre `scratch_left`/
`scratch_right` -- satura o eixo de uma vez (o "gatilho alternado" do
enunciado, estilo LT/RT de controle)."""

_ALT_KEY_ENERGY_DECAY_PER_POLL = 0.25
"""Decaimento por `poll()` da energia de alternancia -- generoso o
bastante para que uma cadencia de tecla humana (varias alternancias por
segundo) mantenha o eixo saturado sem exigir velocidade de mouse."""


def apply_energy_pulse(current: float, gained: float, decay: float) -> float:
    """Soma um ganho instantaneo (roda do mouse), limita a 1.0 e decai --
    PURA (sem pygame), usada por `poll()` e testada isoladamente."""
    return max(0.0, min(1.0, current + gained) - decay)


def advance_alternating_energy(
    current_energy: float,
    last_side,
    left_pressed: bool,
    right_pressed: bool,
    energy_on_switch: float,
    decay: float,
):
    """Notas de Scratch por alternancia (teclado ou LT/RT de um
    controle): uma troca de LADO (nao repetir o mesmo) injeta
    `energy_on_switch`; qualquer chamada decai o valor atual. PURA (sem
    pygame) -- retorna `(nova_energia, novo_last_side)`."""
    if (left_pressed and last_side == "right") or (right_pressed and last_side == "left"):
        current_energy = energy_on_switch
    if left_pressed:
        last_side = "left"
    elif right_pressed:
        last_side = "right"
    return max(0.0, current_energy - decay), last_side


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
    - Eixo `scratch_energy` (Notas de Scratch do Arcade 4K): o MAIOR
      entre 3 fontes independentes, cada uma normalizada 0.0..1.0 --
      movimentos longos e continuos de mouse esbarram no limite fisico
      do mousepad, entao nenhuma delas e obrigatoria:
        1. Magnitude do movimento RELATIVO do mouse no frame
           (`pygame.mouse.get_rel()` / `_SCRATCH_ENERGY_DIVISOR`).
        2. Impulso da RODA do mouse (`pygame.MOUSEWHEEL`), que decai por
           `poll()` (evento discreto, nao continuo).
        3. Alternancia entre as acoes `scratch_left`/`scratch_right`
           (teclado, ou gatilhos LT/RT de um controle nos bindings) --
           cada troca de lado injeta energia maxima, tambem com decaimento
           por `poll()`.
      `ScratchJudgmentSystem` so ve o eixo final combinado -- nunca sabe
      qual das 3 fontes o alimentou.
    """

    def __init__(self) -> None:
        super().__init__()
        self._aim_origin_x = 0.0
        self._aim_origin_y = 0.0
        self._multi_bindings = {}
        self._wheel_energy = 0.0
        self._alt_key_energy = 0.0
        self._last_scratch_side = None

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
        wheel_notches = 0.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._wants_quit = True
            elif event.type == pygame.MOUSEWHEEL:
                wheel_notches += abs(event.y)

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

        # Pipeline de Importacao Direta (Ctrl+V): um CASO UNICO de
        # combinacao de teclas -- fora do esquema geral de
        # `data/input_bindings/*.json` (um codigo por acao, OR entre
        # varios) de proposito, ja que nenhuma OUTRA acao do jogo
        # precisa de uma combinacao (nunca vale a pena generalizar um
        # mecanismo de "chord" pra um unico caso de uso).
        current["paste"] = bool(keys[pygame.K_v]) and (bool(keys[pygame.K_LCTRL]) or bool(keys[pygame.K_RCTRL]))

        self._current_held = current

        mouse_x, mouse_y = pygame.mouse.get_pos()
        delta_x = float(mouse_x) - self._aim_origin_x
        delta_y = float(mouse_y) - self._aim_origin_y
        length = math.hypot(delta_x, delta_y)
        if length > 1e-6:
            self._axes["aim_x"] = delta_x / length
            self._axes["aim_y"] = delta_y / length

        rel_x, rel_y = pygame.mouse.get_rel()
        mouse_energy = min(1.0, math.hypot(rel_x, rel_y) / _SCRATCH_ENERGY_DIVISOR)

        self._wheel_energy = apply_energy_pulse(
            self._wheel_energy, wheel_notches * _WHEEL_ENERGY_PER_NOTCH, _WHEEL_ENERGY_DECAY_PER_POLL
        )

        # Alternancia scratch_left/scratch_right: cada troca de LADO (nao
        # repeticao do mesmo) injeta energia maxima -- mesmo idioma de um
        # LT/RT alternado de controle.
        self._alt_key_energy, self._last_scratch_side = advance_alternating_energy(
            self._alt_key_energy,
            self._last_scratch_side,
            left_pressed=self.is_action_pressed("scratch_left"),
            right_pressed=self.is_action_pressed("scratch_right"),
            energy_on_switch=_ALT_KEY_ENERGY,
            decay=_ALT_KEY_ENERGY_DECAY_PER_POLL,
        )

        self._axes["scratch_energy"] = max(mouse_energy, self._wheel_energy, self._alt_key_energy)
