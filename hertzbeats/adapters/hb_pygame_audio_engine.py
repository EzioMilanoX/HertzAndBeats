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

    def __init__(self) -> None:
        super().__init__()
        self._vocals_muffled = False

    @property
    def vocals_muffled(self) -> bool:
        """ESQUELETO -- Crossfading Vocal: intencao ATUAL registrada por
        `muffle_vocals`, nunca lida por nenhum sistema de gameplay
        ainda -- so' exposta pra inspecao/teste do proprio esqueleto."""
        return self._vocals_muffled

    def muffle_vocals(self, muffled: bool) -> None:
        """ESQUELETO -- Crossfading Vocal (`HertzConfig.karaoke_sync`):
        o plano futuro e' abafar SO a voz (nunca o instrumental) quando
        o jogador errar uma nota, cruzando entre 2 camadas de audio -- o
        mix completo tocando e um stem SO instrumental em paralelo,
        crossfadeados por volume. `pygame.mixer.music` (streaming de
        canal unico, sem EQ/filtro de frequencia) nao consegue isolar
        uma faixa dentro do MESMO arquivo -- a implementacao de verdade
        exige essa 2a camada de audio, que ainda nao existe (nenhuma
        fase tem um stem instrumental separado hoje). Por enquanto so
        registra a INTENCAO (`self._vocals_muffled`); nenhum audio real
        muda ainda -- mesma honestidade de escopo de `set_track_volume`
        acima (aproximacao ao inves de fingir um efeito que o backend
        nao suporta)."""
        self._vocals_muffled = bool(muffled)

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

    def set_track_volume(self, volume: float) -> None:
        """Volume 0.0..1.0 da faixa em reproducao -- usado pelo Flow
        State (Arcade 4K) como aproximacao HONESTA de "bass boost":
        `pygame.mixer` nao expoe nenhum filtro de EQ em tempo real, entao
        o jogo toca a faixa normalmente um pouco ABAIXO do volume maximo
        (`1.0 - flow_volume_boost`) e faz um SWELL ate 1.0 exatamente
        quando o Flow comeca -- um efeito real e audivel, sem fingir um
        grave que o backend nao pode produzir."""
        pygame.mixer.music.set_volume(max(0.0, min(1.0, volume)))
