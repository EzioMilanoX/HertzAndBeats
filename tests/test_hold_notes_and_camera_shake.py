"""Notas Longas (Hold) do Defensor: Fase 1 (Start) engaja, Fase 2 (Sustain) exige fire+mira continuos."""
import dataclasses
import math

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.components.schemas import JUDGMENT_MISS, JUDGMENT_PENDING, JUDGMENT_PERFECT
from hertzbeats.game_state import GameState
from hertzbeats.systems.camera_shake_system import CameraShakeSystem

from tests.conftest import make_config, write_beatmap


def _heavy(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_heavy",
        "lane": lane,
        "strength": 0.9,
    }


def _compose_holds(tmp_path, null_input, null_clock, threats, **overrides):
    beatmap_path = write_beatmap(tmp_path / "h.beatmap.json", threats)
    config = dataclasses.replace(
        make_config(beatmap_path), active_modifiers=("telegraph_rings", "holds"), **overrides
    )
    return compose_world(config, null_input, null_clock), config


def _advance_to(composed, null_clock, null_input, target_seconds: float, dt: float = 0.01) -> None:
    """Mesmo helper de `tests/test_polarity_and_parry.py`: avanca relogio
    e fisica JUNTOS em passos pequenos (nunca um salto so de relogio com
    um `world.step` de dt fixo -- ver a docstring la para o porque)."""
    remaining = target_seconds - null_clock.now_seconds()
    steps = int(round(remaining / dt))
    for _ in range(steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)


def _fire_at(composed, null_clock, null_input, target_seconds: float, aim_x: float, aim_y: float) -> None:
    """Avanca o ultimo trecho pequeno ate `target_seconds` num UNICO
    passo em que `fire` fica "apertado neste frame" -- ver
    `test_polarity_and_parry.py` para a razao de isolar o aperto."""
    dt = target_seconds - null_clock.now_seconds()
    null_input.set_axis("aim_x", aim_x)
    null_input.set_axis("aim_y", aim_y)
    null_input.set_action_held("fire", True)
    null_clock.advance(dt)
    null_input.poll()
    composed.world.step(dt)


def _hold_and_advance(composed, null_clock, null_input, target_seconds: float, aim_x=1.0, aim_y=0.0) -> None:
    """Continua segurando `fire`/mira e avanca ate `target_seconds` em
    passos pequenos (Fase 2 -- Sustain)."""
    null_input.set_axis("aim_x", aim_x)
    null_input.set_axis("aim_y", aim_y)
    null_input.set_action_held("fire", True)
    _advance_to(composed, null_clock, null_input, target_seconds)


def test_engaging_a_hold_does_not_destroy_it_and_disarms_collision(tmp_path, null_input, null_clock):
    composed, config = _compose_holds(tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    velocity_pool = composed.memory_manager.get_pool("velocity")
    hitbox_pool = composed.memory_manager.get_pool("hitbox")

    _advance_to(composed, null_clock, null_input, 2.98)
    assert threat_pool.count == 1
    entity_index = int(threat_pool.active_entity_indices()[0])

    _fire_at(composed, null_clock, null_input, 2.99, 1.0, 0.0)  # dentro da janela Good (0.10)

    assert threat_pool.count == 1  # engajada, NAO destruida
    row = threat_pool.dense_row_of(entity_index)
    assert bool(threat_pool.active_view()["is_hit"][row]) is True
    assert int(threat_pool.active_view()["judgment"][row]) == JUDGMENT_PENDING

    v_row = velocity_pool.dense_row_of(entity_index)
    assert float(velocity_pool.active_view()["linear_x"][v_row]) == 0.0
    assert float(velocity_pool.active_view()["linear_y"][v_row]) == 0.0

    hb_row = hitbox_pool.dense_row_of(entity_index)
    assert int(hitbox_pool.active_view()["collision_layer"][hb_row]) == 0
    assert int(hitbox_pool.active_view()["collision_mask"][hb_row]) == 0


def test_sustaining_through_the_full_duration_scores_perfect(tmp_path, null_input, null_clock):
    composed, config = _compose_holds(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=1.0
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _advance_to(composed, null_clock, null_input, 2.98)
    _fire_at(composed, null_clock, null_input, 2.99, 1.0, 0.0)
    assert threat_pool.count == 1

    # sustenta fire+mira ate passar de target(3.0) + duration(1.0) = 4.0
    _hold_and_advance(composed, null_clock, null_input, 4.02)

    state = composed.game_state
    assert threat_pool.count == 0
    assert state.perfect_count == 1
    assert state.score == config.score_perfect
    assert state.combo_count == 1
    assert state.miss_count == 0


def test_releasing_fire_mid_sustain_breaks_the_hold_after_the_grace_window(tmp_path, null_input, null_clock):
    """Tolerancia Organica -- Hold Forgiveness: soltar o gatilho NAO e
    mais MISS instantaneo (humanos tem micro-tremores de mao) -- so
    depois de ultrapassar `hold_grace_seconds` (Coyote Time) SEM retomar
    a sustentacao."""
    composed, config = _compose_holds(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=1.0
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    state = composed.game_state
    state.combo_count = 5

    _advance_to(composed, null_clock, null_input, 2.98)
    _fire_at(composed, null_clock, null_input, 2.99, 1.0, 0.0)
    assert threat_pool.count == 1

    health_before = state.health
    _hold_and_advance(composed, null_clock, null_input, 3.2)
    null_input.set_action_held("fire", False)
    null_input.poll()

    # Acumula quase toda a graca em passos PEQUENOS (ainda nao quebrou)...
    _advance_to(composed, null_clock, null_input, 3.2 + config.hold_grace_seconds - 0.01)
    assert threat_pool.count == 1  # ainda dentro da graca

    # ...e um ULTIMO passo pequeno que finalmente ultrapassa o limiar -- o
    # tremor e acionado NESTE frame; um dt pequeno mantem o decaimento do
    # MESMO passo (`CameraShakeSystem` roda com o MESMO dt) dentro da
    # tolerancia da asserção abaixo.
    dt = 0.02
    null_clock.advance(dt)
    null_input.poll()
    composed.world.step(dt)

    assert threat_pool.count == 0  # MISS -- ultrapassou a graca sem retomar
    assert state.miss_count == 1
    assert state.combo_count == 0
    assert state.last_judgment == JUDGMENT_MISS
    assert state.perfect_count == 0
    assert state.health == health_before - 1  # Ameaca de Hold Radial: dano instantaneo na quebra

    # feedback fisico duplo desta tarefa (tolerancia ao decaimento minimo do MESMO passo)
    assert abs(state.shake_intensity - config.hold_break_shake_px) < 1.5
    assert null_input._last_rumble == (
        config.rumble_low_freq, config.rumble_high_freq, config.rumble_duration_seconds
    )


def test_briefly_releasing_fire_within_the_grace_window_does_not_break_the_hold(tmp_path, null_input, null_clock):
    """Coyote Time: soltar o gatilho por MENOS que `hold_grace_seconds` e
    retomar antes disso nao quebra o Hold -- o micro-tremor tolerado."""
    composed, config = _compose_holds(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=1.0
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _advance_to(composed, null_clock, null_input, 2.98)
    _fire_at(composed, null_clock, null_input, 2.99, 1.0, 0.0)
    assert threat_pool.count == 1

    _hold_and_advance(composed, null_clock, null_input, 3.2)
    null_input.set_action_held("fire", False)
    null_input.poll()
    # solta por BEM MENOS que a graca (0.05s < 0.15s)...
    null_clock.advance(0.05)
    null_input.poll()
    composed.world.step(0.05)
    assert threat_pool.count == 1  # ainda vivo -- dentro da graca

    # ...e retoma a sustentacao correta antes do limiar estourar.
    _hold_and_advance(composed, null_clock, null_input, 4.02)  # ate passar de target(3.0)+duration(1.0)

    state = composed.game_state
    assert threat_pool.count == 0
    assert state.perfect_count == 1  # sustentou ate o fim -- sucesso, nao MISS
    assert state.miss_count == 0


def test_grace_timer_resets_when_sustain_resumes_so_it_never_accumulates_across_gaps(tmp_path, null_input, null_clock):
    """Duas soltadas breves (cada uma < graca), com retomada entre elas,
    NUNCA devem somar para quebrar o Hold -- o timer zera a cada retomada,
    nao acumula ao longo da vida inteira do Hold."""
    composed, config = _compose_holds(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=2.0
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _advance_to(composed, null_clock, null_input, 2.98)
    _fire_at(composed, null_clock, null_input, 2.99, 1.0, 0.0)
    assert threat_pool.count == 1

    for _ in range(4):  # 4x soltar 0.1s (< graca) + retomar -- soma 0.4s > graca, mas NUNCA de uma vez
        _hold_and_advance(composed, null_clock, null_input, null_clock.now_seconds() + 0.2)
        null_input.set_action_held("fire", False)
        null_input.poll()
        null_clock.advance(0.1)
        null_input.poll()
        composed.world.step(0.1)
        assert threat_pool.count == 1  # sobrevive toda vez -- o timer zera ao retomar

    _hold_and_advance(composed, null_clock, null_input, 5.02)  # ate passar de target(3.0)+duration(2.0)
    assert threat_pool.count == 0
    assert composed.game_state.perfect_count == 1
    assert composed.game_state.miss_count == 0


def test_releasing_fire_mid_sustain_deals_no_damage_in_practice_mode(tmp_path, null_input, null_clock):
    composed, config = _compose_holds(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)],
        hold_duration_seconds=1.0, practice_mode=True,
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    state = composed.game_state
    health_before = state.health

    _advance_to(composed, null_clock, null_input, 2.98)
    _fire_at(composed, null_clock, null_input, 2.99, 1.0, 0.0)
    assert threat_pool.count == 1

    _hold_and_advance(composed, null_clock, null_input, 3.2)
    null_input.set_action_held("fire", False)
    null_input.poll()
    # ultrapassa a graca (Tolerancia Organica -- Hold Forgiveness) antes
    # de checar o veredito -- soltar por si so nao quebra mais instantaneo.
    _advance_to(composed, null_clock, null_input, 3.2 + config.hold_grace_seconds + 0.02)

    assert state.miss_count == 1
    assert state.health == health_before  # Modo Treino: MISS conta, mas sem dano de vida


def test_aiming_away_mid_sustain_breaks_the_hold_after_the_grace_window(tmp_path, null_input, null_clock):
    """Tolerancia Organica -- Hold Forgiveness: desmirar tambem so quebra
    depois de ultrapassar `hold_grace_seconds` sem retomar a mira."""
    composed, config = _compose_holds(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=1.0
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _advance_to(composed, null_clock, null_input, 2.98)
    _fire_at(composed, null_clock, null_input, 2.99, 1.0, 0.0)
    assert threat_pool.count == 1

    _hold_and_advance(composed, null_clock, null_input, 3.2)
    # desmira para 90 graus (bem alem de hold_aim_tolerance_degrees=50) --
    # continua segurando o gatilho
    null_input.set_axis("aim_x", math.cos(math.pi / 2.0))
    null_input.set_axis("aim_y", math.sin(math.pi / 2.0))
    null_input.set_action_held("fire", True)
    _advance_to(composed, null_clock, null_input, 3.2 + config.hold_grace_seconds + 0.02)

    assert threat_pool.count == 0
    assert composed.game_state.miss_count == 1


def test_briefly_aiming_away_within_the_grace_window_does_not_break_the_hold(tmp_path, null_input, null_clock):
    """Coyote Time: desmirar por MENOS que a graca e voltar a mirar
    corretamente antes disso nao quebra o Hold."""
    composed, config = _compose_holds(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=1.0
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _advance_to(composed, null_clock, null_input, 2.98)
    _fire_at(composed, null_clock, null_input, 2.99, 1.0, 0.0)
    assert threat_pool.count == 1

    _hold_and_advance(composed, null_clock, null_input, 3.2)
    null_input.set_axis("aim_x", math.cos(math.pi / 2.0))
    null_input.set_axis("aim_y", math.sin(math.pi / 2.0))
    null_input.set_action_held("fire", True)
    _advance_to(composed, null_clock, null_input, 3.25)  # 0.05s desmirado -- bem dentro da graca
    assert threat_pool.count == 1

    _hold_and_advance(composed, null_clock, null_input, 4.02)  # retoma a mira certa ate o fim
    assert threat_pool.count == 0
    assert composed.game_state.perfect_count == 1
    assert composed.game_state.miss_count == 0


def test_engaged_hold_survives_well_past_its_original_target_time(tmp_path, null_input, null_clock):
    """O `target_hit_time_sec` (o INICIO do hold) fica no passado assim
    que a sustentacao comeca -- a varredura generica de MISS NAO pode
    trata-lo como uma vitima comum so por isso (mesma classe de bug do
    Parry, corrigida aqui do mesmo jeito)."""
    composed, config = _compose_holds(
        tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)], hold_duration_seconds=2.0
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _advance_to(composed, null_clock, null_input, 2.98)
    _fire_at(composed, null_clock, null_input, 2.99, 1.0, 0.0)
    assert threat_pool.count == 1

    # bem alem da janela de miss (0.15s) do instante ORIGINAL (3.0),
    # mas ainda dentro da janela de sustentacao (ate 5.0)
    _hold_and_advance(composed, null_clock, null_input, 3.5)

    assert threat_pool.count == 1
    assert composed.game_state.miss_count == 0
    row = threat_pool.dense_row_of(int(threat_pool.active_entity_indices()[0]))
    assert int(threat_pool.active_view()["judgment"][row]) == JUDGMENT_PENDING


def test_camera_shake_system_decays_linearly_and_stops_at_zero():
    state = GameState(max_health=3)
    system = CameraShakeSystem(state, decay_per_second=10.0)
    state.trigger_shake(25.0)

    system.update(world=None, delta_time=1.0)
    assert abs(state.shake_intensity - 15.0) < 1e-9

    system.update(world=None, delta_time=1.0)
    assert abs(state.shake_intensity - 5.0) < 1e-9

    system.update(world=None, delta_time=1.0)  # nao passa de zero
    assert state.shake_intensity == 0.0


def test_trigger_shake_takes_the_larger_of_overlapping_shakes():
    state = GameState(max_health=3)
    state.trigger_shake(10.0)
    state.trigger_shake(4.0)  # menor -- nao deve reduzir o tremor atual
    assert state.shake_intensity == 10.0
    state.trigger_shake(30.0)  # maior -- substitui
    assert state.shake_intensity == 30.0
