"""
Sintese DETERMINISTICA da faixa demo (numpy puro + stdlib wave, sem
librosa). O arquivo .wav nao e versionado no repositorio: qualquer
maquina reconstroi bit a bit a mesma faixa -- por isso o beatmap.json
gerado pela IA offline sobre ela permanece valido apos um clone.

Roda 100% fora do loop de gameplay (carregamento/ferramentas offline).
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

DEMO_TRACK_BPM: float = 128.0
DEMO_TRACK_BARS: int = 24
DEMO_TRACK_SAMPLE_RATE: int = 44100

_BASS_PROGRESSION_HZ = (55.0, 43.65, 65.41, 49.0)  # A1, F1, C2, G1 (um por compasso)


def synthesize_demo_track(
    bpm: float = DEMO_TRACK_BPM,
    bars: int = DEMO_TRACK_BARS,
    sample_rate: int = DEMO_TRACK_SAMPLE_RATE,
) -> np.ndarray:
    """Sintetiza a faixa demo (mono, float64 em [-1, 1]) com bateria
    marcada -- bumbo em toda batida, caixa nos tempos 2/4, chimbal em
    colcheias suaves e baixo seguindo a progressao -- para que o
    extrator de onsets da engine encontre batidas fortes e limpas.
    A cada 8 compassos o primeiro tempo ganha um acento de "drop"
    (crash + bumbo duplo), rendendo onsets de strength alta que viram
    ameacas pesadas no beatmap.
    """
    beat_seconds = 60.0 / bpm
    total_seconds = bars * 4 * beat_seconds
    n_samples = int(total_seconds * sample_rate)
    t = np.arange(n_samples) / sample_rate
    mix = np.zeros(n_samples, dtype=np.float64)

    def add_at(start_seconds: float, signal: np.ndarray) -> None:
        start = int(start_seconds * sample_rate)
        end = min(start + signal.shape[0], n_samples)
        if start < n_samples:
            mix[start:end] += signal[: end - start]

    def kick(amplitude: float = 0.9) -> np.ndarray:
        length = int(0.14 * sample_rate)
        tt = np.arange(length) / sample_rate
        freq = 150.0 * np.exp(-tt * 18.0) + 45.0
        return amplitude * np.exp(-tt * 22.0) * np.sin(2.0 * np.pi * np.cumsum(freq) / sample_rate)

    def snare(amplitude: float = 0.55) -> np.ndarray:
        length = int(0.09 * sample_rate)
        tt = np.arange(length) / sample_rate
        # ruido deterministico: seno de alta frequencia com fase caotica fixa
        noise = np.sin(2.0 * np.pi * 3987.0 * tt + np.sin(2.0 * np.pi * 977.0 * tt) * 8.0)
        tone = 0.4 * np.sin(2.0 * np.pi * 190.0 * tt)
        return amplitude * np.exp(-tt * 40.0) * (noise * 0.7 + tone)

    def hat(amplitude: float = 0.16) -> np.ndarray:
        length = int(0.03 * sample_rate)
        tt = np.arange(length) / sample_rate
        noise = np.sin(2.0 * np.pi * 9123.0 * tt + np.sin(2.0 * np.pi * 3313.0 * tt) * 11.0)
        return amplitude * np.exp(-tt * 90.0) * noise

    def crash(amplitude: float = 0.5) -> np.ndarray:
        length = int(0.6 * sample_rate)
        tt = np.arange(length) / sample_rate
        noise = np.sin(2.0 * np.pi * 6733.0 * tt + np.sin(2.0 * np.pi * 2141.0 * tt) * 13.0)
        return amplitude * np.exp(-tt * 6.0) * noise

    kick_sig = kick()
    kick_heavy_sig = kick(1.0)
    snare_sig = snare()
    hat_sig = hat()
    crash_sig = crash()

    for bar in range(bars):
        bar_start = bar * 4 * beat_seconds
        bass_freq = _BASS_PROGRESSION_HZ[bar % len(_BASS_PROGRESSION_HZ)]
        is_drop_bar = bar % 8 == 0

        for beat in range(4):
            beat_start = bar_start + beat * beat_seconds
            if is_drop_bar and beat == 0:
                add_at(beat_start, kick_heavy_sig)
                add_at(beat_start, crash_sig)
                add_at(beat_start + beat_seconds * 0.5, kick_sig)
            else:
                add_at(beat_start, kick_sig)
            if beat in (1, 3):
                add_at(beat_start, snare_sig)
            add_at(beat_start + beat_seconds * 0.5, hat_sig)

        # baixo continuo em colcheias, envelope curto por nota
        for eighth in range(8):
            note_start = bar_start + eighth * beat_seconds * 0.5
            length = int(beat_seconds * 0.45 * sample_rate)
            tt = np.arange(length) / sample_rate
            envelope = np.minimum(tt * 60.0, 1.0) * np.exp(-tt * 7.0)
            add_at(note_start, 0.22 * envelope * np.sin(2.0 * np.pi * bass_freq * tt))

    del t
    peak = np.max(np.abs(mix))
    if peak > 0.0:
        mix /= peak * 1.1
    return mix


def write_wav(samples: np.ndarray, destination: Path, sample_rate: int = DEMO_TRACK_SAMPLE_RATE) -> None:
    """Grava `samples` (float em [-1, 1]) como WAV mono 16-bit."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pcm = (samples * np.iinfo(np.int16).max).astype(np.int16)
    with wave.open(str(destination), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())


def ensure_demo_track(track_path: str) -> str:
    """Garante que a faixa demo exista em `track_path`, re-sintetizando-a
    deterministicamente se necessario. Retorna o caminho."""
    path = Path(track_path)
    if not path.exists():
        write_wav(synthesize_demo_track(), path)
    return str(path)
