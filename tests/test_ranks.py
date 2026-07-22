"""Meta-Jogo -- Ranks: SS/S/A/B/C/D calculados por precisao ponderada a partir dos contadores do GameState."""
from hertzbeats.game_state import RANK_ORDER, compute_rank


def test_no_notes_resolved_returns_the_placeholder_rank():
    assert compute_rank(0, 0, 0) == "-"


def test_all_perfect_and_nothing_else_is_ss():
    assert compute_rank(10, 0, 0) == "SS"


def test_a_single_good_among_perfects_is_not_ss_and_the_boundary_is_strict():
    # precisao = (9 + 1*0.5) / 10 = 0.95 EXATAMENTE -- o limiar de S e
    # "> 0.95" (estrito), entao 0.95 cai um degrau, pra A.
    assert compute_rank(9, 1, 0) == "A"


def test_precision_tiers_use_strict_greater_than_thresholds():
    assert compute_rank(97, 2, 1) == "S"  # precisao 0.98 > 0.95
    assert compute_rank(86, 0, 14) == "A"  # precisao 0.86 > 0.85
    assert compute_rank(71, 0, 29) == "B"  # precisao 0.71 > 0.70
    assert compute_rank(51, 0, 49) == "C"  # precisao 0.51 > 0.50
    assert compute_rank(50, 0, 50) == "D"  # precisao exatamente 0.50 -> nao > 0.50


def test_only_misses_is_d():
    assert compute_rank(0, 0, 20) == "D"


def test_good_counts_half_of_a_perfect():
    # 10 GOODs sozinhos: precisao = 5/10 = 0.50 -> D (nao > 0.50)
    assert compute_rank(0, 10, 0) == "D"


def test_rank_order_lists_every_tier_best_to_worst():
    assert RANK_ORDER == ("SS", "S", "A", "B", "C", "D")
