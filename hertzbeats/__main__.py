"""Entrypoint do Hertz & Beats: `python -m hertzbeats [--config caminho] [--latency segundos]`."""
from __future__ import annotations

import argparse

from hertzbeats.bootstrap.rhythm_composition_root import RhythmCompositionRoot
from hertzbeats.config import HertzConfig

DEFAULT_CONFIG_PATH = "data/config/hertz_beats.config.json"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="hertz-beats",
        description="Hertz & Beats: Bullet Hell Ritmico radial sobre a Ouroboros Engine.",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"Caminho do JSON de configuracao (default: {DEFAULT_CONFIG_PATH}).",
    )
    parser.add_argument(
        "--latency",
        type=float,
        default=None,
        help="Sobrescreve a latencia de saida de audio calibrada, em segundos.",
    )
    parser.add_argument(
        "--stage",
        type=int,
        default=None,
        help="Pula o menu e inicia direto a fase N (0 = tutorial).",
    )
    args = parser.parse_args(argv)

    config = HertzConfig.from_json(args.config)
    root = RhythmCompositionRoot(config)
    game_loop, audio_engine = root.build()

    if args.latency is not None:
        audio_engine.get_clock().calibrate_latency(args.latency)
    if args.stage is not None:
        game_loop.start_stage(args.stage)

    try:
        game_loop.run()  # Tela de Titulo -> HUB -> Carrossel -> Pre-Voo -> jogo; ESC na Tela de Titulo encerra
    finally:
        from hertzbeats.user_settings import save_user_latency

        save_user_latency(audio_engine.get_clock().get_output_latency_seconds())
        state = game_loop.composed.game_state
        print(
            "ultima partida: "
            f"score={state.score} max_combo={state.max_combo} "
            f"perfect={state.perfect_count} good={state.good_count} "
            f"miss={state.miss_count} dodge={state.dodge_count} "
            f"vida_restante={state.health}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
