"""Rogue-lite Endgame: estado de uma corrida, catalogo de Perks e sorteio do Mapa/Recompensa."""
from __future__ import annotations

import random
from typing import Dict, FrozenSet, Sequence, Tuple

PERK_VAMPIRISM_THRESHOLD = "vampirism_threshold"
PERK_PERFECT_WINDOW_MULTIPLIER = "perfect_window_multiplier"

ROGUE_PERK_CATALOG: Dict[str, Dict[str, object]] = {
    PERK_VAMPIRISM_THRESHOLD: {
        "label": "Vampirismo",
        "vampirism_combo_threshold": 10,
    },
    PERK_PERFECT_WINDOW_MULTIPLIER: {
        "label": "Janela Ampliada",
        "perfect_window_multiplier": 1.15,
    },
}
"""Catalogo de Perks do Rogue-lite -- cada entrada guarda os valores de
afinacao PUROS (multiplicadores/limiares primitivos) resolvidos UMA
UNICA vez na composicao da fase (`HertzGameLoop._compose_stage`, via
`dataclasses.replace` sobre a `HertzConfig` -- ver `resolve_rogue_perks`
em `stages.py`/composicao) -- nunca uma checagem de string dentro do
loop do `JudgmentSystem`. `JudgmentSystem` so enxerga
`vampirism_combo_threshold`/`perfect_window_seconds` ja resolvidos, sem
saber que "Perks" ou "Rogue-lite" existem."""

_MIND_GAMES_MODIFIER_POOL: Tuple[str, ...] = ("wormholes", "mirages", "rubber_band")
"""As 3 mecanicas de Mind Games (Buracos de Minhoca/Ameacas Fantasmas/
Efeito Elastico) sao o repertorio de modifiers FORCADOS do Mapa
Rogue-lite -- cada uma das 2 opcoes de musica recebe UMA distinta
(nunca as duas iguais), o contraste que da nome ao Mapa ("Musica A com
Eclipses vs Musica B com Notas Ocultas" no pedido original)."""


class RogueRunState:
    """Estado de UMA corrida Rogue-lite, persistente ENTRE fases --
    sobrevive a recomposicao de `GameState` a cada musica nova
    (`HertzGameLoop._rogue_run` guarda esta MESMA instancia e a injeta
    em `GameState.rogue_run` a cada `_compose_stage`, mesmo criterio ja
    usado por `HertzGameLoop._ironman_carried_health` para vida
    carregada entre fases do Ironman). `GameState.health` continua
    sendo a copia VIVA usada por `CoreDamageSystem`/`JudgmentSystem`
    durante a fase; `HertzGameLoop` sincroniza `health` de volta pra
    ca ao fim de cada fase (vitoria ou derrota), nunca no meio dela.
    """

    __slots__ = ("health", "perks", "stage_level")

    def __init__(
        self, health: int, perks: FrozenSet[str] = frozenset(), stage_level: int = 1,
    ) -> None:
        self.health = int(health)
        self.perks: FrozenSet[str] = frozenset(perks)
        self.stage_level = int(stage_level)


def roll_map_choices(
    free_play_entries: Sequence[Tuple[int, object]], rng: random.Random,
) -> Tuple[Tuple[int, Tuple[str, ...]], Tuple[int, Tuple[str, ...]]]:
    """Sorteia as 2 opcoes de musica do Mapa Rogue-lite a partir das
    entradas `(indice_original, StageDef)` de `HertzGameLoop.
    free_play_entries()` -- cada uma ganha UM modifier de Mind Games
    distinto forcado (`_MIND_GAMES_MODIFIER_POOL`). Com menos de 2
    musicas de jogador disponiveis, repete a mesma opcao (o repertorio
    vazio ja e tolerado do mesmo jeito pelo Free Play normal)."""
    if not free_play_entries:
        return (), ()
    pool = list(free_play_entries)
    picks = rng.sample(pool, k=min(2, len(pool)))
    if len(picks) == 1:
        picks = picks * 2
    modifiers = rng.sample(_MIND_GAMES_MODIFIER_POOL, k=2)
    return (
        (picks[0][0], (modifiers[0],)),
        (picks[1][0], (modifiers[1],)),
    )


def roll_perk_choices(owned_perks: FrozenSet[str], rng: random.Random) -> Tuple[str, ...]:
    """Sorteia 2 Perks distintos do catalogo, priorizando os que o
    jogador AINDA nao tem nesta corrida -- se sobrar so 1 (ou 0) inedito,
    oferece repetido em vez de travar a tela de Recompensa sem opcao."""
    available = [perk_id for perk_id in ROGUE_PERK_CATALOG if perk_id not in owned_perks]
    if not available:
        available = list(ROGUE_PERK_CATALOG)
    picks = rng.sample(available, k=min(2, len(available)))
    if len(picks) == 1:
        picks = picks * 2
    return tuple(picks)
