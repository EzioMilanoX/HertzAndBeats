"""O "InputSystem" da composicao: traduz teclado/mouse em mira 360, Dash e i-frames."""
from __future__ import annotations

import math

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.input_provider import IInputProvider


class PlayerInputSystem(ISystem):
    """
    Primeiro sistema do frame (o "InputSystem" da ordem de composicao):
    le o `IInputProvider` (ja `poll()`ado pelo GameLoop) e escreve o
    estado do jogador nas pools SoA -- nenhum outro sistema toca o
    backend de input para decidir gameplay de mira/dash.

    Responsabilidades:
        - Mira 360: converte os eixos `aim_x`/`aim_y` (vetor unitario
          mouse->nucleo publicado pelo adapter) em `aim_angle_rad` via
          `math.atan2` escalar (uma unica entidade: o jogador).
        - Dash: na borda de pressao de `dash`, se fora de cooldown,
          arma `iframe_timer_sec` (janela de invencibilidade que o
          `CoreDamageSystem` respeita) e o cooldown.
        - Timers: decrementados com `delta_time` de frame -- correto
          aqui, pois i-frames/cooldown sao "game feel", nao eventos
          sincronizados a batida (estes consultam `IAudioClock`).
        - Feedback visual: reposiciona a entidade do crosshair no anel
          de mira e pisca o tint do nucleo durante os i-frames.

    Zero-GC: apenas leituras/escritas escalares em linhas densas
    re-resolvidas por frame (`dense_row_of`, nunca cacheadas -- um
    swap-remove alheio pode move-las entre frames).
    """

    def __init__(
        self,
        input_provider: IInputProvider,
        memory_manager: MemoryManager,
        player_entity_index: int,
        crosshair_entity_index: int,
        center_xy: tuple,
        crosshair_orbit_radius: float,
        dash_duration_seconds: float,
        dash_cooldown_seconds: float,
    ) -> None:
        """Resolve pools uma unica vez; guarda indices/afinacao primitivos."""
        self._input_provider = input_provider
        self._player_pool = memory_manager.get_pool("player_state")
        self._transform_pool = memory_manager.get_pool("transform")
        self._sprite_pool = memory_manager.get_pool("sprite")
        self._player_entity_index = int(player_entity_index)
        self._crosshair_entity_index = int(crosshair_entity_index)
        self._center_x = float(center_xy[0])
        self._center_y = float(center_xy[1])
        self._crosshair_orbit_radius = float(crosshair_orbit_radius)
        self._dash_duration_seconds = float(dash_duration_seconds)
        self._dash_cooldown_seconds = float(dash_cooldown_seconds)

    def update(self, world: World, delta_time: float) -> None:
        """Atualiza mira, dash e timers do jogador para este frame."""
        player_row = self._player_pool.dense_row_of(self._player_entity_index)
        player_view = self._player_pool.active_view()

        aim_x = self._input_provider.get_axis("aim_x")
        aim_y = self._input_provider.get_axis("aim_y")
        if (aim_x * aim_x + aim_y * aim_y) > 1e-8:
            player_view["aim_angle_rad"][player_row] = math.atan2(aim_y, aim_x)
        aim_angle = float(player_view["aim_angle_rad"][player_row])

        cooldown = float(player_view["dash_cooldown_sec"][player_row]) - delta_time
        iframes = float(player_view["iframe_timer_sec"][player_row]) - delta_time
        if self._input_provider.is_action_pressed("dash") and cooldown <= 0.0:
            iframes = self._dash_duration_seconds
            cooldown = self._dash_cooldown_seconds
        player_view["dash_cooldown_sec"][player_row] = cooldown if cooldown > 0.0 else 0.0
        player_view["iframe_timer_sec"][player_row] = iframes if iframes > 0.0 else 0.0

        crosshair_row = self._transform_pool.dense_row_of(self._crosshair_entity_index)
        transform_view = self._transform_pool.active_view()
        transform_view["position_x"][crosshair_row] = (
            self._center_x + math.cos(aim_angle) * self._crosshair_orbit_radius
        )
        transform_view["position_y"][crosshair_row] = (
            self._center_y + math.sin(aim_angle) * self._crosshair_orbit_radius
        )
        transform_view["rotation_rad"][crosshair_row] = aim_angle

        player_sprite_row = self._sprite_pool.dense_row_of(self._player_entity_index)
        sprite_view = self._sprite_pool.active_view()
        if iframes > 0.0:
            sprite_view["tint_r"][player_sprite_row] = 80
            sprite_view["tint_g"][player_sprite_row] = 255
            sprite_view["tint_b"][player_sprite_row] = 255
        else:
            sprite_view["tint_r"][player_sprite_row] = 240
            sprite_view["tint_g"][player_sprite_row] = 240
            sprite_view["tint_b"][player_sprite_row] = 255
