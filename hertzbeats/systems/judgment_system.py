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
    MODE_TAG_DEFENDER,
    POLARITY_BLUE,
    POLARITY_PINK,
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
        misfire_jam_seconds: float = 0.0,
        audio_engine=None,
        shot_sound_id: str = None,
        jam_sound_id: str = None,
        fire_action_name: str = "fire",
        polarity_enabled: bool = False,
        fire_alt_action_name: str = "fire_alt",
        heavy_threat_type_id: int = None,
        deflect_sound_id: str = None,
        parry_sound_id: str = None,
        reflected_collision_layer: int = None,
        reflected_collision_mask: int = None,
        hold_threat_type_id: int = None,
        hold_aim_tolerance_rad: float = None,
        hold_break_shake_px: float = 0.0,
        rumble_low_freq: float = 0.0,
        rumble_high_freq: float = 0.0,
        rumble_duration_seconds: float = 0.0,
        hold_engage_sound_id: str = None,
        hold_break_sound_id: str = None,
    ) -> None:
        """Resolve as pools uma unica vez e pre-aloca TODOS os buffers de
        trabalho com o tamanho da capacidade da pool de ameacas -- o
        update nunca aloca arrays novos.

        POLARIDADE (opt-in, `polarity_enabled=True`): duas acoes de
        disparo, cada uma com uma cor fixa (`fire_action_name` = azul,
        `fire_alt_action_name` = rosa, estilo Ikaruga). Uma ameaca so e
        destruida pela cor que combina com `polarity_id`; apertar a cor
        ERRADA dentro da janela de tempo+mira e um DEFLECT -- nao pune
        (o timing estava certo), mas tambem nao acerta.

        PARRY PERFEITO (ativo quando `heavy_threat_type_id` e
        fornecido): ameacas pesadas so entram como candidatas dentro da
        janela PERFECT (mais estreita que a Good usada pelas demais) --
        ao serem selecionadas, sao REFLETIDAS (velocidade invertida,
        camada de colisao trocada) em vez de destruidas; o
        `ParryImpactSystem` cuida do resto do voo/impacto.

        NOTAS LONGAS / HOLD (ativo quando `hold_threat_type_id` e
        fornecido -- mutuamente exclusivo com Parry por fase, embora
        ambos reusem o mesmo `threat_type` "pesada"): um acerto na
        janela Good normal, Fase 1 (Start), NAO destroi a candidata --
        ela fica "engajada" (`is_hit=True`, `judgment` permanece
        PENDING, velocidade zerada, colisao com o nucleo desarmada) e
        `_sweep_engaged_holds` assume o resto do ciclo de vida a cada
        frame: Fase 2 (Sustain) exige `fire` segurado E mira dentro de
        `hold_aim_tolerance_rad` continuamente ate
        `target_hit_time_sec + duration_sec`; soltar OU desmirar antes
        disso e MISS imediato (`hold_break_shake_px` de Camera Shake +
        `set_rumble` do `IInputProvider`), sustentar ate o fim e
        PERFECT.
        """
        self._audio_clock = audio_clock
        self._input_provider = input_provider
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._player_pool = memory_manager.get_pool("player_state")
        self._velocity_pool = memory_manager.get_pool("velocity")
        self._hitbox_pool = memory_manager.get_pool("hitbox")
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
        self._misfire_jam_seconds = float(misfire_jam_seconds)
        self._audio_engine = audio_engine
        self._shot_sound_id = shot_sound_id
        self._jam_sound_id = jam_sound_id
        self._fire_action_name = fire_action_name
        self._polarity_enabled = bool(polarity_enabled)
        self._fire_alt_action_name = fire_alt_action_name
        self._heavy_threat_type_id = heavy_threat_type_id
        self._deflect_sound_id = deflect_sound_id
        self._parry_sound_id = parry_sound_id
        self._reflected_collision_layer = reflected_collision_layer
        self._reflected_collision_mask = reflected_collision_mask
        self._hold_threat_type_id = hold_threat_type_id
        self._hold_aim_tolerance_rad = hold_aim_tolerance_rad
        self._hold_break_shake_px = float(hold_break_shake_px)
        self._rumble_low_freq = float(rumble_low_freq)
        self._rumble_high_freq = float(rumble_high_freq)
        self._rumble_duration_seconds = float(rumble_duration_seconds)
        self._hold_engage_sound_id = hold_engage_sound_id
        self._hold_break_sound_id = hold_break_sound_id

        capacity = self._threat_pool.capacity
        self._delta_buffer = np.zeros(capacity, dtype=np.float64)
        self._abs_delta_buffer = np.zeros(capacity, dtype=np.float64)
        self._angle_buffer = np.zeros(capacity, dtype=np.float64)
        self._candidate_mask = np.zeros(capacity, dtype=bool)
        self._pre_polarity_mask = np.zeros(capacity, dtype=bool)
        self._heavy_mask = np.zeros(capacity, dtype=bool)
        self._color_mask = np.zeros(capacity, dtype=bool)
        self._scratch_mask = np.zeros(capacity, dtype=bool)
        self._owned_mask = np.zeros(capacity, dtype=bool)
        self._window_buffer = np.zeros(capacity, dtype=np.float64)
        self._selection_buffer = np.zeros(capacity, dtype=np.float64)
        self._engaged_mask = np.zeros(capacity, dtype=bool)
        self._sustain_end_buffer = np.zeros(capacity, dtype=np.float64)

    def update(self, world: World, delta_time: float) -> None:
        """Executa o julgamento do frame: (1) varre MISSes vencidos,
        (2) se "fire" foi pressionado neste frame, tenta converter a
        melhor candidata em PERFECT/GOOD. `delta_time` e ignorado para
        decisoes ritmicas -- a fonte de verdade e o `IAudioClock`.
        """
        del delta_time

        player_row = self._player_pool.dense_row_of(self._player_entity_index)
        gun_jammed = float(self._player_pool.active_view()["gun_jam_sec"][player_row]) > 0.0

        # Sem Polaridade: um unico gatilho, sem cor. Com Polaridade: os
        # dois botoes (azul/rosa) sao checados nesta ordem fixa a cada
        # frame -- cada um e um disparo INDEPENDENTE contra a pool.
        fire_events = [(self._fire_action_name, POLARITY_BLUE)]
        if self._polarity_enabled:
            fire_events.append((self._fire_alt_action_name, POLARITY_PINK))

        triggered_polarities = []
        for action_name, polarity in fire_events:
            if self._input_provider.is_action_pressed(action_name):
                if gun_jammed:
                    self._play(self._jam_sound_id, 0.4)
                else:
                    triggered_polarities.append(polarity)

        active_count = self._threat_pool.count
        if active_count == 0:
            for _ in triggered_polarities:
                self._register_misfire()  # tiro com a arena vazia tambem e fora do tempo
            return

        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )

        threat_view = self._threat_pool.active_view()
        deltas = self._delta_buffer[:active_count]
        np.subtract(threat_view["target_hit_time_sec"], now_effective, out=deltas)

        # este juiz so e dono das ameacas RADIAIS -- no modo Hibrido,
        # paredes de som coexistem na mesma pool e pertencem a outro juiz
        owned = self._owned_mask[:active_count]
        np.equal(threat_view["mode_tag"], MODE_TAG_DEFENDER, out=owned)

        pending = self._scratch_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=pending)
        np.logical_and(pending, owned, out=pending)

        # Holds ENGAJADOS (`is_hit=True`, `judgment` ainda PENDING de
        # proposito -- ver `_sweep_engaged_holds`) tem seu PROPRIO ciclo
        # de vida por sustentacao; a varredura generica de overdue nao
        # pode trata-los como vitimas comuns so porque o
        # `target_hit_time_sec` (o INICIO do hold) ja passou.
        not_engaged = self._engaged_mask[:active_count]
        np.logical_not(threat_view["is_hit"], out=not_engaged)
        np.logical_and(pending, not_engaged, out=pending)

        if self._heavy_threat_type_id is not None:
            # projeteis refletidos (Parry) continuam PENDING de proposito
            # -- sao "armas" agora, nao vitimas; a varredura de miss NAO
            # pode destruir um refletido so porque o `target_hit_time_sec`
            # original (do momento em que era vitima) ja passou.
            reflected = self._heavy_mask[:active_count]
            np.logical_not(threat_view["is_reflected"], out=reflected)
            np.logical_and(pending, reflected, out=pending)

        self._sweep_overdue_misses(world, threat_view, deltas, pending, active_count)
        if self._hold_threat_type_id is not None:
            self._sweep_engaged_holds(world, threat_view, active_count, now_effective)

        for polarity in triggered_polarities:
            self._try_player_hit(world, threat_view, deltas, active_count, polarity)

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

    def _play(self, sound_id, volume: float) -> None:
        """Dispara um SFX se houver backend e som configurados (testes
        headless injetam NullAudioEngine ou nada)."""
        if self._audio_engine is not None and sound_id is not None:
            self._audio_engine.play_one_shot(sound_id, volume)

    def _register_misfire(self) -> None:
        """MISFIRE punitivo (estilo BPM/Hellsinger): disparo SEM candidata
        na janela de tempo + cone de mira. A arma EMPERRA por
        `misfire_jam_seconds` (clique seco; o gatilho nao responde), o
        combo zera e o feedback de MISS aparece -- a disciplina que forca
        o jogador a atirar NA batida, nao a metralhar. Desligavel por
        fase (`misfire_breaks_combo: false`, ex.: tutorial)."""
        state = self._game_state
        state.misfire_count += 1
        self._play(self._jam_sound_id, 0.55)
        if self._misfire_breaks_combo:
            state.combo_count = 0
            state.register_judgment_feedback(JUDGMENT_MISS, self._judgment_display_seconds)
            if self._misfire_jam_seconds > 0.0:
                player_row = self._player_pool.dense_row_of(self._player_entity_index)
                self._player_pool.active_view()["gun_jam_sec"][player_row] = self._misfire_jam_seconds

    def _try_player_hit(
        self,
        world: World,
        threat_view: np.ndarray,
        deltas: np.ndarray,
        active_count: int,
        fired_polarity: int,
    ) -> None:
        """Seleciona a melhor candidata (menor |delta|) dentro da janela
        de tempo (Good, ou PERFECT-apenas para ameacas pesadas -- ver
        `heavy_threat_type_id`) E do cone de mira, e converte em
        PERFECT/GOOD (ou PARRY, se pesada). Disparo sem candidata
        alguma NA JANELA DE TEMPO+MIRA e um MISFIRE; disparo com
        candidata de tempo+mira mas de COR ERRADA e um DEFLECT (nao
        pune, so nao acerta) -- so existe essa distincao com
        `polarity_enabled`.
        """
        player_row = self._player_pool.dense_row_of(self._player_entity_index)
        aim_angle = float(self._player_pool.active_view()["aim_angle_rad"][player_row])

        abs_deltas = self._abs_delta_buffer[:active_count]
        np.abs(deltas, out=abs_deltas)

        # janela por linha: PERFECT-apenas para pesadas (parry), Good
        # para as demais -- assim uma pesada so vira candidata quando o
        # timing ja garante PERFECT, sem branch extra depois.
        if self._heavy_threat_type_id is not None:
            # `np.where` nao aceita `out=` -- preenche com a janela Good
            # e sobrescreve so as linhas pesadas com a Perfect (mesmo
            # idioma de mascara booleana ja usado em `_selection_buffer`
            # logo abaixo).
            window = self._window_buffer[:active_count]
            is_heavy = self._scratch_mask[:active_count]
            np.equal(threat_view["threat_type"], self._heavy_threat_type_id, out=is_heavy)
            window.fill(self._good_window)
            window[is_heavy] = self._perfect_window
        else:
            window = self._good_window

        candidates = self._candidate_mask[:active_count]
        np.less_equal(abs_deltas, window, out=candidates)

        pending = self._scratch_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=pending)
        np.logical_and(pending, self._owned_mask[:active_count], out=pending)
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

        # Polaridade: pesadas aceitam QUALQUER cor (o parry e a defesa
        # universal); basicas exigem `polarity_id == fired_polarity`.
        # Se sobrar candidata SO por causa da cor (pre-polaridade
        # nao-vazio, pos-polaridade vazio) e um DEFLECT -- timing certo,
        # cor errada, sem punicao.
        if self._polarity_enabled:
            pre_polarity = self._pre_polarity_mask[:active_count]
            np.copyto(pre_polarity, candidates)

            color_match = self._color_mask[:active_count]
            np.equal(threat_view["polarity_id"], fired_polarity, out=color_match)

            if self._heavy_threat_type_id is not None:
                # heavy sempre passa (o parry e a defesa universal);
                # basica exige a cor certa -- OR sobre buffers distintos
                is_heavy = self._heavy_mask[:active_count]
                np.equal(threat_view["threat_type"], self._heavy_threat_type_id, out=is_heavy)
                allow = self._scratch_mask[:active_count]
                np.logical_or(is_heavy, color_match, out=allow)
            else:
                allow = color_match
            np.logical_and(candidates, allow, out=candidates)

            if not np.any(candidates) and np.any(pre_polarity):
                self._register_deflect()
                return

        if not np.any(candidates):
            self._register_misfire()
            return

        selection = self._selection_buffer[:active_count]
        np.copyto(selection, abs_deltas)
        rejected = self._scratch_mask[:active_count]
        np.logical_not(candidates, out=rejected)
        selection[rejected] = np.inf
        best_row = int(np.argmin(selection))

        # Notas Longas (Hold): Fase 1 (Start) bem-sucedida -- a candidata
        # NAO e destruida, fica "engajada" para `_sweep_engaged_holds`
        # assumir a Fase 2 (Sustain) a partir do proximo frame. Checado
        # ANTES do Parry por construcao (as duas mecanicas sao mutuamente
        # exclusivas por fase, mas a ordem fixa evita ambiguidade caso
        # uma fase configure as duas por engano).
        if self._hold_threat_type_id is not None and float(threat_view["duration_sec"][best_row]) > 0.0:
            self._register_hold_engage(threat_view, best_row)
            return

        is_parry = (
            self._heavy_threat_type_id is not None
            and int(threat_view["threat_type"][best_row]) == self._heavy_threat_type_id
        )
        if is_parry:
            self._register_parry(world, threat_view, best_row)
            return

        best_abs_delta = float(abs_deltas[best_row])
        judgment = JUDGMENT_PERFECT if best_abs_delta <= self._perfect_window else JUDGMENT_GOOD

        threat_view["is_hit"][best_row] = True
        threat_view["judgment"][best_row] = judgment
        world.destroy_entity(int(threat_view["packed_handle"][best_row]))

        # Gun Sync: o canhao do tiro certeiro E percussao da trilha
        self._play(self._shot_sound_id, 0.9)

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

    def _register_deflect(self) -> None:
        """DEFLECT (Polaridade): timing e mira certos, cor errada -- a
        "bala reflete" sem efeito algum: nao pune (combo/vida intactos),
        nao pontua, so um som/feedback sutil. A ameaca segue pendente e
        pode ainda ser acertada pela cor certa antes de vencer."""
        self._game_state.deflect_count += 1
        self._play(self._deflect_sound_id, 0.5)

    def _register_parry(self, world: World, threat_view: np.ndarray, best_row: int) -> None:
        """PARRY PERFEITO: em vez de destruir a ameaca pesada, inverte
        sua velocidade (via `velocity_pool`, resolvido sob demanda --
        raro, 0-1x por partida), marca `is_reflected` E troca sua
        camada/mascara de colisao para `REFLECTED_COLLISION_LAYER` (bate
        em ameacas, nunca no nucleo) -- sem essa troca o projetil
        continuaria com a camada/mascara ORIGINAL (ameaca x nucleo) e o
        `CollisionSystem` jamais geraria um par entre ele e outra ameaca
        pendente. O `ParryImpactSystem` cuida do resto: colisao com
        outras ameacas e expiracao ao sair da arena."""
        entity_index = int(self._threat_pool.active_entity_indices()[best_row])
        velocity_pool = self._velocity_pool
        v_row = velocity_pool.dense_row_of(entity_index)
        v_view = velocity_pool.active_view()
        v_view["linear_x"][v_row] *= -1.0
        v_view["linear_y"][v_row] *= -1.0

        if self._reflected_collision_layer is not None:
            hb_row = self._hitbox_pool.dense_row_of(entity_index)
            hb_view = self._hitbox_pool.active_view()
            hb_view["collision_layer"][hb_row] = self._reflected_collision_layer
            hb_view["collision_mask"][hb_row] = self._reflected_collision_mask

        threat_view["is_reflected"][best_row] = True
        threat_view["judgment"][best_row] = JUDGMENT_PENDING  # segue viva, agora como arma

        self._play(self._parry_sound_id, 1.0)

        state = self._game_state
        state.parry_count += 1
        state.combo_count += 1
        if state.combo_count > state.max_combo:
            state.max_combo = state.combo_count
        state.register_judgment_feedback(JUDGMENT_PERFECT, self._judgment_display_seconds)

    def _register_hold_engage(self, threat_view: np.ndarray, best_row: int) -> None:
        """Notas Longas -- Fase 1 (Start): a candidata vencedora NAO e
        destruida. Zera sua velocidade (para junto ao anel em vez de
        atravessar) e DESARMA sua colisao com o nucleo
        (`collision_layer/mask = 0`, o MESMO idioma do aviso telegrafado
        da Sobrevivencia) -- assim o `CoreDamageSystem` nunca a ve
        enquanto ela estiver sustentada, sem precisar tocar naquele
        sistema. `is_hit=True` com `judgment` ainda PENDING marca "esta
        linha pertence a Fase 2" para `_sweep_engaged_holds` e para a
        exclusao correspondente em `update()`."""
        entity_index = int(self._threat_pool.active_entity_indices()[best_row])

        v_row = self._velocity_pool.dense_row_of(entity_index)
        v_view = self._velocity_pool.active_view()
        v_view["linear_x"][v_row] = 0.0
        v_view["linear_y"][v_row] = 0.0

        hb_row = self._hitbox_pool.dense_row_of(entity_index)
        hb_view = self._hitbox_pool.active_view()
        hb_view["collision_layer"][hb_row] = 0
        hb_view["collision_mask"][hb_row] = 0

        threat_view["is_hit"][best_row] = True

        self._play(self._hold_engage_sound_id, 0.6)

    def _sweep_engaged_holds(
        self,
        world: World,
        threat_view: np.ndarray,
        active_count: int,
        now_effective: float,
    ) -> None:
        """Notas Longas -- Fase 2 (Sustain), vetorizada sobre TODAS as
        linhas engajadas (tipicamente 0-1 por vez, mas nao ha razao para
        um laco escalar): uma linha completa com sucesso quando
        `agora_efetivo >= target_hit_time_sec + duration_sec`; quebra
        (MISS imediato) se `fire` nao estiver segurado OU a mira sair de
        `hold_aim_tolerance_rad` -- o que vier primeiro no frame, sem
        esperar o fim da janela. `fire_held`/`aim_angle` sao leituras
        ESCALARES (um unico gatilho, uma unica mira) comparadas contra
        TODAS as linhas engajadas de uma vez via `out=`.
        """
        owned = self._owned_mask[:active_count]
        np.equal(threat_view["mode_tag"], MODE_TAG_DEFENDER, out=owned)
        engaged = self._engaged_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=engaged)
        np.logical_and(engaged, threat_view["is_hit"], out=engaged)
        np.logical_and(engaged, owned, out=engaged)
        np.greater(threat_view["duration_sec"], 0.0, out=self._scratch_mask[:active_count])
        np.logical_and(engaged, self._scratch_mask[:active_count], out=engaged)
        if not np.any(engaged):
            return

        sustain_end = self._sustain_end_buffer[:active_count]
        np.add(threat_view["target_hit_time_sec"], threat_view["duration_sec"], out=sustain_end)
        completed = self._heavy_mask[:active_count]
        np.greater_equal(now_effective, sustain_end, out=completed)
        np.logical_and(completed, engaged, out=completed)

        fire_held = self._input_provider.is_action_held(self._fire_action_name)
        player_row = self._player_pool.dense_row_of(self._player_entity_index)
        aim_angle = float(self._player_pool.active_view()["aim_angle_rad"][player_row])
        angles = self._angle_buffer[:active_count]
        np.subtract(threat_view["spawn_angle_rad"], aim_angle, out=angles)
        np.add(angles, math.pi, out=angles)
        np.mod(angles, _TAU, out=angles)
        np.subtract(angles, math.pi, out=angles)
        np.abs(angles, out=angles)
        aim_ok = self._pre_polarity_mask[:active_count]
        np.less_equal(angles, self._hold_aim_tolerance_rad, out=aim_ok)

        broken = self._color_mask[:active_count]
        if fire_held:
            np.logical_not(aim_ok, out=broken)
        else:
            broken.fill(True)
        np.logical_and(broken, engaged, out=broken)
        np.logical_and(broken, np.logical_not(completed), out=broken)  # completar tem prioridade

        for row in np.flatnonzero(completed):
            self._resolve_hold_success(world, threat_view, int(row))
        for row in np.flatnonzero(broken):
            self._resolve_hold_break(world, threat_view, int(row))

    def _resolve_hold_success(self, world: World, threat_view: np.ndarray, row: int) -> None:
        """Sustentou o Hold ate o fim: PERFECT, destruicao diferida,
        placar/combo normais."""
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
        """Soltou o gatilho ou desmirou antes do fim do Hold: MISS
        imediato (sem esperar a janela de miss generica), combo zerado,
        e o feedback fisico duplo que esta tarefa pediu -- Camera Shake
        (`GameState.trigger_shake`) e Haptics (`IInputProvider.set_rumble`,
        no-op silencioso sem controle conectado)."""
        threat_view["judgment"][row] = JUDGMENT_MISS
        world.destroy_entity(int(threat_view["packed_handle"][row]))

        state = self._game_state
        state.miss_count += 1
        state.combo_count = 0
        state.register_judgment_feedback(JUDGMENT_MISS, self._judgment_display_seconds)
        state.trigger_shake(self._hold_break_shake_px)
        self._input_provider.set_rumble(
            self._rumble_low_freq, self._rumble_high_freq, self._rumble_duration_seconds
        )
        self._play(self._hold_break_sound_id, 0.7)
