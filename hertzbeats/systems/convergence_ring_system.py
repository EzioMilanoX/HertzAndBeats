"""Aneis de Convergencia do Defensor: o aviso visual que encolhe ate o anel de julgamento no ms do hit."""
from __future__ import annotations

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock

CONVERGENCE_RING_DTYPE: np.dtype = np.dtype(
    [
        ("target_hit_time_sec", np.float64),
        ("travel_seconds", np.float64),
        ("packed_handle", np.uint64),
    ]
)
"""Estado SoA de UM anel de convergencia: instante do hit, duracao total
da aproximacao (para a interpolacao de raio) e o proprio handle (para a
autodestruicao Zero-GC no instante do hit)."""


class ConvergenceRingSystem(ISystem):
    """
    Anima os aneis-aviso do Defensor: para cada ameaca radial que nasce
    na borda, o spawner cria tambem um ANEL centrado no nucleo, e este
    sistema encolhe o raio dele MATEMATICAMENTE para alinhar com o anel
    de julgamento exatamente no milissegundo do hit::

        fracao = (target_hit_time - agora_efetivo) / travel_seconds
        raio   = anel_julgamento + (raio_spawn - anel_julgamento) * fracao

    Como `agora_efetivo` e o MESMO relogio compensado do julgamento, o
    anel tocando o anel de julgamento E a janela PERFECT -- o jogador
    atira quando os circulos se beijam, sem precisar estimar velocidade.

    Zero-GC: interpolacao vetorizada em buffers pre-alocados sobre a
    pool `convergence_ring`; escrita de escala via linhas densas
    re-resolvidas (`dense_rows_of`); aneis vencidos sao destruidos pelo
    `packed_handle` gravado na propria linha (destruicao diferida).
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        memory_manager: MemoryManager,
        spawn_radius: float,
        judgment_ring_radius: float,
    ) -> None:
        """Resolve as pools uma vez e pre-aloca os buffers de trabalho."""
        self._audio_clock = audio_clock
        self._ring_pool = memory_manager.get_pool("convergence_ring")
        self._transform_pool = memory_manager.get_pool("transform")
        self._spawn_radius = float(spawn_radius)
        self._judgment_ring_radius = float(judgment_ring_radius)

        capacity = self._ring_pool.capacity
        self._fraction_buffer = np.zeros(capacity, dtype=np.float64)
        self._radius_buffer = np.zeros(capacity, dtype=np.float64)
        self._expired_mask = np.zeros(capacity, dtype=bool)

    def update(self, world: World, delta_time: float) -> None:
        """Interpola os raios do frame e destroi aneis que ja convergiram."""
        del delta_time

        active_count = self._ring_pool.count
        if active_count == 0:
            return
        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )

        ring_view = self._ring_pool.active_view()
        fractions = self._fraction_buffer[:active_count]
        np.subtract(ring_view["target_hit_time_sec"], now_effective, out=fractions)

        # aneis que chegaram ao hit: convergiram, somem neste frame
        expired = self._expired_mask[:active_count]
        np.less_equal(fractions, 0.0, out=expired)
        expired_rows = np.flatnonzero(expired)
        for row in expired_rows:
            world.destroy_entity(int(ring_view["packed_handle"][int(row)]))

        np.divide(fractions, ring_view["travel_seconds"], out=fractions)
        np.clip(fractions, 0.0, 1.0, out=fractions)

        radii = self._radius_buffer[:active_count]
        np.multiply(fractions, self._spawn_radius - self._judgment_ring_radius, out=radii)
        np.add(radii, self._judgment_ring_radius, out=radii)
        np.divide(radii, 8.0, out=radii)  # escala do renderer: raio = 8 * scale

        entity_indices = self._ring_pool.active_entity_indices()
        transform_rows = self._transform_pool.dense_rows_of(entity_indices)
        transform_view = self._transform_pool.active_view()
        transform_view["scale_x"][transform_rows] = radii
        transform_view["scale_y"][transform_rows] = radii
