"""Regressao VISUAL do renderer (pygame headless): textos blitam como glifos, nunca blocos solidos.

Contexto: `Surface.set_alpha(None)` DESLIGA o alpha por pixel no pygame;
uma textura de fonte blitada assim vira um retangulo cheio da cor do
texto (bug visto em producao: 'MISS' como bloco vermelho, 'SCORE' como
barra lilas). Estes testes desenham pelo caminho REAL do `draw_batch` e
medem a fracao de pixels pintados dentro do bounding box da textura --
um glifo tem buracos; um bloco solido nao.
"""
import numpy as np
import pygame
import pytest

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.adapters.texture_bank import build_and_register_hud_textures
from hertzbeats.components.texture_ids import TEX_DIGIT_BASE, TEX_WORD_MISS


@pytest.fixture
def renderer():
    renderer = HBPygameRenderer()
    renderer.initialize(320, 240, "test")
    build_and_register_hud_textures(renderer)
    yield renderer
    renderer.shutdown()


def _draw_texture(renderer, texture_id: int, alpha: int) -> float:
    """Desenha `texture_id` centrado via draw_batch e retorna a fracao de
    pixels NAO-fundo dentro do bounding box da textura."""
    positions = np.array([[160.0, 120.0]], dtype=np.float32)
    rotations = np.zeros(1, dtype=np.float32)
    scales = np.ones((1, 2), dtype=np.float32)
    texture_ids = np.array([texture_id], dtype=np.uint32)
    tints = np.array([[255, 255, 255, alpha]], dtype=np.uint8)
    layers = np.zeros(1, dtype=np.int16)

    renderer.begin_frame()
    renderer.draw_batch(positions, rotations, scales, texture_ids, tints, layers, 1)

    texture = renderer._textures[texture_id]
    width, height = texture.get_width(), texture.get_height()
    pixels = pygame.surfarray.array3d(renderer._surface)
    box = pixels[160 - width // 2 : 160 + width // 2, 120 - height // 2 : 120 + height // 2]
    background = np.array([8, 6, 20])
    painted = np.any(box != background, axis=2)
    return float(painted.mean())


def test_word_texture_has_glyph_holes(renderer):
    painted_ratio = _draw_texture(renderer, TEX_WORD_MISS, alpha=255)
    assert 0.05 < painted_ratio < 0.85, (
        f"'MISS' pintou {painted_ratio:.0%} do bounding box -- ~100% significa "
        "bloco solido (alpha por pixel perdido), ~0% significa nada desenhado"
    )


def test_word_texture_survives_alpha_roundtrip(renderer):
    """O caminho alpha<255 (set_alpha numerico) nao pode degradar o blit
    opaco seguinte -- era exatamente o roundtrip que quebrava com
    set_alpha(None)."""
    _draw_texture(renderer, TEX_WORD_MISS, alpha=120)
    painted_ratio = _draw_texture(renderer, TEX_WORD_MISS, alpha=255)
    assert 0.05 < painted_ratio < 0.85


def test_digit_texture_has_glyph_holes(renderer):
    painted_ratio = _draw_texture(renderer, TEX_DIGIT_BASE + 0, alpha=255)
    assert 0.05 < painted_ratio < 0.9  # o '0' tem um buraco no meio


def test_hidden_sprite_paints_nothing(renderer):
    painted_ratio = _draw_texture(renderer, TEX_WORD_MISS, alpha=0)
    assert painted_ratio == 0.0


def test_mode_hint_and_display_name_texts_fit_within_the_default_window_width():
    """Achado real ao adicionar os hints do 3o pacote hardcore do
    Defensor (Escudos Rotativos/Gemeos/Eclipses/Overload) ao seletor de
    minigame: um texto comprido demais estoura as bordas da janela,
    porque `HBPygameRenderer._blit_centered` so centraliza uma Surface
    JA PRONTA -- nunca quebra linha nem escala pra caber. Mede a largura
    RENDERIZADA (mesma fonte/tamanho usados de verdade em
    `build_and_register_overlay_surfaces`) de todo hint/nome de
    `texture_bank.py` contra a largura padrao da janela real."""
    from hertzbeats.adapters.texture_bank import _MODE_CONTROL_HINTS, _MODE_DISPLAY_NAMES
    from hertzbeats.config import HertzConfig

    config = HertzConfig.from_json("data/config/hertz_beats.config.json")
    if not pygame.font.get_init():
        pygame.font.init()
    hint_font = pygame.font.Font(None, 28)
    name_font = pygame.font.Font(None, 44)

    for mode, hint_text in _MODE_CONTROL_HINTS.items():
        width, _ = hint_font.size(hint_text)
        assert width < config.window_width, (
            f"hint de {mode!r} estoura a janela: {width}px >= {config.window_width}px"
        )

    for mode, display_name in _MODE_DISPLAY_NAMES.items():
        width, _ = name_font.size(f"<  MODO: {display_name}  >")
        assert width < config.window_width, (
            f"nome de {mode!r} estoura a janela: {width}px >= {config.window_width}px"
        )


def test_curated_stage_labels_fit_within_the_default_window_width():
    """Mesmo achado do teste anterior, mas para os rotulos de fase
    (`stage.name` + `stage.subtitle`) do `stages.json` REAL -- achado ao
    redesenhar a campanha do Defensor (3 rotulos estouravam a janela: 2
    novos de subtitulos compridos demais e 1 pre-existente, "8 - Arcade:
    Notas Longas"). O rotulo SELECIONADO (com os marcadores "> ... <")
    e sempre mais largo que o normal, entao e o que precisa caber."""
    from hertzbeats.config import HertzConfig
    from hertzbeats.stages import load_stages

    config = HertzConfig.from_json("data/config/hertz_beats.config.json")
    stages = load_stages(config.stages_path)
    if not pygame.font.get_init():
        pygame.font.init()
    stage_font = pygame.font.Font(None, 40)

    for stage in stages:
        label = f"{stage.name}   {stage.subtitle}" if stage.subtitle else stage.name
        width, _ = stage_font.size(f"> {label} <")
        assert width < config.window_width, (
            f"rotulo de {stage.stage_id!r} estoura a janela: {width}px >= {config.window_width}px"
        )
