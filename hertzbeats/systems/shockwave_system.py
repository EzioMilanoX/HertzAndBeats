"""Overload do Nucleo: Dash em Overdrive dispara uma onda de choque que varre ameacas fracas."""
from __future__ import annotations

import numpy as np

from ouroboros.core.constants import INVALID_DENSE_ROW
from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.systems.collision_system import CollisionSystem
from ouroboros.core.world import World

from hertzbeats.components.schemas import JUDGMENT_MISS, JUDGMENT_PENDING, MODE_TAG_DEFENDER, PHASE_ORBITING
from hertzbeats.game_state import GameState

SHOCKWAVE_DTYPE = np.dtype(
    [
        ("elapsed_seconds", np.float32),
        ("active", np.bool_),
    ]
)
"""Ciclo de vida de UMA entidade de onda de choque (pool de tamanho
fixo, pre-alocada uma unica vez -- ver `shockwave_pool_size`)."""

SHOCKWAVE_COLLISION_LAYER = 16
"""Camada exclusiva da onda: colide com ameacas comuns (mask delas
inclui o nucleo), nunca com o proprio nucleo (que a disparou)."""


class ShockwaveSystem(ISystem):
    """
    "Overload do Nucleo": reaproveitamento DIRETO do `ShockwaveSystem`
    original (Pulso de Impacto da extinta Sobrevivencia) -- mesmo
    crescimento exponencial de raio, mesmo pool fixo round-robin, MESMO
    truque de camada de colisao propria sobre o `CollisionSystem`
    generico. So o GATILHO muda: em vez de um dash na batida do corpo
    movel, este sistema consome `GameState.overload_requested` (armado
    pelo `JudgmentSystem` quando o jogador aciona Dash com a Ressonancia
    de Polaridade CHEIA sobre uma batida viva -- ver
    `GameState.consume_overdrive_for_overload`) -- um pedido de UM
    frame, resetado aqui mesmo apos consumido.

    Zero-GC: crescimento EXPONENCIAL do raio (`min * (max/min)^(t/dur)`)
    escalar sobre as poucas linhas ativas (0-5 slots); hitbox atualizada
    em escala com o raio; ao expirar, desativa (layer/mask 0, invisivel).
    """

    def __init__(
        self,
        collision_system: CollisionSystem,
        memory_manager: MemoryManager,
        game_state: GameState,
        player_entity_index: int,
        shockwave_entity_indices: np.ndarray,
        min_radius: float,
        max_radius: float,
        duration_seconds: float,
        score_per_kill: int,
        heavy_threat_type_id: int = None,
        orbit_threat_type_id: int = None,
        trigger_shake_px: float = 0.0,
    ) -> None:
        self._collision_system = collision_system
        self._transform_pool = memory_manager.get_pool("transform")
        self._hitbox_pool = memory_manager.get_pool("hitbox")
        self._sprite_pool = memory_manager.get_pool("sprite")
        self._shockwave_pool = memory_manager.get_pool("shockwave")
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._game_state = game_state
        self._player_entity_index = int(player_entity_index)
        self._entity_indices = shockwave_entity_indices
        self._min_radius = float(min_radius)
        self._max_radius = float(max_radius)
        self._duration = float(duration_seconds)
        self._score_per_kill = int(score_per_kill)
        self._heavy_threat_type_id = heavy_threat_type_id
        self._orbit_threat_type_id = orbit_threat_type_id
        self._trigger_shake_px = float(trigger_shake_px)
        self._next_slot = 0

    def update(self, world: World, delta_time: float) -> None:
        if self._game_state.overload_requested:
            self._game_state.overload_requested = False
            self._trigger_next_slot()

        self._advance_active_slots(delta_time)
        self._process_impacts(world)

    def _trigger_next_slot(self) -> None:
        """Ativa o proximo slot do pool fixo (round-robin: um inteiro
        primitivo ciclando 0..N-1, sem alocar nada), centrado no nucleo
        (o jogador do Defensor nunca se move -- ao contrario da
        Sobrevivencia extinta, nao ha posicao de corpo a consultar alem
        da propria entidade do jogador)."""
        if self._trigger_shake_px > 0.0:
            self._game_state.trigger_shake(self._trigger_shake_px)

        entity_index = int(self._entity_indices[self._next_slot])
        self._next_slot = (self._next_slot + 1) % self._entity_indices.shape[0]

        shockwave_row = self._shockwave_pool.dense_row_of(entity_index)
        shockwave_view = self._shockwave_pool.active_view()
        shockwave_view["elapsed_seconds"][shockwave_row] = 0.0
        shockwave_view["active"][shockwave_row] = True

        transform_pool = self._transform_pool
        player_row = transform_pool.dense_row_of(self._player_entity_index)
        player_view = transform_pool.active_view()
        px, py = float(player_view["position_x"][player_row]), float(player_view["position_y"][player_row])

        own_row = transform_pool.dense_row_of(entity_index)
        transform_pool.active_view()["position_x"][own_row] = px
        transform_pool.active_view()["position_y"][own_row] = py
        transform_pool.active_view()["scale_x"][own_row] = self._min_radius / 8.0
        transform_pool.active_view()["scale_y"][own_row] = self._min_radius / 8.0

        hitbox_row = self._hitbox_pool.dense_row_of(entity_index)
        hitbox_view = self._hitbox_pool.active_view()
        hitbox_view["half_width"][hitbox_row] = self._min_radius
        hitbox_view["half_height"][hitbox_row] = self._min_radius
        hitbox_view["collision_layer"][hitbox_row] = SHOCKWAVE_COLLISION_LAYER
        hitbox_view["collision_mask"][hitbox_row] = 4  # THREAT_COLLISION_LAYER

        sprite_row = self._sprite_pool.dense_row_of(entity_index)
        sprite_view = self._sprite_pool.active_view()
        sprite_view["tint_r"][sprite_row] = 200
        sprite_view["tint_g"][sprite_row] = 255
        sprite_view["tint_b"][sprite_row] = 255
        sprite_view["tint_a"][sprite_row] = 150
        sprite_view["layer_z"][sprite_row] = 25

    def _advance_active_slots(self, delta_time: float) -> None:
        shockwave_view = self._shockwave_pool.active_view()
        growth_ratio = self._max_radius / self._min_radius
        for row in range(self._entity_indices.shape[0]):
            entity_index = int(self._entity_indices[row])
            shockwave_row = self._shockwave_pool.dense_row_of(entity_index)
            if not bool(shockwave_view["active"][shockwave_row]):
                continue
            elapsed = float(shockwave_view["elapsed_seconds"][shockwave_row]) + delta_time
            if elapsed >= self._duration:
                shockwave_view["active"][shockwave_row] = False
                hitbox_row = self._hitbox_pool.dense_row_of(entity_index)
                hitbox_view = self._hitbox_pool.active_view()
                hitbox_view["collision_layer"][hitbox_row] = 0
                hitbox_view["collision_mask"][hitbox_row] = 0
                sprite_row = self._sprite_pool.dense_row_of(entity_index)
                self._sprite_pool.active_view()["tint_a"][sprite_row] = 0
                continue

            shockwave_view["elapsed_seconds"][shockwave_row] = elapsed
            radius = self._min_radius * (growth_ratio ** (elapsed / self._duration))
            transform_row = self._transform_pool.dense_row_of(entity_index)
            transform_view = self._transform_pool.active_view()
            transform_view["scale_x"][transform_row] = radius / 8.0
            transform_view["scale_y"][transform_row] = radius / 8.0
            hitbox_row = self._hitbox_pool.dense_row_of(entity_index)
            hitbox_view = self._hitbox_pool.active_view()
            hitbox_view["half_width"][hitbox_row] = radius
            hitbox_view["half_height"][hitbox_row] = radius
            sprite_row = self._sprite_pool.dense_row_of(entity_index)
            fade = max(0.0, 1.0 - elapsed / self._duration)
            self._sprite_pool.active_view()["tint_a"][sprite_row] = int(150 * fade)

    def _process_impacts(self, world: World) -> None:
        pairs = self._collision_system.get_collision_pairs()
        pair_count = pairs.shape[0]
        if pair_count == 0:
            return
        shockwave_pool = self._shockwave_pool
        threat_pool = self._threat_pool
        threat_view = threat_pool.active_view()

        for pair_row in range(pair_count):
            index_a = int(pairs[pair_row, 0])
            index_b = int(pairs[pair_row, 1])
            row_a = shockwave_pool.dense_row_of(index_a)
            row_b = shockwave_pool.dense_row_of(index_b)
            if row_a != INVALID_DENSE_ROW:
                victim_index = index_b
            elif row_b != INVALID_DENSE_ROW:
                victim_index = index_a
            else:
                continue

            threat_row = threat_pool.dense_row_of(victim_index)
            if threat_row == INVALID_DENSE_ROW:
                continue
            if int(threat_view["mode_tag"][threat_row]) != MODE_TAG_DEFENDER:
                continue
            if int(threat_view["judgment"][threat_row]) != JUDGMENT_PENDING:
                continue
            # pesadas/orbitais resistem ao pulso, como ao Parry -- e
            # projeteis ja refletidos ou escudos capturados (PENDING de
            # proposito, "armas" e nao "vitimas") nunca sao varridos por
            # engano (mesma licao de exclusao ja aplicada no
            # `JudgmentSystem`/`ParryImpactSystem`).
            if bool(threat_view["is_reflected"][threat_row]):
                continue
            if int(threat_view["phase"][threat_row]) == PHASE_ORBITING:
                continue
            if (
                self._heavy_threat_type_id is not None
                and int(threat_view["threat_type"][threat_row]) == self._heavy_threat_type_id
            ):
                continue
            if (
                self._orbit_threat_type_id is not None
                and int(threat_view["threat_type"][threat_row]) == self._orbit_threat_type_id
            ):
                continue

            # veredito terminal generico (mesmo enum de MISS -- nao e um
            # erro do jogador; nao incrementa miss_count nem quebra combo,
            # so marca a linha como resolvida para o flush).
            threat_view["judgment"][threat_row] = JUDGMENT_MISS
            world.destroy_entity(int(threat_view["packed_handle"][threat_row]))
            self._game_state.score += self._score_per_kill
