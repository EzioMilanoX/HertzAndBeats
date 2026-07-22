"""
Efeitos sonoros sintetizados deterministicamente (numpy + stdlib wave),
como as faixas: nenhum .wav de SFX e versionado -- qualquer maquina
reconstroi os mesmos sons no primeiro build.

Gun Sync: o canhao do tiro certeiro E percussao (bumbo pesado + estalo),
desenhado para se fundir a trilha; o clique seco do misfire e o "tec" de
arma emperrada; o tap fantasma e um tick discreto de batucada livre.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from hertzbeats.audio.demo_track_synth import write_wav

SFX_SAMPLE_RATE = 44100
SFX_CANNON = "data/sfx/cannon.wav"
SFX_CLICK = "data/sfx/click.wav"
SFX_TAP = "data/sfx/tap.wav"
SFX_DEFLECT = "data/sfx/deflect.wav"
SFX_PARRY = "data/sfx/parry.wav"
SFX_HOLD_ENGAGE = "data/sfx/hold_engage.wav"
SFX_HOLD_BREAK = "data/sfx/hold_break.wav"
SFX_SHIELD_BREAK = "data/sfx/shield_break.wav"
SFX_BOMB = "data/sfx/bomb.wav"
SFX_HEAL = "data/sfx/heal.wav"
SFX_MISS = "data/sfx/miss.wav"
"""Auditoria de Juice: nem o MISS por tempo (Defensor) nem o dano no
nucleo tocavam NENHUM som antes disto -- so tremor/texto. Thud seco e
curto, claramente um erro (distinto do "clique" do misfire, que e sobre
a ARMA emperrar, nao sobre errar o tempo)."""

SFX_ANNOUNCER_COMBO = "data/sfx/announcer_combo.wav"
SFX_ANNOUNCER_RANK = "data/sfx/announcer_rank.wav"
"""Meta-Jogo -- Announcer: o jogo inteiro sintetiza audio proceduralmente
(numpy puro, Zero-GC/deterministico, sem TTS nem gravacao -- ver
`hertzbeats/audio/demo_track_synth.py`). Sem motor de texto-pra-fala
disponivel no ambiente, "voz do Announcer" vira um STINGER sintetizado
(nao fala real) nos mesmos 2 marcos do pedido original:
`SFX_ANNOUNCER_COMBO` ao cruzar `ANNOUNCER_COMBO_THRESHOLD` de combo
(`HertzGameLoop._sync_announcer`), `SFX_ANNOUNCER_RANK` ao entrar em
`FLOW_RESULTS` com Rank S ou melhor."""

_PITCH_VARIANT_COUNT = 5
"""Combo Pitch Shift: quantas variantes de afinacao existem por som de
acerto -- `JudgmentSystem`/`LaneJudgmentSystem` escolhem o indice
`min(combo // 10, _PITCH_VARIANT_COUNT - 1)`, nunca pitch-shiftando ao
vivo (`pygame.mixer` nao suporta)."""

SFX_CANNON_VARIANTS = tuple(
    SFX_CANNON if i == 0 else f"data/sfx/cannon_{i}.wav" for i in range(_PITCH_VARIANT_COUNT)
)
"""5 variantes do canhao (Defensor), cada uma um semitom mais aguda que
a anterior -- a variante 0 e o PROPRIO `SFX_CANNON` de sempre (nenhuma
mudanca para quem so olha o combo baixo)."""

SFX_NOTE_HIT_VARIANTS = tuple(f"data/sfx/note_hit_{i}.wav" for i in range(_PITCH_VARIANT_COUNT))
"""5 variantes do acerto de nota do Arcade 4K -- ate agora um PERFECT/GOOD
de coluna nao tocava som nenhum (so o ghost tap tinha som); fecha essa
lacuna com o MESMO tratamento de Combo Pitch Shift do canhao."""

_SEMITONE_RATIO = 2.0 ** (1.0 / 12.0)


def _cannon(sample_rate: int, pitch_ratio: float = 1.0) -> np.ndarray:
    """Tiro no tempo: bumbo profundo (sweep 160->40 Hz) + estalo curto --
    percussao que se soma a musica. `pitch_ratio` escala TODAS as
    frequencias (Combo Pitch Shift: gerar 5 variantes semitom a semitom
    no CARREGAMENTO, nunca em tempo real)."""
    length = int(0.22 * sample_rate)
    t = np.arange(length) / sample_rate
    body = np.exp(-t * 16.0) * np.sin(
        2 * np.pi * np.cumsum(160.0 * pitch_ratio * np.exp(-t * 24.0) + 40.0 * pitch_ratio) / sample_rate
    )
    snap = np.exp(-t * 220.0) * np.sin(
        2 * np.pi * 2400.0 * pitch_ratio * t + np.sin(2 * np.pi * 700.0 * pitch_ratio * t) * 6.0
    )
    mix = 0.9 * body + 0.25 * snap
    return mix / (np.max(np.abs(mix)) * 1.05)


def _note_hit(sample_rate: int, pitch_ratio: float = 1.0) -> np.ndarray:
    """Acerto de nota do Arcade 4K: blip curto e limpo (envelope
    exponencial sobre um tom + o 2o harmonico), bem distinto do "tick"
    quase inaudivel do ghost tap. `pitch_ratio`: ver `_cannon`."""
    length = int(0.09 * sample_rate)
    t = np.arange(length) / sample_rate
    tone = np.exp(-t * 30.0) * (
        np.sin(2 * np.pi * 720.0 * pitch_ratio * t) + 0.4 * np.sin(2 * np.pi * 1440.0 * pitch_ratio * t)
    )
    return tone / (np.max(np.abs(tone)) * 1.05)


def _miss(sample_rate: int) -> np.ndarray:
    """MISS por tempo / dano no nucleo: thud grave e seco -- claramente
    um erro, distinto do "clique" metalico do misfire (sobre a arma
    emperrar, nao sobre o tempo)."""
    length = int(0.16 * sample_rate)
    t = np.arange(length) / sample_rate
    thud = np.exp(-t * 20.0) * np.sin(2 * np.pi * np.cumsum(120.0 * np.exp(-t * 30.0) + 45.0) / sample_rate)
    return thud / (np.max(np.abs(thud)) * 1.05)


def _click(sample_rate: int) -> np.ndarray:
    """Misfire: 'tec' seco e metalico de gatilho emperrado."""
    length = int(0.05 * sample_rate)
    t = np.arange(length) / sample_rate
    mix = np.exp(-t * 300.0) * np.sin(2 * np.pi * 1900.0 * t + np.sin(2 * np.pi * 517.0 * t) * 9.0)
    return mix / (np.max(np.abs(mix)) * 1.05)


def _tap(sample_rate: int) -> np.ndarray:
    """Ghost tap: tick suave e abafado (batucada livre sem punicao)."""
    length = int(0.03 * sample_rate)
    t = np.arange(length) / sample_rate
    mix = np.exp(-t * 180.0) * np.sin(2 * np.pi * 620.0 * t)
    return mix / (np.max(np.abs(mix)) * 1.05)


def _deflect(sample_rate: int) -> np.ndarray:
    """Deflect (Polaridade): tempo e mira certos, cor errada -- ping
    metalico curto e agudo, sem peso (nao pune, so avisa "quase")."""
    length = int(0.08 * sample_rate)
    t = np.arange(length) / sample_rate
    mix = np.exp(-t * 90.0) * np.sin(2 * np.pi * 1500.0 * t + np.sin(2 * np.pi * 900.0 * t) * 4.0)
    return mix / (np.max(np.abs(mix)) * 1.05)


def _parry(sample_rate: int) -> np.ndarray:
    """Parry Perfeito: impacto mais pesado que o canhao normal -- a
    inversao de velocidade de uma ameaca pesada merece o SFX mais
    dramatico do Defensor."""
    length = int(0.30 * sample_rate)
    t = np.arange(length) / sample_rate
    body = np.exp(-t * 10.0) * np.sin(
        2 * np.pi * np.cumsum(220.0 * np.exp(-t * 18.0) + 55.0) / sample_rate
    )
    ring = np.exp(-t * 6.0) * np.sin(2 * np.pi * 1800.0 * t)
    mix = 0.85 * body + 0.35 * ring
    return mix / (np.max(np.abs(mix)) * 1.05)


def _hold_engage(sample_rate: int) -> np.ndarray:
    """Notas Longas -- Fase 1 (Start) engajada: zumbido curto que
    "trava", como um motor comecando a girar (sustentado ate a Fase 2
    resolver)."""
    length = int(0.12 * sample_rate)
    t = np.arange(length) / sample_rate
    mix = (1.0 - np.exp(-t * 40.0)) * np.sin(2 * np.pi * 220.0 * t)
    return mix / (np.max(np.abs(mix)) * 1.05)


def _hold_break(sample_rate: int) -> np.ndarray:
    """Notas Longas -- Fase 2 quebrada: queda abrupta de tom (o
    "motor" solta), acompanhando o Camera Shake/Rumble do break."""
    length = int(0.18 * sample_rate)
    t = np.arange(length) / sample_rate
    mix = np.exp(-t * 14.0) * np.sin(
        2 * np.pi * np.cumsum(340.0 * np.exp(-t * 22.0) + 60.0) / sample_rate
    )
    return mix / (np.max(np.abs(mix)) * 1.05)


def _shield_break(sample_rate: int) -> np.ndarray:
    """Shield esgotado (Arcade 4K): estilhaco de vidro -- ruido
    filtrado de decaimento rapido somado a um estalo agudo, marcando
    que a falha finalmente custou vida de verdade."""
    length = int(0.28 * sample_rate)
    rng = np.random.RandomState(4090)
    noise = rng.uniform(-1.0, 1.0, size=length)
    t = np.arange(length) / sample_rate
    shard = np.exp(-t * 9.0) * np.sin(2 * np.pi * 3200.0 * t)
    mix = np.exp(-t * 18.0) * noise * 0.7 + shard * 0.5
    return mix / (np.max(np.abs(mix)) * 1.05)


def _bomb(sample_rate: int) -> np.ndarray:
    """Bomba (Arcade 4K): explosao curta e suja -- ruido grave
    filtrado + thump abafado, claramente um erro (nao um acerto)."""
    length = int(0.32 * sample_rate)
    rng = np.random.RandomState(666)
    noise = rng.uniform(-1.0, 1.0, size=length)
    t = np.arange(length) / sample_rate
    thump = np.exp(-t * 12.0) * np.sin(
        2 * np.pi * np.cumsum(90.0 * np.exp(-t * 20.0) + 35.0) / sample_rate
    )
    mix = np.exp(-t * 10.0) * noise * 0.55 + thump * 0.7
    return mix / (np.max(np.abs(mix)) * 1.05)


def _heal(sample_rate: int) -> np.ndarray:
    """Nota de Cura: sino ascendente suave (2 harmonicos subindo) --
    contraste deliberado com o Bomba/thump grave, remete a "recuperar"."""
    length = int(0.25 * sample_rate)
    t = np.arange(length) / sample_rate
    sweep = np.cumsum(520.0 + 260.0 * (t / t[-1])) / sample_rate
    tone = np.exp(-t * 5.0) * (np.sin(2 * np.pi * sweep) + 0.5 * np.sin(2 * np.pi * 2 * sweep))
    return tone / (np.max(np.abs(tone)) * 1.05)


def _announcer_combo(sample_rate: int) -> np.ndarray:
    """Marco de combo (Announcer -- `ANNOUNCER_COMBO_THRESHOLD`): stinger
    ENERGETICO -- arpejo ascendente de 3 tons (A4->D5->A5) entrando em
    sequencia, cada um com o 2o harmonico por cima -- comunica "subindo",
    sem depender de fala real (ver decisao do usuario -- o jogo inteiro
    sintetiza audio, sem TTS disponivel no ambiente)."""
    length = int(0.5 * sample_rate)
    note_length = length // 3
    mix = np.zeros(length, dtype=np.float64)
    for i, freq in enumerate((440.0, 587.33, 880.0)):  # A4, D5, A5
        start = i * note_length
        seg_t = np.arange(length - start) / sample_rate
        tone = np.exp(-seg_t * 7.0) * (
            np.sin(2 * np.pi * freq * seg_t) + 0.5 * np.sin(2 * np.pi * 2.0 * freq * seg_t)
        )
        mix[start:] += tone * 0.6
    return mix / (np.max(np.abs(mix)) * 1.05)


def _announcer_rank(sample_rate: int) -> np.ndarray:
    """Rank S/SS nos Resultados (Announcer): stinger TRIUNFANTE -- acorde
    maior sustentado (C5-E5-G5 simultaneos), decaimento bem mais LONGO
    que qualquer outro SFX do jogo -- um momento de celebracao na tela
    final, nao uma reacao rapida de gameplay."""
    length = int(1.0 * sample_rate)
    t = np.arange(length) / sample_rate
    mix = np.zeros(length, dtype=np.float64)
    for freq in (523.25, 659.25, 783.99):  # C5, E5, G5
        mix += np.exp(-t * 2.2) * np.sin(2 * np.pi * freq * t)
    return mix / (np.max(np.abs(mix)) * 1.05)


def ensure_sfx() -> None:
    """Garante todos os SFX em data/sfx/ (sintese deterministica, so na
    primeira execucao). Chamado no build, fora do loop de gameplay."""
    for path, synth in (
        (SFX_CANNON, _cannon),
        (SFX_CLICK, _click),
        (SFX_TAP, _tap),
        (SFX_DEFLECT, _deflect),
        (SFX_PARRY, _parry),
        (SFX_HOLD_ENGAGE, _hold_engage),
        (SFX_HOLD_BREAK, _hold_break),
        (SFX_SHIELD_BREAK, _shield_break),
        (SFX_BOMB, _bomb),
        (SFX_HEAL, _heal),
        (SFX_MISS, _miss),
        (SFX_ANNOUNCER_COMBO, _announcer_combo),
        (SFX_ANNOUNCER_RANK, _announcer_rank),
    ):
        if not Path(path).exists():
            write_wav(synth(SFX_SAMPLE_RATE), Path(path), sample_rate=SFX_SAMPLE_RATE)

    # Combo Pitch Shift: 5 variantes cada, um semitom acima da anterior
    # (indice 0 = afinacao original -- `SFX_CANNON_VARIANTS[0]` e o
    # PROPRIO `SFX_CANNON` de sempre, ja gerado no laco acima).
    for i, path in enumerate(SFX_CANNON_VARIANTS):
        if not Path(path).exists():
            write_wav(_cannon(SFX_SAMPLE_RATE, _SEMITONE_RATIO**i), Path(path), sample_rate=SFX_SAMPLE_RATE)
    for i, path in enumerate(SFX_NOTE_HIT_VARIANTS):
        if not Path(path).exists():
            write_wav(_note_hit(SFX_SAMPLE_RATE, _SEMITONE_RATIO**i), Path(path), sample_rate=SFX_SAMPLE_RATE)
