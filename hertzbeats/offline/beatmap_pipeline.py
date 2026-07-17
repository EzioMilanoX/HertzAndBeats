"""
Gera beatmaps do Hertz & Beats com a IA offline da engine -- MAPEADOR v2.

Por que v2: o mapeador original escolhia os ONSETS crus mais fortes.
Onsets marcam qualquer ataque (voz, chimbal, ruido) e o extrator ainda
os backtrackeia para o vale de energia ANTES do ataque -- notas caiam
sistematicamente adiantadas e fora da pulsacao, e o jogo "parecia
dessincronizado" mesmo com o relogio perfeito. O v2 faz o que os jogos
de ritmo reais fazem:

    1. GRADE: o beat-tracker da engine fornece os instantes das batidas;
       subdividimos em colcheias (`subdivisions=2`). TODA nota nasce em
       um ponto da grade -- nunca no timestamp cru do onset.
    2. ENERGIA: cada ponto da grade recebe a forca do onset mais forte a
       ate `snap_tolerance` dele; pontos sem evento musical ficam vazios.
    3. SELECAO: os melhores pontos (forca + bonus por cair NA batida)
       ate a densidade-alvo, com espacamento minimo e janela jogavel.
    4. LANE PELO TIMBRE: o centroide espectral no instante da nota
       escolhe a coluna/direcao (grave -> esquerda/baixo, agudo ->
       direita/cima) por quantis da propria musica: o mesmo som repete a
       mesma lane (padroes musicais viram padroes de jogo), com
       anti-jack para nao exigir repeticoes impossiveis.

As etapas 1-4 sao FUNCOES PURAS sobre arrays (testaveis sem librosa);
librosa entra apenas via os extratores da engine e no centroide.
"""
from __future__ import annotations

import bisect
from pathlib import Path
from typing import List, Tuple

import numpy as np

from ouroboros.rhythm.offline.audio_loader import AudioLoader
from ouroboros.rhythm.offline.beatmap_schema import BeatmapValidator, ScheduledThreatDefinition
from ouroboros.rhythm.offline.beatmap_writer import BeatmapWriter
from ouroboros.rhythm.offline.bpm_extractor import BpmExtractor
from ouroboros.rhythm.offline.onset_extractor import OnsetExtractor

from hertzbeats.mapper_version import MAPPER_VERSION

THREAT_TYPE_BASIC = "rhythm_threat_basic"
THREAT_TYPE_HEAVY = "rhythm_threat_heavy"

ON_BEAT_SCORE_BONUS = 0.35
"""Bonus de selecao para pontos que caem NA batida (vs colcheia): a
espinha do mapa deve ser a pulsacao, subdivisoes entram como tempero."""


# ------------------------------------------------------------------ puras

def build_beat_grid(beat_times: np.ndarray, subdivisions: int = 2) -> Tuple[np.ndarray, np.ndarray]:
    """Constroi a grade ritmica a partir dos instantes de batida do
    beat-tracker: cada intervalo entre batidas consecutivas e dividido em
    `subdivisions` partes iguais. Retorna `(grid_times, on_beat)` --
    `on_beat[i]` True quando o ponto e uma batida inteira."""
    beat_times = np.asarray(beat_times, dtype=np.float64)
    if beat_times.shape[0] < 2:
        return beat_times.copy(), np.ones(beat_times.shape[0], dtype=bool)

    grid = []
    on_beat = []
    for i in range(beat_times.shape[0] - 1):
        start, end = beat_times[i], beat_times[i + 1]
        for k in range(subdivisions):
            grid.append(start + (end - start) * k / subdivisions)
            on_beat.append(k == 0)
    grid.append(beat_times[-1])
    on_beat.append(True)
    return np.asarray(grid, dtype=np.float64), np.asarray(on_beat, dtype=bool)


def snap_onsets_to_grid(
    grid_times: np.ndarray,
    onset_times: np.ndarray,
    onset_strengths: np.ndarray,
    snap_tolerance: float = 0.08,
) -> Tuple[np.ndarray, np.ndarray]:
    """Para cada ponto da grade: `(forca, tem_evento)`. `tem_evento` e
    um booleano proprio -- a normalizacao de strength da engine colapsa
    a maioria dos onsets em ~0.0, entao "forca zero" NAO significa "nada
    aconteceu ali". O TEMPO da nota sera o da GRADE; o onset so vota em
    quais pontos importam -- e assim que o vies de backtracking dos
    onsets deixa de dessincronizar as notas."""
    slot_strengths = np.zeros(grid_times.shape[0], dtype=np.float64)
    slot_has_event = np.zeros(grid_times.shape[0], dtype=bool)
    if onset_times.shape[0] == 0:
        return slot_strengths, slot_has_event
    order = np.argsort(onset_times)
    sorted_times = np.asarray(onset_times, dtype=np.float64)[order]
    sorted_strengths = np.asarray(onset_strengths, dtype=np.float64)[order]

    for slot_index in range(grid_times.shape[0]):
        slot_time = grid_times[slot_index]
        left = np.searchsorted(sorted_times, slot_time - snap_tolerance, side="left")
        right = np.searchsorted(sorted_times, slot_time + snap_tolerance, side="right")
        if right > left:
            slot_strengths[slot_index] = float(np.max(sorted_strengths[left:right]))
            slot_has_event[slot_index] = True
    return slot_strengths, slot_has_event


def select_slots(
    grid_times: np.ndarray,
    on_beat: np.ndarray,
    slot_strengths: np.ndarray,
    slot_has_event: np.ndarray,
    min_start_seconds: float,
    max_end_seconds: float,
    min_gap_seconds: float,
    target_density_per_second: float,
) -> List[int]:
    """Escolhe os pontos da grade que viram notas: guloso por
    `forca + bonus_na_batida`, respeitando janela jogavel, espacamento
    minimo e densidade-alvo. So pontos COM evento musical
    (`slot_has_event`) sao elegiveis. Retorna indices em ordem temporal."""
    playable_span = max(0.0, max_end_seconds - min_start_seconds)
    max_slots = int(round(target_density_per_second * playable_span))
    if max_slots <= 0:
        return []

    scores = slot_strengths + np.where(on_beat, ON_BEAT_SCORE_BONUS, 0.0)
    by_score = sorted(
        range(grid_times.shape[0]), key=lambda i: float(scores[i]), reverse=True
    )
    accepted_times: List[float] = []
    accepted: List[int] = []
    for slot_index in by_score:
        if len(accepted) >= max_slots:
            break
        if not slot_has_event[slot_index]:
            continue  # ponto sem evento musical: nunca vira nota
        slot_time = float(grid_times[slot_index])
        if slot_time < min_start_seconds or slot_time > max_end_seconds:
            continue
        insert_at = bisect.bisect_left(accepted_times, slot_time)
        if insert_at > 0 and slot_time - accepted_times[insert_at - 1] < min_gap_seconds:
            continue
        if insert_at < len(accepted_times) and accepted_times[insert_at] - slot_time < min_gap_seconds:
            continue
        accepted_times.insert(insert_at, slot_time)
        accepted.append(slot_index)

    return sorted(accepted, key=lambda i: float(grid_times[i]))


def assign_lanes(
    slot_times: np.ndarray,
    slot_centroids: np.ndarray,
    lane_count: int = 8,
    anti_jack_gap_seconds: float = 0.22,
) -> List[int]:
    """Lane pelo TIMBRE: os centroides espectrais da propria musica sao
    divididos em `lane_count` quantis -- som grave vira lane baixa, som
    agudo vira lane alta, e o MESMO som repete a MESMA lane (padrao
    musical = padrao de jogo). Anti-jack: nota na mesma lane da anterior
    com gap menor que `anti_jack_gap_seconds` desloca para a vizinha."""
    n = slot_times.shape[0]
    if n == 0:
        return []
    quantiles = np.quantile(slot_centroids, np.linspace(0.0, 1.0, lane_count + 1)[1:-1])
    lanes = np.searchsorted(quantiles, slot_centroids, side="right").astype(int)

    result = []
    for i in range(n):
        lane = int(lanes[i])
        if result and lane == result[-1] and float(slot_times[i] - slot_times[i - 1]) < anti_jack_gap_seconds:
            lane = (lane + 1) % lane_count
        result.append(lane)
    return result


# ------------------------------------------------------------ com librosa

def _spectral_centroids_at(audio, times: np.ndarray) -> np.ndarray:
    """Centroide espectral (Hz) da musica no instante de cada nota."""
    import librosa  # offline-only

    hop_length = 512
    centroids = librosa.feature.spectral_centroid(
        y=audio.samples, sr=audio.sample_rate, hop_length=hop_length
    )[0]
    frame_times = librosa.frames_to_time(
        np.arange(centroids.shape[0]), sr=audio.sample_rate, hop_length=hop_length
    )
    indices = np.clip(np.searchsorted(frame_times, times), 0, centroids.shape[0] - 1)
    return centroids[indices]


def generate_beatmap(
    audio_path: Path,
    output_path: Path,
    track_id: str,
    lane_count: int = 8,
    min_gap_seconds: float = 0.45,
    min_start_seconds: float = 2.5,
    target_density_per_second: float = 1.4,
    end_margin_seconds: float = 1.2,
    heavy_strength_threshold: float = 0.80,
    subdivisions: int = 2,
    snap_tolerance_seconds: float = 0.08,
) -> dict:
    """Roda a IA da engine sobre `audio_path` e grava um beatmap.json
    QUANTIZADO na grade de batidas (ver docstring do modulo). Se o
    beat-tracker nao encontrar pulsacao suficiente (< 8 batidas), cai no
    plano B por onsets (sem quantizacao, melhor que nada).

    Retorna um resumo primitivo (bpm, contagens, fracao na batida) para
    logging da CLI."""
    audio = AudioLoader().load(Path(audio_path))
    bpm_result = BpmExtractor().extract(audio)
    onset_result = OnsetExtractor().extract(audio)

    track_duration = audio.samples.shape[0] / float(audio.sample_rate)
    max_end_seconds = track_duration - end_margin_seconds
    beat_times = np.asarray(bpm_result.beat_timestamps_seconds, dtype=np.float64)

    if beat_times.shape[0] >= 8:
        grid_times, on_beat = build_beat_grid(beat_times, subdivisions=subdivisions)
        slot_strengths, slot_has_event = snap_onsets_to_grid(
            grid_times,
            onset_result.onset_timestamps_seconds,
            onset_result.onset_strengths,
            snap_tolerance=snap_tolerance_seconds,
        )
        chosen = select_slots(
            grid_times, on_beat, slot_strengths, slot_has_event,
            min_start_seconds=min_start_seconds,
            max_end_seconds=max_end_seconds,
            min_gap_seconds=min_gap_seconds,
            target_density_per_second=target_density_per_second,
        )
        note_times = grid_times[chosen]
        note_strengths = slot_strengths[chosen]
        on_beat_count = int(np.count_nonzero(on_beat[chosen]))
        quantized = True
    else:
        # plano B: sem pulsacao confiavel, usa os onsets diretamente
        order = np.argsort(-onset_result.onset_strengths)
        note_times_list: List[float] = []
        for onset_index in order:
            t = float(onset_result.onset_timestamps_seconds[onset_index])
            if t < min_start_seconds or t > max_end_seconds:
                continue
            pos = bisect.bisect_left(note_times_list, t)
            if pos > 0 and t - note_times_list[pos - 1] < min_gap_seconds:
                continue
            if pos < len(note_times_list) and note_times_list[pos] - t < min_gap_seconds:
                continue
            note_times_list.insert(pos, t)
            if len(note_times_list) >= int(target_density_per_second * (max_end_seconds - min_start_seconds)):
                break
        note_times = np.asarray(note_times_list, dtype=np.float64)
        strengths_sorted = np.interp(
            note_times, onset_result.onset_timestamps_seconds, onset_result.onset_strengths
        )
        note_strengths = strengths_sorted
        on_beat_count = 0
        quantized = False

    centroids = (
        _spectral_centroids_at(audio, note_times) if note_times.shape[0] else np.zeros(0)
    )
    lanes = assign_lanes(note_times, centroids, lane_count=lane_count)

    threats: List[ScheduledThreatDefinition] = []
    heavy_count = 0
    for i in range(note_times.shape[0]):
        strength = float(min(max(note_strengths[i], 0.0), 1.0))
        is_heavy = strength >= heavy_strength_threshold
        heavy_count += int(is_heavy)
        threats.append(
            ScheduledThreatDefinition(
                timestamp_seconds=float(note_times[i]),
                threat_type=THREAT_TYPE_HEAVY if is_heavy else THREAT_TYPE_BASIC,
                lane=int(lanes[i]),
                strength=strength,
            )
        )

    validator = BeatmapValidator()
    beatmap_dict = validator.build_beatmap_dict(
        track_id=track_id,
        bpm=bpm_result.bpm,
        threats=tuple(threats),
    )
    beatmap_dict["mapper_version"] = MAPPER_VERSION
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    BeatmapWriter(validator).write(beatmap_dict, output_path)

    return {
        "bpm": float(bpm_result.bpm),
        "onset_count": int(onset_result.onset_timestamps_seconds.shape[0]),
        "threat_count": len(threats),
        "heavy_count": heavy_count,
        "on_beat_count": on_beat_count,
        "quantized": quantized,
        "output_path": str(output_path),
    }
