"""Modo Arcade 4K: julga a tecla da coluna (D/F/J/K) contra a janela temporal da nota."""
from __future__ import annotations

from typing import Tuple

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
    JUDGMENT_SURVIVED,
    MODE_TAG_LANES,
)
from hertzbeats.game_state import GameState

DEFAULT_LANE_ACTIONS: Tuple[str, ...] = ("lane_0", "lane_1", "lane_2", "lane_3")
"""Acoes abstratas das 4 colunas (bindings data-driven: D/F/J/K por padrao)."""


class LaneJudgmentSystem(ISystem):
    """
    Julgamento do modo Arcade 4K: para cada coluna cuja tecla foi
    PRESSIONADA neste frame, avalia
    `delta = target_hit_time_sec - agora_efetivo` (relogio de audio
    compensado de latencia -- a MESMA base de tempo do spawner) contra
    as janelas de tolerancia, exigindo que a nota candidata pertenca a
    MESMA coluna (`lane == coluna da tecla`, igualdade vetorizada).

    Entre as candidatas da coluna vence a de menor |delta|; o veredito
    (PERFECT/GOOD) e um inteiro gravado na linha SoA da nota, a
    destruicao e diferida para o flush e o placar e atualizado por
    aritmetica -- nenhum evento/objeto alocado dinamicamente.

    Notas nao pressionadas vencem por varredura de MISS
    (`delta < -miss_window`), zerando o combo -- identico ao modo
    Defensor. Tecla pressionada SEM nota na janela da coluna (ghost tap)
    nao pune: fiel ao estilo VSRG/FNF.

    NOTAS LONGAS CLASSICAS + SHIELD (opt-in via `holds_enabled`; campo
    `duration_sec` escrito pelo `LaneNoteSpawnerSystem` nas pesadas que
    NAO viraram Scratch): apertar a coluna certa na janela Good de uma
    linha com `duration_sec > 0` NAO a destroi -- ela fica "engajada"
    (`is_hit=True`, `judgment` continua PENDING) e a barra segue caindo
    normalmente (mesmo idioma visual do Scratch); `_sweep_engaged_lane_holds`
    assume o resto do ciclo: soltar a tecla da coluna antes do fim e
    MISS imediato, sustentar ate `target_hit_time_sec + duration_sec` e
    PERFECT. Um MISS de Hold e absorvido por `GameState.shield_charges`
    enquanto houver carga (so tremor leve); esgotado, passa a custar
    vida de verdade -- a PRIMEIRA forma do Arcade 4K de chegar ao Game
    Over.

    NOTAS TOXICAS / BOMBAS (opt-in via `bomb_threat_type_id`, presenca
    do tipo "rhythm_threat_bomb" no beatmap): candidata como qualquer
    outra na selecao por tempo+coluna, mas acerta-la NUNCA pontua --
    zera o combo, custa vida e cega o jogador por um instante
    (`GameState.trigger_blindness`, Vignette Flash). O jogo CORRETO e
    NAO tocar: uma bomba que passa da linha sem ser pressionada e
    destruida silenciosamente como SURVIVED (sem punicao nenhuma),
    excluida da varredura generica de MISS pela mesma licao de exclusao
    do Hold/Scratch.

    NOTAS DE CURA (opt-in via `heal_threat_type_id`): em tudo igual a
    uma nota comum (pontua PERFECT/GOOD, deixar passar e MISS normal,
    sem exclusao nenhuma de varredura) -- so um acerto PERFECT tem o
    efeito colateral extra de curar `heal_amount` de vida, respeitando
    o teto de `max_health`.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        input_provider: IInputProvider,
        memory_manager: MemoryManager,
        game_state: GameState,
        perfect_window_seconds: float,
        good_window_seconds: float,
        miss_window_seconds: float,
        score_perfect: int,
        score_good: int,
        judgment_display_seconds: float,
        lane_action_names: Tuple[str, ...] = DEFAULT_LANE_ACTIONS,
        audio_engine=None,
        ghost_tap_sound_id: str = None,
        holds_enabled: bool = False,
        practice_mode: bool = False,
        hold_break_shake_px: float = 0.0,
        lane_shield_depleted_shake_px: float = 0.0,
        rumble_low_freq: float = 0.0,
        rumble_high_freq: float = 0.0,
        rumble_duration_seconds: float = 0.0,
        hold_engage_sound_id: str = None,
        hold_break_sound_id: str = None,
        shield_break_sound_id: str = None,
        bomb_threat_type_id: int = None,
        bomb_hit_shake_px: float = 0.0,
        bomb_blindness_seconds: float = 0.0,
        bomb_hit_sound_id: str = None,
        heal_threat_type_id: int = None,
        max_health: int = 0,
        heal_amount: int = 1,
        heal_sound_id: str = None,
        note_hit_sound_ids: tuple = (),
        miss_sound_id: str = None,
    ) -> None:
        """Buffers pre-alocados pela capacidade da pool (o update nunca
        aloca arrays)."""
        self._audio_clock = audio_clock
        self._input_provider = input_provider
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._game_state = game_state
        self._perfect_window = float(perfect_window_seconds)
        self._good_window = float(good_window_seconds)
        self._miss_window = float(miss_window_seconds)
        self._score_perfect = int(score_perfect)
        self._score_good = int(score_good)
        self._judgment_display_seconds = float(judgment_display_seconds)
        self._lane_action_names = tuple(lane_action_names)
        self._audio_engine = audio_engine
        self._ghost_tap_sound_id = ghost_tap_sound_id
        self._holds_enabled = bool(holds_enabled)
        self._practice_mode = bool(practice_mode)
        self._hold_break_shake_px = float(hold_break_shake_px)
        self._lane_shield_depleted_shake_px = float(lane_shield_depleted_shake_px)
        self._rumble_low_freq = float(rumble_low_freq)
        self._rumble_high_freq = float(rumble_high_freq)
        self._rumble_duration_seconds = float(rumble_duration_seconds)
        self._hold_engage_sound_id = hold_engage_sound_id
        self._hold_break_sound_id = hold_break_sound_id
        self._shield_break_sound_id = shield_break_sound_id
        self._bomb_threat_type_id = bomb_threat_type_id
        self._bomb_hit_shake_px = float(bomb_hit_shake_px)
        self._bomb_blindness_seconds = float(bomb_blindness_seconds)
        self._bomb_hit_sound_id = bomb_hit_sound_id
        self._heal_threat_type_id = heal_threat_type_id
        self._max_health = int(max_health)
        self._heal_amount = int(heal_amount)
        self._heal_sound_id = heal_sound_id
        self._note_hit_sound_ids = tuple(note_hit_sound_ids)
        self._miss_sound_id = miss_sound_id

        capacity = self._threat_pool.capacity
        self._delta_buffer = np.zeros(capacity, dtype=np.float64)
        self._abs_delta_buffer = np.zeros(capacity, dtype=np.float64)
        self._candidate_mask = np.zeros(capacity, dtype=bool)
        self._scratch_mask = np.zeros(capacity, dtype=bool)
        self._owned_mask = np.zeros(capacity, dtype=bool)
        self._not_hold_mask = np.zeros(capacity, dtype=bool)
        self._engaged_mask = np.zeros(capacity, dtype=bool)
        self._selection_buffer = np.zeros(capacity, dtype=np.float64)

    def update(self, world: World, delta_time: float) -> None:
        """Varre MISSes vencidos e julga as teclas de coluna do frame."""
        del delta_time

        active_count = self._threat_pool.count
        if active_count == 0:
            return

        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )
        threat_view = self._threat_pool.active_view()
        deltas = self._delta_buffer[:active_count]
        np.subtract(threat_view["target_hit_time_sec"], now_effective, out=deltas)

        # dono apenas das NOTAS de coluna (coexistencia multi-modo)
        owned = self._owned_mask[:active_count]
        np.equal(threat_view["mode_tag"], MODE_TAG_LANES, out=owned)

        self._sweep_overdue_misses(world, threat_view, deltas, active_count)
        if self._bomb_threat_type_id is not None:
            self._sweep_overdue_bombs(world, threat_view, deltas, active_count)
        if self._holds_enabled:
            self._sweep_engaged_lane_holds(world, threat_view, active_count, now_effective)

        # 4 checagens escalares de acao por frame; mascaras vetorizadas
        # apenas para as colunas efetivamente pressionadas (raro).
        for lane_index in range(len(self._lane_action_names)):
            if self._input_provider.is_action_pressed(self._lane_action_names[lane_index]):
                self._try_lane_hit(world, threat_view, deltas, active_count, lane_index)

    def _sweep_overdue_misses(
        self,
        world: World,
        threat_view: np.ndarray,
        deltas: np.ndarray,
        active_count: int,
    ) -> None:
        """Nota que passou da linha alem da janela de miss sem tecla:
        MISS, combo zerado (uma vez por frame), destruicao diferida."""
        overdue = self._candidate_mask[:active_count]
        np.less(deltas, -self._miss_window, out=overdue)
        pending = self._scratch_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=pending)
        np.logical_and(overdue, pending, out=overdue)
        np.logical_and(overdue, self._owned_mask[:active_count], out=overdue)
        # notas de Scratch sao do `ScratchJudgmentSystem` -- nunca vencem
        # por esta varredura de tempo (elas tem sua PROPRIA janela/regra)
        not_hold = self._not_hold_mask[:active_count]
        np.logical_not(threat_view["is_hold"], out=not_hold)
        np.logical_and(overdue, not_hold, out=overdue)
        # notas longas classicas ENGAJADAS (`is_hit=True`, `duration_sec>0`,
        # `judgment` ainda PENDING de proposito -- ver `_sweep_engaged_lane_holds`)
        # tem seu PROPRIO ciclo de vida por sustentacao; esta varredura
        # generica so pode destruir quem AINDA nao foi tocado (mesma
        # licao do Hold do Defensor).
        not_engaged = self._engaged_mask[:active_count]
        np.logical_not(threat_view["is_hit"], out=not_engaged)
        np.logical_and(overdue, not_engaged, out=overdue)
        # Bombas passam despercebidas de proposito -- destruidas
        # silenciosamente por `_sweep_overdue_bombs`, NUNCA como MISS
        # comum (o jogo CORRETO e nao tocar nelas).
        if self._bomb_threat_type_id is not None:
            not_bomb = self._not_hold_mask[:active_count]
            np.not_equal(threat_view["threat_type"], self._bomb_threat_type_id, out=not_bomb)
            np.logical_and(overdue, not_bomb, out=overdue)

        overdue_rows = np.flatnonzero(overdue)
        if overdue_rows.shape[0] == 0:
            return
        for row in overdue_rows:
            row_int = int(row)
            threat_view["judgment"][row_int] = JUDGMENT_MISS
            world.destroy_entity(int(threat_view["packed_handle"][row_int]))
        state = self._game_state
        state.miss_count += int(overdue_rows.shape[0])
        state.combo_count = 0
        state.register_judgment_feedback(JUDGMENT_MISS, self._judgment_display_seconds)
        # Audio Ducking: SFX de erro em volume MAXIMO.
        self._play(self._miss_sound_id, 1.0)

    def _try_lane_hit(
        self,
        world: World,
        threat_view: np.ndarray,
        deltas: np.ndarray,
        active_count: int,
        lane_index: int,
    ) -> None:
        """Melhor candidata (menor |delta|) DENTRO da janela Good E da
        coluna `lane_index`; ghost taps nao punem."""
        abs_deltas = self._abs_delta_buffer[:active_count]
        np.abs(deltas, out=abs_deltas)

        candidates = self._candidate_mask[:active_count]
        np.less_equal(abs_deltas, self._good_window, out=candidates)

        pending = self._scratch_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=pending)
        np.logical_and(candidates, pending, out=candidates)
        np.logical_and(candidates, self._owned_mask[:active_count], out=candidates)

        not_hold = self._not_hold_mask[:active_count]
        np.logical_not(threat_view["is_hold"], out=not_hold)
        np.logical_and(candidates, not_hold, out=candidates)

        np.equal(threat_view["lane"], lane_index, out=self._scratch_mask[:active_count])
        np.logical_and(candidates, self._scratch_mask[:active_count], out=candidates)

        if not np.any(candidates):
            # GHOST TAPPING (FNF moderno): batucar livre sem nota na
            # janela NAO pune -- so um tick discreto para manter o balanco
            if self._audio_engine is not None and self._ghost_tap_sound_id is not None:
                self._audio_engine.play_one_shot(self._ghost_tap_sound_id, 0.3)
            return

        selection = self._selection_buffer[:active_count]
        np.copyto(selection, abs_deltas)
        rejected = self._scratch_mask[:active_count]
        np.logical_not(candidates, out=rejected)
        selection[rejected] = np.inf
        best_row = int(np.argmin(selection))

        # Nota longa classica: Fase 1 (Start) bem-sucedida -- a
        # candidata NAO e destruida, fica "engajada" para
        # `_sweep_engaged_lane_holds` assumir a Fase 2 (Sustain).
        if self._holds_enabled and float(threat_view["duration_sec"][best_row]) > 0.0:
            self._register_hold_engage(threat_view, best_row)
            return

        # Bomba: candidata como qualquer nota, mas NUNCA pontua --
        # sempre pune (ver `_register_bomb_hit`).
        if (
            self._bomb_threat_type_id is not None
            and int(threat_view["threat_type"][best_row]) == self._bomb_threat_type_id
        ):
            self._register_bomb_hit(world, threat_view, best_row)
            return

        judgment = (
            JUDGMENT_PERFECT if float(abs_deltas[best_row]) <= self._perfect_window else JUDGMENT_GOOD
        )
        threat_view["is_hit"][best_row] = True
        threat_view["judgment"][best_row] = judgment
        is_heal = (
            self._heal_threat_type_id is not None
            and int(threat_view["threat_type"][best_row]) == self._heal_threat_type_id
        )
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
        # Acessibilidade -- Hit-Error Meter/Histograma: delta ASSINADO na
        # convencao "atual - esperado" (negativo=cedo, positivo=tarde) --
        # `deltas` guarda o INVERSO (`target_hit_time_sec - agora`), por
        # isso negativa aqui antes de gravar.
        state.record_hit_delta(-float(deltas[best_row]))
        # Combo Pitch Shift: mesmo truque Zero-GC do canhao do Defensor --
        # so escolhe qual variante ja sintetizada tocar, nunca faz
        # pitch-shift em tempo real.
        self._play(self._note_hit_sound_for_combo(state.combo_count), 0.7)

        # Nota de Cura: so um PERFECT cura -- GOOD pontua normalmente
        # (mesma nota, sem penalidade), mas nao recupera vida.
        if is_heal and judgment == JUDGMENT_PERFECT and state.health < self._max_health:
            state.health = min(state.health + self._heal_amount, self._max_health)
            self._play(self._heal_sound_id, 0.6)

    def _play(self, sound_id, volume: float) -> None:
        """Dispara um SFX se houver backend e som configurados (testes
        headless injetam NullAudioEngine ou nada)."""
        if self._audio_engine is not None and sound_id is not None:
            self._audio_engine.play_one_shot(sound_id, volume)

    def _note_hit_sound_for_combo(self, combo_count: int):
        """Combo Pitch Shift: ver `JudgmentSystem._shot_sound_for_combo`
        -- mesma aritmetica, variantes diferentes."""
        if not self._note_hit_sound_ids:
            return None
        index = min(combo_count // 10, len(self._note_hit_sound_ids) - 1)
        return self._note_hit_sound_ids[index]

    def _register_hold_engage(self, threat_view: np.ndarray, best_row: int) -> None:
        """Nota longa classica -- Fase 1 (Start): a candidata vencedora
        NAO e destruida nem tem sua velocidade alterada -- a barra
        continua caindo normalmente (mesmo idioma visual do Scratch),
        so precisa que a tecla da coluna continue pressionada ate o
        fim. `is_hit=True` com `judgment` ainda PENDING marca "esta
        linha pertence a Fase 2" para `_sweep_engaged_lane_holds` e para
        a exclusao correspondente em `_sweep_overdue_misses`."""
        threat_view["is_hit"][best_row] = True
        self._play(self._hold_engage_sound_id, 0.6)

    def _sweep_engaged_lane_holds(
        self,
        world: World,
        threat_view: np.ndarray,
        active_count: int,
        now_effective: float,
    ) -> None:
        """Notas longas classicas -- Fase 2 (Sustain): filtro vetorizado
        (linhas engajadas, `duration_sec>0`, donas deste juiz) seguido
        de um laco escalar sobre as poucas linhas casadas (tipicamente
        0-4, no maximo uma por coluna) -- cada linha tem sua PROPRIA
        tecla de coluna (`lane_action_names[lane]`), o que impede a
        checagem vetorizada de um unico gatilho usada pelo Hold do
        Defensor. Soltar a tecla antes do fim e MISS imediato; segurar
        ate `target_hit_time_sec + duration_sec` e PERFECT."""
        owned = self._owned_mask[:active_count]
        np.equal(threat_view["mode_tag"], MODE_TAG_LANES, out=owned)
        engaged = self._engaged_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=engaged)
        np.logical_and(engaged, threat_view["is_hit"], out=engaged)
        np.logical_and(engaged, owned, out=engaged)
        np.greater(threat_view["duration_sec"], 0.0, out=self._scratch_mask[:active_count])
        np.logical_and(engaged, self._scratch_mask[:active_count], out=engaged)

        engaged_rows = np.flatnonzero(engaged)
        if engaged_rows.shape[0] == 0:
            return

        for row in engaged_rows:
            row_int = int(row)
            lane = int(threat_view["lane"][row_int])
            if not self._input_provider.is_action_held(self._lane_action_names[lane]):
                self._resolve_hold_break(world, threat_view, row_int)
                continue
            sustain_end = float(threat_view["target_hit_time_sec"][row_int]) + float(
                threat_view["duration_sec"][row_int]
            )
            if now_effective >= sustain_end:
                self._resolve_hold_success(world, threat_view, row_int)

    def _resolve_hold_success(self, world: World, threat_view: np.ndarray, row: int) -> None:
        """Sustentou a nota longa ate o fim: PERFECT, destruicao
        diferida, placar/combo normais (mesmo veredito do Hold do
        Defensor)."""
        threat_view["judgment"][row] = JUDGMENT_PERFECT
        world.destroy_entity(int(threat_view["packed_handle"][row]))

        state = self._game_state
        state.score += self._score_perfect
        state.perfect_count += 1
        state.combo_count += 1
        if state.combo_count > state.max_combo:
            state.max_combo = state.combo_count
        state.register_judgment_feedback(JUDGMENT_PERFECT, self._judgment_display_seconds)

    def _resolve_hold_break(self, world: World, threat_view: np.ndarray, row: int) -> None:
        """Soltou a tecla da coluna antes do fim da nota longa: MISS
        imediato, combo zerado. O Shield (`GameState.shield_charges`)
        absorve a falha enquanto houver carga -- so consome 1 carga e
        um tremor leve; esgotado, a falha passa a custar vida de
        verdade (tremor maior + Haptics) -- a PRIMEIRA forma do Arcade
        4K de chegar ao Game Over."""
        threat_view["judgment"][row] = JUDGMENT_MISS
        world.destroy_entity(int(threat_view["packed_handle"][row]))

        state = self._game_state
        state.miss_count += 1
        state.combo_count = 0
        state.register_judgment_feedback(JUDGMENT_MISS, self._judgment_display_seconds)

        if state.shield_charges > 0:
            state.shield_charges -= 1
            state.trigger_shake(self._hold_break_shake_px)
            self._play(self._hold_break_sound_id, 0.7)
        else:
            if not self._practice_mode and state.health > 0:
                state.health -= 1
            state.trigger_shake(self._lane_shield_depleted_shake_px)
            self._input_provider.set_rumble(
                self._rumble_low_freq, self._rumble_high_freq, self._rumble_duration_seconds
            )
            self._play(self._shield_break_sound_id, 0.85)

    def _sweep_overdue_bombs(
        self,
        world: World,
        threat_view: np.ndarray,
        deltas: np.ndarray,
        active_count: int,
    ) -> None:
        """Bomba que passou da linha de julgamento SEM ser pressionada:
        o jogo CORRETO -- destruida silenciosamente como SURVIVED, sem
        nenhum efeito de combo/vida/tremor (o oposto do MISS comum)."""
        overdue = self._candidate_mask[:active_count]
        np.less(deltas, -self._miss_window, out=overdue)
        pending = self._scratch_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=pending)
        np.logical_and(overdue, pending, out=overdue)
        np.logical_and(overdue, self._owned_mask[:active_count], out=overdue)
        is_bomb = self._not_hold_mask[:active_count]
        np.equal(threat_view["threat_type"], self._bomb_threat_type_id, out=is_bomb)
        np.logical_and(overdue, is_bomb, out=overdue)

        overdue_rows = np.flatnonzero(overdue)
        if overdue_rows.shape[0] == 0:
            return
        for row in overdue_rows:
            row_int = int(row)
            threat_view["judgment"][row_int] = JUDGMENT_SURVIVED
            world.destroy_entity(int(threat_view["packed_handle"][row_int]))

    def _register_bomb_hit(self, world: World, threat_view: np.ndarray, best_row: int) -> None:
        """Pressionou a coluna de uma Bomba: NUNCA pontua -- combo
        zerado, dano de vida (respeita Modo Treino), tremor, Haptics e
        Vignette Flash (cegueira ritmica), reaproveitando o mesmo
        veredito MISS (nao e um erro de tempo, mas termina a linha)."""
        threat_view["is_hit"][best_row] = True
        threat_view["judgment"][best_row] = JUDGMENT_MISS
        world.destroy_entity(int(threat_view["packed_handle"][best_row]))

        state = self._game_state
        state.miss_count += 1
        state.combo_count = 0
        if not self._practice_mode and state.health > 0:
            state.health -= 1
        state.register_judgment_feedback(JUDGMENT_MISS, self._judgment_display_seconds)
        state.trigger_shake(self._bomb_hit_shake_px)
        state.trigger_blindness(self._bomb_blindness_seconds)
        self._play(self._bomb_hit_sound_id, 0.85)
