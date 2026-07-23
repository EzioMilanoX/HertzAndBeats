"""HertzConfig: toda a afinacao de gameplay carregada de JSON (data-driven, nunca hardcoded em sistema)."""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from typing import Dict, Tuple

from utils.path_resolver import get_resource_path


@dataclass(frozen=True)
class HertzConfig:
    """
    Configuracao imutavel do Hertz & Beats, carregada de
    `data/config/hertz_beats.config.json` ANTES da composicao -- mesmo
    papel da `EngineConfig` da engine, estendida com a afinacao do
    gameplay radial/ritmico. Sistemas recebem valores primitivos ja
    resolvidos no construtor; nenhum sistema le JSON em runtime.
    """

    window_width: int
    window_height: int
    window_title: str
    entity_capacity: int
    max_threats: int
    max_threats_per_frame: int
    target_fps: int

    beatmap_path: str
    track_path: str
    input_bindings_path: str
    stages_path: str

    threat_type_ids: Dict[str, int]
    threat_half_extents: Dict[str, float]
    lane_count: int

    approach_seconds: float
    spawn_radius: float
    core_half_extent: float

    perfect_window_seconds: float
    good_window_seconds: float
    miss_window_seconds: float
    aim_tolerance_degrees: float

    score_perfect: int
    score_good: int
    max_health: int
    judgment_display_seconds: float

    dash_duration_seconds: float
    dash_cooldown_seconds: float

    output_latency_seconds: float

    # -- modo de jogo (a IA dita o TEMPO; o modo dita a interpretacao
    #    espacial e de input do MESMO beatmap.json). Selecionado por
    #    fase via `overrides` (dataclasses.replace).
    game_mode: str = "defender"
    misfire_breaks_combo: bool = True
    lane_spacing: float = 110.0
    judgment_line_offset: float = 170.0
    misfire_jam_seconds: float = 0.5

    # -- Mecanicas Modulares (Modifiers): substitui os antigos flags
    #    rigidos por modo (`polarity_enabled`/`holds_enabled`) por uma
    #    lista aberta de strings, lida por `rhythm_composition_root.py`
    #    para decidir quais sistemas/campos EXTRA entram na composicao --
    #    qualquer fase pode combinar livremente. Vem de `StageDef.
    #    active_modifiers` (`resolve_stage_config` copia a lista da fase
    #    inteira -- NAO e um dict de `overrides`, e substituida por
    #    completo por fase, nunca herdada/mesclada com a base). Catalogo
    #    atual (Defensor, exceto onde indicado):
    #      "telegraph_rings"  -- ConvergenceRingSystem (aneis-aviso)
    #      "polarity"         -- disparo azul/rosa + Parry Perfeito
    #                            (fundacao de quase todos os outros)
    #      "orbital_shields"  -- Captura Orbital (Escudos Rotativos);
    #                            exige "polarity" tambem ativo
    #      "twin_threats"     -- Gemeos de Polaridade; exige "polarity"
    #      "orbital_eclipses" -- Eclipses Orbitais (independente)
    #      "overload"         -- Overload do Nucleo/Shockwave; exige
    #                            "polarity" (Ressonancia so existe com ela)
    #      "vision_tunnel"    -- Colapso de Visao (independente): NUNCA
    #                            muda `current_judgment_radius` (fisico,
    #                            fixo desde a composicao) -- so o raio
    #                            COSMETICO do campo de luz (`GameState.
    #                            tunnel_radius`), ver `VisionTunnelSystem`
    #      "holds"            -- Notas Longas (os 2 modos); MUTUAMENTE
    #                            EXCLUSIVO com "polarity" por convencao de
    #                            fase (os dois reusam o mesmo threat_type
    #                            "pesada" com significados incompativeis)
    #      "bombs"/"heal"     -- Arcade 4K, opt-in por presenca do tipo
    #                            no beatmap (aqui so garante que o TIPO
    #                            exista em `threat_type_ids`)
    #      "roleta_russa"     -- Meta-Jogo (os 2 modos): forca `max_health`
    #                            para 1 na composicao (`HertzGameLoop.
    #                            _compose_stage`, depois de resolver
    #                            overrides/painel) -- NENHUM sistema novo:
    #                            todo MISS ja custa exatamente 1 de vida em
    #                            CoreDamageSystem/JudgmentSystem/
    #                            LaneJudgmentSystem, entao 1 de vida maxima
    #                            e' Game Over instantaneo no primeiro erro
    #                            "de graca" (maior bonus de pontuacao do
    #                            catalogo, ver `MODIFIER_SCORE_BONUS`)
    #      "boomerang"        -- Defensor (independente): `BoomerangThreatSystem`
    #                            -- nasce no nucleo, voa ate a borda e
    #                            volta (formula senoidal do raio, nao a
    #                            reta constante de toda ameaca comum);
    #                            deixe passar na ida, atire na volta
    #      "corrupcao"        -- os 2 modos (independente): barras de
    #                            estatica visual na tela inteira
    #                            enquanto a fase toca -- puramente
    #                            cosmetico, nenhuma mudanca de
    #                            jogabilidade (`HBPygameRenderer.
    #                            _draw_glitch_bars`)
    #      "phalanx"          -- Defensor (independente), Modo Falange
    #                            (Undyne): `toggle_phalanx` troca o tiro
    #                            manual por um escudo automatico (arco em
    #                            torno da mira sobre o anel de julgamento)
    #                            -- reduz fadiga de clique variando o
    #                            ritmo (ver `JudgmentSystem.
    #                            _run_phalanx_block_check`)
    #      "focus_beam"       -- Defensor (independente), Raio de Foco/
    #                            "Microondas": uma fracao das ameacas comuns
    #                            vira `is_focus_target` -- exige mira
    #                            SUSTENTADA (nao clique) perto do anel de
    #                            julgamento ate `focus_health` zerar;
    #                            desmirar antes reseta pro maximo (ver
    #                            `JudgmentSystem._run_focus_beam_check`)
    #      "radial_slash"     -- Defensor (independente), A Lamina: uma
    #                            fracao vira `is_slash_target` -- ignora
    #                            clique, exige um ARRASTO rapido do mouse
    #                            cujo arco cruze o angulo da ameaca dentro
    #                            da janela PERFECT (ver `JudgmentSystem.
    #                            _run_slash_check`)
    #    Um modifier cuja dependencia nao esta presente (ex.:
    #    "orbital_shields" sem "polarity") degrada silenciosamente para
    #    no-op -- nunca lanca erro (mesma filosofia de opt-in gracioso ja
    #    usada por `orbit_threat_type_id`/`twin_threat_type_id`).
    active_modifiers: Tuple[str, ...] = ()

    # -- Polaridade + Parry Perfeito (Defensor, opt-in via "polarity" em
    #    `active_modifiers`) --
    fire_alt_action_name: str = "fire_alt"

    # -- Meta-Jogo -- Paletas Cosmeticas: os UNICOS 2 tints que mudam por
    #    paleta desbloqueavel (ver `hertzbeats.palettes.PALETTE_CATALOG`,
    #    resolvido em `RhythmCompositionRoot.build()` a partir da escolha
    #    salva do jogador -- `user_settings.load_user_palette_id`). O Anel
    #    de Convergencia HERDA a cor da ameaca que o gerou, sem precisar
    #    de um campo proprio. Default = a paleta "classic" (tons de
    #    sempre, comportamento IDENTICO a antes desta feature existir).
    threat_blue_rgb: Tuple[int, int, int] = (70, 140, 255)
    threat_pink_rgb: Tuple[int, int, int] = (255, 90, 190)

    # -- Pistas Dinamicas (Arcade 4K, sempre ativo) --
    lane_sway_amplitude_px: float = 34.0
    lane_sway_decay_per_second: float = 2.2

    # -- Notas de Scratch (Arcade 4K, sempre ativo) --
    scratch_cluster_gap_seconds: float = 0.6
    scratch_min_cluster_size: int = 3
    scratch_hold_tail_seconds: float = 0.35
    scratch_min_energy: float = 0.12

    # -- Flow State (Arcade 4K, sempre ativo) --
    flow_combo_threshold: int = 50
    flow_volume_boost: float = 0.15
    flow_shatter_seconds: float = 0.35

    # -- Screen Shake (Camera, comum aos 3 modos -- sempre ativo; quem
    #    aciona e cada mecanica via `GameState.trigger_shake`) --
    shake_decay_per_second: float = 60.0

    # -- Haptics/Rumble (comum; no-op silencioso sem controle conectado) --
    rumble_low_freq: float = 0.35
    rumble_high_freq: float = 0.85
    rumble_duration_seconds: float = 0.25

    # -- Notas Longas / Holds -- UM modifier ("holds" em `active_modifiers`)
    #    para os 2 modos, cada um interpreta a sustentacao a sua maneira
    #    (Defensor: fire+mira; Arcade: tecla da coluna + Shield) -- mesma
    #    filosofia de "a IA dita o tempo, o modo dita a interpretacao" ja
    #    usada pelo resto do schema. --
    hold_duration_seconds: float = 1.5

    # -- Defensor: Hold por fire+mira sustentados --
    hold_aim_tolerance_degrees: float = 50.0
    hold_break_shake_px: float = 22.0
    # Tolerancia Organica -- Hold Forgiveness ("Coyote Time" para
    # micro-tremores de mao): segundos de graca ANTES de quebrar um Hold
    # engajado quando a mira escapa do cone ou o gatilho e solto -- ver
    # `RHYTHM_THREAT_DTYPE.hold_grace_timer_sec` e
    # `JudgmentSystem._sweep_engaged_holds`.
    hold_grace_seconds: float = 0.15

    # -- Arcade 4K: Hold classico (tecla sustentada) + Shield --
    lane_shield_max_charges: int = 3
    lane_shield_depleted_shake_px: float = 35.0
    # a barra caida representa `hold_duration_seconds` a MESMA velocidade
    # de queda da nota -- sem teto, uma duracao comparavel a
    # `approach_seconds` (o padrao de ambas, ~1.5-1.8s) produz uma barra
    # que cobre quase a tela inteira. Fracao MAXIMA da distancia total de
    # queda que a barra pode ocupar visualmente; a duracao real exigida
    # do jogador (`hold_duration_seconds`) nunca muda, so o desenho.
    lane_hold_visual_max_fraction: float = 0.35

    # -- Mais tremores/efeitos ("game feel" geral, sempre ativos) --
    core_damage_shake_px: float = 14.0
    parry_impact_shake_px: float = 10.0

    # -- Juice Visual: Sparks (particulas no acerto PERFECT, Defensor) --
    spark_pool_size: int = 128
    spark_lifetime_seconds: float = 0.22
    spark_max_length_px: float = 24.0
    spark_burst_count: int = 5

    # -- Juice Visual: UI Bump (digitos do combo em destaque a cada
    #    multiplo de `combo_bump_threshold`, comum aos 3 modos) --
    combo_bump_threshold: int = 50
    combo_bump_seconds: float = 0.5

    # -- Audio Ducking (comum aos 3 modos: MISS/dano abaixam a musica) --
    duck_volume_fraction: float = 0.3
    duck_duration_seconds: float = 0.5

    # -- Meta-Jogo: Multiplicador de Pontuacao -- resolvido pelo
    #    HertzGameLoop na tela de Pre-Voo (`compute_score_multiplier`,
    #    a partir dos modifiers/Modo Treino escolhidos) e aplicado UMA
    #    vez na composicao (score_perfect/score_good efetivos, nunca em
    #    tempo real por acerto) -- ver `_compose_stage`/`compose_world`.
    score_multiplier: float = 1.0

    # -- Modo Treino (musicas do jogador, alternado no menu com T) --
    practice_mode: bool = False
    practice_density_keep_fraction: float = 0.5

    # -- Meta-Jogo: tela de Calibracao (metronomo + tecla no tempo) --
    calibration_bpm: float = 120.0
    calibration_target_taps: int = 8

    # -- Arcade 4K: Notas Toxicas (Bombas) -- opt-in por presenca do
    #    tipo "rhythm_threat_bomb" em `threat_type_ids` (sem flag extra,
    #    mesmo criterio de `rhythm_threat_heavy`) --
    bomb_hit_shake_px: float = 18.0
    bomb_blindness_seconds: float = 1.2

    # -- Arcade 4K: Stutter Scroll (gagueira visual, nao afeta a fisica) --
    stutter_scroll_enabled: bool = False
    stutter_scroll_amplitude_px: float = 10.0
    stutter_scroll_frequency_hz: float = 9.0

    # -- Arcade 4K: Notas Fantasmas (Hidden mod, fade de tint_a) --
    hidden_notes_enabled: bool = False
    hidden_fade_seconds: float = 0.5

    # -- Arcade 4K: Notas de Cura -- opt-in por presenca do tipo
    #    "rhythm_threat_heal" em `threat_type_ids` (mesmo criterio de
    #    Bombas), so em acerto PERFECT --
    heal_amount: int = 1

    # -- Arcade 4K: Obstrucoes Visuais (jumpscares/distracoes) --
    distraction_pool_size: int = 5

    # -- Arcade 4K: Inversao de Gravidade (Reverse Scroll dinamico) --
    # nenhum campo extra necessario: o piso numerico do recalculo de
    # velocidade e uma constante interna do `ReverseScrollSystem`
    # (`_TIME_EPSILON_SECONDS`), nao uma afinacao de jogabilidade.

    # -- Defensor: Captura Orbital (Escudos Rotativos) -- opt-in via
    #    "orbital_shields" em `active_modifiers` (exige "polarity" junto) --
    orbit_radius: float = 90.0
    orbit_angular_speed_rad_per_sec: float = 2.4

    # -- Defensor: Ameacas Bumerangue -- opt-in via "boomerang" em
    #    `active_modifiers` (independente, nao exige "polarity"): nascem
    #    no nucleo, voam ate `spawn_radius` e voltam, tudo dentro deste
    #    tempo total -- `target_hit_time_sec` continua sendo o instante
    #    do RETORNO (ver `BoomerangThreatSystem`). Deve ficar <=
    #    `approach_seconds` da fase para a ameaca nascer (e ficar parada,
    #    raio 0) ANTES do inicio de fato do percurso -- maior que isso, a
    #    entidade so e criada pelo spawner generico da engine DEPOIS do
    #    instante em que o percurso ja deveria ter comecado, "pulando"
    #    direto para o meio da viagem.
    boomerang_round_trip_seconds: float = 2.0

    # -- Defensor: Ressonancia de Polaridade (Combos Monocromaticos,
    #    automatica quando "polarity" esta em `active_modifiers` --
    #    reusa a MESMA cor ja atribuida a cada ameaca comum) --
    resonance_chain_threshold: int = 10

    # -- Defensor: Juice Extremo de Parry (Hitlag Visual Simulado) --
    parry_hitlag_freeze_frames: int = 3

    # -- Defensor: Gemeos de Polaridade -- opt-in via "twin_threats" em
    #    `active_modifiers` (exige "polarity" junto); nenhum campo extra
    #    necessario aqui -- reusa `lane_count` ja existente.

    # -- Defensor: Eclipses Orbitais (Barreiras Dinamicas) -- opt-in via
    #    "orbital_eclipses" em `active_modifiers`; `orbital_eclipse_count`
    #    continua controlando QUANTOS obstaculos nascem --
    orbital_eclipse_count: int = 3
    orbital_eclipse_radius: float = 150.0
    orbital_eclipse_rotation_speed_rad_per_sec: float = 1.2
    orbital_eclipse_half_width: float = 28.0
    orbital_eclipse_half_height: float = 8.0

    # -- Defensor: Overload do Nucleo (Dash + Ressonancia cheia sobre
    #    batida viva) -- reusa o `ShockwaveSystem` do Pulso de Impacto
    #    da extinta Sobrevivencia; opt-in via "overload" em
    #    `active_modifiers` (exige "polarity" tambem -- a Ressonancia so
    #    existe com ela) --
    shockwave_pool_size: int = 5
    shockwave_min_radius: float = 20.0
    shockwave_max_radius: float = 260.0
    shockwave_duration_seconds: float = 0.2
    shockwave_trigger_shake_px: float = 8.0

    # -- Preparacao para Crossfading Vocal (esqueleto, ainda inerte):
    #    marca que a faixa da fase tem legendas/vocal sincronizados por
    #    tempo -- hoje NENHUMA fase popula os arrays cronologicos que o
    #    `UIRenderSystem` esta preparado para ler (mesmo cursor
    #    monotonico do `TutorialSystem`), e `HBPygameAudioEngine.
    #    muffle_vocals` ainda nao muda audio nenhum (exigiria uma 2a
    #    camada de audio -- stem instrumental -- que nao existe). Este
    #    campo so existe pra ja ter onde declarar o opt-in quando essa
    #    pipeline for construida de verdade.
    karaoke_sync: bool = False

    # -- Defensor: Colapso de Visao (Visual Tunnel) -- opt-in via
    #    "vision_tunnel" em `active_modifiers`. Tolerancia Organica:
    #    substitui o antigo "Colapso do Anel de Julgamento", que mutava
    #    `current_judgment_radius` (FISICO -- usado no calculo de
    #    velocidade das ameacas e na orbita da mira) e por isso quebrava
    #    a fisica ja calculada no spawn de ameacas em voo. Agora so um
    #    raio COSMETICO (`GameState.tunnel_radius`, campo de luz
    #    desenhado pelo renderer) encolhe -- nenhum numero de jogabilidade
    #    muda. Nenhum campo extra necessario aqui: o raio BASE (campo
    #    "totalmente aberto") e a diagonal centro->canto da janela,
    #    calculada na composicao; os eventos vem de `StageDef.
    #    modchart_events` (`{"type": "vision_tunnel", "time_seconds",
    #    "duration_seconds", "target_radius"}`), mesmo dado 100%
    #    game-side ja usado por Swap/Reverse Scroll/Distraction. --

    # -- Carrossel Horizontal (Audio Preview): o cursor precisa REPOUSAR
    #    numa musica por `carousel_preview_hover_seconds` antes do preview
    #    comecar (senao navegar rapido dispararia um preview por musica
    #    visitada) -- toca a partir de `carousel_preview_start_fraction`
    #    da duracao TOTAL (30% pula a intro, cai perto do groove
    #    principal) com um fade-in de `carousel_preview_fade_ms`.
    carousel_preview_hover_seconds: float = 0.5
    carousel_preview_start_fraction: float = 0.3
    carousel_preview_fade_ms: int = 1000

    # -- Estetica Reativa: fundo desfocado/escurecido derivado da
    #    miniatura do video (`HBPygameRenderer.cache_carousel_visuals`) --
    #    escurecido em `carousel_background_darken_fraction` (0.85 = so
    #    15% do brilho original sobrevive, o suficiente pra nao competir
    #    com a arena desenhada por cima).
    carousel_background_darken_fraction: float = 0.85

    # -- Eventos de Gameplay via Capitulos do YouTube: um capitulo cujo
    #    titulo contenha (case-insensitive) alguma destas palavras vira
    #    um evento de Modchart sintetico "arena_warp" (tremor de tela,
    #    os 2 modos) + "reverse_scroll" no Arcade 4K (reaproveita a
    #    coreografia global JA existente, ver
    #    `modchart.chapters_to_modchart_events`). `arena_warp_shake_px`
    #    e' a intensidade do tremor (`GameState.trigger_shake`).
    chapter_event_keywords: Tuple[str, ...] = ("drop", "chorus", "climax", "intense")
    arena_warp_shake_px: float = 24.0

    # -- Rogue-lite Endgame -- Mind Games (Defensor): opt-in via
    #    "wormholes"/"mirages"/"rubber_band" em `active_modifiers`, o
    #    Mapa Rogue-lite forca exatamente UM por musica (ver
    #    `hertzbeats.rogue_lite.roll_map_choices`) -- ver
    #    `RadialRhythmSpawnerSystem`/`MindGamesSystem`/`JudgmentSystem`.
    wormhole_teleport_radius: float = 220.0
    # Ameacas Fantasmas: PRECISA ficar MENOR que `good_window_seconds`
    # (0.10 por padrao) -- e' o unico jeito de "atirar nela antes de
    # sumir aplica MISS" ser alcancavel de verdade. Se este valor fosse
    # MAIOR que a janela Good (ex.: 0.2s, ingenuo a primeira vista), o
    # fantasma sempre teria sumido em silencio ANTES de sequer entrar na
    # janela de acerto -- o "atirar nela = MISS" nunca aconteceria na
    # pratica, so' o desaparecimento silencioso. 0.03s deixa uma folga
    # real (~70ms com a janela Good padrao) onde o disparo pune, e so'
    # nos ultimos 30ms o fantasma se dissolve de misericordia.
    mirage_vanish_seconds: float = 0.03

    # -- Rogue-lite Endgame -- Perks (resolvidos em `HertzGameLoop.
    #    _compose_stage` a partir de `GameState.rogue_run.perks`, nunca
    #    checados por string dentro do loop de `JudgmentSystem`) --
    #    ver `hertzbeats.rogue_lite.ROGUE_PERK_CATALOG`. `0`/`0` = os 2
    #    Perks desligados (fase normal, fora de uma corrida).
    vampirism_combo_threshold: int = 0
    vampirism_max_health: int = 0

    # -- Modo Falange (Undyne, Defensor) -- opt-in via "phalanx" em
    #    `active_modifiers`: substitui o tiro manual por um ESCUDO que
    #    bloqueia automaticamente qualquer ameaca que cruze o anel de
    #    julgamento DENTRO do arco em torno da mira -- ver
    #    `PlayerInputSystem` (alterna via `toggle_phalanx`) e
    #    `JudgmentSystem._run_phalanx_block_check`.
    phalanx_radius_tolerance_px: float = 24.0
    """Faixa (px, em torno de `current_judgment_radius`) em que o
    escudo bloqueia -- MESMA unidade de `spawn_radius`/`wormhole_teleport_radius`,
    escalada junto com a janela em `fit_config_to_display`."""
    phalanx_shield_arc_degrees: float = 45.0
    """Largura TOTAL do arco do escudo (metade pra cada lado da mira) --
    mesma convencao de `aim_tolerance_degrees` (graus, convertido pra
    radianos na composicao)."""
    phalanx_activate_shake_px: float = 12.0
    """Tremor de camera ao ALTERNAR o Modo Falange (entrar OU sair) --
    `GameState.trigger_shake`, mesmo mecanismo de sempre."""
    core_pulse_seconds: float = 0.15
    """Modo Falange -- Juice Visual: duracao do pulso de escala do
    nucleo a cada bloqueio (encolhe `core_pulse_depth` e volta
    LINEARMENTE ao normal ao longo deste tempo)."""
    core_pulse_depth: float = 0.10
    """Modo Falange: fracao de encolhimento do nucleo no INSTANTE do
    bloqueio (0.10 = 90% do tamanho normal), decaindo de volta a 1.0."""

    # -- Raio de Foco/"Microondas" (Defensor) -- opt-in via "focus_beam"
    #    em `active_modifiers`: ameacas `is_focus_target` NAO aceitam
    #    clique -- exigem mira sustentada enquanto estiverem perto do
    #    anel de julgamento, ver `JudgmentSystem._run_focus_beam_check`.
    focus_target_seconds: float = 0.6
    """Segundos de mira sustentada necessarios pra `focus_health` zerar
    (o PROPRIO valor inicial de `focus_health` no spawn) -- reseta pro
    valor cheio se a mira sair ANTES de chegar a zero."""
    focus_tolerance_degrees: float = 15.0
    """Cone de mira (graus, convertido pra radianos na composicao --
    mesma convencao de `aim_tolerance_degrees") pra contar como "mira em
    cima" do alvo de foco."""
    focus_radius_tolerance_px: float = 60.0
    """Faixa (px, em torno de `current_judgment_radius`, MESMA unidade
    de `phalanx_radius_tolerance_px`) dentro da qual o foco realmente
    decrementa -- fora dela (ainda longe do anel), `focus_health` fica
    parado no valor cheio, nunca decrementa nem reseta."""

    # -- A Lamina/"Radial Slash" (Defensor) -- opt-in via "radial_slash"
    #    em `active_modifiers`: ameacas `is_slash_target` IGNORAM
    #    cliques -- exigem um arrasto RAPIDO do mouse cujo arco cruze o
    #    angulo da ameaca dentro da janela PERFECT, ver
    #    `JudgmentSystem._run_slash_check`.
    slash_min_angular_speed_rad_per_sec: float = 12.0
    """Velocidade angular MINIMA (rad/s, `|mira_atual - mira_anterior| /
    delta_time`, com wraparound em +-PI) pra contar como um "arrasto
    rapido" -- movimento normal de mira (rastrear uma ameaca chegando)
    fica bem abaixo disso; so' um puxao deliberado do pulso qualifica."""

    @property
    def center_xy(self) -> Tuple[float, float]:
        """Centro da arena (posicao do nucleo), derivado da janela."""
        return (self.window_width / 2.0, self.window_height / 2.0)

    @staticmethod
    def from_json(config_path: str) -> "HertzConfig":
        """Carrega e valida uma `HertzConfig` a partir de um arquivo JSON.

        `config_path` e' o UNICO arquivo curado empacotado com o jogo
        (`data/config/hertz_beats.config.json`, default de
        `hertzbeats.__main__.DEFAULT_CONFIG_PATH`) -- resolvido aqui via
        `get_resource_path` (raiz = `sys._MEIPASS` num build PyInstaller
        congelado). Os campos QUE ESTE JSON contem (`stages_path`,
        `track_path`, `input_bindings_path`, ...) continuam strings
        relativas cruas no dataclass -- cada consumidor resolve o SEU
        proprio caminho no seu proprio ponto de uso (`load_stages`,
        `HBPygameAudioEngine`, ...), nunca aqui."""
        with open(get_resource_path(config_path), "r", encoding="utf-8") as f:
            raw = json.load(f)
        return HertzConfig(
            window_width=raw["window_width"],
            window_height=raw["window_height"],
            window_title=raw["window_title"],
            entity_capacity=raw["entity_capacity"],
            max_threats=raw["max_threats"],
            max_threats_per_frame=raw["max_threats_per_frame"],
            target_fps=raw["target_fps"],
            beatmap_path=raw["beatmap_path"],
            track_path=raw["track_path"],
            input_bindings_path=raw["input_bindings_path"],
            stages_path=raw["stages_path"],
            threat_type_ids=dict(raw["threat_type_ids"]),
            threat_half_extents=dict(raw["threat_half_extents"]),
            lane_count=raw["lane_count"],
            approach_seconds=raw["approach_seconds"],
            spawn_radius=raw["spawn_radius"],
            core_half_extent=raw["core_half_extent"],
            perfect_window_seconds=raw["perfect_window_seconds"],
            good_window_seconds=raw["good_window_seconds"],
            miss_window_seconds=raw["miss_window_seconds"],
            aim_tolerance_degrees=raw["aim_tolerance_degrees"],
            score_perfect=raw["score_perfect"],
            score_good=raw["score_good"],
            max_health=raw["max_health"],
            judgment_display_seconds=raw["judgment_display_seconds"],
            dash_duration_seconds=raw["dash_duration_seconds"],
            dash_cooldown_seconds=raw["dash_cooldown_seconds"],
            output_latency_seconds=raw["output_latency_seconds"],
            game_mode=raw.get("game_mode", "defender"),
            misfire_breaks_combo=raw.get("misfire_breaks_combo", True),
            lane_spacing=raw.get("lane_spacing", 110.0),
            judgment_line_offset=raw.get("judgment_line_offset", 170.0),
            misfire_jam_seconds=raw.get("misfire_jam_seconds", 0.5),
            threat_blue_rgb=tuple(raw.get("threat_blue_rgb", (70, 140, 255))),
            threat_pink_rgb=tuple(raw.get("threat_pink_rgb", (255, 90, 190))),
            active_modifiers=tuple(raw.get("active_modifiers", ())),
            fire_alt_action_name=raw.get("fire_alt_action_name", "fire_alt"),
            lane_sway_amplitude_px=raw.get("lane_sway_amplitude_px", 34.0),
            lane_sway_decay_per_second=raw.get("lane_sway_decay_per_second", 2.2),
            scratch_cluster_gap_seconds=raw.get("scratch_cluster_gap_seconds", 0.6),
            scratch_min_cluster_size=raw.get("scratch_min_cluster_size", 3),
            scratch_hold_tail_seconds=raw.get("scratch_hold_tail_seconds", 0.35),
            scratch_min_energy=raw.get("scratch_min_energy", 0.12),
            flow_combo_threshold=raw.get("flow_combo_threshold", 50),
            flow_volume_boost=raw.get("flow_volume_boost", 0.15),
            flow_shatter_seconds=raw.get("flow_shatter_seconds", 0.35),
            shake_decay_per_second=raw.get("shake_decay_per_second", 60.0),
            rumble_low_freq=raw.get("rumble_low_freq", 0.35),
            rumble_high_freq=raw.get("rumble_high_freq", 0.85),
            rumble_duration_seconds=raw.get("rumble_duration_seconds", 0.25),
            hold_duration_seconds=raw.get("hold_duration_seconds", 1.5),
            hold_aim_tolerance_degrees=raw.get("hold_aim_tolerance_degrees", 50.0),
            hold_break_shake_px=raw.get("hold_break_shake_px", 22.0),
            hold_grace_seconds=raw.get("hold_grace_seconds", 0.15),
            lane_shield_max_charges=raw.get("lane_shield_max_charges", 3),
            lane_shield_depleted_shake_px=raw.get("lane_shield_depleted_shake_px", 35.0),
            lane_hold_visual_max_fraction=raw.get("lane_hold_visual_max_fraction", 0.35),
            core_damage_shake_px=raw.get("core_damage_shake_px", 14.0),
            parry_impact_shake_px=raw.get("parry_impact_shake_px", 10.0),
            spark_pool_size=raw.get("spark_pool_size", 128),
            spark_lifetime_seconds=raw.get("spark_lifetime_seconds", 0.22),
            spark_max_length_px=raw.get("spark_max_length_px", 24.0),
            spark_burst_count=raw.get("spark_burst_count", 5),
            combo_bump_threshold=raw.get("combo_bump_threshold", 50),
            combo_bump_seconds=raw.get("combo_bump_seconds", 0.5),
            duck_volume_fraction=raw.get("duck_volume_fraction", 0.3),
            duck_duration_seconds=raw.get("duck_duration_seconds", 0.5),
            score_multiplier=raw.get("score_multiplier", 1.0),
            calibration_bpm=raw.get("calibration_bpm", 120.0),
            calibration_target_taps=raw.get("calibration_target_taps", 8),
            practice_mode=raw.get("practice_mode", False),
            practice_density_keep_fraction=raw.get("practice_density_keep_fraction", 0.5),
            bomb_hit_shake_px=raw.get("bomb_hit_shake_px", 18.0),
            bomb_blindness_seconds=raw.get("bomb_blindness_seconds", 1.2),
            stutter_scroll_enabled=raw.get("stutter_scroll_enabled", False),
            stutter_scroll_amplitude_px=raw.get("stutter_scroll_amplitude_px", 10.0),
            stutter_scroll_frequency_hz=raw.get("stutter_scroll_frequency_hz", 9.0),
            hidden_notes_enabled=raw.get("hidden_notes_enabled", False),
            hidden_fade_seconds=raw.get("hidden_fade_seconds", 0.5),
            heal_amount=raw.get("heal_amount", 1),
            distraction_pool_size=raw.get("distraction_pool_size", 5),
            orbit_radius=raw.get("orbit_radius", 90.0),
            orbit_angular_speed_rad_per_sec=raw.get("orbit_angular_speed_rad_per_sec", 2.4),
            boomerang_round_trip_seconds=raw.get("boomerang_round_trip_seconds", 2.0),
            resonance_chain_threshold=raw.get("resonance_chain_threshold", 10),
            parry_hitlag_freeze_frames=raw.get("parry_hitlag_freeze_frames", 3),
            orbital_eclipse_count=raw.get("orbital_eclipse_count", 3),
            orbital_eclipse_radius=raw.get("orbital_eclipse_radius", 150.0),
            orbital_eclipse_rotation_speed_rad_per_sec=raw.get(
                "orbital_eclipse_rotation_speed_rad_per_sec", 1.2
            ),
            orbital_eclipse_half_width=raw.get("orbital_eclipse_half_width", 28.0),
            orbital_eclipse_half_height=raw.get("orbital_eclipse_half_height", 8.0),
            shockwave_pool_size=raw.get("shockwave_pool_size", 5),
            shockwave_min_radius=raw.get("shockwave_min_radius", 20.0),
            shockwave_max_radius=raw.get("shockwave_max_radius", 260.0),
            shockwave_duration_seconds=raw.get("shockwave_duration_seconds", 0.2),
            shockwave_trigger_shake_px=raw.get("shockwave_trigger_shake_px", 8.0),
            karaoke_sync=raw.get("karaoke_sync", False),
            carousel_preview_hover_seconds=raw.get("carousel_preview_hover_seconds", 0.5),
            carousel_preview_start_fraction=raw.get("carousel_preview_start_fraction", 0.3),
            carousel_preview_fade_ms=raw.get("carousel_preview_fade_ms", 1000),
            carousel_background_darken_fraction=raw.get("carousel_background_darken_fraction", 0.85),
            chapter_event_keywords=tuple(
                raw.get("chapter_event_keywords", ("drop", "chorus", "climax", "intense"))
            ),
            arena_warp_shake_px=raw.get("arena_warp_shake_px", 24.0),
            wormhole_teleport_radius=raw.get("wormhole_teleport_radius", 220.0),
            mirage_vanish_seconds=raw.get("mirage_vanish_seconds", 0.03),
            vampirism_combo_threshold=raw.get("vampirism_combo_threshold", 0),
            vampirism_max_health=raw.get("vampirism_max_health", 0),
            phalanx_radius_tolerance_px=raw.get("phalanx_radius_tolerance_px", 24.0),
            phalanx_shield_arc_degrees=raw.get("phalanx_shield_arc_degrees", 45.0),
            phalanx_activate_shake_px=raw.get("phalanx_activate_shake_px", 12.0),
            core_pulse_seconds=raw.get("core_pulse_seconds", 0.15),
            core_pulse_depth=raw.get("core_pulse_depth", 0.10),
            focus_target_seconds=raw.get("focus_target_seconds", 0.6),
            focus_tolerance_degrees=raw.get("focus_tolerance_degrees", 15.0),
            focus_radius_tolerance_px=raw.get("focus_radius_tolerance_px", 60.0),
            slash_min_angular_speed_rad_per_sec=raw.get("slash_min_angular_speed_rad_per_sec", 12.0),
        )


def fit_config_to_display(
    config: HertzConfig,
    display_width: int,
    display_height: int,
    height_margin: int = 90,
    width_margin: int = 20,
) -> HertzConfig:
    """Encolhe a janela (e TODA a geometria de gameplay, na mesma
    proporcao) quando o monitor nao comporta o tamanho configurado --
    uma janela 960x960 numa tela de 768 de altura ficaria cortada, com
    HUD e metade da arena invisiveis.

    Escala uniformemente: janela, raio de spawn, nucleo e meios-tamanhos
    de ameaca. Como as VELOCIDADES derivam de distancia/tempo no spawn,
    a fisica e o julgamento continuam cravados na batida em qualquer
    escala; `approach_seconds` e as janelas temporais nao mudam.
    Retorna a config intocada se ela ja cabe na tela. Funcao PURA
    (testavel sem pygame); quem sonda o tamanho real do display e o
    adapter concreto.
    """
    usable = min(display_width - width_margin, display_height - height_margin)
    if usable <= 0 or usable >= config.window_width:
        return config

    scale = usable / float(config.window_width)
    return dataclasses.replace(
        config,
        window_width=usable,
        window_height=usable,
        spawn_radius=config.spawn_radius * scale,
        core_half_extent=config.core_half_extent * scale,
        threat_half_extents={
            name: half * scale for name, half in config.threat_half_extents.items()
        },
        wormhole_teleport_radius=config.wormhole_teleport_radius * scale,
        phalanx_radius_tolerance_px=config.phalanx_radius_tolerance_px * scale,
        focus_radius_tolerance_px=config.focus_radius_tolerance_px * scale,
    )
