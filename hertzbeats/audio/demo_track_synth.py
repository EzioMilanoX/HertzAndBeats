"""
Sintese DETERMINISTICA das faixas das fases (numpy puro + stdlib wave,
sem librosa). Nenhum .wav e versionado no repositorio: qualquer maquina
reconstroi bit a bit a mesma faixa a partir da especificacao
`{"bpm", "bars", "style"}` da fase -- por isso o beatmap.json gerado
pela IA offline sobre ela permanece valido apos um clone.

Estilos:
    calm     -- bumbo por batida, caixa em 2/4, sem chimbal, sem drops:
                onsets esparsos e limpos (fase introdutoria).
    standard -- bateria completa + drop a cada 8 compassos.
    intense  -- chimbal em colcheias acentuadas, bumbo dobrado no fim de
                cada 4 compassos e drop a cada 4: mapa denso.

Roda 100% fora do loop de gameplay (carregamento/ferramentas offline).
"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Dict, Optional

import numpy as np

DEMO_TRACK_BPM: float = 128.0
DEMO_TRACK_BARS: int = 24
DEMO_TRACK_SAMPLE_RATE: int = 44100

_BASS_PROGRESSION_HZ = (55.0, 43.65, 65.41, 49.0)  # A1, F1, C2, G1 (um por compasso)

_STYLE_PARAMS: Dict[str, Dict] = {
    "calm": {"hats": False, "drop_every_bars": 0, "double_kick_fill": False, "hat_amp": 0.0},
    "standard": {"hats": True, "drop_every_bars": 8, "double_kick_fill": False, "hat_amp": 0.16},
    "intense": {"hats": True, "drop_every_bars": 4, "double_kick_fill": True, "hat_amp": 0.22},
}


def synthesize_track(
    bpm: float,
    bars: int,
    style: str = "standard",
    sample_rate: int = DEMO_TRACK_SAMPLE_RATE,
) -> np.ndarray:
    """Sintetiza uma faixa (mono, float64 em [-1, 1]) com bateria marcada
    para que o extrator de onsets da engine encontre batidas fortes e
    limpas. Drops (acentos de crash + bumbo pesado) rendem onsets de
    strength alta, que o pipeline converte em ameacas pesadas."""
    params = _STYLE_PARAMS[style]
    beat_seconds = 60.0 / bpm
    total_seconds = bars * 4 * beat_seconds
    n_samples = int(total_seconds * sample_rate)
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

    def hat(amplitude: float) -> np.ndarray:
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
    hat_sig = hat(params["hat_amp"]) if params["hats"] else None
    crash_sig = crash()
    drop_every = params["drop_every_bars"]

    for bar in range(bars):
        bar_start = bar * 4 * beat_seconds
        bass_freq = _BASS_PROGRESSION_HZ[bar % len(_BASS_PROGRESSION_HZ)]
        is_drop_bar = drop_every > 0 and bar % drop_every == 0
        is_fill_bar = params["double_kick_fill"] and bar % 4 == 3

        for beat in range(4):
            beat_start = bar_start + beat * beat_seconds
            if is_drop_bar and beat == 0:
                add_at(beat_start, kick_heavy_sig)
                add_at(beat_start, crash_sig)
                add_at(beat_start + beat_seconds * 0.5, kick_sig)
            else:
                add_at(beat_start, kick_sig)
                if is_fill_bar:
                    add_at(beat_start + beat_seconds * 0.5, kick_sig)
            if beat in (1, 3):
                add_at(beat_start, snare_sig)
            if hat_sig is not None:
                add_at(beat_start + beat_seconds * 0.5, hat_sig)

        # baixo continuo em colcheias, envelope curto por nota
        for eighth in range(8):
            note_start = bar_start + eighth * beat_seconds * 0.5
            length = int(beat_seconds * 0.45 * sample_rate)
            tt = np.arange(length) / sample_rate
            envelope = np.minimum(tt * 60.0, 1.0) * np.exp(-tt * 7.0)
            add_at(note_start, 0.22 * envelope * np.sin(2.0 * np.pi * bass_freq * tt))

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


def ensure_track(track_path: str, synth_spec: Optional[Dict]) -> str:
    """Garante que a faixa exista em `track_path`, re-sintetizando-a
    deterministicamente a partir de `synth_spec` se necessario. Sem
    `synth_spec` (faixa do usuario), o arquivo precisa existir."""
    path = Path(track_path)
    if not path.exists():
        if synth_spec is None:
            raise FileNotFoundError(f"faixa de audio nao encontrada: {path}")
        samples = synthesize_track(
            bpm=float(synth_spec["bpm"]),
            bars=int(synth_spec["bars"]),
            style=synth_spec.get("style", "standard"),
        )
        write_wav(samples, path)
    return str(path)


def synthesize_demo_track(
    bpm: float = DEMO_TRACK_BPM,
    bars: int = DEMO_TRACK_BARS,
    sample_rate: int = DEMO_TRACK_SAMPLE_RATE,
) -> np.ndarray:
    """Compat: a faixa demo original e o estilo `standard` em 128 BPM."""
    return synthesize_track(bpm=bpm, bars=bars, style="standard", sample_rate=sample_rate)


def ensure_demo_track(track_path: str) -> str:
    """Compat: garante a faixa demo (estilo `standard`, 128 BPM, 24 compassos)."""
    return ensure_track(track_path, {"bpm": DEMO_TRACK_BPM, "bars": DEMO_TRACK_BARS, "style": "standard"})
