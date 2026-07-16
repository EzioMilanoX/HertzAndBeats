"""Julga o input do jogador contra as ameacas vivas: PERFECT/GOOD/MISS, sem alocar um unico objeto."""
from __future__ import annotations

import math

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock
from ouroboros.interfaces.input_provider import IInputProvider

from hertzbeats.components.schemas import (
    JUDGMENT_GOOD,
    JUDGMENT_MISS,
    JUDGMENT_PENDING,
    JUDGMENT_PERFECT,
)
from hertzbeats.game_state import GameState

_TAU = 2.0 * math.pi


class JudgmentSystem(ISystem):
    """
    Roda logo apos a leitura do input e avalia se o jogador apertou
    "fire" no tempo E na direcao certos.

    LOGICA ZERO-GC: a cada frame o sistema varre a pool `rhythm_threat`
    (o RhythmThreatPool) calculando, VETORIZADO e sobre buffers
    pre-alocados no construtor (`out=` em todas as ufuncs), a diferenca
    `delta = target_hit_time_sec - agora_efetivo`, onde `agora_efetivo`
    vem exclusivamente do `IAudioClock` compensado de latencia -- a
    MESMA formula do spawner, entao julgamento e impacto compartilham a
    mesma base de tempo. Nenhum "HitEvent" ou string dinamica e criado:
    o veredito e um inteiro gravado na propria linha SoA da ameaca.

    JANELAS DE TOLERANCIA (data-driven via config):
        |delta| <= perfect_window  -> PERFECT
        |delta| <= good_window     -> GOOD
        delta   < -miss_window     -> MISS (passou do tempo)

    MIRA 360: alem da janela temporal, o acerto exige que a mira do
    jogador (`player_state.aim_angle_rad`) aponte para a ameaca dentro
    de `aim_tolerance_rad` (diferenca angular com wrap em +-pi,
    vetorizada). Entre as candidatas validas, vence a de menor |delta|.

    ATUALIZACAO DE ESTADO: no acerto, `is_hit = True` e gravado na linha
    (o restante do frame -- CollisionSystem/CoreDamageSystem -- passa a
    ignora-la), a destruicao e enfileirada via `world.destroy_entity`
    (DIFERIDA: efetivada no flush ao final do step, nunca no meio do
    frame), e o placar global (`GameState.score`/`combo_count`) e
    atualizado por aritmetica de inteiros. Zero alocacao dinamica.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        input_provider: IInputProvider,
        memory_manager: MemoryManager,
        game_state: GameState,
        player_entity_index: int,
        perfect_window_seconds: float,
        good_window_seconds: float,
        miss_window_seconds: float,
        aim_tolerance_rad: float,
        score_perfect: int,
        score_good: int,
        judgment_display_seconds: float,
        misfire_breaks_combo: bool = True,
        fire_action_name: str = "fire",
    ) -> None:
        """Resolve as pools uma unica vez e pre-aloca TODOS os buffers de
        trabalho com o tamanho da capacidade da pool de ameacas -- o
        update nunca aloca arrays novos.
        """
        self._audio_clock = audio_clock
        self._input_provider = input_provider
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._player_pool = memory_manager.get_pool("player_state")
        self._game_state = game_state
        self._player_entity_index = int(player_entity_index)

        self._perfect_window = float(perfect_window_seconds)
        self._good_window = float(good_window_seconds)
        self._miss_window = float(miss_window_seconds)
        self._aim_tolerance_rad = float(aim_tolerance_rad)
        self._score_perfect = int(score_perfect)
        self._score_good = int(score_good)
        self._judgment_display_seconds = float(judgment_display_seconds)
        self._misfire_breaks_combo = bool(misfire_breaks_combo)
        self._fire_action_name = fire_action_name

        capacity = self._threat_pool.capacity
        self._delta_buffer = np.zeros(capacity, dtype=np.float64)
        self._abs_delta_buffer = np.zeros(capacity, dtype=np.float64)
        self._angle_buffer = np.zeros(capacity, dtype=np.float64)
        self._candidate_mask = np.zeros(capacity, dtype=bool)
        self._scratch_mask = np.zeros(capacity, dtype=bool)
        self._selection_buffer = np.zeros(capacity, dtype=np.float64)

    def update(self, world: World, delta_time: float) -> None:
        """Executa o julgamento do frame: (1) varre MISSes vencidos,
        (2) se "fire" foi pressionado neste frame, tenta converter a
        melhor candidata em PERFECT/GOOD. `delta_time` e ignorado para
        decisoes ritmicas -- a fonte de verdade e o `IAudioClock`.
        """
        del delta_time

        active_count = self._threat_pool.count
        if active_count == 0:
            if self._input_provider.is_action_pressed(self._fire_action_name):
                self._register_misfire()  # tiro com a arena vazia tambem e fora do tempo
            return

        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )

        threat_view = self._threat_pool.active_view()
        deltas = self._delta_buffer[:active_count]
        np.subtract(threat_view["target_hit_time_sec"], now_effective, out=deltas)

        pending = self._scratch_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=pending)

        self._sweep_overdue_misses(world, threat_view, deltas, pending, active_count)

        if self._input_provider.is_action_pressed(self._fire_action_name):
            self._try_player_hit(world, threat_view, deltas, active_count)

    def _sweep_overdue_misses(
        self,
        world: World,
        threat_view: np.ndarray,
        deltas: np.ndarray,
        pending: np.ndarray,
        active_count: int,
    ) -> None:
        """Marca como MISS (e enfileira destruicao) toda ameaca ainda
        pendente cujo tempo ja passou alem da janela de miss
        (`delta < -miss_window`). Quebra o combo UMA vez por frame,
        independente de quantas ameacas vencerem juntas.
        """
        overdue = self._candidate_mask[:active_count]
        np.less(deltas, -self._miss_window, out=overdue)
        np.logical_and(overdue, pending, out=overdue)

        overdue_rows = np.flatnonzero(overdue)
        if overdue_rows.shape[0] == 0:
            return

        for row in overdue_rows:
            row_int = int(row)
            threat_view["judgment"][row_int] = JUDGMENT_MISS
            world.destroy_entity(int(threat_view["packed_handle"][row_int]))

        missed = int(overdue_rows.shape[0])
        self._game_state.miss_count += missed
        self._game_state.combo_count = 0
        self._game_state.register_judgment_feedback(JUDGMENT_MISS, self._judgment_display_seconds)

    def _register_misfire(self) -> None:
        """MISFIRE (estilo BPM/Hellsinger): disparo SEM candidata na
        janela de tempo + cone de mira. Falha de ritmo: zera o combo e
        exibe feedback de MISS -- e a disciplina que forca o jogador a
        atirar NA batida, nao a metralhar. Desligavel por fase
        (`misfire_breaks_combo: false`, ex.: tutorial)."""
        state = self._game_state
        state.misfire_count += 1
        if self._misfire_breaks_combo:
            state.combo_count = 0
            state.register_judgment_feedback(JUDGMENT_MISS, self._judgment_display_seconds)

    def _try_player_hit(
        self,
        world: World,
        threat_view: np.ndarray,
        deltas: np.ndarray,
        active_count: int,
    ) -> None:
        """Seleciona a melhor candidata (menor |delta|) dentro da janela
        Good E do cone de mira, e converte em PERFECT/GOOD. Disparo sem
        candidata alguma e um MISFIRE (ver `_register_misfire`).
        """
        player_row = self._player_pool.dense_row_of(self._player_entity_index)
        aim_angle = float(self._player_pool.active_view()["aim_angle_rad"][player_row])

        abs_deltas = self._abs_delta_buffer[:active_count]
        np.abs(deltas, out=abs_deltas)

        candidates = self._candidate_mask[:active_count]
        np.less_equal(abs_deltas, self._good_window, out=candidates)

        pending = self._scratch_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=pending)
        np.logical_and(candidates, pending, out=candidates)

        # Diferenca angular com wrap em +-pi, toda em buffers pre-alocados:
        # ang = |((spawn_angle - aim + pi) mod tau) - pi|
        angles = self._angle_buffer[:active_count]
        np.subtract(threat_view["spawn_angle_rad"], aim_angle, out=angles)
        np.add(angles, math.pi, out=angles)
        np.mod(angles, _TAU, out=angles)
        np.subtract(angles, math.pi, out=angles)
        np.abs(angles, out=angles)

        np.less_equal(angles, self._aim_tolerance_rad, out=self._scratch_mask[:active_count])
        np.logical_and(candidates, self._scratch_mask[:active_count], out=candidates)

        if not np.any(candidates):
            self._register_misfire()
            return

        selection = self._selection_buffer[:active_count]
        np.copyto(selection, abs_deltas)
        rejected = self._scratch_mask[:active_count]
        np.logical_not(candidates, out=rejected)
        selection[rejected] = np.inf
        best_row = int(np.argmin(selection))

        best_abs_delta = float(abs_deltas[best_row])
        judgment = JUDGMENT_PERFECT if best_abs_delta <= self._perfect_window else JUDGMENT_GOOD

        threat_view["is_hit"][best_row] = True
        threat_view["judgment"][best_row] = judgment
        world.destroy_entity(int(threat_view["packed_handle"][best_row]))

        state = self._game_state
        if judgment == JUDGMENT_PERFECT:
            state.score += self._score_perfect
            state.perfect_count += 1
        else:
            state.score += self._score_good
            state.good_count += 1
        state.combo_count += 1
        if state.combo_count > state.max_combo:
            state.max_combo = state.combo_count
        state.register_judgment_feedback(judgment, self._judgment_display_seconds)
