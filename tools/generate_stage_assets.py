"""
Gera os assets de TODAS as fases de data/stages/stages.json: sintetiza
cada faixa deterministicamente e roda a IA offline da engine (librosa)
para extrair o beatmap correspondente.

Uso (a partir da raiz do repositorio):
    python tools/generate_stage_assets.py [--force]

--force re-sintetiza as faixas mesmo se ja existirem (necessario apos
mudar a especificacao `synth` de alguma fase).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hertzbeats.audio.demo_track_synth import ensure_track
from hertzbeats.offline.beatmap_pipeline import generate_beatmap
from hertzbeats.stages import load_stages

STAGES_PATH = "data/stages/stages.json"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-sintetiza faixas ja existentes.")
    args = parser.parse_args(argv)

    stages = load_stages(STAGES_PATH)
    for stage in stages:
        if not stage.track_path:
            continue
        if args.force:
            Path(stage.track_path).unlink(missing_ok=True)
        track_path = ensure_track(stage.track_path, stage.synth)
        print(f"[{stage.stage_id}] faixa pronta: {track_path}")

        if stage.tutorial_steps:
            # beatmap do tutorial e AUTORAL (timing didatico): nunca
            # sobrescrever com a saida da IA
            print(f"[{stage.stage_id}] beatmap autoral preservado: {stage.beatmap_path}")
            continue

        summary = generate_beatmap(
            audio_path=Path(track_path),
            output_path=Path(stage.beatmap_path),
            track_id=stage.stage_id,
            min_gap_seconds=stage.beatmap_params.get("min_gap_seconds", 0.45),
            min_start_seconds=stage.beatmap_params.get("min_start_seconds", 2.5),
            target_density_per_second=stage.beatmap_params.get("target_density_per_second", 1.4),
            end_margin_seconds=stage.beatmap_params.get("end_margin_seconds", 1.2),
        )
        print(
            f"[{stage.stage_id}] beatmap da IA: bpm={summary['bpm']:.2f} "
            f"onsets={summary['onset_count']} ameacas={summary['threat_count']} "
            f"(pesadas={summary['heavy_count']}) -> {summary['output_path']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
