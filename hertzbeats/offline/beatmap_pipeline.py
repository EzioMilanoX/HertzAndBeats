"""
Gera beatmaps do Hertz & Beats com a IA offline da engine: os extratores
de BPM/onset (librosa) fazem a analise; este modulo aplica apenas o
MAPEAMENTO especifico do jogo radial (curadoria de espacamento, lane em
setor angular, ameacas pesadas nos picos) antes da escrita atomica.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from ouroboros.rhythm.offline.audio_loader import AudioLoader
from ouroboros.rhythm.offline.beatmap_schema import BeatmapValidator, ScheduledThreatDefinition
from ouroboros.rhythm.offline.beatmap_writer import BeatmapWriter
from ouroboros.rhythm.offline.bpm_extractor import BpmExtractor
from ouroboros.rhythm.offline.onset_extractor import OnsetExtractor

THREAT_TYPE_BASIC = "rhythm_threat_basic"
THREAT_TYPE_HEAVY = "rhythm_threat_heavy"


def select_onsets(
    timestamps,
    strengths,
    min_start_seconds: float,
    max_end_seconds: float,
    min_gap_seconds: float,
    target_density_per_second: float,
) -> List[int]:
    """Seleciona os indices dos onsets que viram ameacas: os MAIS FORTES
    da faixa, ate a densidade-alvo, respeitando o espacamento minimo.

    Algoritmo (guloso por forca, nao por ordem temporal): percorre os
    onsets em ordem DECRESCENTE de strength e aceita cada um que (a)
    caiba na janela temporal jogavel e (b) nao fique a menos de
    `min_gap_seconds` de um onset ja aceito; para ao atingir
    `target_density * duracao_jogavel` aceitos. Isso e o que faz a
    dificuldade ser ESTAVEL entre musicas: um limiar absoluto de
    strength nao transfere (a distribuicao muda por faixa/mixagem) -- ou
    corta quase tudo, ou nao corta nada; ja "as N batidas mais fortes,
    espacadas" produz sempre um mapa na cadencia desejada, ancorado nos
    picos reais da musica (bumbo/caixa/drops), nunca no ruido continuo
    de baixo/chimbal.

    Retorna os indices aceitos em ordem TEMPORAL.
    """
    import bisect

    playable_span = max(0.0, max_end_seconds - min_start_seconds)
    max_threats = int(round(target_density_per_second * playable_span))
    if max_threats <= 0:
        return []

    by_strength = sorted(
        range(timestamps.shape[0]), key=lambda i: float(strengths[i]), reverse=True
    )
    accepted_times: List[float] = []  # mantido ordenado (bisect)
    accepted_indices: List[int] = []
    for onset_index in by_strength:
        if len(accepted_indices) >= max_threats:
            break
        timestamp = float(timestamps[onset_index])
        if timestamp < min_start_seconds or timestamp > max_end_seconds:
            continue
        insert_at = bisect.bisect_left(accepted_times, timestamp)
        if insert_at > 0 and timestamp - accepted_times[insert_at - 1] < min_gap_seconds:
            continue
        if insert_at < len(accepted_times) and accepted_times[insert_at] - timestamp < min_gap_seconds:
            continue
        accepted_times.insert(insert_at, timestamp)
        accepted_indices.append(onset_index)

    return sorted(accepted_indices, key=lambda i: float(timestamps[i]))


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
) -> dict:
    """Roda a IA da engine sobre `audio_path` e grava um beatmap.json
    jogavel para a arena radial.

    Curadoria pos-IA (o que difere do mapeador default da engine):
        - Janela temporal jogavel: nada antes de `min_start_seconds` (a
          primeira ameaca precisa de pista completa) nem depois de
          `duracao - end_margin_seconds` -- toda ameaca precisa ser
          resolvivel (janela de miss + punicao) ANTES da musica acabar,
          pois o relogio de audio congela no fim da faixa.
        - Selecao adaptativa (ver `select_onsets`): os onsets MAIS
          FORTES ate `target_density_per_second`, espacados por
          `min_gap_seconds` -- densidade estavel entre musicas, ancorada
          nas batidas reais.
        - Onsets com strength >= `heavy_strength_threshold` (drops/picos
          de energia) viram `rhythm_threat_heavy`.
        - `lane = indice_aceito % lane_count` distribui as ameacas em
          setores angulares alternados da borda.

    Retorna um resumo primitivo (bpm, contagens) para logging da CLI.
    """
    audio = AudioLoader().load(Path(audio_path))
    bpm_result = BpmExtractor().extract(audio)
    onset_result = OnsetExtractor().extract(audio)

    track_duration = audio.samples.shape[0] / float(audio.sample_rate)
    max_end_seconds = track_duration - end_margin_seconds

    timestamps = onset_result.onset_timestamps_seconds
    strengths = onset_result.onset_strengths

    selected = select_onsets(
        timestamps,
        strengths,
        min_start_seconds=min_start_seconds,
        max_end_seconds=max_end_seconds,
        min_gap_seconds=min_gap_seconds,
        target_density_per_second=target_density_per_second,
    )

    threats: List[ScheduledThreatDefinition] = []
    heavy_count = 0
    for onset_index in selected:
        strength = float(strengths[onset_index])
        is_heavy = strength >= heavy_strength_threshold
        heavy_count += int(is_heavy)
        threats.append(
            ScheduledThreatDefinition(
                timestamp_seconds=float(timestamps[onset_index]),
                threat_type=THREAT_TYPE_HEAVY if is_heavy else THREAT_TYPE_BASIC,
                lane=len(threats) % lane_count,
                strength=strength,
            )
        )

    validator = BeatmapValidator()
    beatmap_dict = validator.build_beatmap_dict(
        track_id=track_id,
        bpm=bpm_result.bpm,
        threats=tuple(threats),
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    BeatmapWriter(validator).write(beatmap_dict, output_path)

    return {
        "bpm": float(bpm_result.bpm),
        "onset_count": int(timestamps.shape[0]),
        "threat_count": len(threats),
        "heavy_count": heavy_count,
        "output_path": str(output_path),
    }
