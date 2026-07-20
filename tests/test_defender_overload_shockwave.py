"""Defensor -- Overload do Nucleo: Dash em Overdrive sobre uma batida viva dispara o ShockwaveSystem reaproveitado."""
import dataclasses

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.components.schemas import POLARITY_BLUE

from tests.conftest import make_config, write_beatmap


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _compose_polarity(tmp_path, null_input, null_clock, threats, **overrides):
    beatmap_path = write_beatmap(tmp_path / "overload.beatmap.json", threats)
    config = dataclasses.replace(
        make_config(beatmap_path),
        active_modifiers=("telegraph_rings", "polarity", "overload"),
        **overrides,
    )
    return compose_world(config, null_input, null_clock), config


def _advance_to(composed, null_clock, null_input, target_seconds: float, dt: float = 0.01) -> None:
    remaining = target_seconds - null_clock.now_seconds()
    steps = int(round(remaining / dt))
    for _ in range(steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)


def _press_dash_at(composed, null_clock, null_input, target_seconds: float) -> None:
    dt = target_seconds - null_clock.now_seconds()
    null_input.set_action_held("dash", True)
    null_clock.advance(dt)
    null_input.poll()
    composed.world.step(dt)


def _any_shockwave_active(composed) -> bool:
    shockwave_pool = composed.memory_manager.get_pool("shockwave")
    return bool(shockwave_pool.active_view()["active"][: shockwave_pool.count].any())


def test_dash_in_overdrive_on_a_live_beat_triggers_overload_and_resets_resonance(tmp_path, null_input, null_clock):
    composed, config = _compose_polarity(
        tmp_path, null_input, null_clock, [_basic(3.0, lane=0)], resonance_chain_threshold=2
    )
    state = composed.game_state
    state.resonance_color = POLARITY_BLUE
    state.resonance_chain = 2  # ja em Overdrive
    assert state.in_overdrive is True

    _advance_to(composed, null_clock, null_input, 2.98)
    _press_dash_at(composed, null_clock, null_input, 2.99)  # |delta|=0.01 <= good_window(0.10)

    assert state.overload_requested is False  # consumido no MESMO frame pelo ShockwaveSystem
    assert state.resonance_chain == 0
    assert state.resonance_color == -1
    assert _any_shockwave_active(composed)


def test_dash_without_overdrive_never_triggers_overload(tmp_path, null_input, null_clock):
    composed, config = _compose_polarity(
        tmp_path, null_input, null_clock, [_basic(3.0, lane=0)], resonance_chain_threshold=2
    )
    state = composed.game_state
    state.resonance_color = POLARITY_BLUE
    state.resonance_chain = 1  # abaixo do limiar -- NAO esta em Overdrive
    assert state.in_overdrive is False

    _advance_to(composed, null_clock, null_input, 2.98)
    _press_dash_at(composed, null_clock, null_input, 2.99)

    assert state.resonance_chain == 1  # intocado
    assert not _any_shockwave_active(composed)


def test_dash_in_overdrive_without_a_live_beat_nearby_does_nothing(tmp_path, null_input, null_clock):
    composed, config = _compose_polarity(
        tmp_path, null_input, null_clock, [_basic(5.0, lane=0)], resonance_chain_threshold=2
    )
    state = composed.game_state
    state.resonance_color = POLARITY_BLUE
    state.resonance_chain = 2
    assert state.in_overdrive is True

    _advance_to(composed, null_clock, null_input, 1.0)  # ameaca de 5.0 esta bem longe no tempo
    _press_dash_at(composed, null_clock, null_input, 1.01)

    assert state.resonance_chain == 2  # nao consumido -- nenhuma batida viva
    assert not _any_shockwave_active(composed)


def test_overload_shockwave_destroys_a_weak_threat_it_sweeps(tmp_path, null_input, null_clock):
    # 4.5s: ja nasceu quando avancamos ate 2.98 (spawn = 4.5 - approach_seconds(2.0) = 2.5),
    # mas seu proprio impacto esta longe o bastante de 2.99 para nao ser
    # a "batida viva" do gatilho nem varrida como overdue-miss.
    composed, config = _compose_polarity(
        tmp_path, null_input, null_clock,
        [_basic(3.0, lane=0), _basic(4.5, lane=4)],
        resonance_chain_threshold=2,
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    transform_pool = composed.memory_manager.get_pool("transform")
    state = composed.game_state
    state.resonance_color = POLARITY_BLUE
    state.resonance_chain = 2

    _advance_to(composed, null_clock, null_input, 2.98)
    assert threat_pool.count == 2

    # teleporta a ameaca "vitima" (a distante, ainda intocada) para cima
    # do nucleo -- mesmo truque de `test_orbital_shield_destroys_a_threat...`
    center_x, center_y = config.center_xy
    victim_index = None
    for entity_index in threat_pool.active_entity_indices():
        entity_index = int(entity_index)
        row = threat_pool.dense_row_of(entity_index)
        if float(threat_pool.active_view()["target_hit_time_sec"][row]) == 4.5:
            victim_index = entity_index
    assert victim_index is not None
    v_row = transform_pool.dense_row_of(victim_index)
    transform_pool.active_view()["position_x"][v_row] = center_x
    transform_pool.active_view()["position_y"][v_row] = center_y

    score_before = state.score
    _press_dash_at(composed, null_clock, null_input, 2.99)  # dispara o Overload sobre a batida de 3.0
    assert _any_shockwave_active(composed)
    assert threat_pool.count == 2  # o CollisionSystem deste frame rodou ANTES da onda ativar

    # o impacto so e detectado pelo CollisionSystem do PROXIMO frame,
    # ja com a hitbox da onda ativa desde o inicio do step
    null_input.set_action_held("dash", False)
    null_clock.advance(0.01)
    null_input.poll()
    composed.world.step(0.01)

    # a ameaca "gatilho" (3.0) chega ao anel de julgamento EXATAMENTE
    # neste instante -- podendo tambem cair dentro do alcance AABB da
    # onda (raio + meia-largura); a unica garantia estrita desta
    # afirmacao e sobre a VITIMA teleportada.
    remaining_indices = {int(i) for i in threat_pool.active_entity_indices()}
    assert victim_index not in remaining_indices  # a vitima foi varrida pela onda
    assert state.score > score_before
