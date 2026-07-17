"""
Extracao percussiva com separacao de fontes -- o estagio DSP do mapeador.

Problema que resolve ("frequency masking"): em Lo-Fi e faixas densas,
pads/sintetizadores altos e vocais mascaram bumbo/caixa no envelope de
onset de banda cheia -- o extrator generico devolve falsos positivos
harmonicos e o beatmap sai poluido e fora do ritmo.

Pipeline sequencial (offline; qualidade > custo):

    1. HPSS (Harmonic-Percussive Source Separation):
       `librosa.effects.hpss(y)` separa o sinal; SOMENTE `y_percussive`
       segue adiante -- vocais, pads e sustains harmonicos morrem aqui.
    2. Mel-espectrograma grave/medio (`fmax` ~250 Hz):
       o envelope de onset e calculado num espectrograma focado em
       bumbo (40-100 Hz) e corpo de caixa (150-250 Hz), ignorando
       chimbais ruidosos de banda alta.
    3. PLP (Predominant Local Pulse):
       `librosa.beat.plp(onset_envelope=...)` transforma o envelope em
       uma curva de pulso dominante LOCAL -- resiliente a acelerandos e
       sincopas que quebram um beat-tracker global.
    4. Threshold inteligente sobre os picos
       (`scipy.signal.find_peaks`): intervalo minimo entre picos
       (`minimum_interval_sec`) E altura minima relativa ao pico maximo
       da curva -- pulsos residuais fracos (ruido) sao descartados.

A GRADE do mapeador passa a vir dos picos do PLP; os "votos" de energia
vem dos picos do envelope percussivo grave. As funcoes de pico/tempo sao
PURAS (testaveis sem librosa); librosa e importado lazy dentro de
`extract` -- este modulo pertence ao pacote offline e nunca roda no loop
de gameplay.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np
from scipy.signal import find_peaks


@dataclass(frozen=True)
class PercussiveExtractionResult:
    """Saida do estagio DSP, pronta para o mapeador (grade + votos).

    Atributos:
        pulse_timestamps_seconds: instantes dos pulsos dominantes (picos
            filtrados do PLP) -- a GRADE ritmica do mapa.
        pulse_strengths: altura normalizada de cada pulso (0..1).
        onset_timestamps_seconds: picos do envelope percussivo grave --
            os VOTOS de energia por ponto da grade.
        onset_strengths: altura normalizada de cada onset (0..1).
        tempo_bpm_estimate: BPM estimado da mediana dos intervalos entre
            pulsos (telemetria/campo `bpm` do beatmap).
    """

    pulse_timestamps_seconds: np.ndarray
    pulse_strengths: np.ndarray
    onset_timestamps_seconds: np.ndarray
    onset_strengths: np.ndarray
    tempo_bpm_estimate: float


# ------------------------------------------------------------------ puras

def select_curve_peaks(
    curve: np.ndarray,
    frame_times: np.ndarray,
    minimum_interval_sec: float,
    min_height_ratio: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Etapa 4 (threshold inteligente), pura: picos de `curve` com
    espacamento minimo em SEGUNDOS (convertido para frames pela taxa real
    da curva) e altura minima `min_height_ratio * max(curve)`. Retorna
    `(tempos, alturas_normalizadas)`."""
    curve = np.asarray(curve, dtype=np.float64)
    frame_times = np.asarray(frame_times, dtype=np.float64)
    if curve.shape[0] < 3:
        return np.zeros(0), np.zeros(0)
    peak_value = float(curve.max())
    if peak_value <= 0.0:
        return np.zeros(0), np.zeros(0)

    frame_period = float(np.median(np.diff(frame_times))) if frame_times.shape[0] > 1 else 1.0
    distance_frames = max(1, int(round(minimum_interval_sec / max(frame_period, 1e-9))))
    peak_indices, _ = find_peaks(
        curve, distance=distance_frames, height=min_height_ratio * peak_value
    )
    return frame_times[peak_indices], curve[peak_indices] / peak_value


def estimate_bpm_from_pulses(pulse_times: np.ndarray, fallback_bpm: float = 120.0) -> float:
    """BPM pela MEDIANA dos intervalos entre pulsos consecutivos --
    robusta a um ou outro pulso perdido (a media nao e). O valor e
    dobrado/dividido por oitavas ate a faixa musical usual [70, 180):
    o PLP pode travar no dobro/metade do tempo percebido (ambiguidade
    classica de oitava), o que nao afeta a grade (mesmos pulsos), so o
    METADADO de bpm."""
    pulse_times = np.asarray(pulse_times, dtype=np.float64)
    if pulse_times.shape[0] < 2:
        return fallback_bpm
    median_gap = float(np.median(np.diff(pulse_times)))
    if median_gap <= 0.0:
        return fallback_bpm
    bpm = 60.0 / median_gap
    while bpm >= 180.0:
        bpm /= 2.0
    while bpm < 70.0:
        bpm *= 2.0
    return bpm


# ------------------------------------------------------------ com librosa

class PercussiveOnsetExtractor:
    """Extrator DSP das 4 etapas (ver docstring do modulo). Parametros
    sao afinacao de qualidade, nao de gameplay."""

    def __init__(
        self,
        fmax_hz: float = 250.0,
        n_mels: int = 40,
        hop_length: int = 512,
        plp_tempo_min: float = 40.0,
        plp_tempo_max: float = 220.0,
        minimum_interval_sec: float = 0.10,
        pulse_min_height_ratio: float = 0.30,
        onset_min_height_ratio: float = 0.12,
    ) -> None:
        """`fmax_hz` limita o espectrograma a graves/medios (bumbo +
        corpo de caixa); `pulse_min_height_ratio` e o threshold de
        amplitude da etapa 4; `minimum_interval_sec` o de intervalo."""
        self._fmax_hz = float(fmax_hz)
        self._n_mels = int(n_mels)
        self._hop_length = int(hop_length)
        self._plp_tempo_min = float(plp_tempo_min)
        self._plp_tempo_max = float(plp_tempo_max)
        self._minimum_interval_sec = float(minimum_interval_sec)
        self._pulse_min_height_ratio = float(pulse_min_height_ratio)
        self._onset_min_height_ratio = float(onset_min_height_ratio)

    def extract(self, audio) -> PercussiveExtractionResult:
        """Executa o pipeline 1-4 sobre um `LoadedAudio` (samples mono +
        sample_rate) e retorna grade (pulsos) + votos (onsets)."""
        import librosa  # offline-only, lazy

        samples = np.asarray(audio.samples, dtype=np.float32)
        sample_rate = int(audio.sample_rate)

        # 1. HPSS: so a componente percussiva segue -- pads/vocais fora.
        _, y_percussive = librosa.effects.hpss(samples)

        # 2. Envelope de onset num mel-espectrograma grave/medio:
        #    bumbo e corpo de caixa entram; chimbal de banda alta nao.
        mel_spectrogram = librosa.feature.melspectrogram(
            y=y_percussive,
            sr=sample_rate,
            hop_length=self._hop_length,
            n_mels=self._n_mels,
            fmax=self._fmax_hz,
        )
        onset_envelope = librosa.onset.onset_strength(
            S=librosa.power_to_db(mel_spectrogram, ref=np.max),
            sr=sample_rate,
            hop_length=self._hop_length,
        )
        frame_times = librosa.times_like(
            onset_envelope, sr=sample_rate, hop_length=self._hop_length
        )

        # 3. PLP: pulso dominante LOCAL a partir do envelope percussivo.
        plp_curve = librosa.beat.plp(
            onset_envelope=onset_envelope,
            sr=sample_rate,
            hop_length=self._hop_length,
            tempo_min=self._plp_tempo_min,
            tempo_max=self._plp_tempo_max,
        )

        # 4. Threshold inteligente (intervalo minimo + amplitude minima)
        #    sobre AMBAS as curvas.
        pulse_times, pulse_strengths = select_curve_peaks(
            plp_curve, frame_times,
            minimum_interval_sec=self._minimum_interval_sec,
            min_height_ratio=self._pulse_min_height_ratio,
        )
        onset_times, onset_strengths = select_curve_peaks(
            onset_envelope, frame_times,
            minimum_interval_sec=self._minimum_interval_sec,
            min_height_ratio=self._onset_min_height_ratio,
        )

        return PercussiveExtractionResult(
            pulse_timestamps_seconds=pulse_times,
            pulse_strengths=pulse_strengths,
            onset_timestamps_seconds=onset_times,
            onset_strengths=onset_strengths,
            tempo_bpm_estimate=estimate_bpm_from_pulses(pulse_times),
        )
