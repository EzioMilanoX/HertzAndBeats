"""Colapso do Anel de Julgamento: interpola GameState.current_judgment_radius conforme os eventos do beatmap."""
from __future__ import annotations

from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock

from hertzbeats.game_state import GameState
from hertzbeats.modchart import compute_collapsed_radius


class JudgmentRadiusSystem(ISystem):
    """
    "Colapso do Anel de Julgamento" (Defensor): escreve
    `GameState.current_judgment_radius` TODO frame a partir de
    `compute_collapsed_radius` (funcao pura em `modchart.py`, MESMO
    idioma de encadeamento Lerp de `compute_scroll_flip_fraction`) --
    sem nenhum evento `radius_collapse` no beatmap da fase, o raio
    simplesmente permanece em `base_radius` para sempre (no-op, mesma
    filosofia do `ReverseScrollSystem` "sempre registrado, inofensivo
    sem Modchart ativo").

    Nao toca NENHUMA pool de entidade -- e um escalar so em
    `GameState`, lido por `RadialRhythmSpawnerSystem` (velocidade de
    ameacas novas), `PlayerInputSystem` (orbita da mira) e
    `HertzGameLoop._sync_defender_playfield` (o anel desenhado). Zero-GC
    trivial: nenhum array, nenhuma pool, um float por frame.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        game_state: GameState,
        base_radius: float,
        collapse_events: tuple,
    ) -> None:
        self._audio_clock = audio_clock
        self._game_state = game_state
        self._base_radius = float(base_radius)
        self._collapse_events = tuple(collapse_events)

    def update(self, world: World, delta_time: float) -> None:
        del world, delta_time
        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )
        self._game_state.current_judgment_radius = compute_collapsed_radius(
            now_effective, self._base_radius, self._collapse_events
        )
