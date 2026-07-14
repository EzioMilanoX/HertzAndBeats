"""Dirige o banner de instrucoes do tutorial em sincronia com a musica (cursor de tempo, zero-GC)."""
from __future__ import annotations

import numpy as np

from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock


class TutorialSystem(ISystem):
    """
    Exibe as instrucoes do tutorial DURANTE o gameplay, trocando a
    textura de um unico sprite-banner de HUD conforme a musica avanca.

    Os passos vem da definicao da fase (`tutorial_steps` em
    `stages.json`, data-driven): cada passo vale ate `until_seconds` na
    linha do tempo da faixa. O texto de cada passo foi pre-renderizado
    na composicao (`TEX_TUTORIAL_BASE + ...`); aqui so se escolhe QUAL
    id mostrar -- nenhum `font.render`, nenhuma string em runtime.

    Mesmo padrao de cursor monotonico do `RhythmSpawnerSystem`: um unico
    inteiro `_current_step` avanca contra o array pre-alocado de
    `until_seconds`, comparado ao `IAudioClock` compensado de latencia
    (a MESMA base de tempo do spawner/julgamento -- o banner de "dash"
    aparece exatamente junto da onda que ensina o dash). Pausar a musica
    congela o relogio e, com ele, o tutorial inteiro.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        memory_manager: MemoryManager,
        banner_entity_index: int,
        step_until_seconds: np.ndarray,
        step_texture_ids: np.ndarray,
    ) -> None:
        """`step_until_seconds` (float64, crescente) e `step_texture_ids`
        (int64, paralelo) sao materializados pela composicao a partir da
        definicao da fase; ficam imutaveis durante o gameplay."""
        self._audio_clock = audio_clock
        self._sprite_pool = memory_manager.get_pool("sprite")
        self._banner_entity_index = int(banner_entity_index)
        self._step_until_seconds = step_until_seconds
        self._step_texture_ids = step_texture_ids
        self._current_step = 0

    @property
    def current_step(self) -> int:
        """Indice do passo ativo (== total de passos quando o tutorial acabou)."""
        return self._current_step

    def update(self, world: World, delta_time: float) -> None:
        """Avanca o cursor de passo contra o relogio de audio e escreve
        textura/alfa do banner (escritas escalares em linha densa
        re-resolvida por frame)."""
        del delta_time

        now_effective = max(
            0.0,
            self._audio_clock.now_seconds() - self._audio_clock.get_output_latency_seconds(),
        )
        step_count = self._step_until_seconds.shape[0]
        while self._current_step < step_count and now_effective >= self._step_until_seconds[self._current_step]:
            self._current_step += 1

        banner_row = self._sprite_pool.dense_row_of(self._banner_entity_index)
        sprite_view = self._sprite_pool.active_view()
        if self._current_step < step_count:
            sprite_view["texture_id"][banner_row] = self._step_texture_ids[self._current_step]
            sprite_view["tint_a"][banner_row] = 255
        else:
            sprite_view["tint_a"][banner_row] = 0
