"""Arcade 4K: Obstrucoes Visuais (jumpscares) -- pool fixo ativado por evento, cobre a tela por um instante e some sozinho."""
import dataclasses

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.components.texture_ids import TEX_DISTRACTION_SPLAT
from hertzbeats.systems.distraction_system import parse_distraction_events

from tests.conftest import make_config, write_beatmap


def test_parse_distraction_events_sorts_by_time_and_ignores_unknown_types():
    raw = [
        {"type": "distraction", "time_seconds": 5.0, "duration_seconds": 0.5, "x_fraction": 0.2, "y_fraction": 0.8},
        {"type": "distraction", "time_seconds": 1.0, "duration_seconds": 0.3, "x_fraction": 0.5, "y_fraction": 0.5},
        {"type": "swap", "time_seconds": 0.5, "lane_a": 0, "lane_b": 3},
    ]
    events = parse_distraction_events(raw)
    assert events == ((1.0, 0.3, 0.5, 0.5), (5.0, 0.5, 0.2, 0.8))


def _compose_lane_distractions(tmp_path, null_input, null_clock, distraction_events):
    beatmap_path = write_beatmap(tmp_path / "distraction.beatmap.json", [])
    config = dataclasses.replace(make_config(beatmap_path), game_mode="lanes")
    return (
        compose_world(config, null_input, null_clock, modchart_events=distraction_events),
        config,
    )


def _advance_to(composed, null_clock, null_input, target_seconds: float, dt: float = 0.01) -> None:
    remaining = target_seconds - null_clock.now_seconds()
    steps = int(round(remaining / dt))
    for _ in range(steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)


def _active_distraction(composed):
    pool = composed.memory_manager.get_pool("distraction")
    view = pool.active_view()
    for entity_index in pool.active_entity_indices():
        entity_index = int(entity_index)
        row = pool.dense_row_of(entity_index)
        if bool(view["active"][row]):
            return entity_index
    return None


def test_distraction_activates_at_its_scheduled_time_with_correct_position_and_texture(
    tmp_path, null_input, null_clock
):
    events = [{"type": "distraction", "time_seconds": 2.0, "duration_seconds": 0.5, "x_fraction": 0.25, "y_fraction": 0.75}]
    composed, config = _compose_lane_distractions(tmp_path, null_input, null_clock, events)

    _advance_to(composed, null_clock, null_input, 1.9)
    assert _active_distraction(composed) is None  # ainda nao chegou a hora

    _advance_to(composed, null_clock, null_input, 2.01)
    entity_index = _active_distraction(composed)
    assert entity_index is not None

    transform_pool = composed.memory_manager.get_pool("transform")
    sprite_pool = composed.memory_manager.get_pool("sprite")
    t_row = transform_pool.dense_row_of(entity_index)
    s_row = sprite_pool.dense_row_of(entity_index)
    assert abs(float(transform_pool.active_view()["position_x"][t_row]) - 0.25 * config.window_width) < 1e-3
    assert abs(float(transform_pool.active_view()["position_y"][t_row]) - 0.75 * config.window_height) < 1e-3
    assert int(sprite_pool.active_view()["texture_id"][s_row]) == TEX_DISTRACTION_SPLAT
    assert int(sprite_pool.active_view()["tint_a"][s_row]) == 255
    assert int(sprite_pool.active_view()["layer_z"][s_row]) > 100  # acima do HUD


def test_distraction_hides_itself_after_its_duration_expires(tmp_path, null_input, null_clock):
    events = [{"type": "distraction", "time_seconds": 2.0, "duration_seconds": 0.3, "x_fraction": 0.5, "y_fraction": 0.5}]
    composed, config = _compose_lane_distractions(tmp_path, null_input, null_clock, events)

    _advance_to(composed, null_clock, null_input, 2.05)
    entity_index = _active_distraction(composed)
    assert entity_index is not None

    _advance_to(composed, null_clock, null_input, 2.35)  # passou dos 0.3s de duracao
    assert _active_distraction(composed) is None
    sprite_pool = composed.memory_manager.get_pool("sprite")
    s_row = sprite_pool.dense_row_of(entity_index)
    assert int(sprite_pool.active_view()["tint_a"][s_row]) == 0


def test_multiple_distractions_round_robin_across_the_fixed_pool(tmp_path, null_input, null_clock):
    events = [
        {"type": "distraction", "time_seconds": t, "duration_seconds": 5.0, "x_fraction": 0.5, "y_fraction": 0.5}
        for t in (1.0, 1.2, 1.4)
    ]
    composed, config = _compose_lane_distractions(tmp_path, null_input, null_clock, events)

    _advance_to(composed, null_clock, null_input, 1.5)
    pool = composed.memory_manager.get_pool("distraction")
    active_count = sum(
        1 for idx in pool.active_entity_indices()
        if bool(pool.active_view()["active"][pool.dense_row_of(int(idx))])
    )
    assert active_count == 3  # 3 eventos disparados, pool tem 5 slots -- cabem sem reciclar


def test_no_distraction_events_never_activates_the_pool(tmp_path, null_input, null_clock):
    composed, config = _compose_lane_distractions(tmp_path, null_input, null_clock, [])
    _advance_to(composed, null_clock, null_input, 5.0)
    assert _active_distraction(composed) is None
