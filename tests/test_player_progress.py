"""Meta-Jogo -- Medalhas: player_progress.json acumula (uniao, nunca substitui) os modifiers vencidos por fase."""
from hertzbeats.player_progress import load_progress, record_stage_cleared


def test_loading_a_missing_file_returns_an_empty_dict(tmp_path):
    assert load_progress(str(tmp_path / "missing.json")) == {}


def test_loading_a_corrupted_file_returns_an_empty_dict(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("{ nao e json valido", encoding="utf-8")
    assert load_progress(str(path)) == {}


def test_record_stage_cleared_persists_and_reloads(tmp_path):
    path = str(tmp_path / "progress.json")
    record_stage_cleared("defender_1_iniciacao", ("telegraph_rings", "polarity"), path=path)

    reloaded = load_progress(path)
    assert reloaded["defender_1_iniciacao"] == frozenset({"telegraph_rings", "polarity"})


def test_record_stage_cleared_unions_across_multiple_clears_never_replacing(tmp_path):
    path = str(tmp_path / "progress.json")
    record_stage_cleared("stage_x", ("polarity",), path=path)
    record_stage_cleared("stage_x", ("holds",), path=path)  # combinacao DIFERENTE da vez anterior

    progress = load_progress(path)
    assert progress["stage_x"] == frozenset({"polarity", "holds"})  # as 2 medalhas convivem


def test_record_stage_cleared_with_no_modifiers_still_registers_the_stage(tmp_path):
    path = str(tmp_path / "progress.json")
    record_stage_cleared("plain_stage", (), path=path)
    progress = load_progress(path)
    assert progress["plain_stage"] == frozenset()


def test_progress_for_different_stages_never_mixes(tmp_path):
    path = str(tmp_path / "progress.json")
    record_stage_cleared("stage_a", ("polarity",), path=path)
    record_stage_cleared("stage_b", ("holds",), path=path)

    progress = load_progress(path)
    assert progress["stage_a"] == frozenset({"polarity"})
    assert progress["stage_b"] == frozenset({"holds"})
