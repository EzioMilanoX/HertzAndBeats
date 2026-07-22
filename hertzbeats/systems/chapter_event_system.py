"""Eventos de Gameplay via Capitulos do YouTube: dispara "Deformacao de Arena" (tremor) ao cruzar cada evento arena_warp agendado."""
from __future__ import annotations

from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock

from hertzbeats.game_state import GameState


class ChapterEventSystem(ISystem):
    """
    Dispara `GameState.trigger_shake` UMA VEZ por evento "arena_warp"
    agendado (`modchart.parse_arena_warp_events`, derivado dos
    capitulos do YouTube com palavra-chave de intensidade -- ver
    `modchart.chapters_to_modchart_events`) -- MESMO cursor monotonico
    do `TutorialSystem`/esqueleto de Karaoke (array crescente de
    `time_seconds` comparado ao `IAudioClock` compensado de latencia,
    avancando UM indice por vez, nunca reavaliado do zero, nunca
    disparado duas vezes pro mesmo evento).

    So registrado na composicao quando ha PELO MENOS um evento
    "arena_warp" (ver `rhythm_composition_root.compose_world`) -- sem
    capitulos com palavra-chave, nenhum sistema extra entra, zero custo
    por frame (mesma filosofia "so paga quem usa" de toda Mecanica
    Modular). "Deformacao de Arena" e' deliberadamente um tremor de tela
    (mecanismo JA existente e testado) em vez de ligar Eclipses/Rastros
    a meio da fase -- isso exigiria tornar `active_modifiers` dinamico
    em tempo real, um escopo maior deixado de fora aqui de proposito
    (ver o Modchart "reverse_scroll" sintetico, ja acionado a parte para
    o Arcade 4K em `chapters_to_modchart_events`, pela coreografia
    global JA existente).
    """

    def __init__(self, audio_clock: IAudioClock, game_state: GameState, warp_events: tuple) -> None:
        self._audio_clock = audio_clock
        self._game_state = game_state
        self._warp_events = tuple(warp_events)
        self._next_index = 0

    def update(self, world: World, delta_time: float) -> None:
        del world, delta_time
        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )
        count = len(self._warp_events)
        while self._next_index < count and now_effective >= self._warp_events[self._next_index][0]:
            _time_seconds, shake_px = self._warp_events[self._next_index]
            self._game_state.trigger_shake(shake_px)
            self._next_index += 1
