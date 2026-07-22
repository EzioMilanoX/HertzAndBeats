"""Juice Visual -- Sparks: pool fixo Zero-GC, ativado pelo JudgmentSystem em acertos PERFEITOS."""
import math

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.systems.spark_system import SparkSystem

from tests.conftest import make_config, write_beatmap


def _heavy(timestamp: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": timestamp, "threat_type": "rhythm_threat_heavy", "lane": lane, "strength": 0.9}


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": timestamp, "threat_type": "rhythm_threat_basic", "lane": lane, "strength": 0.5}


# -- unidade: o SparkSystem em isolamento ---------------------------------


def test_emit_burst_activates_the_requested_number_of_slots():
    system = SparkSystem(pool_size=16, lifetime_seconds=0.2, max_length=20.0)
    system.emit_burst(100.0, 200.0, count=5)
    _, _, _, _, alphas, count = system.render_arrays()
    assert count == 16
    assert int((alphas > 0.0).sum()) == 5


def test_emitted_sparks_start_at_the_given_origin_with_zero_length():
    system = SparkSystem(pool_size=8, lifetime_seconds=0.2, max_length=20.0)
    system.emit_burst(50.0, 75.0, count=3)
    xs, ys, angles, lengths, alphas, count = system.render_arrays()
    active = alphas > 0.0
    assert (xs[active] == 50.0).all()
    assert (ys[active] == 75.0).all()
    assert (lengths[active] < 1e-5).all()  # recem-nascida: comprimento ~0 (ainda nao "esticou")
    assert (alphas[active] > 250.0).all()  # recem-nascida: alfa no maximo


def test_sparks_stretch_and_fade_over_their_lifetime():
    system = SparkSystem(pool_size=4, lifetime_seconds=0.2, max_length=20.0)
    system.emit_burst(0.0, 0.0, count=1)
    system.update(world=None, delta_time=0.1)  # metade da vida
    _, _, _, lengths, alphas, _ = system.render_arrays()
    active_row = (alphas > 0.0).argmax()
    assert abs(float(lengths[active_row]) - 10.0) < 0.5  # metade do comprimento maximo
    assert abs(float(alphas[active_row]) - 127.5) < 2.0  # metade do alfa


def test_sparks_fully_expire_and_free_their_slot_for_round_robin_reuse():
    system = SparkSystem(pool_size=2, lifetime_seconds=0.1, max_length=10.0)
    system.emit_burst(1.0, 1.0, count=1)
    system.update(world=None, delta_time=0.5)  # bem alem da vida util
    _, _, _, _, alphas, _ = system.render_arrays()
    assert (alphas <= 0.0).all()

    # round-robin: reaproveita o slot livremente, sem checar se "ainda vivia"
    system.emit_burst(2.0, 2.0, count=2)
    xs, ys, _, _, alphas, _ = system.render_arrays()
    active = alphas > 0.0
    assert int(active.sum()) == 2
    assert (xs[active] == 2.0).all()


def test_emit_burst_wraps_around_the_pool_in_round_robin_order():
    system = SparkSystem(pool_size=4, lifetime_seconds=1.0, max_length=10.0)
    system.emit_burst(1.0, 1.0, count=4)  # enche o pool inteiro
    system.emit_burst(2.0, 2.0, count=2)  # deveria sobrescrever os 2 PRIMEIROS slots
    xs, _, _, _, alphas, _ = system.render_arrays()
    assert list(xs) == [2.0, 2.0, 1.0, 1.0]
    assert (alphas > 0.0).all()


# -- integracao: JudgmentSystem aciona o SparkSystem em acertos PERFEITOS --


def test_perfect_hit_emits_a_spark_burst_at_the_crosshair(tmp_path, null_input, null_clock):
    beatmap_path = write_beatmap(tmp_path / "spark.beatmap.json", [_basic(3.0, lane=0)])
    config = make_config(beatmap_path)
    composed = compose_world(config, null_input, null_clock)
    assert isinstance(composed.spark_system, SparkSystem)

    null_input.set_axis("aim_x", 1.0)
    null_input.set_axis("aim_y", 0.0)
    dt = 3.0 - null_clock.now_seconds()
    null_input.set_action_held("fire", True)
    null_clock.advance(dt)
    null_input.poll()
    composed.world.step(dt)

    _, _, _, _, alphas, _ = composed.spark_system.render_arrays()
    assert int((alphas > 0.0).sum()) == config.spark_burst_count


def test_good_hit_does_not_emit_sparks(tmp_path, null_input, null_clock):
    beatmap_path = write_beatmap(tmp_path / "spark_good.beatmap.json", [_basic(3.0, lane=0)])
    config = make_config(beatmap_path)
    composed = compose_world(config, null_input, null_clock)

    null_input.set_axis("aim_x", 1.0)
    null_input.set_axis("aim_y", 0.0)
    # GOOD, nao PERFECT: bem depois da janela perfect (0.05s) mas dentro da good (0.10s)
    dt = 3.08 - null_clock.now_seconds()
    null_input.set_action_held("fire", True)
    null_clock.advance(dt)
    null_input.poll()
    composed.world.step(dt)

    _, _, _, _, alphas, _ = composed.spark_system.render_arrays()
    assert int((alphas > 0.0).sum()) == 0


def test_lanes_mode_never_registers_a_spark_system(tmp_path, null_input, null_clock):
    import dataclasses

    beatmap_path = write_beatmap(tmp_path / "no_spark.beatmap.json", [])
    config = dataclasses.replace(make_config(beatmap_path), game_mode="lanes")
    composed = compose_world(config, null_input, null_clock)
    assert composed.spark_system is None
