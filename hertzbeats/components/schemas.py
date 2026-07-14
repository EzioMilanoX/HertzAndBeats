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
"""Atravessou o nucleo durante os i-frames de um Dash: nao pune nem
quebra o combo, mas tambem nao pontua."""

RHYTHM_THREAT_DTYPE: np.dtype = np.dtype(
    [
        ("lane", np.int8),
        ("threat_type", np.int16),
        ("strength", np.float32),
        ("target_hit_time_sec", np.float64),
        ("spawn_angle_rad", np.float32),
        ("is_hit", np.bool_),
        ("judgment", np.int8),
        ("packed_handle", np.uint64),
    ]
)
"""Estado ritmico de UMA ameaca radial viva (o "RhythmThreatPool" da
arquitetura).

Campos:
    lane/threat_type: escritos pelo `RhythmSpawnerSystem` da engine no
        momento do disparo (contrato `lane_pool_name`/
        `threat_type_pool_name` -- esta pool cumpre os dois papeis, pois
        possui ambos os campos).
    strength: intensidade 0..1 extraida pela IA offline (onset strength).
    target_hit_time_sec: instante EXATO (base de tempo de
        `IAudioClock.now_seconds`) em que a ameaca toca o anel do
        nucleo. E contra este campo que o `JudgmentSystem` mede o delta
        do input do jogador.
    spawn_angle_rad: angulo (coordenadas de tela, y para baixo) da borda
        onde a ameaca nasceu; comparado com a mira 360 do jogador.
    is_hit: marcada True quando o jogador acerta o tiro/parry -- o
        restante do frame (CollisionSystem/CoreDamageSystem) ignora a
        ameaca, que ja esta com destruicao enfileirada para o flush.
    judgment: JUDGMENT_* -- toda ameaca termina com exatamente UM
        veredito (perfect/good/miss/dodged); sistemas so agem sobre
        linhas ainda JUDGMENT_PENDING, o que impede dupla contagem no
        mesmo frame.
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
