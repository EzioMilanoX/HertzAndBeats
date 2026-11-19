"""DSL de autoria: escrever chart a mao em compasso:batida, com linter.

O formato do beatmap sempre foi trivial e o tutorial sempre foi autoral --
mas nao havia ferramenta: escrever um chefao significava calcular
`timestamp_seconds` numa calculadora, e um erro de arredondamento ali nao
falha em teste nenhum, a nota so cai fora da batida.

O que estes testes protegem, em ordem de importancia: a aritmetica
compasso->segundos, o REPORTE DE LINHA de cada erro (a razao de a DSL
existir), e o linter que roda as invariantes de jogabilidade antes de o
chart chegar ao jogo.
"""
import pytest

from hertzbeats.offline.beatmap_dsl import (
    TYPE_ALIASES,
    BeatmapSyntaxError,
    bar_beat_to_seconds,
    compile_beatmap_source,
    lint_authored_beatmap,
)


def _compile(source, **kwargs):
    return compile_beatmap_source(source, track_id="teste", **kwargs)


# ------------------------------------------------------------- aritmetica


@pytest.mark.parametrize(
    "bar,beat,bpm,expected",
    [
        (1, 1.0, 120.0, 0.0),  # 1:1 e o instante zero
        (1, 2.0, 120.0, 0.5),  # 1 batida a 120 BPM
        (2, 1.0, 120.0, 2.0),  # 1 compasso = 4 batidas
        (5, 2.5, 150.0, 7.0),  # batida fracionaria: (4*4 + 1.5) * 0.4s
    ],
)
def test_bar_beat_to_seconds(bar, beat, bpm, expected):
    assert bar_beat_to_seconds(bar, beat, bpm) == pytest.approx(expected)


def test_notes_carry_the_computed_time():
    beatmap = _compile("bpm 120\n2:1 basic 0\n")
    assert beatmap["threats"][0]["timestamp_seconds"] == pytest.approx(2.0)


def test_output_is_always_sorted_in_time():
    """Um chart escrito por secoes sai fora de ordem com facilidade, e o
    jogo exige `timestamp_seconds` crescente."""
    beatmap = _compile("bpm 120\n9:1 basic 0\n2:1 basic 1\n5:1 basic 2\n")
    times = [t["timestamp_seconds"] for t in beatmap["threats"]]
    assert times == sorted(times)


# ---------------------------------------------------------------- sintaxe


def test_comments_and_blank_lines_are_ignored():
    beatmap = _compile("# titulo\nbpm 120\n\n2:1 basic 0  # o downbeat\n")
    assert len(beatmap["threats"]) == 1


def test_aliases_resolve_to_real_threat_types():
    beatmap = _compile("bpm 120\n2:1 heavy 0\n")
    assert beatmap["threats"][0]["threat_type"] == TYPE_ALIASES["heavy"]


def test_strength_defaults_and_overrides():
    beatmap = _compile("bpm 120\n2:1 basic 0\n3:1 heavy 1 0.95\n")
    assert beatmap["threats"][0]["strength"] == 0.5
    assert beatmap["threats"][1]["strength"] == 0.95


def test_repetition_expands_into_evenly_spaced_notes():
    """`5:1..4:1` = 4 notas a partir de 5:1, uma por batida. Sem isso, um
    groove de 16 compassos seria 64 linhas escritas a mao."""
    beatmap = _compile("bpm 120\n5:1..4:1 basic 0\n")
    times = [t["timestamp_seconds"] for t in beatmap["threats"]]
    assert len(times) == 4
    assert times == pytest.approx([8.0, 8.5, 9.0, 9.5])


def test_repetition_step_can_be_fractional():
    beatmap = _compile("bpm 120\n5:1..3:0.5 basic 0\n")
    times = [t["timestamp_seconds"] for t in beatmap["threats"]]
    assert times == pytest.approx([8.0, 8.25, 8.5])


def test_lane_count_bounds_the_lanes():
    _compile("bpm 120\nlane_count 4\n2:1 basic 3\n")
    with pytest.raises(BeatmapSyntaxError, match="pista 4 fora"):
        _compile("bpm 120\nlane_count 4\n2:1 basic 4\n")


def test_known_types_from_config_are_enforced():
    """Um apelido valido cujo `threat_type` nao existe NA CONFIG da fase
    (ex. `bomb` sem o modificador de bombas) tem de falhar na compilacao."""
    with pytest.raises(BeatmapSyntaxError, match="nao existe na config"):
        _compile("bpm 120\n2:1 bomb 0\n", known_types=("rhythm_threat_basic",))


@pytest.mark.parametrize(
    "source,expected_line,fragment",
    [
        ("bpm 150\n5:1 basico 0\n", 2, "tipo 'basico' desconhecido"),
        ("5:1 basic 0\n", 1, "antes de declarar `bpm`"),
        ("bpm 150\n5 basic 0\n", 2, "sem ':'"),
        ("bpm 150\n0:1 basic 0\n", 2, "1-indexada"),
        ("bpm 150\n5:9 basic 0\n", 2, "fora de [1, 5)"),
        ("bpm 150\n5:1 basic 0 1.5\n", 2, "forca 1.5 fora"),
        ("bpm 150\n5:1 basic x\n", 2, "nao inteira"),
        ("bpm zero\n", 1, "invalido"),
        ("bpm 0\n", 1, "> 0"),
        ("bpm 150\n5:1 basic\n", 2, "use:"),
        ("bpm 150\n5:1..x:1 basic 0\n", 2, "nao numerica"),
    ],
)
def test_every_error_names_the_offending_line(source, expected_line, fragment):
    """O reporte de LINHA e o motivo principal de a DSL existir em vez de
    se editar JSON a mao."""
    with pytest.raises(BeatmapSyntaxError) as caught:
        _compile(source)
    assert caught.value.line_number == expected_line
    assert fragment in str(caught.value)


def test_empty_and_bpm_only_files_are_rejected():
    with pytest.raises(BeatmapSyntaxError, match="sem `bpm`"):
        _compile("# so um comentario\n")
    with pytest.raises(BeatmapSyntaxError, match="sem nenhuma nota"):
        _compile("bpm 120\n")


# ----------------------------------------------------------------- linter


def test_lint_accepts_a_playable_chart():
    beatmap = _compile("bpm 150\n5:1..4:1 basic 0\n")  # 0.4s de gap a 150 BPM
    assert lint_authored_beatmap(beatmap, 0.30, 2.6) == []


def test_lint_flags_a_gap_below_the_playability_floor():
    """A violacao facil de cometer a mao -- e a mesma que a curadoria por
    secao cometeu quando autorada a 0.2s."""
    beatmap = _compile("bpm 150\n5:1 basic 0\n5:1.5 basic 1\n")
    problems = lint_authored_beatmap(beatmap, 0.30, 2.6)
    assert len(problems) == 1
    assert "linha 3" in problems[0] and "0.200s" in problems[0]


def test_lint_flags_a_note_too_close_to_the_end_of_the_track():
    """Ameaca depois do fim da musica e softlock: o relogio de audio
    congela quando a faixa acaba e a fase nunca conclui."""
    beatmap = _compile("bpm 150\n1:1 basic 0\n28:4 basic 1\n")
    problems = lint_authored_beatmap(beatmap, 0.30, 2.6, track_duration_seconds=44.8)
    assert any("softlock" in p for p in problems)


def test_lint_flags_excessive_mean_density():
    beatmap = _compile("bpm 150\n1:1..40:1 basic 0\n")
    problems = lint_authored_beatmap(beatmap, 0.30, 2.6, track_duration_seconds=8.0)
    assert any("densidade media" in p for p in problems)


def test_lint_skips_duration_checks_without_a_reference_track():
    """Sem faixa de referencia nao ha como julgar margem de fim nem
    densidade -- e melhor nao checar do que checar contra um palpite."""
    beatmap = _compile("bpm 150\n1:1..40:1 basic 0\n")
    assert lint_authored_beatmap(beatmap, 0.30, 2.6) == []


# ------------------------------------------------- o exemplo versionado


def test_the_versioned_example_chart_compiles_and_passes_lint():
    """`charts/exemplo_chefao.hbm` e documentacao EXECUTAVEL da DSL: se a
    sintaxe mudar e o exemplo parar de compilar, este teste avisa."""
    from pathlib import Path

    source = Path("charts/exemplo_chefao.hbm").read_text(encoding="utf-8")
    beatmap = compile_beatmap_source(source, track_id="exemplo")
    assert len(beatmap["threats"]) > 20
    assert lint_authored_beatmap(beatmap, 0.30, 2.6, track_duration_seconds=44.8) == []
