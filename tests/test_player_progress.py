"""Meta-Jogo -- Medalhas + Rank Maximo: player_progress.json acumula modifiers (uniao) e best_rank (so melhora)."""
from hertzbeats.player_progress import load_progress, record_stage_cleared


def test_loading_a_missing_file_returns_an_empty_dict(tmp_path):
    assert load_progress(str(tmp_path / "missing.json")) == {}


def test_loading_a_corrupted_file_returns_an_empty_dict(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("{ nao e json valido", encoding="utf-8")
    assert load_progress(str(path)) == {}


def test_record_stage_cleared_persists_and_reloads(tmp_path):
    path = str(tmp_path / "progress.json")
    record_stage_cleared("defender_1_iniciacao", ("telegraph_rings", "polarity"), rank="A", path=path)

    reloaded = load_progress(path)
    assert reloaded["defender_1_iniciacao"]["modifiers"] == frozenset({"telegraph_rings", "polarity"})
    assert reloaded["defender_1_iniciacao"]["best_rank"] == "A"


def test_record_stage_cleared_unions_modifiers_across_multiple_clears_never_replacing(tmp_path):
    path = str(tmp_path / "progress.json")
    record_stage_cleared("stage_x", ("polarity",), rank="B", path=path)
    record_stage_cleared("stage_x", ("holds",), rank="B", path=path)  # combinacao DIFERENTE da vez anterior

    progress = load_progress(path)
    assert progress["stage_x"]["modifiers"] == frozenset({"polarity", "holds"})  # as 2 medalhas convivem


def test_record_stage_cleared_with_no_modifiers_still_registers_the_stage(tmp_path):
    path = str(tmp_path / "progress.json")
    record_stage_cleared("plain_stage", (), rank="D", path=path)
    progress = load_progress(path)
    assert progress["plain_stage"]["modifiers"] == frozenset()
    assert progress["plain_stage"]["best_rank"] == "D"


def test_progress_for_different_stages_never_mixes(tmp_path):
    path = str(tmp_path / "progress.json")
    record_stage_cleared("stage_a", ("polarity",), rank="S", path=path)
    record_stage_cleared("stage_b", ("holds",), rank="C", path=path)

    progress = load_progress(path)
    assert progress["stage_a"]["modifiers"] == frozenset({"polarity"})
    assert progress["stage_b"]["modifiers"] == frozenset({"holds"})


# -- Rank Maximo: so melhora, nunca piora -----------------------------------


def test_best_rank_starts_unset_until_the_first_clear(tmp_path):
    path = str(tmp_path / "progress.json")
    record_stage_cleared("stage_x", (), rank=None, path=path)
    assert load_progress(path)["stage_x"]["best_rank"] is None


def test_a_better_rank_replaces_the_stored_one(tmp_path):
    path = str(tmp_path / "progress.json")
    record_stage_cleared("stage_x", (), rank="B", path=path)
    record_stage_cleared("stage_x", (), rank="S", path=path)
    assert load_progress(path)["stage_x"]["best_rank"] == "S"


def test_a_worse_rank_never_replaces_the_stored_one(tmp_path):
    path = str(tmp_path / "progress.json")
    record_stage_cleared("stage_x", (), rank="S", path=path)
    record_stage_cleared("stage_x", (), rank="C", path=path)  # partida pior, jogada de novo
    assert load_progress(path)["stage_x"]["best_rank"] == "S"


def test_the_placeholder_rank_never_overwrites_a_real_one(tmp_path):
    path = str(tmp_path / "progress.json")
    record_stage_cleared("stage_x", (), rank="D", path=path)
    record_stage_cleared("stage_x", (), rank="-", path=path)  # fase sem nenhuma nota resolvida
    assert load_progress(path)["stage_x"]["best_rank"] == "D"


def test_ss_is_recognized_as_the_best_possible_rank(tmp_path):
    path = str(tmp_path / "progress.json")
    record_stage_cleared("stage_x", (), rank="S", path=path)
    record_stage_cleared("stage_x", (), rank="SS", path=path)
    assert load_progress(path)["stage_x"]["best_rank"] == "SS"
