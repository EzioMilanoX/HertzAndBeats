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
    JUDGMENT_DODGED,
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
        shot_sound_ids: tuple = (),
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
        hold_grace_seconds: float = 0.15,
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
        dash_action_name: str = "dash",
        spark_system=None,
        crosshair_entity_index: int = None,
        spark_burst_count: int = 5,
        miss_sound_id: str = None,
        mirages_enabled: bool = False,
        mirage_vanish_seconds: float = 0.03,
        vampirism_combo_threshold: int = 0,
        vampirism_max_health: int = 0,
        center_xy: tuple = (0.0, 0.0),
        phalanx_radius_tolerance: float = 0.0,
        phalanx_shield_arc_rad: float = 0.0,
        core_pulse_seconds: float = 0.15,
        focus_beam_enabled: bool = False,
        focus_tolerance_rad: float = 0.0,
        focus_radius_tolerance: float = 0.0,
        focus_target_seconds: float = 0.0,
        slash_enabled: bool = False,
        slash_min_angular_speed_rad_per_sec: float = 0.0,
        slash_sound_id: str = None,
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
        `target_hit_time_sec + duration_sec`.

        TOLERANCIA ORGANICA -- HOLD FORGIVENESS ("Coyote Time" para
        micro-tremores de mao): soltar OU desmirar NAO e mais MISS
        instantaneo -- humanos nao conseguem manter mira+gatilho
        perfeitamente estaticos por segundos continuos. Cada frame
        "quebrado" acumula `delta_time` em `hold_grace_timer_sec` (campo
        na propria linha da ameaca); voltar a segurar corretamente antes
        de estourar `hold_grace_seconds` (0.15s por padrao) zera o timer
        sem penalidade. So passar desse limiar SEM retomar e MISS de
        verdade (`hold_break_shake_px` de Camera Shake + `set_rumble` do
        `IInputProvider`). Sustentar ate o fim e PERFECT (dano
        instantaneo no nucleo em caso de quebra, mesmo guarda
        `practice_mode` do `CoreDamageSystem`).

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

        OVERLOAD DO NUCLEO (automatico quando `polarity_enabled`):
        acionar `dash_action_name` (Espaco) com a Ressonancia CHEIA
        (`GameState.in_overdrive`) sobre uma batida viva arma
        `GameState.overload_requested` -- o `ShockwaveSystem` (reusado
        da extinta Sobrevivencia) consome o pedido e dispara o Pulso de
        Impacto no proximo `update` dele.

        JUICE VISUAL -- SPARKS (ativo quando `spark_system` e fornecido):
        toda vez que este sistema resolve um acerto de precisao PERFEITA
        (comum, Parry, Captura Orbital ou sustentacao de Hold ate o
        fim), chama `spark_system.emit_burst(x, y, spark_burst_count)`
        na posicao ATUAL da mira (`crosshair_entity_index`, lido do
        `transform_pool` -- o `PlayerInputSystem` ja a reposicionou
        neste MESMO frame, antes deste sistema rodar). Referencia direta
        entre sistemas, mesmo padrao ja usado por `ParryImpactSystem` <-
        `CollisionSystem`.

        ROGUE-LITE -- MIND GAMES: AMEACAS FANTASMAS (`mirages_enabled`,
        opt-in via "mirages" em `HertzConfig.active_modifiers`): linhas
        `is_mirage` tem seu PROPRIO ciclo de vida, excluido da varredura
        generica de MISS (mesmo criterio de exclusao ja aplicado a
        Holds/refletidos/orbitais) -- `_sweep_vanishing_mirages` as
        destroi em SILENCIO (`JUDGMENT_DODGED`: nao pune, nao quebra
        combo, nao pontua -- reaproveita o MESMO veredito ja usado pelos
        i-frames do Dash) a menos de `mirage_vanish_seconds` do impacto.
        Se o jogador acertar o tiro ANTES do desaparecimento,
        `_try_player_hit` forca MISS em vez de PERFECT/GOOD -- e um
        alvo falso, nunca pode ser destruido de verdade.

        ROGUE-LITE -- PERK VAMPIRISMO (`vampirism_combo_threshold > 0`):
        a cada N acertos PERFEITOS consecutivos (comum, Parry, Captura
        Orbital, sustentacao de Hold ou o abate em grupo do Overdrive --
        QUALQUER site que já incrementa `combo_count` num desfecho
        vitorioso, exceto o Auto-Play de Developer Tools, que e cheat
        e nao mecanica real), cura 1 de vida, respeitando o teto opcional
        `vampirism_max_health` (`0` = sem teto). Resolvido primitivamente
        aqui (inteiro/resto), sem o `JudgmentSystem` saber que "Perks"
        existem -- os campos ja chegam prontos de
        `HertzGameLoop._compose_stage`/`GameState.rogue_run`.

        MODO FALANGE (Undyne, `GameState.phalanx_mode`, opt-in via
        "phalanx" em `active_modifiers`): substitui por COMPLETO o
        tiro manual -- nenhuma leitura de `is_action_pressed`/misfire
        acontece enquanto ativo (ver `update`). Em vez disso,
        `_run_phalanx_block_check` varre TODA ameaca PENDENTE a cada
        frame: se o RAIO atual (lido do `transform_pool`, distancia ao
        centro -- nao o relogio) estiver a `phalanx_radius_tolerance`
        do anel de julgamento (`GameState.current_judgment_radius`) E o
        angulo (`spawn_angle_rad`, fixo desde o spawn -- o movimento
        radial e sempre puramente angular-constante) estiver dentro de
        `phalanx_shield_arc_rad` da mira atual, e bloqueada como PERFECT
        automatico (destruida, pontua, mantem o combo, aciona
        `GameState.trigger_core_pulse`). Uma ameaca que passa direto
        (fora do raio ou do arco) segue seu curso normal -- a varredura
        generica de MISS (`_sweep_overdue_misses`) e o dano por colisao
        do `CoreDamageSystem` continuam intocados, "MISS e dano como de
        costume".

        RAIO DE FOCO -- O MICROONDAS (`is_focus_target`, opt-in via
        "focus_beam" em `active_modifiers`, fracao fixa `lane % 3 == 1`
        do spawner): substitui o CLIQUE por SUSTENTACAO de mira. Roda
        TODO frame (`_run_focus_beam_check`), independente de
        `phalanx_mode` -- os dois modificadores mudam o VERBO do
        jogador para ameacas DIFERENTES da mesma pool, nunca competem
        pela mesma linha. Enquanto a mira ficar dentro de
        `focus_tolerance_rad` do angulo fixo da ameaca,
        `focus_health` decresce `delta_time` por frame (mesmo idioma
        de escrita in-place por mascara booleana da Tolerancia
        Organica do Hold: `focus_health[aimed] -= delta_time`).
        Afastar a mira ANTES da ameaca "morrer" reseta `focus_health`
        pro maximo INSTANTANEAMENTE -- punicao maxima, sem meio-termo.
        So vira PERFECT quando `focus_health <= 0` E a ameaca ja
        estiver dentro de `focus_radius_tolerance` do anel de
        julgamento (uma ameaca ainda longe do anel so acumula
        sustentacao, nunca resolve sozinha). O hexagono pulsa
        (+-10% de escala, escrito DIRETO no `transform_pool` a cada
        frame) independente de estar sendo mirado -- primeiro uso
        real de uma animacao continua neste padrao "estado visual
        derivado escrito direto na ECS", ate agora so usado por
        eventos pontuais (pulso do nucleo da Falange).

        A LAMINA -- RADIAL SLASH (`is_slash_target`, opt-in via
        "radial_slash" em `active_modifiers`, fracao fixa
        `lane % 3 == 2`): substitui o CLIQUE PONTUAL por um ARRASTO
        fisico. `_run_slash_check` roda TODO frame ignorando por
        completo `is_action_pressed` -- so considera ameacas dentro
        da MESMA janela temporal de precisao ja usada por
        `_try_player_hit` (`|delta| <= perfect_window`). Compara o
        angulo atual da mira contra `GameState.mouse_angle_previous`
        (gravado pelo `PlayerInputSystem` ANTES de recalcular a mira
        neste mesmo frame): se a VELOCIDADE angular do gesto
        (`|delta_angulo| / delta_time`, normalizada por frame pra nao
        depender de FPS) atingir `slash_min_angular_speed_rad_per_sec`
        E o arco varrido (de `mouse_angle_previous` ate a mira atual)
        cruzar o `spawn_angle_rad` da ameaca (teste de menor-caminho-
        com-sinal: `0 <= offset <= raw_delta` ou o inverso conforme o
        sinal do gesto), e PERFECT automatico com SFX de "swish". Uma
        ameaca de Lamina fora da janela de tempo, ou tocada por um
        gesto lento demais, simplesmente segue seu curso normal (MISS
        pela varredura generica, como qualquer outra).
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
        self._shot_sound_ids = tuple(shot_sound_ids)
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
        self._hold_grace_seconds = float(hold_grace_seconds)
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
        self._dash_action_name = dash_action_name
        self._spark_system = spark_system
        self._crosshair_entity_index = crosshair_entity_index
        self._spark_burst_count = int(spark_burst_count)
        self._transform_pool = memory_manager.get_pool("transform")
        self._miss_sound_id = miss_sound_id
        self._mirages_enabled = bool(mirages_enabled)
        self._mirage_vanish_seconds = float(mirage_vanish_seconds)
        self._vampirism_combo_threshold = int(vampirism_combo_threshold)
        self._vampirism_max_health = int(vampirism_max_health)
        self._center_x = float(center_xy[0])
        self._center_y = float(center_xy[1])
        self._phalanx_radius_tolerance = float(phalanx_radius_tolerance)
        self._phalanx_shield_arc_rad = float(phalanx_shield_arc_rad)
        self._core_pulse_seconds = float(core_pulse_seconds)
        self._focus_beam_enabled = bool(focus_beam_enabled)
        self._focus_tolerance_rad = float(focus_tolerance_rad)
        self._focus_radius_tolerance = float(focus_radius_tolerance)
        self._focus_target_seconds = float(focus_target_seconds)
        self._slash_enabled = bool(slash_enabled)
        self._slash_min_angular_speed_rad_per_sec = float(slash_min_angular_speed_rad_per_sec)
        self._slash_sound_id = slash_sound_id

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
        self._mirage_mask = np.zeros(capacity, dtype=bool)
        self._phalanx_pending_mask = np.zeros(capacity, dtype=bool)
        self._phalanx_radius_buffer = np.zeros(capacity, dtype=np.float64)
        self._phalanx_angle_buffer = np.zeros(capacity, dtype=np.float64)
        self._phalanx_block_mask = np.zeros(capacity, dtype=bool)
        self._focus_pending_mask = np.zeros(capacity, dtype=bool)
        self._focus_radius_buffer = np.zeros(capacity, dtype=np.float64)
        self._focus_angle_buffer = np.zeros(capacity, dtype=np.float64)
        self._focus_in_band_mask = np.zeros(capacity, dtype=bool)
        self._focus_in_cone_mask = np.zeros(capacity, dtype=bool)
        self._focus_aimed_mask = np.zeros(capacity, dtype=bool)
        self._focus_not_aimed_mask = np.zeros(capacity, dtype=bool)
        self._focus_resolved_mask = np.zeros(capacity, dtype=bool)
        self._slash_pending_mask = np.zeros(capacity, dtype=bool)
        self._slash_abs_delta_buffer = np.zeros(capacity, dtype=np.float64)
        self._slash_window_mask = np.zeros(capacity, dtype=bool)
        self._slash_offset_buffer = np.zeros(capacity, dtype=np.float64)
        self._slash_crossed_mask = np.zeros(capacity, dtype=bool)
        self._slash_scratch_mask = np.zeros(capacity, dtype=bool)

    def update(self, world: World, delta_time: float) -> None:
        """Executa o julgamento do frame: (1) varre MISSes vencidos,
        (2) se "fire" foi pressionado neste frame, tenta converter a
        melhor candidata em PERFECT/GOOD. `delta_time` e ignorado para
        decisoes ritmicas (a fonte de verdade e o `IAudioClock`) EXCETO
        pelo timer de graca do Hold Forgiveness (`_sweep_engaged_holds`)
        -- esse e "game feel" de tremor de mao, nao um evento ritmico,
        mesmo criterio dos timers de i-frame/cooldown do
        `PlayerInputSystem`.
        """
        # Developer Tools -- Auto-Play (Modo Deus): `bot_mode` substitui
        # o resto deste metodo por completo -- `_run_bot_mode` nunca lê
        # `PlayerInputSystem` (nem `fire`/mira), ver seu docstring.
        if self._game_state.bot_mode:
            self._run_bot_mode(world)
            return

        # Modo Falange: enquanto ativo, o tiro manual nao existe -- nem
        # sequer LEMOS "fire"/"fire_alt" (nenhum misfire, nenhuma troca
        # de forma do nucleo por cor). O bloqueio passivo roda mais
        # abaixo (`_run_phalanx_block_check`), depois das varreduras de
        # MISS/Hold/Mirage de sempre.
        phalanx_active = self._game_state.phalanx_mode

        player_row = self._player_pool.dense_row_of(self._player_entity_index)
        gun_jammed = float(self._player_pool.active_view()["gun_jam_sec"][player_row]) > 0.0

        triggered_polarities = []
        if not phalanx_active:
            # Sem Polaridade: um unico gatilho, sem cor. Com Polaridade:
            # os dois botoes (azul/rosa) sao checados nesta ordem fixa a
            # cada frame -- cada um e um disparo INDEPENDENTE contra a pool.
            fire_events = [(self._fire_action_name, POLARITY_BLUE)]
            if self._polarity_enabled:
                fire_events.append((self._fire_alt_action_name, POLARITY_PINK))

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

        if self._mirages_enabled:
            # Rogue-lite -- Ameacas Fantasmas: `is_mirage` tem seu
            # PROPRIO ciclo de vida (`_sweep_vanishing_mirages`), fora da
            # varredura generica de MISS -- mesma classe de exclusao de
            # refletidos/orbitais acima (senao um fantasma que passou do
            # tempo viraria MISS de verdade, o oposto do pedido).
            not_mirage = self._mirage_mask[:active_count]
            np.logical_not(threat_view["is_mirage"], out=not_mirage)
            np.logical_and(pending, not_mirage, out=pending)

        # NOTA -- Raio de Foco/Lamina (`is_focus_target`/`is_slash_target`)
        # NAO sao excluidos daqui de proposito, ao contrario de
        # fantasmas/refletidos/orbitais acima: os dois tem janela de
        # resolucao propria (banda de raio/velocidade de gesto) SEMPRE
        # mais estreita que a janela generica de miss, entao se o
        # tempo esgotar sem a condicao especial ser satisfeita a
        # varredura generica abaixo deve mesmo puni-los como MISS --
        # e o "afastar renuncia" natural da mecanica, nao um bug.
        # `_run_focus_beam_check`/`_run_slash_check` recalculam seu
        # PROPRIO pending a partir do `judgment` (mesmo idioma de
        # `_sweep_vanishing_mirages`/`_run_phalanx_block_check`) e por
        # isso nunca reprocessam uma linha que a varredura abaixo ja
        # resolveu neste mesmo frame.

        # Overload do Nucleo: Dash sobre uma batida VIVA (candidata
        # comum dentro da janela Good -- mesmo `pending` ja refinado
        # acima, entao exclui Holds engajados/refletidos/escudos) com a
        # Ressonancia de Polaridade CHEIA arma o `ShockwaveSystem`
        # (`GameState.consume_overdrive_for_overload` tambem zera a
        # corrente -- o "custo" do Overload). So testado quando
        # `polarity_enabled` (a Ressonancia nem existe sem Polaridade).
        if self._polarity_enabled and self._input_provider.is_action_pressed(self._dash_action_name):
            if self._game_state.in_overdrive:
                abs_deltas_for_beat = self._abs_delta_buffer[:active_count]
                np.abs(deltas, out=abs_deltas_for_beat)
                live_beat = self._duration_mask[:active_count]
                np.less_equal(abs_deltas_for_beat, self._good_window, out=live_beat)
                np.logical_and(live_beat, pending, out=live_beat)
                if np.any(live_beat):
                    self._game_state.consume_overdrive_for_overload()

        self._sweep_overdue_misses(world, threat_view, deltas, pending, active_count)
        if self._mirages_enabled:
            self._sweep_vanishing_mirages(world, threat_view, deltas, active_count)
        if self._hold_threat_type_id is not None:
            self._sweep_engaged_holds(world, threat_view, active_count, now_effective, delta_time)

        # Raio de Foco / Lamina: rodam TODO frame, independente do
        # Modo Falange -- os tres modificadores mudam o verbo do
        # jogador para AMEACAS DIFERENTES da mesma pool (nunca a
        # mesma linha, ver os `lane % 3`/exclusoes mutuas no spawner e
        # em `_run_phalanx_block_check`), entao nunca competem entre si.
        if self._focus_beam_enabled:
            self._run_focus_beam_check(world, threat_view, active_count, now_effective, delta_time)
        if self._slash_enabled:
            self._run_slash_check(world, threat_view, deltas, active_count, delta_time)

        if phalanx_active:
            self._run_phalanx_block_check(world, threat_view, active_count)
        else:
            for polarity in triggered_polarities:
                self._try_player_hit(world, threat_view, deltas, active_count, polarity)

    def _run_bot_mode(self, world: World) -> None:
        """Developer Tools -- Auto-Play (Modo Deus, `GameState.bot_mode`):
        ligado por F12 em `FLOW_PREFLIGHT`
        (`HertzGameLoop._advance_preflight`), pra facilitar teste de
        campanhas/geracao de beatmap sem precisar jogar manualmente.
        IGNORA por completo o `PlayerInputSystem` -- nenhuma leitura de
        `is_action_pressed`/mira acontece aqui. Toda ameaca PENDENTE
        deste juiz (Defensor) e resolvida como PERFECT no EXATO instante
        em que `agora_efetivo` entra na janela PERFECT dela
        (`delta <= perfect_window`), sem checar mira/cor/tipo -- uma
        ameaca ja atrasada (delta bem negativo) tambem satisfaz essa
        condicao, entao nada fica preso PENDING pra sempre mesmo se o
        modo for ligado com ameacas ja em voo.

        Escopo DELIBERADO de cheat, nao de mecanica real: Parry/Hold/
        Captura Orbital nao sao reproduzidos (nenhuma reflexao/
        sustentacao/orbita) -- toda ameaca especial e' so destruida como
        PERFECT comum, o suficiente pra validar o RITMO do beatmap sem
        replicar toda a fisica secundaria dessas mecanicas.

        ZERO-GC: reusa os MESMOS buffers pre-alocados no construtor
        (`_delta_buffer`/`_owned_mask`/`_scratch_mask`/`_engaged_mask`/
        `_heavy_mask`/`_orbiting_mask`/`_candidate_mask`) -- seguro
        porque este metodo SUBSTITUI o resto de `update()` pro frame
        inteiro (nunca roda ao lado do fluxo normal, sem conflito de
        uso concorrente). `np.flatnonzero` + laco escalar final sobre as
        poucas linhas prontas no frame: mesmo criterio ja aceito em
        `_sweep_overdue_misses`/`_register_piercing_kill` (o numero de
        candidatas simultaneas e tipicamente pequeno, vetorizar so'
        complicaria sem ganho real)."""
        active_count = self._threat_pool.count
        if active_count == 0:
            return

        now_effective = max(
            0.0, self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )
        threat_view = self._threat_pool.active_view()
        deltas = self._delta_buffer[:active_count]
        np.subtract(threat_view["target_hit_time_sec"], now_effective, out=deltas)

        # mesma exclusao de "pending" ja usada em `update()`: so ameacas
        # RADIAIS (owned), ainda nao engajadas/refletidas/orbitando.
        owned = self._owned_mask[:active_count]
        np.equal(threat_view["mode_tag"], MODE_TAG_DEFENDER, out=owned)

        pending = self._scratch_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=pending)
        np.logical_and(pending, owned, out=pending)

        not_engaged = self._engaged_mask[:active_count]
        np.logical_not(threat_view["is_hit"], out=not_engaged)
        np.logical_and(pending, not_engaged, out=pending)

        if self._heavy_threat_type_id is not None:
            not_reflected = self._heavy_mask[:active_count]
            np.logical_not(threat_view["is_reflected"], out=not_reflected)
            np.logical_and(pending, not_reflected, out=pending)

        if self._orbit_threat_type_id is not None:
            not_orbiting = self._orbiting_mask[:active_count]
            np.not_equal(threat_view["phase"], PHASE_ORBITING, out=not_orbiting)
            np.logical_and(pending, not_orbiting, out=pending)

        ready = self._candidate_mask[:active_count]
        np.less_equal(deltas, self._perfect_window, out=ready)
        np.logical_and(ready, pending, out=ready)

        rows = np.flatnonzero(ready)
        if rows.shape[0] == 0:
            return

        state = self._game_state
        for row in rows:
            row = int(row)
            threat_view["is_hit"][row] = True
            threat_view["judgment"][row] = JUDGMENT_PERFECT
            world.destroy_entity(int(threat_view["packed_handle"][row]))
            state.score += self._score_perfect
            state.perfect_count += 1
            state.combo_count += 1
            if state.combo_count > state.max_combo:
                state.max_combo = state.combo_count
        state.register_judgment_feedback(JUDGMENT_PERFECT, self._judgment_display_seconds)

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
        # Audio Ducking: o SFX de erro toca em volume MAXIMO -- e a
        # musica quem abaixa ao redor dele (`HertzGameLoop._sync_track_volume`),
        # nao o som de erro que precisa competir com ela.
        self._play(self._miss_sound_id, 1.0)

    def _sweep_vanishing_mirages(
        self,
        world: World,
        threat_view: np.ndarray,
        deltas: np.ndarray,
        active_count: int,
    ) -> None:
        """Rogue-lite -- Mind Games (Ameacas Fantasmas): destroi em
        SILENCIO toda ameaca `is_mirage` ainda pendente a
        `mirage_vanish_seconds` (ou menos) do impacto -- `JUDGMENT_DODGED`
        (nao pune, nao quebra combo, nao pontua) em vez do MISS que a
        varredura generica aplicaria a qualquer outra ameaca no mesmo
        instante. Recalcula `pending` do ZERO a partir de
        `threat_view["judgment"]` (em vez de reusar a mascara de
        `update()`, ja desatualizada apos `_sweep_overdue_misses` rodar)
        -- evita destruir a mesma linha duas vezes no mesmo frame."""
        vanishing = self._mirage_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=vanishing)
        np.logical_and(vanishing, threat_view["is_mirage"], out=vanishing)

        ready = self._scratch_mask[:active_count]
        np.less_equal(deltas, self._mirage_vanish_seconds, out=ready)
        np.logical_and(vanishing, ready, out=vanishing)

        vanishing_rows = np.flatnonzero(vanishing)
        if vanishing_rows.shape[0] == 0:
            return
        for row in vanishing_rows:
            row_int = int(row)
            threat_view["judgment"][row_int] = JUDGMENT_DODGED
            world.destroy_entity(int(threat_view["packed_handle"][row_int]))

    def _run_phalanx_block_check(
        self,
        world: World,
        threat_view: np.ndarray,
        active_count: int,
    ) -> None:
        """Modo Falange (Undyne): bloqueio PASSIVO continuo -- roda TODO
        frame que `GameState.phalanx_mode` estiver ativo, sem precisar de
        nenhum clique. Uma ameaca vira PERFECT automatico quando o RAIO
        atual (lido do `transform_pool`, distancia ate o centro -- nao o
        relogio) estiver a `phalanx_radius_tolerance` do anel de
        julgamento E o angulo (`spawn_angle_rad`, fixo desde o spawn --
        o voo radial e sempre puramente angular-constante) estiver
        dentro de `phalanx_shield_arc_rad` da mira atual.

        Recalcula `pending` do ZERO com a MESMA cadeia de exclusao do
        topo de `update()` (Holds engajados/refletidos/escudos
        orbitais/fantasmas continuam PENDING de proposito, cada um com
        seu proprio ciclo de vida) -- nunca reusa a mascara de la, ja
        desatualizada apos as varreduras de MISS/Hold/Mirage rodarem
        neste mesmo frame (mesmo motivo de `_sweep_vanishing_mirages`).
        """
        pending = self._phalanx_pending_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=pending)
        np.logical_and(pending, self._owned_mask[:active_count], out=pending)

        not_engaged = self._phalanx_block_mask[:active_count]
        np.logical_not(threat_view["is_hit"], out=not_engaged)
        np.logical_and(pending, not_engaged, out=pending)

        if self._heavy_threat_type_id is not None:
            not_reflected = self._phalanx_block_mask[:active_count]
            np.logical_not(threat_view["is_reflected"], out=not_reflected)
            np.logical_and(pending, not_reflected, out=pending)

        if self._orbit_threat_type_id is not None:
            not_orbiting = self._phalanx_block_mask[:active_count]
            np.not_equal(threat_view["phase"], PHASE_ORBITING, out=not_orbiting)
            np.logical_and(pending, not_orbiting, out=pending)

        if self._mirages_enabled:
            not_mirage = self._phalanx_block_mask[:active_count]
            np.logical_not(threat_view["is_mirage"], out=not_mirage)
            np.logical_and(pending, not_mirage, out=pending)

        if self._focus_beam_enabled:
            # Raio de Foco: uma linha `is_focus_target` so pode
            # resolver por `_run_focus_beam_check` -- o bloqueio
            # generico da Falange nao pode "roubar" o PERFECT dela so
            # por estar no raio/arco do escudo.
            not_focus = self._phalanx_block_mask[:active_count]
            np.logical_not(threat_view["is_focus_target"], out=not_focus)
            np.logical_and(pending, not_focus, out=pending)

        if self._slash_enabled:
            # A Lamina: mesma razao, `is_slash_target` so resolve por
            # `_run_slash_check` (arrasto fisico), nunca pelo bloqueio
            # passivo da Falange.
            not_slash = self._phalanx_block_mask[:active_count]
            np.logical_not(threat_view["is_slash_target"], out=not_slash)
            np.logical_and(pending, not_slash, out=pending)

        if not np.any(pending):
            return

        player_row = self._player_pool.dense_row_of(self._player_entity_index)
        aim_angle = float(self._player_pool.active_view()["aim_angle_rad"][player_row])

        entity_indices = self._threat_pool.active_entity_indices()
        transform_rows = self._transform_pool.dense_rows_of(entity_indices)
        transform_view = self._transform_pool.active_view()

        radius = self._phalanx_radius_buffer[:active_count]
        dx = transform_view["position_x"][transform_rows] - self._center_x
        dy = transform_view["position_y"][transform_rows] - self._center_y
        np.hypot(dx, dy, out=radius)
        np.subtract(radius, self._game_state.current_judgment_radius, out=radius)
        np.abs(radius, out=radius)
        in_band = self._candidate_mask[:active_count]
        np.less_equal(radius, self._phalanx_radius_tolerance, out=in_band)

        angles = self._phalanx_angle_buffer[:active_count]
        np.subtract(threat_view["spawn_angle_rad"], aim_angle, out=angles)
        np.add(angles, math.pi, out=angles)
        np.mod(angles, _TAU, out=angles)
        np.subtract(angles, math.pi, out=angles)
        np.abs(angles, out=angles)
        in_arc = self._pre_polarity_mask[:active_count]
        np.less_equal(angles, self._phalanx_shield_arc_rad, out=in_arc)

        blocked = self._phalanx_block_mask[:active_count]
        np.logical_and(in_band, in_arc, out=blocked)
        np.logical_and(blocked, pending, out=blocked)

        rows = np.flatnonzero(blocked)
        if rows.shape[0] == 0:
            return

        state = self._game_state
        for row in rows:
            row = int(row)
            threat_view["is_hit"][row] = True
            threat_view["judgment"][row] = JUDGMENT_PERFECT
            world.destroy_entity(int(threat_view["packed_handle"][row]))
            state.score += self._score_perfect
            state.perfect_count += 1
            state.combo_count += 1
            if state.combo_count > state.max_combo:
                state.max_combo = state.combo_count
            if self._vampirism_combo_threshold > 0:
                self._apply_vampirism_heal(state)
            self._emit_perfect_sparks()
        state.trigger_core_pulse(self._core_pulse_seconds)
        state.register_judgment_feedback(JUDGMENT_PERFECT, self._judgment_display_seconds)
        self._play(self._parry_sound_id, 1.0)

    def _run_focus_beam_check(
        self,
        world: World,
        threat_view: np.ndarray,
        active_count: int,
        now_effective: float,
        delta_time: float,
    ) -> None:
        """Raio de Foco (Microondas): bloqueio PASSIVO continuo, roda
        TODO frame que `focus_beam_enabled` estiver ligado -- sem
        precisar de clique. Recalcula `pending` do ZERO a partir de
        `threat_view["judgment"]` (mesmo motivo de
        `_sweep_vanishing_mirages`/`_run_phalanx_block_check`: nunca
        reusa a mascara do topo de `update()`, ja desatualizada apos
        `_sweep_overdue_misses` rodar neste mesmo frame).
        """
        pending = self._focus_pending_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=pending)
        np.logical_and(pending, threat_view["is_focus_target"], out=pending)
        if not np.any(pending):
            return

        entity_indices = self._threat_pool.active_entity_indices()
        transform_rows = self._transform_pool.dense_rows_of(entity_indices)
        transform_view = self._transform_pool.active_view()

        # Pulso visual continuo (+-10% de escala): escrito DIRETO no
        # transform, independente de estar sendo mirado -- o
        # `HBPygameRenderer` so desenha o hexagono no raio JA escalado
        # (ver comentario em `draw_batch`).
        pulse_scale = 1.0 + 0.1 * math.sin(now_effective * 6.0)
        pulsing_rows = transform_rows[pending]
        transform_view["scale_x"][pulsing_rows] = pulse_scale
        transform_view["scale_y"][pulsing_rows] = pulse_scale

        player_row = self._player_pool.dense_row_of(self._player_entity_index)
        aim_angle = float(self._player_pool.active_view()["aim_angle_rad"][player_row])

        angles = self._focus_angle_buffer[:active_count]
        np.subtract(threat_view["spawn_angle_rad"], aim_angle, out=angles)
        np.add(angles, math.pi, out=angles)
        np.mod(angles, _TAU, out=angles)
        np.subtract(angles, math.pi, out=angles)
        np.abs(angles, out=angles)
        in_cone = self._focus_in_cone_mask[:active_count]
        np.less_equal(angles, self._focus_tolerance_rad, out=in_cone)

        aimed = self._focus_aimed_mask[:active_count]
        np.logical_and(pending, in_cone, out=aimed)
        np.logical_not(in_cone, out=in_cone)  # agora "fora do cone"
        not_aimed = self._focus_not_aimed_mask[:active_count]
        np.logical_and(pending, in_cone, out=not_aimed)

        # Afastar a mira ANTES da ameaca "morrer" reseta pro maximo
        # INSTANTANEAMENTE (punicao maxima); sustentar decrementa
        # `delta_time` -- mesmo idioma de escrita in-place por mascara
        # booleana ja usado pela Tolerancia Organica do Hold
        # (`grace_timer[broken] += delta_time`).
        focus_health = threat_view["focus_health"]
        focus_health[not_aimed] = self._focus_target_seconds
        focus_health[aimed] -= delta_time

        radius = self._focus_radius_buffer[:active_count]
        dx = transform_view["position_x"][transform_rows] - self._center_x
        dy = transform_view["position_y"][transform_rows] - self._center_y
        np.hypot(dx, dy, out=radius)
        np.subtract(radius, self._game_state.current_judgment_radius, out=radius)
        np.abs(radius, out=radius)
        in_band = self._focus_in_band_mask[:active_count]
        np.less_equal(radius, self._focus_radius_tolerance, out=in_band)

        depleted = self._focus_resolved_mask[:active_count]
        np.less_equal(focus_health, 0.0, out=depleted)
        np.logical_and(depleted, aimed, out=depleted)
        np.logical_and(depleted, in_band, out=depleted)

        rows = np.flatnonzero(depleted)
        if rows.shape[0] == 0:
            return

        state = self._game_state
        for row in rows:
            row = int(row)
            threat_view["is_hit"][row] = True
            threat_view["judgment"][row] = JUDGMENT_PERFECT
            world.destroy_entity(int(threat_view["packed_handle"][row]))
            state.score += self._score_perfect
            state.perfect_count += 1
            state.combo_count += 1
            if state.combo_count > state.max_combo:
                state.max_combo = state.combo_count
            if self._vampirism_combo_threshold > 0:
                self._apply_vampirism_heal(state)
            self._emit_perfect_sparks()
        state.register_judgment_feedback(JUDGMENT_PERFECT, self._judgment_display_seconds)

    def _run_slash_check(
        self,
        world: World,
        threat_view: np.ndarray,
        deltas: np.ndarray,
        active_count: int,
        delta_time: float,
    ) -> None:
        """A Lamina (Radial Slash): ignora POR COMPLETO
        `is_action_pressed` -- so considera um ARRASTO fisico rapido
        cujo arco varrido (de `GameState.mouse_angle_previous` ate a
        mira atual) cruze o angulo de uma ameaca `is_slash_target`
        dentro da MESMA janela de precisao usada por
        `_try_player_hit` (`|delta| <= perfect_window`).
        """
        pending = self._slash_pending_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=pending)
        np.logical_and(pending, threat_view["is_slash_target"], out=pending)
        if not np.any(pending):
            return

        abs_deltas = self._slash_abs_delta_buffer[:active_count]
        np.abs(deltas, out=abs_deltas)
        window = self._slash_window_mask[:active_count]
        np.less_equal(abs_deltas, self._perfect_window, out=window)
        np.logical_and(window, pending, out=window)
        if not np.any(window):
            return

        player_row = self._player_pool.dense_row_of(self._player_entity_index)
        current_angle = float(self._player_pool.active_view()["aim_angle_rad"][player_row])
        previous_angle = float(self._game_state.mouse_angle_previous)

        # Velocidade angular do gesto normalizada por `delta_time` --
        # de proposito, NAO a diferenca bruta pedida ao pe da letra,
        # pra a deteccao do golpe nao depender do FPS.
        raw_delta = current_angle - previous_angle
        raw_delta = (raw_delta + math.pi) % _TAU - math.pi
        angular_speed = abs(raw_delta) / delta_time if delta_time > 0.0 else 0.0
        if angular_speed < self._slash_min_angular_speed_rad_per_sec:
            return

        # Teste de cruzamento por menor-caminho-com-sinal: o arco
        # varrido cruza o angulo da ameaca sse `offset` (angulo da
        # ameaca relativo a mira ANTERIOR) estiver entre 0 e
        # `raw_delta`, inclusive -- o sentido da comparacao inverte
        # conforme o sinal do gesto.
        offset = self._slash_offset_buffer[:active_count]
        np.subtract(threat_view["spawn_angle_rad"], previous_angle, out=offset)
        np.add(offset, math.pi, out=offset)
        np.mod(offset, _TAU, out=offset)
        np.subtract(offset, math.pi, out=offset)

        crossed = self._slash_crossed_mask[:active_count]
        scratch = self._slash_scratch_mask[:active_count]
        if raw_delta >= 0.0:
            np.greater_equal(offset, 0.0, out=crossed)
            np.less_equal(offset, raw_delta, out=scratch)
        else:
            np.less_equal(offset, 0.0, out=crossed)
            np.greater_equal(offset, raw_delta, out=scratch)
        np.logical_and(crossed, scratch, out=crossed)
        np.logical_and(crossed, window, out=crossed)

        rows = np.flatnonzero(crossed)
        if rows.shape[0] == 0:
            return

        state = self._game_state
        for row in rows:
            row = int(row)
            threat_view["is_hit"][row] = True
            threat_view["judgment"][row] = JUDGMENT_PERFECT
            world.destroy_entity(int(threat_view["packed_handle"][row]))
            state.score += self._score_perfect
            state.perfect_count += 1
            state.combo_count += 1
            if state.combo_count > state.max_combo:
                state.max_combo = state.combo_count
            if self._vampirism_combo_threshold > 0:
                self._apply_vampirism_heal(state)
            self._emit_perfect_sparks()
        state.register_judgment_feedback(JUDGMENT_PERFECT, self._judgment_display_seconds)
        self._play(self._slash_sound_id, 1.0)

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

    def _shot_sound_for_combo(self, combo_count: int):
        """Combo Pitch Shift (truque Zero-GC): `shot_sound_ids` e uma
        tupla de N variantes PRE-SINTETIZADAS do canhao (cada uma um
        semitom mais aguda -- `sfx_synth.py`), nunca um pitch-shift em
        tempo real (`pygame.mixer` nao suporta). So a ESCOLHA de qual
        arquivo tocar muda por aritmetica: a cada 10 de combo, sobe uma
        variante, ate a ultima (a mais aguda)."""
        if not self._shot_sound_ids:
            return None
        index = min(combo_count // 10, len(self._shot_sound_ids) - 1)
        return self._shot_sound_ids[index]

    def _emit_perfect_sparks(self) -> None:
        """Juice Visual -- Sparks: rajada na posicao ATUAL da mira, so
        quando `spark_system` foi injetado (opt-in, mesma filosofia
        graciosa do resto do arquivo -- sem ele, um no-op)."""
        if self._spark_system is None:
            return
        row = self._transform_pool.dense_row_of(self._crosshair_entity_index)
        view = self._transform_pool.active_view()
        x = float(view["position_x"][row])
        y = float(view["position_y"][row])
        self._spark_system.emit_burst(x, y, self._spark_burst_count)

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

        if self._focus_beam_enabled or self._slash_enabled:
            # Raio de Foco / Lamina: nenhum dos dois aceita clique --
            # "o jogador nao clica" / "ignora inputs de botao", so
            # resolvem por `_run_focus_beam_check`/`_run_slash_check`.
            # Reusa `_scratch_mask` (o antigo `pending` acima ja foi
            # incorporado a `candidates`, nao e mais lido).
            not_special_input = self._scratch_mask[:active_count]
            np.logical_or(threat_view["is_focus_target"], threat_view["is_slash_target"], out=not_special_input)
            np.logical_not(not_special_input, out=not_special_input)
            np.logical_and(candidates, not_special_input, out=candidates)

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

        # Rogue-lite -- Ameacas Fantasmas: um "fantasma" e sempre MISS
        # ao ser atingido ANTES de desaparecer sozinho (ver
        # `_sweep_vanishing_mirages`) -- checado ANTES de Hold/Parry/
        # Captura Orbital por construcao (um fantasma nunca deveria
        # coexistir com essas mecanicas, mas a ordem fixa evita
        # ambiguidade caso uma fase combine os modifiers por engano).
        if bool(threat_view["is_mirage"][best_row]):
            self._resolve_mirage_miss(world, threat_view, best_row)
            return

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
        if judgment == JUDGMENT_PERFECT and self._vampirism_combo_threshold > 0:
            self._apply_vampirism_heal(state)
        state.register_judgment_feedback(judgment, self._judgment_display_seconds)
        # Acessibilidade -- Hit-Error Meter/Histograma: delta ASSINADO
        # na convencao "atual - esperado" (negativo=cedo, positivo=tarde)
        # -- `deltas` guarda o INVERSO (`target_hit_time_sec - agora`,
        # ver `update()`), entao negativa aqui antes de gravar.
        state.record_hit_delta(-float(deltas[best_row]))

        # Gun Sync + Combo Pitch Shift: o canhao do tiro certeiro E
        # percussao da trilha -- a variante tocada sobe de semitom a cada
        # 10 de combo (ate a mais aguda), so escolhendo QUAL arquivo ja
        # sintetizado tocar (zero custo de pitch-shift em runtime).
        self._play(self._shot_sound_for_combo(state.combo_count), 0.9)
        if self._polarity_enabled:
            self._register_resonance(int(threat_view["polarity_id"][best_row]))
        if judgment == JUDGMENT_PERFECT:
            self._emit_perfect_sparks()

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
        if self._vampirism_combo_threshold > 0:
            self._apply_vampirism_heal(state)
        state.register_judgment_feedback(JUDGMENT_PERFECT, self._judgment_display_seconds)
        if self._hitlag_freeze_frames > 0:
            state.trigger_hitlag(self._hitlag_freeze_frames)
        self._emit_perfect_sparks()

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
                self._emit_perfect_sparks()
            else:
                state.score += self._score_good
                state.good_count += 1
            state.combo_count += 1
            if state.combo_count > state.max_combo:
                state.max_combo = state.combo_count
            if judgment == JUDGMENT_PERFECT and self._vampirism_combo_threshold > 0:
                self._apply_vampirism_heal(state)

        # Gun Sync + Combo Pitch Shift: UM tiro so, mas ja refletindo o
        # combo FINAL apos abater o grupo inteiro (ver `_shot_sound_for_combo`).
        self._play(self._shot_sound_for_combo(state.combo_count), 0.9)
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
        campo `phase` ja existente, sem precisar de um campo novo).
        `spawn_angle_rad` (so telemetria ate a captura) vira o OFFSET
        ANGULAR FIXO da orbita a partir deste instante."""
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
        if self._vampirism_combo_threshold > 0:
            self._apply_vampirism_heal(state)
        state.register_judgment_feedback(JUDGMENT_PERFECT, self._judgment_display_seconds)
        if self._hitlag_freeze_frames > 0:
            state.trigger_hitlag(self._hitlag_freeze_frames)
        self._emit_perfect_sparks()

    def _register_hold_engage(self, threat_view: np.ndarray, best_row: int) -> None:
        """Notas Longas -- Fase 1 (Start): a candidata vencedora NAO e
        destruida. Zera sua velocidade (para junto ao anel em vez de
        atravessar) e DESARMA sua colisao com o nucleo
        (`collision_layer/mask = 0`) -- assim o `CoreDamageSystem` nunca
        a ve enquanto ela estiver sustentada, sem precisar tocar naquele
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
        delta_time: float,
    ) -> None:
        """Notas Longas -- Fase 2 (Sustain), vetorizada sobre TODAS as
        linhas engajadas (tipicamente 0-1 por vez, mas nao ha razao para
        um laco escalar): uma linha completa com sucesso quando
        `agora_efetivo >= target_hit_time_sec + duration_sec`. `fire_held`/
        `aim_angle` sao leituras ESCALARES (um unico gatilho, uma unica
        mira) comparadas contra TODAS as linhas engajadas de uma vez via
        `out=`.

        TOLERANCIA ORGANICA -- HOLD FORGIVENESS: `fire` solto OU mira
        fora de `hold_aim_tolerance_rad` ("quebrado" neste frame) NAO e
        mais MISS instantaneo -- acumula `delta_time` em
        `hold_grace_timer_sec` (Coyote Time); retomar a sustentacao
        correta zera o timer da linha. So vira MISS de verdade
        (`_resolve_hold_break`) quando o timer ultrapassa
        `hold_grace_seconds` SEM ter sido zerado antes -- humanos nao
        conseguem manter mira+gatilho perfeitamente estaticos por
        segundos continuos.
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

        # Hold Forgiveness: linhas "quebradas" neste frame acumulam
        # delta_time no timer de graca; linhas engajadas que retomaram a
        # sustentacao correta (engaged AND NOT broken) zeram o timer --
        # ambas fatiadas do MESMO array de trabalho (`grace_timer`), a
        # escrita por mascara booleana e in-place (mesmo idioma ja usado
        # por `window[is_special] = ...`/`selection[rejected] = np.inf`).
        grace_timer = threat_view["hold_grace_timer_sec"]
        still_holding = self._scratch_mask[:active_count]
        np.logical_and(engaged, np.logical_not(broken), out=still_holding)
        grace_timer[still_holding] = 0.0
        grace_timer[broken] += delta_time

        past_grace = self._duration_mask[:active_count]
        np.greater(grace_timer, self._hold_grace_seconds, out=past_grace)
        np.logical_and(past_grace, broken, out=past_grace)

        for row in np.flatnonzero(completed):
            self._resolve_hold_success(world, threat_view, int(row))
        for row in np.flatnonzero(past_grace):
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
        if self._vampirism_combo_threshold > 0:
            self._apply_vampirism_heal(state)
        state.register_judgment_feedback(JUDGMENT_PERFECT, self._judgment_display_seconds)
        self._emit_perfect_sparks()

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

    def _apply_vampirism_heal(self, state: GameState) -> None:
        """Rogue-lite -- Perk Vampirismo: a cada `vampirism_combo_threshold`
        acertos PERFEITOS consecutivos (o combo zera em qualquer MISS,
        entao e sempre uma sequencia CONTINUA), cura 1 de vida --
        checado por CRUZAMENTO de multiplo (resto, nao divisao), pra
        nunca curar duas vezes seguidas no mesmo combo. Respeita
        `vampirism_max_health` quando fornecido (`0` = sem teto)."""
        if state.combo_count % self._vampirism_combo_threshold != 0:
            return
        if self._vampirism_max_health > 0 and state.health >= self._vampirism_max_health:
            return
        state.health += 1

    def _resolve_mirage_miss(self, world: World, threat_view: np.ndarray, row: int) -> None:
        """Rogue-lite -- Ameacas Fantasmas: acertar um "fantasma" ANTES
        dele desaparecer sozinho (`_sweep_vanishing_mirages`) e sempre
        MISS -- e um alvo falso, nunca pode ser destruido de verdade
        mesmo com timing+mira perfeitos."""
        threat_view["judgment"][row] = JUDGMENT_MISS
        world.destroy_entity(int(threat_view["packed_handle"][row]))

        state = self._game_state
        state.miss_count += 1
        state.combo_count = 0
        state.register_judgment_feedback(JUDGMENT_MISS, self._judgment_display_seconds)
        self._play(self._miss_sound_id, 1.0)
