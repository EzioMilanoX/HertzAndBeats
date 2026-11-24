"""
Gera (renderiza) as MUSICAS ORIGINAIS das fases em .wav -- para ouvir,
para passar pelo `tools/rascunho_beatmap.py` ou para regenerar a faixa
depois de mexer na composicao.

Uso (a partir da raiz do repositorio):
    python tools/compor_faixas.py --listar
    python tools/compor_faixas.py --todas                  # todas as fases com musica original
    python tools/compor_faixas.py --fase original_2_contratempo --saida /tmp/contratempo.wav
    python tools/compor_faixas.py --fase original_3_hiperpulso --stems   # + instrumental/lead
    python tools/compor_faixas.py --fase original_1_mare_lenta --rate 0.75

A composicao (instrumentos, groove, harmonia e melodia de cada parte)
mora em `hertzbeats/audio/original_songs.py` -- e nao aqui -- por um
motivo pratico: os `.wav` NAO sao versionados, entao o proprio jogo
precisa conseguir re-sintetizar a faixa num clone novo (ou no .exe
empacotado), e o jogo nao importa `tools/`. Esta ferramenta e a porta de
entrada humana para o mesmo gerador. A ordem/tamanho das secoes de cada
musica e dado, em `data/stages/stages.json` (`synth.sections`).

Sem `--saida`, grava no `track_path` da fase (sobrescrevendo): depois
disso o `track_fingerprint` do beatmap so continua valido se a
composicao nao mudou -- mudou? rode `python tools/generate_stage_assets.py`
para recompilar o chart e recarimbar a digital.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hertzbeats.audio.demo_track_synth import (
    STEMS,
    percussive_onset_times,
    stem_track_path,
    synthesize_from_spec,
    total_bars,
    write_wav,
)
from hertzbeats.audio.original_songs import SONGS
from hertzbeats.rate_scaling import clamp_rate, rate_variant_track_path, scaled_synth_spec
from hertzbeats.stages import load_stages

STAGES_PATH = "data/stages/stages.json"


def original_stages(stages_path: str = STAGES_PATH):
    """Fases cuja faixa e uma musica original (`synth.song`), uma por faixa."""
    seen = set()
    result = []
    for stage in load_stages(stages_path):
        if stage.synth and "song" in stage.synth and stage.track_path not in seen:
            seen.add(stage.track_path)
            result.append(stage)
    return result


def render_stage(stage, output: Path, rate: float = 1.0, stems: bool = False) -> None:
    spec = scaled_synth_spec(stage.synth, rate)
    samples = synthesize_from_spec(spec)
    write_wav(samples, output)
    seconds = total_bars(spec) * 4 * 60.0 / float(spec["bpm"])
    hits = percussive_onset_times(spec)
    print(
        f"[{stage.stage_id}] {spec['song']} {float(spec['bpm']):.1f} BPM, {total_bars(spec)} compassos, "
        f"{seconds:.1f}s, {hits.shape[0]} golpes de bateria -> {output}"
    )
    if stems:
        for stem in STEMS:
            destination = Path(stem_track_path(str(output), stem))
            write_wav(synthesize_from_spec(spec, stem=stem), destination)
            print(f"    stem {stem}: {destination}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--listar", action="store_true", help="Lista musicas e fases que as usam.")
    parser.add_argument("--todas", action="store_true", help="Renderiza todas as fases com musica original.")
    parser.add_argument("--fase", help="stage_id da fase a renderizar.")
    parser.add_argument("--saida", type=Path, help="Destino do .wav (default: track_path da fase).")
    parser.add_argument("--rate", type=float, default=1.0, help="Escala de Tempo (0.5-1.0).")
    parser.add_argument("--stems", action="store_true", help="Grava tambem os stems instrumental/lead.")
    parser.add_argument("--stages", default=STAGES_PATH)
    args = parser.parse_args(argv)

    stages = original_stages(args.stages)
    if args.listar or not (args.todas or args.fase):
        print("musicas originais disponiveis:")
        for song_id, parts in SONGS.items():
            users = [s.stage_id for s in stages if s.synth["song"] == song_id]
            print(f"  {song_id:12s} partes: {', '.join(parts)} | fases: {', '.join(users) or '-'}")
        return 0

    rate = clamp_rate(args.rate)
    selected = stages if args.todas else [s for s in stages if s.stage_id == args.fase]
    if not selected:
        print(f"fase {args.fase!r} nao existe ou nao usa musica original (veja --listar)")
        return 2
    if args.saida and len(selected) > 1:
        parser.error("--saida so com uma fase")
    for stage in selected:
        output = args.saida or Path(rate_variant_track_path(stage.track_path, rate))
        render_stage(stage, output, rate=rate, stems=args.stems)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
