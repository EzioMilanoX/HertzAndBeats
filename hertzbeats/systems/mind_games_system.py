"""Rogue-lite -- Mind Games (Defensor): Buracos de Minhoca (teleporte) e Efeito Elastico (aproximacao nao-linear)."""
from __future__ import annotations

import math

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock

from hertzbeats.components.schemas import JUDGMENT_PENDING

_TAU = 2.0 * math.pi
_MIN_SPEED = 1e-6


class MindGamesSystem(ISystem):
    """
    Registrado DEPOIS do `PhysicsSystem` da engine (mesmo slot
    conceitual do `OrbitalEclipseSystem` -- ambos precisam da posicao ja
    integrada pelo frame) -- reprojeta a posicao de ameacas marcadas com
    as flags opt-in de Mind Games (`will_teleport`/`nonlinear_approach`),
    SEM tocar o `PhysicsSystem` generico da engine (mesma disciplina ja
    usada por `BoomerangThreatSystem`/`OrbitalCaptureSystem` para nao
    fazer uma mudanca cross-repo).

    BURACOS DE MINHOCA (`will_teleport`, opt-in via "wormholes" em
    `HertzConfig.active_modifiers`): quando a ameaca cruza
    `teleport_radius` rumo ao nucleo, sua posicao e REFLETIDA pelo
    centro e a velocidade e negada -- matematicamente EQUIVALENTE a
    girar `spawn_angle_rad` por PI mantendo o MESMO raio e a MESMA
    velocidade radial de aproximacao (reflexao por um ponto preserva a
    distancia ao centro, so troca de lado). A ameaca reaparece
    INSTANTANEAMENTE do lado OPOSTO do circulo, ainda convergindo pro
    nucleo na mesma velocidade -- `target_hit_time_sec` continua o
    instante CORRETO de impacto (a trajetoria raio-por-tempo nao muda,
    so o angulo); a decepcao e a DIRECAO que o jogador precisa mirar,
    que inverte de surpresa. `spawn_angle_rad` (o angulo usado pelo
    cone de mira do `JudgmentSystem`) e girado em PI JUNTO -- sem isso,
    o jogador continuaria mirando na direcao ANTIGA mesmo depois do
    susto visual. Consome a flag (`will_teleport=False`) no proprio
    frame em que dispara -- evento ONE-SHOT, nunca reflete duas vezes.

    EFEITO ELASTICO (`nonlinear_approach`, opt-in via "rubber_band"):
    reprojeta o RAIO (mantendo o angulo fixo) usando uma curva de easing
    sobre a fracao de progresso REAL do voo -- derivada do
    `IAudioClock` (`tempo_restante = target_hit_time_sec - agora_efetivo`,
    MESMA base de tempo do `JudgmentSystem`/spawner) contra a duracao
    TOTAL do voo, recuperada da MAGNITUDE da velocidade constante desta
    linha (`travel_distance / speed`) -- nunca de um campo novo de
    "tempo de spawn" na SoA. CUIDADO: NAO e correto rederivar essa
    fracao a partir do RAIO ATUAL da posicao apos este proprio sistema
    ja ter sobrescrito `position_x/y` na curva de easing -- isso
    realimentaria o proprio easing a cada frame (compondo `sin` sobre
    `sin` indefinidamente em vez de aplicar a curva UMA vez contra o
    tempo real), por isso o relogio de audio (imune a qualquer escrita
    deste sistema) e a UNICA fonte de verdade aqui. `sin(fracao * pi/2)`
    (ease-out: acelera MUITO ao nascer, freia perto do nucleo). Roda
    TODO frame -- ao contrario do teleporte, e um efeito CONTINUO do
    voo inteiro, nunca consome a flag.

    Zero-GC: vetorizado sobre as poucas linhas marcadas por frame
    (tipicamente 0-3 candidatas simultaneas), buffers pre-alocados no
    construtor + fancy indexing -- nenhum array transiente novo por
    frame.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        memory_manager: MemoryManager,
        center_xy: tuple,
        spawn_radius: float,
        judgment_radius: float,
        audio_engine=None,
        glitch_sound_id: str = None,
    ) -> None:
        self._audio_clock = audio_clock
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._transform_pool = memory_manager.get_pool("transform")
        self._velocity_pool = memory_manager.get_pool("velocity")
        self._center_x = float(center_xy[0])
        self._center_y = float(center_xy[1])
        self._spawn_radius = float(spawn_radius)
        self._judgment_radius = float(judgment_radius)
        self._audio_engine = audio_engine
        self._glitch_sound_id = glitch_sound_id

        capacity = self._threat_pool.capacity
        self._pending_mask = np.zeros(capacity, dtype=bool)
        self._wormhole_mask = np.zeros(capacity, dtype=bool)
        self._rubber_band_mask = np.zeros(capacity, dtype=bool)
        self._radius_buffer = np.zeros(capacity, dtype=np.float64)

    def update(self, world: World, delta_time: float) -> None:
        del delta_time
        threat_pool = self._threat_pool
        active_count = threat_pool.count
        if active_count == 0:
            return
        threat_view = threat_pool.active_view()

        pending = self._pending_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=pending)

        entity_indices = threat_pool.active_entity_indices()
        transform_rows = self._transform_pool.dense_rows_of(entity_indices)
        transform_view = self._transform_pool.active_view()
        dx = transform_view["position_x"][transform_rows] - self._center_x
        dy = transform_view["position_y"][transform_rows] - self._center_y
        radius = self._radius_buffer[:active_count]
        np.hypot(dx, dy, out=radius)

        self._apply_wormholes(
            world, threat_view, transform_rows, transform_view, radius, pending, active_count, entity_indices,
        )

        now_effective = max(
            0.0, self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )
        self._apply_rubber_band(
            threat_view, transform_rows, transform_view, pending, active_count, entity_indices, now_effective,
        )

    def _apply_wormholes(
        self,
        world: World,
        threat_view: np.ndarray,
        transform_rows: np.ndarray,
        transform_view: np.ndarray,
        radius: np.ndarray,
        pending: np.ndarray,
        active_count: int,
        entity_indices: np.ndarray,
    ) -> None:
        del world
        crossing = self._wormhole_mask[:active_count]
        np.less_equal(radius, threat_view["teleport_radius"], out=crossing)
        np.logical_and(crossing, threat_view["will_teleport"], out=crossing)
        np.logical_and(crossing, pending, out=crossing)

        rows = np.flatnonzero(crossing)
        if rows.shape[0] == 0:
            return

        t_rows = transform_rows[rows]
        transform_view["position_x"][t_rows] = 2.0 * self._center_x - transform_view["position_x"][t_rows]
        transform_view["position_y"][t_rows] = 2.0 * self._center_y - transform_view["position_y"][t_rows]

        v_rows = self._velocity_pool.dense_rows_of(entity_indices[rows])
        v_view = self._velocity_pool.active_view()
        v_view["linear_x"][v_rows] *= -1.0
        v_view["linear_y"][v_rows] *= -1.0

        threat_view["spawn_angle_rad"][rows] = np.mod(threat_view["spawn_angle_rad"][rows] + math.pi, _TAU)
        threat_view["will_teleport"][rows] = False

        if self._audio_engine is not None and self._glitch_sound_id is not None:
            self._audio_engine.play_one_shot(self._glitch_sound_id, 0.6)

    def _apply_rubber_band(
        self,
        threat_view: np.ndarray,
        transform_rows: np.ndarray,
        transform_view: np.ndarray,
        pending: np.ndarray,
        active_count: int,
        entity_indices: np.ndarray,
        now_effective: float,
    ) -> None:
        travel = self._spawn_radius - self._judgment_radius
        if travel <= 0.0:
            return

        elastic = self._rubber_band_mask[:active_count]
        np.logical_and(threat_view["nonlinear_approach"], pending, out=elastic)

        rows = np.flatnonzero(elastic)
        if rows.shape[0] == 0:
            return

        v_rows = self._velocity_pool.dense_rows_of(entity_indices[rows])
        v_view = self._velocity_pool.active_view()
        speed = np.hypot(v_view["linear_x"][v_rows], v_view["linear_y"][v_rows])
        np.maximum(speed, _MIN_SPEED, out=speed)
        total_flight_seconds = travel / speed

        time_remaining = threat_view["target_hit_time_sec"][rows] - now_effective
        linear_t = np.clip(1.0 - time_remaining / total_flight_seconds, 0.0, 1.0)
        eased_t = np.sin(linear_t * (math.pi / 2.0))
        eased_radius = self._spawn_radius - eased_t * travel

        angles = threat_view["spawn_angle_rad"][rows]
        t_rows = transform_rows[rows]
        transform_view["position_x"][t_rows] = self._center_x + eased_radius * np.cos(angles)
        transform_view["position_y"][t_rows] = self._center_y + eased_radius * np.sin(angles)
