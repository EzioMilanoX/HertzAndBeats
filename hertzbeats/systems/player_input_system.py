"""O "InputSystem" da composicao: traduz teclado/mouse em mira 360, Dash e i-frames."""
from __future__ import annotations

import math

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.input_provider import IInputProvider

from hertzbeats.game_state import GameState


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
          de mira (raio LIDO de `GameState.current_judgment_radius` TODO
          frame -- Colapso do Anel de Julgamento -- nunca uma constante
          capturada no construtor) e pisca o tint do nucleo durante os
          i-frames.
        - Modo Falange (Undyne, opt-in via "phalanx" em `active_modifiers`):
          `toggle_phalanx` alterna `GameState.phalanx_mode` (SFX de
          equipar + tremor de camera nos 2 sentidos -- entrar E sair) e
          o crosshair convencional some (`tint_a=0`, mesmo mecanismo ja
          usado pelo dimming do jam da arma) enquanto ativo -- o
          `HBPygameRenderer` desenha o arco do escudo no lugar dele (ver
          `JudgmentSystem._run_phalanx_block_check`).

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
        game_state: GameState,
        dash_duration_seconds: float,
        dash_cooldown_seconds: float,
        phalanx_enabled: bool = False,
        toggle_phalanx_action_name: str = "toggle_phalanx",
        audio_engine=None,
        phalanx_equip_sound_id: str = None,
        phalanx_activate_shake_px: float = 0.0,
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
        self._game_state = game_state
        self._dash_duration_seconds = float(dash_duration_seconds)
        self._dash_cooldown_seconds = float(dash_cooldown_seconds)
        self._phalanx_enabled = bool(phalanx_enabled)
        self._toggle_phalanx_action_name = toggle_phalanx_action_name
        self._audio_engine = audio_engine
        self._phalanx_equip_sound_id = phalanx_equip_sound_id
        self._phalanx_activate_shake_px = float(phalanx_activate_shake_px)

    def update(self, world: World, delta_time: float) -> None:
        """Atualiza mira, dash e timers do jogador para este frame."""
        player_row = self._player_pool.dense_row_of(self._player_entity_index)
        player_view = self._player_pool.active_view()

        # A Lamina (Radial Slash): guarda o angulo PRE-este-frame ANTES
        # de recalcula-lo -- `JudgmentSystem` roda logo depois no MESMO
        # frame e usa os 2 pontos (`mouse_angle_previous` aqui,
        # `aim_angle_rad` ja atualizado abaixo) pra medir o arrasto.
        self._game_state.mouse_angle_previous = float(player_view["aim_angle_rad"][player_row])

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

        # arma emperrada (misfire): decrementa aqui, o dono dos timers
        gun_jam = float(player_view["gun_jam_sec"][player_row]) - delta_time
        player_view["gun_jam_sec"][player_row] = gun_jam if gun_jam > 0.0 else 0.0

        # Modo Falange (Undyne, opt-in "phalanx"): alterna nos 2
        # sentidos (entrar E sair tocam o MESMO SFX de equipar + o
        # MESMO tremor -- e' a mesma acao fisica de erguer/baixar o
        # escudo). So' reage a tecla quando o modifier esta ativo nesta
        # fase (`_phalanx_enabled`), mesma filosofia graciosa do resto
        # das Mecanicas Modulares.
        if self._phalanx_enabled and self._input_provider.is_action_pressed(self._toggle_phalanx_action_name):
            self._game_state.phalanx_mode = not self._game_state.phalanx_mode
            self._play(self._phalanx_equip_sound_id, 0.8)
            if self._phalanx_activate_shake_px > 0.0:
                self._game_state.trigger_shake(self._phalanx_activate_shake_px)

        crosshair_row = self._transform_pool.dense_row_of(self._crosshair_entity_index)
        transform_view = self._transform_pool.active_view()
        orbit_radius = self._game_state.current_judgment_radius
        transform_view["position_x"][crosshair_row] = (
            self._center_x + math.cos(aim_angle) * orbit_radius
        )
        transform_view["position_y"][crosshair_row] = (
            self._center_y + math.sin(aim_angle) * orbit_radius
        )
        transform_view["rotation_rad"][crosshair_row] = aim_angle

        # feedback do jam/Falange: a mira apaga enquanto a arma nao
        # responde OU some por completo (o escudo desenhado pelo
        # renderer ocupa o lugar dela) durante o Modo Falange.
        crosshair_sprite_row = self._sprite_pool.dense_row_of(self._crosshair_entity_index)
        sprite_view = self._sprite_pool.active_view()
        if self._game_state.phalanx_mode:
            sprite_view["tint_a"][crosshair_sprite_row] = 0
        else:
            sprite_view["tint_a"][crosshair_sprite_row] = 80 if gun_jam > 0.0 else 255

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

    def _play(self, sound_id, volume: float) -> None:
        """Dispara um SFX se houver backend e som configurados (testes
        headless injetam NullAudioEngine ou nada) -- mesmo helper
        duplicado em `JudgmentSystem`/`CoreDamageSystem`."""
        if self._audio_engine is not None and sound_id is not None:
            self._audio_engine.play_one_shot(sound_id, volume)
