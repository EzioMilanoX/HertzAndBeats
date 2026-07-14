"""Placar global da partida: o equivalente das "variaveis globais no World" da arquitetura."""
from __future__ import annotations

from hertzbeats.components.schemas import JUDGMENT_PENDING


class GameState:
    """
    Placar/estado global da partida, alocado UMA UNICA VEZ na composicao
    e injetado nos sistemas que leem/escrevem pontuacao
    (`JudgmentSystem`, `CoreDamageSystem`, `UIRenderSystem`).

    O `World` da engine e agnostico de produto e nao possui campos de
    placar; este objeto cumpre o papel de "variaveis globais de
    pontuacao no World" da arquitetura sem tocar o nucleo. Mutar
    atributos primitivos de uma instancia pre-alocada e Zero-GC pelo
    mesmo criterio dos contadores internos da engine (ex.:
    `World._pending_destroy_count`).
    """

    __slots__ = (
        "score",
        "combo_count",
        "max_combo",
        "perfect_count",
        "good_count",
        "miss_count",
        "dodge_count",
        "health",
        "last_judgment",
        "judgment_display_seconds_left",
    )

    def __init__(self, max_health: int) -> None:
        self.score: int = 0
        self.combo_count: int = 0
        self.max_combo: int = 0
        self.perfect_count: int = 0
        self.good_count: int = 0
        self.miss_count: int = 0
        self.dodge_count: int = 0
        self.health: int = max_health
        self.last_judgment: int = JUDGMENT_PENDING
        self.judgment_display_seconds_left: float = 0.0

    def register_judgment_feedback(self, judgment: int, display_seconds: float) -> None:
        """Atualiza o feedback visual de julgamento consumido pelo
        `UIRenderSystem` (palavra PERFECT/GOOD/MISS por alguns frames).
        """
        self.last_judgment = judgment
        self.judgment_display_seconds_left = display_seconds
