"""Combo Pitch Shift: a variante de SFX tocada sobe por indice a cada 10 de combo, nunca pitch-shift em tempo real."""
import dataclasses

from hertzbeats.audio.sfx_synth import SFX_CANNON, SFX_CANNON_VARIANTS, SFX_NOTE_HIT_VARIANTS
from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.systems.judgment_system import JudgmentSystem
from hertzbeats.systems.lane_judgment_system import LaneJudgmentSystem

from tests.conftest import make_config, write_beatmap


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": timestamp, "threat_type": "rhythm_threat_basic", "lane": lane, "strength": 0.5}


def test_variants_are_five_and_the_first_cannon_variant_is_the_original_sound():
    assert len(SFX_CANNON_VARIANTS) == 5
    assert SFX_CANNON_VARIANTS[0] == SFX_CANNON
    assert len(set(SFX_CANNON_VARIANTS)) == 5  # 5 arquivos distintos
    assert len(SFX_NOTE_HIT_VARIANTS) == 5
    assert len(set(SFX_NOTE_HIT_VARIANTS)) == 5


def test_shot_sound_for_combo_climbs_one_variant_per_10_combo_capped_at_the_last():
    system = JudgmentSystem.__new__(JudgmentSystem)  # so testa o metodo puro, sem compor o mundo
    system._shot_sound_ids = SFX_CANNON_VARIANTS
    assert system._shot_sound_for_combo(0) == SFX_CANNON_VARIANTS[0]
    assert system._shot_sound_for_combo(9) == SFX_CANNON_VARIANTS[0]
    assert system._shot_sound_for_combo(10) == SFX_CANNON_VARIANTS[1]
    assert system._shot_sound_for_combo(39) == SFX_CANNON_VARIANTS[3]
    assert system._shot_sound_for_combo(40) == SFX_CANNON_VARIANTS[4]
    assert system._shot_sound_for_combo(999) == SFX_CANNON_VARIANTS[4]  # capado na ultima


def test_shot_sound_for_combo_is_a_graceful_no_op_without_variants():
    system = JudgmentSystem.__new__(JudgmentSystem)
    system._shot_sound_ids = ()
    assert system._shot_sound_for_combo(50) is None


def test_note_hit_sound_for_combo_uses_the_same_arithmetic():
    system = LaneJudgmentSystem.__new__(LaneJudgmentSystem)
    system._note_hit_sound_ids = SFX_NOTE_HIT_VARIANTS
    assert system._note_hit_sound_for_combo(0) == SFX_NOTE_HIT_VARIANTS[0]
    assert system._note_hit_sound_for_combo(20) == SFX_NOTE_HIT_VARIANTS[2]


def test_perfect_hit_plays_the_cannon_variant_matching_the_new_combo(tmp_path, null_input, null_clock):
    beatmap_path = write_beatmap(tmp_path / "pitch.beatmap.json", [_basic(3.0, lane=0)])
    config = make_config(beatmap_path)
    audio_engine = NullAudioEngine()
    composed = compose_world(config, null_input, null_clock, audio_engine=audio_engine)
    composed.game_state.combo_count = 19  # o proximo acerto sobe pra 20 -> variante indice 2

    null_input.set_axis("aim_x", 1.0)
    null_input.set_axis("aim_y", 0.0)
    dt = 3.0 - null_clock.now_seconds()
    null_input.set_action_held("fire", True)
    null_clock.advance(dt)
    null_input.poll()
    composed.world.step(dt)

    played_ids = [sound_id for sound_id, _volume in audio_engine._one_shots_played]
    assert SFX_CANNON_VARIANTS[2] in played_ids
    assert SFX_CANNON_VARIANTS[0] not in played_ids
