"""PygameAudioEngine estendido com pausa/retomada da faixa (congela o IAudioClock junto)."""
from __future__ import annotations

import pygame

from ouroboros.adapters.pygame_backend.pygame_audio_engine import PygameAudioEngine


class HBPygameAudioEngine(PygameAudioEngine):
    """
    `PygameAudioEngine` da engine estendido com `pause_track`/
    `resume_track` para o fluxo de pausa do Hertz & Beats.

    Propriedade central: `pygame.mixer.music.pause()` congela tambem o
    `music.get_pos()` (verificado empiricamente -- a posicao conta audio
    efetivamente consumido). Como o `PygameAudioClock` deriva
    `now_seconds()` de `get_pos()`, pausar a musica congela o relogio, e
    TODO o gameplay ritmico (spawner/julgamento) congela em sincronia
    sem nenhum estado extra; `unpause()` retoma do exato ponto.
    """

    def preload_one_shot(self, sound_id: str) -> None:
        """Carrega um SFX para o cache ANTES do gameplay (o primeiro
        `play_one_shot` deixaria de tocar no tempo por causa do I/O)."""
        if sound_id not in self._sounds:
            self._sounds[sound_id] = pygame.mixer.Sound(sound_id)

    def pause_track(self) -> None:
        """Pausa a faixa em reproducao (e, com ela, o `IAudioClock`)."""
        pygame.mixer.music.pause()

    def resume_track(self) -> None:
        """Retoma a faixa pausada do ponto exato em que congelou."""
        pygame.mixer.music.unpause()
