"""Estagio DSP anti-mascaramento: threshold puro, e HPSS+mel+PLP sobre audio sintetico REAL.

Os dois ultimos testes rodam librosa de verdade sobre ~10s de audio
sintetizado -- lentos (~s), mas sao a prova de que a separacao de fontes
resolve o cenario Lo-Fi: um pad de sintetizador ALTO por cima do bumbo
nao pode poluir a grade de pulsos.
"""
import numpy as np
import pytest

from hertzbeats.offline.percussive_extraction import (
    PercussiveOnsetExtractor,
    estimate_bpm_from_pulses,
    select_curve_peaks,
)

# ------------------------------------------------------------------ puros


def test_peak_selection_enforces_interval_and_amplitude():
    # curva com picos fortes a cada 0.5s e ruido fraco entre eles
    frame_rate = 100.0
    times = np.arange(0, 4.0, 1.0 / frame_rate)
    curve = np.zeros_like(times)
    for beat_time in np.arange(0.5, 4.0, 0.5):
        curve[int(beat_time * frame_rate)] = 1.0
    rng_bumps = np.arange(0.25, 4.0, 0.5)  # ruido no meio, 20% da altura
    for bump in rng_bumps:
        curve[int(bump * frame_rate)] = 0.2

    peak_times, peak_heights = select_curve_peaks(
        curve, times, minimum_interval_sec=0.10, min_height_ratio=0.30
    )
    assert np.allclose(peak_times, np.arange(0.5, 4.0, 0.5), atol=0.02)  # so os fortes
    assert np.all(peak_heights >= 0.99)


def test_peak_selection_min_interval_merges_double_hits():
    frame_rate = 100.0
    times = np.arange(0, 2.0, 1.0 / frame_rate)
    curve = np.zeros_like(times)
    curve[100] = 1.0
    curve[106] = 0.9  # 60ms depois: flam/eco -- deve ser engolido
    peak_times, _ = select_curve_peaks(
        curve, times, minimum_interval_sec=0.10, min_height_ratio=0.30
    )
    assert peak_times.shape[0] == 1


def test_bpm_from_pulses_is_median_robust():
    pulses = np.array([1.0, 1.5, 2.0, 2.5, 3.5, 4.0])  # um pulso perdido em 3.0
    assert abs(estimate_bpm_from_pulses(pulses) - 120.0) < 1e-6
    assert estimate_bpm_from_pulses(np.array([1.0])) == 120.0  # fallback


def test_bpm_octave_ambiguity_is_folded_into_musical_range():
    double_time = np.arange(0.0, 6.0, 0.3)  # pulsos a 200/min (PLP no dobro)
    assert abs(estimate_bpm_from_pulses(double_time) - 100.0) < 1e-6
    slow = np.arange(0.0, 20.0, 1.0)  # 60/min: dobra para 120
    assert abs(estimate_bpm_from_pulses(slow) - 120.0) < 1e-6


# ------------------------------------------------- DSP real (librosa)


def _drums_with_loud_pad(bpm=100.0, seconds=10.0, sample_rate=22050, pad_gain=0.9):
    """Bumbo seco a cada batida + PAD harmonico continuo mais ALTO que o
    bumbo (o cenario 'Melatonin': mascaramento por sintetizador)."""
    n = int(seconds * sample_rate)
    t = np.arange(n) / sample_rate
    mix = np.zeros(n)

    beat_period = 60.0 / bpm
    kick_len = int(0.12 * sample_rate)
    tt = np.arange(kick_len) / sample_rate
    kick = np.exp(-tt * 28.0) * np.sin(2 * np.pi * np.cumsum(140.0 * np.exp(-tt * 20.0) + 45.0) / sample_rate)
    for beat_start in np.arange(0.5, seconds - 0.2, beat_period):
        start = int(beat_start * sample_rate)
        mix[start : start + kick_len] += 0.55 * kick[: max(0, min(kick_len, n - start))]

    # pad: acorde sustentado com vibrato lento, MAIS ALTO que o bumbo
    pad = (
        np.sin(2 * np.pi * 220.0 * t)
        + np.sin(2 * np.pi * 277.18 * t)
        + np.sin(2 * np.pi * 329.63 * t)
    ) / 3.0
    pad *= 1.0 + 0.15 * np.sin(2 * np.pi * 0.4 * t)
    mix += pad_gain * pad

    mix /= np.max(np.abs(mix)) * 1.05

    class _Audio:
        samples = mix.astype(np.float32)
        sample_rate_value = sample_rate

    audio = _Audio()
    audio.sample_rate = sample_rate
    return audio


@pytest.mark.slow
def test_pulse_grid_locks_to_kick_despite_loud_pad():
    """REGRESSAO DE MASCARAMENTO: com um pad mais alto que o bumbo, os
    pulsos extraidos ainda devem seguir o periodo do bumbo (0.6s a
    100 BPM) -- HPSS + mel grave descartam o pad antes do PLP."""
    audio = _drums_with_loud_pad(bpm=100.0)
    result = PercussiveOnsetExtractor().extract(audio)

    assert result.pulse_timestamps_seconds.shape[0] >= 8
    gaps = np.diff(result.pulse_timestamps_seconds)
    median_gap = float(np.median(gaps))
    assert abs(median_gap - 0.6) < 0.06, f"gap mediano {median_gap:.3f}s != periodo do bumbo 0.6s"
    assert abs(result.tempo_bpm_estimate - 100.0) < 10.0

    # e os VOTOS percussivos caem perto dos bumbos (nao no pad continuo)
    kick_times = np.arange(0.5, 9.8, 0.6)
    hits = sum(
        1 for onset in result.onset_timestamps_seconds
        if np.min(np.abs(kick_times - onset)) < 0.08
    )
    assert hits >= 0.7 * result.onset_timestamps_seconds.shape[0]


@pytest.mark.slow
def test_extraction_feeds_quantized_beatmap_end_to_end(tmp_path):
    """Pipeline completo com o estagio DSP: beatmap quantizado no periodo
    do bumbo, mesmo sob o pad."""
    import wave

    audio = _drums_with_loud_pad(bpm=100.0, seconds=12.0)
    wav_path = tmp_path / "lofi_mascarada.wav"
    pcm = (audio.samples * np.iinfo(np.int16).max * 0.9).astype(np.int16)
    with wave.open(str(wav_path), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(audio.sample_rate)
        f.writeframes(pcm.tobytes())

    from hertzbeats.offline.beatmap_pipeline import generate_beatmap

    summary = generate_beatmap(
        audio_path=wav_path, output_path=tmp_path / "out.beatmap.json", track_id="lofi",
        min_start_seconds=1.0, end_margin_seconds=0.8, target_density_per_second=1.6,
        min_gap_seconds=0.4,
    )
    assert summary["dsp_stage"] == "percussive-plp"
    assert summary["quantized"] is True
    assert summary["threat_count"] >= 8

    import json
    beatmap = json.loads((tmp_path / "out.beatmap.json").read_text(encoding="utf-8"))
    times = [t["timestamp_seconds"] for t in beatmap["threats"]]
    gaps = np.diff(times)
    half_beat = 0.3  # 100 BPM
    multiples = gaps / half_beat
    near = np.sum(np.abs(multiples - np.round(multiples)) < 0.25)
    assert near >= 0.85 * gaps.shape[0], "notas nao estao na grade do bumbo"
