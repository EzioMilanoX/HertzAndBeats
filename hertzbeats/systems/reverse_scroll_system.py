"""Inversao de Gravidade (Reverse Scroll): espelha spawn/linha de julgamento em tempo real -- o julgamento nunca muda."""
from __future__ import annotations

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock

from hertzbeats.components.schemas import JUDGMENT_PENDING, MODE_TAG_LANES
from hertzbeats.modchart import compute_scroll_flip_fraction

_TIME_EPSILON_SECONDS = 1e-3
"""Piso de seguranca PURAMENTE numerico para `time_remaining` no
recalculo continuo de velocidade -- evita divisao por zero/negativo
para uma nota ja vencida (prestes a ser varrida como MISS pelo
`LaneJudgmentSystem`). Deliberadamente MUITO menor que o
`min_travel_seconds` do spawner (que evita uma nota inteira cruzar a
tela num unico frame se nascer perto demais do proprio hit): um piso
GRANDE aqui frearia visivelmente TODA nota nos ultimos instantes antes
do julgamento, mesmo sem nenhum Reverse Scroll ativo."""


class ReverseScrollSystem(ISystem):
    """
    "Inversao de Gravidade": `reverse_scroll_events` (mesma lista de
    `modchart_events` da fase) fazem um Lerp continuo entre scroll
    NORMAL (notas caem, linha de julgamento embaixo) e INVERTIDO (notas
    sobem, linha de julgamento em cima) -- espelhando `spawn_y`/
    `judgment_line_y` em torno do centro vertical da janela
    (`flipped = window_height - base`).

    `current_geometry_y` (buffer de 2 elementos, MUTAVEL, compartilhado
    por IDENTIDADE com o `LaneNoteSpawnerSystem`) e reescrito todo
    frame -- uma nota NOVA nasce exatamente na geometria atual (mesma
    tecnica do buffer `current_lane_xs` do Swap). Uma nota JA CAINDO
    tambem precisa espelhar a mudanca: este sistema recalcula
    `velocity.linear_y` de TODA nota pendente do Arcade 4K a cada frame,
    de forma que, continuando nessa velocidade pelo tempo restante
    (`target_hit_time_sec - agora`), ela chegue EXATAMENTE na linha de
    julgamento ATUAL -- a mesma formula usada no spawn, so que reaplicada
    a cada frame a partir da posicao CORRENTE em vez da posicao de
    spawn. Quando nenhum evento esta ativo, essa formula e
    matematicamente IDENTICA a manter a velocidade original (nenhuma
    mudanca de comportamento fora de um Reverse Scroll ativo).

    O `LaneJudgmentSystem` e 100% temporal (nunca le posicao/velocidade),
    entao o julgamento nunca e afetado -- so a fisica/visual da queda.

    Zero-GC: um escalar (`compute_scroll_flip_fraction`) por frame;
    reescrita vetorizada de `velocity.linear_y` para TODAS as notas
    pendentes do modo (fancy indexing sobre buffers pre-alocados) mais
    um laco escalar minusculo (4 iteracoes) para os receptores/rotulos.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        memory_manager: MemoryManager,
        base_spawn_y: float,
        base_judgment_line_y: float,
        window_height: float,
        current_geometry_y: np.ndarray,
        reverse_events: tuple,
        receptor_entity_indices: np.ndarray,
        key_label_entity_indices: np.ndarray,
    ) -> None:
        """`current_geometry_y` e um array `[spawn_y, judgment_line_y]`
        MUTAVEL, da MESMA identidade que o `LaneNoteSpawnerSystem` le
        para posicionar notas novas -- este sistema o reescreve por
        inteiro todo frame."""
        self._audio_clock = audio_clock
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._transform_pool = memory_manager.get_pool("transform")
        self._velocity_pool = memory_manager.get_pool("velocity")
        self._base_spawn_y = float(base_spawn_y)
        self._base_judgment_line_y = float(base_judgment_line_y)
        self._flipped_spawn_y = float(window_height) - self._base_spawn_y
        self._flipped_judgment_line_y = float(window_height) - self._base_judgment_line_y
        self._current_geometry_y = current_geometry_y
        self._reverse_events = tuple(reverse_events)
        self._receptor_entity_indices = receptor_entity_indices
        self._key_label_entity_indices = key_label_entity_indices

        capacity = self._threat_pool.capacity
        self._owned_mask = np.zeros(capacity, dtype=bool)
        self._scratch_mask = np.zeros(capacity, dtype=bool)
        self._time_remaining_buffer = np.zeros(capacity, dtype=np.float64)

    def update(self, world: World, delta_time: float) -> None:
        del world
        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )
        flip = compute_scroll_flip_fraction(now_effective, self._reverse_events)
        spawn_y = self._base_spawn_y + (self._flipped_spawn_y - self._base_spawn_y) * flip
        judgment_line_y = (
            self._base_judgment_line_y
            + (self._flipped_judgment_line_y - self._base_judgment_line_y) * flip
        )
        self._current_geometry_y[0] = spawn_y
        self._current_geometry_y[1] = judgment_line_y

        # Este sistema roda ANTES do PhysicsSystem (registrado depois),
        # entao `transform.position_y` lido abaixo ainda NAO foi
        # avancado pelo delta_time deste frame -- corresponde ao
        # instante ANTERIOR (`now_effective - delta_time`), nao a
        # `now_effective`. Usar `now_effective` direto criaria um
        # descasamento de UM frame entre posicao (velha) e tempo restante
        # (novo), introduzindo um vies de velocidade PERMANENTE logo no
        # primeiro recalculo (achado escrevendo o teste real de fisica
        # sem deriva). Medir o tempo restante a partir do instante que
        # a posicao REALMENTE representa mantem o recalculo IDENTICO ao
        # valor original sempre que nenhum Reverse Scroll estiver ativo.
        reference_time = max(0.0, now_effective - delta_time)
        self._retarget_falling_notes(reference_time, judgment_line_y)
        self._reposition_receptors(judgment_line_y, flip)

    def _retarget_falling_notes(self, reference_time: float, judgment_line_y: float) -> None:
        """`reference_time` e o instante que `transform.position_y`
        REALMENTE representa neste ponto do frame (ver `update`) -- NAO
        `now_effective` diretamente."""
        active_count = self._threat_pool.count
        if active_count == 0:
            return
        threat_view = self._threat_pool.active_view()
        owned = self._owned_mask[:active_count]
        np.equal(threat_view["mode_tag"], MODE_TAG_LANES, out=owned)
        pending = self._scratch_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=pending)
        np.logical_and(owned, pending, out=owned)

        rows = np.flatnonzero(owned)
        if rows.shape[0] == 0:
            return

        entity_indices = self._threat_pool.active_entity_indices()[rows]
        transform_rows = self._transform_pool.dense_rows_of(entity_indices)
        velocity_rows = self._velocity_pool.dense_rows_of(entity_indices)

        time_remaining = self._time_remaining_buffer[: rows.shape[0]]
        np.subtract(threat_view["target_hit_time_sec"][rows], reference_time, out=time_remaining)
        np.maximum(time_remaining, _TIME_EPSILON_SECONDS, out=time_remaining)

        positions_y = self._transform_pool.active_view()["position_y"][transform_rows]
        new_velocity_y = (judgment_line_y - positions_y) / time_remaining
        self._velocity_pool.active_view()["linear_y"][velocity_rows] = new_velocity_y

    def _reposition_receptors(self, judgment_line_y: float, flip: float) -> None:
        """Receptores acompanham a linha de julgamento; o rotulo da
        tecla fica do lado OPOSTO a area de jogo -- `+46px` no scroll
        normal (abaixo da linha), invertido suavemente para `-46px`
        (acima) conforme `flip` avanca, para nao ficar por cima das
        notas subindo."""
        transform_view = self._transform_pool.active_view()
        label_offset = 46.0 - 92.0 * flip
        for lane in range(self._receptor_entity_indices.shape[0]):
            receptor_row = self._transform_pool.dense_row_of(int(self._receptor_entity_indices[lane]))
            transform_view["position_y"][receptor_row] = judgment_line_y
            label_row = self._transform_pool.dense_row_of(int(self._key_label_entity_indices[lane]))
            transform_view["position_y"][label_row] = judgment_line_y + label_offset
