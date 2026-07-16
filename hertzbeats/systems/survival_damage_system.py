"""Modo Sobrevivencia: julgamento 100% via CollisionSystem -- tocar a parede pune, atravessar no Dash pontua."""
from __future__ import annotations

import numpy as np

from ouroboros.core.constants import INVALID_DENSE_ROW
from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.systems.collision_system import CollisionSystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock

from hertzbeats.components.schemas import (
    JUDGMENT_DODGED,
    JUDGMENT_MISS,
    JUDGMENT_PENDING,
    JUDGMENT_SURVIVED,
    MODE_TAG_SURVIVAL,
)
from hertzbeats.game_state import GameState


class SurvivalDamageSystem(ISystem):
    """
    Unico juiz do modo Sobrevivencia (nao ha botao de ritmo): consome os
    pares do `CollisionSystem` e o relogio de audio para dar a cada
    parede de som exatamente UM veredito:

        - Toque SEM i-frames  -> MISS: dano, combo zerado. A parede NAO
          e destruida (segue varrendo, so o veredito impede dano duplo).
        - Toque COM i-frames  -> DODGED: atravessou a parede no ritmo --
          pontua e estende o combo (o Dash e o "acerto" deste modo).
        - Expirou sem toque   -> SURVIVED: o jogador saiu do caminho por
          posicionamento -- pontua e estende o combo.

    A varredura de expiracao (vetorizada, buffers pre-alocados) tambem e
    o coletor de lixo do modo: TODA parede com `expire_time_sec` vencido
    e destruida (destruicao diferida da engine), pontuando apenas as
    ainda pendentes. Sem isso a pool nunca esvaziaria e a fase nunca
    terminaria.
    """

    def __init__(
        self,
        collision_system: CollisionSystem,
        audio_clock: IAudioClock,
        memory_manager: MemoryManager,
        game_state: GameState,
        player_entity_index: int,
        score_survive: int,
        judgment_display_seconds: float,
    ) -> None:
        """Buffers dimensionados pela capacidade da pool de ameacas."""
        self._collision_system = collision_system
        self._audio_clock = audio_clock
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._player_pool = memory_manager.get_pool("player_state")
        self._game_state = game_state
        self._player_entity_index = int(player_entity_index)
        self._score_survive = int(score_survive)
        self._judgment_display_seconds = float(judgment_display_seconds)

        capacity = self._threat_pool.capacity
        self._expired_mask = np.zeros(capacity, dtype=bool)
        self._pending_mask = np.zeros(capacity, dtype=bool)
        self._owned_mask = np.zeros(capacity, dtype=bool)

    def update(self, world: World, delta_time: float) -> None:
        """Aplica vereditos de colisao e a varredura de expiracao."""
        del delta_time

        active_count = self._threat_pool.count
        if active_count == 0:
            return

        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )
        threat_view = self._threat_pool.active_view()

        self._judge_collisions(world, threat_view)
        self._sweep_expired(world, threat_view, now_effective, active_count)

    def _judge_collisions(self, world: World, threat_view: np.ndarray) -> None:
        """Pares jogador x parede do frame: MISS (dano) ou DODGED (dash)."""
        pairs = self._collision_system.get_collision_pairs()
        pair_count = pairs.shape[0]
        if pair_count == 0:
            return

        player_row = self._player_pool.dense_row_of(self._player_entity_index)
        iframes_active = float(self._player_pool.active_view()["iframe_timer_sec"][player_row]) > 0.0
        player_index = self._player_entity_index
        state = self._game_state

        for pair_row in range(pair_count):
            index_a = int(pairs[pair_row, 0])
            index_b = int(pairs[pair_row, 1])
            if index_a == player_index:
                other_index = index_b
            elif index_b == player_index:
                other_index = index_a
            else:
                continue

            threat_row = self._threat_pool.dense_row_of(other_index)
            if threat_row == INVALID_DENSE_ROW:
                continue
            if int(threat_view["mode_tag"][threat_row]) != MODE_TAG_SURVIVAL:
                continue  # ameaca radial de outro juiz (modo Hibrido)
            if int(threat_view["judgment"][threat_row]) != JUDGMENT_PENDING:
                continue

            if iframes_active:
                threat_view["judgment"][threat_row] = JUDGMENT_DODGED
                state.dodge_count += 1
                state.score += self._score_survive
                state.combo_count += 1
                if state.combo_count > state.max_combo:
                    state.max_combo = state.combo_count
            else:
                threat_view["judgment"][threat_row] = JUDGMENT_MISS
                state.miss_count += 1
                state.combo_count = 0
                if state.health > 0:
                    state.health -= 1
                state.register_judgment_feedback(JUDGMENT_MISS, self._judgment_display_seconds)

    def _sweep_expired(
        self,
        world: World,
        threat_view: np.ndarray,
        now_effective: float,
        active_count: int,
    ) -> None:
        """Destroi TODA parede vencida; pontua as que expiraram ainda
        pendentes (SURVIVED)."""
        expired = self._expired_mask[:active_count]
        np.less(threat_view["expire_time_sec"], now_effective, out=expired)
        # o coletor de expiracao so recolhe as PROPRIAS paredes -- as
        # ameacas radiais do modo Hibrido tem seu proprio ciclo de vida
        owned = self._owned_mask[:active_count]
        np.equal(threat_view["mode_tag"], MODE_TAG_SURVIVAL, out=owned)
        np.logical_and(expired, owned, out=expired)
        expired_rows = np.flatnonzero(expired)
        if expired_rows.shape[0] == 0:
            return

        pending = self._pending_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=pending)

        state = self._game_state
        for row in expired_rows:
            row_int = int(row)
            if pending[row_int]:
                threat_view["judgment"][row_int] = JUDGMENT_SURVIVED
                state.survive_count += 1
                state.score += self._score_survive
                state.combo_count += 1
                if state.combo_count > state.max_combo:
                    state.max_combo = state.combo_count
            world.destroy_entity(int(threat_view["packed_handle"][row_int]))
