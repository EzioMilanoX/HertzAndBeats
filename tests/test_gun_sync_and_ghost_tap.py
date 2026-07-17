"""Gun Sync (canhao no acerto, clique no misfire) e Ghost Tapping (tap livre sem punicao) no Arcade."""
import dataclasses

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine

from hertzbeats.audio.sfx_synth import SFX_CANNON, SFX_CLICK, SFX_TAP
from hertzbeats.bootstrap.rhythm_composition_root import compose_world

from tests.conftest import make_config, write_beatmap


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _compose_defender(tmp_path, null_input, null_clock, threats):
    beatmap_path = write_beatmap(tmp_path / "d.beatmap.json", threats)
    audio_engine = NullAudioEngine()
    composed = compose_world(make_config(beatmap_path), null_input, null_clock, audio_engine=audio_engine)
    return composed, audio_engine


def test_hit_on_time_plays_the_cannon(tmp_path, null_input, null_clock):
    composed, audio_engine = _compose_defender(tmp_path, null_input, null_clock, [_basic(3.0, lane=0)])

    null_clock.set_now_seconds(2.98)
    null_input.set_axis("aim_x", 1.0)
    null_input.set_axis("aim_y", 0.0)
    null_input.set_action_held("fire", True)
    null_input.poll()
    composed.world.step(0.016)

    assert (SFX_CANNON, 0.9) in audio_engine._one_shots_played
    assert not any(sound_id == SFX_CLICK for sound_id, _ in audio_engine._one_shots_played)


def test_misfire_plays_click_and_jams_the_gun(tmp_path, null_input, null_clock):
    composed, audio_engine = _compose_defender(tmp_path, null_input, null_clock, [_basic(3.0, lane=0)])

    null_clock.set_now_seconds(1.0)  # fora de qualquer janela
    null_input.set_action_held("fire", True)
    null_input.poll()
    composed.world.step(0.016)

    assert any(sound_id == SFX_CLICK for sound_id, _ in audio_engine._one_shots_played)
    player_pool = composed.memory_manager.get_pool("player_state")
    row = player_pool.dense_row_of(composed.player_entity_index)
    assert float(player_pool.active_view()["gun_jam_sec"][row]) > 0.0


def test_jammed_gun_ignores_trigger_until_it_clears(tmp_path, null_input, null_clock):
    composed, audio_engine = _compose_defender(
        tmp_path, null_input, null_clock, [_basic(3.0, lane=0), _basic(3.5, lane=0)]
    )
    state = composed.game_state

    null_clock.set_now_seconds(1.0)  # misfire: arma emperra
    null_input.set_action_held("fire", True)
    null_input.poll()
    composed.world.step(0.016)
    assert state.misfire_count == 1

    audio_engine._one_shots_played.clear()
    null_input.set_action_held("fire", False)
    null_input.poll()
    composed.world.step(0.016)  # solta o gatilho (fire=False): sem novo misfire
    null_input.set_action_held("fire", True)
    null_input.poll()
    composed.world.step(0.016)  # tenta atirar de novo AINDA emperrado

    assert state.misfire_count == 1  # nao conta um segundo misfire: o gatilho nao respondeu
    assert any(sound_id == SFX_CLICK for sound_id, _ in audio_engine._one_shots_played)

    # espera o jam passar (0.5s default) e confirma que a arma volta a funcionar
    null_input.set_action_held("fire", False)
    null_input.poll()
    for _ in range(40):
        composed.world.step(0.016)
    player_pool = composed.memory_manager.get_pool("player_state")
    row = player_pool.dense_row_of(composed.player_entity_index)
    assert float(player_pool.active_view()["gun_jam_sec"][row]) == 0.0

    null_clock.set_now_seconds(3.48)
    null_input.set_axis("aim_x", 1.0)
    null_input.set_axis("aim_y", 0.0)
    null_input.set_action_held("fire", True)
    null_input.poll()
    composed.world.step(0.016)
    assert state.perfect_count == 1  # arma respondendo normalmente


def _compose_lanes(tmp_path, null_input, null_clock, threats):
    beatmap_path = write_beatmap(tmp_path / "l.beatmap.json", threats)
    config = dataclasses.replace(make_config(beatmap_path), game_mode="lanes")
    audio_engine = NullAudioEngine()
    composed = compose_world(config, null_input, null_clock, audio_engine=audio_engine)
    return composed, audio_engine


def test_ghost_tap_plays_soft_tick_without_penalty(tmp_path, null_input, null_clock):
    composed, audio_engine = _compose_lanes(tmp_path, null_input, null_clock, [_basic(3.0, lane=0)])
    state = composed.game_state
    state.combo_count = 6

    null_clock.set_now_seconds(1.0)  # nenhuma nota na janela desta coluna
    null_input.set_action_held("lane_0", True)
    null_input.poll()
    composed.world.step(0.016)

    assert state.combo_count == 6  # batucar livre nao pune
    assert (SFX_TAP, 0.3) in audio_engine._one_shots_played
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 1  # a nota real segue viva
