"""Arcade 4K: Notas Longas classicas (tecla sustentada) + Shield -- Fase 1 engaja, Fase 2 exige a tecla segurada."""
import dataclasses

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.components.schemas import JUDGMENT_MISS, JUDGMENT_PENDING

from tests.conftest import make_config, write_beatmap


def _heavy(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_heavy",
        "lane": lane,
        "strength": 0.9,
    }


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _compose_lane_holds(tmp_path, null_input, null_clock, threats, **overrides):
    beatmap_path = write_beatmap(tmp_path / "lh.beatmap.json", threats)
    config = dataclasses.replace(
        make_config(beatmap_path), game_mode="lanes", active_modifiers=("holds",), **overrides
    )
    return compose_world(config, null_input, null_clock), config


def _advance_to(composed, null_clock, null_input, target_seconds: float, dt: float = 0.01) -> None:
    """Mesmo helper de `test_hold_notes_and_camera_shake.py`: avanca
    relogio e fisica JUNTOS em passos pequenos."""
    remaining = target_seconds - null_clock.now_seconds()
    steps = int(round(remaining / dt))
    for _ in range(steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)


def _press_lane(composed, null_clock, null_input, target_seconds: float, lane_index: int) -> None:
    """Aperta a tecla da coluna num UNICO passo isolado -- a borda de
    pressao (`is_action_pressed`) precisa cair exatamente neste frame."""
    dt = target_seconds - null_clock.now_seconds()
    null_input.set_action_held(f"lane_{lane_index}", True)
    null_clock.advance(dt)
    null_input.poll()
    composed.world.step(dt)


def _hold_lane_and_advance(composed, null_clock, null_input, target_seconds: float, lane_index: int) -> None:
    """Continua segurando a tecla da coluna e avanca ate `target_seconds`
    em passos pequenos (Fase 2 -- Sustain)."""
    null_input.set_action_held(f"lane_{lane_index}", True)
    _advance_to(composed, null_clock, null_input, target_seconds)


def _release_lane(composed, null_input, lane_index: int) -> None:
    """Solta a tecla da coluna e roda um passo de dt=0.0 -- isola a
    quebra do Hold no MESMO frame, sem decaimento de Camera Shake."""
    null_input.set_action_held(f"lane_{lane_index}", False)
    null_input.poll()
    composed.world.step(0.0)


def test_lone_heavy_note_becomes_a_classic_hold_with_duration(tmp_path, null_input, null_clock):
    composed, config = _compose_lane_holds(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=1.0
    )
    _advance_to(composed, null_clock, null_input, 1.0)
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 1
    row = threat_pool.dense_row_of(int(threat_pool.active_entity_indices()[0]))
    view = threat_pool.active_view()
    assert bool(view["is_hold"][row]) is False  # nao e Scratch (cluster de 1 < min_cluster_size)
    assert abs(float(view["duration_sec"][row]) - 1.0) < 1e-6


def test_hold_visual_bar_is_capped_and_never_dominates_the_fall_column(tmp_path, null_input, null_clock):
    """Bug real encontrado via smoke test: com `hold_duration_seconds`
    comparavel a `approach_seconds` (o padrao de ambos, ~1.5-1.8s), a
    barra caida SEM TETO cobria ~75% da altura da janela (a mesma
    velocidade de queda da nota, por `duration_sec` inteiro) -- um
    "bug" visual que fazia a nota longa parecer quebrada/gigante.
    `lane_hold_visual_max_fraction` limita o COMPRIMENTO RENDERIZADO,
    nunca a duracao exigida do jogador."""
    composed, config = _compose_lane_holds(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)],
        hold_duration_seconds=1.5, approach_seconds=1.8,
    )
    _advance_to(composed, null_clock, null_input, 1.5)
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 1
    entity_index = int(threat_pool.active_entity_indices()[0])
    transform_pool = composed.memory_manager.get_pool("transform")
    t_row = transform_pool.dense_row_of(entity_index)
    scale_y = float(transform_pool.active_view()["scale_y"][t_row])
    rendered_height_px = scale_y * 16.0  # mesma conversao do HBPygameRenderer.draw_batch

    judgment_line_y = config.window_height - config.judgment_line_offset
    fall_distance_px = judgment_line_y - (-24.0)  # spawn_y fixo do modo Lanes
    max_allowed_px = fall_distance_px * config.lane_hold_visual_max_fraction

    assert rendered_height_px <= max_allowed_px + 1e-6
    # ainda assim claramente mais longa que uma nota normal (nao veio a
    # zero/desapareceu por causa do teto)
    assert rendered_height_px > 100.0


def test_pressing_the_lane_key_on_a_hold_note_engages_without_destroying(tmp_path, null_input, null_clock):
    composed, config = _compose_lane_holds(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=1.0
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 2.98)
    entity_index = int(threat_pool.active_entity_indices()[0])

    _press_lane(composed, null_clock, null_input, 2.99, 0)  # dentro da janela Good (0.10)

    assert threat_pool.count == 1  # engajada, NAO destruida
    row = threat_pool.dense_row_of(entity_index)
    view = threat_pool.active_view()
    assert bool(view["is_hit"][row]) is True
    assert int(view["judgment"][row]) == JUDGMENT_PENDING


def test_sustaining_the_lane_key_through_duration_scores_perfect(tmp_path, null_input, null_clock):
    composed, config = _compose_lane_holds(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=1.0
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 2.98)
    _press_lane(composed, null_clock, null_input, 2.99, 0)
    assert threat_pool.count == 1

    # sustenta a tecla ate passar de target(3.0) + duration(1.0) = 4.0
    _hold_lane_and_advance(composed, null_clock, null_input, 4.02, 0)

    state = composed.game_state
    assert threat_pool.count == 0
    assert state.perfect_count == 1
    assert state.score == config.score_perfect
    assert state.combo_count == 1
    assert state.miss_count == 0


def test_engaged_hold_survives_well_past_its_original_target_time(tmp_path, null_input, null_clock):
    """O `target_hit_time_sec` (o INICIO do hold) fica no passado assim
    que a sustentacao comeca -- a varredura generica de MISS NAO pode
    trata-lo como uma vitima comum so por isso (mesma classe de bug do
    Hold do Defensor/Parry, corrigida aqui do mesmo jeito)."""
    composed, config = _compose_lane_holds(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=2.0
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 2.98)
    _press_lane(composed, null_clock, null_input, 2.99, 0)
    assert threat_pool.count == 1

    # bem alem da janela de miss (0.15) do instante ORIGINAL (3.0), mas
    # ainda dentro da sustentacao (ate 5.0)
    _hold_lane_and_advance(composed, null_clock, null_input, 3.5, 0)

    assert threat_pool.count == 1
    assert composed.game_state.miss_count == 0
    row = threat_pool.dense_row_of(int(threat_pool.active_entity_indices()[0]))
    assert int(threat_pool.active_view()["judgment"][row]) == JUDGMENT_PENDING


def test_releasing_the_lane_key_mid_sustain_is_absorbed_by_the_shield(tmp_path, null_input, null_clock):
    composed, config = _compose_lane_holds(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=1.0
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    state = composed.game_state
    state.combo_count = 5
    assert state.shield_charges == config.lane_shield_max_charges

    _advance_to(composed, null_clock, null_input, 2.98)
    _press_lane(composed, null_clock, null_input, 2.99, 0)
    assert threat_pool.count == 1

    _hold_lane_and_advance(composed, null_clock, null_input, 3.2, 0)  # bem antes do fim (4.0)
    _release_lane(composed, null_input, 0)

    assert threat_pool.count == 0  # MISS imediato -- nao esperou o fim
    assert state.miss_count == 1
    assert state.combo_count == 0
    assert state.last_judgment == JUDGMENT_MISS
    assert state.perfect_count == 0

    assert state.shield_charges == config.lane_shield_max_charges - 1
    assert state.health == config.max_health  # absorvido pelo Shield -- sem dano
    assert state.shake_intensity == config.hold_break_shake_px


def test_shield_absorbs_up_to_its_max_charges_then_costs_real_health(tmp_path, null_input, null_clock):
    """Esgotado o Shield, a proxima quebra de Hold passa a custar vida
    de verdade -- a PRIMEIRA forma do Arcade 4K de chegar ao Game Over."""
    threats = [_heavy(3.0, lane=0), _heavy(6.0, lane=1), _heavy(9.0, lane=2), _heavy(12.0, lane=3)]
    composed, config = _compose_lane_holds(tmp_path, null_input, null_clock, threats, hold_duration_seconds=1.0)
    state = composed.game_state
    assert state.shield_charges == config.lane_shield_max_charges == 3

    for lane_index, hit_time in enumerate((3.0, 6.0, 9.0)):
        _advance_to(composed, null_clock, null_input, hit_time - 0.02)
        _press_lane(composed, null_clock, null_input, hit_time - 0.01, lane_index)
        _hold_lane_and_advance(composed, null_clock, null_input, hit_time + 0.2, lane_index)
        _release_lane(composed, null_input, lane_index)

    assert state.shield_charges == 0
    assert state.health == config.max_health  # as 3 quebras ainda foram absorvidas
    assert state.shake_intensity == config.hold_break_shake_px

    # 4a quebra: Shield ja esgotado -> custa vida de verdade + tremor maior
    _advance_to(composed, null_clock, null_input, 12.0 - 0.02)
    _press_lane(composed, null_clock, null_input, 12.0 - 0.01, 3)
    _hold_lane_and_advance(composed, null_clock, null_input, 12.2, 3)
    _release_lane(composed, null_input, 3)

    assert state.shield_charges == 0  # nao fica negativo
    assert state.health == config.max_health - 1
    assert state.shake_intensity == config.lane_shield_depleted_shake_px
    assert null_input._last_rumble == (
        config.rumble_low_freq, config.rumble_high_freq, config.rumble_duration_seconds
    )


def test_basic_note_is_unaffected_by_holds_enabled(tmp_path, null_input, null_clock):
    composed, config = _compose_lane_holds(tmp_path, null_input, null_clock, [_basic(3.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 2.98)
    _press_lane(composed, null_clock, null_input, 2.99, 0)

    assert threat_pool.count == 0  # destruida normalmente, sem engajar
    assert composed.game_state.perfect_count == 1
