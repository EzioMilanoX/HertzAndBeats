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
        "misfire_count",
        "survive_count",
        "health",
        "last_judgment",
        "judgment_display_seconds_left",
        "graze_score",
        "fever_meter",
        "parry_count",
        "deflect_count",
    )

    def __init__(self, max_health: int) -> None:
        self.score: int = 0
        self.combo_count: int = 0
        self.max_combo: int = 0
        self.perfect_count: int = 0
        self.good_count: int = 0
        self.miss_count: int = 0
        self.dodge_count: int = 0
        self.misfire_count: int = 0
        self.survive_count: int = 0
        self.health: int = max_health
        self.last_judgment: int = JUDGMENT_PENDING
        self.judgment_display_seconds_left: float = 0.0
        self.graze_score: int = 0
        """Modo Sobrevivencia: pontos de "raspar" perto de uma parede
        letal sem tocar -- estilo Touhou. Alimenta `fever_meter`."""
        self.fever_meter: float = 0.0
        """0..1: enche com Graze, decai com o tempo (ver
        `GrazeSystem`/`survival_fever_decay_per_second`). Em 1.0, a
        pontuacao de Graze e de sobrevivencia dobra (`in_fever`)."""
        self.parry_count: int = 0
        """Defensor (Polaridade): ameacas pesadas refletidas com sucesso
        no PERFECT."""
        self.deflect_count: int = 0
        """Defensor (Polaridade): tiros no tempo certo mas na cor
        errada -- nao pune, so nao acerta."""

    @property
    def in_fever(self) -> bool:
        """True quando `fever_meter` esta cheio -- dobra a pontuacao de
        Graze/sobrevivencia enquanto durar."""
        return self.fever_meter >= 1.0

    def register_judgment_feedback(self, judgment: int, display_seconds: float) -> None:
        """Atualiza o feedback visual de julgamento consumido pelo
        `UIRenderSystem` (palavra PERFECT/GOOD/MISS por alguns frames).
        """
        self.last_judgment = judgment
        self.judgment_display_seconds_left = display_seconds
