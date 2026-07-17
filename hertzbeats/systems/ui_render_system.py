"""Monta o HUD (placar/combo/veredito/vida) por aritmetica de digitos sobre sprites pre-criados."""
from __future__ import annotations

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World

from hertzbeats.components.texture_ids import JUDGMENT_WORD_TEXTURES, TEX_DIGIT_BASE
from hertzbeats.game_state import GameState


class UIRenderSystem(ISystem):
    """
    Ultimo sistema do frame: converte o placar global (`GameState`) em
    estado de SPRITE das entidades de HUD -- que sao entidades comuns
    (`transform` + `sprite`) criadas UMA unica vez na composicao e
    desenhadas pelo MESMO `IRenderer.draw_batch()` ultra-rapido do jogo
    base. Nenhum `font.render(...)` acontece aqui: os glifos 0-9 e as
    palavras PERFECT/GOOD/MISS foram pre-renderizados como texturas
    estaticas na tela de carregamento (ver `texture_bank`), e este
    sistema apenas escolhe `texture_id`/`tint_a` por aritmetica.

    LOGICA ZERO-GC dos digitos: se o combo e 142, o sistema extrai os
    digitos 1, 4 e 2 com `digito_i = (valor // 10**i) % 10`,
    VETORIZADO sobre buffers pre-alocados (`np.floor_divide`/`np.mod`
    com `out=`), e grava `TEX_DIGIT_BASE + digito` no `texture_id` de
    cada entidade-digito. Zeros a esquerda sao ocultados com
    `tint_a = 0` (o adapter pula sprites transparentes). As posicoes dos
    digitos sao fixas, escritas uma unica vez na composicao.

    O timer da palavra de veredito decrementa com `delta_time` de frame
    (feedback visual, nao evento ritmico).
    """

    def __init__(
        self,
        memory_manager: MemoryManager,
        game_state: GameState,
        score_digit_entity_indices: np.ndarray,
        combo_digit_entity_indices: np.ndarray,
        judgment_word_entity_index: int,
        health_pip_entity_indices: np.ndarray,
        show_health_pips: bool = True,
        flow_combo_threshold: int = None,
        score_label_entity_index: int = None,
        combo_label_entity_index: int = None,
    ) -> None:
        """Os arrays de indices de entidade do HUD (int64, ordem: digito
        menos significativo primeiro) sao pre-alocados pela composicao.
        Buffers de trabalho dimensionados aqui, nunca no update.
        """
        self._sprite_pool = memory_manager.get_pool("sprite")
        self._game_state = game_state
        self._score_digit_indices = score_digit_entity_indices
        self._combo_digit_indices = combo_digit_entity_indices
        self._judgment_word_entity_index = int(judgment_word_entity_index)
        self._health_pip_indices = health_pip_entity_indices
        self._show_health_pips = bool(show_health_pips)
        self._flow_combo_threshold = flow_combo_threshold
        self._score_label_entity_index = score_label_entity_index
        self._combo_label_entity_index = combo_label_entity_index

        score_digits = score_digit_entity_indices.shape[0]
        combo_digits = combo_digit_entity_indices.shape[0]
        self._score_powers = np.power(10, np.arange(score_digits, dtype=np.int64))
        self._combo_powers = np.power(10, np.arange(combo_digits, dtype=np.int64))
        self._score_digit_buffer = np.zeros(score_digits, dtype=np.int64)
        self._combo_digit_buffer = np.zeros(combo_digits, dtype=np.int64)
        self._score_alpha_buffer = np.zeros(score_digits, dtype=np.int64)
        self._combo_alpha_buffer = np.zeros(combo_digits, dtype=np.int64)

    def update(self, world: World, delta_time: float) -> None:
        """Reescreve texture_id/tint_a dos sprites de HUD a partir do
        `GameState` corrente."""
        sprite_view = self._sprite_pool.active_view()
        state = self._game_state

        # FLOW STATE: combo >= limiar -> interface some por completo (a
        # imersao "vidro quebrado" do enunciado). Um simples if sobre um
        # inteiro primitivo -- nenhum estado extra precisa ser guardado,
        # o combo ja e a fonte de verdade e zera sozinho no primeiro erro.
        if self._flow_combo_threshold is not None and state.combo_count >= self._flow_combo_threshold:
            self._hide_everything(sprite_view)
            if state.judgment_display_seconds_left > 0.0:
                state.judgment_display_seconds_left -= delta_time
            return

        # fora do Flow: labels sempre visiveis (restaura caso o Flow
        # anterior os tenha apagado -- `_hide_everything` nao e chamado
        # todo frame, entao ninguem mais os re-exibiria sozinho)
        for label_index in (self._score_label_entity_index, self._combo_label_entity_index):
            if label_index is not None:
                label_row = self._sprite_pool.dense_row_of(label_index)
                sprite_view["tint_a"][label_row] = 255

        self._write_number(
            sprite_view,
            state.score,
            self._score_digit_indices,
            self._score_powers,
            self._score_digit_buffer,
            self._score_alpha_buffer,
        )
        self._write_number(
            sprite_view,
            state.combo_count,
            self._combo_digit_indices,
            self._combo_powers,
            self._combo_digit_buffer,
            self._combo_alpha_buffer,
        )

        if state.judgment_display_seconds_left > 0.0:
            state.judgment_display_seconds_left -= delta_time
        word_row = self._sprite_pool.dense_row_of(self._judgment_word_entity_index)
        word_texture = JUDGMENT_WORD_TEXTURES[state.last_judgment]
        if state.judgment_display_seconds_left > 0.0 and word_texture != 0:
            sprite_view["texture_id"][word_row] = word_texture
            sprite_view["tint_a"][word_row] = 255
        else:
            sprite_view["tint_a"][word_row] = 0

        # modos sem pressao de vida (Arcade 4K) ocultam os pips
        pip_count = self._health_pip_indices.shape[0]
        for pip in range(pip_count):
            pip_row = self._sprite_pool.dense_row_of(int(self._health_pip_indices[pip]))
            if not self._show_health_pips:
                sprite_view["tint_a"][pip_row] = 0
            else:
                sprite_view["tint_a"][pip_row] = 255 if pip < state.health else 45

    def _hide_everything(self, sprite_view: np.ndarray) -> None:
        """Flow State: apaga score, combo, palavra de veredito e pips de
        vida -- so a arena e as notas ficam visiveis."""
        for entity_indices in (self._score_digit_indices, self._combo_digit_indices, self._health_pip_indices):
            rows = self._sprite_pool.dense_rows_of(entity_indices)
            sprite_view["tint_a"][rows] = 0
        word_row = self._sprite_pool.dense_row_of(self._judgment_word_entity_index)
        sprite_view["tint_a"][word_row] = 0
        for label_index in (self._score_label_entity_index, self._combo_label_entity_index):
            if label_index is not None:
                label_row = self._sprite_pool.dense_row_of(label_index)
                sprite_view["tint_a"][label_row] = 0

    def _write_number(
        self,
        sprite_view: np.ndarray,
        value: int,
        entity_indices: np.ndarray,
        powers: np.ndarray,
        digit_buffer: np.ndarray,
        alpha_buffer: np.ndarray,
    ) -> None:
        """Extrai os digitos de `value` (base 10, vetorizado, buffers
        `out=`) e grava textura/alfa nos sprites correspondentes; digitos
        alem do mais significativo ficam com alfa 0 (ocultos), exceto o
        das unidades, sempre visivel (mostra o proprio 0).
        """
        np.floor_divide(value, powers, out=digit_buffer)
        np.mod(digit_buffer, 10, out=digit_buffer)
        np.add(digit_buffer, TEX_DIGIT_BASE, out=digit_buffer)

        # visibilidade: potencia <= valor (ou digito das unidades)
        np.less_equal(powers, value, out=alpha_buffer)
        np.multiply(alpha_buffer, 255, out=alpha_buffer)
        alpha_buffer[0] = 255

        rows = self._sprite_pool.dense_rows_of(entity_indices)
        sprite_view["texture_id"][rows] = digit_buffer
        sprite_view["tint_a"][rows] = alpha_buffer
