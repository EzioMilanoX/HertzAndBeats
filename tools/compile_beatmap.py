"""
Compila um beatmap AUTORAL escrito na DSL (compasso:batida) para
beatmap.json, rodando o linter de jogabilidade antes de gravar.

Uso (a partir da raiz do repositorio):
    python tools/compile_beatmap.py --source charts/chefao.hbm \
        --output data/beatmaps/chefao.beatmap.json --track-id chefao

    # conferindo contra a faixa da fase (habilita margem de fim e densidade):
    python tools/compile_beatmap.py --source charts/chefao.hbm \
        --output data/beatmaps/chefao.beatmap.json --track-id chefao \
        --stage defender_5_pesadelo

    # so validar, sem gravar:
    python tools/compile_beatmap.py --source charts/chefao.hbm --lint-only

Diferente de `tools/make_beatmap.py` (que roda a IA offline sobre um
audio), aqui NADA e extraido: o chart e escrito a mao. E o caminho pra um
chefao com notas colocadas contra a estrutura da musica, em vez de
onsets escolhidos por densidade.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hertzbeats.audio.demo_track_synth import total_bars
from hertzbeats.config import HertzConfig
from hertzbeats.offline.beatmap_dsl import (
    BeatmapSyntaxError,
    compile_beatmap_source,
    lint_authored_beatmap,
)
from hertzbeats.stages import load_stages

DEFAULT_CONFIG_PATH = "data/config/hertz_beats.config.json"

# Mesmos limites de `tests/test_playability_invariants.py` -- a fonte da
# verdade e aquele teste; repetidos aqui como default de CLI para o linter
# poder rodar sem importar codigo de teste.
LINT_MIN_GAP_SECONDS = 0.30
LINT_MAX_MEAN_DENSITY = 2.6
LINT_END_MARGIN_SECONDS = 1.0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Arquivo .hbm com a DSL.")
    parser.add_argument("--output", type=Path, help="Destino do beatmap.json (omitido com --lint-only).")
    parser.add_argument("--track-id", dest="track_id", help="Identificador da faixa.")
    parser.add_argument(
        "--stage",
        default=None,
        help="stage_id cuja faixa serve de referencia (habilita margem de fim e densidade).",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--lint-only", action="store_true", help="Valida e nao grava nada.")
    parser.add_argument(
        "--allow-warnings", action="store_true", help="Grava mesmo com problemas de jogabilidade."
    )
    args = parser.parse_args(argv)

    if not args.lint_only and (args.output is None or args.track_id is None):
        parser.error("--output e --track-id sao obrigatorios sem --lint-only")

    config = HertzConfig.from_json(args.config)
    source = args.source.read_text(encoding="utf-8")

    try:
        beatmap = compile_beatmap_source(
            source,
            track_id=args.track_id or args.source.stem,
            known_types=tuple(config.threat_type_ids),
        )
    except BeatmapSyntaxError as exc:
        print(f"[dsl] erro de sintaxe:\n{exc}")
        return 2

    duration = None
    if args.stage:
        stage = next((s for s in load_stages(config.stages_path) if s.stage_id == args.stage), None)
        if stage is None:
            print(f"[dsl] fase {args.stage!r} nao existe em {config.stages_path}")
            return 2
        if stage.synth is not None:
            duration = total_bars(stage.synth) * 4 * (60.0 / float(stage.synth["bpm"]))

    problems = lint_authored_beatmap(
        beatmap,
        min_gap_seconds=LINT_MIN_GAP_SECONDS,
        max_mean_density_per_second=LINT_MAX_MEAN_DENSITY,
        track_duration_seconds=duration,
        end_margin_seconds=LINT_END_MARGIN_SECONDS,
    )

    threats = beatmap["threats"]
    print(
        f"[dsl] {len(threats)} notas, bpm={beatmap['bpm']:.2f}, "
        f"de {threats[0]['timestamp_seconds']:.2f}s a {threats[-1]['timestamp_seconds']:.2f}s"
        + (f", faixa de referencia {duration:.2f}s" if duration else "")
    )
    for problem in problems:
        print(f"[lint] {problem}")

    if problems and not args.allow_warnings:
        print(f"[dsl] {len(problems)} problema(s) de jogabilidade; nada gravado (use --allow-warnings)")
        return 1
    if args.lint_only:
        print("[dsl] ok (lint-only, nada gravado)")
        return 0

    payload = {k: v for k, v in beatmap.items() if not k.startswith("_")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"[dsl] gravado: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
