"""Decai o tremor de tela e a Cegueira Ritmica globais a cada frame -- comum a todos os modos, independente de quem os acionou."""
from __future__ import annotations

from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World

from hertzbeats.game_state import GameState


class CameraShakeSystem(ISystem):
    """
    Metade "gameplay" do Screen Shake: a metade "apresentacao" vive no
    `HertzGameLoop` (le `game_state.shake_intensity` a cada frame e
    chama `IRenderer.set_camera_offset(dx, dy)` -- metodo JA EXISTENTE
    na engine, ROADMAP M1/M2, com default no-op e implementacao real em
    `PygameRenderer`; nao inventamos um mecanismo novo de deslocamento).

    Este sistema so cuida do DECAIMENTO: `GameState.shake_intensity` e
    escrito por `trigger_shake(...)` de QUALQUER sistema (Hold quebrado
    no Defensor, onda fora da Safe Zone na Sobrevivencia, ...) e este
    sistema o reduz linearmente ate 0 -- um UNICO escalar primitivo,
    entao mesmo sem vetorizacao numpy isso e Zero-GC por construcao
    (nao ha array por entidade aqui: a "camera" e uma so).

    Registrado INCONDICIONALMENTE em `compose_world` (como o
    `UIRenderSystem`) -- roda em todo modo, mesmo que nenhuma mecanica
    daquele modo dispare shake ainda.

    Tambem decai `GameState.blindness_timer_sec` (Vignette Flash,
    Arcade 4K -- Bombas): um contador de SEGUNDOS RESTANTES, nao uma
    intensidade, entao decresce por `delta_time` puro (nao por uma taxa
    configuravel) ate zero -- o mesmo criterio simples de
    `judgment_display_seconds_left`."""

    def __init__(self, game_state: GameState, decay_per_second: float) -> None:
        self._game_state = game_state
        self._decay_per_second = float(decay_per_second)

    def update(self, world: World, delta_time: float) -> None:
        del world
        state = self._game_state
        if state.shake_intensity > 0.0:
            state.shake_intensity = max(0.0, state.shake_intensity - self._decay_per_second * delta_time)
        if state.blindness_timer_sec > 0.0:
            state.blindness_timer_sec = max(0.0, state.blindness_timer_sec - delta_time)
