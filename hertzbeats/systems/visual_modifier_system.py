"""Stutter Scroll (Arcade 4K): gagueira visual em Y -- a fisica real (velocity_y) nunca muda."""
from __future__ import annotations

import math

from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock

from hertzbeats.game_state import GameState


def compute_stutter_offset_y(now_effective: float, frequency_hz: float, amplitude_px: float) -> float:
    """`sin(now_seconds * freq) * amplitude` -- puro e sem estado,
    testavel sem ECS. Um UNICO valor GLOBAL (nao por nota): todas as
    notas do Arcade 4K "gaguejam" em uníssono no momento do
    `draw_batch`, nunca na posicao fisica real."""
    return amplitude_px * math.sin(now_effective * frequency_hz)


class VisualModifierSystem(ISystem):
    """
    Stutter Scroll: escreve `GameState.lane_stutter_offset_y` a cada
    frame com `compute_stutter_offset_y(...)` -- um ruido puramente
    ESTETICO que confunde a leitura visual da queda das notas do
    Arcade 4K sem qualquer risco para o julgamento (o `LaneJudgmentSystem`
    e 100% temporal, nunca le posicao).

    Registrado ANTES do `UIRenderSystem` na ordem de sistemas (como
    pedido): o valor fica pronto no `GameState` antes do
    `HertzGameLoop._render_frame` (overrescrito) le-lo e somar so na
    posicao RENDERIZADA, no momento do `draw_batch` -- `transform.position_y`
    (a fisica real que o `PhysicsSystem` integra) nunca e escrito por
    este sistema, entao nao ha deriva acumulada frame a frame.

    Zero-GC: um escalar por frame, nenhuma alocacao.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        game_state: GameState,
        frequency_hz: float,
        amplitude_px: float,
    ) -> None:
        self._audio_clock = audio_clock
        self._game_state = game_state
        self._frequency_hz = float(frequency_hz)
        self._amplitude_px = float(amplitude_px)

    def update(self, world: World, delta_time: float) -> None:
        del world, delta_time
        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )
        self._game_state.lane_stutter_offset_y = compute_stutter_offset_y(
            now_effective, self._frequency_hz, self._amplitude_px
        )
