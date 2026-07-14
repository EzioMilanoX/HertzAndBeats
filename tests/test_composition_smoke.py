"""Smoke headless: a composicao completa roda uma faixa inteira sem vazar entidades."""
from hertzbeats.components.schemas import JUDGMENT_PENDING


def _make_track(threat_count: int = 12, first_hit: float = 3.0, spacing: float = 0.5) -> list:
    threats = []
    for i in range(threat_count):
        threats.append(
            {
                "timestamp_seconds": first_hit + i * spacing,
                "threat_type": "rhythm_threat_heavy" if i % 5 == 4 else "rhythm_threat_basic",
                "lane": i % 8,
                "strength": 0.9 if i % 5 == 4 else 0.5,
            }
        )
    return threats


def test_full_track_without_input_resolves_every_threat(compose, null_clock, null_input):
    threats = _make_track()
    composed, _ = compose(threats)
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    dt = 0.016
    last_hit = threats[-1]["timestamp_seconds"]
    steps = int((last_hit + 1.0) / dt) + 1
    null_input.poll()
    for _ in range(steps):
        null_clock.advance(dt)
        composed.world.step(dt)

    state = composed.game_state
    assert composed.spawner_system.is_finished
    assert threat_pool.count == 0  # nenhuma ameaca vazou
    # sem input, toda ameaca termina em MISS (por colisao no nucleo ou sweep)
    assert state.miss_count == len(threats)
    assert state.score == 0
    assert state.combo_count == 0
    assert state.health == 0  # dano ate o piso, sem underflow


def test_autoplay_perfect_run(compose, null_clock, null_input):
    """Simula um jogador perfeito: mira na lane da proxima ameaca e atira
    no instante exato da batida -- valida o caminho feliz completo."""
    import math

    threats = _make_track(threat_count=6, spacing=0.7)
    composed, _ = compose(threats)
    state = composed.game_state

    dt = 0.008
    fire_next = {t["timestamp_seconds"]: t["lane"] for t in threats}
    pending_times = sorted(fire_next)
    null_input.poll()

    now = 0.0
    last_hit = pending_times[-1]
    while now < last_hit + 0.5:
        now += dt
        null_clock.set_now_seconds(now)
        fire = False
        if pending_times and now >= pending_times[0]:
            lane = fire_next[pending_times.pop(0)]
            angle = 2.0 * math.pi * lane / 8
            null_input.set_axis("aim_x", math.cos(angle))
            null_input.set_axis("aim_y", math.sin(angle))
            fire = True
        null_input.set_action_held("fire", fire)
        null_input.poll()
        composed.world.step(dt)

    assert state.perfect_count == len(threats)
    assert state.miss_count == 0
    assert state.combo_count == len(threats)
    assert state.max_combo == len(threats)
    assert state.score == 300 * len(threats)
    assert state.health == 3
    assert composed.memory_manager.get_pool("rhythm_threat").count == 0
