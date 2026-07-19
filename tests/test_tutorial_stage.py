"""Tutorial: banner sincronizado ao relogio de audio e validade dos dados versionados das fases."""
import numpy as np

from ouroboros.rhythm.runtime.beatmap_loader import BeatmapLoader

from hertzbeats.components.texture_ids import MAX_TUTORIAL_STEPS, TEX_TUTORIAL_BASE
from hertzbeats.config import HertzConfig
from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.stages import load_stages, resolve_stage_config
from hertzbeats.systems.tutorial_system import TutorialSystem

from tests.conftest import make_config, write_beatmap


def _find_tutorial_system(composed) -> TutorialSystem:
    for system in composed.world._systems:
        if isinstance(system, TutorialSystem):
            return system
    raise AssertionError("TutorialSystem nao registrado")


def test_repo_stage_data_is_valid():
    """Os dados VERSIONADOS do repositorio sao coerentes: toda fase de
    stages.json resolve overrides contra a config real e tem um beatmap
    carregavel pelo loader da engine (schema v1, ordenado)."""
    base_config = HertzConfig.from_json("data/config/hertz_beats.config.json")
    stages = load_stages(base_config.stages_path)

    assert stages[0].stage_id == "tutorial"
    assert len(stages[0].tutorial_steps) == 5
    # tutorial + 3 defensor + arcade + polaridade + holds + arcade notas longas
    assert len(stages) == 8

    from hertzbeats.bootstrap.rhythm_composition_root import MODE_COMPOSERS

    loader = BeatmapLoader(base_config.threat_type_ids)
    for stage in stages:
        stage_config = resolve_stage_config(base_config, stage)  # overrides validos
        assert stage_config.game_mode in MODE_COMPOSERS, (
            f"{stage.stage_id}: game_mode invalido {stage_config.game_mode!r}"
        )
        scheduled = loader.load(stage.beatmap_path)
        assert scheduled.shape[0] > 0
        assert np.all(np.diff(scheduled["timestamp_seconds"]) >= 0.0)
        # toda ameaca nasce depois do inicio da faixa, ja descontada a aproximacao
        assert float(scheduled["timestamp_seconds"][0]) >= stage_config.approach_seconds


def test_tutorial_banner_follows_music_clock(tmp_path, null_input, null_clock):
    beatmap_path = write_beatmap(tmp_path / "t.beatmap.json", [
        {"timestamp_seconds": 12.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.4},
    ])
    steps = (
        {"until_seconds": 5.0, "text": "passo um"},
        {"until_seconds": 10.0, "text": "passo dois"},
    )
    composed = compose_world(
        make_config(beatmap_path), null_input, null_clock, tutorial_steps=steps, stage_ordinal=3
    )
    tutorial = _find_tutorial_system(composed)
    sprite_pool = composed.memory_manager.get_pool("sprite")
    texture_base = TEX_TUTORIAL_BASE + 3 * MAX_TUTORIAL_STEPS

    def banner():
        view = sprite_pool.active_view()
        row = sprite_pool.dense_row_of(tutorial._banner_entity_index)
        return int(view["texture_id"][row]), int(view["tint_a"][row])

    null_input.poll()
    null_clock.set_now_seconds(1.0)
    composed.world.step(0.016)
    assert banner() == (texture_base + 0, 255)
    assert tutorial.current_step == 0

    null_clock.set_now_seconds(7.0)
    composed.world.step(0.016)
    assert banner() == (texture_base + 1, 255)

    null_clock.set_now_seconds(11.0)
    composed.world.step(0.016)
    assert banner()[1] == 0  # tutorial encerrado: banner oculto
    assert tutorial.current_step == 2


def test_stage_without_tutorial_steps_has_no_tutorial_system(compose):
    composed, _ = compose([
        {"timestamp_seconds": 3.0, "threat_type": "rhythm_threat_basic", "lane": 0, "strength": 0.5},
    ])
    assert not any(isinstance(s, TutorialSystem) for s in composed.world._systems)


def test_simultaneous_tutorial_wave_all_dodged_with_one_dash(tmp_path, null_input, null_clock):
    """A onda de dash do tutorial (3 ameacas simultaneas) e atravessavel
    com UM dash: todas viram DODGED, sem dano e sem quebrar o combo."""
    beatmap_path = write_beatmap(tmp_path / "d.beatmap.json", [
        {"timestamp_seconds": 5.0, "threat_type": "rhythm_threat_basic", "lane": 1, "strength": 0.6},
        {"timestamp_seconds": 5.0, "threat_type": "rhythm_threat_basic", "lane": 4, "strength": 0.6},
        {"timestamp_seconds": 5.0, "threat_type": "rhythm_threat_basic", "lane": 7, "strength": 0.6},
    ])
    composed = compose_world(make_config(beatmap_path), null_input, null_clock)
    state = composed.game_state
    state.combo_count = 3

    # spawn (dt=0, devido em 5.0 - approach 2.0 = 3.0) e teleporte das 3 para o nucleo
    null_clock.set_now_seconds(3.0)
    composed.world.step(0.0)
    memory_manager = composed.memory_manager
    threat_pool = memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 3
    transform_pool = memory_manager.get_pool("transform")
    center_x, center_y = make_config(beatmap_path).center_xy
    for entity_index in threat_pool.active_entity_indices():
        row = transform_pool.dense_row_of(int(entity_index))
        transform_pool.active_view()["position_x"][row] = center_x
        transform_pool.active_view()["position_y"][row] = center_y

    null_clock.set_now_seconds(5.12)
    null_input.set_action_held("dash", True)
    null_input.poll()
    composed.world.step(0.016)

    assert state.dodge_count == 3
    assert state.health == 3
    assert state.combo_count == 3
    assert threat_pool.count == 0
