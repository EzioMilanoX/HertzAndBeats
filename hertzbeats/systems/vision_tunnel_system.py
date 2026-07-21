"""Colapso de Visao: interpola GameState.tunnel_radius (puramente cosmetico) conforme os eventos do beatmap."""
from __future__ import annotations

from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock

from hertzbeats.game_state import GameState
from hertzbeats.modchart import compute_tunnel_radius


class VisionTunnelSystem(ISystem):
    """
    "Colapso de Visao" (Defensor, "vision_tunnel"): escreve
    `GameState.tunnel_radius` TODO frame a partir de
    `compute_tunnel_radius` (funcao pura em `modchart.py`, MESMO idioma
    de encadeamento Lerp de `compute_scroll_flip_fraction`) -- sem
    nenhum evento `vision_tunnel` no beatmap da fase, o raio simplesmente
    permanece em `base_radius` (o campo "totalmente aberto", a diagonal
    centro->canto da janela) para sempre (no-op, mesma filosofia do
    `ReverseScrollSystem` "sempre registrado, inofensivo sem Modchart
    ativo").

    TOLERANCIA ORGANICA: substitui o antigo "Colapso do Anel de
    Julgamento" (`JudgmentRadiusSystem`, removido), que mutava o raio
    FISICO (`GameState.current_judgment_radius`) usado no calculo de
    velocidade das ameacas e na orbita da mira -- encolher aquele raio
    no meio da fase quebrava a velocidade ja calculada de ameacas em
    voo. Este sistema so mexe num raio COSMETICO (o campo de luz
    desenhado pelo `HBPygameRenderer`): nenhuma fisica/velocidade
    depende dele, entao o Colapso pode escalar a dificuldade (esconder o
    spawn das ameacas) sem nunca ser injusto.

    Nao toca NENHUMA pool de entidade -- e um escalar so em
    `GameState`, lido apenas pelo `HertzGameLoop._sync_defender_playfield`
    (publicado ao renderer). Zero-GC trivial: nenhum array, nenhuma
    pool, um float por frame.
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
        self._game_state.tunnel_radius = compute_tunnel_radius(
            now_effective, self._base_radius, self._collapse_events
        )
