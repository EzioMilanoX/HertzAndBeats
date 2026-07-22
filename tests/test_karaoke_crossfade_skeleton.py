"""Preparacao para Crossfading Vocal: HertzConfig.karaoke_sync, esqueleto de legendas do UIRenderSystem e HBPygameAudioEngine.muffle_vocals."""
import numpy as np

from hertzbeats.adapters.hb_pygame_audio_engine import HBPygameAudioEngine
from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.config import HertzConfig
from hertzbeats.systems.ui_render_system import UIRenderSystem

from tests.conftest import make_config, write_beatmap


# -- HertzConfig.karaoke_sync (esqueleto, so' um campo) ----------------------


def test_karaoke_sync_field_defaults_to_false():
    import dataclasses

    field = next(f for f in dataclasses.fields(HertzConfig) if f.name == "karaoke_sync")
    assert field.default is False


def test_karaoke_sync_roundtrips_through_from_json(tmp_path):
    import json

    raw = json.loads(open("data/config/hertz_beats.config.json", "r", encoding="utf-8").read())
    raw["karaoke_sync"] = True
    config_path = tmp_path / "karaoke_on.config.json"
    config_path.write_text(json.dumps(raw), encoding="utf-8")

    config = HertzConfig.from_json(str(config_path))
    assert config.karaoke_sync is True


def test_the_real_shipped_config_defaults_karaoke_sync_off():
    """Nenhuma fase real tem legendas ainda -- o jogo de verdade nunca
    liga o esqueleto sozinho."""
    config = HertzConfig.from_json("data/config/hertz_beats.config.json")
    assert config.karaoke_sync is False


# -- UIRenderSystem: esqueleto de legendas cronologicas ----------------------


def _find_ui_system(composed) -> UIRenderSystem:
    for system in composed.world._systems:
        if isinstance(system, UIRenderSystem):
            return system
    raise AssertionError("UIRenderSystem nao registrado")


def test_karaoke_subtitles_is_a_no_op_when_composed_normally(tmp_path, null_input, null_clock):
    """Nenhuma fase popula os 4 parametros `karaoke_*` -- o UIRenderSystem
    REAL da composicao roda o metodo todo frame sem fazer nada (e sem
    quebrar)."""
    beatmap_path = write_beatmap(tmp_path / "k.beatmap.json", [
        {"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.5},
    ])
    composed = compose_world(make_config(beatmap_path), null_input, null_clock)
    ui_system = _find_ui_system(composed)
    assert ui_system._karaoke_audio_clock is None

    composed.world.step(0.016)  # nao explode
    assert ui_system._karaoke_line_index == 0


def _shadow_karaoke_system(composed, null_clock, until_seconds, texture_ids) -> UIRenderSystem:
    """Uma SEGUNDA instancia de `UIRenderSystem`, nunca registrada no
    `World` (nunca chamada por `world.step`) -- reusa o MESMO
    `memory_manager`/`GameState` da composicao real e o entity index da
    palavra de veredito como um banner de legenda "de mentirinha", so'
    para exercitar `_advance_karaoke_subtitles` isoladamente sem
    precisar wireup real em `compose_world` (o esqueleto ainda nao
    populado por nenhuma fase de verdade)."""
    real = _find_ui_system(composed)
    return UIRenderSystem(
        memory_manager=composed.memory_manager,
        game_state=composed.game_state,
        score_digit_entity_indices=real._score_digit_indices,
        combo_digit_entity_indices=real._combo_digit_indices,
        judgment_word_entity_index=real._judgment_word_entity_index,
        health_pip_entity_indices=real._health_pip_indices,
        karaoke_audio_clock=null_clock,
        karaoke_line_until_seconds=np.array(until_seconds, dtype=np.float64),
        karaoke_line_texture_ids=np.array(texture_ids, dtype=np.int64),
        karaoke_banner_entity_index=real._judgment_word_entity_index,
    )


def _banner_state(composed, entity_index):
    sprite_pool = composed.memory_manager.get_pool("sprite")
    row = sprite_pool.dense_row_of(entity_index)
    view = sprite_pool.active_view()
    return int(view["texture_id"][row]), int(view["tint_a"][row])


def test_karaoke_cursor_advances_the_line_as_the_clock_passes_each_until_seconds(tmp_path, null_input, null_clock):
    beatmap_path = write_beatmap(tmp_path / "k2.beatmap.json", [
        {"timestamp_seconds": 20.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.5},
    ])
    composed = compose_world(make_config(beatmap_path), null_input, null_clock)
    shadow = _shadow_karaoke_system(
        composed, null_clock, until_seconds=[5.0, 10.0], texture_ids=[701, 702],
    )
    banner = shadow._karaoke_banner_entity_index

    null_clock.set_now_seconds(1.0)
    shadow._advance_karaoke_subtitles()
    assert _banner_state(composed, banner) == (701, 255)
    assert shadow._karaoke_line_index == 0

    null_clock.set_now_seconds(7.0)
    shadow._advance_karaoke_subtitles()
    assert _banner_state(composed, banner) == (702, 255)
    assert shadow._karaoke_line_index == 1

    null_clock.set_now_seconds(11.0)
    shadow._advance_karaoke_subtitles()
    assert _banner_state(composed, banner)[1] == 0  # legendas acabaram: banner some
    assert shadow._karaoke_line_index == 2


def test_karaoke_cursor_never_goes_backward_even_if_the_clock_does(tmp_path, null_input, null_clock):
    """Mesmo cursor MONOTONICO do `TutorialSystem` -- nunca reavalia do
    zero, so' anda pra frente contra o relogio."""
    beatmap_path = write_beatmap(tmp_path / "k3.beatmap.json", [
        {"timestamp_seconds": 20.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.5},
    ])
    composed = compose_world(make_config(beatmap_path), null_input, null_clock)
    shadow = _shadow_karaoke_system(
        composed, null_clock, until_seconds=[5.0, 10.0], texture_ids=[701, 702],
    )

    null_clock.set_now_seconds(7.0)
    shadow._advance_karaoke_subtitles()
    assert shadow._karaoke_line_index == 1

    null_clock.set_now_seconds(2.0)  # relogio "voltou" (nao deveria acontecer de verdade)
    shadow._advance_karaoke_subtitles()
    assert shadow._karaoke_line_index == 1  # cursor nao regride


# -- HBPygameAudioEngine.muffle_vocals (esqueleto) ---------------------------


def test_muffle_vocals_defaults_to_unmuffled():
    engine = HBPygameAudioEngine()
    assert engine.vocals_muffled is False


def test_muffle_vocals_records_the_intent_without_touching_playback():
    engine = HBPygameAudioEngine()
    engine.muffle_vocals(True)
    assert engine.vocals_muffled is True
    engine.muffle_vocals(False)
    assert engine.vocals_muffled is False
