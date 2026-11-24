"""
Gera os assets de TODAS as fases de data/stages/stages.json: sintetiza
cada faixa deterministicamente e roda a IA offline da engine (librosa)
para extrair o beatmap correspondente.

Uso (a partir da raiz do repositorio):
    python tools/generate_stage_assets.py [--force]

--force re-sintetiza as faixas mesmo se ja existirem (necessario apos
mudar a especificacao `synth` de alguma fase).

--apenas-autorais pula as fases cujo beatmap vem da IA (nao precisa de
librosa): so re-sintetiza e recompila os charts AUTORAIS.

Fase com `"beatmap": {"authored_source": "charts/x.hbm"}` (as da campanha
`trilhas_originais`) NAO passa pela IA: o chart e escrito na DSL
(`compasso:batida`, normalmente a partir de um rascunho de
`tools/rascunho_beatmap.py` revisado a mao) e aqui so e compilado,
checado pelo linter de jogabilidade e carimbado com a digital da faixa.
Rodar a IA por cima apagaria a revisao.
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hertzbeats.audio.demo_track_synth import (
    ensure_track,
    measure_onset_lag_seconds,
    wav_fingerprint,
)
from hertzbeats.audio.demo_track_synth import total_bars
from hertzbeats.offline.beatmap_dsl import compile_beatmap_source, lint_authored_beatmap
from hertzbeats.stages import load_stages

STAGES_PATH = "data/stages/stages.json"


def _correct_onset_lag(beatmap_path: str, synth_spec) -> float:
    """Desconta o vies do extrator de onsets usando a VERDADE FUNDAMENTAL
    desta faixa, e devolve quanto foi descontado (em segundos).

    So possivel porque a faixa e sintetizada: `percussive_onset_times` sabe
    exatamente onde cada bumbo esta, entao o desvio nao e estimado, e
    medido. Numa musica do jogador isso nao existe e vale a constante
    global (`DEFAULT_ONSET_LAG_SECONDS`, aplicada por `music_library`).

    Aplica um deslocamento UNIFORME (a mediana), nunca por nota: o vies e
    sistemico -- vem da convencao de frame do DSP -- e "consertar" cada
    nota individualmente contra a batida mais proxima seria quantizar o
    chart a forca, apagando a sincopa que a IA legitimamente encontrou.
    """
    with open(beatmap_path, "r", encoding="utf-8") as f:
        beatmap = json.load(f)
    times = np.array([t["timestamp_seconds"] for t in beatmap["threats"]], dtype=np.float64)
    lag = measure_onset_lag_seconds(times, synth_spec)
    if abs(lag) < 0.001:  # ja alinhado; nao reescrever por ruido de 1 ms
        return 0.0
    for threat in beatmap["threats"]:
        threat["timestamp_seconds"] = max(0.0, threat["timestamp_seconds"] - lag)
    beatmap["onset_lag_correction_seconds"] = lag
    with open(beatmap_path, "w", encoding="utf-8") as f:
        json.dump(beatmap, f, indent=2, ensure_ascii=False)
    return lag


def _stamp_track_fingerprint(beatmap_path: str, fingerprint: str) -> None:
    """Grava `track_fingerprint` no beatmap, preservando todo o resto.

    Roda tambem no beatmap AUTORAL do tutorial (que nunca e regerado pela
    IA) -- e ali que a digital mais importa: os timestamps didaticos foram
    escritos a mao contra aquela faixa, e mudar a faixa faria as ameacas
    caírem no silencio sem nenhum erro.
    """
    with open(beatmap_path, "r", encoding="utf-8") as f:
        beatmap = json.load(f)
    beatmap["track_fingerprint"] = fingerprint
    # mesmo formato do escritor de beatmap da engine (indent=2, unicode cru)
    with open(beatmap_path, "w", encoding="utf-8") as f:
        json.dump(beatmap, f, indent=2, ensure_ascii=False)


def _compile_authored(stage, fingerprint: str) -> None:
    """Compila o chart AUTORAL da fase (`beatmap.authored_source`) para o
    `beatmap_path`, abortando se o linter de jogabilidade reclamar.

    `onset_lag_correction_seconds` e gravado como 0.0 de proposito: o chart
    e escrito NA GRADE (`compasso:batida` sobre o BPM exato da sintese),
    entao nao ha vies de extrator para descontar -- e o campo existe para
    a correcao ser auditavel (`tests/test_beat_alignment.py`)."""
    source = Path(stage.beatmap_params["authored_source"])
    beatmap = compile_beatmap_source(source.read_text(encoding="utf-8"), track_id=stage.stage_id)
    duration = total_bars(stage.synth) * 4 * 60.0 / float(stage.synth["bpm"]) if stage.synth else None
    problems = lint_authored_beatmap(beatmap, 0.30, 2.6, track_duration_seconds=duration)
    if problems:
        raise SystemExit(f"[{stage.stage_id}] {source}: " + "; ".join(problems))
    payload = {k: v for k, v in beatmap.items() if not k.startswith("_")}
    payload["authored_source"] = source.as_posix()
    payload["onset_lag_correction_seconds"] = 0.0
    payload["track_fingerprint"] = fingerprint
    with open(stage.beatmap_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-sintetiza faixas ja existentes.")
    parser.add_argument(
        "--apenas-autorais", dest="only_authored", action="store_true",
        help="So as fases com chart autoral (sem IA, sem librosa).",
    )
    args = parser.parse_args(argv)

    stages = load_stages(STAGES_PATH)
    processed_tracks = set()
    processed_beatmaps = set()
    for stage in stages:
        if not stage.track_path:
            continue
        authored = "authored_source" in stage.beatmap_params
        if args.only_authored and not authored:
            continue
        if stage.track_path not in processed_tracks:
            processed_tracks.add(stage.track_path)
            if args.force:
                Path(stage.track_path).unlink(missing_ok=True)
            track_path = ensure_track(stage.track_path, stage.synth)
            print(f"[{stage.stage_id}] faixa pronta: {track_path}")
        fingerprint = wav_fingerprint(stage.track_path)

        if stage.tutorial_steps:
            # beatmap do tutorial e AUTORAL (timing didatico): nunca
            # sobrescrever com a saida da IA -- mas a digital da faixa e
            # carimbada igual, justamente pra proteger esse casamento
            _stamp_track_fingerprint(stage.beatmap_path, fingerprint)
            print(f"[{stage.stage_id}] beatmap autoral preservado: {stage.beatmap_path}")
            continue
        if stage.beatmap_path in processed_beatmaps:
            # fases de modos alternativos consomem o MESMO beatmap de uma
            # fase anterior (a tese multi-modo): a curadoria e a da fase dona
            print(f"[{stage.stage_id}] beatmap compartilhado (mesmo json): {stage.beatmap_path}")
            continue
        processed_beatmaps.add(stage.beatmap_path)

        if authored:
            _compile_authored(stage, fingerprint)
            print(f"[{stage.stage_id}] chart autoral compilado: {stage.beatmap_params['authored_source']} "
                  f"-> {stage.beatmap_path}")
            continue

        # import tardio: so a IA precisa de librosa (via engine)
        from hertzbeats.offline.beatmap_pipeline import generate_beatmap

        summary = generate_beatmap(
            audio_path=Path(stage.track_path),
            output_path=Path(stage.beatmap_path),
            track_id=stage.stage_id,
            min_gap_seconds=stage.beatmap_params.get("min_gap_seconds", 0.45),
            min_start_seconds=stage.beatmap_params.get("min_start_seconds", 2.5),
            target_density_per_second=stage.beatmap_params.get("target_density_per_second", 1.4),
            end_margin_seconds=stage.beatmap_params.get("end_margin_seconds", 1.2),
            profile=stage.beatmap_params.get("profile", "groove"),
            # curadoria POR SECAO: cada secao da faixa usa seu proprio
            # gap/densidade (a ponte respira, o climax aperta). Faixa
            # plana -> uma janela global, comportamento historico.
            synth_spec=stage.synth,
            min_note_separation_seconds=stage.beatmap_params.get("min_note_separation_seconds"),
        )
        corrected = _correct_onset_lag(stage.beatmap_path, stage.synth) if stage.synth else 0.0
        _stamp_track_fingerprint(stage.beatmap_path, fingerprint)
        if corrected:
            print(f"[{stage.stage_id}] vies do extrator descontado: {corrected * 1000:+.1f} ms")
        print(
            f"[{stage.stage_id}] beatmap da IA ({summary['profile']}): bpm={summary['bpm']:.2f} "
            f"ameacas={summary['threat_count']} (kick={summary['kick_count']} "
            f"vocal={summary['vocal_count']} pesadas={summary['heavy_count']}) "
            f"-> {summary['output_path']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
