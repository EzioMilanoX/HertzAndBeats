"""Arcade 4K: Inversao de Gravidade (Reverse Scroll) -- espelha spawn/linha de julgamento em tempo real; o julgamento nunca muda."""
import dataclasses

from hertzbeats.bootstrap.rhythm_composition_root import compose_world, lane_center_positions
from hertzbeats.modchart import compute_scroll_flip_fraction, parse_reverse_scroll_events

from tests.conftest import make_config, write_beatmap


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _compose_lane_reverse(tmp_path, null_input, null_clock, threats, reverse_events, **overrides):
    beatmap_path = write_beatmap(tmp_path / "rev.beatmap.json", threats)
    config = dataclasses.replace(make_config(beatmap_path), game_mode="lanes", **overrides)
    return (
        compose_world(config, null_input, null_clock, modchart_events=reverse_events),
        config,
    )


def _advance_to(composed, null_clock, null_input, target_seconds: float, dt: float = 0.01) -> None:
    remaining = target_seconds - null_clock.now_seconds()
    steps = int(round(remaining / dt))
    for _ in range(steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)


# -- funcoes puras -----------------------------------------------------


def test_parse_reverse_scroll_events_sorts_by_time():
    raw = [
        {"type": "reverse_scroll", "time_seconds": 5.0, "duration_seconds": 1.0, "reversed": False},
        {"type": "reverse_scroll", "time_seconds": 1.0, "duration_seconds": 2.0, "reversed": True},
        {"type": "swap", "time_seconds": 0.5, "lane_a": 0, "lane_b": 3},
    ]
    events = parse_reverse_scroll_events(raw)
    assert events == ((1.0, 2.0, 1.0), (5.0, 1.0, 0.0))


def test_compute_scroll_flip_fraction_before_after_and_midway():
    events = ((10.0, 2.0, 1.0),)
    assert compute_scroll_flip_fraction(5.0, events) == 0.0  # antes do evento
    assert abs(compute_scroll_flip_fraction(11.0, events) - 0.5) < 1e-9  # metade do caminho
    assert compute_scroll_flip_fraction(50.0, events) == 1.0  # bem depois -- congelado invertido


def test_compute_scroll_flip_fraction_toggles_back_to_normal():
    events = ((10.0, 1.0, 1.0), (20.0, 1.0, 0.0))
    assert compute_scroll_flip_fraction(15.0, events) == 1.0  # invertido apos o 1o evento
    assert compute_scroll_flip_fraction(50.0, events) == 0.0  # normal de novo apos o 2o evento


# -- regressao: sem eventos, a fisica precisa continuar EXATA ----------


def test_no_reverse_events_note_still_lands_exactly_on_the_judgment_line(tmp_path, null_input, null_clock):
    """Bug real encontrado ao escrever este teste: o ReverseScrollSystem
    roda incondicionalmente (mesmo sem nenhum evento) para poder
    reagir a Modcharts registrados a qualquer momento -- recalcular a
    velocidade TODO frame precisa ser matematicamente EXATO quando
    nao ha inversao ativa, senao toda nota do Arcade 4K passaria a
    cair fora do tempo. Corrigido usando `now_effective - delta_time`
    (o instante que a posicao AINDA NAO integrada de fato representa)
    em vez de `now_effective` puro no recalculo."""
    composed, config = _compose_lane_reverse(
        tmp_path, null_input, null_clock, [_basic(3.0, lane=6)], reverse_events=[]
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 1.0)
    assert threat_pool.count == 1
    entity_index = int(threat_pool.active_entity_indices()[0])
    transform_pool = composed.memory_manager.get_pool("transform")
    t_row = transform_pool.dense_row_of(entity_index)

    _advance_to(composed, null_clock, null_input, 3.0)  # exatamente no hit_time
    judgment_line_y = config.window_height - config.judgment_line_offset
    y = float(transform_pool.active_view()["position_y"][t_row])
    assert abs(y - judgment_line_y) < 0.5


# -- integracao: geometria dinamica -------------------------------------


def test_reverse_scroll_event_flips_spawn_and_judgment_geometry(tmp_path, null_input, null_clock):
    composed, config = _compose_lane_reverse(
        tmp_path, null_input, null_clock, [],
        reverse_events=[{"type": "reverse_scroll", "time_seconds": 1.0, "duration_seconds": 1.0, "reversed": True}],
    )
    base_judgment_line_y = config.window_height - config.judgment_line_offset
    flipped_judgment_line_y = config.window_height - base_judgment_line_y

    _advance_to(composed, null_clock, null_input, 0.5)
    assert abs(float(composed.lane_geometry_y[1]) - base_judgment_line_y) < 1e-6

    _advance_to(composed, null_clock, null_input, 5.0)  # bem depois do fim (1.0+1.0=2.0)
    assert abs(float(composed.lane_geometry_y[1]) - flipped_judgment_line_y) < 1e-6


def test_falling_note_retargets_to_the_flipped_judgment_line_in_real_time(tmp_path, null_input, null_clock):
    """Nota nascida ANTES da inversao comecar precisa terminar sua
    queda na linha de julgamento INVERTIDA, nao na original -- a
    "fisica real" (velocity_y) e recalculada a cada frame para
    espelhar a mudanca."""
    composed, config = _compose_lane_reverse(
        tmp_path, null_input, null_clock,
        [_basic(20.0, lane=0)],  # hit_time=20, approach=20 -> spawna em t=0, cai por 20s
        reverse_events=[{"type": "reverse_scroll", "time_seconds": 2.0, "duration_seconds": 1.0, "reversed": True}],
        approach_seconds=20.0,
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 1.0)
    assert threat_pool.count == 1
    entity_index = int(threat_pool.active_entity_indices()[0])
    transform_pool = composed.memory_manager.get_pool("transform")
    t_row = transform_pool.dense_row_of(entity_index)

    base_judgment_line_y = config.window_height - config.judgment_line_offset
    flipped_judgment_line_y = config.window_height - base_judgment_line_y

    _advance_to(composed, null_clock, null_input, 20.0)  # hit_time -- flip ja completo ha muito
    y = float(transform_pool.active_view()["position_y"][t_row])
    assert abs(y - flipped_judgment_line_y) < 1.0
    assert abs(flipped_judgment_line_y - base_judgment_line_y) > 100.0  # confirma que sao bem diferentes


def test_judgment_is_unaffected_by_an_active_reverse_scroll(tmp_path, null_input, null_clock):
    """O `LaneJudgmentSystem` e 100% temporal -- um PERFECT no instante
    certo continua um PERFECT independente da geometria visual."""
    composed, config = _compose_lane_reverse(
        tmp_path, null_input, null_clock, [_basic(3.0, lane=0)],
        reverse_events=[{"type": "reverse_scroll", "time_seconds": 1.0, "duration_seconds": 0.5, "reversed": True}],
    )
    null_clock.set_now_seconds(2.98)  # dentro da janela PERFECT
    null_input.set_action_held("lane_0", True)
    null_input.poll()
    composed.world.step(0.016)

    state = composed.game_state
    assert state.perfect_count == 1
    assert state.score == config.score_perfect
