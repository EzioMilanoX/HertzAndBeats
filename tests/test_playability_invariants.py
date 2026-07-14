"""Invariantes de JOGABILIDADE sobre os beatmaps versionados.

Estes testes protegem contra a regressao que tornou o jogo injogavel:
mapas com 3-4 ameacas/s continuas (metralhadora de onsets fracos) e
ameacas agendadas depois do fim da musica (softlock: o relogio de audio
congela quando a faixa acaba). Qualquer beatmap regenerado/adicionado
precisa passar por aqui.
"""
import json

from hertzbeats.config import HertzConfig
from hertzbeats.stages import load_stages, resolve_stage_config

MAX_MEAN_DENSITY_PER_SECOND = 2.6
MAX_PEAK_DENSITY_5S_WINDOW = 3.2
MIN_GAP_SECONDS = 0.30
END_MARGIN_SECONDS = 1.0
LANE_COUNT = 8


def _load_all_stages():
    base_config = HertzConfig.from_json("data/config/hertz_beats.config.json")
    stages = load_stages(base_config.stages_path)
    for stage in stages:
        with open(stage.beatmap_path, encoding="utf-8") as f:
            beatmap = json.load(f)
        yield base_config, stage, beatmap


def _synth_duration_seconds(stage) -> float:
    """Duracao da faixa derivada da especificacao de sintese (pura
    aritmetica: compassos * 4 batidas * 60/bpm), sem precisar do .wav."""
    assert stage.synth is not None, f"{stage.stage_id}: fase versionada sem synth spec"
    return stage.synth["bars"] * 4 * (60.0 / stage.synth["bpm"])


def test_every_threat_is_resolvable_before_the_music_ends():
    for _, stage, beatmap in _load_all_stages():
        duration = _synth_duration_seconds(stage)
        last_hit = beatmap["threats"][-1]["timestamp_seconds"]
        margin = duration - last_hit
        assert margin >= END_MARGIN_SECONDS, (
            f"{stage.stage_id}: ultima ameaca a {last_hit:.2f}s com faixa de {duration:.2f}s "
            f"(margem {margin:.2f}s < {END_MARGIN_SECONDS}s -> risco de softlock no fim)"
        )


def test_first_threat_leaves_room_for_full_approach():
    for base_config, stage, beatmap in _load_all_stages():
        stage_config = resolve_stage_config(base_config, stage)
        first_hit = beatmap["threats"][0]["timestamp_seconds"]
        assert first_hit >= stage_config.approach_seconds + 0.3, (
            f"{stage.stage_id}: primeira ameaca a {first_hit:.2f}s nao da pista completa "
            f"(approach {stage_config.approach_seconds}s)"
        )


def test_density_stays_humanly_playable():
    for _, stage, beatmap in _load_all_stages():
        timestamps = [t["timestamp_seconds"] for t in beatmap["threats"]]
        span = timestamps[-1] - timestamps[0]
        if span <= 0:
            continue
        mean_density = len(timestamps) / span
        assert mean_density <= MAX_MEAN_DENSITY_PER_SECOND, (
            f"{stage.stage_id}: densidade media {mean_density:.2f}/s alem do jogavel"
        )
        peak = max(
            sum(1 for t in timestamps if start <= t < start + 5.0)
            for start in range(int(timestamps[-1]) + 1)
        )
        assert peak / 5.0 <= MAX_PEAK_DENSITY_5S_WINDOW, (
            f"{stage.stage_id}: pico de {peak / 5.0:.2f}/s em janela de 5s alem do jogavel"
        )


def test_consecutive_threats_never_overlap_judgment_windows():
    for _, stage, beatmap in _load_all_stages():
        timestamps = [t["timestamp_seconds"] for t in beatmap["threats"]]
        for previous, current in zip(timestamps, timestamps[1:]):
            gap = current - previous
            if stage.tutorial_steps and gap == 0.0:
                continue  # ondas simultaneas do tutorial (ensinam o dash) sao intencionais
            assert gap >= MIN_GAP_SECONDS, (
                f"{stage.stage_id}: gap de {gap:.3f}s entre {previous:.2f}s e {current:.2f}s "
                f"(minimo jogavel {MIN_GAP_SECONDS}s)"
            )


def test_threat_fields_are_within_domain():
    base_config = HertzConfig.from_json("data/config/hertz_beats.config.json")
    for _, stage, beatmap in _load_all_stages():
        for i, threat in enumerate(beatmap["threats"]):
            assert 0 <= threat["lane"] < LANE_COUNT, f"{stage.stage_id}: threats[{i}] lane invalida"
            assert 0.0 <= threat["strength"] <= 1.0, f"{stage.stage_id}: threats[{i}] strength invalida"
            assert threat["threat_type"] in base_config.threat_type_ids, (
                f"{stage.stage_id}: threats[{i}] tipo desconhecido"
            )


def test_tutorial_simultaneous_waves_are_bounded():
    """As ondas simultaneas do tutorial (dash) tem no maximo 3 ameacas e
    folga de respiro antes da proxima -- atravessaveis com UM dash."""
    for _, stage, beatmap in _load_all_stages():
        if not stage.tutorial_steps:
            continue
        timestamps = [t["timestamp_seconds"] for t in beatmap["threats"]]
        groups = {}
        for t in timestamps:
            groups[t] = groups.get(t, 0) + 1
        for when, size in groups.items():
            assert size <= 3, f"tutorial: onda de {size} ameacas simultaneas em {when}s"
            if size > 1:
                others = [t for t in sorted(set(timestamps)) if t != when]
                nearest = min(abs(t - when) for t in others)
                assert nearest >= 1.5, f"tutorial: onda em {when}s sem respiro (vizinho a {nearest}s)"
