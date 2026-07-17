"""Modo Sobrevivencia: movimento livre WASD + Dash direcional com i-frames NA BATIDA."""
from __future__ import annotations

import math

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock
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
    - Dash com ESQUIVA RITMICA: o dash so FUNCIONA (impulso + i-frames,
      respeitados pelo `SurvivalDamageSystem`) se o aperto cair a ate
      `on_beat_window_seconds` de algum evento musical vivo na tela
      (`target_hit_time_sec` das ameacas -- os onsets que o jogador esta
      OUVINDO). Dash no desespero, fora do tempo, EMPERRA: consome o
      cooldown, toca o clique seco e nada protege -- o contato com a
      parede pune. `on_beat_window <= 0` desliga a exigencia (modo
      classico do tutorial/Defensor).
    - Feedback: tint ciano no nucleo durante os i-frames.

    Zero-GC: leituras de acao escalares, checagem de batida vetorizada
    em buffer pre-alocado, escritas escalares em linhas densas
    re-resolvidas por frame.
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
        audio_clock: IAudioClock = None,
        on_beat_window_seconds: float = 0.0,
        audio_engine=None,
        offbeat_sound_id: str = None,
    ) -> None:
        """Resolve pools uma unica vez; guarda afinacao primitiva."""
        self._input_provider = input_provider
        self._player_pool = memory_manager.get_pool("player_state")
        self._transform_pool = memory_manager.get_pool("transform")
        self._sprite_pool = memory_manager.get_pool("sprite")
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._player_entity_index = int(player_entity_index)
        self._arena_width = float(arena_width)
        self._arena_height = float(arena_height)
        self._move_speed = float(move_speed)
        self._dash_speed = float(dash_speed)
        self._dash_duration_seconds = float(dash_duration_seconds)
        self._dash_cooldown_seconds = float(dash_cooldown_seconds)
        self._arena_margin = float(arena_margin)
        self._audio_clock = audio_clock
        self._on_beat_window_seconds = float(on_beat_window_seconds)
        self._audio_engine = audio_engine
        self._offbeat_sound_id = offbeat_sound_id
        self._delta_buffer = np.zeros(self._threat_pool.capacity, dtype=np.float64)

        # Lidos pelo `ShockwaveSystem` (registrado logo depois): "houve
        # dash ESTE frame, e foi na batida?" -- mesmo idioma de
        # `CollisionSystem.get_collision_pairs()` (um sistema segura
        # referencia a outro e le seu resultado do frame, sem
        # reimplementar a deteccao).
        self.dash_triggered_this_frame: bool = False
        self.dash_was_on_beat_this_frame: bool = False

    def _dash_is_on_beat(self) -> bool:
        """True se o aperto de dash cai na janela de alguma batida viva
        (menor |target - agora_efetivo| entre as ameacas na tela)."""
        if self._on_beat_window_seconds <= 0.0 or self._audio_clock is None:
            return True
        active_count = self._threat_pool.count
        if active_count == 0:
            return False  # silencio: nao ha batida para acertar
        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )
        deltas = self._delta_buffer[:active_count]
        np.subtract(
            self._threat_pool.active_view()["target_hit_time_sec"], now_effective, out=deltas
        )
        np.abs(deltas, out=deltas)
        return bool(deltas.min() <= self._on_beat_window_seconds)

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

        self.dash_triggered_this_frame = False
        self.dash_was_on_beat_this_frame = False

        cooldown = float(player_view["dash_cooldown_sec"][player_row]) - delta_time
        iframes = float(player_view["iframe_timer_sec"][player_row]) - delta_time
        if inp.is_action_pressed("dash") and cooldown <= 0.0:
            cooldown = self._dash_cooldown_seconds
            self.dash_triggered_this_frame = True
            if self._dash_is_on_beat():
                iframes = self._dash_duration_seconds  # esquiva RITMICA: protegido
                self.dash_was_on_beat_this_frame = True
            elif self._audio_engine is not None and self._offbeat_sound_id is not None:
                # dash no desespero: emperra (cooldown gasto, clique, nada sai)
                self._audio_engine.play_one_shot(self._offbeat_sound_id, 0.45)
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
