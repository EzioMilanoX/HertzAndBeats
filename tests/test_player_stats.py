"""Meta-Jogo -- Estatisticas Globais: player_lifetime_stats.json acumula PERFECTs/tiros/tempo entre partidas."""
from hertzbeats.player_stats import load_stats, record_match_stats


def test_loading_a_missing_file_returns_zeroed_defaults(tmp_path):
    assert load_stats(str(tmp_path / "missing.json")) == {
        "lifetime_perfect_count": 0, "lifetime_shots_fired": 0, "lifetime_playtime_seconds": 0.0,
    }


def test_loading_a_corrupted_file_returns_zeroed_defaults(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("{ nao e json valido", encoding="utf-8")
    assert load_stats(str(path)) == {
        "lifetime_perfect_count": 0, "lifetime_shots_fired": 0, "lifetime_playtime_seconds": 0.0,
    }


def test_record_match_stats_persists_and_reloads(tmp_path):
    path = str(tmp_path / "stats.json")
    record_match_stats(perfect_count=10, shots_fired=15, playtime_seconds=42.5, path=path)

    reloaded = load_stats(path)
    assert reloaded["lifetime_perfect_count"] == 10
    assert reloaded["lifetime_shots_fired"] == 15
    assert reloaded["lifetime_playtime_seconds"] == 42.5


def test_record_match_stats_accumulates_across_multiple_matches(tmp_path):
    path = str(tmp_path / "stats.json")
    record_match_stats(perfect_count=10, shots_fired=15, playtime_seconds=42.5, path=path)
    record_match_stats(perfect_count=3, shots_fired=8, playtime_seconds=12.0, path=path)

    stats = load_stats(path)
    assert stats["lifetime_perfect_count"] == 13
    assert stats["lifetime_shots_fired"] == 23
    assert stats["lifetime_playtime_seconds"] == 54.5


def test_a_lost_match_still_accumulates_its_stats(tmp_path):
    """Um PERFECT continua contando mesmo numa tentativa que terminou em
    Game Over -- estatisticas vitalicias nao dependem de vencer a fase."""
    path = str(tmp_path / "stats.json")
    record_match_stats(perfect_count=2, shots_fired=5, playtime_seconds=8.0, path=path)
    assert load_stats(path)["lifetime_perfect_count"] == 2


def test_record_match_stats_returns_the_updated_totals(tmp_path):
    path = str(tmp_path / "stats.json")
    result = record_match_stats(perfect_count=1, shots_fired=1, playtime_seconds=1.0, path=path)
    assert result == load_stats(path)
