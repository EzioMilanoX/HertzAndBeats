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

RHYTHM_THREAT_DTYPE: np.dtype = np.dtype(
    [
        ("lane", np.int8),
        ("threat_type", np.int16),
        ("strength", np.float32),
        ("target_hit_time_sec", np.float64),
        ("expire_time_sec", np.float64),
        ("spawn_angle_rad", np.float32),
        ("is_hit", np.bool_),
        ("judgment", np.int8),
        ("packed_handle", np.uint64),
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
"""

PLAYER_STATE_DTYPE: np.dtype = np.dtype(
    [
        ("aim_angle_rad", np.float32),
        ("dash_cooldown_sec", np.float32),
        ("iframe_timer_sec", np.float32),
    ]
)
"""Estado do nucleo/jogador (uma unica linha anexada a entidade do
jogador; manter em pool SoA -- e nao em atributos de um objeto Player --
segue o mesmo padrao de todo o resto do gameplay).

Campos:
    aim_angle_rad: mira 360 atual (coordenadas de tela, y para baixo).
    dash_cooldown_sec: tempo restante ate poder dar Dash de novo.
    iframe_timer_sec: janela de invencibilidade restante do Dash atual.
"""
