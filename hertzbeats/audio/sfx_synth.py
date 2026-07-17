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
SFX_GRAZE = "data/sfx/graze.wav"


def _cannon(sample_rate: int) -> np.ndarray:
    """Tiro no tempo: bumbo profundo (sweep 160->40 Hz) + estalo curto --
    percussao que se soma a musica."""
    length = int(0.22 * sample_rate)
    t = np.arange(length) / sample_rate
    body = np.exp(-t * 16.0) * np.sin(
        2 * np.pi * np.cumsum(160.0 * np.exp(-t * 24.0) + 40.0) / sample_rate
    )
    snap = np.exp(-t * 220.0) * np.sin(2 * np.pi * 2400.0 * t + np.sin(2 * np.pi * 700.0 * t) * 6.0)
    mix = 0.9 * body + 0.25 * snap
    return mix / (np.max(np.abs(mix)) * 1.05)


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


def _graze(sample_rate: int) -> np.ndarray:
    """Graze (Touhou): faisca sutil de hi-hat -- ruido determinístico
    (semente fixa) filtrado por envelope curtissimo, nunca chamativo."""
    length = int(0.045 * sample_rate)
    rng = np.random.RandomState(2026)
    noise = rng.uniform(-1.0, 1.0, size=length)
    t = np.arange(length) / sample_rate
    envelope = np.exp(-t * 260.0)
    shimmer = np.sin(2 * np.pi * 7200.0 * t)
    mix = envelope * noise * 0.6 + envelope * shimmer * 0.4
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
        (SFX_GRAZE, _graze),
    ):
        if not Path(path).exists():
            write_wav(synth(SFX_SAMPLE_RATE), Path(path), sample_rate=SFX_SAMPLE_RATE)
