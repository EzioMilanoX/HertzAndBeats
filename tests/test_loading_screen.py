"""Tela de carregamento: a janela nao pode parecer travada durante a IA.

Bug real e reportado: subir `MAPPER_VERSION` (de 4 para 5, pela correcao do
vies do extrator) invalidou TODOS os beatmaps cacheados de musica do
jogador, e o jogo reanalisou as 4 de uma vez no startup -- 159 s. Durante
esse tempo o processo nunca voltava ao loop principal, e um app que nao
atende a fila de mensagens por alguns segundos e' marcado pelo Windows como
"Nao Respondendo": janela cinza/branca.

O estrago nao e' cosmetico. O jogador ve travamento, mata o processo, a
analise nunca termina de cachear -- e na abertura seguinte tudo se repete,
para sempre.
"""
import pygame
import pytest

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer


@pytest.fixture
def renderer():
    renderer = HBPygameRenderer()
    renderer.initialize(320, 240, "test")
    yield renderer
    renderer.shutdown()


def test_loading_screen_services_the_os_message_queue(renderer, monkeypatch):
    """A correcao do bug. Sem `pump()`, a janela e marcada como travada
    pelo SO durante qualquer carregamento longo."""
    calls = []
    monkeypatch.setattr(pygame.event, "pump", lambda: calls.append(1))
    renderer.show_loading_message("Analisando musica 1")
    assert calls, "show_loading_message precisa chamar pygame.event.pump()"


def test_loading_screen_pumps_after_flipping_too(renderer, monkeypatch):
    """Bombear antes E depois do flip: o desenho em si leva tempo, e e' o
    intervalo TOTAL sem atender a fila que o SO mede."""
    calls = []
    monkeypatch.setattr(pygame.event, "pump", lambda: calls.append(1))
    renderer.show_loading_message("Analisando musica 1")
    assert len(calls) >= 2


def test_loading_screen_does_not_consume_pending_events(renderer):
    """`pump()` e nao `get()`: os eventos seguem na fila pro loop de
    gameplay. Com `get()` aqui, um QUIT do jogador durante o carregamento
    seria engolido em silencio."""
    pygame.event.clear()
    pygame.event.post(pygame.event.Event(pygame.QUIT))
    renderer.show_loading_message("Analisando musica 1")
    tipos = [event.type for event in pygame.event.get()]
    assert pygame.QUIT in tipos, "o QUIT do jogador foi engolido pela tela de carregamento"


def test_loading_screen_accepts_a_submessage(renderer):
    """A submensagem carrega a estimativa de tempo -- sem numero nem
    estimativa, uma pasta `musicas/` cheia e indistinguivel de travamento."""
    renderer.show_loading_message("Analisando musica 2: 'x'", "~30 s por musica. Nao feche.")


def test_loading_screen_paints_something(renderer):
    """Guarda basico: se a tela ficasse preta, o aviso nao existiria na
    pratica -- e o jogador continuaria vendo uma janela morta."""
    import numpy as np

    renderer.show_loading_message("Analisando musica 1")
    pixels = pygame.surfarray.array3d(pygame.display.get_surface())
    assert int(np.count_nonzero(pixels.sum(axis=2))) > 0
