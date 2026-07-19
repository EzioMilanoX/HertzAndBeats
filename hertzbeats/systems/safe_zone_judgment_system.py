"""Modo Sobrevivencia: Safe Zone estacionaria -- julga por distancia direta, exige Ancora continua."""
from __future__ import annotations

import math

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock
from ouroboros.interfaces.input_provider import IInputProvider

from hertzbeats.components.schemas import (
    JUDGMENT_MISS,
    JUDGMENT_PENDING,
    JUDGMENT_SURVIVED,
    MODE_TAG_SURVIVAL,
    PHASE_LETHAL,
)
from hertzbeats.game_state import GameState


class SafeZoneJudgmentSystem(ISystem):
    """
    Safe Zone (opt-in via `holds_enabled`): zonas circulares ESTACIONARIAS
    (`SurvivalSpawnerSystem`, `duration_sec > 0`) cuja hitbox NUNCA e
    armada (`WallPhaseSystem` as poupa por construcao) -- este sistema e
    o UNICO juiz delas, julgando por DISTANCIA DIRETA (mesmo idioma do
    `GrazeSystem`: le transform+hitbox das pools diretamente, sem
    depender de pares do `CollisionSystem`).

    Regra: a partir do onset (`phase == PHASE_LETHAL` -- o mesmo instante
    em que a zona "solidifica" visualmente), o jogador precisa ficar
    dentro de `safe_zone_radius` da zona E segurar a acao `anchor`
    continuamente ate `target_hit_time_sec + duration_sec`:
        - Sustentou ate o fim        -> SURVIVED: pontua, estende combo.
        - Saiu do raio OU soltou
          Ancora antes do fim        -> MISS imediato: dano de vida
          (respeita `practice_mode`), Camera Shake e Haptics
          (`IInputProvider.set_rumble`).

    Zero-GC: filtro vetorizado (linhas ativas, tipicamente 0-2 por vez)
    seguido de um laco escalar computando a distancia via `math.hypot`
    -- mesmo padrao do `GrazeSystem`/Hold do Defensor.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        input_provider: IInputProvider,
        memory_manager: MemoryManager,
        game_state: GameState,
        player_entity_index: int,
        anchor_action_name: str,
        score_per_success: int,
        judgment_display_seconds: float,
        safe_zone_break_shake_px: float,
        rumble_low_freq: float,
        rumble_high_freq: float,
        rumble_duration_seconds: float,
        practice_mode: bool = False,
        audio_engine=None,
        success_sound_id: str = None,
        break_sound_id: str = None,
    ) -> None:
        self._audio_clock = audio_clock
        self._input_provider = input_provider
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._transform_pool = memory_manager.get_pool("transform")
        self._hitbox_pool = memory_manager.get_pool("hitbox")
        self._game_state = game_state
        self._player_entity_index = int(player_entity_index)
        self._anchor_action_name = anchor_action_name
        self._score_per_success = int(score_per_success)
        self._judgment_display_seconds = float(judgment_display_seconds)
        self._safe_zone_break_shake_px = float(safe_zone_break_shake_px)
        self._rumble_low_freq = float(rumble_low_freq)
        self._rumble_high_freq = float(rumble_high_freq)
        self._rumble_duration_seconds = float(rumble_duration_seconds)
        self._practice_mode = bool(practice_mode)
        self._audio_engine = audio_engine
        self._success_sound_id = success_sound_id
        self._break_sound_id = break_sound_id

        capacity = self._threat_pool.capacity
        self._active_mask = np.zeros(capacity, dtype=bool)
        self._scratch_mask = np.zeros(capacity, dtype=bool)

    def update(self, world: World, delta_time: float) -> None:
        """Filtra as Safe Zones ativas (fase letal, ainda pendentes) e
        resolve cada uma por distancia direta ao jogador + estado da
        acao `anchor`."""
        del delta_time

        active_count = self._threat_pool.count
        if active_count == 0:
            return

        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )
        threat_view = self._threat_pool.active_view()

        active = self._active_mask[:active_count]
        np.equal(threat_view["mode_tag"], MODE_TAG_SURVIVAL, out=active)
        np.greater(threat_view["duration_sec"], 0.0, out=self._scratch_mask[:active_count])
        np.logical_and(active, self._scratch_mask[:active_count], out=active)
        np.equal(threat_view["phase"], PHASE_LETHAL, out=self._scratch_mask[:active_count])
        np.logical_and(active, self._scratch_mask[:active_count], out=active)
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=self._scratch_mask[:active_count])
        np.logical_and(active, self._scratch_mask[:active_count], out=active)

        active_rows = np.flatnonzero(active)
        if active_rows.shape[0] == 0:
            return

        transform_pool = self._transform_pool
        player_row = transform_pool.dense_row_of(self._player_entity_index)
        player_view = transform_pool.active_view()
        player_x = float(player_view["position_x"][player_row])
        player_y = float(player_view["position_y"][player_row])

        hitbox_pool = self._hitbox_pool
        anchor_held = self._input_provider.is_action_held(self._anchor_action_name)
        entity_indices = self._threat_pool.active_entity_indices()

        for row in active_rows:
            row_int = int(row)
            entity_index = int(entity_indices[row_int])
            t_row = transform_pool.dense_row_of(entity_index)
            zone_x = float(transform_pool.active_view()["position_x"][t_row])
            zone_y = float(transform_pool.active_view()["position_y"][t_row])
            hb_row = hitbox_pool.dense_row_of(entity_index)
            radius = float(hitbox_pool.active_view()["half_width"][hb_row])

            distance = math.hypot(player_x - zone_x, player_y - zone_y)
            if distance > radius or not anchor_held:
                self._resolve_break(world, threat_view, row_int)
                continue

            sustain_end = float(threat_view["target_hit_time_sec"][row_int]) + float(
                threat_view["duration_sec"][row_int]
            )
            if now_effective >= sustain_end:
                self._resolve_success(world, threat_view, row_int)

    def _play(self, sound_id, volume: float) -> None:
        """Dispara um SFX se houver backend e som configurados (testes
        headless injetam NullAudioEngine ou nada)."""
        if self._audio_engine is not None and sound_id is not None:
            self._audio_engine.play_one_shot(sound_id, volume)

    def _resolve_success(self, world: World, threat_view: np.ndarray, row: int) -> None:
        """Sustentou dentro da zona ate o fim: SURVIVED, destruicao
        diferida, placar/combo normais (mesmo veredito de sobreviver a
        uma parede comum)."""
        threat_view["judgment"][row] = JUDGMENT_SURVIVED
        world.destroy_entity(int(threat_view["packed_handle"][row]))

        state = self._game_state
        state.survive_count += 1
        state.score += self._score_per_success
        state.combo_count += 1
        if state.combo_count > state.max_combo:
            state.max_combo = state.combo_count
        state.register_judgment_feedback(JUDGMENT_SURVIVED, self._judgment_display_seconds)
        self._play(self._success_sound_id, 0.6)

    def _resolve_break(self, world: World, threat_view: np.ndarray, row: int) -> None:
        """Saiu do raio ou soltou Ancora antes do fim: MISS imediato,
        combo zerado, dano de vida (respeita Modo Treino) e o feedback
        fisico duplo -- Camera Shake e Haptics (`IInputProvider.set_rumble`,
        no-op silencioso sem controle conectado)."""
        threat_view["judgment"][row] = JUDGMENT_MISS
        world.destroy_entity(int(threat_view["packed_handle"][row]))

        state = self._game_state
        state.miss_count += 1
        state.combo_count = 0
        if not self._practice_mode and state.health > 0:
            state.health -= 1
        state.register_judgment_feedback(JUDGMENT_MISS, self._judgment_display_seconds)
        state.trigger_shake(self._safe_zone_break_shake_px)
        self._input_provider.set_rumble(
            self._rumble_low_freq, self._rumble_high_freq, self._rumble_duration_seconds
        )
        self._play(self._break_sound_id, 0.7)
