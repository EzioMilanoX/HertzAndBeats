"""Defensor -- Colapso de Visao (Tolerancia Organica): raio cosmetico via evento do beatmap, NUNCA a fisica (mira/spawner)."""
import dataclasses
import math

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.modchart import compute_tunnel_radius, parse_vision_tunnel_events

from tests.conftest import make_config, write_beatmap


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _compose_defender(tmp_path, null_input, null_clock, threats, collapse_events, **overrides):
    beatmap_path = write_beatmap(tmp_path / "tunnel.beatmap.json", threats)
    config = dataclasses.replace(
        make_config(beatmap_path),
        active_modifiers=("telegraph_rings", "vision_tunnel"),
        **overrides,
    )
    return (
        compose_world(config, null_input, null_clock, modchart_events=collapse_events),
        config,
    )


def _advance_to(composed, null_clock, null_input, target_seconds: float, dt: float = 0.01) -> None:
    remaining = target_seconds - null_clock.now_seconds()
    steps = int(round(remaining / dt))
    for _ in range(steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)


# -- funcoes puras -------------------------------------------------------


def test_parse_vision_tunnel_events_sorts_by_time_and_filters_other_types():
    raw = [
        {"type": "vision_tunnel", "time_seconds": 5.0, "duration_seconds": 1.0, "target_radius": 50.0},
        {"type": "vision_tunnel", "time_seconds": 1.0, "duration_seconds": 2.0, "target_radius": 20.0},
        {"type": "swap", "time_seconds": 0.5, "lane_a": 0, "lane_b": 3},
    ]
    events = parse_vision_tunnel_events(raw)
    assert events == ((1.0, 2.0, 20.0), (5.0, 1.0, 50.0))


def test_compute_tunnel_radius_before_during_and_after():
    events = ((10.0, 2.0, 50.0),)
    assert compute_tunnel_radius(5.0, 150.0, events) == 150.0  # antes do evento
    assert abs(compute_tunnel_radius(11.0, 150.0, events) - 100.0) < 1e-9  # metade do caminho
    assert compute_tunnel_radius(50.0, 150.0, events) == 50.0  # bem depois -- congelado no alvo


def test_compute_tunnel_radius_chains_a_sequence_of_events():
    events = ((10.0, 1.0, 50.0), (20.0, 1.0, 150.0))
    assert compute_tunnel_radius(15.0, 150.0, events) == 50.0  # colapsado apos o 1o evento
    assert compute_tunnel_radius(50.0, 150.0, events) == 150.0  # expandido de volta apos o 2o


# -- regressao: sem eventos, o campo de luz fica sempre TOTALMENTE ABERTO --


def test_no_vision_tunnel_events_keeps_the_field_fully_open_forever(tmp_path, null_input, null_clock):
    composed, config = _compose_defender(tmp_path, null_input, null_clock, [], collapse_events=[])
    base_radius = math.hypot(config.window_width, config.window_height)
    assert abs(composed.game_state.tunnel_radius - base_radius) < 1e-9

    _advance_to(composed, null_clock, null_input, 5.0)
    assert abs(composed.game_state.tunnel_radius - base_radius) < 1e-9


def test_vision_tunnel_is_fully_open_even_without_the_modifier(tmp_path, null_input, null_clock):
    """Sem "vision_tunnel" em `active_modifiers`, nenhum `VisionTunnelSystem`
    e registrado -- `GameState.tunnel_radius` fica no valor de composicao
    (campo aberto), NUNCA em 0 (o que enegreceria a arena inteira numa
    fase que nunca pediu o modifier)."""
    beatmap_path = write_beatmap(tmp_path / "no_tunnel.beatmap.json", [])
    config = make_config(beatmap_path)  # active_modifiers=("telegraph_rings",), sem "vision_tunnel"
    composed = compose_world(config, null_input, null_clock)
    base_radius = math.hypot(config.window_width, config.window_height)
    assert abs(composed.game_state.tunnel_radius - base_radius) < 1e-9


# -- integracao: GameState.tunnel_radius reage ao evento do beatmap ------


def test_vision_tunnel_event_shrinks_tunnel_radius_over_time(tmp_path, null_input, null_clock):
    composed, config = _compose_defender(
        tmp_path, null_input, null_clock, [],
        collapse_events=[{"type": "vision_tunnel", "time_seconds": 1.0, "duration_seconds": 1.0, "target_radius": 10.0}],
    )
    base_radius = math.hypot(config.window_width, config.window_height)
    state = composed.game_state
    assert abs(state.tunnel_radius - base_radius) < 1e-9

    _advance_to(composed, null_clock, null_input, 0.5)
    assert abs(state.tunnel_radius - base_radius) < 1e-6  # antes do evento comecar

    _advance_to(composed, null_clock, null_input, 1.5)  # metade do caminho (1.0 + duration/2)
    expected_mid = base_radius + (10.0 - base_radius) * 0.5
    assert abs(state.tunnel_radius - expected_mid) < 0.5

    _advance_to(composed, null_clock, null_input, 5.0)  # bem depois -- congelado no alvo
    assert abs(state.tunnel_radius - 10.0) < 1e-6


# -- Tolerancia Organica: o Colapso de Visao NUNCA toca a fisica ---------


def test_vision_tunnel_never_changes_the_physical_judgment_radius(tmp_path, null_input, null_clock):
    """A garantia central desta correcao: encolher o campo de luz nao
    pode mudar `current_judgment_radius` (fisico, lido pelo spawner/mira)
    -- mudar esse raio no meio da fase quebrava a velocidade ja
    calculada de ameacas em voo (o defeito que motivou reverter o antigo
    "Colapso do Anel de Julgamento")."""
    composed, config = _compose_defender(
        tmp_path, null_input, null_clock, [],
        collapse_events=[{"type": "vision_tunnel", "time_seconds": 0.0, "duration_seconds": 0.1, "target_radius": 10.0}],
    )
    base_judgment_radius = config.core_half_extent + config.threat_half_extents["rhythm_threat_basic"]
    state = composed.game_state
    assert abs(state.current_judgment_radius - base_judgment_radius) < 1e-9

    _advance_to(composed, null_clock, null_input, 5.0)  # o tunnel ja colapsou por completo
    assert abs(state.tunnel_radius - 10.0) < 1e-6  # o campo de luz encolheu de verdade...
    assert abs(state.current_judgment_radius - base_judgment_radius) < 1e-9  # ...o raio fisico NAO


def test_crosshair_orbit_radius_is_unaffected_by_the_vision_tunnel(tmp_path, null_input, null_clock):
    composed, config = _compose_defender(
        tmp_path, null_input, null_clock, [],
        collapse_events=[{"type": "vision_tunnel", "time_seconds": 0.0, "duration_seconds": 0.2, "target_radius": 10.0}],
    )
    null_input.set_axis("aim_x", 1.0)
    null_input.set_axis("aim_y", 0.0)
    _advance_to(composed, null_clock, null_input, 5.0)  # colapso de visao ja completo

    base_judgment_radius = config.core_half_extent + config.threat_half_extents["rhythm_threat_basic"]
    transform_pool = composed.memory_manager.get_pool("transform")
    row = transform_pool.dense_row_of(composed.crosshair_entity_index)
    center_x, _ = config.center_xy
    x = float(transform_pool.active_view()["position_x"][row])
    assert abs(x - (center_x + base_judgment_radius)) < 0.5


def test_new_threat_speed_is_unaffected_by_the_vision_tunnel(tmp_path, null_input, null_clock):
    composed, config = _compose_defender(
        tmp_path, null_input, null_clock, [_basic(3.0, lane=0)],
        collapse_events=[
            {"type": "vision_tunnel", "time_seconds": 0.0, "duration_seconds": 0.1, "target_radius": 10.0}
        ],
    )
    _advance_to(composed, null_clock, null_input, 1.0)  # spawn = 3.0 - approach_seconds(2.0); tunnel ja colapsado
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    assert threat_pool.count == 1
    velocity_pool = composed.memory_manager.get_pool("velocity")
    entity_index = int(threat_pool.active_entity_indices()[0])
    v_row = velocity_pool.dense_row_of(entity_index)
    speed = math.hypot(
        float(velocity_pool.active_view()["linear_x"][v_row]),
        float(velocity_pool.active_view()["linear_y"][v_row]),
    )

    base_judgment_radius = config.core_half_extent + config.threat_half_extents["rhythm_threat_basic"]
    time_remaining = 3.0 - null_clock.now_seconds()
    expected_speed = (config.spawn_radius - base_judgment_radius) / time_remaining
    assert abs(speed - expected_speed) < 1.0
