"""Parry Perfeito: o projetil refletido varre o caminho de volta, destruindo ameacas mais fracas."""
from __future__ import annotations

from ouroboros.core.constants import INVALID_DENSE_ROW
from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.systems.collision_system import CollisionSystem
from ouroboros.core.world import World

from hertzbeats.components.schemas import (
    JUDGMENT_MISS,
    JUDGMENT_PENDING,
    MODE_TAG_DEFENDER,
    PHASE_ORBITING,
)
from hertzbeats.game_state import GameState

REFLECTED_COLLISION_LAYER = 32
"""Camada exclusiva do projetil refletido -- nao colide com o nucleo
(o `CoreDamageSystem` so processa pares que envolvem o indice do
jogador; este sistema so processa pares que NAO envolvem o jogador)."""

SHIELD_COLLISION_LAYER = 64
"""Camada exclusiva dos Escudos Rotativos (Captura Orbital) -- bit
proprio, distinto de `REFLECTED_COLLISION_LAYER` (32): um escudo e um
"atacante" permanente (nunca expira/sai da arena como um refletido).

Tambem usada pelos Eclipses Orbitais (Barreiras Dinamicas, arquetipo
`orbital_eclipse`): la, o `collision_mask` e `REFLECTED_COLLISION_LAYER`
(nao `THREAT_COLLISION_LAYER`) -- geometricamente, o `CollisionSystem`
generico ainda DETECTA pares entre um Eclipse e o projetil refletido do
Parry. TOLERANCIA ORGANICA -- ECLIPSES PERMEAVEIS: esses pares nao sao
mais CONSUMIDOS por nenhum sistema (ver `ParryImpactSystem`) -- um
Eclipse rotaciona por conta propria, fora do controle do jogador; deixa-lo
anular um Parry Perfeito (que, pela janela de candidatura do
`JudgmentSystem`, so pode nascer DENTRO de `perfect_window_seconds`)
seria um softlock de habilidade contra sorte de posicionamento, nao um
desafio justo. O projetil refletido atravessa Eclipses livremente e
continua destruindo o que estiver alem deles."""


class ParryImpactSystem(ISystem):
    """
    Metade "de impacto" do Parry Perfeito: o `JudgmentSystem`, ao
    detectar um acerto PERFECT numa ameaca pesada, inverte sua
    velocidade e troca sua camada de colisao para `REFLECTED_COLLISION_LAYER`
    (mascara = camada normal de ameacas) -- isso faz o `CollisionSystem`
    generico passar a gerar pares ENTRE o projetil refletido e as demais
    ameacas pendentes no seu caminho, sem tocar o nucleo. Captura Orbital
    (Escudos Rotativos): o MESMO `JudgmentSystem`, num acerto PERFECT
    numa ameaca tipo "orbit", troca a camada para `SHIELD_COLLISION_LAYER`
    em vez de refletir -- um escudo e um "atacante" tao valido quanto um
    projetil refletido, so que PERMANENTE (nunca expira).

    Este sistema, registrado logo apos o `CollisionSystem`, consome
    esses pares (ignorando qualquer par que envolva o jogador -- esse e
    tratado pelo `CoreDamageSystem`) e destroi a ameaca mais fraca de
    cada par colidente (o "atacante" -- refletido OU escudo -- nunca e
    destruido pela colisao), pontuando o jogador. O projetil refletido
    em si e destruido quando sai da arena (`spawn_radius` do centro);
    escudos orbitais NUNCA expiram por distancia (`is_reflected`
    permanece `False` neles, entao `_expire_out_of_bounds` os ignora
    naturalmente).

    Eclipses Orbitais: TOLERANCIA ORGANICA -- ECLIPSES PERMEAVEIS (ver
    `SHIELD_COLLISION_LAYER`) -- um par entre o projetil refletido e um
    Eclipse simplesmente NAO gera nenhum efeito aqui (nem destruicao, nem
    pontuacao): cai no mesmo guard de `INVALID_DENSE_ROW` do laço
    principal, ja que um Eclipse nunca vive na pool `rhythm_threat`. Um
    Parry Perfeito atravessa Eclipses livremente.

    Zero-GC: mesmo idioma do `CoreDamageSystem` -- laco escalar sobre
    os poucos pares do frame (tipicamente 0-2).
    """

    def __init__(
        self,
        collision_system: CollisionSystem,
        memory_manager: MemoryManager,
        game_state: GameState,
        player_entity_index: int,
        center_xy: tuple,
        spawn_radius: float,
        score_per_kill: int,
        impact_shake_px: float = 0.0,
    ) -> None:
        self._collision_system = collision_system
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._transform_pool = memory_manager.get_pool("transform")
        self._game_state = game_state
        self._player_entity_index = int(player_entity_index)
        self._center_x, self._center_y = float(center_xy[0]), float(center_xy[1])
        self._spawn_radius_sq = float(spawn_radius) ** 2
        self._score_per_kill = int(score_per_kill)
        self._impact_shake_px = float(impact_shake_px)

    def update(self, world: World, delta_time: float) -> None:
        del delta_time

        threat_pool = self._threat_pool
        if threat_pool.count == 0:
            return
        threat_view = threat_pool.active_view()

        self._process_collisions(world, threat_view)
        self._expire_out_of_bounds(world, threat_view)

    def _process_collisions(self, world: World, threat_view) -> None:
        pairs = self._collision_system.get_collision_pairs()
        pair_count = pairs.shape[0]
        if pair_count == 0:
            return
        threat_pool = self._threat_pool
        player_index = self._player_entity_index

        for pair_row in range(pair_count):
            index_a = int(pairs[pair_row, 0])
            index_b = int(pairs[pair_row, 1])
            if index_a == player_index or index_b == player_index:
                continue  # par nucleo x ameaca: e do CoreDamageSystem

            row_a = threat_pool.dense_row_of(index_a)
            row_b = threat_pool.dense_row_of(index_b)
            if row_a == INVALID_DENSE_ROW or row_b == INVALID_DENSE_ROW:
                # Eclipses Permeaveis: um Eclipse nunca vive na pool
                # `rhythm_threat`, entao um par com ele cai aqui e nao
                # produz nenhum efeito -- o projetil refletido atravessa
                # livremente (Tolerancia Organica, ver SHIELD_COLLISION_LAYER).
                continue
            if int(threat_view["mode_tag"][row_a]) != MODE_TAG_DEFENDER:
                continue
            if int(threat_view["mode_tag"][row_b]) != MODE_TAG_DEFENDER:
                continue

            a_is_attacker = self._is_attacker(threat_view, row_a)
            b_is_attacker = self._is_attacker(threat_view, row_b)
            attacker_row, victim_row = None, None
            if a_is_attacker and not b_is_attacker:
                attacker_row, victim_row = row_a, row_b
            elif b_is_attacker and not a_is_attacker:
                attacker_row, victim_row = row_b, row_a
            else:
                continue  # nenhum dos dois e um atacante (ou os dois sao)

            if int(threat_view["judgment"][victim_row]) != JUDGMENT_PENDING:
                continue

            # veredito terminal (mesmo enum de MISS -- nao e um erro do
            # jogador, so precisa de UM valor != PENDING); NAO soma
            # miss_count nem quebra combo, so pontua.
            threat_view["judgment"][victim_row] = JUDGMENT_MISS
            world.destroy_entity(int(threat_view["packed_handle"][victim_row]))
            self._game_state.score += self._score_per_kill
            if self._impact_shake_px > 0.0:
                self._game_state.trigger_shake(self._impact_shake_px)

    @staticmethod
    def _is_attacker(threat_view, row: int) -> bool:
        """Uma linha e "atacante" (colide com ameacas, nunca e vitima)
        se for um projetil refletido (`is_reflected`) OU um Escudo
        Rotativo capturado (`phase == PHASE_ORBITING`) -- os dois
        desfechos possiveis de um Parry Perfeito."""
        return bool(threat_view["is_reflected"][row]) or int(threat_view["phase"][row]) == PHASE_ORBITING

    def _expire_out_of_bounds(self, world: World, threat_view) -> None:
        """Destroi projeteis refletidos que ja saíram da arena (alem do
        raio de spawn do centro) -- sem isso, um refletido que nunca
        acerta nada viveria para sempre."""
        transform_pool = self._transform_pool
        active_indices = self._threat_pool.active_entity_indices()
        for row in range(active_indices.shape[0]):
            if not bool(threat_view["is_reflected"][row]):
                continue
            entity_index = int(active_indices[row])
            t_row = transform_pool.dense_row_of(entity_index)
            t_view = transform_pool.active_view()
            dx = float(t_view["position_x"][t_row]) - self._center_x
            dy = float(t_view["position_y"][t_row]) - self._center_y
            if dx * dx + dy * dy >= self._spawn_radius_sq:
                world.destroy_entity(int(threat_view["packed_handle"][row]))
