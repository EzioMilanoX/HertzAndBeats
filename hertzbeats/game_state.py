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
        "shake_intensity",
        "shield_charges",
        "blindness_timer_sec",
        "lane_stutter_offset_y",
    )

    def __init__(self, max_health: int, shield_charges: int = 0) -> None:
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
        self.shake_intensity: float = 0.0
        """Tremor de tela ATUAL, em pixels de deslocamento maximo --
        a "variavel global de camera" que o `CameraShakeSystem` decai a
        cada frame (`HertzConfig.shake_decay_per_second`, mesmo par
        mutavel/tuning-estatico de `fever_meter`/`fever_decay_per_second`)
        e que o `HertzGameLoop` le a cada frame para transformar num
        offset aleatorio real via `IRenderer.set_camera_offset` (metodo
        JA EXISTENTE na engine, ROADMAP M1/M2 -- nao inventamos um novo).
        Qualquer sistema pode chamar `trigger_shake(...)`; NUNCA e
        escrito diretamente (sempre por esse metodo, que decide o
        criterio de sobreposicao de tremores concorrentes)."""
        self.shield_charges: int = int(shield_charges)
        """Arcade 4K -- Notas Longas classicas (opt-in, `holds_enabled`):
        quantas vezes o jogador pode QUEBRAR um Hold antes que passe a
        custar vida de verdade (o Arcade normalmente nao tira vida).
        Inicializado por `_compose_lanes_mode` a partir de
        `HertzConfig.lane_shield_max_charges`; `0` nos demais modos
        (nunca lido/decrementado la)."""
        self.blindness_timer_sec: float = 0.0
        """Vignette Flash ("Cegueira Ritmica", Arcade 4K -- Bombas):
        segundos restantes com a arena coberta por um overlay escuro
        com um buraco focado na linha de julgamento. Decai a cada frame
        (mesmo `CameraShakeSystem`/`shake_intensity`); o
        `HBPygameRenderer` so desenha o overlay enquanto `> 0`."""
        self.lane_stutter_offset_y: float = 0.0
        """Stutter Scroll (Arcade 4K, opt-in `stutter_scroll_enabled`):
        ruido visual ATUAL em Y (pixels), escrito todo frame pelo
        `VisualModifierSystem` (`sin(now_seconds * freq) * amplitude`).
        Lido pelo `HertzGameLoop._render_frame` (overrescrito) para
        deslocar so a POSICAO RENDERIZADA das notas do Arcade 4K no
        momento do `draw_batch` -- `transform.position_y` (a fisica
        REAL, que o `LaneJudgmentSystem`/`PhysicsSystem` usam) nunca e
        tocado, entao nao ha deriva acumulada frame a frame."""

    @property
    def is_blinded(self) -> bool:
        """True enquanto o Vignette Flash estiver ativo."""
        return self.blindness_timer_sec > 0.0

    def trigger_blindness(self, seconds: float) -> None:
        """Aciona/reforca a Cegueira Ritmica. Mesmo criterio de
        `trigger_shake`: usa `max()`, nao soma -- duas bombas seguidas
        nao empilham um tempo de cegueira absurdo."""
        self.blindness_timer_sec = max(self.blindness_timer_sec, float(seconds))

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

    def trigger_shake(self, intensity_px: float) -> None:
        """Aciona/reforca o tremor de tela. Usa `max()`, nao soma: dois
        tremores sobrepostos (ex.: um MISS de Hold bem no instante de uma
        parede letal) resultam no MAIOR dos dois, nao numa intensidade
        absurda que a soma produziria -- decai normalmente dali."""
        self.shake_intensity = max(self.shake_intensity, float(intensity_px))
