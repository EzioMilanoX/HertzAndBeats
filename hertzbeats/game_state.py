"""Placar global da partida: o equivalente das "variaveis globais no World" da arquitetura."""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from hertzbeats.components.schemas import JUDGMENT_PENDING
from hertzbeats.rogue_lite import RogueRunState

RANK_ORDER = ("SS", "S", "A", "B", "C", "D")

HIT_ERROR_BUFFER_CAPACITY = 512
"""Acessibilidade -- Hit-Error Meter/Histograma de Resultados: quantos
deltas de acerto (PERFECT/GOOD, segundos assinados -- negativo=cedo,
positivo=tarde) ficam guardados por partida, num RingBuffer de tamanho
FIXO (`GameState.record_hit_delta`) -- generoso o bastante pra cobrir
qualquer fase curada do repositorio (107-180 notas) inteira; musicas do
jogador MUITO longas guardam so os ULTIMOS `HIT_ERROR_BUFFER_CAPACITY`
acertos (mesmo criterio de saturacao ja usado pelo Ghost Trail/SparkPool)."""
"""Ordem de exibicao (melhor -> pior) -- MESMA ordem usada por
`texture_bank.py` para registrar `rank_{letra}` uma unica vez no
carregamento."""


def compute_rank(perfect_count: int, good_count: int, miss_count: int) -> str:
    """Meta-Jogo -- Ranks: `SS` exige 100% PERFECT (nenhum GOOD, nenhum
    MISS); os demais usam a PRECISAO ponderada
    `(PERFECT + GOOD*0.5) / total` (um GOOD vale meio PERFECT, um MISS
    nao vale nada). Pura e sem estado -- so aritmetica sobre os 3
    contadores ja existentes em `GameState`, calculada UMA vez ao entrar
    em FLOW_RESULTS (`HertzGameLoop`), nunca por frame. `"-"` e o unico
    veredito possivel quando a fase termina sem nenhuma nota resolvida
    (`total == 0` -- ex.: uma fase vazia)."""
    total = perfect_count + good_count + miss_count
    if total == 0:
        return "-"
    if miss_count == 0 and good_count == 0 and perfect_count > 0:
        return "SS"
    precision = (perfect_count + good_count * 0.5) / total
    if precision > 0.95:
        return "S"
    if precision > 0.85:
        return "A"
    if precision > 0.70:
        return "B"
    if precision > 0.50:
        return "C"
    return "D"


RESULTS_HISTOGRAM_BIN_COUNT = 11
RESULTS_HISTOGRAM_RANGE_SECONDS = 0.15
"""Acessibilidade -- Histograma de Resultados: MESMA escala do Hit-Error
Meter ao vivo (`_HIT_ERROR_METER_RANGE_SECONDS`) -- 11 barras (numero
IMPAR: a do meio e sempre "quase no tempo exato") cobrindo -150ms a
+150ms, o resto da distribuicao satura nas pontas."""


def compute_hit_error_histogram(hit_delta_buffer: np.ndarray, filled_count: int) -> tuple:
    """Acessibilidade -- Histograma de Resultados: conta quantos PERFECT/
    GOOD desta partida caem em cada uma das `RESULTS_HISTOGRAM_BIN_COUNT`
    faixas de tempo -- pura, chamada UMA vez na transicao pra
    `FLOW_RESULTS` (nunca por frame), sobre o MESMO RingBuffer que
    alimenta o Hit-Error Meter ao vivo. `filled_count == 0` (fase sem
    nenhum PERFECT/GOOD, ex.: so MISS) devolve todas as faixas zeradas."""
    if filled_count <= 0:
        return (0,) * RESULTS_HISTOGRAM_BIN_COUNT
    deltas = hit_delta_buffer[:filled_count]
    clamped = np.clip(deltas, -RESULTS_HISTOGRAM_RANGE_SECONDS, RESULTS_HISTOGRAM_RANGE_SECONDS)
    counts, _ = np.histogram(
        clamped, bins=RESULTS_HISTOGRAM_BIN_COUNT,
        range=(-RESULTS_HISTOGRAM_RANGE_SECONDS, RESULTS_HISTOGRAM_RANGE_SECONDS),
    )
    return tuple(int(c) for c in counts)


class GameState:
    """
    Placar/estado global da partida, alocado UMA UNICA VEZ na composicao
    e injetado nos sistemas que leem/escrevem pontuacao
    (`JudgmentSystem`, `CoreDamageSystem`, `UIRenderSystem`).

    O `World` da engine e agnostico de produto e nao possui campos de
    placar; este objeto cumpre o papel de "variaveis globais de
    pontuacao no World" da arquitetura sem tocar o nucleo. Mutar
    atributos primitivos de uma instancia pre-alocada e Zero-GC pelo
    mesmo criterio dos contadores internos da engine (ex.:
    `World._pending_destroy_count`).
    """

    __slots__ = (
        "score",
        "combo_count",
        "max_combo",
        "perfect_count",
        "good_count",
        "miss_count",
        "dodge_count",
        "misfire_count",
        "health",
        "last_judgment",
        "judgment_display_seconds_left",
        "parry_count",
        "deflect_count",
        "shake_intensity",
        "shield_charges",
        "blindness_timer_sec",
        "lane_stutter_offset_y",
        "orbit_capture_count",
        "resonance_color",
        "resonance_chain",
        "resonance_overdrive_threshold",
        "visual_freeze_frames",
        "invert_colors",
        "current_judgment_radius",
        "overload_requested",
        "tunnel_radius",
        "bpm",
        "current_palette",
        "hit_delta_buffer",
        "hit_delta_write_index",
        "hit_delta_filled_count",
        "bot_mode",
        "rogue_run",
    )

    def __init__(
        self,
        max_health: int,
        shield_charges: int = 0,
        resonance_chain_threshold: int = 10,
        judgment_radius: float = 0.0,
        tunnel_radius: float = 0.0,
        bpm: float = 120.0,
        current_palette: Tuple[int, int, int] = (255, 255, 255),
    ) -> None:
        self.score: int = 0
        self.combo_count: int = 0
        self.max_combo: int = 0
        self.perfect_count: int = 0
        self.good_count: int = 0
        self.miss_count: int = 0
        self.dodge_count: int = 0
        self.misfire_count: int = 0
        self.health: int = max_health
        self.last_judgment: int = JUDGMENT_PENDING
        self.judgment_display_seconds_left: float = 0.0
        self.parry_count: int = 0
        """Defensor (Polaridade): ameacas pesadas refletidas com sucesso
        no PERFECT."""
        self.deflect_count: int = 0
        """Defensor (Polaridade): tiros no tempo certo mas na cor
        errada -- nao pune, so nao acerta."""
        self.shake_intensity: float = 0.0
        """Tremor de tela ATUAL, em pixels de deslocamento maximo --
        a "variavel global de camera" que o `CameraShakeSystem` decai a
        cada frame (`HertzConfig.shake_decay_per_second`) e que o
        `HertzGameLoop` le a cada frame para transformar num
        offset aleatorio real via `IRenderer.set_camera_offset` (metodo
        JA EXISTENTE na engine, ROADMAP M1/M2 -- nao inventamos um novo).
        Qualquer sistema pode chamar `trigger_shake(...)`; NUNCA e
        escrito diretamente (sempre por esse metodo, que decide o
        criterio de sobreposicao de tremores concorrentes)."""
        self.shield_charges: int = int(shield_charges)
        """Arcade 4K -- Notas Longas classicas (opt-in via "holds" em `active_modifiers`):
        quantas vezes o jogador pode QUEBRAR um Hold antes que passe a
        custar vida de verdade (o Arcade normalmente nao tira vida).
        Inicializado por `_compose_lanes_mode` a partir de
        `HertzConfig.lane_shield_max_charges`; `0` nos demais modos
        (nunca lido/decrementado la)."""
        self.blindness_timer_sec: float = 0.0
        """Vignette Flash ("Cegueira Ritmica", Arcade 4K -- Bombas):
        segundos restantes com a arena coberta por um overlay escuro
        com um buraco focado na linha de julgamento. Decai a cada frame
        (mesmo `CameraShakeSystem`/`shake_intensity`); o
        `HBPygameRenderer` so desenha o overlay enquanto `> 0`."""
        self.lane_stutter_offset_y: float = 0.0
        """Stutter Scroll (Arcade 4K, opt-in `stutter_scroll_enabled`):
        ruido visual ATUAL em Y (pixels), escrito todo frame pelo
        `VisualModifierSystem` (`sin(now_seconds * freq) * amplitude`).
        Lido pelo `HertzGameLoop._render_frame` (overrescrito) para
        deslocar so a POSICAO RENDERIZADA das notas do Arcade 4K no
        momento do `draw_batch` -- `transform.position_y` (a fisica
        REAL, que o `LaneJudgmentSystem`/`PhysicsSystem` usam) nunca e
        tocado, entao nao ha deriva acumulada frame a frame."""
        self.orbit_capture_count: int = 0
        """Defensor (Captura Orbital): quantos Escudos Rotativos o
        jogador ja capturou na partida -- telemetria/HUD, espelha
        `parry_count`/`deflect_count`."""
        self.resonance_color: int = -1
        """Defensor (Ressonancia de Polaridade): a cor (`POLARITY_BLUE`/
        `POLARITY_PINK`) da corrente MONOCROMATICA atual. `-1` (nenhuma
        cor valida) e o estado inicial "sem corrente" -- o primeiro
        acerto de qualquer cor sempre inicia uma corrente nova, nunca
        casa por acidente com `POLARITY_BLUE == 0`."""
        self.resonance_chain: int = 0
        """Defensor (Ressonancia de Polaridade): ameacas comuns
        destruidas em sequencia com a MESMA `resonance_color`. Destruir
        uma ameaca de cor DIFERENTE reinicia a corrente em 1 (nao soma) --
        ver `JudgmentSystem._register_resonance`."""
        self.resonance_overdrive_threshold: int = int(resonance_chain_threshold)
        """Defensor (Ressonancia de Polaridade): tamanho da corrente que
        liga o Overdrive daquela cor (`in_overdrive`). Guardado aqui (nao
        so em `HertzConfig`) para que a property `in_overdrive` seja
        auto-suficiente, mesmo criterio de `shield_charges` guardar o
        valor de config resolvido na composicao."""
        self.visual_freeze_frames: int = 0
        """Juice de Parry (Hitlag Visual Simulado): quadros de
        RENDERIZACAO restantes com o `draw_batch` suspenso (repete o
        ultimo frame desenhado) -- decaido por `CameraShakeSystem`
        (`-1` por `update`, nunca por `delta_time`: e uma contagem de
        QUADROS, nao de segundos). O `IAudioClock`/`world.step` NUNCA
        param por causa disso -- so a APRESENTACAO congela, exatamente
        a garantia que esta tarefa exige."""
        self.invert_colors: bool = False
        """Juice de Parry: pedido de flash de cor invertida, consumido
        UMA UNICA VEZ pelo `HertzGameLoop._sync_hitlag` no exato frame
        em que `visual_freeze_frames` volta a 0 ("quando a tela volta") --
        nunca lido/escrito por nenhum `ISystem`, mesma familia de
        `is_blinded`/`set_blindness_active`."""
        self.current_judgment_radius: float = float(judgment_radius)
        """Defensor: raio (px) do anel onde o hit e esperado -- FIXO
        desde a composicao (nucleo + meio-tamanho da ameaca comum), NUNCA
        mutado por nenhum sistema depois disso. `RadialRhythmSpawnerSystem`
        o le no SPAWN de cada nova ameaca (calculo de velocidade),
        `PlayerInputSystem` o le TODO frame (orbita da mira) e o
        `HertzGameLoop` o publica no `HBPygameRenderer`
        (`_sync_defender_playfield`) para o anel desenhado.

        Historico (Tolerancia Organica): ja existiu um "Colapso do Anel
        de Julgamento" que MUTAVA este valor em tempo real via beatmap
        -- foi revertido porque mudar o raio FISICO no meio da fase
        quebra a velocidade ja calculada das ameacas em voo (calculada
        UMA vez no spawn contra o raio do instante). Ver `tunnel_radius`
        para o substituto puramente COSMETICO (Colapso de Visao)."""
        self.overload_requested: bool = False
        """Defensor -- Overload do Nucleo: pedido de UM frame para o
        `ShockwaveSystem` disparar o proximo slot do seu pool fixo,
        consumido (resetado a `False`) pelo proprio `ShockwaveSystem` no
        frame em que age -- mesmo padrao pull-based de
        `invert_colors`/`is_blinded`, nunca lido por mais de um
        sistema."""
        self.tunnel_radius: float = float(tunnel_radius)
        """Defensor -- Colapso de Visao ("vision_tunnel", Tolerancia
        Organica): raio (px) do campo de luz PURAMENTE COSMETICO ao
        redor do nucleo -- fora dele, o `HBPygameRenderer` cobre a arena
        com um overlay preto, escondendo o spawn de ameacas ate entrarem
        no circulo iluminado. MUTAVEL (o valor de composicao, a
        diagonal centro->canto da janela, e so o ponto de partida "campo
        totalmente aberto"): o `VisionTunnelSystem` o interpola conforme
        os eventos `vision_tunnel` do beatmap. Nenhuma FISICA/velocidade
        le este campo -- ao contrario do extinto Colapso do Anel de
        Julgamento (ver `current_judgment_radius`), encolher a visao
        nunca quebra o calculo ja feito de nenhuma ameaca em voo."""
        self.bpm: float = float(bpm)
        """Heartbeat (Juice Visual): BPM do beatmap da fase ATUAL, lido
        uma unica vez na composicao (`_read_beatmap_bpm`) -- FIXO pelo
        resto da partida, nunca mutado por nenhum sistema. O
        `HertzGameLoop` deriva `beat_phase` dele (`now_seconds %
        (60/bpm) / (60/bpm)`) para pulsar o Anel de Julgamento/pistas e
        o Metronomo Periferico -- puramente cosmetico, nenhum julgamento
        le este campo."""
        self.current_palette: Tuple[int, int, int] = tuple(current_palette)
        """Estetica Reativa (Paleta Dinamica): cor RGB media da miniatura
        do video em exibicao (`pygame.transform.average_color`,
        calculada UMA vez ao cachear a miniatura no Carrossel -- nunca
        por frame), ou `(255, 255, 255)` (neutro -- multiplicar por
        branco nao muda nada) pra fases SEM miniatura (todo o repositorio
        hoje). `HBPygameRenderer.apply_palette_tint`/o anel de julgamento
        e os digitos NEUTROS do HUD (`UIRenderSystem`) adotam esta cor
        como tint base -- FIXA desde a composicao, nunca mutada por
        nenhum sistema depois disso (mesmo criterio de `bpm`)."""
        self.hit_delta_buffer: np.ndarray = np.zeros(HIT_ERROR_BUFFER_CAPACITY, dtype=np.float64)
        self.hit_delta_write_index: int = 0
        self.hit_delta_filled_count: int = 0
        """Acessibilidade -- Hit-Error Meter/Histograma: RingBuffer de
        tamanho FIXO (nunca alocado por acerto) com os deltas assinados
        de cada PERFECT/GOOD -- `record_hit_delta` e' o UNICO jeito de
        escrever nele (mesmo criterio de `trigger_shake`)."""
        self.bot_mode: bool = False
        """Developer Tools -- Auto-Play (Modo Deus): quando `True`,
        `JudgmentSystem` ignora por completo o `PlayerInputSystem` e
        resolve toda ameaca do Defensor como PERFECT assim que o tempo
        entra na janela PERFECT dela (ver `JudgmentSystem._run_bot_mode`).
        Ligado por F12 em `FLOW_PREFLIGHT`
        (`HertzGameLoop._advance_preflight`) -- o TOGGLE em si vive em
        `HertzGameLoop._bot_mode_enabled` (sobrevive a troca de
        `GameState` entre fases) e e' copiado pra ca em `_start_stage`,
        no instante exato da composicao; nenhum sistema ESCREVE este
        campo depois disso, so' le."""
        self.rogue_run: Optional[RogueRunState] = None
        """Rogue-lite Endgame: `None` fora de uma corrida. Quando ativa,
        `HertzGameLoop._rogue_run` (a MESMA instancia -- nunca uma copia
        nova, ver `RogueRunState`) e injetada aqui em `_compose_stage`,
        junto com `health` inicializado a partir de `rogue_run.health`
        (clampado ao `max_health` da fase nova, mesmo criterio ja usado
        pela vida carregada do Ironman -- `_ironman_carried_health`).
        Nenhum sistema LE este campo hoje (os Perks resolvidos em
        `rogue_run.perks` ja chegam em `JudgmentSystem`/`HertzConfig`
        como multiplicadores/limiares primitivos na composicao, nunca
        checados por string em tempo real) -- guardado aqui so para
        UI/telemetria (ex.: HUD do Rogue-lite mostrar o nivel da
        corrida). `HertzGameLoop` sincroniza `health` de volta pra
        `rogue_run.health` ao fim de cada fase (vitoria ou derrota),
        nunca no meio dela."""

    def record_hit_delta(self, delta_seconds: float) -> None:
        """Acessibilidade -- Hit-Error Meter/Histograma de Resultados:
        grava o delta ASSINADO (negativo=cedo, positivo=tarde) de UM
        PERFECT/GOOD no RingBuffer -- chamado por `JudgmentSystem`/
        `LaneJudgmentSystem`/`ScratchJudgmentSystem` no exato instante em
        que o julgamento e decidido, nunca recalculado depois."""
        self.hit_delta_buffer[self.hit_delta_write_index] = float(delta_seconds)
        self.hit_delta_write_index = (self.hit_delta_write_index + 1) % HIT_ERROR_BUFFER_CAPACITY
        self.hit_delta_filled_count = min(self.hit_delta_filled_count + 1, HIT_ERROR_BUFFER_CAPACITY)

    def consume_overdrive_for_overload(self) -> None:
        """Defensor -- Overload do Nucleo: o `JudgmentSystem` chama isto
        ao detectar Dash+batida viva com a Ressonancia CHEIA (`in_overdrive`)
        -- arma o pedido de Shockwave E zera a corrente de Ressonancia
        (`resonance_chain`/`resonance_color`) na MESMA chamada, como o
        "custo" de ativar o Overload (a barra se esvazia ao ser gasta,
        nao continua cheia)."""
        self.overload_requested = True
        self.resonance_chain = 0
        self.resonance_color = -1

    @property
    def is_blinded(self) -> bool:
        """True enquanto o Vignette Flash estiver ativo."""
        return self.blindness_timer_sec > 0.0

    def trigger_blindness(self, seconds: float) -> None:
        """Aciona/reforca a Cegueira Ritmica. Mesmo criterio de
        `trigger_shake`: usa `max()`, nao soma -- duas bombas seguidas
        nao empilham um tempo de cegueira absurdo."""
        self.blindness_timer_sec = max(self.blindness_timer_sec, float(seconds))

    @property
    def in_overdrive(self) -> bool:
        """Defensor (Ressonancia de Polaridade): True quando a corrente
        MONOCROMATICA atual atingiu o limiar de Overdrive -- disparos
        comuns de `resonance_color` viram "perfurantes" (abatem TODAS
        as candidatas validas do frame, nao so a melhor -- ver
        `JudgmentSystem._try_player_hit`)."""
        return self.resonance_chain >= self.resonance_overdrive_threshold

    def register_judgment_feedback(self, judgment: int, display_seconds: float) -> None:
        """Atualiza o feedback visual de julgamento consumido pelo
        `UIRenderSystem` (palavra PERFECT/GOOD/MISS por alguns frames).
        """
        self.last_judgment = judgment
        self.judgment_display_seconds_left = display_seconds

    def trigger_shake(self, intensity_px: float) -> None:
        """Aciona/reforca o tremor de tela. Usa `max()`, nao soma: dois
        tremores sobrepostos (ex.: um MISS de Hold bem no instante de uma
        parede letal) resultam no MAIOR dos dois, nao numa intensidade
        absurda que a soma produziria -- decai normalmente dali."""
        self.shake_intensity = max(self.shake_intensity, float(intensity_px))

    def trigger_hitlag(self, freeze_frames: int) -> None:
        """Aciona/reforca o Hitlag Visual do Parry. Mesmo criterio de
        `trigger_shake`/`trigger_blindness`: `max()`, nao soma -- dois
        Parries no mesmo instante nao dobram o congelamento. SEMPRE
        arma o flash de cor invertida (`invert_colors = True`) junto,
        mesmo se `freeze_frames` nao renovar o congelamento atual (um
        Parry novo continua merecendo o flash de retorno)."""
        self.visual_freeze_frames = max(self.visual_freeze_frames, int(freeze_frames))
        self.invert_colors = True
