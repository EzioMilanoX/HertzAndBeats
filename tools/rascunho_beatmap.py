"""
Geracao ASSISTIDA de beatmap: le um audio, detecta BPM/onsets e escreve
RASCUNHOS na DSL (`compasso:batida`) em ate 3 dificuldades, para voce
revisar a mao e depois compilar com `tools/compile_beatmap.py`.

Uso (a partir da raiz do repositorio):
    python tools/rascunho_beatmap.py --audio musicas/minha.wav --saida charts/minha
        -> charts/minha_facil.hbm, charts/minha_normal.hbm, charts/minha_dificil.hbm

    # so uma dificuldade, forcando o BPM (a deteccao errou a oitava):
    python tools/rascunho_beatmap.py --audio x.wav --saida charts/x --dificuldades normal --bpm 76

    # deteccao sem librosa (so WAV), e o 1:1 forcado em 0.37 s:
    python tools/rascunho_beatmap.py --audio x.wav --saida charts/x --backend numpy --offset 0.37

Fluxo completo:
    1. gere o rascunho (este script) e OUCA a musica lendo o .hbm;
    2. revise: apague notas que nao "pedem" tiro, desenhe as lanes por
       frase, marque `heavy` so onde a musica acentua, deixe as quebras
       respirarem;
    3. valide e grave:
       python tools/compile_beatmap.py --source charts/x_normal.hbm \\
           --output data/beatmaps/x.beatmap.json --track-id x

Deteccao: librosa se instalada (le mp3/ogg/wav); senao um detector de
onsets em numpy puro (so WAV). `--backend` forca um dos dois. O BPM vem
com candidatos alternativos no cabecalho do rascunho -- se a musica soa
no dobro/metade, rode de novo com `--bpm`.

Dificuldades (densidade por padrao; ver `beatmap_assist.DIFFICULTIES`):
    facil    so batidas,               gap >= 0.60 s, ~0.75 notas/s
    normal   ate colcheias,            gap >= 0.40 s, ~1.35 notas/s
    dificil  ate semicolcheias,        gap >= 0.30 s, ~2.1 notas/s
As tres sao ANINHADAS: o normal contem o facil, o dificil contem o normal.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hertzbeats.offline.beatmap_assist import DIFFICULTIES, analyze_audio, draft_charts, render_dsl
from hertzbeats.offline.beatmap_dsl import compile_beatmap_source, lint_authored_beatmap

LINT_MIN_GAP_SECONDS = 0.30
LINT_MAX_MEAN_DENSITY = 2.6


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audio", required=True, type=Path, help="Arquivo de audio (wav; mp3/ogg com librosa).")
    parser.add_argument("--saida", required=True, type=Path, help="Prefixo dos .hbm (ex.: charts/minha).")
    parser.add_argument(
        "--dificuldades", default=",".join(DIFFICULTIES),
        help=f"Lista separada por virgula (default: {','.join(DIFFICULTIES)}).",
    )
    parser.add_argument("--backend", choices=["auto", "librosa", "numpy"], default="auto")
    parser.add_argument("--bpm", type=float, default=None, help="Forca o BPM (pula a deteccao).")
    parser.add_argument("--offset", type=float, default=None, help="Forca onde cai o 1:1, em segundos.")
    parser.add_argument(
        "--inicio", type=float, default=3.0,
        help="Nenhuma nota antes disto (s) -- deixe >= approach_seconds da fase + 0.3 (default: 3.0).",
    )
    parser.add_argument("--margem-fim", dest="margem_fim", type=float, default=1.5, help="Folga no fim (s).")
    parser.add_argument("--lanes", type=int, default=8)
    args = parser.parse_args(argv)

    wanted = [name.strip() for name in args.dificuldades.split(",") if name.strip()]
    unknown = [name for name in wanted if name not in DIFFICULTIES]
    if unknown:
        parser.error(f"dificuldade(s) desconhecida(s): {unknown} (validas: {list(DIFFICULTIES)})")

    try:
        analysis = analyze_audio(args.audio, backend=args.backend, bpm=args.bpm, offset_seconds=args.offset)
    except (OSError, ValueError) as exc:
        print(f"[rascunho] {exc}")
        return 2
    candidates = ", ".join(f"{c:g}" for c in analysis.bpm_candidates) or "(forcado)"
    print(
        f"[rascunho] {args.audio.name}: {analysis.duration_seconds:.1f}s, deteccao {analysis.backend}, "
        f"{analysis.onset_times.shape[0]} onsets, bpm {analysis.bpm:g} (candidatos: {candidates}), "
        f"1:1 em {analysis.offset_seconds:.3f}s"
    )

    charts = draft_charts(
        analysis, wanted, min_start_seconds=args.inicio, end_margin_seconds=args.margem_fim, lane_count=args.lanes
    )
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    worst = 0
    for name in wanted:
        chart = charts[name]
        text = render_dsl(chart, analysis, args.audio.name, lane_count=args.lanes)
        destination = args.saida.with_name(f"{args.saida.name}_{name}.hbm")
        destination.write_text(text, encoding="utf-8")
        # auto-checagem: o rascunho TEM de compilar e passar no linter --
        # senao o dono revisaria um arquivo que ja nasce quebrado
        beatmap = compile_beatmap_source(text, track_id=args.saida.name)
        problems = lint_authored_beatmap(
            beatmap, LINT_MIN_GAP_SECONDS, LINT_MAX_MEAN_DENSITY, track_duration_seconds=analysis.duration_seconds
        )
        notes = chart.notes
        span = (notes[-1].time_seconds - notes[0].time_seconds) if len(notes) > 1 else 0.0
        print(
            f"  {name:8s} {len(notes):4d} notas, {len(notes) / max(span, 1e-6):.2f}/s, "
            f"{sum(n.heavy for n in notes)} pesadas -> {destination}"
            + ("" if not problems else f"  [{len(problems)} aviso(s) do linter]")
        )
        for problem in problems:
            print(f"      [lint] {problem}")
        worst = max(worst, 1 if problems else 0)
    print("[rascunho] revise os .hbm e compile com tools/compile_beatmap.py")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
