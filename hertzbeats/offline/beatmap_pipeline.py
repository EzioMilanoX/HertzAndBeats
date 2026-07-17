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
from ouroboros.rhythm.offline.extraction_profiles import (
    EXTRACTION_PROFILES,
    LAYER_KICK,
    LAYER_VOCAL,
    estimate_bpm_from_pulses,
    extract_with_profile,
)
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


def select_strongest_unquantized(
    times: np.ndarray,
    strengths: np.ndarray,
    min_start_seconds: float,
    max_end_seconds: float,
    min_gap_seconds: float,
    max_notes: int,
) -> List[int]:
    """Selecao SEM grade (camada vocal / plano B): os eventos mais
    fortes, gulosos, com espacamento minimo e janela jogavel -- abraca a
    sincopa em vez de quantizar. Retorna indices em ordem temporal."""
    if max_notes <= 0:
        return []
    order = sorted(range(times.shape[0]), key=lambda i: float(strengths[i]), reverse=True)
    accepted_times: List[float] = []
    accepted: List[int] = []
    for index in order:
        if len(accepted) >= max_notes:
            break
        t = float(times[index])
        if t < min_start_seconds or t > max_end_seconds:
            continue
        pos = bisect.bisect_left(accepted_times, t)
        if pos > 0 and t - accepted_times[pos - 1] < min_gap_seconds:
            continue
        if pos < len(accepted_times) and accepted_times[pos] - t < min_gap_seconds:
            continue
        accepted_times.insert(pos, t)
        accepted.append(index)
    return sorted(accepted, key=lambda i: float(times[i]))


def merge_note_layers(
    kick_times: np.ndarray,
    kick_strengths: np.ndarray,
    vocal_times: np.ndarray,
    vocal_strengths: np.ndarray,
    min_separation_seconds: float,
) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """Funde as camadas do perfil "hybrid" com PRIORIDADE do kick: as
    notas de groove (quantizadas) entram todas; uma nota vocal so entra
    se ficar a pelo menos `min_separation_seconds` de qualquer nota ja
    aceita (o esqueleto ritmico nunca e empurrado pela melodia).
    Retorna `(tempos, forcas, layers)` em ordem temporal."""
    accepted_times: List[float] = [float(t) for t in kick_times]
    merged = [
        (float(kick_times[i]), float(kick_strengths[i]), LAYER_KICK)
        for i in range(kick_times.shape[0])
    ]
    for i in range(vocal_times.shape[0]):
        t = float(vocal_times[i])
        pos = bisect.bisect_left(accepted_times, t)
        if pos > 0 and t - accepted_times[pos - 1] < min_separation_seconds:
            continue
        if pos < len(accepted_times) and accepted_times[pos] - t < min_separation_seconds:
            continue
        accepted_times.insert(pos, t)
        merged.append((t, float(vocal_strengths[i]), LAYER_VOCAL))

    merged.sort(key=lambda item: item[0])
    times = np.asarray([item[0] for item in merged], dtype=np.float64)
    strengths = np.asarray([item[1] for item in merged], dtype=np.float64)
    layers = [item[2] for item in merged]
    return times, strengths, layers


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
    heavy_quantile: float = 0.92,
    subdivisions: int = 2,
    snap_tolerance_seconds: float = 0.08,
    profile: str = "groove",
    hybrid_kick_share: float = 0.60,
) -> dict:
    """Roda a IA da engine sobre `audio_path` com o PERFIL DE EXTRACAO
    pedido e grava um beatmap.json.

    Perfis (a matematica vive na engine, `extraction_profiles`; aqui e
    so interpretacao/curadoria):
        "groove"      -- notas QUANTIZADAS na grade do PLP percussivo
                         (faixas guiadas por bumbo), camada "kick".
        "vocal_shred" -- notas SEM quantizacao nos onsets da melodia
                         (faixas guiadas por voz/synth, estilo FNF),
                         camada "vocal".
        "hybrid"      -- esqueleto kick quantizado (`hybrid_kick_share`
                         da densidade) + melodia vocal sincopada por
                         cima, fundidas com prioridade do kick; cada
                         nota carrega a tag `layer` para o roteamento
                         espacial do jogo.

    Retorna um resumo primitivo (bpm, contagens por camada) para a CLI."""
    if profile not in EXTRACTION_PROFILES:
        raise ValueError(f"perfil desconhecido: {profile!r} (validos: {EXTRACTION_PROFILES})")

    audio = AudioLoader().load(Path(audio_path))
    track_duration = audio.samples.shape[0] / float(audio.sample_rate)
    max_end_seconds = track_duration - end_margin_seconds
    playable_span = max(0.0, max_end_seconds - min_start_seconds)

    # Estagio DSP na ENGINE; fallback para os extratores genericos
    # (audio exotico nunca derruba a analise).
    try:
        layers = {layer.layer: layer for layer in extract_with_profile(audio, profile).layers}
        dsp_stage = f"profile:{profile}"
    except Exception as exc:
        print(f"[mapper] perfil '{profile}' falhou ({exc}); usando extratores genericos")
        layers = {}
        dsp_stage = "generic-fallback"

    kick_layer = layers.get(LAYER_KICK)
    vocal_layer = layers.get(LAYER_VOCAL)

    # -- camada kick: quantizada na grade dos pulsos do PLP ------------
    kick_times = np.zeros(0)
    kick_strengths = np.zeros(0)
    on_beat_count = 0
    quantized = False
    kick_budget = target_density_per_second * (hybrid_kick_share if vocal_layer is not None else 1.0)
    if kick_layer is not None and kick_layer.pulse_timestamps_seconds.shape[0] >= 8:
        grid_times, on_beat = build_beat_grid(
            kick_layer.pulse_timestamps_seconds, subdivisions=subdivisions
        )
        slot_strengths, slot_has_event = snap_onsets_to_grid(
            grid_times,
            kick_layer.onset_timestamps_seconds,
            kick_layer.onset_strengths,
            snap_tolerance=snap_tolerance_seconds,
        )
        chosen = select_slots(
            grid_times, on_beat, slot_strengths, slot_has_event,
            min_start_seconds=min_start_seconds,
            max_end_seconds=max_end_seconds,
            min_gap_seconds=min_gap_seconds,
            target_density_per_second=kick_budget,
        )
        kick_times = grid_times[chosen]
        kick_strengths = slot_strengths[chosen]
        on_beat_count = int(np.count_nonzero(on_beat[chosen]))
        quantized = True

    # -- camada vocal: sincopada, sem grade ----------------------------
    vocal_times = np.zeros(0)
    vocal_strengths = np.zeros(0)
    if vocal_layer is not None:
        vocal_share = 1.0 if kick_layer is None else (1.0 - hybrid_kick_share)
        vocal_chosen = select_strongest_unquantized(
            vocal_layer.onset_timestamps_seconds,
            vocal_layer.onset_strengths,
            min_start_seconds=min_start_seconds,
            max_end_seconds=max_end_seconds,
            min_gap_seconds=min_gap_seconds,
            max_notes=int(round(target_density_per_second * vocal_share * playable_span)),
        )
        vocal_times = vocal_layer.onset_timestamps_seconds[vocal_chosen]
        vocal_strengths = vocal_layer.onset_strengths[vocal_chosen]

    # -- fallback generico (sem camada alguma) -------------------------
    generic_bpm = None
    if kick_layer is None and vocal_layer is None:
        bpm_result = BpmExtractor().extract(audio)
        generic_bpm = float(bpm_result.bpm)
        onset_result = OnsetExtractor().extract(audio)
        beat_times = np.asarray(bpm_result.beat_timestamps_seconds, dtype=np.float64)
        if beat_times.shape[0] >= 8:
            grid_times, on_beat = build_beat_grid(beat_times, subdivisions=subdivisions)
            slot_strengths, slot_has_event = snap_onsets_to_grid(
                grid_times, onset_result.onset_timestamps_seconds,
                onset_result.onset_strengths, snap_tolerance=snap_tolerance_seconds,
            )
            chosen = select_slots(
                grid_times, on_beat, slot_strengths, slot_has_event,
                min_start_seconds=min_start_seconds, max_end_seconds=max_end_seconds,
                min_gap_seconds=min_gap_seconds,
                target_density_per_second=target_density_per_second,
            )
            kick_times = grid_times[chosen]
            kick_strengths = slot_strengths[chosen]
            on_beat_count = int(np.count_nonzero(on_beat[chosen]))
            quantized = True
        else:
            chosen = select_strongest_unquantized(
                onset_result.onset_timestamps_seconds, onset_result.onset_strengths,
                min_start_seconds, max_end_seconds, min_gap_seconds,
                int(round(target_density_per_second * playable_span)),
            )
            kick_times = onset_result.onset_timestamps_seconds[chosen]
            kick_strengths = onset_result.onset_strengths[chosen]

    # -- fusao multi-camada com prioridade do esqueleto ritmico --------
    note_times, note_strengths, note_layers = merge_note_layers(
        kick_times, kick_strengths, vocal_times, vocal_strengths,
        min_separation_seconds=0.5 * min_gap_seconds,
    )

    if kick_layer is not None and kick_layer.tempo_bpm_estimate > 0.0:
        detected_bpm = kick_layer.tempo_bpm_estimate
    elif generic_bpm is not None:
        detected_bpm = generic_bpm
    else:
        detected_bpm = estimate_bpm_from_pulses(note_times)  # vocal_shred: so metadado

    centroids = (
        _spectral_centroids_at(audio, note_times) if note_times.shape[0] else np.zeros(0)
    )
    lanes = assign_lanes(note_times, centroids, lane_count=lane_count)

    # Pesadas por QUANTIL, nunca por limiar absoluto: cada estagio de
    # extracao normaliza forcas numa escala propria (o generico colapsa
    # em ~0, o percussivo satura em ~1) -- um corte fixo ou marca tudo
    # ou nada. Os acentos reais sao o topo da distribuicao DA PROPRIA
    # musica, com guarda para distribuicoes achatadas (sem acento claro
    # -> sem pesadas).
    if note_times.shape[0]:
        heavy_cutoff = float(np.quantile(note_strengths, heavy_quantile))
        strength_median = float(np.median(note_strengths))
    else:
        heavy_cutoff = np.inf
        strength_median = 0.0

    threats: List[ScheduledThreatDefinition] = []
    heavy_count = 0
    for i in range(note_times.shape[0]):
        strength = float(min(max(note_strengths[i], 0.0), 1.0))
        is_heavy = strength >= heavy_cutoff and strength > strength_median + 1e-6
        heavy_count += int(is_heavy)
        threats.append(
            ScheduledThreatDefinition(
                timestamp_seconds=float(note_times[i]),
                threat_type=THREAT_TYPE_HEAVY if is_heavy else THREAT_TYPE_BASIC,
                lane=int(lanes[i]),
                strength=strength,
                layer=note_layers[i],
            )
        )

    validator = BeatmapValidator()
    beatmap_dict = validator.build_beatmap_dict(
        track_id=track_id,
        bpm=float(detected_bpm),
        threats=tuple(threats),
    )
    beatmap_dict["mapper_version"] = MAPPER_VERSION
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    BeatmapWriter(validator).write(beatmap_dict, output_path)

    return {
        "bpm": float(detected_bpm),
        "profile": profile,
        "threat_count": len(threats),
        "kick_count": sum(1 for layer_tag in note_layers if layer_tag == LAYER_KICK),
        "vocal_count": sum(1 for layer_tag in note_layers if layer_tag == LAYER_VOCAL),
        "heavy_count": heavy_count,
        "on_beat_count": on_beat_count,
        "quantized": quantized,
        "dsp_stage": dsp_stage,
        "output_path": str(output_path),
    }
