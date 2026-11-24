"""Geracao assistida de beatmap (`hertzbeats/offline/beatmap_assist.py` +
`tools/rascunho_beatmap.py`).

O audio de teste e uma MUSICA ORIGINAL sintetizada (`original_songs`), o
que da verdade fundamental: sabemos o BPM, onde cai o `1:1` e onde esta
cada bumbo/caixa -- entao da para medir a ferramenta, nao so ver que roda.
A deteccao roda no backend numpy (sem librosa): deterministico e sem
dependencia opcional; o backend librosa tem um teste proprio, pulado se
ela nao estiver instalada.
"""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from hertzbeats.audio.demo_track_synth import write_wav
from hertzbeats.audio.original_songs import SAMPLE_RATE, percussive_onset_times, render_song
from hertzbeats.offline.beatmap_assist import (
    DIFFICULTIES,
    LEVEL_BEAT,
    _max_lane_step,
    analyze_audio,
    draft_charts,
    load_audio,
    render_dsl,
)
from hertzbeats.offline.beatmap_dsl import (
    TYPE_ALIASES,
    BeatmapSyntaxError,
    compile_beatmap_source,
    lint_authored_beatmap,
)

SPEC = {
    "bpm": 170.0,
    "song": "hiperpulso",
    "sections": [{"name": "build", "bars": 4}, {"name": "drop", "bars": 12}, {"name": "fim", "bars": 2}],
}
LEAD_IN_SECONDS = 0.5


@pytest.fixture(scope="module")
def track(tmp_path_factory):
    path = tmp_path_factory.mktemp("assist") / "hiperpulso_curta.wav"
    write_wav(render_song(SPEC), path)
    return path


@pytest.fixture(scope="module")
def analysis(track):
    return analyze_audio(track, backend="numpy")


@pytest.fixture(scope="module")
def charts(analysis):
    return draft_charts(analysis, min_start_seconds=2.0, end_margin_seconds=1.0)


def _truth():
    return percussive_onset_times(SPEC)


def _nearest_errors(times, truth):
    index = np.searchsorted(truth, times).clip(1, truth.shape[0] - 1)
    return np.minimum(np.abs(times - truth[index - 1]), np.abs(times - truth[index]))


# ------------------------------------------------------------ deteccao


def test_detects_the_tempo_and_the_downbeat(analysis):
    assert analysis.backend == "numpy"
    assert analysis.bpm == pytest.approx(170.0, abs=0.05)
    bar = 4 * 60.0 / 170.0
    offset = min(analysis.offset_seconds % bar, bar - analysis.offset_seconds % bar)
    assert offset < 0.006, f"1:1 detectado {analysis.offset_seconds * 1000:.1f} ms fora do downbeat"


def test_onsets_are_refined_to_the_attack_not_the_flux_peak(analysis):
    """O vies que deixou os charts curados +18 ms atrasados: aqui o
    instante vem do ataque no sinal bruto e o vies some."""
    truth = _truth()
    errors = analysis.onset_times[:, None] - truth[None, :]
    nearest = errors[np.arange(errors.shape[0]), np.argmin(np.abs(errors), axis=1)]
    matched = nearest[np.abs(nearest) < 0.03]
    assert matched.shape[0] >= 0.8 * truth.shape[0]
    assert abs(float(np.median(matched))) < 0.004


def test_forced_bpm_and_offset_are_respected(track):
    forced = analyze_audio(track, backend="numpy", bpm=85.0, offset_seconds=0.25)
    assert forced.bpm == 85.0
    assert forced.offset_seconds == 0.25
    assert forced.bpm_candidates == ()


def test_a_lead_in_becomes_the_offset_directive(tmp_path):
    """Musica real tem silencio antes do 1o tempo forte: o rascunho tem de
    escrever `offset` e as notas compiladas cairem nos golpes reais."""
    samples = np.concatenate([np.zeros(int(LEAD_IN_SECONDS * SAMPLE_RATE)), render_song(SPEC)])
    path = tmp_path / "com_silencio.wav"
    write_wav(samples, path)
    shifted = analyze_audio(path, backend="numpy")
    assert shifted.offset_seconds == pytest.approx(LEAD_IN_SECONDS, abs=0.006)

    chart = draft_charts(shifted, ["normal"], min_start_seconds=2.0)["normal"]
    text = render_dsl(chart, shifted, path.name)
    assert "\noffset 0.5" in text
    compiled = compile_beatmap_source(text, track_id="x")
    times = np.array([t["timestamp_seconds"] for t in compiled["threats"]])
    assert np.median(_nearest_errors(times, _truth() + LEAD_IN_SECONDS)) < 0.006


def test_numpy_backend_reads_only_wav(tmp_path):
    with pytest.raises(ValueError, match="librosa"):
        load_audio(tmp_path / "musica.mp3", use_librosa=False)


def test_librosa_backend_agrees_when_installed(track):
    pytest.importorskip("librosa")
    result = analyze_audio(track, backend="librosa")
    assert result.backend == "librosa"
    assert result.bpm == pytest.approx(170.0, abs=0.05)


# ------------------------------------------------------------ rascunhos


@pytest.mark.parametrize("difficulty", list(DIFFICULTIES))
def test_every_draft_is_a_valid_beatmap_in_the_dsl(charts, analysis, difficulty):
    """O rascunho e TEXTO da DSL: tem de compilar com os tipos reais e
    passar no linter de jogabilidade antes de chegar ao dono."""
    text = render_dsl(charts[difficulty], analysis, "x.wav")
    assert text.startswith("# RASCUNHO")
    beatmap = compile_beatmap_source(text, track_id="x", known_types=tuple(TYPE_ALIASES.values()))
    assert len(beatmap["threats"]) == len(charts[difficulty].notes)
    assert lint_authored_beatmap(beatmap, 0.30, 2.6, track_duration_seconds=analysis.duration_seconds) == []
    for threat in beatmap["threats"]:
        assert 0 <= threat["lane"] < 8
        assert threat["threat_type"] in ("rhythm_threat_basic", "rhythm_threat_heavy")


def test_density_grows_with_difficulty(charts):
    counts = [len(charts[name].notes) for name in DIFFICULTIES]
    assert counts == sorted(counts) and len(set(counts)) == 3, counts
    for name, preset in DIFFICULTIES.items():
        times = np.array([n.time_seconds for n in charts[name].notes])
        span = times[-1] - times[0]
        assert np.diff(times).min() >= preset.min_gap_seconds - 1e-9, name
        # densidade-alvo e TETO (o guloso para ao atingi-la), com folga de 1 nota
        assert len(times) <= preset.target_density_per_second * span + 2, name


def test_easy_uses_only_beats(charts):
    assert all(note.level >= LEVEL_BEAT for note in charts["facil"].notes)


def test_difficulties_are_nested(charts):
    """Subir de dificuldade so ACRESCENTA notas: o que o jogador aprendeu
    no facil continua la no normal e no dificil."""
    facil, normal, dificil = ({n.slot for n in charts[name].notes} for name in DIFFICULTIES)
    assert facil <= normal <= dificil


def test_drafts_land_on_real_drum_hits(charts):
    truth = _truth()
    for name in DIFFICULTIES:
        times = np.array([n.time_seconds for n in charts[name].notes])
        on_drum = float(np.mean(_nearest_errors(times, truth) < 0.012))
        assert on_drum >= 0.85, f"{name}: so {on_drum:.0%} das notas em golpe de bateria"


def test_lane_moves_are_bounded_by_the_time_available(charts):
    """Nota proxima nunca pede atravessar a arena."""
    for name in DIFFICULTIES:
        notes = charts[name].notes
        for previous, current in zip(notes, notes[1:]):
            gap = current.time_seconds - previous.time_seconds
            step = min((current.lane - previous.lane) % 8, (previous.lane - current.lane) % 8)
            assert step <= _max_lane_step(gap) + 1, (name, previous, current)  # +1: anti-jack


def test_unknown_difficulty_is_rejected(analysis):
    with pytest.raises(ValueError, match="dificuldade"):
        draft_charts(analysis, ["insano"])


# ------------------------------------------------------------ CLI


def _load_tool(name):
    path = Path(__file__).resolve().parent.parent / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_tool_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_writes_one_draft_per_difficulty(track, tmp_path, capsys):
    tool = _load_tool("rascunho_beatmap")
    prefix = tmp_path / "charts" / "curta"
    code = tool.main(["--audio", str(track), "--saida", str(prefix), "--backend", "numpy", "--inicio", "2.0"])
    assert code == 0, capsys.readouterr().out
    for name in DIFFICULTIES:
        text = (tmp_path / "charts" / f"curta_{name}.hbm").read_text(encoding="utf-8")
        assert f"dificuldade: {name}" in text
        compile_beatmap_source(text, track_id="curta")


# ------------------------------------------------------------ DSL: offset


def test_dsl_offset_shifts_every_note():
    beatmap = compile_beatmap_source("bpm 120\noffset 0.25\n1:1 basic 0\n2:1 basic 1\n", track_id="x")
    assert [t["timestamp_seconds"] for t in beatmap["threats"]] == pytest.approx([0.25, 2.25])


@pytest.mark.parametrize(
    "source",
    ["bpm 120\noffset -1\n1:1 basic 0\n", "bpm 120\n1:1 basic 0\noffset 0.5\n", "bpm 120\noffset x\n1:1 basic 0\n"],
)
def test_dsl_offset_errors_point_to_the_line(source):
    with pytest.raises(BeatmapSyntaxError):
        compile_beatmap_source(source, track_id="x")
