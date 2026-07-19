"""Captura Orbital: escudos capturados orbitam o nucleo via seno/cosseno, fora da jurisdicao do PhysicsSystem generico."""
from __future__ import annotations

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock

from hertzbeats.components.schemas import PHASE_ORBITING


class OrbitalCaptureSystem(ISystem):
    """
    Move os Escudos Rotativos (Captura Orbital, Modo Defensor): a
    velocidade ja foi zerada por `JudgmentSystem._register_orbital_capture`
    no instante da captura, entao o `PhysicsSystem` generico da engine e
    um NO-OP para essas linhas -- este sistema, registrado ANTES dele,
    sobrescreve `position_x/y` DIRETAMENTE todo frame via seno/cosseno em
    torno do nucleo. Mesmo padrao ja usado por `LaneChoreographySystem`
    (Modchart Swap) e `ReverseScrollSystem` (Inversao de Gravidade) --
    evita tocar o `PhysicsSystem` da ENGINE (mudanca cross-repo).

    O angulo de cada escudo e `spawn_angle_rad` (o angulo de CAPTURA,
    congelado no momento do Parry -- campo que so servia de telemetria
    ate a captura) + `angular_speed_rad_per_sec * agora_efetivo`: todos
    os escudos giram JUNTOS na mesma velocidade angular, preservando o
    espacamento relativo entre capturas sucessivas sem precisar guardar
    nenhum estado extra por escudo.

    Zero-GC: vetorizado sobre TODAS as linhas `phase == PHASE_ORBITING`
    de uma vez (tipicamente 0-3 por partida) via mascara booleana e
    fancy indexing sobre buffers pre-alocados -- nenhum laco escalar,
    nenhum array transiente novo por frame.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        memory_manager: MemoryManager,
        center_xy: tuple,
        orbit_radius: float,
        angular_speed_rad_per_sec: float,
    ) -> None:
        self._audio_clock = audio_clock
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._transform_pool = memory_manager.get_pool("transform")
        self._center_x, self._center_y = float(center_xy[0]), float(center_xy[1])
        self._orbit_radius = float(orbit_radius)
        self._angular_speed = float(angular_speed_rad_per_sec)

        capacity = self._threat_pool.capacity
        self._orbiting_mask = np.zeros(capacity, dtype=bool)
        self._angle_buffer = np.zeros(capacity, dtype=np.float64)

    def update(self, world: World, delta_time: float) -> None:
        del world, delta_time
        threat_pool = self._threat_pool
        active_count = threat_pool.count
        if active_count == 0:
            return
        threat_view = threat_pool.active_view()

        orbiting = self._orbiting_mask[:active_count]
        np.equal(threat_view["phase"], PHASE_ORBITING, out=orbiting)
        rows = np.flatnonzero(orbiting)
        if rows.shape[0] == 0:
            return

        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )
        angles = self._angle_buffer[: rows.shape[0]]
        np.add(
            threat_view["spawn_angle_rad"][rows],
            self._angular_speed * now_effective,
            out=angles,
        )

        entity_indices = threat_pool.active_entity_indices()[rows]
        transform_rows = self._transform_pool.dense_rows_of(entity_indices)
        transform_view = self._transform_pool.active_view()
        transform_view["position_x"][transform_rows] = self._center_x + np.cos(angles) * self._orbit_radius
        transform_view["position_y"][transform_rows] = self._center_y + np.sin(angles) * self._orbit_radius
        transform_view["rotation_rad"][transform_rows] = angles
