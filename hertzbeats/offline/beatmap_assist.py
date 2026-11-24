"""
Geracao ASSISTIDA de beatmap: audio -> rascunho na DSL (`compasso:batida`),
em tres dificuldades, para o dono REVISAR a mao.

Onde isto se encaixa entre as ferramentas que ja existiam:

- `tools/make_beatmap.py` roda a IA da engine e cospe um `beatmap.json`
  pronto -- uma TRANSCRICAO, em segundos de ponto flutuante, que ninguem
  revisa nota a nota.
- `tools/compile_beatmap.py` compila um chart ESCRITO A MAO na DSL.

Faltava o meio do caminho: escrever um chart a mao do zero e lento, e
editar um JSON de timestamps e inviavel. Aqui a maquina faz a parte chata
(achar o BPM, onde cai o `1:1`, quais semicolcheias tem ataque de verdade,
quantas notas cabem em cada dificuldade) e devolve TEXTO na DSL, ja na
grade, que o dono le, apaga, move e recompila. O rascunho e um ponto de
partida, nunca o produto final -- por isso sai com cabecalho de rascunho
e com um comentario por compasso.

Etapas (todas puras sobre arrays, exceto a carga do audio):

1. ONSETS. Com librosa instalada usa `librosa.onset` (fluxo espectral
   em mel, robusto e com leitura de mp3/ogg); sem ela, um detector
   proprio em numpy (fluxo espectral log-comprimido + pico adaptativo),
   que so le WAV. Os dois passam pelo mesmo REFINAMENTO: o instante sai do
   ataque no sinal bruto (maior subida do envelope de amplitude), nao do
   pico do fluxo -- que acontece 1-2 frames DEPOIS do transiente, o mesmo
   vies de +18 ms que ja tinha deixado os charts curados fora do tempo
   (ver README, "O chart estava fora do ritmo").
2. TEMPO. Coerencia circular ponderada dos onsets em cada periodo
   candidato (`estimate_bpm`), seguida de uma checagem de NIVEL METRICO:
   se uma paridade das batidas domina a outra, o pulso real e o dobro do
   periodo (o erro classico de oitava: 76 BPM lido como 152).
3. GRADE. Regressao linear (instante ~ fase + n * periodo) sobre os
   onsets que caem na batida refina BPM e fase; o tempo forte (`1:1`) e
   a batida cuja classe (mod 4) concentra mais energia GRAVE (bumbo).
4. SELECAO por dificuldade (`DIFFICULTIES`): subdivisao permitida,
   espacamento minimo e densidade-alvo. As dificuldades sao ANINHADAS --
   o normal contem o facil e o dificil contem o normal --, entao subir de
   dificuldade so acrescenta notas, nunca reescreve o que o jogador ja
   aprendeu.
5. LANES. Pelo timbre (o mesmo som tende a cair na mesma regiao) mas com
   o deslocamento angular limitado pelo tempo disponivel: nota proxima
   nunca pede atravessar a arena.
"""
from __future__ import annotations

import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from hertzbeats.offline.beatmap_dsl import BEATS_PER_BAR

PLAYABLE_MIN_GAP_SECONDS = 0.30
"""Piso de espacamento do jogo (o mesmo de `tests/test_playability_invariants.py`
e `beatmap_pipeline.MIN_PLAYABLE_GAP_SECONDS` -- repetido para este modulo
nao importar o pipeline da IA, que puxa a engine e librosa)."""

MAX_NOTES_PER_5_SECONDS = 15
"""Teto de pico: 3.0 notas/s em qualquer janela de 5 s, abaixo dos 3.2 do
teste de invariantes."""

SUBDIVISIONS_PER_BEAT = 4
"""A grade de candidatos e em semicolcheias: e onde 87-100% dos ataques de
musica real caem a menos de 40 ms (medido no README, "Transcricao fiel")."""

LEVEL_DOWNBEAT, LEVEL_BEAT, LEVEL_EIGHTH, LEVEL_SIXTEENTH = 3, 2, 1, 0
_LEVEL_BONUS = {LEVEL_DOWNBEAT: 0.6, LEVEL_BEAT: 0.4, LEVEL_EIGHTH: 0.15, LEVEL_SIXTEENTH: 0.0}


@dataclass(frozen=True)
class DifficultyPreset:
    name: str
    min_level: int
    """Nivel metrico minimo permitido (batida, colcheia ou semicolcheia)."""
    min_gap_seconds: float
    target_density_per_second: float
    heavy_fraction: float


DIFFICULTIES: Dict[str, DifficultyPreset] = {
    "facil": DifficultyPreset("facil", LEVEL_BEAT, 0.60, 0.75, 0.08),
    "normal": DifficultyPreset("normal", LEVEL_EIGHTH, 0.40, 1.35, 0.12),
    "dificil": DifficultyPreset("dificil", LEVEL_SIXTEENTH, PLAYABLE_MIN_GAP_SECONDS, 2.1, 0.15),
}
"""Ordem importa: e a ordem do aninhamento (cada uma semeia a seguinte)."""


@dataclass
class AudioAnalysis:
    duration_seconds: float
    bpm: float
    offset_seconds: float
    """Onde cai o `1:1` (primeiro tempo forte), em [0, duracao de 1 compasso)."""
    onset_times: np.ndarray
    onset_strengths: np.ndarray
    """Normalizadas em [0, 1] (percentil 98 = 1)."""
    onset_brightness: np.ndarray
    """Centroide espectral do ataque, por POSTO na propria musica, em [0, 1]."""
    backend: str
    bpm_candidates: Tuple[float, ...] = ()


@dataclass(frozen=True)
class DraftNote:
    slot: int
    """Indice na grade de semicolcheias a partir do `1:1`."""
    time_seconds: float
    level: int
    strength: float
    brightness: float
    lane: int = 0
    heavy: bool = False

    @property
    def bar(self) -> int:
        return self.slot // (SUBDIVISIONS_PER_BEAT * BEATS_PER_BAR) + 1

    @property
    def beat(self) -> float:
        return 1.0 + (self.slot % (SUBDIVISIONS_PER_BEAT * BEATS_PER_BAR)) / SUBDIVISIONS_PER_BEAT


@dataclass
class DraftChart:
    difficulty: str
    notes: List[DraftNote] = field(default_factory=list)


# ------------------------------------------------------------ audio


def librosa_available() -> bool:
    try:
        import librosa  # noqa: F401
    except ImportError:
        return False
    return True


def load_audio(path: Path, use_librosa: bool) -> Tuple[np.ndarray, int]:
    """Audio mono float64 em [-1, 1] e a taxa de amostragem original."""
    if use_librosa:
        import librosa

        samples, sample_rate = librosa.load(str(path), sr=None, mono=True)
        return samples.astype(np.float64), int(sample_rate)
    if Path(path).suffix.lower() != ".wav":
        raise ValueError(
            f"{path}: sem librosa so ha leitor de WAV -- instale librosa (pip install librosa) "
            f"ou converta o audio para .wav"
        )
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        raw = wav_file.readframes(wav_file.getnframes())
    if width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    elif width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif width == 3:
        bytes_ = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        ints = bytes_[:, 0] | (bytes_[:, 1] << 8) | (bytes_[:, 2] << 16)
        ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
        data = ints.astype(np.float64) / float(1 << 23)
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float64) / float(1 << 31)
    else:
        raise ValueError(f"{path}: WAV de {width * 8} bits nao suportado")
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, int(sample_rate)


# ------------------------------------------------------------ onsets


_N_FFT = 2048
_HOP = 512


def _stft_magnitudes(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """|STFT| centrado (frame k em k*hop), em blocos pra nao alocar o
    espectrograma inteiro de uma vez. Corta acima de 11 kHz."""
    padded = np.pad(samples, (_N_FFT // 2, _N_FFT // 2))
    window = np.hanning(_N_FFT)
    frames = np.lib.stride_tricks.sliding_window_view(padded, _N_FFT)[::_HOP]
    top_bin = int(min(11000.0, sample_rate / 2.0) / (sample_rate / _N_FFT))
    chunks = []
    for start in range(0, frames.shape[0], 512):
        block = frames[start : start + 512] * window
        chunks.append(np.abs(np.fft.rfft(block, axis=1))[:, :top_bin])
    return np.concatenate(chunks, axis=0)


def _moving_mean(values: np.ndarray, radius: int) -> np.ndarray:
    kernel = np.ones(2 * radius + 1) / (2 * radius + 1)
    return np.convolve(np.pad(values, radius, mode="edge"), kernel, mode="valid")


def detect_onsets_numpy(samples: np.ndarray, sample_rate: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Detector de onsets sem dependencia: fluxo espectral log-comprimido
    em BANDAS logaritmicas, com pico adaptativo. Devolve `(instantes,
    forca_bruta, centroide_hz)`.

    Bandas, nao bins: somando bins lineares, o ruido de uma caixa (que
    ocupa centenas de bins agudos) valia 4-5x um bumbo (meia duzia de bins
    graves) -- medido nas faixas curadas, a batida so com bumbo saia com
    forca 0.2 e a com caixa 0.85, e o detector de oitava lia isso como
    "contratempo". Com a media por banda (como o mel do librosa), cada
    regiao do espectro pesa igual."""
    mags = _stft_magnitudes(samples, sample_rate)
    bin_hz = sample_rate / _N_FFT
    edges = np.unique(np.clip((np.geomspace(30.0, mags.shape[1] * bin_hz, 33) / bin_hz).astype(int), 1, mags.shape[1]))
    bands = np.stack([mags[:, a:b].mean(axis=1) for a, b in zip(edges[:-1], edges[1:]) if b > a], axis=1)
    flux = np.zeros(mags.shape[0])
    flux[1:] = np.maximum(0.0, np.diff(np.log1p(100.0 * bands), axis=0)).sum(axis=1)

    frame_rate = sample_rate / _HOP
    local_max = np.ones_like(flux, dtype=bool)
    radius = 3  # ~35 ms: dois ataques mais proximos que isso viram um
    for shift in range(1, radius + 1):
        local_max[shift:] &= flux[shift:] >= flux[:-shift]
        local_max[:-shift] &= flux[:-shift] > flux[shift:]
    threshold = _moving_mean(flux, int(0.5 * frame_rate)) + 0.06 * float(np.percentile(flux, 99))
    peaks = np.flatnonzero(local_max & (flux > threshold))

    bins_hz = np.arange(mags.shape[1]) * (sample_rate / _N_FFT)
    centroids = (mags[peaks] * bins_hz).sum(axis=1) / np.maximum(mags[peaks].sum(axis=1), 1e-9)
    return peaks / frame_rate, flux[peaks], centroids


def detect_onsets_librosa(samples: np.ndarray, sample_rate: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    import librosa

    envelope = librosa.onset.onset_strength(y=samples.astype(np.float32), sr=sample_rate, hop_length=_HOP)
    frames = librosa.onset.onset_detect(
        onset_envelope=envelope, sr=sample_rate, hop_length=_HOP, backtrack=False, units="frames"
    )
    centroid = librosa.feature.spectral_centroid(
        y=samples.astype(np.float32), sr=sample_rate, n_fft=_N_FFT, hop_length=_HOP
    )[0]
    frames = frames[frames < centroid.shape[0]]
    times = librosa.frames_to_time(frames, sr=sample_rate, hop_length=_HOP)
    return np.asarray(times, dtype=np.float64), envelope[frames].astype(np.float64), centroid[frames].astype(np.float64)


def refine_onset_times(
    samples: np.ndarray, sample_rate: int, times: np.ndarray, before: float = 0.05, after: float = 0.03
) -> np.ndarray:
    """Leva cada onset ao ATAQUE no sinal bruto: o ponto de maior subida do
    envelope de amplitude (suavizado em ~1.5 ms) numa janela em volta do
    pico do fluxo. Precisao de amostra em vez de frame (11.6 ms) -- medido
    nas 7 faixas sintetizadas, o vies cai de +18 ms (pico do fluxo) para
    -0.7 ms. (Testei "a primeira subida acima de 50% da maior", para nao
    pegar a 2a mao de uma palma: a fase da grade PIOROU 10-15 ms nas
    faixas com piano eletrico/sino, cujo ataque lento dispara cedo.)"""
    smooth = max(1, int(0.0015 * sample_rate))
    rise = max(1, int(0.002 * sample_rate))
    refined = np.empty_like(times)
    for index, t in enumerate(times):
        start = max(0, int((t - before) * sample_rate))
        end = min(samples.shape[0], int((t + after) * sample_rate))
        if end - start <= smooth + rise + 2:
            refined[index] = t
            continue
        envelope = np.convolve(np.abs(samples[start:end]), np.ones(smooth) / smooth, mode="same")
        slope = envelope[rise:] - envelope[:-rise]
        refined[index] = (start + int(np.argmax(slope))) / sample_rate
    return refined


# ------------------------------------------------------------ tempo e grade


def _coherence(times: np.ndarray, weights: np.ndarray, period: float) -> complex:
    return complex(np.sum(weights * np.exp(2j * np.pi * times / period)) / max(np.sum(weights), 1e-12))


_GRID_LEVEL_SCORE = np.array([1.0, 0.25, 0.5, 0.25])
"""Pontuacao de um onset pela posicao na grade de semicolcheias do tempo
candidato: na batida, semicolcheia, colcheia, semicolcheia."""
_OFF_GRID_PENALTY = 0.5


def _grid_score(times: np.ndarray, weights: np.ndarray, bpm: float) -> Tuple[float, float]:
    """Quao bem o BPM candidato EXPLICA os onsets: cada onset vale pelo
    nivel metrico em que cai na grade de semicolcheias (batida > colcheia >
    semicolcheia) e onset fora da grade custa. Devolve `(nota, fase_da_batida)`.

    Por que nao so a coerencia na batida: ela pune contratempo como se
    fosse erro. Num funk em tresillo (bumbo em 1, 1.75, 2.5) a coerencia
    na batida prefere 140 a 112 BPM -- 5 periodos de 140 fecham exatamente
    1 compasso de 112 e "explicam" os bumbos sincopados. Na grade de
    semicolcheias de 112 todo golpe tem casa; na de 140, nao."""
    step = 60.0 / bpm / 4.0
    phase16 = np.angle(_coherence(times, weights, step)) / (2.0 * np.pi) * step
    position = (times - phase16) / step
    index = np.round(position)
    on_grid = np.abs(position - index) * step <= min(0.03, 0.2 * step)
    total = max(float(np.sum(weights)), 1e-12)
    penalty = _OFF_GRID_PENALTY * float(np.sum(weights[~on_grid]))
    best_score, best_phase = -np.inf, phase16
    for k in range(4):  # qual das 4 semicolcheias e a batida
        cls = ((index[on_grid] - k) % 4).astype(int)
        score = (float(np.sum(weights[on_grid] * _GRID_LEVEL_SCORE[cls])) - penalty) / total
        if score > best_score:
            best_score, best_phase = score, phase16 + k * step
    return best_score, float(best_phase)


def _strongest_per_beat(times: np.ndarray, strengths: np.ndarray, period: float, phase: float) -> np.ndarray:
    """Forca do golpe mais forte em cada batida (0 se nenhum), da primeira
    a ultima batida com onset, comecando numa batida de indice PAR."""
    index = np.round((times - phase) / period).astype(int)
    near = np.abs(times - phase - index * period) <= 0.1 * period
    if not near.any():
        return np.zeros(0)
    first = int(index[near].min())
    first -= first % 2
    per_beat = np.zeros(int(index[near].max()) - first + 1)
    np.maximum.at(per_beat, index[near] - first, strengths[near])
    return per_beat


def estimate_bpm(
    times: np.ndarray, strengths: np.ndarray, bpm_min: float = 70.0, bpm_max: float = 180.0
) -> Tuple[float, Tuple[float, ...]]:
    """BPM pela grade que melhor explica os onsets (`_grid_score`, peso =
    forca^2 para o esqueleto de bateria mandar e o chimbal nao), seguido da
    correcao de NIVEL METRICO. Devolve `(bpm, candidatos_em_ordem)`."""
    if times.shape[0] < 4:
        raise ValueError("onsets insuficientes para estimar o tempo")
    weights = strengths**2
    coarse = np.arange(bpm_min, bpm_max + 1e-9, 0.05)
    scores = np.array([_grid_score(times, weights, bpm)[0] for bpm in coarse])
    candidates: List[float] = []
    for i in np.argsort(-scores):
        if all(abs(coarse[i] - c) > 2.0 for c in candidates):
            candidates.append(round(float(coarse[i]), 2))
        if len(candidates) == 3:
            break
    fine = np.arange(candidates[0] - 0.06, candidates[0] + 0.06, 0.004)
    best = float(fine[np.argmax([_grid_score(times, weights, bpm)[0] for bpm in fine])])

    # nivel metrico: a grade acima sempre "explica" tambem o dobro do
    # tempo (toda colcheia vira batida). Se ate as batidas MAIS FRACAS de
    # uma paridade (quartil 25) passam de 1.6x as tipicas da outra (quantil
    # 60), a outra paridade e contratempo e o pulso e a metade -- 76 lido
    # como 152. Quantis, nao soma nem media: num drum'n'bass (bumbo no 1,
    # caixa no 2 e no 4, nada no 3) a paridade "par" tem metade das batidas
    # vazias e mesmo assim o pulso certo e o de 170.
    while best / 2.0 >= bpm_min:
        period = 60.0 / best
        per_beat = _strongest_per_beat(times, strengths, period, _grid_score(times, weights, best)[1])
        if per_beat.shape[0] < 8:
            break
        even, odd = per_beat[0::2], per_beat[1::2]
        strong, weak = (even, odd) if np.median(even) >= np.median(odd) else (odd, even)
        if float(np.percentile(strong, 25)) < 1.6 * max(float(np.percentile(weak, 60)), 1e-6):
            break
        best /= 2.0
    return best, tuple(candidates)


def fit_grid(times: np.ndarray, strengths: np.ndarray, bpm: float) -> Tuple[float, float]:
    """Refina `(bpm, fase)` por minimos quadrados sobre os onsets que caem
    numa batida -- a busca acha o periodo com resolucao de grade; a
    regressao usa a duracao inteira da musica e erra fracoes de ms."""
    weights = strengths**2
    period = 60.0 / bpm
    phase = _grid_score(times, weights, bpm)[1]
    for _ in range(3):
        index = np.round((times - phase) / period)
        near = np.abs(times - phase - index * period) <= 0.1 * period
        if near.sum() < 4:
            break
        sqrt_w = np.sqrt(weights[near])
        design = np.stack([np.ones(int(near.sum())), index[near]], axis=1) * sqrt_w[:, None]
        solution, *_ = np.linalg.lstsq(design, times[near] * sqrt_w, rcond=None)
        phase, period = float(solution[0]), float(solution[1])
    return 60.0 / period, phase


def phase_for_bpm(times: np.ndarray, strengths: np.ndarray, bpm: float) -> float:
    """Fase da grade com o BPM FIXO (detectado e arredondado, ou forcado
    pelo usuario): parte da fase da grade de semicolcheias e corrige pela
    media ponderada do residuo dos onsets que caem numa batida."""
    weights = strengths**2
    period = 60.0 / bpm
    phase = _grid_score(times, weights, bpm)[1]
    for _ in range(2):
        index = np.round((times - phase) / period)
        residual = times - index * period - phase
        near = np.abs(residual) <= 0.1 * period
        if not near.any():
            break
        phase += float(np.sum(weights[near] * residual[near]) / np.sum(weights[near]))
    return float(phase)


def choose_downbeat(
    times: np.ndarray, strengths: np.ndarray, brightness: np.ndarray, bpm: float, phase: float
) -> float:
    """Instante do `1:1`: a classe de batida (mod 4) com mais energia GRAVE
    (forca x (1 - brilho)) -- o bumbo marca o tempo forte na enorme maioria
    da musica popular. Devolvido em [0, 1 compasso)."""
    period = 60.0 / bpm
    index = np.round((times - phase) / period)
    near = np.abs(times - phase - index * period) <= 0.1 * period
    scores = np.zeros(BEATS_PER_BAR)
    for k in range(BEATS_PER_BAR):
        mask = near & (index % BEATS_PER_BAR == k)
        scores[k] = float(np.sum(strengths[mask] ** 2 * (1.0 - brightness[mask])))
    downbeat = phase + int(np.argmax(scores)) * period
    bar = BEATS_PER_BAR * period
    offset = downbeat % bar
    if offset > bar - 0.002:  # 1:1 a um fio do zero e zero, nao "quase um compasso"
        offset -= bar
    return max(0.0, offset)


def _snap_bpm(bpm: float) -> float:
    """BPM a menos de 0.01 de um inteiro vira o inteiro (deriva < 6 ms em
    70 s): o rascunho fica legivel sem custo de tempo."""
    rounded = round(bpm)
    return float(rounded) if abs(bpm - rounded) < 0.01 else round(bpm, 3)


def analyze_audio(
    path: Path,
    backend: str = "auto",
    bpm: Optional[float] = None,
    offset_seconds: Optional[float] = None,
    bpm_range: Tuple[float, float] = (70.0, 180.0),
) -> AudioAnalysis:
    """Carrega o audio e extrai tudo o que a selecao precisa.

    `backend`: "auto" (librosa se instalada), "librosa" ou "numpy".
    `bpm`/`offset_seconds` forcam o tempo e o `1:1` quando a deteccao
    errar (a correcao manual mais comum: oitava do BPM ou anacruse)."""
    if backend not in ("auto", "librosa", "numpy"):
        raise ValueError(f"backend desconhecido {backend!r}")
    use_librosa = librosa_available() if backend == "auto" else backend == "librosa"
    samples, sample_rate = load_audio(Path(path), use_librosa)
    detector = detect_onsets_librosa if use_librosa else detect_onsets_numpy
    times, raw_strengths, centroids = detector(samples, sample_rate)
    if times.shape[0] < 4:
        raise ValueError(f"{path}: so {times.shape[0]} onsets detectados -- audio silencioso?")
    times = refine_onset_times(samples, sample_rate, times)
    strengths = np.clip(raw_strengths / max(float(np.percentile(raw_strengths, 98)), 1e-12), 0.0, 1.0)
    ranks = np.argsort(np.argsort(centroids))
    brightness = ranks / max(1, ranks.shape[0] - 1)

    candidates: Tuple[float, ...] = ()
    if bpm is None:
        estimate, candidates = estimate_bpm(times, strengths, *bpm_range)
        bpm = _snap_bpm(fit_grid(times, strengths, estimate)[0])
    phase = phase_for_bpm(times, strengths, float(bpm))
    if offset_seconds is None:
        offset_seconds = choose_downbeat(times, strengths, brightness, bpm, phase)
    return AudioAnalysis(
        duration_seconds=samples.shape[0] / sample_rate,
        bpm=float(bpm),
        offset_seconds=float(offset_seconds),
        onset_times=times,
        onset_strengths=strengths,
        onset_brightness=brightness,
        backend="librosa" if use_librosa else "numpy",
        bpm_candidates=candidates,
    )


# ------------------------------------------------------------ selecao


def slot_level(slot: int) -> int:
    per_bar = SUBDIVISIONS_PER_BEAT * BEATS_PER_BAR
    if slot % per_bar == 0:
        return LEVEL_DOWNBEAT
    if slot % SUBDIVISIONS_PER_BEAT == 0:
        return LEVEL_BEAT
    if slot % (SUBDIVISIONS_PER_BEAT // 2) == 0:
        return LEVEL_EIGHTH
    return LEVEL_SIXTEENTH


def build_slots(analysis: AudioAnalysis, snap_tolerance_seconds: float = 0.035) -> Dict[int, Tuple[float, float]]:
    """Semicolcheias com ataque de verdade: `{slot: (forca, brilho)}`.

    Onset longe de qualquer semicolcheia (tercina, swing, ruido) fica de
    fora em vez de ser arrastado -- arrastar e o que produz nota "quase" na
    batida."""
    step = 60.0 / analysis.bpm / SUBDIVISIONS_PER_BEAT
    tolerance = min(snap_tolerance_seconds, 0.3 * step)
    slots: Dict[int, Tuple[float, float]] = {}
    for t, strength, bright in zip(analysis.onset_times, analysis.onset_strengths, analysis.onset_brightness):
        slot = int(round((t - analysis.offset_seconds) / step))
        if slot < 0 or abs(t - analysis.offset_seconds - slot * step) > tolerance:
            continue
        current = slots.get(slot)
        if current is None or strength > current[0]:
            slots[slot] = (float(strength), float(bright))
    return slots


def _fits(time: float, accepted: List[float], min_gap: float) -> bool:
    index = int(np.searchsorted(accepted, time))
    if index > 0 and time - accepted[index - 1] < min_gap - 1e-9:
        return False
    if index < len(accepted) and accepted[index] - time < min_gap - 1e-9:
        return False
    # pico: nenhuma janela de 5 s que contenha esta nota pode estourar
    lo = int(np.searchsorted(accepted, time - 5.0, side="right"))
    hi = int(np.searchsorted(accepted, time + 5.0, side="left"))
    window = accepted[lo:hi] + [time]
    window.sort()
    for i in range(len(window)):
        j = int(np.searchsorted(window, window[i] + 5.0, side="left"))
        if j - i > MAX_NOTES_PER_5_SECONDS:
            return False
    return True


def select_notes(
    analysis: AudioAnalysis,
    preset: DifficultyPreset,
    min_start_seconds: float,
    end_margin_seconds: float,
    seed: Sequence[DraftNote] = (),
    min_strength: float = 0.12,
) -> List[DraftNote]:
    """Escolhe as notas de UMA dificuldade.

    `seed` (as notas da dificuldade anterior) entra primeiro e sem
    disputa -- e o aninhamento. Depois, guloso por pontuacao (forca +
    bonus metrico: tempo forte > batida > colcheia > semicolcheia), com
    espacamento minimo e teto de pico, ate a densidade-alvo."""
    step = 60.0 / analysis.bpm / SUBDIVISIONS_PER_BEAT
    last_allowed = analysis.duration_seconds - end_margin_seconds
    candidates = []
    for slot, (strength, bright) in build_slots(analysis).items():
        time = analysis.offset_seconds + slot * step
        level = slot_level(slot)
        if level < preset.min_level or strength < min_strength:
            continue
        if not (min_start_seconds <= time <= last_allowed):
            continue
        candidates.append((strength + _LEVEL_BONUS[level], slot, time, level, strength, bright))
    if not candidates:
        return list(seed)

    span = max(c[2] for c in candidates) - min(c[2] for c in candidates)
    target = max(len(seed), int(round(preset.target_density_per_second * max(span, 1.0))))

    chosen: Dict[int, DraftNote] = {note.slot: note for note in seed}
    accepted = sorted(note.time_seconds for note in seed)
    for _score, slot, time, level, strength, bright in sorted(candidates, key=lambda c: (-c[0], c[1])):
        if len(chosen) >= target:
            break
        if slot in chosen or not _fits(time, accepted, preset.min_gap_seconds):
            continue
        chosen[slot] = DraftNote(slot, time, level, strength, bright)
        accepted.insert(int(np.searchsorted(accepted, time)), time)
    return sorted(chosen.values(), key=lambda n: n.slot)


def _max_lane_step(gap_seconds: float) -> int:
    """Quantos setores (de 8) a mira pode andar entre duas notas: perto no
    tempo = perto no espaco. Atravessar a arena (4 setores) so com folga."""
    if gap_seconds < 0.45:
        return 1
    if gap_seconds < 0.75:
        return 2
    if gap_seconds < 1.2:
        return 3
    return 4


def assign_lanes(notes: Sequence[DraftNote], lane_count: int = 8) -> List[DraftNote]:
    """Lane desejada pelo brilho (grave -> setor baixo, agudo -> alto),
    limitada pelo tempo ate a nota anterior; mais de 3 repeticoes na mesma
    lane com pouco tempo empurram para a vizinha (anti-jack)."""
    result: List[DraftNote] = []
    run = 0
    for note in notes:
        desired = int(round(note.brightness * (lane_count - 1)))
        if not result:
            lane = desired
        else:
            previous = result[-1]
            gap = note.time_seconds - previous.time_seconds
            delta = (desired - previous.lane + lane_count // 2) % lane_count - lane_count // 2
            limit = _max_lane_step(gap)
            lane = (previous.lane + max(-limit, min(limit, delta))) % lane_count
            run = run + 1 if lane == previous.lane else 0
            if run >= 3 and gap < 0.6:
                lane = (lane + (1 if delta >= 0 else -1)) % lane_count
                run = 0
        result.append(DraftNote(note.slot, note.time_seconds, note.level, note.strength, note.brightness, lane))
    return result


def mark_heavy(notes: Sequence[DraftNote], fraction: float) -> List[DraftNote]:
    """As notas mais fortes EM TEMPO FORTE/BATIDA viram `heavy` (acento)."""
    eligible = [n for n in notes if n.level >= LEVEL_BEAT]
    count = int(round(fraction * len(notes)))
    heavy_slots = {n.slot for n in sorted(eligible, key=lambda n: (-n.strength, n.slot))[:count]}
    return [
        DraftNote(n.slot, n.time_seconds, n.level, n.strength, n.brightness, n.lane, n.slot in heavy_slots)
        for n in notes
    ]


def draft_charts(
    analysis: AudioAnalysis,
    difficulties: Sequence[str] = tuple(DIFFICULTIES),
    min_start_seconds: float = 3.0,
    end_margin_seconds: float = 1.5,
    lane_count: int = 8,
) -> Dict[str, DraftChart]:
    """Gera os rascunhos pedidos. As dificuldades sao calculadas SEMPRE na
    ordem facil -> normal -> dificil (o aninhamento depende disso), mesmo
    que so uma seja pedida."""
    unknown = set(difficulties) - set(DIFFICULTIES)
    if unknown:
        raise ValueError(f"dificuldade(s) desconhecida(s): {sorted(unknown)}; validas: {list(DIFFICULTIES)}")
    charts: Dict[str, DraftChart] = {}
    seed: List[DraftNote] = []
    for name, preset in DIFFICULTIES.items():
        seed = select_notes(analysis, preset, min_start_seconds, end_margin_seconds, seed=seed)
        if name in difficulties:
            notes = mark_heavy(assign_lanes(seed, lane_count), preset.heavy_fraction)
            charts[name] = DraftChart(name, notes)
    return charts


# ------------------------------------------------------------ saida na DSL


def _format_beat(beat: float) -> str:
    return f"{beat:g}"


def render_dsl(chart: DraftChart, analysis: AudioAnalysis, source_name: str, lane_count: int = 8) -> str:
    """Texto da DSL, comentado por compasso, pronto para revisao."""
    notes = chart.notes
    lines = [
        "# RASCUNHO gerado por tools/rascunho_beatmap.py -- REVISE antes de usar",
        f"# fonte: {source_name} | deteccao: {analysis.backend} | dificuldade: {chart.difficulty}",
        f"# bpm detectado {analysis.bpm:g}"
        + (f" (outros candidatos: {', '.join(f'{c:g}' for c in analysis.bpm_candidates[1:])})"
           if len(analysis.bpm_candidates) > 1 else "")
        + f" | 1:1 em {analysis.offset_seconds:.3f}s",
    ]
    if notes:
        gaps = np.diff([n.time_seconds for n in notes]) if len(notes) > 1 else np.array([0.0])
        span = notes[-1].time_seconds - notes[0].time_seconds
        lines.append(
            f"# {len(notes)} notas, {len(notes) / max(span, 1e-6):.2f} notas/s, "
            f"gap minimo {float(gaps.min()):.3f}s, {sum(n.heavy for n in notes)} pesadas"
        )
    lines += [
        "# Revisao sugerida: frases (o mesmo motivo -> o mesmo desenho de lanes),",
        "# respiros nas quebras, acentos (heavy) so onde a musica acentua.",
        "",
        f"bpm {analysis.bpm:g}",
    ]
    if analysis.offset_seconds > 0.0:
        lines.append(f"offset {analysis.offset_seconds:.4f}")
    lines += [f"lane_count {lane_count}", ""]
    current_bar = None
    for note in notes:
        if note.bar != current_bar:
            current_bar = note.bar
            lines.append(f"# -- compasso {current_bar}")
        kind = "heavy" if note.heavy else "basic"
        position = f"{note.bar}:{_format_beat(note.beat)}"
        lines.append(f"{position:<9s}{kind:<7s}{note.lane}  {max(0.05, min(1.0, note.strength)):.2f}")
    return "\n".join(lines) + "\n"
