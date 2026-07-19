"""Modificadores puramente visuais do Arcade 4K: Stutter Scroll (ruido em Y) e Hidden (fade de tint_a) -- nenhum toca o julgamento."""
from __future__ import annotations

import math

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock

from hertzbeats.components.schemas import JUDGMENT_PENDING, MODE_TAG_LANES
from hertzbeats.game_state import GameState


def compute_stutter_offset_y(now_effective: float, frequency_hz: float, amplitude_px: float) -> float:
    """`sin(now_seconds * freq) * amplitude` -- puro e sem estado,
    testavel sem ECS. Um UNICO valor GLOBAL (nao por nota): todas as
    notas do Arcade 4K "gaguejam" em uníssono no momento do
    `draw_batch`, nunca na posicao fisica real."""
    return amplitude_px * math.sin(now_effective * frequency_hz)


def compute_hidden_alpha(delta_seconds: float, fade_seconds: float) -> int:
    """Notas Fantasmas (Hidden): fracao de `tint_a` (0..255) de uma nota
    a `delta_seconds` do julgamento -- 255 (opaca) para `delta >=
    fade_seconds`, decaindo LINEARMENTE ate 0 (invisivel) exatamente em
    `delta == 0`. Pura, testavel sem ECS."""
    if fade_seconds <= 0.0:
        return 255 if delta_seconds > 0.0 else 0
    fraction = max(0.0, min(1.0, delta_seconds / fade_seconds))
    return int(round(fraction * 255))


class VisualModifierSystem(ISystem):
    """
    Dois modificadores puramente ESTETICOS do Arcade 4K, nenhum deles
    lido pelo `LaneJudgmentSystem` (100% temporal, nunca posicao/tint):

    - **Stutter Scroll**: escreve `GameState.lane_stutter_offset_y` a
      cada frame (`compute_stutter_offset_y`) -- o `HertzGameLoop`
      (`_render_frame` overrescrito) soma esse ruido SO na posicao
      RENDERIZADA, no momento do `draw_batch`; `transform.position_y`
      (a fisica real que o `PhysicsSystem` integra) nunca e tocado.
    - **Hidden (Notas Fantasmas)**, opt-in via `hidden_notes_enabled`:
      `delta = target_hit_time_sec - agora_efetivo` para toda nota AINDA
      PENDENTE e nao engajada/Scratch; dentro de `hidden_fade_seconds`
      do julgamento, `sprite.tint_a` interpola linearmente de 255 ate 0
      (`compute_hidden_alpha`) -- a nota fica progressivamente invisivel,
      mas sua janela de acerto (puramente temporal) nao muda em nada.

    Registrado ANTES do `UIRenderSystem` na ordem de sistemas: os dois
    valores ficam prontos antes do `HertzGameLoop` ler/renderizar.

    Zero-GC: Stutter e um escalar por frame; Hidden e vetorizado sobre
    as poucas linhas candidatas (fancy indexing em buffers ja
    pre-alocados, mesmo idioma do resto do jogo).
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        memory_manager: MemoryManager,
        game_state: GameState,
        frequency_hz: float,
        amplitude_px: float,
        hidden_notes_enabled: bool = False,
        hidden_fade_seconds: float = 0.5,
    ) -> None:
        self._audio_clock = audio_clock
        self._threat_pool = memory_manager.get_pool("rhythm_threat")
        self._sprite_pool = memory_manager.get_pool("sprite")
        self._game_state = game_state
        self._frequency_hz = float(frequency_hz)
        self._amplitude_px = float(amplitude_px)
        self._hidden_notes_enabled = bool(hidden_notes_enabled)
        self._hidden_fade_seconds = float(hidden_fade_seconds)

        capacity = self._threat_pool.capacity
        self._delta_buffer = np.zeros(capacity, dtype=np.float64)
        self._owned_mask = np.zeros(capacity, dtype=bool)
        self._scratch_mask = np.zeros(capacity, dtype=bool)
        self._fraction_buffer = np.zeros(capacity, dtype=np.float64)

    def update(self, world: World, delta_time: float) -> None:
        del world, delta_time
        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )
        self._game_state.lane_stutter_offset_y = compute_stutter_offset_y(
            now_effective, self._frequency_hz, self._amplitude_px
        )
        if self._hidden_notes_enabled:
            self._apply_hidden_fade(now_effective)

    def _apply_hidden_fade(self, now_effective: float) -> None:
        active_count = self._threat_pool.count
        if active_count == 0:
            return
        threat_view = self._threat_pool.active_view()

        owned = self._owned_mask[:active_count]
        np.equal(threat_view["mode_tag"], MODE_TAG_LANES, out=owned)
        pending = self._scratch_mask[:active_count]
        np.equal(threat_view["judgment"], JUDGMENT_PENDING, out=pending)
        np.logical_and(owned, pending, out=owned)
        # notas ja engajadas (Hold sustentando) ou de Scratch tem seu
        # PROPRIO tratamento visual -- o fade nao se aplica a elas.
        not_engaged = self._scratch_mask[:active_count]
        np.logical_not(threat_view["is_hit"], out=not_engaged)
        np.logical_and(owned, not_engaged, out=owned)
        not_scratch = self._scratch_mask[:active_count]
        np.logical_not(threat_view["is_hold"], out=not_scratch)
        np.logical_and(owned, not_scratch, out=owned)

        deltas = self._delta_buffer[:active_count]
        np.subtract(threat_view["target_hit_time_sec"], now_effective, out=deltas)
        within_fade = self._scratch_mask[:active_count]
        np.less(deltas, self._hidden_fade_seconds, out=within_fade)
        np.logical_and(owned, within_fade, out=owned)

        rows = np.flatnonzero(owned)
        if rows.shape[0] == 0:
            return

        entity_indices = self._threat_pool.active_entity_indices()[rows]
        sprite_rows = self._sprite_pool.dense_rows_of(entity_indices)
        fraction = self._fraction_buffer[: rows.shape[0]]
        np.clip(deltas[rows], 0.0, self._hidden_fade_seconds, out=fraction)
        if self._hidden_fade_seconds > 0.0:
            np.divide(fraction, self._hidden_fade_seconds, out=fraction)
        alpha = (fraction * 255.0).astype(np.uint8)
        self._sprite_pool.active_view()["tint_a"][sprite_rows] = alpha
