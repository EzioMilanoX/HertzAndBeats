"""Modo Sobrevivencia: movimento livre WASD + Dash direcional com i-frames (estilo Just Shapes & Beats)."""
from __future__ import annotations

import math

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.input_provider import IInputProvider

_DIAGONAL_NORMALIZER = 1.0 / math.sqrt(2.0)


class SurvivalPlayerSystem(ISystem):
    """
    O "InputSystem" do modo Sobrevivencia: em vez de mira 360 fixa no
    centro, o jogador MOVE o nucleo livremente pela arena (WASD) e usa o
    Dash como unico verbo ritmico -- nao ha botao de ataque; atravessar
    as paredes de som no tempo certo E o gameplay.

    - Movimento: eixos derivados das acoes seguradas (`move_*`),
      diagonal normalizada, posicao integrada com `delta_time` de frame
      (game feel, nao evento ritmico) e CLAMPED a arena.
    - Dash: na borda de `dash` fora de cooldown, arma i-frames
      (`iframe_timer_sec`, respeitados pelo `SurvivalDamageSystem`) e um
      impulso de velocidade na direcao atual de movimento
      (`survival_dash_speed` durante os i-frames). A direcao fica
      gravada em `player_state.aim_angle_rad` (reinterpretada pelo modo
      como "direcao de deslocamento").
    - Feedback: tint ciano no nucleo durante os i-frames.

    Zero-GC: leituras de acao escalares + escritas escalares em linhas
    densas re-resolvidas por frame.
    """

    def __init__(
        self,
        input_provider: IInputProvider,
        memory_manager: MemoryManager,
        player_entity_index: int,
        arena_width: float,
        arena_height: float,
        move_speed: float,
        dash_speed: float,
        dash_duration_seconds: float,
        dash_cooldown_seconds: float,
        arena_margin: float = 24.0,
    ) -> None:
        """Resolve pools uma unica vez; guarda afinacao primitiva."""
        self._input_provider = input_provider
        self._player_pool = memory_manager.get_pool("player_state")
        self._transform_pool = memory_manager.get_pool("transform")
        self._sprite_pool = memory_manager.get_pool("sprite")
        self._player_entity_index = int(player_entity_index)
        self._arena_width = float(arena_width)
        self._arena_height = float(arena_height)
        self._move_speed = float(move_speed)
        self._dash_speed = float(dash_speed)
        self._dash_duration_seconds = float(dash_duration_seconds)
        self._dash_cooldown_seconds = float(dash_cooldown_seconds)
        self._arena_margin = float(arena_margin)

    def update(self, world: World, delta_time: float) -> None:
        """Integra movimento/dash do frame e escreve o estado do jogador."""
        inp = self._input_provider
        player_row = self._player_pool.dense_row_of(self._player_entity_index)
        player_view = self._player_pool.active_view()

        move_x = (1.0 if inp.is_action_held("move_right") else 0.0) - (
            1.0 if inp.is_action_held("move_left") else 0.0
        )
        move_y = (1.0 if inp.is_action_held("move_down") else 0.0) - (
            1.0 if inp.is_action_held("move_up") else 0.0
        )
        if move_x != 0.0 and move_y != 0.0:
            move_x *= _DIAGONAL_NORMALIZER
            move_y *= _DIAGONAL_NORMALIZER
        if move_x != 0.0 or move_y != 0.0:
            player_view["aim_angle_rad"][player_row] = math.atan2(move_y, move_x)

        cooldown = float(player_view["dash_cooldown_sec"][player_row]) - delta_time
        iframes = float(player_view["iframe_timer_sec"][player_row]) - delta_time
        if inp.is_action_pressed("dash") and cooldown <= 0.0:
            iframes = self._dash_duration_seconds
            cooldown = self._dash_cooldown_seconds
        player_view["dash_cooldown_sec"][player_row] = cooldown if cooldown > 0.0 else 0.0
        player_view["iframe_timer_sec"][player_row] = iframes if iframes > 0.0 else 0.0

        # durante o dash o deslocamento segue a direcao gravada, com o
        # impulso de dash; fora dele, o input do frame com velocidade base
        if iframes > 0.0:
            dash_angle = float(player_view["aim_angle_rad"][player_row])
            step = self._dash_speed * delta_time
            step_x = math.cos(dash_angle) * step
            step_y = math.sin(dash_angle) * step
        else:
            step_x = move_x * self._move_speed * delta_time
            step_y = move_y * self._move_speed * delta_time

        transform_row = self._transform_pool.dense_row_of(self._player_entity_index)
        transform_view = self._transform_pool.active_view()
        new_x = float(transform_view["position_x"][transform_row]) + step_x
        new_y = float(transform_view["position_y"][transform_row]) + step_y
        margin = self._arena_margin
        if new_x < margin:
            new_x = margin
        elif new_x > self._arena_width - margin:
            new_x = self._arena_width - margin
        if new_y < margin:
            new_y = margin
        elif new_y > self._arena_height - margin:
            new_y = self._arena_height - margin
        transform_view["position_x"][transform_row] = new_x
        transform_view["position_y"][transform_row] = new_y

        sprite_row = self._sprite_pool.dense_row_of(self._player_entity_index)
        sprite_view = self._sprite_pool.active_view()
        if iframes > 0.0:
            sprite_view["tint_r"][sprite_row] = 80
            sprite_view["tint_g"][sprite_row] = 255
            sprite_view["tint_b"][sprite_row] = 255
        else:
            sprite_view["tint_r"][sprite_row] = 240
            sprite_view["tint_g"][sprite_row] = 240
            sprite_view["tint_b"][sprite_row] = 255
