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
quebra o combo, mas tambem nao pontua (no modo Sobrevivencia, pontua
como sobrevivida)."""

JUDGMENT_SURVIVED: int = 5
"""Modo Sobrevivencia: a ameaca varreu a arena e expirou sem tocar o
jogador -- pontua e estende o combo."""

MODE_TAG_DEFENDER: int = 0
"""Ameaca radial (julgada por mira + tempo)."""

MODE_TAG_SURVIVAL: int = 1
"""Parede de som (julgada por colisao/expiracao)."""

MODE_TAG_LANES: int = 2
"""Nota de coluna (julgada por tecla + tempo)."""

PHASE_WARNING: int = 0
"""Fase de TELEGRAPH de uma parede de som: linha-guia translucida
piscando, IGNORADA pela colisao (hitbox com layer/mask 0)."""

PHASE_LETHAL: int = 1
"""Fase letal: no instante do onset a parede fica solida e a colisao
passa a valer."""

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
        ("has_grazed", np.bool_),
    ]
)
"""Estado ritmico de UMA ameaca viva (o "RhythmThreatPool" da
arquitetura). O MESMO schema serve aos tres modos de jogo: a IA dita o
TEMPO (`target_hit_time_sec`); o modo ativo dita a INTERPRETACAO
espacial dos campos (ver abaixo).

Campos:
    lane/threat_type: escritos pelo `RhythmSpawnerSystem` da engine no
        momento do disparo (contrato `lane_pool_name`/
        `threat_type_pool_name` -- esta pool cumpre os dois papeis, pois
        possui ambos os campos). Interpretacao por modo:
        Defensor -> setor angular da borda (angulo = tau*lane/8);
        Sobrevivencia -> eixo/borda da varredura (lane % 4);
        Arcade 4K -> coluna da nota (lane % 4).
    mode_tag: MODE_TAG_* -- QUAL juiz e dono desta ameaca. No modo
        Hibrido, ameacas radiais e paredes coexistem na MESMA pool;
        cada juiz filtra pelo seu tag (mascara vetorizada) e nunca toca
        as ameacas do outro. Escrito SEMPRE pelo spawner (linhas densas
        sao reusadas apos swap-remove -- um tag obsoleto seria lido como
        valido).
    strength: intensidade 0..1 extraida pela IA offline (onset strength).
    target_hit_time_sec: instante EXATO (base de tempo de
        `IAudioClock.now_seconds`) do evento ritmico: toque no anel do
        nucleo (Defensor), cruzamento do centro da arena
        (Sobrevivencia) ou chegada a linha de julgamento (Arcade). E
        contra este campo que os JudgmentSystems medem o delta do input.
    expire_time_sec: instante em que a ameaca deixa de ser relevante
        (Sobrevivencia: varredura saiu da arena -> vira SURVIVED se
        ninguem foi atingido). Nos demais modos, o proprio instante da
        batida (telemetria).
    spawn_angle_rad: Defensor: angulo (tela, y para baixo) da borda onde
        nasceu, comparado com a mira 360. Demais modos: orientacao
        visual/telemetria.
    phase: PHASE_* -- ciclo telegraph->letal das paredes de som
        (Sobrevivencia/Hibrido): nascem como AVISO (colisao desligada
        via layer/mask 0) e viram letais exatamente no onset. Ameacas
        radiais e notas nascem direto em PHASE_LETHAL.
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
        `polarity_enabled`). Derivada da METADE do bucket de timbre que
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
    has_grazed: Sobrevivencia -- True apos o `GrazeSystem` ja ter
        contabilizado esta parede como "raspada" (impede pontuar Graze
        repetidamente por quadro enquanto o jogador permanece na faixa).
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
