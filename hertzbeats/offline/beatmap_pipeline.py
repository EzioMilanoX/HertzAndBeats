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


def generate_beatmap(
    audio_path: Path,
    output_path: Path,
    track_id: str,
    lane_count: int = 8,
    min_gap_seconds: float = 0.20,
    min_start_seconds: float = 2.5,
    heavy_strength_threshold: float = 0.80,
) -> dict:
    """Roda a IA da engine sobre `audio_path` e grava um beatmap.json
    jogavel para a arena radial.

    Curadoria pos-IA (o que difere do mapeador default da engine):
        - `min_gap_seconds`: descarta onsets proximos demais do anterior
          aceito, garantindo que duas janelas de julgamento nunca se
          sobreponham.
        - `min_start_seconds`: descarta onsets antes do tempo minimo de
          aproximacao (a primeira ameaca precisa de pista completa).
        - Onsets com strength >= `heavy_strength_threshold` (drops/picos
          de energia) viram `rhythm_threat_heavy`.
        - `lane = indice_aceito % lane_count` distribui as ameacas em
          setores angulares alternados da borda.

    Retorna um resumo primitivo (bpm, contagens) para logging da CLI.
    """
    audio = AudioLoader().load(Path(audio_path))
    bpm_result = BpmExtractor().extract(audio)
    onset_result = OnsetExtractor().extract(audio)

    timestamps = onset_result.onset_timestamps_seconds
    strengths = onset_result.onset_strengths

    threats: List[ScheduledThreatDefinition] = []
    last_accepted = -1e9
    heavy_count = 0
    for onset_index in range(timestamps.shape[0]):
        timestamp = float(timestamps[onset_index])
        if timestamp < min_start_seconds:
            continue
        if timestamp - last_accepted < min_gap_seconds:
            continue
        last_accepted = timestamp
        strength = float(strengths[onset_index])
        is_heavy = strength >= heavy_strength_threshold
        heavy_count += int(is_heavy)
        threats.append(
            ScheduledThreatDefinition(
                timestamp_seconds=timestamp,
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
