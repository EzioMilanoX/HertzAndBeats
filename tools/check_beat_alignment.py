"""
Audita se os beatmaps das fases curadas caem NA batida da faixa.

Uso (a partir da raiz do repositorio):
    python tools/check_beat_alignment.py
    python tools/check_beat_alignment.py --stage defender_3_ikaruga --verbose

So funciona em fase com `synth` spec: a verdade fundamental
(`demo_track_synth.percussive_onset_times`) existe porque a faixa foi
SINTETIZADA -- sabemos onde cada bumbo esta pela mesma aritmetica que os
posicionou. Musica do jogador nao tem isso; ali o alinhamento depende da
constante `DEFAULT_ONSET_LAG_SECONDS`, derivada exatamente destas medidas.

Positivo = ameaca chega DEPOIS da bateria real.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hertzbeats.audio.demo_track_synth import percussive_onset_times
from hertzbeats.config import HertzConfig
from hertzbeats.stages import load_stages

MATCH_WINDOW_SECONDS = 0.06


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", default=None, help="Auditar so esta fase.")
    parser.add_argument("--config", default="data/config/hertz_beats.config.json")
    parser.add_argument("--verbose", action="store_true", help="Lista as piores notas.")
    args = parser.parse_args(argv)

    config = HertzConfig.from_json(args.config)
    perfect_ms = config.perfect_window_seconds * 1000.0

    stages = [
        s
        for s in load_stages(config.stages_path)
        if s.synth is not None and not s.tutorial_steps and s.track_path
        and (args.stage is None or s.stage_id == args.stage)
    ]
    if not stages:
        print("nenhuma fase curada corresponde (musica do jogador nao tem verdade fundamental)")
        return 1

    print(f"janela PERFECT da config base: +/-{perfect_ms:.0f} ms")
    print(f"{'fase':26s} {'n':>4s} {'vies':>9s} {'|erro| med':>11s} {'p90':>8s} {'casadas':>8s}")
    print("-" * 74)
    worst_bias = 0.0
    for stage in stages:
        truth = percussive_onset_times(stage.synth)
        with open(stage.beatmap_path, encoding="utf-8") as f:
            beatmap = json.load(f)
        times = np.array([t["timestamp_seconds"] for t in beatmap["threats"]], dtype=np.float64)
        index = np.searchsorted(truth, times).clip(1, truth.shape[0] - 1)
        before, after = truth[index - 1], truth[index]
        nearest = np.where(np.abs(times - before) < np.abs(times - after), before, after)
        delta = times - nearest
        matched = delta[np.abs(delta) <= MATCH_WINDOW_SECONDS]
        bias = float(np.median(matched)) if matched.shape[0] else 0.0
        worst_bias = max(worst_bias, abs(bias))
        print(
            f"{stage.stage_id:26s} {times.shape[0]:4d} {bias * 1000:+7.1f}ms "
            f"{np.median(np.abs(delta)) * 1000:8.1f}ms {np.percentile(np.abs(delta), 90) * 1000:6.1f}ms "
            f"{matched.shape[0] / max(1, times.shape[0]):7.0%}"
        )
        applied = beatmap.get("onset_lag_correction_seconds")
        if applied:
            print(f"{'':26s}      (correcao ja aplicada na geracao: {applied * 1000:+.1f} ms)")
        if args.verbose:
            order = np.argsort(-np.abs(delta))[:5]
            for i in order:
                print(f"{'':28s}pior: {times[i]:6.2f}s  {delta[i] * 1000:+6.1f}ms")

    print()
    if worst_bias * 1000 > 3.0:
        print(
            f"VIES SISTEMATICO de ate {worst_bias * 1000:.1f} ms -- o chart nao esta na batida.\n"
            f"Rode: python tools/generate_stage_assets.py --force"
        )
        return 1
    print("sem vies sistematico: os charts estao na batida.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
