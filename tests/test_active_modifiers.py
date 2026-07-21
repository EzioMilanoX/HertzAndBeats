"""Arquitetura de Mecanicas Modulares: `active_modifiers` decide QUAIS sistemas extras entram na composicao, sem tocar a ordem base."""
import dataclasses

import numpy as np

from hertzbeats.bootstrap.rhythm_composition_root import (
    _reinterpret_scheduled_for_modifiers,
    compose_world,
)
from hertzbeats.stages import StageDef, resolve_stage_config
from hertzbeats.systems.convergence_ring_system import ConvergenceRingSystem
from hertzbeats.systems.orbital_capture_system import OrbitalCaptureSystem
from hertzbeats.systems.orbital_eclipse_system import OrbitalEclipseSystem
from hertzbeats.systems.parry_impact_system import ParryImpactSystem
from hertzbeats.systems.shockwave_system import ShockwaveSystem
from hertzbeats.systems.vision_tunnel_system import VisionTunnelSystem

from tests.conftest import make_config, write_beatmap


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _heavy(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_heavy",
        "lane": lane,
        "strength": 0.9,
    }


def _compose(tmp_path, null_input, null_clock, threats, active_modifiers, **overrides):
    beatmap_path = write_beatmap(tmp_path / "mods.beatmap.json", threats)
    config = dataclasses.replace(
        make_config(beatmap_path), active_modifiers=active_modifiers, **overrides
    )
    return compose_world(config, null_input, null_clock), config


def _has_system(composed, system_type) -> bool:
    return any(isinstance(system, system_type) for system in composed.world._systems)


def test_telegraph_rings_off_never_registers_the_convergence_ring_system(tmp_path, null_input, null_clock):
    composed, _ = _compose(tmp_path, null_input, null_clock, [_basic(3.0)], active_modifiers=())
    assert not _has_system(composed, ConvergenceRingSystem)


def test_telegraph_rings_on_registers_the_convergence_ring_system(tmp_path, null_input, null_clock):
    composed, _ = _compose(
        tmp_path, null_input, null_clock, [_basic(3.0)], active_modifiers=("telegraph_rings",)
    )
    assert _has_system(composed, ConvergenceRingSystem)


def test_polarity_off_never_registers_parry_impact_or_shockwave(tmp_path, null_input, null_clock):
    composed, _ = _compose(tmp_path, null_input, null_clock, [_heavy(3.0)], active_modifiers=())
    assert not _has_system(composed, ParryImpactSystem)
    assert not _has_system(composed, ShockwaveSystem)


def test_polarity_on_registers_parry_impact_system(tmp_path, null_input, null_clock):
    composed, _ = _compose(
        tmp_path, null_input, null_clock, [_heavy(3.0)], active_modifiers=("polarity",)
    )
    assert _has_system(composed, ParryImpactSystem)


def test_orbital_shields_without_polarity_degrades_to_no_op(tmp_path, null_input, null_clock):
    """"orbital_shields" sozinho (sem "polarity") nunca deveria acontecer
    numa fase bem curada, mas o design exige degradar graciosamente em
    vez de lancar erro -- nem o OrbitalCaptureSystem nem o ParryImpactSystem
    (a maquina de Parry inteira) sao registrados."""
    composed, _ = _compose(
        tmp_path, null_input, null_clock, [_heavy(3.0)], active_modifiers=("orbital_shields",)
    )
    assert not _has_system(composed, OrbitalCaptureSystem)
    assert not _has_system(composed, ParryImpactSystem)


def test_orbital_shields_with_polarity_registers_orbital_capture_system(tmp_path, null_input, null_clock):
    composed, _ = _compose(
        tmp_path, null_input, null_clock, [_heavy(3.0)],
        active_modifiers=("polarity", "orbital_shields"),
    )
    assert _has_system(composed, OrbitalCaptureSystem)


def test_overload_without_polarity_never_registers_shockwave(tmp_path, null_input, null_clock):
    composed, _ = _compose(
        tmp_path, null_input, null_clock, [_basic(3.0)], active_modifiers=("overload",)
    )
    assert not _has_system(composed, ShockwaveSystem)


def test_overload_with_polarity_registers_shockwave(tmp_path, null_input, null_clock):
    composed, _ = _compose(
        tmp_path, null_input, null_clock, [_basic(3.0)], active_modifiers=("polarity", "overload")
    )
    assert _has_system(composed, ShockwaveSystem)


def test_orbital_eclipses_requires_both_the_modifier_and_a_positive_count(tmp_path, null_input, null_clock):
    composed_without_modifier, _ = _compose(
        tmp_path, null_input, null_clock, [], active_modifiers=(), orbital_eclipse_count=3
    )
    assert not _has_system(composed_without_modifier, OrbitalEclipseSystem)

    composed_zero_count, _ = _compose(
        tmp_path, null_input, null_clock, [], active_modifiers=("orbital_eclipses",), orbital_eclipse_count=0
    )
    assert not _has_system(composed_zero_count, OrbitalEclipseSystem)

    composed_both, _ = _compose(
        tmp_path, null_input, null_clock, [], active_modifiers=("orbital_eclipses",), orbital_eclipse_count=3
    )
    assert _has_system(composed_both, OrbitalEclipseSystem)


def test_vision_tunnel_off_never_registers_vision_tunnel_system(tmp_path, null_input, null_clock):
    composed, _ = _compose(tmp_path, null_input, null_clock, [], active_modifiers=())
    assert not _has_system(composed, VisionTunnelSystem)


def test_vision_tunnel_on_registers_vision_tunnel_system(tmp_path, null_input, null_clock):
    composed, _ = _compose(
        tmp_path, null_input, null_clock, [], active_modifiers=("vision_tunnel",)
    )
    assert _has_system(composed, VisionTunnelSystem)


def test_active_modifiers_never_leaks_between_stages(tmp_path):
    """`resolve_stage_config` SUBSTITUI a lista inteira -- uma fase sem
    `active_modifiers` no JSON nunca herda os modifiers da fase anterior
    (ou de qualquer default residual)."""
    beatmap_path = write_beatmap(tmp_path / "leak.beatmap.json", [_basic(3.0)])
    base_config = dataclasses.replace(make_config(beatmap_path), active_modifiers=("polarity", "holds"))

    plain_stage = StageDef(
        stage_id="plain", name="PLAIN", subtitle="", track_path="x.wav",
        beatmap_path=str(beatmap_path), synth=None, beatmap_params={}, overrides={},
    )
    resolved = resolve_stage_config(base_config, plain_stage)
    assert resolved.active_modifiers == ()


def test_reinterpret_scheduled_reassigns_a_deterministic_fraction_of_types():
    """Gemeos/Escudos Rotativos nunca sao emitidos pelo mapeador offline
    (basic/heavy so) -- a composicao reinterpreta uma fracao FIXA e
    DETERMINISTICA (nunca por sorteio) das linhas ja agendadas."""
    from ouroboros.rhythm.runtime.schemas import SCHEDULED_THREAT_DTYPE

    basic_id, heavy_id, orbit_id, twin_id = 0, 1, 4, 5
    threat_type_ids = {
        "rhythm_threat_basic": basic_id,
        "rhythm_threat_heavy": heavy_id,
        "rhythm_threat_orbit": orbit_id,
        "rhythm_threat_twin": twin_id,
    }
    config = dataclasses.replace(
        make_config(""), threat_type_ids=threat_type_ids, active_modifiers=("polarity", "orbital_shields", "twin_threats")
    )

    scheduled = np.zeros(15, dtype=SCHEDULED_THREAT_DTYPE)
    scheduled["timestamp_seconds"] = np.arange(15, dtype=np.float64)
    # 10 comuns intercaladas com 5 pesadas
    pattern = [basic_id] * 2 + [heavy_id]
    scheduled["threat_type"] = (pattern * 5)[:15]
    original = scheduled.copy()

    modifiers = frozenset(config.active_modifiers)
    reassigned = _reinterpret_scheduled_for_modifiers(scheduled, config, modifiers)

    assert reassigned is not scheduled  # sempre uma COPIA nova
    np.testing.assert_array_equal(scheduled["threat_type"], original["threat_type"])  # original intocado

    original_basic_rows = np.flatnonzero(original["threat_type"] == basic_id)
    original_heavy_rows = np.flatnonzero(original["threat_type"] == heavy_id)
    assert np.array_equal(
        np.flatnonzero(reassigned["threat_type"] == twin_id), original_basic_rows[::5]
    )
    assert np.array_equal(
        np.flatnonzero(reassigned["threat_type"] == orbit_id), original_heavy_rows[::3]
    )
    # nenhuma linha sumiu ou trocou de timestamp
    np.testing.assert_array_equal(reassigned["timestamp_seconds"], original["timestamp_seconds"])


def test_reinterpret_scheduled_is_a_no_op_without_the_relevant_modifiers():
    from ouroboros.rhythm.runtime.schemas import SCHEDULED_THREAT_DTYPE

    config = make_config("")
    scheduled = np.zeros(5, dtype=SCHEDULED_THREAT_DTYPE)
    scheduled["threat_type"] = 0

    reassigned = _reinterpret_scheduled_for_modifiers(scheduled, config, frozenset())
    assert reassigned is scheduled  # nem copia quando nao ha nada a fazer
