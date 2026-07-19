"""Consome os pares do CollisionSystem: pune o jogador quando uma ameaca vencida atinge o nucleo."""
from __future__ import annotations

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
    MODE_TAG_DEFENDER,
)
from hertzbeats.game_state import GameState


class CoreDamageSystem(ISystem):
    """
    Metade "punitiva" do passo de colisao da composicao: o
    `CollisionSystem` generico da engine DETECTA os pares AABB
    (nucleo x ameaca, filtrados por layer/mask bitwise); este sistema,
    registrado imediatamente depois, decide as CONSEQUENCIAS.

    Regras, por par envolvendo o nucleo:
        - Ameaca com `judgment != PENDING` e ignorada: ou o jogador ja
          a acertou neste exato frame (`is_hit`, destruicao ja
          enfileirada), ou ela ja foi varrida como MISS -- o veredito de
          uma ameaca e emitido no maximo UMA vez.
        - A punicao so vale se a ameaca esta VENCIDA
          (`agora_efetivo - target_hit_time_sec > good_window`): como a
          geometria faz a borda da ameaca tocar o anel do nucleo
          exatamente em `target_hit_time_sec`, o overlap AABB comeca
          junto com a janela de acerto tardio -- sem este guarda
          temporal, a colisao roubaria da janela GOOD do jogador.
        - I-frames de Dash ativos -> DODGED: destroi a ameaca sem dano
          e sem quebrar o combo ("atravessou o anel no ritmo certo").
        - Caso contrario -> dano no nucleo, combo zerado e feedback de
          MISS.

    Zero-GC: itera apenas sobre a view de pares ja pre-alocada do
    `CollisionSystem` (tipicamente 0-2 pares por frame), com leituras
    escalares primitivas. Como toda destruicao e DIFERIDA para o flush,
    os pares permanecem validos durante o frame inteiro.
    """

    def __init__(
        self,
        collision_system: CollisionSystem,
        audio_clock: IAudioClock,
        memory_manager: MemoryManager,
        game_state: GameState,
        player_entity_index: int,
        good_window_seconds: float,
        judgment_display_seconds: float,
        practice_mode: bool = False,
    ) -> None:
        """Guarda a referencia ao `CollisionSystem` ja registrado (fonte
        dos pares do frame) e resolve as pools uma unica vez.

        Modo Treino (`practice_mode=True`, musicas do jogador): o MISS
        continua contando/quebrando o combo normalmente (o feedback de
        ritmo nao muda) -- so o dano de vida e suprimido, para treinar
        um mapeamento novo sem risco de Game Over."""
        self._collision_system = collision_system
        self._audio_clock = audio_clock
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._player_pool = memory_manager.get_pool("player_state")
        self._game_state = game_state
        self._player_entity_index = int(player_entity_index)
        self._good_window = float(good_window_seconds)
        self._judgment_display_seconds = float(judgment_display_seconds)
        self._practice_mode = bool(practice_mode)

    def update(self, world: World, delta_time: float) -> None:
        """Processa os pares de colisao do frame corrente (ver regras na
        docstring da classe)."""
        del delta_time

        pairs = self._collision_system.get_collision_pairs()
        pair_count = pairs.shape[0]
        if pair_count == 0:
            return

        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )

        player_row = self._player_pool.dense_row_of(self._player_entity_index)
        iframes_active = float(self._player_pool.active_view()["iframe_timer_sec"][player_row]) > 0.0

        threat_view = self._threat_pool.active_view()
        player_index = self._player_entity_index

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
            if int(threat_view["mode_tag"][threat_row]) != MODE_TAG_DEFENDER:
                continue  # parede de som de outro juiz (modo Hibrido)
            if int(threat_view["judgment"][threat_row]) != JUDGMENT_PENDING:
                continue
            overdue_by = now_effective - float(threat_view["target_hit_time_sec"][threat_row])
            if overdue_by <= self._good_window:
                continue  # ainda dentro da janela de acerto tardio do jogador

            world.destroy_entity(int(threat_view["packed_handle"][threat_row]))
            state = self._game_state
            if iframes_active:
                threat_view["judgment"][threat_row] = JUDGMENT_DODGED
                state.dodge_count += 1
            else:
                threat_view["judgment"][threat_row] = JUDGMENT_MISS
                state.miss_count += 1
                state.combo_count = 0
                if not self._practice_mode and state.health > 0:
                    state.health -= 1
                state.register_judgment_feedback(JUDGMENT_MISS, self._judgment_display_seconds)
