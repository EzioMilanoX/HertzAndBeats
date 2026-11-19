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
    parser.add_argument(
        "--rate",
        type=float,
        default=None,
        help=(
            "Acessibilidade -- Escala de Tempo: toca as fases mais devagar "
            "(ex. 0.75 = 25%% mais lento). Faixa re-sintetizada no BPM "
            "escalado, sem resampling; janelas de julgamento nao mudam."
        ),
    )
    parser.add_argument(
        "--section",
        default=None,
        help=(
            "Treino por Secao: pratica so uma secao da faixa pelo nome "
            "(ex. 'climax'), comecando a musica ali. Ver `synth.sections` "
            "em data/stages/stages.json."
        ),
    )
    parser.add_argument(
        "--locale",
        default=None,
        help="Idioma da interface (pt_BR, en). Tambem pela variavel HERTZ_LOCALE.",
    )
    args = parser.parse_args(argv)

    config = HertzConfig.from_json(args.config)
    if args.locale:
        import dataclasses as _dc

        config = _dc.replace(config, locale=args.locale)
    if args.section:
        import dataclasses as _dc

        config = _dc.replace(config, practice_section=args.section)
    if args.rate is not None:
        import dataclasses

        from hertzbeats.rate_scaling import clamp_rate

        config = dataclasses.replace(config, playback_rate=clamp_rate(args.rate))
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
        # Diagnostico por Secao: aponta o trecho onde o jogador mais errou,
        # que e' exatamente o argumento de `--section` pra treinar so ele.
        section_counts = getattr(game_loop, "_section_miss_counts", {})
        if section_counts:
            from hertzbeats.section_diagnostics import format_section_report

            print(format_section_report(section_counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
