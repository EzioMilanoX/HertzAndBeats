"""Treino por Secao e Diagnostico por Secao -- as duas metades do mesmo ciclo.

A tela de resultados diz ONDE o jogador perdeu; o Treino por Secao deixa
ele praticar exatamente aquele trecho (`--section climax`) em vez de
repetir a musica inteira pra chegar onde falhou. Nenhuma das duas era
possivel antes de as faixas terem estrutura nomeada.
"""
import dataclasses
import json

import pytest

from hertzbeats.config import HertzConfig
from hertzbeats.section_diagnostics import (
    accumulate_section_misses,
    format_section_report,
    section_for_time,
    worst_section,
)
from hertzbeats.stages import load_stages, resolve_stage_config

WINDOWS = (("intro", 0.0, 6.4), ("assalto", 6.4, 19.2), ("ponte", 19.2, 25.6), ("climax", 25.6, 44.8))


# ------------------------------------------------------------- atribuicao


@pytest.mark.parametrize(
    "time_seconds,expected",
    [
        (0.0, "intro"),
        (6.39, "intro"),
        (6.4, "assalto"),  # fronteira pertence a secao que COMECA
        (20.0, "ponte"),
        (44.79, "climax"),
        (44.8, None),  # depois do fim da faixa
        (-1.0, None),
    ],
)
def test_section_for_time(time_seconds, expected):
    assert section_for_time(WINDOWS, time_seconds) == expected


def test_flat_track_has_no_sections_to_attribute_to():
    """Faixa plana (a maioria das musicas do jogador): o diagnostico
    simplesmente nao se aplica, em vez de inventar uma secao."""
    assert section_for_time((), 10.0) is None
    assert accumulate_section_misses({}, (), 10.0, 3) == {}


def test_misses_land_in_the_section_that_was_playing():
    counts = {}
    accumulate_section_misses(counts, WINDOWS, 21.0, 2)
    accumulate_section_misses(counts, WINDOWS, 30.0, 5)
    accumulate_section_misses(counts, WINDOWS, 31.0, 1)
    assert counts == {"ponte": 2, "climax": 6}


def test_zero_or_negative_new_misses_change_nothing():
    """O detector roda TODO frame; na esmagadora maioria deles o delta e
    zero e a funcao nao pode nem criar chave."""
    assert accumulate_section_misses({}, WINDOWS, 10.0, 0) == {}
    assert accumulate_section_misses({}, WINDOWS, 10.0, -3) == {}


# ---------------------------------------------------------------- pior secao


def test_worst_section_is_the_one_with_most_misses():
    assert worst_section({"intro": 1, "assalto": 4, "climax": 9}) == ("climax", 9)


def test_no_misses_means_no_worst_section():
    assert worst_section({}) is None
    assert worst_section({"intro": 0, "climax": 0}) is None


def test_ties_go_to_the_earliest_section():
    """Empate resolve pela secao mais CEDO: um erro cedo custa o combo de
    tudo que vem depois, entao praticar o primeiro trecho problematico e
    melhor conselho do que praticar o ultimo."""
    counts = {}
    for name in ("intro", "assalto", "climax"):
        counts[name] = 0
    counts["assalto"] = 4
    counts["climax"] = 4
    assert worst_section(counts) == ("assalto", 4)


def test_report_mentions_the_worst_section_and_the_breakdown():
    text = format_section_report({"intro": 1, "climax": 7})
    assert "climax" in text and "7" in text and "intro=1" in text


def test_report_when_the_player_never_missed():
    assert "nenhum miss" in format_section_report({"intro": 0})


# --------------------------------------------------- janela pedida na fase


@pytest.fixture
def base_config():
    return HertzConfig.from_json("data/config/hertz_beats.config.json")


@pytest.fixture
def sectioned_stage():
    return next(
        s
        for s in load_stages("data/stages/stages.json")
        if s.synth is not None and s.synth.get("sections")
    )


def test_named_section_resolves_to_its_time_window(base_config, sectioned_stage):
    name = sectioned_stage.synth["sections"][-1]["name"]
    config = resolve_stage_config(
        dataclasses.replace(base_config, practice_section=name), sectioned_stage
    )
    assert config.practice_section_end_seconds > config.practice_section_start_seconds


def test_no_section_requested_means_the_whole_stage(base_config, sectioned_stage):
    config = resolve_stage_config(base_config, sectioned_stage)
    assert config.practice_section_start_seconds == config.practice_section_end_seconds == 0.0


def test_unknown_section_falls_back_to_the_whole_stage(base_config, sectioned_stage):
    """Errar o nome nao pode deixar o jogador numa fase vazia."""
    config = resolve_stage_config(
        dataclasses.replace(base_config, practice_section="nao_existe"), sectioned_stage
    )
    assert config.practice_section_start_seconds == config.practice_section_end_seconds == 0.0


def test_section_window_stretches_with_the_playback_rate(base_config, sectioned_stage):
    """Pedir o climax a 0.75x tem de cair no mesmo trecho MUSICAL: o audio
    estica, os nomes nao. Sem escalar a janela, o treino comecaria no
    compasso errado."""
    name = sectioned_stage.synth["sections"][-1]["name"]
    normal = resolve_stage_config(
        dataclasses.replace(base_config, practice_section=name), sectioned_stage
    )
    slowed = resolve_stage_config(
        dataclasses.replace(base_config, practice_section=name, playback_rate=0.75),
        sectioned_stage,
    )
    assert slowed.practice_section_start_seconds == pytest.approx(
        normal.practice_section_start_seconds / 0.75
    )


def test_requested_section_contains_fewer_threats_than_the_whole_stage(
    base_config, sectioned_stage
):
    """O efeito util, medido no beatmap real: praticar uma secao ve so as
    ameacas dela."""
    with open(sectioned_stage.beatmap_path, encoding="utf-8") as f:
        times = [t["timestamp_seconds"] for t in json.load(f)["threats"]]
    name = sectioned_stage.synth["sections"][-1]["name"]
    config = resolve_stage_config(
        dataclasses.replace(base_config, practice_section=name), sectioned_stage
    )
    inside = [
        t
        for t in times
        if config.practice_section_start_seconds <= t < config.practice_section_end_seconds
    ]
    assert 0 < len(inside) < len(times)
