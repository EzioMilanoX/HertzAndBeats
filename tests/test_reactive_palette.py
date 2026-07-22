"""Estetica Reativa: Paleta Dinamica (GameState.current_palette, tint dos aneis-guia e dos digitos neutros do HUD) e Fundo Imersivo."""
import pygame
import pytest

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.adapters.texture_bank import build_and_register_hud_textures
from hertzbeats.bootstrap.hertz_game_loop import HertzGameLoop
from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.components.texture_ids import TEX_DIGIT_BASE, TEX_DIGIT_PALETTE_BASE
from hertzbeats.stages import StageDef

from tests.conftest import make_config, write_beatmap
from tests.test_match_flow import _basic


# -- compose_world: palette_rgb/neutral_digit_texture_base -------------------


def test_compose_world_defaults_to_the_neutral_palette(tmp_path, null_input, null_clock):
    beatmap_path = write_beatmap(tmp_path / "b.beatmap.json", [_basic(3.0)])
    composed = compose_world(make_config(beatmap_path), null_input, null_clock)
    assert composed.game_state.current_palette == (255, 255, 255)

    ui_system = next(s for s in composed.world._systems if type(s).__name__ == "UIRenderSystem")
    assert ui_system._neutral_digit_texture_base == TEX_DIGIT_BASE


def test_compose_world_propagates_a_custom_palette(tmp_path, null_input, null_clock):
    beatmap_path = write_beatmap(tmp_path / "b.beatmap.json", [_basic(3.0)])
    composed = compose_world(
        make_config(beatmap_path), null_input, null_clock,
        palette_rgb=(200, 40, 40), neutral_digit_texture_base=TEX_DIGIT_PALETTE_BASE,
    )
    assert composed.game_state.current_palette == (200, 40, 40)

    ui_system = next(s for s in composed.world._systems if type(s).__name__ == "UIRenderSystem")
    assert ui_system._neutral_digit_texture_base == TEX_DIGIT_PALETTE_BASE


def test_score_digits_use_the_custom_palette_base_when_composed_with_one(tmp_path, null_input, null_clock):
    from ouroboros.core.memory.memory_manager import MemoryManager  # noqa: F401 (so' pra clareza do teste)

    beatmap_path = write_beatmap(tmp_path / "b.beatmap.json", [_basic(3.0)])
    composed = compose_world(
        make_config(beatmap_path), null_input, null_clock,
        palette_rgb=(10, 250, 10), neutral_digit_texture_base=TEX_DIGIT_PALETTE_BASE,
    )
    ui_system = next(s for s in composed.world._systems if type(s).__name__ == "UIRenderSystem")
    composed.game_state.score = 7
    composed.world.step(0.016)

    sprite_pool = composed.memory_manager.get_pool("sprite")
    row = sprite_pool.dense_row_of(int(ui_system._score_digit_indices[0]))
    texture_id = int(sprite_pool.active_view()["texture_id"][row])
    assert TEX_DIGIT_PALETTE_BASE <= texture_id < TEX_DIGIT_PALETTE_BASE + 10


# -- HBPygameRenderer: apply_palette_tint / clear_palette_tint / tinted rings -


@pytest.fixture
def renderer_with_digits():
    renderer = HBPygameRenderer()
    renderer.initialize(200, 200, "test")
    build_and_register_hud_textures(renderer)
    return renderer


def test_apply_palette_tint_registers_a_recolored_digit_atlas(renderer_with_digits):
    renderer = renderer_with_digits
    assert renderer._textures.get(TEX_DIGIT_PALETTE_BASE) is None

    renderer.apply_palette_tint((255, 0, 0))
    tinted = renderer._textures.get(TEX_DIGIT_PALETTE_BASE)
    assert tinted is not None
    # multiplicar um branco quase puro por vermelho puro deve zerar os
    # canais verde/azul, mas preservar o alfa do glifo (per-pixel)
    pixels = pygame.surfarray.array3d(tinted)
    assert pixels[:, :, 1].max() == 0
    assert pixels[:, :, 2].max() == 0


def test_apply_palette_tint_never_mutates_the_original_white_digit_surface(renderer_with_digits):
    renderer = renderer_with_digits
    original = renderer._textures[TEX_DIGIT_BASE]
    original_pixels_before = pygame.surfarray.array3d(original).copy()

    renderer.apply_palette_tint((255, 0, 0))
    original_pixels_after = pygame.surfarray.array3d(renderer._textures[TEX_DIGIT_BASE])
    assert (original_pixels_before == original_pixels_after).all()


def test_tinted_ring_color_blends_toward_the_active_palette(renderer_with_digits):
    renderer = renderer_with_digits
    base = (90, 70, 160)
    assert renderer._tinted_ring_color(base) == base  # sem tint ativo, intocada

    renderer.apply_palette_tint((0, 0, 0))
    tinted = renderer._tinted_ring_color(base)
    assert tinted != base
    assert all(0 <= c < base_c for c, base_c in zip(tinted, base))  # rumo ao preto, mais escuro


def test_clear_palette_tint_resets_the_ring_color_to_neutral(renderer_with_digits):
    renderer = renderer_with_digits
    renderer.apply_palette_tint((0, 0, 0))
    assert renderer._tinted_ring_color((90, 70, 160)) != (90, 70, 160)

    renderer.clear_palette_tint()
    assert renderer._tinted_ring_color((90, 70, 160)) == (90, 70, 160)


# -- HertzGameLoop._compose_stage: fio ate o renderer cacheado --------------


class _FakePaletteRenderer(NullRenderer):
    """`NullRenderer` + a interface de Estetica Reativa, com os dados
    JA "cacheados" na mao (sem precisar carregar uma imagem de verdade)
    -- so' pra verificar que `HertzGameLoop._compose_stage` LE/CHAMA a
    interface certa, sem precisar de pygame.image/Surfaces reais."""

    def __init__(self, cached_by_stage_id):
        super().__init__()
        self._cached_by_stage_id = cached_by_stage_id
        self.apply_palette_tint_calls = []
        self.clear_palette_tint_calls = 0
        self.set_background_image_calls = []

    def thumbnail_average_color(self, stage_id):
        entry = self._cached_by_stage_id.get(stage_id)
        return entry["average_color"] if entry else (255, 255, 255)

    def thumbnail_background(self, stage_id):
        entry = self._cached_by_stage_id.get(stage_id)
        return entry["background"] if entry else None

    def apply_palette_tint(self, rgb):
        self.apply_palette_tint_calls.append(rgb)

    def clear_palette_tint(self):
        self.clear_palette_tint_calls += 1

    def set_background_image(self, surface):
        self.set_background_image_calls.append(surface)


def _stage_loop_with_fake_renderer(tmp_path, null_input, cached_by_stage_id):
    beatmap_path = write_beatmap(tmp_path / "s.beatmap.json", [_basic(3.0)])
    stage = StageDef(
        stage_id="stage_with_palette", name="FASE", subtitle="", track_path="",
        beatmap_path=str(beatmap_path), synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
    )
    renderer = _FakePaletteRenderer(cached_by_stage_id)
    audio_engine = NullAudioEngine()
    loop = HertzGameLoop(
        base_config=make_config(beatmap_path), stages=(stage,), renderer=renderer,
        input_provider=null_input, audio_engine=audio_engine, audio_clock=audio_engine.get_clock(),
        player_progress_path=str(tmp_path / "player_progress.json"),
        player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
        user_settings_path=str(tmp_path / "user_settings.json"),
    )
    return loop, renderer


def test_compose_stage_applies_a_cached_non_neutral_palette(tmp_path, null_input):
    background = pygame.Surface((10, 10))
    cached = {"stage_with_palette": {"average_color": (200, 50, 50), "background": background}}
    loop, renderer = _stage_loop_with_fake_renderer(tmp_path, null_input, cached)

    assert loop.composed.game_state.current_palette == (200, 50, 50)
    assert renderer.apply_palette_tint_calls == [(200, 50, 50)]
    assert renderer.clear_palette_tint_calls == 0
    assert renderer.set_background_image_calls == [background]


def test_compose_stage_clears_the_palette_for_a_stage_without_a_cached_thumbnail(tmp_path, null_input):
    loop, renderer = _stage_loop_with_fake_renderer(tmp_path, null_input, cached_by_stage_id={})

    assert loop.composed.game_state.current_palette == (255, 255, 255)
    assert renderer.apply_palette_tint_calls == []
    assert renderer.clear_palette_tint_calls >= 1
    assert renderer.set_background_image_calls == [None]


def test_compose_stage_works_without_a_renderer_supporting_the_reactive_aesthetic(tmp_path, null_input):
    """`NullRenderer` puro (sem nenhum metodo de Estetica Reativa) --
    `_compose_stage` cai pro neutro sem quebrar (mesmo criterio de
    qualquer outra sincronizacao `hasattr`-guardada do jogo)."""
    beatmap_path = write_beatmap(tmp_path / "s.beatmap.json", [_basic(3.0)])
    stage = StageDef(
        stage_id="s", name="FASE", subtitle="", track_path="", beatmap_path=str(beatmap_path),
        synth={"bpm": 120.0, "bars": 1}, beatmap_params={}, overrides={},
    )
    audio_engine = NullAudioEngine()
    loop = HertzGameLoop(
        base_config=make_config(beatmap_path), stages=(stage,), renderer=NullRenderer(),
        input_provider=null_input, audio_engine=audio_engine, audio_clock=audio_engine.get_clock(),
        player_progress_path=str(tmp_path / "player_progress.json"),
        player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
        user_settings_path=str(tmp_path / "user_settings.json"),
    )
    assert loop.composed.game_state.current_palette == (255, 255, 255)


