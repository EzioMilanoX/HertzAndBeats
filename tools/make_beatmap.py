"""
Gera um beatmap do Hertz & Beats a partir de QUALQUER musica sua,
usando a IA offline da engine (librosa).

Uso (a partir da raiz do repositorio):
    python tools/make_beatmap.py --audio minha_musica.mp3 --output data/beatmaps/minha.beatmap.json --track-id minha

Depois aponte "beatmap_path"/"track_path" no
data/config/hertz_beats.config.json para os novos arquivos.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hertzbeats.offline.beatmap_pipeline import generate_beatmap


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, type=Path, help="Arquivo de audio (wav/ogg/mp3).")
    parser.add_argument("--output", required=True, type=Path, help="Destino do beatmap.json.")
    parser.add_argument("--track-id", required=True, dest="track_id", help="Identificador da faixa.")
    parser.add_argument("--lanes", type=int, default=8, help="Setores angulares da borda (default: 8).")
    parser.add_argument(
        "--min-gap",
        type=float,
        default=0.20,
        dest="min_gap",
        help="Espacamento minimo entre ameacas, em segundos (default: 0.20).",
    )
    parser.add_argument(
        "--profile",
        choices=["groove", "vocal_shred", "hybrid"],
        default="hybrid",
        help=(
            "Perfil de Extracao DSP: groove (bumbo/estabilidade), vocal_shred "
            "(melodia sincopada, estilo FNF) ou hybrid (camadas kick+vocal "
            "taggeadas; default)."
        ),
    )
    args = parser.parse_args(argv)

    summary = generate_beatmap(
        audio_path=args.audio,
        output_path=args.output,
        track_id=args.track_id,
        lane_count=args.lanes,
        min_gap_seconds=args.min_gap,
        profile=args.profile,
    )
    print(
        f"beatmap gerado pela IA offline ({summary['profile']}): "
        f"bpm={summary['bpm']:.2f} ameacas={summary['threat_count']} "
        f"(kick={summary['kick_count']} vocal={summary['vocal_count']} "
        f"pesadas={summary['heavy_count']}) -> {summary['output_path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
