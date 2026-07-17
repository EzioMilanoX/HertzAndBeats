"""Pulso de Impacto: Dash perfeito dispara uma onda de choque que varre obstaculos fracos."""
from __future__ import annotations

import numpy as np

from ouroboros.core.constants import INVALID_DENSE_ROW
from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.systems.collision_system import CollisionSystem
from ouroboros.core.world import World

from hertzbeats.components.schemas import JUDGMENT_MISS, JUDGMENT_PENDING, MODE_TAG_SURVIVAL
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
"""Camada exclusiva da onda: colide com paredes de som (mask delas
inclui o jogador), nunca com o proprio jogador (que a disparou)."""


class ShockwaveSystem(ISystem):
    """
    "Pulso de Impacto": quando o `SurvivalPlayerSystem` registra um dash
    PERFEITO (na batida) neste frame, este sistema pega a PROXIMA das
    `shockwave_pool_size` entidades pre-alocadas (round-robin -- nunca
    cria/destroi entidade, ao contrario do resto do jogo, seguindo a
    disciplina extra pedida: um pool fixo reaproveitado para sempre) e a
    poe na posicao do jogador, ativa.

    Zero-GC: crescimento EXPONENCIAL do raio (`min * (max/min)^(t/dur)`)
    vetorizado sobre as poucas linhas ativas (0-5); hitbox atualizada em
    escala com o raio; ao expirar, desativa (layer/mask 0, invisivel).
    Reusa o `CollisionSystem` generico: a onda tem sua PROPRIA camada
    (`SHOCKWAVE_COLLISION_LAYER`), destruindo paredes NAO-pesadas (o
    "obstaculo fraco" do enunciado) que cruzarem seu raio -- pesadas
    resistem, como no Parry do Defensor.
    """

    def __init__(
        self,
        collision_system: CollisionSystem,
        memory_manager: MemoryManager,
        game_state: GameState,
        survival_player_system,
        player_entity_index: int,
        shockwave_entity_indices: np.ndarray,
        min_radius: float,
        max_radius: float,
        duration_seconds: float,
        heavy_threat_type_id: int,
        score_per_kill: int,
    ) -> None:
        self._collision_system = collision_system
        self._transform_pool = memory_manager.get_pool("transform")
        self._hitbox_pool = memory_manager.get_pool("hitbox")
        self._sprite_pool = memory_manager.get_pool("sprite")
        self._shockwave_pool = memory_manager.get_pool("shockwave")
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._game_state = game_state
        self._survival_player_system = survival_player_system
        self._player_entity_index = int(player_entity_index)
        self._entity_indices = shockwave_entity_indices
        self._min_radius = float(min_radius)
        self._max_radius = float(max_radius)
        self._duration = float(duration_seconds)
        self._heavy_threat_type_id = int(heavy_threat_type_id)
        self._score_per_kill = int(score_per_kill)
        self._next_slot = 0

    def update(self, world: World, delta_time: float) -> None:
        if (
            self._survival_player_system.dash_triggered_this_frame
            and self._survival_player_system.dash_was_on_beat_this_frame
        ):
            self._trigger_next_slot()

        self._advance_active_slots(delta_time)
        self._process_impacts(world)

    def _trigger_next_slot(self) -> None:
        """Ativa o proximo slot do pool fixo (round-robin: um inteiro
        primitivo cclando 0..N-1, sem alocar nada)."""
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
            if int(threat_view["mode_tag"][threat_row]) != MODE_TAG_SURVIVAL:
                continue
            if int(threat_view["judgment"][threat_row]) != JUDGMENT_PENDING:
                continue
            if int(threat_view["threat_type"][threat_row]) == self._heavy_threat_type_id:
                continue  # pesada resiste ao pulso, como ao Parry do Defensor

            # veredito terminal generico (mesmo enum de MISS -- nao e um
            # erro do jogador; nao incrementa miss_count nem quebra combo,
            # so marca a linha como resolvida para o flush).
            threat_view["judgment"][threat_row] = JUDGMENT_MISS
            world.destroy_entity(int(threat_view["packed_handle"][threat_row]))
            self._game_state.score += self._score_per_kill
