"""Eclipses Orbitais: converte a rotacao ja integrada pelo PhysicsSystem generico em posicao orbital cartesiana."""
from __future__ import annotations

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World


class OrbitalEclipseSystem(ISystem):
    """
    "Eclipses Orbitais" (Barreiras Dinamicas): cada obstaculo do
    arquetipo `orbital_eclipse` tem `velocity.angular` CONSTANTE (armado
    uma unica vez na criacao) -- o `PhysicsSystem` GENERICO da engine ja
    integra sozinho `transform.rotation_rad += angular * delta_time`
    (movimento circular uniforme "de graca", sem nenhum sistema novo
    para isso). O motor generico, porem, nao tem nocao de ORBITA: ele so
    sabe girar (`rotation_rad`) e transladar linearmente
    (`position += velocity_linear * dt`) -- nunca converter um angulo em
    posicao ao redor de um centro. Este sistema faz exatamente essa
    ponte, e por isso PRECISA rodar DEPOIS do `PhysicsSystem` no
    registro da composicao: le o `rotation_rad` JA atualizado neste
    frame e sobrescreve `position_x/y` para o ponto correspondente no
    circulo de raio `orbit_radius` -- `velocity.linear_x/y` de cada
    eclipse fica ZERADO desde a criacao, entao a integracao linear do
    `PhysicsSystem` sobre elas e sempre um no-op (evita tocar a ENGINE).

    Zero-GC: vetorizado sobre os poucos eclipses (tipicamente 1-3) via
    `dense_rows_of`; `np.cos`/`np.sin` alocam um array transiente do
    tamanho da contagem de eclipses -- desprezivel e do MESMO padrao ja
    aceito pelo `OrbitalCaptureSystem`.
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        center_xy: tuple,
        orbit_radius: float,
        eclipse_entity_indices: np.ndarray,
    ) -> None:
        self._transform_pool = memory_manager.get_pool("transform")
        self._center_x, self._center_y = float(center_xy[0]), float(center_xy[1])
        self._orbit_radius = float(orbit_radius)
        self._entity_indices = eclipse_entity_indices

    def update(self, world: World, delta_time: float) -> None:
        del world, delta_time
        rows = self._transform_pool.dense_rows_of(self._entity_indices)
        view = self._transform_pool.active_view()
        angles = view["rotation_rad"][rows]
        view["position_x"][rows] = self._center_x + np.cos(angles) * self._orbit_radius
        view["position_y"][rows] = self._center_y + np.sin(angles) * self._orbit_radius
