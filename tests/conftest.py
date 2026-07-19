"""Fixtures da suite headless do Hertz & Beats (backends Null da engine, clock manual)."""
import os

# Drivers dummy ANTES de qualquer import capaz de tocar pygame (mesma
# fiacao de infraestrutura do conftest da engine).
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import json
from pathlib import Path

import pytest

from ouroboros.interfaces.null.null_audio_clock import NullAudioClock
from ouroboros.interfaces.null.null_input_provider import NullInputProvider

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.config import HertzConfig


def write_beatmap(path: Path, threats: list, mapper_version: int = None) -> Path:
    """Grava um beatmap.json valido (schema v1 da engine) com a lista de
    ameacas fornecida (dicts com timestamp_seconds/threat_type/lane/strength).
    `mapper_version` opcional simula beatmaps cacheados da biblioteca."""
    document = {
        "version": 1,
        "track_id": "test_track",
        "bpm": 120.0,
        "threats": sorted(threats, key=lambda t: t["timestamp_seconds"]),
    }
    if mapper_version is not None:
        document["mapper_version"] = mapper_version
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(document, f)
    return path


def make_config(beatmap_path: Path) -> HertzConfig:
    """`HertzConfig` deterministico de teste: mesma afinacao do jogo real,
    latencia zero (clock manual) e caminhos apontando para o tmp."""
    return HertzConfig(
        window_width=960,
        window_height=960,
        window_title="test",
        entity_capacity=1024,
        max_threats=64,
        max_threats_per_frame=32,
        target_fps=60,
        beatmap_path=str(beatmap_path),
        track_path="unused.wav",
        input_bindings_path="unused.json",
        stages_path="unused.json",
        threat_type_ids={"rhythm_threat_basic": 0, "rhythm_threat_heavy": 1, "rhythm_threat_bomb": 2},
        threat_half_extents={
            "rhythm_threat_basic": 10.0, "rhythm_threat_heavy": 16.0, "rhythm_threat_bomb": 12.0,
        },
        lane_count=8,
        approach_seconds=2.0,
        spawn_radius=420.0,
        core_half_extent=16.0,
        perfect_window_seconds=0.05,
        good_window_seconds=0.10,
        miss_window_seconds=0.15,
        aim_tolerance_degrees=35.0,
        score_perfect=300,
        score_good=100,
        max_health=3,
        judgment_display_seconds=0.6,
        dash_duration_seconds=0.25,
        dash_cooldown_seconds=0.8,
        output_latency_seconds=0.0,
    )


@pytest.fixture
def null_input() -> NullInputProvider:
    return NullInputProvider()


@pytest.fixture
def null_clock() -> NullAudioClock:
    clock = NullAudioClock()
    clock.set_playing(True)
    return clock


@pytest.fixture
def compose(tmp_path, null_input, null_clock):
    """Fabrica de composicao headless: `compose(threats)` grava o beatmap
    em tmp e monta o jogo COMPLETO (mesma `compose_world` do jogo real)
    sobre os backends Null."""

    def _compose(threats: list):
        beatmap_path = write_beatmap(tmp_path / "test.beatmap.json", threats)
        config = make_config(beatmap_path)
        composed = compose_world(config, null_input, null_clock)
        return composed, config

    return _compose
