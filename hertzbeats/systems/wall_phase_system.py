"""Vira as paredes de som de AVISO para LETAL exatamente no onset (e anima o piscar do telegraph)."""
from __future__ import annotations

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock

from hertzbeats.components.schemas import (
    MODE_TAG_SURVIVAL,
    PHASE_LETHAL,
    PHASE_WARNING,
)

_BLINK_HZ = 6.0


class WallPhaseSystem(ISystem):
    """
    O coracao do telegraphing: registrado ANTES do `CollisionSystem`,
    para que a virada AVISO -> LETAL valha no mesmo frame do onset.

    - AVISO: a linha-guia pisca (alfa oscilando; pulso acelera perto do
      strike) e a colisao esta desarmada (layer/mask 0, decidido no
      spawn -- este sistema nao precisa "proteger" nada, o
      CollisionSystem nem gera pares).
    - VIRADA: quando `agora_efetivo >= target_hit_time_sec` (o MESMO
      relogio compensado do julgamento), a parede fica solida (alfa 255,
      camada visual acima) e a hitbox e ARMADA com as camadas reais --
      EXCETO Safe Zones (`duration_sec > 0`, opt-in via `holds_enabled`):
      elas tambem "solidificam" visualmente no onset, mas a hitbox
      NUNCA e armada (permanece layer/mask 0 para sempre) -- sao um
      refugio julgado por distancia direta pelo `SafeZoneJudgmentSystem`,
      nunca uma colisao perigosa.

    Zero-GC: mascaras vetorizadas em buffers pre-alocados selecionam as
    paredes em aviso e as que viram neste frame; o pisca-pisca e uma
    unica expressao vetorizada; a virada escreve escalarmente nas 0-2
    linhas do frame.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        memory_manager: MemoryManager,
        lethal_collision_layer: int,
        lethal_collision_mask: int,
    ) -> None:
        """Guarda as camadas reais da hitbox (armadas na virada)."""
        self._audio_clock = audio_clock
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._hitbox_pool = memory_manager.get_pool("hitbox")
        self._sprite_pool = memory_manager.get_pool("sprite")
        self._lethal_collision_layer = int(lethal_collision_layer)
        self._lethal_collision_mask = int(lethal_collision_mask)

        capacity = self._threat_pool.capacity
        self._warning_mask = np.zeros(capacity, dtype=bool)
        self._scratch_mask = np.zeros(capacity, dtype=bool)
        self._time_left_buffer = np.zeros(capacity, dtype=np.float64)
        self._alpha_buffer = np.zeros(capacity, dtype=np.float64)

    def update(self, world: World, delta_time: float) -> None:
        del delta_time

        active_count = self._threat_pool.count
        if active_count == 0:
            return
        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )

        threat_view = self._threat_pool.active_view()
        warning = self._warning_mask[:active_count]
        np.equal(threat_view["phase"], PHASE_WARNING, out=warning)
        np.equal(threat_view["mode_tag"], MODE_TAG_SURVIVAL, out=self._scratch_mask[:active_count])
        np.logical_and(warning, self._scratch_mask[:active_count], out=warning)
        if not np.any(warning):
            return

        time_left = self._time_left_buffer[:active_count]
        np.subtract(threat_view["target_hit_time_sec"], now_effective, out=time_left)

        # VIRADA: onset alcancado -> solida e letal neste mesmo frame
        due = self._scratch_mask[:active_count]
        np.less_equal(time_left, 0.0, out=due)
        np.logical_and(due, warning, out=due)
        due_rows = np.flatnonzero(due)
        entity_indices = self._threat_pool.active_entity_indices()
        hitbox_view = self._hitbox_pool.active_view()
        sprite_view = self._sprite_pool.active_view()
        for row in due_rows:
            row_int = int(row)
            threat_view["phase"][row_int] = PHASE_LETHAL
            entity_index = int(entity_indices[row_int])
            if float(threat_view["duration_sec"][row_int]) <= 0.0:
                hitbox_row = self._hitbox_pool.dense_row_of(entity_index)
                hitbox_view["collision_layer"][hitbox_row] = self._lethal_collision_layer
                hitbox_view["collision_mask"][hitbox_row] = self._lethal_collision_mask
            sprite_row = self._sprite_pool.dense_row_of(entity_index)
            sprite_view["tint_a"][sprite_row] = 255
            sprite_view["layer_z"][sprite_row] = 22
            warning[row_int] = False

        # PISCA-PISCA do aviso: alfa oscila e acelera conforme o strike
        # se aproxima (|sin| da contagem regressiva)
        warning_rows = np.flatnonzero(warning)
        if warning_rows.shape[0] == 0:
            return
        alphas = self._alpha_buffer[:active_count]
        np.multiply(time_left, _BLINK_HZ * np.pi, out=alphas)
        np.sin(alphas, out=alphas)
        np.abs(alphas, out=alphas)
        np.multiply(alphas, 70.0, out=alphas)
        np.add(alphas, 40.0, out=alphas)
        for row in warning_rows:
            row_int = int(row)
            entity_index = int(entity_indices[row_int])
            sprite_row = self._sprite_pool.dense_row_of(entity_index)
            sprite_view["tint_a"][sprite_row] = int(alphas[row_int])
