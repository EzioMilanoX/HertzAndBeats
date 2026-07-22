"""Meta-Jogo -- Paletas Cosmeticas: desbloqueio puro por Rank ja alcancado em alguma fase/musica."""
from hertzbeats.palettes import PALETTE_CATALOG, unlocked_palette_ids

_ALWAYS_UNLOCKED = ("classic", "colorblind", "monochrome")
"""`unlock_rank=None`: "classic" (default) e as 2 paletas de
Acessibilidade -- nunca condicionadas a desempenho/progresso."""


def test_only_the_always_unlocked_palettes_are_available_with_no_progress_at_all():
    assert unlocked_palette_ids({}) == _ALWAYS_UNLOCKED


def test_accessibility_palettes_are_never_gated_by_rank():
    """Daltonico/Monocromatico sao opcoes de ACESSIBILIDADE -- jamais faz
    sentido condiciona-las a desempenho, ao contrario das recompensas
    cosmeticas (gold_silver/neon)."""
    progress = {"stage_a": {"modifiers": frozenset(), "best_rank": "D"}}
    unlocked = unlocked_palette_ids(progress)
    assert "colorblind" in unlocked
    assert "monochrome" in unlocked


def test_gold_silver_unlocks_with_an_s_rank_somewhere():
    progress = {"stage_a": {"modifiers": frozenset(), "best_rank": "S"}}
    assert "gold_silver" in unlocked_palette_ids(progress)
    assert "neon" not in unlocked_palette_ids(progress)


def test_an_ss_rank_unlocks_both_gold_silver_and_neon():
    progress = {"stage_a": {"modifiers": frozenset(), "best_rank": "SS"}}
    unlocked = unlocked_palette_ids(progress)
    assert "gold_silver" in unlocked
    assert "neon" in unlocked


def test_a_rank_below_the_threshold_unlocks_nothing_extra():
    progress = {"stage_a": {"modifiers": frozenset(), "best_rank": "A"}}
    assert unlocked_palette_ids(progress) == _ALWAYS_UNLOCKED


def test_the_placeholder_rank_never_unlocks_anything():
    progress = {"stage_a": {"modifiers": frozenset(), "best_rank": "-"}}
    assert unlocked_palette_ids(progress) == _ALWAYS_UNLOCKED


def test_none_best_rank_never_unlocks_anything():
    progress = {"stage_a": {"modifiers": frozenset(), "best_rank": None}}
    assert unlocked_palette_ids(progress) == _ALWAYS_UNLOCKED


def test_only_one_good_stage_among_many_is_enough_to_unlock():
    progress = {
        "stage_a": {"modifiers": frozenset(), "best_rank": "C"},
        "stage_b": {"modifiers": frozenset(), "best_rank": "SS"},
    }
    assert "neon" in unlocked_palette_ids(progress)


def test_unlocked_ids_preserve_catalog_order():
    progress = {"stage_a": {"modifiers": frozenset(), "best_rank": "SS"}}
    assert unlocked_palette_ids(progress) == tuple(PALETTE_CATALOG.keys())
