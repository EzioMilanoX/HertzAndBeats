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
    PHASE_ORBITING,
    POLARITY_BLUE,
    POLARITY_PINK,
)
from hertzbeats.components.texture_ids import TEX_PLAYER_CORE_BLUE, TEX_PLAYER_CORE_PINK
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
        practice_mode: bool = False,
        hitlag_freeze_frames: int = 0,
        orbit_threat_type_id: int = None,
        shield_collision_layer: int = None,
        shield_collision_mask: int = None,
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
        PERFECT (dano instantaneo no nucleo em caso de quebra, mesmo
        guarda `practice_mode` do `CoreDamageSystem`).

        CAPTURA ORBITAL (ativo quando `orbit_threat_type_id` e
        fornecido): MESMA janela PERFECT-apenas do Parry, mas o desfecho
        e diferente -- `_register_orbital_capture` marca `PHASE_ORBITING`
        em vez de refletir; o `OrbitalCaptureSystem` assume o resto.

        RESSONANCIA DE POLARIDADE (automatico quando `polarity_enabled`):
        cada destruicao comum atualiza `GameState.resonance_color/chain`
        (`_register_resonance`); ao atingir `in_overdrive`, um disparo da
        cor quente vira "perfurante" -- reinterpretado para o modelo
        hitscan como abater TODAS as candidatas validas do frame de uma
        vez (`_register_piercing_kill`), nao so a melhor.

        JUICE DE PARRY (ativo quando `hitlag_freeze_frames > 0`): todo
        Parry Perfeito (classico OU Captura Orbital) arma
        `GameState.trigger_hitlag` -- congela a APRESENTACAO por N
        quadros (o `IAudioClock`/`world.step` nunca param) e agenda o
        flash de cor invertida de retorno.
        """
        self._audio_clock = audio_clock
        self._input_provider = input_provider
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._player_pool = memory_manager.get_pool("player_state")
        self._velocity_pool = memory_manager.get_pool("velocity")
        self._hitbox_pool = memory_manager.get_pool("hitbox")
        self._sprite_pool = memory_manager.get_pool("sprite")
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
        self._practice_mode = bool(practice_mode)
        self._hitlag_freeze_frames = int(hitlag_freeze_frames)
        self._orbit_threat_type_id = orbit_threat_type_id
        self._shield_collision_layer = shield_collision_layer
        self._shield_collision_mask = shield_collision_mask

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
        self._pierce_mask = np.zeros(capacity, dtype=bool)
        self._duration_mask = np.zeros(capacity, dtype=bool)
        self._orbiting_mask = np.zeros(capacity, dtype=bool)

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

        if self._polarity_enabled and triggered_polarities:
            # acessibilidade a daltonismo (item 1 do pedido de polimento):
            # o NUCLEO muda de forma (triangulo/quadrado, mesmo simbolo
            # das ameacas) ao trocar de cor -- reforco visual de "voce
            # esta atirando NESTA cor agora", independente de acerto.
            self._set_core_polarity_shape(triggered_polarities[-1])

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

        if self._orbit_threat_type_id is not None:
            # Escudos capturados (`phase == PHASE_ORBITING`) tambem
            # continuam PENDING de proposito -- viram "armas" que
            # orbitam para sempre (`OrbitalCaptureSystem`); a varredura
            # de miss NAO pode destrui-los so porque o `target_hit_time_sec`
            # original (de quando ainda eram vitimas) ja passou -- mesma
            # classe de exclusao ja aplicada acima para refletidos.
            not_orbiting = self._orbiting_mask[:active_count]
            np.not_equal(threat_view["phase"], PHASE_ORBITING, out=not_orbiting)
            np.logical_and(pending, not_orbiting, out=pending)

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

    def _set_core_polarity_shape(self, polarity: int) -> None:
        """Troca o `texture_id` do sprite do nucleo para a variante com o
        simbolo interno da cor disparada -- so o `texture_id` muda
        (nunca o `tint_r/g/b/a`, que continua 100% do `PlayerInputSystem`
        para o feedback de i-frames do Dash): como nenhum outro sistema
        reescreve `texture_id` do nucleo por frame, a mudanca persiste
        sozinha ate o proximo disparo, sem precisar reaplicar todo
        frame."""
        row = self._sprite_pool.dense_row_of(self._player_entity_index)
        self._sprite_pool.active_view()["texture_id"][row] = (
            TEX_PLAYER_CORE_PINK if polarity == POLARITY_PINK else TEX_PLAYER_CORE_BLUE
        )

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

        # janela por linha: PERFECT-apenas para pesadas (parry) E
        # orbitais (Captura Orbital -- MESMO Parry Perfeito, so muda o
        # DESFECHO), Good para as demais -- assim so viram candidatas
        # quando o timing ja garante PERFECT, sem branch extra depois.
        # `is_special` (buffer `_heavy_mask`, reaproveitado abaixo no
        # bloco de Polaridade -- nao e recalculado la) fica gravado ate
        # o fim da funcao: nenhum outro trecho escreve nele entre aqui e
        # o bloco `if self._polarity_enabled:`.
        if self._heavy_threat_type_id is not None or self._orbit_threat_type_id is not None:
            # `np.where` nao aceita `out=` -- preenche com a janela Good
            # e sobrescreve so as linhas especiais com a Perfect (mesmo
            # idioma de mascara booleana ja usado em `_selection_buffer`
            # logo abaixo).
            window = self._window_buffer[:active_count]
            is_special = self._heavy_mask[:active_count]
            is_special.fill(False)
            if self._heavy_threat_type_id is not None:
                np.equal(threat_view["threat_type"], self._heavy_threat_type_id, out=self._scratch_mask[:active_count])
                np.logical_or(is_special, self._scratch_mask[:active_count], out=is_special)
            if self._orbit_threat_type_id is not None:
                np.equal(threat_view["threat_type"], self._orbit_threat_type_id, out=self._scratch_mask[:active_count])
                np.logical_or(is_special, self._scratch_mask[:active_count], out=is_special)
            window.fill(self._good_window)
            window[is_special] = self._perfect_window
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

        # Polaridade: pesadas/orbitais aceitam QUALQUER cor (o Parry e a
        # defesa universal, capturar um escudo tambem); basicas exigem
        # `polarity_id == fired_polarity`. Se sobrar candidata SO por
        # causa da cor (pre-polaridade nao-vazio, pos-polaridade vazio)
        # e um DEFLECT -- timing certo, cor errada, sem punicao.
        if self._polarity_enabled:
            pre_polarity = self._pre_polarity_mask[:active_count]
            np.copyto(pre_polarity, candidates)

            color_match = self._color_mask[:active_count]
            np.equal(threat_view["polarity_id"], fired_polarity, out=color_match)

            if self._heavy_threat_type_id is not None or self._orbit_threat_type_id is not None:
                # `is_special` (heavy OU orbit) ja foi computado no
                # bloco da janela acima, no MESMO buffer `_heavy_mask` --
                # nenhum trecho intermediario o reescreve, entao reusar
                # aqui evita recalcular a mascara do zero.
                allow = self._scratch_mask[:active_count]
                np.logical_or(self._heavy_mask[:active_count], color_match, out=allow)
            else:
                allow = color_match
            np.logical_and(candidates, allow, out=candidates)

            if not np.any(candidates) and np.any(pre_polarity):
                self._register_deflect()
                return

        if not np.any(candidates):
            self._register_misfire()
            return

        # Ressonancia de Polaridade -- Overdrive: reinterpretacao do
        # "tiro perfurante" para o modelo hitscan sem projetil fisico do
        # Defensor (nao ha bala para atravessar nada) -- em vez disso, UM
        # disparo em Overdrive abate TODAS as candidatas comuns da cor
        # quente presentes NESTE frame, nao so a melhor (`argmin`
        # normal). Pesadas/orbitais (Parry/Captura, sempre "passam" de
        # cor) e Holds engajaveis ficam de fora -- continuam seguindo
        # suas proprias rotas mesmo durante o Overdrive.
        if (
            self._polarity_enabled
            and self._game_state.in_overdrive
            and fired_polarity == self._game_state.resonance_color
        ):
            pierce_candidates = self._pierce_mask[:active_count]
            np.copyto(pierce_candidates, candidates)
            if self._heavy_threat_type_id is not None or self._orbit_threat_type_id is not None:
                not_special = self._engaged_mask[:active_count]
                np.logical_not(self._heavy_mask[:active_count], out=not_special)
                np.logical_and(pierce_candidates, not_special, out=pierce_candidates)
            if self._hold_threat_type_id is not None:
                not_hold = self._duration_mask[:active_count]
                np.greater(threat_view["duration_sec"], 0.0, out=not_hold)
                np.logical_not(not_hold, out=not_hold)
                np.logical_and(pierce_candidates, not_hold, out=pierce_candidates)

            pierce_rows = np.flatnonzero(pierce_candidates)
            if pierce_rows.shape[0] > 1:
                self._register_piercing_kill(world, threat_view, abs_deltas, pierce_rows)
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

        is_orbit_capture = (
            self._orbit_threat_type_id is not None
            and int(threat_view["threat_type"][best_row]) == self._orbit_threat_type_id
        )
        if is_orbit_capture:
            self._register_orbital_capture(world, threat_view, best_row)
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
        if self._polarity_enabled:
            self._register_resonance(int(threat_view["polarity_id"][best_row]))

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
        if self._hitlag_freeze_frames > 0:
            state.trigger_hitlag(self._hitlag_freeze_frames)

    def _register_resonance(self, polarity_id: int) -> None:
        """Ressonancia de Polaridade (Combos Monocromaticos): destruir
        uma ameaca comum da MESMA cor da corrente atual estende a
        corrente; uma cor DIFERENTE reinicia em 1 (nao soma com a
        anterior -- a corrente e sempre de UMA cor so por vez)."""
        state = self._game_state
        if polarity_id == state.resonance_color:
            state.resonance_chain += 1
        else:
            state.resonance_color = polarity_id
            state.resonance_chain = 1

    def _register_piercing_kill(
        self,
        world: World,
        threat_view: np.ndarray,
        abs_deltas: np.ndarray,
        pierce_rows: np.ndarray,
    ) -> None:
        """Overdrive de Ressonancia: UM disparo abate TODAS as linhas em
        `pierce_rows` de uma vez (cada uma julgada PERFECT/GOOD pelo seu
        PROPRIO delta) -- ver a nota de reinterpretacao do "perfurante"
        hitscan em `_try_player_hit`. Laco escalar deliberado: o numero
        de candidatas simultaneas na MESMA janela+cone e tipicamente
        pequeno (poucas ameacas convergindo no mesmo instante), entao
        vetorizar aqui so complicaria sem ganho real de performance."""
        self._play(self._shot_sound_id, 0.9)
        state = self._game_state
        any_perfect = False
        for row in pierce_rows:
            row = int(row)
            best_abs_delta = float(abs_deltas[row])
            judgment = JUDGMENT_PERFECT if best_abs_delta <= self._perfect_window else JUDGMENT_GOOD
            any_perfect = any_perfect or judgment == JUDGMENT_PERFECT

            threat_view["is_hit"][row] = True
            threat_view["judgment"][row] = judgment
            world.destroy_entity(int(threat_view["packed_handle"][row]))
            self._register_resonance(int(threat_view["polarity_id"][row]))

            if judgment == JUDGMENT_PERFECT:
                state.score += self._score_perfect
                state.perfect_count += 1
            else:
                state.score += self._score_good
                state.good_count += 1
            state.combo_count += 1
            if state.combo_count > state.max_combo:
                state.max_combo = state.combo_count

        state.register_judgment_feedback(
            JUDGMENT_PERFECT if any_perfect else JUDGMENT_GOOD, self._judgment_display_seconds
        )

    def _register_orbital_capture(self, world: World, threat_view: np.ndarray, best_row: int) -> None:
        """CAPTURA ORBITAL: em vez de refletir (Parry classico) ou
        destruir, a ameaca tipo "orbit" vira um ESCUDO ROTATIVO em
        torno do nucleo -- velocidade zerada (`OrbitalCaptureSystem`
        assume a posicao via seno/cosseno a partir daqui em diante),
        colisao trocada para `SHIELD_COLLISION_LAYER` (arma contra
        ameacas comuns, nunca contra o nucleo -- mesma logica de troca
        de camada do Parry) e `phase` marcada `PHASE_ORBITING` (reusa o
        campo do telegraph da Sobrevivencia, sem conflito de dono aqui
        no Defensor). `spawn_angle_rad` (so telemetria ate a captura)
        vira o OFFSET ANGULAR FIXO da orbita a partir deste instante."""
        entity_index = int(self._threat_pool.active_entity_indices()[best_row])
        velocity_pool = self._velocity_pool
        v_row = velocity_pool.dense_row_of(entity_index)
        v_view = velocity_pool.active_view()
        v_view["linear_x"][v_row] = 0.0
        v_view["linear_y"][v_row] = 0.0

        if self._shield_collision_layer is not None:
            hb_row = self._hitbox_pool.dense_row_of(entity_index)
            hb_view = self._hitbox_pool.active_view()
            hb_view["collision_layer"][hb_row] = self._shield_collision_layer
            hb_view["collision_mask"][hb_row] = self._shield_collision_mask

        threat_view["phase"][best_row] = PHASE_ORBITING
        threat_view["judgment"][best_row] = JUDGMENT_PENDING  # segue viva, agora como escudo

        self._play(self._parry_sound_id, 1.0)  # mesma "defesa perfeita" do Parry classico

        state = self._game_state
        state.orbit_capture_count += 1
        state.combo_count += 1
        if state.combo_count > state.max_combo:
            state.max_combo = state.combo_count
        state.register_judgment_feedback(JUDGMENT_PERFECT, self._judgment_display_seconds)
        if self._hitlag_freeze_frames > 0:
            state.trigger_hitlag(self._hitlag_freeze_frames)

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
        dano INSTANTANEO no nucleo (mesmo guarda `practice_mode`/
        `health > 0` do `CoreDamageSystem` -- Ameaca de Hold Radial e
        tao punitiva quanto deixar uma ameaca comum atingir o nucleo, so
        que pela quebra da sustentacao em vez de colisao), e o feedback
        fisico duplo que esta tarefa pediu -- Camera Shake
        (`GameState.trigger_shake`) e Haptics (`IInputProvider.set_rumble`,
        no-op silencioso sem controle conectado)."""
        threat_view["judgment"][row] = JUDGMENT_MISS
        world.destroy_entity(int(threat_view["packed_handle"][row]))

        state = self._game_state
        state.miss_count += 1
        state.combo_count = 0
        if not self._practice_mode and state.health > 0:
            state.health -= 1
        state.register_judgment_feedback(JUDGMENT_MISS, self._judgment_display_seconds)
        state.trigger_shake(self._hold_break_shake_px)
        self._input_provider.set_rumble(
            self._rumble_low_freq, self._rumble_high_freq, self._rumble_duration_seconds
        )
        self._play(self._hold_break_sound_id, 0.7)
