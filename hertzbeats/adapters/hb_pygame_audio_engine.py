"""PygameAudioEngine estendido com a camada vocal, volume da faixa e caminhos graváveis.

A pausa/retomada da faixa (que congela o IAudioClock junto) agora vem da engine:
`IAudioEngine.pause_track(track_id)` / `resume_track(track_id)`."""
from __future__ import annotations

import pygame

from ouroboros.adapters.pygame_backend.pygame_audio_engine import PygameAudioEngine

from utils.path_resolver import get_writable_data_path


class HBPygameAudioEngine(PygameAudioEngine):
    """
    `PygameAudioEngine` da engine estendido para o Hertz & Beats (a pausa
    `pause_track`/`resume_track` e' a da engine).

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
        self._vocal_channel = None
        self._vocal_sound = None

    VOCAL_MUFFLED_VOLUME = 0.15
    """Volume do canal vocal quando abafado. Nao ZERO de proposito: a voz
    sumir por completo soa como bug de audio; abafada soa como punicao."""

    @property
    def vocals_muffled(self) -> bool:
        """Crossfading Vocal: estado ATUAL do abafamento da voz."""
        return self._vocals_muffled

    @property
    def has_vocal_layer(self) -> bool:
        """True quando ha um stem vocal carregado -- entao `muffle_vocals`
        muda audio de verdade. False numa fase sem stems (musica do
        jogador, faixa sem melodia): a chamada segue valida e registra a
        intencao, so nao ha o que abafar."""
        return self._vocal_sound is not None

    def load_vocal_layer(self, vocal_track_path: str) -> None:
        """Carrega o stem VOCAL num canal `Sound` proprio, em paralelo ao
        instrumental que toca em `pygame.mixer.music`.

        A divisao importa e e' deliberada: o INSTRUMENTAL fica em
        `music`, que continua sendo a unica fonte do `IAudioClock` -- logo
        nada no gameplay ritmico muda, nem a pausa (que congela o relogio
        via `music.pause()`), nem a calibracao de latencia. O vocal fica
        num canal secundario, cujo volume o jogo abaixa ao errar.

        `pygame.mixer.music` e' streaming de canal UNICO, e era essa a
        razao pela qual o Crossfading Vocal foi documentado como
        impossivel. A saida nao foi filtrar audio (o backend nao tem EQ):
        foi RENDERIZAR duas faixas, o que so e' possivel porque as faixas
        curadas sao sintetizadas -- ver `demo_track_synth.STEMS`.
        """
        resolved = get_writable_data_path(vocal_track_path)
        if pygame.mixer.get_init() is None:
            pygame.mixer.init()
        self._vocal_sound = pygame.mixer.Sound(resolved)
        self._vocal_channel = None

    def start_vocal_layer(self) -> None:
        """Comeca o stem vocal. Chamar IMEDIATAMENTE depois de
        `play_track` do instrumental: os dois streams sao independentes,
        entao qualquer trabalho entre as duas chamadas vira desalinhamento
        audivel -- e num jogo ritmico alguns milissegundos de deriva entre
        bateria e melodia sao percebidos como faixa desafinada no tempo.
        """
        if self._vocal_sound is None:
            return
        self._vocal_channel = self._vocal_sound.play()
        self._apply_vocal_volume()

    def stop_vocal_layer(self) -> None:
        if self._vocal_channel is not None:
            self._vocal_channel.stop()
            self._vocal_channel = None

    def pause_vocal_layer(self, paused: bool) -> None:
        """Pausa/retoma o vocal junto com o instrumental -- sem isto, a
        melodia continuaria tocando com o jogo congelado e, pior,
        retomaria fora de fase."""
        if self._vocal_channel is None:
            return
        if paused:
            self._vocal_channel.pause()
        else:
            self._vocal_channel.unpause()

    def _apply_vocal_volume(self) -> None:
        if self._vocal_channel is None:
            return
        self._vocal_channel.set_volume(
            self.VOCAL_MUFFLED_VOLUME if self._vocals_muffled else 1.0
        )

    def muffle_vocals(self, muffled: bool) -> None:
        """Crossfading Vocal: abafa SO a voz, nunca o instrumental.

        Deixou de ser esqueleto. O que mudou nao foi o backend -- segue
        sem EQ/filtro -- e sim de onde vem o audio: com o stem vocal
        carregado por `load_vocal_layer` num canal proprio, "abafar a voz"
        e' baixar o volume DAQUELE canal, uma operacao que
        `pygame.mixer.Channel` sempre soube fazer.

        Sem stem carregado, segue registrando so a intencao (musica do
        jogador nao tem stems) -- a chamada nunca falha por isso.
        """
        self._vocals_muffled = bool(muffled)
        self._apply_vocal_volume()

    def preload_one_shot(self, sound_id: str) -> None:
        """Carrega um SFX para o cache ANTES do gameplay (o primeiro
        `play_one_shot` deixaria de tocar no tempo por causa do I/O).

        `sound_id` (ex.: `"data/sfx/cannon.wav"`) e' resolvido via
        `get_writable_data_path` -- NAO `get_resource_path` -- porque
        `sfx_synth.ensure_sfx` pode GRAVAR o arquivo ali mesmo (sintese
        na 1a execucao); `sys._MEIPASS` (a raiz de `get_resource_path`
        quando congelado) e' apagado ao sair do jogo, o que faria
        ressintetizar TODO SFX a cada execucao. A chave do cache
        `self._sounds` continua sendo o `sound_id` ORIGINAL (relativo)
        -- so' o caminho passado a `pygame.mixer.Sound` e' resolvido --
        entao `play_one_shot(sound_id)` (chamado em todo o resto do
        jogo com a MESMA string original) continua encontrando o cache
        sem nenhuma mudanca no resto do codebase."""
        if sound_id not in self._sounds:
            self._sounds[sound_id] = pygame.mixer.Sound(get_writable_data_path(sound_id))

    def load_track(self, track_id: str, file_path: str) -> None:
        """Override fino sobre `PygameAudioEngine.load_track` (engine,
        nao editada) -- resolve `file_path` via `get_writable_data_path`
        PELO MESMO MOTIVO de `preload_one_shot` (faixas tambem podem
        ser sintetizadas em runtime por `demo_track_synth.ensure_track`)
        antes de delegar pro comportamento real da engine. Cobre TODO
        `self._audio_engine.load_track(...)` do jogo de uma vez so' --
        nenhum call site em `hertz_game_loop.py` precisa saber disso."""
        super().load_track(track_id, get_writable_data_path(file_path))

    def set_track_volume(self, volume: float) -> None:
        """Volume 0.0..1.0 da faixa em reproducao -- usado pelo Flow
        State (Arcade 4K) como aproximacao HONESTA de "bass boost":
        `pygame.mixer` nao expoe nenhum filtro de EQ em tempo real, entao
        o jogo toca a faixa normalmente um pouco ABAIXO do volume maximo
        (`1.0 - flow_volume_boost`) e faz um SWELL ate 1.0 exatamente
        quando o Flow comeca -- um efeito real e audivel, sem fingir um
        grave que o backend nao pode produzir."""
        pygame.mixer.music.set_volume(max(0.0, min(1.0, volume)))

    def play_preview(self, track_id: str, start_offset_seconds: float, fade_ms: int = 1000) -> None:
        """Audio Preview (Carrossel Horizontal): toca um TRECHO da
        musica `track_id` (ja carregada via `load_track`) a partir de
        `start_offset_seconds`, com fade-in de `fade_ms` -- MESMO
        `pygame.mixer.music.play(start=...)` que `play_track` ja usa
        (arg `fade_ms` nativo do pygame, so' nunca precisou dele ate
        agora). Carregar a musica de novo (`.load()`) troca
        implicitamente a faixa anterior tocando -- pygame so admite UM
        canal de musica por vez, entao nao precisa de nenhum `stop_track`
        explicito ao trocar de preview."""
        file_path = self._loaded_tracks[track_id]
        pygame.mixer.music.load(file_path)
        pygame.mixer.music.play(loops=0, start=max(0.0, start_offset_seconds), fade_ms=int(fade_ms))
        self._current_track_id = track_id
