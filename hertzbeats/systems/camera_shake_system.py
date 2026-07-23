"""Decai o tremor de tela e a Cegueira Ritmica globais a cada frame -- comum a todos os modos, independente de quem os acionou."""
from __future__ import annotations

from ouroboros.core.memory.memory_manager import MemoryManager
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
    no Defensor, impacto do Parry, ...) e este sistema o reduz
    linearmente ate 0 -- um UNICO escalar primitivo, entao mesmo sem
    vetorizacao numpy isso e Zero-GC por construcao
    (nao ha array por entidade aqui: a "camera" e uma so).

    Registrado INCONDICIONALMENTE em `compose_world` (como o
    `UIRenderSystem`) -- roda em todo modo, mesmo que nenhuma mecanica
    daquele modo dispare shake ainda.

    Tambem decai `GameState.blindness_timer_sec` (Vignette Flash,
    Arcade 4K -- Bombas): um contador de SEGUNDOS RESTANTES, nao uma
    intensidade, entao decresce por `delta_time` puro (nao por uma taxa
    configuravel) ate zero -- o mesmo criterio simples de
    `judgment_display_seconds_left`.

    E tambem decai `GameState.visual_freeze_frames` (Juice de Parry,
    Defensor): um contador de QUADROS de renderizacao, nao de segundos
    -- decresce 1 por `update` (1 `update` = 1 frame real de
    `world.step`), nunca por `delta_time`, entao o congelamento dura o
    mesmo numero de quadros independente do FPS real.

    MODO FALANGE -- PULSO DO NUCLEO (`core_pulse_seconds_left`, opt-in
    via `player_entity_index` fornecido): mesmo criterio de
    `blindness_timer_sec` (segundos restantes, decai por `delta_time`
    puro), mas ALEM de decair tambem ESCREVE a escala interpolada
    direto no `transform` do nucleo (`base_scale * (1 - core_pulse_depth
    * fracao_restante)`) -- ninguem mais reescreve `scale_x/y` do
    nucleo por frame, entao essa escrita persiste sozinha ate o proximo
    pulso. `player_entity_index=None` (Arcade 4K, sem nucleo pulsante)
    e' um no-op completo, mesma filosofia graciosa do resto do jogo."""

    def __init__(
        self,
        game_state: GameState,
        decay_per_second: float,
        memory_manager: MemoryManager = None,
        player_entity_index: int = None,
        core_base_scale: float = 1.0,
        core_pulse_seconds: float = 0.15,
        core_pulse_depth: float = 0.10,
    ) -> None:
        self._game_state = game_state
        self._decay_per_second = float(decay_per_second)
        self._transform_pool = memory_manager.get_pool("transform") if player_entity_index is not None else None
        self._player_entity_index = player_entity_index
        self._core_base_scale = float(core_base_scale)
        self._core_pulse_seconds = float(core_pulse_seconds)
        self._core_pulse_depth = float(core_pulse_depth)

    def update(self, world: World, delta_time: float) -> None:
        del world
        state = self._game_state
        if state.shake_intensity > 0.0:
            state.shake_intensity = max(0.0, state.shake_intensity - self._decay_per_second * delta_time)
        if state.blindness_timer_sec > 0.0:
            state.blindness_timer_sec = max(0.0, state.blindness_timer_sec - delta_time)
        if state.visual_freeze_frames > 0:
            state.visual_freeze_frames -= 1

        if self._player_entity_index is None:
            return
        if state.core_pulse_seconds_left > 0.0:
            state.core_pulse_seconds_left = max(0.0, state.core_pulse_seconds_left - delta_time)
        fraction = (
            state.core_pulse_seconds_left / self._core_pulse_seconds
            if self._core_pulse_seconds > 0.0 else 0.0
        )
        scale = self._core_base_scale * (1.0 - self._core_pulse_depth * fraction)
        row = self._transform_pool.dense_row_of(self._player_entity_index)
        view = self._transform_pool.active_view()
        view["scale_x"][row] = scale
        view["scale_y"][row] = scale
