"""Ameacas Bumerangue (Defensor, modifier "boomerang"): nascem no nucleo, voam ate a borda e voltam."""
from __future__ import annotations

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock

from hertzbeats.components.schemas import JUDGMENT_PENDING


class BoomerangThreatSystem(ISystem):
    """
    Sobrescreve a posicao das ameacas Bumerangue TODO frame com uma
    formula senoidal do raio (`radius(t) = spawn_radius * sin(pi * fracao)`,
    0 no nascimento -- o nucleo -- pico em `spawn_radius` na METADE do
    percurso -- a borda -- de volta a 0 exatamente em `target_hit_time_sec`
    -- o nucleo de novo, o instante em que o jogador precisa atirar).
    Ao contrario do `PhysicsSystem` generico da engine (velocidade
    CONSTANTE, reta), aqui a velocidade radial muda de SINAL na metade
    do percurso -- por isso `RadialRhythmSpawnerSystem._materialize_threat`
    zera a velocidade das ameacas Bumerangue no spawn (o `PhysicsSystem`
    vira um no-op nelas) e este sistema, registrado ANTES dele na
    composicao, e quem de fato as move -- mesmo padrao ja usado por
    `OrbitalCaptureSystem`/`LaneChoreographySystem`/`ReverseScrollSystem`
    para nao tocar o `PhysicsSystem` da ENGINE (mudanca cross-repo).

    `JudgmentSystem`/`CoreDamageSystem` NAO precisam saber que a ameaca e
    Bumerangue: o julgamento so compara `agora` contra `target_hit_time_sec`
    (TEMPO, nunca posicao -- ver `JudgmentSystem._try_player_hit`), entao a
    mesma ameaca so vira uma candidata valida de PERFECT/GOOD perto do
    RETORNO, nunca durante a ida (`|agora - target_hit_time_sec|` bem
    maior que a janela ali, mesmo que o jogador mire bem na direcao
    dela). E o guard de tempo do `CoreDamageSystem`
    (`overdue_by <= good_window` -> ignora o par) ja protege o instante
    do nascimento (quando a ameaca nasce LITERALMENTE em cima do nucleo,
    raio 0) do mesmo jeito que protegeria qualquer ameaca comum ainda
    longe do seu instante de acerto -- nenhuma mudanca la foi necessaria.

    Zero-GC: vetorizado sobre TODAS as linhas Bumerangue PENDENTES de uma
    vez (tipicamente 0-2 por partida) via mascara booleana pre-alocada +
    fancy indexing, nenhum array transiente novo por frame.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        memory_manager: MemoryManager,
        threat_type_id: int,
        center_xy: tuple,
        spawn_radius: float,
        round_trip_seconds: float,
    ) -> None:
        self._audio_clock = audio_clock
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._transform_pool = memory_manager.get_pool("transform")
        self._threat_type_id = int(threat_type_id)
        self._center_x = float(center_xy[0])
        self._center_y = float(center_xy[1])
        self._spawn_radius = float(spawn_radius)
        self._round_trip_seconds = float(round_trip_seconds)

        capacity = self._threat_pool.capacity
        self._boomerang_mask = np.zeros(capacity, dtype=bool)
        self._pending_mask = np.zeros(capacity, dtype=bool)

    def update(self, world: World, delta_time: float) -> None:
        del world, delta_time
        threat_pool = self._threat_pool
        active_count = threat_pool.count
        if active_count == 0:
            return
        threat_view = threat_pool.active_view()

        is_boomerang = self._boomerang_mask[:active_count]
        np.equal(threat_view["threat_type"], self._threat_type_id, out=is_boomerang)
        is_pending = self._pending_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=is_pending)
        np.logical_and(is_boomerang, is_pending, out=is_boomerang)
        rows = np.flatnonzero(is_boomerang)
        if rows.shape[0] == 0:
            return

        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )
        elapsed = now_effective - (threat_view["target_hit_time_sec"][rows] - self._round_trip_seconds)
        fraction = np.clip(elapsed / self._round_trip_seconds, 0.0, 1.0)
        radius = self._spawn_radius * np.sin(np.pi * fraction)
        angles = threat_view["spawn_angle_rad"][rows]

        entity_indices = threat_pool.active_entity_indices()[rows]
        transform_rows = self._transform_pool.dense_rows_of(entity_indices)
        transform_view = self._transform_pool.active_view()
        transform_view["position_x"][transform_rows] = self._center_x + radius * np.cos(angles)
        transform_view["position_y"][transform_rows] = self._center_y + radius * np.sin(angles)
