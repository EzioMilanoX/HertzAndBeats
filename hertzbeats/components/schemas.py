"""
Schemas SoA especificos do Hertz & Beats. Assim como os schemas do
nucleo da engine, NAO sao classes instanciadas por entidade -- sao
`numpy.dtype` estruturados consumidos por `MemoryManager.create_pool`
na composicao do jogo. Nenhum "HitEvent"/"Threat" Python existe em
runtime: apenas linhas destes arrays contiguos.
"""
from __future__ import annotations

import numpy as np

JUDGMENT_PENDING: int = 0
"""Ameaca ainda viva e nao julgada (valor default de pool zerada)."""

JUDGMENT_PERFECT: int = 1
"""Acertada com |delta| <= janela Perfect."""

JUDGMENT_GOOD: int = 2
"""Acertada com |delta| <= janela Good."""

JUDGMENT_MISS: int = 3
"""Passou do tempo sem acerto, ou atingiu o nucleo."""

JUDGMENT_DODGED: int = 4
"""Atravessou a ameaca durante os i-frames de um Dash: nao pune nem
quebra o combo, mas tambem nao pontua."""

JUDGMENT_SURVIVED: int = 5
"""Arcade 4K -- Bombas: a nota passou da linha de julgamento sem ser
tocada -- o jogo CORRETO (silencioso, sem punicao nem pontuacao)."""

MODE_TAG_DEFENDER: int = 0
"""Ameaca radial (julgada por mira + tempo)."""

MODE_TAG_LANES: int = 2
"""Nota de coluna (julgada por tecla + tempo)."""

PHASE_LETHAL: int = 1
"""Fase padrao de toda ameaca/nota: colisao/julgamento valem
normalmente desde o spawn."""

PHASE_ORBITING: int = 2
"""Defensor -- Captura Orbital (Escudos Rotativos): um Parry Perfeito
numa ameaca tipo "orbit" nao a destroi nem a reflete -- ela vira um
ESCUDO que orbita o nucleo para sempre (`OrbitalCaptureSystem`, seno/
cosseno sobre `spawn_angle_rad` como offset angular fixo + o relogio).
Reaproveita o MESMO campo `phase` (normalmente PHASE_LETHAL) sem
precisar de um campo novo."""

POLARITY_BLUE: int = 0
"""Timbre AGUDO (metade superior dos buckets de timbre da IA -- ver
`assign_lanes` no mapeador): so pode ser destruida pelo botao azul."""

POLARITY_PINK: int = 1
"""Timbre GRAVE (metade inferior dos buckets de timbre): so pode ser
destruida pelo botao rosa."""

RHYTHM_THREAT_DTYPE: np.dtype = np.dtype(
    [
        ("lane", np.int8),
        ("threat_type", np.int16),
        ("mode_tag", np.int8),
        ("phase", np.int8),
        ("strength", np.float32),
        ("target_hit_time_sec", np.float64),
        ("expire_time_sec", np.float64),
        ("spawn_angle_rad", np.float32),
        ("is_hit", np.bool_),
        ("judgment", np.int8),
        ("packed_handle", np.uint64),
        ("polarity_id", np.uint8),
        ("is_reflected", np.bool_),
        ("is_hold", np.bool_),
        ("duration_sec", np.float32),
        ("hold_grace_timer_sec", np.float32),
        ("will_teleport", np.bool_),
        ("teleport_radius", np.float32),
        ("is_mirage", np.bool_),
        ("nonlinear_approach", np.bool_),
        ("is_focus_target", np.bool_),
        ("focus_health", np.float32),
        ("is_slash_target", np.bool_),
    ]
)
"""Estado ritmico de UMA ameaca viva (o "RhythmThreatPool" da
arquitetura). O MESMO schema serve aos dois modos de jogo: a IA dita o
TEMPO (`target_hit_time_sec`); o modo ativo dita a INTERPRETACAO
espacial dos campos (ver abaixo).

Campos:
    lane/threat_type: escritos pelo `RhythmSpawnerSystem` da engine no
        momento do disparo (contrato `lane_pool_name`/
        `threat_type_pool_name` -- esta pool cumpre os dois papeis, pois
        possui ambos os campos). Interpretacao por modo:
        Defensor -> setor angular da borda (angulo = tau*lane/8);
        Arcade 4K -> coluna da nota (lane % 4).
    mode_tag: MODE_TAG_* -- QUAL juiz e dono desta ameaca. Escrito
        SEMPRE pelo spawner (linhas densas sao reusadas apos
        swap-remove -- um tag obsoleto seria lido como valido).
    strength: intensidade 0..1 extraida pela IA offline (onset strength).
    target_hit_time_sec: instante EXATO (base de tempo de
        `IAudioClock.now_seconds`) do evento ritmico: toque no anel do
        nucleo (Defensor) ou chegada a linha de julgamento (Arcade). E
        contra este campo que os JudgmentSystems medem o delta do input.
    expire_time_sec: telemetria (o proprio instante da batida); tambem
        usado como fim do cluster de Scratch do Arcade 4K (ver `is_hold`).
    spawn_angle_rad: Defensor: angulo (tela, y para baixo) da borda onde
        nasceu, comparado com a mira 360. Arcade 4K: orientacao
        visual/telemetria. Captura Orbital (Defensor): apos a captura,
        REUTILIZADO como o OFFSET ANGULAR FIXO da orbita (congelado no
        angulo de spawn) -- o `OrbitalCaptureSystem` soma
        `angular_speed * agora_efetivo` a ele a cada frame, entao
        escudos capturados em momentos diferentes mantem seu
        espacamento relativo enquanto giram juntos.
    phase: PHASE_* -- normalmente PHASE_LETHAL (default de toda ameaca
        desde o spawn). Defensor -- Captura Orbital: um Parry Perfeito
        num tipo "orbit" grava PHASE_ORBITING (ver a constante) em vez
        de destruir/refletir.
    is_hit: marcada True quando o jogador converte a ameaca com input
        correto -- o restante do frame ignora a linha, ja com destruicao
        enfileirada para o flush.
    judgment: JUDGMENT_* -- toda ameaca termina com exatamente UM
        veredito; sistemas so agem sobre linhas ainda JUDGMENT_PENDING,
        o que impede dupla contagem no mesmo frame.
    packed_handle: `PackedEntityId` (uint64 primitivo) da propria
        entidade, gravado no spawn -- padrao da engine (ver
        `handles.py`/`DungeonStreamingSystem`) para que qualquer sistema
        possa chamar `world.destroy_entity` sem instanciar
        `EntityHandle`.
    polarity_id: POLARITY_BLUE/POLARITY_PINK (Defensor, opt-in via
        "polarity" em `active_modifiers`). Derivada da METADE do bucket de timbre que
        `assign_lanes` ja atribui a `lane` -- zero custo extra de
        analise: o mesmo dado que decide a cor no Arcade decide a
        polaridade no Defensor.
    is_reflected: Parry Perfeito -- True apos um acerto PERFECT numa
        ameaca pesada refletir seu vetor de volta para fora; enquanto
        True, a ameaca muda de "vitima" para "arma" (colide com outras
        ameacas pendentes, destruindo-as, via `ParryImpactSystem`).
    is_hold: nota de Scratch do Arcade 4K (cluster de pesadas fundido
        pelo `lane_choreography`): exige energia de mouse continua entre
        `target_hit_time_sec` (inicio) e `expire_time_sec` (fim do
        cluster) -- julgada por `ScratchJudgmentSystem`, nao pelo
        `LaneJudgmentSystem` comum.
    duration_sec: Notas Longas (Holds) genericas -- `> 0.0` marca a linha
        como uma nota de HOLD cuja janela de sustentacao vai de
        `target_hit_time_sec` (inicio, "Fase 1") ate
        `target_hit_time_sec + duration_sec` (fim, "Fase 2"); `== 0.0`
        (default de pool zerada) e uma nota comum. NAO existe um campo
        `threat_type` novo para isso -- o schema ja tem um
        (`threat_type`, int16, basic/heavy) desde a sessao anterior, e
        REUTILIZAMOS ele: Holds do Defensor sao ameacas HEAVY spawnadas
        com `duration_sec>0` (opt-in via "holds" em `HertzConfig.active_modifiers`),
        nao um terceiro tipo. Distinto do `is_hold` ja existente (notas
        de Scratch do Arcade 4K: sustentacao por ENERGIA CONTINUA de
        mouse, julgadas por `ScratchJudgmentSystem`) -- os dois campos
        coexistem porque representam mecanicas de sustentacao DIFERENTES
        (uma por eixo continuo, a outra por press+hold de acao/mira)
        julgadas por sistemas diferentes; ver o `JudgmentSystem` do
        Defensor para o ciclo Start/Sustain/Break do `duration_sec`.
    hold_grace_timer_sec: Tolerancia Organica -- Hold Forgiveness ("Coyote
        Time" para micro-tremores de mao): so relevante numa linha
        ENGAJADA (`duration_sec>0`, Fase 2/Sustain). Acumula `delta_time`
        de FRAME (nao o `IAudioClock`, e "game feel" -- mesmo criterio
        dos timers de i-frame/cooldown do `PlayerInputSystem`) a cada
        frame em que a mira escapa do cone `hold_aim_tolerance_rad` OU o
        gatilho e solto; volta a `0.0` no frame seguinte em que a
        sustentacao correta e retomada. So vira MISS de verdade (quebra
        do Hold) se ultrapassar `HertzConfig.hold_grace_seconds` (0.15s
        por padrao) SEM retomar -- humanos nao conseguem manter mira+
        gatilho perfeitamente estaticos por segundos continuos; ver
        `JudgmentSystem._sweep_engaged_holds`.
    will_teleport: Rogue-lite -- Mind Games "Buraco de Minhoca"
        (opt-in via "wormholes" em `HertzConfig.active_modifiers`):
        marca uma ameaca do Defensor que, ao cruzar `teleport_radius`
        rumo ao nucleo, tem sua posicao refletida pelo centro E sua
        velocidade negada pelo `MindGamesSystem` -- matematicamente
        EQUIVALENTE a girar `spawn_angle_rad` por PI mantendo o MESMO
        raio e a MESMA velocidade radial de aproximacao (reflexao por
        um ponto preserva distancia ao centro, so inverte o lado). A
        ameaca reaparece INSTANTANEAMENTE do lado OPOSTO do circulo,
        ainda convergindo pro nucleo na mesma velocidade -- o
        `target_hit_time_sec` original continua o instante CORRETO de
        impacto (a trajetoria raio-por-tempo nao muda, so o angulo);
        so' a DIRECAO que o jogador precisa mirar inverte de surpresa.
        Consumida (volta a False) no proprio frame em que dispara -- e
        um evento ONE-SHOT por ameaca, nao um estado continuo.
    teleport_radius: raio (mesma unidade de `spawn_radius`/
        `current_judgment_radius`) no qual o Buraco de Minhoca desta
        linha dispara; escrito pelo spawner a partir de
        `HertzConfig.wormhole_teleport_radius` quando `will_teleport`
        e marcado.
    is_mirage: Rogue-lite -- Mind Games "Ameaca Fantasma" (opt-in via
        "mirages" em `HertzConfig.active_modifiers`): a ameaca segue a
        fisica normalmente, mas o `JudgmentSystem` a destroi em
        silencio (sem MISS, sem quebrar combo) assim que faltar menos
        de `HertzConfig.mirage_vanish_seconds` para o impacto. Se o
        jogador acertar o tiro ANTES do desaparecimento, o acerto e
        forcado para JUDGMENT_MISS em vez de PERFECT/GOOD -- e um
        "fantasma", nao pode ser destruido de verdade.
    nonlinear_approach: Rogue-lite -- Mind Games "Efeito Elastico"
        (opt-in via "rubber_band" em `HertzConfig.active_modifiers`):
        o `MindGamesSystem` reprojeta o RAIO desta linha (mantendo
        `spawn_angle_rad` fixo) a cada frame usando uma curva de
        easing sobre a fracao linear de progresso ja percorrida
        (derivada do raio atual, sem precisar de um campo novo de
        "tempo de spawn") -- a ameaca acelera muito ao nascer e freia
        perto do nucleo, em vez do avanco linear padrao do
        `PhysicsSystem`.
    is_focus_target: Raio de Foco/"Microondas" (Defensor, opt-in via
        "focus_beam" em `HertzConfig.active_modifiers`): ameaca que
        NAO aceita clique (excluida das candidatas de
        `JudgmentSystem._try_player_hit`) -- em vez disso, o jogador
        precisa manter a mira travada sobre ela (`focus_tolerance_rad`)
        enquanto seu raio atual estiver dentro da faixa de foco
        (`HertzConfig.focus_radius_tolerance_px` em torno do anel de
        julgamento) para `focus_health` chegar a zero (ver
        `JudgmentSystem._run_focus_beam_check`). Textura procedural
        distinta (hexagono pulsante, `TEX_THREAT_FOCUS_HEXAGON`) --
        `HBPygameRenderer.draw_batch` desenha a forma, `JudgmentSystem`
        escreve a escala pulsante direto no `transform` a cada frame
        (mesmo criterio Zero-GC do Pulso do Nucleo no Modo Falange).
    focus_health: segundos RESTANTES de foco sustentado ate o bloqueio
        automatico (contador regressivo, nao um relogio) -- inicializado
        em `HertzConfig.focus_target_seconds` no spawn. Decrementado por
        `delta_time` de frame (e' "game feel" de sustentacao, mesmo
        criterio de `hold_grace_timer_sec`) so' enquanto a mira estiver
        em cima E o raio dentro da faixa; sair da mira ANTES de chegar a
        zero reseta pra `focus_target_seconds` de novo (punicao maxima:
        nenhum progresso parcial sobrevive a uma desmirada).
    is_slash_target: A Lamina/"Radial Slash" (Defensor, opt-in via
        "radial_slash" em `HertzConfig.active_modifiers`): ameaca que
        IGNORA cliques (excluida das candidatas de `_try_player_hit`,
        mesmo criterio de `is_focus_target`) -- so aceita um ARRASTO
        rapido do mouse (`GameState.mouse_angle_previous` -> mira atual)
        cuja velocidade angular exceda `HertzConfig.
        slash_min_angular_speed_rad_per_sec` E cujo arco varrido cruze
        `spawn_angle_rad`, dentro da janela PERFECT (ver
        `JudgmentSystem._run_slash_check`). Textura procedural distinta
        (barra rotacionada tangente ao anel, `TEX_THREAT_SLASH` --
        `rotation_rad` gravado como `spawn_angle_rad + PI/2` no spawn,
        primeiro consumidor real de `rotations_rad` em `draw_batch`).
"""

PLAYER_STATE_DTYPE: np.dtype = np.dtype(
    [
        ("aim_angle_rad", np.float32),
        ("dash_cooldown_sec", np.float32),
        ("iframe_timer_sec", np.float32),
        ("gun_jam_sec", np.float32),
    ]
)
"""Estado do nucleo/jogador (uma unica linha anexada a entidade do
jogador; manter em pool SoA -- e nao em atributos de um objeto Player --
segue o mesmo padrao de todo o resto do gameplay).

Campos:
    aim_angle_rad: mira 360 atual (coordenadas de tela, y para baixo).
    dash_cooldown_sec: tempo restante ate poder dar Dash de novo.
    iframe_timer_sec: janela de invencibilidade restante do Dash atual.
    gun_jam_sec: arma EMPERRADA (misfire punitivo do Defensor): enquanto
        > 0, o gatilho so produz o clique seco -- nenhum tiro sai.
"""
