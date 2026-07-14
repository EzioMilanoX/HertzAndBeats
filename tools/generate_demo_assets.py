"""
Gera os assets da faixa demo: sintetiza o WAV deterministico e roda a
IA offline da engine (librosa) para extrair o beatmap jogavel.

Uso (a partir da raiz do repositorio):
    python tools/generate_demo_assets.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hertzbeats.audio.demo_track_synth import ensure_demo_track
from hertzbeats.offline.beatmap_pipeline import generate_beatmap

TRACK_PATH = Path("data/tracks/demo_track.wav")
BEATMAP_PATH = Path("data/beatmaps/demo_track.beatmap.json")


def main() -> int:
    track_path = ensure_demo_track(str(TRACK_PATH))
    print(f"faixa demo pronta: {track_path}")

    summary = generate_beatmap(
        audio_path=Path(track_path),
        output_path=BEATMAP_PATH,
        track_id="demo_track",
    )
    print(
        "beatmap gerado pela IA offline: "
        f"bpm={summary['bpm']:.2f} onsets={summary['onset_count']} "
        f"ameacas={summary['threat_count']} (pesadas={summary['heavy_count']}) "
        f"-> {summary['output_path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
