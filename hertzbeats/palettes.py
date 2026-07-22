"""Meta-Jogo -- Paletas Cosmeticas: recolore Azul/Rosa da Polaridade, desbloqueadas por Rank."""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from hertzbeats.game_state import RANK_ORDER

PALETTE_CATALOG: Dict[str, Dict] = {
    "classic": {
        "label": "Classica (Azul/Rosa)",
        "threat_blue_rgb": (70, 140, 255),
        "threat_pink_rgb": (255, 90, 190),
        "unlock_rank": None,
    },
    "gold_silver": {
        "label": "Dourado/Prata",
        "threat_blue_rgb": (210, 210, 220),
        "threat_pink_rgb": (255, 214, 64),
        "unlock_rank": "S",
    },
    "neon": {
        "label": "Neon Verde/Roxo",
        "threat_blue_rgb": (140, 255, 120),
        "threat_pink_rgb": (190, 90, 255),
        "unlock_rank": "SS",
    },
}
"""Catalogo de paletas cosmeticas -- so recolore os 2 tints de Polaridade
(`HertzConfig.threat_blue_rgb`/`threat_pink_rgb`); o Anel de Convergencia
herda a cor da ameaca automaticamente (`RadialRhythmSpawnerSystem.
_spawn_convergence_ring`), sem precisar de um campo proprio. "classic" e'
o default de sempre (`unlock_rank=None`, sempre disponivel); as demais
exigem ter alcancado aquele Rank (ou melhor) em PELO MENOS uma fase/
musica salva em `player_progress.json` -- ver `unlocked_palette_ids`."""

DEFAULT_PALETTE_ID = "classic"


def _rank_reached(best_rank: Optional[str], required: str) -> bool:
    """`best_rank` e' PELO MENOS tao bom quanto `required` --
    `RANK_ORDER` e' MELHOR->PIOR, entao um indice MENOR OU IGUAL basta."""
    if best_rank not in RANK_ORDER:
        return False
    return RANK_ORDER.index(best_rank) <= RANK_ORDER.index(required)


def unlocked_palette_ids(player_progress: Dict[str, dict]) -> Tuple[str, ...]:
    """Paletas desbloqueadas PELO progresso salvo: `"classic"` sempre;
    as demais assim que QUALQUER fase/musica salva tiver `best_rank`
    igual ou melhor que `unlock_rank` daquela paleta -- pura, testavel
    sem `HertzGameLoop`. Mantem a ORDEM de `PALETTE_CATALOG` (a mesma em
    que o jogador vai ciclando no Vault)."""
    best_ranks = [entry.get("best_rank") for entry in player_progress.values()]
    unlocked = []
    for palette_id, palette in PALETTE_CATALOG.items():
        required = palette["unlock_rank"]
        if required is None or any(_rank_reached(rank, required) for rank in best_ranks):
            unlocked.append(palette_id)
    return tuple(unlocked)
