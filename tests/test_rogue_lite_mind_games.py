"""Rogue-lite -- Mind Games (Defensor): Buracos de Minhoca, Ameacas Fantasmas, Efeito Elastico, Perk Vampirismo."""
import dataclasses
import math

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.components.schemas import JUDGMENT_DODGED, JUDGMENT_MISS, JUDGMENT_PENDING, JUDGMENT_PERFECT
from hertzbeats.systems.mind_games_system import MindGamesSystem

from tests.conftest import make_config, write_beatmap


def _threat(timestamp: float, lane: int = 0, threat_type: str = "rhythm_threat_basic") -> dict:
    return {"timestamp_seconds": timestamp, "threat_type": threat_type, "lane": lane, "strength": 0.5}


def _compose(tmp_path, null_input, null_clock, threats, **overrides):
    beatmap_path = write_beatmap(tmp_path / "mind_games.beatmap.json", threats)
    config = dataclasses.replace(make_config(beatmap_path), **overrides)
    return compose_world(config, null_input, null_clock), config


def _advance_to(composed, null_clock, null_input, target_seconds: float, dt: float = 0.01) -> None:
    remaining = target_seconds - null_clock.now_seconds()
    steps = int(round(remaining / dt))
    for _ in range(steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)


def _fire_at(composed, null_clock, null_input, target_seconds: float, angle: float) -> None:
    """Um UNICO disparo de borda (mesmo criterio de
    `test_defender_polarity_resonance._fire_at`) -- solta o gatilho
    logo depois, pra que a PROXIMA chamada produza uma borda de pressao
    nova em vez de ficar "sempre segurado" (`is_action_pressed` e'
    detectado por BORDA, `NullInputProvider.is_action_pressed`)."""
    dt = target_seconds - null_clock.now_seconds()
    null_input.set_axis("aim_x", math.cos(angle))
    null_input.set_axis("aim_y", math.sin(angle))
    null_input.set_action_held("fire", True)
    null_clock.advance(dt)
    null_input.poll()
    composed.world.step(dt)
    null_input.set_action_held("fire", False)
    null_input.poll()


def _radius(config, x: float, y: float) -> float:
    cx, cy = config.center_xy
    return math.hypot(x - cx, y - cy)


# -- Registro condicional do MindGamesSystem --------------------------------


def test_mind_games_system_is_absent_without_wormholes_or_rubber_band(tmp_path, null_input, null_clock):
    composed, _config = _compose(
        tmp_path, null_input, null_clock, [_threat(3.0)], active_modifiers=("mirages",),
    )
    assert not any(isinstance(s, MindGamesSystem) for s in composed.world._systems)


def test_mind_games_system_registers_for_wormholes(tmp_path, null_input, null_clock):
    composed, _config = _compose(
        tmp_path, null_input, null_clock, [_threat(3.0)], active_modifiers=("wormholes",),
    )
    assert any(isinstance(s, MindGamesSystem) for s in composed.world._systems)


def test_mind_games_system_registers_for_rubber_band(tmp_path, null_input, null_clock):
    composed, _config = _compose(
        tmp_path, null_input, null_clock, [_threat(3.0)], active_modifiers=("rubber_band",),
    )
    assert any(isinstance(s, MindGamesSystem) for s in composed.world._systems)


# -- Buracos de Minhoca (teleporte) -----------------------------------------


def test_wormholes_flag_common_threats_but_not_boomerangs(tmp_path, null_input, null_clock):
    # Um DUMMY "basic" adicional (lane 5, descartado) e necessario:
    # `_reinterpret_scheduled_for_modifiers` (modifier "boomerang"
    # sozinho) reinterpreta a cada 7a ocorrencia AINDA "basic" da fila
    # como bumerangue TAMBEM -- `[::7]` conta posicoes DENTRO do array
    # filtrado de linhas "basic" (nao o indice absoluto na fila), entao
    # com so' 1 linha "basic" ela SEMPRE seria a "0a" e seria pega por
    # engano. Com 2 linhas "basic" (dummy + a de verdade), so' a 1a
    # (dummy) e' reinterpretada -- a linha 0 (lane 0) fica "basic" de
    # verdade, validando so' o que o teste pediu: a EXCLUSAO de
    # bumerangues (ja tipados desde o beatmap) do Buraco de Minhoca.
    composed, config = _compose(
        tmp_path, null_input, null_clock,
        [
            _threat(8.0, lane=5),  # dummy -- absorve a reinterpretacao [::7]
            _threat(9.0, lane=1, threat_type="rhythm_threat_boomerang"),
            _threat(10.0, lane=0),
        ],
        active_modifiers=("wormholes", "boomerang"),  # "boomerang" precisa estar ativo pro
        # spawner reconhecer o threat_type como bumerangue de verdade (`is_boomerang`
        # depende de `boomerang_threat_type_id`, so' resolvido quando o modifier esta ligado)
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 10.0 - config.approach_seconds + 0.01)
    assert threat_pool.count == 3
    view = threat_pool.active_view()
    will_teleport = {int(view["lane"][r]): bool(view["will_teleport"][r]) for r in range(3)}
    teleport_radius = {int(view["lane"][r]): float(view["teleport_radius"][r]) for r in range(3)}
    assert will_teleport[0] is True
    assert will_teleport[1] is False  # bumerangue nunca teleporta
    assert teleport_radius[0] == config.wormhole_teleport_radius


def test_wormhole_reflects_position_negates_velocity_and_flips_the_aim_angle(tmp_path, null_input, null_clock):
    composed, config = _compose(
        tmp_path, null_input, null_clock, [_threat(10.0, lane=0)], active_modifiers=("wormholes",),
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    transform_pool = composed.memory_manager.get_pool("transform")
    velocity_pool = composed.memory_manager.get_pool("velocity")
    center_x, center_y = config.center_xy

    spawn_time = 10.0 - config.approach_seconds
    _advance_to(composed, null_clock, null_input, spawn_time + 0.01)
    entity_index = int(threat_pool.active_entity_indices()[0])
    t_row = transform_pool.dense_row_of(entity_index)
    v_row = velocity_pool.dense_row_of(entity_index)
    velocity_before = float(velocity_pool.active_view()["linear_x"][v_row])
    assert velocity_before < 0.0  # lane 0 -> angulo 0 -- viaja em -x rumo ao centro

    # cruza `teleport_radius` (220.0 por padrao) em algum ponto do voo --
    # avanca frame a frame ate o raio efetivamente cair CLARAMENTE abaixo
    # dele (margem de 5px -- so' checar "<= teleport_radius" pode parar
    # UM frame ANTES da travessia de verdade, com o raio ainda um pouco
    # ACIMA do limiar, e o teleporte so dispara no frame seguinte).
    for _ in range(400):
        null_clock.advance(0.005)
        null_input.poll()
        composed.world.step(0.005)
        x = float(transform_pool.active_view()["position_x"][t_row])
        y = float(transform_pool.active_view()["position_y"][t_row])
        if _radius(config, x, y) <= config.wormhole_teleport_radius - 5.0:
            break

    threat_row = threat_pool.dense_row_of(entity_index)
    threat_view = threat_pool.active_view()
    assert bool(threat_view["will_teleport"][threat_row]) is False  # consumida, one-shot

    x_after = float(transform_pool.active_view()["position_x"][t_row])
    y_after = float(transform_pool.active_view()["position_y"][t_row])
    # lane 0 -> angulo 0 -> nasceu no lado +x (x > center_x); refletido
    # pelo centro, reaparece do lado OPOSTO (-x, x < center_x).
    assert x_after < center_x
    assert abs(y_after - center_y) < 1.0

    velocity_after = float(velocity_pool.active_view()["linear_x"][v_row])
    assert velocity_after == -velocity_before  # negada

    angle_after = float(threat_view["spawn_angle_rad"][threat_row])
    assert abs((angle_after % (2.0 * math.pi)) - math.pi) < 1e-3  # angulo original (0) + PI


def test_aiming_at_the_original_angle_after_a_wormhole_flip_no_longer_hits(tmp_path, null_input, null_clock):
    composed, config = _compose(
        tmp_path, null_input, null_clock, [_threat(10.0, lane=0)], active_modifiers=("wormholes",),
    )
    _advance_to(composed, null_clock, null_input, 10.0 - config.approach_seconds + 0.01)
    _advance_to(composed, null_clock, null_input, 9.99)  # bem perto do impacto -- ja passou pelo raio de 220px
    _fire_at(composed, null_clock, null_input, 10.0, 0.0)  # angulo ORIGINAL (lane 0)

    state = composed.game_state
    assert state.perfect_count == 0
    assert state.misfire_count == 1  # nada la naquela direcao mais


def test_aiming_at_the_flipped_angle_still_scores_perfect_on_time(tmp_path, null_input, null_clock):
    composed, config = _compose(
        tmp_path, null_input, null_clock, [_threat(10.0, lane=0)], active_modifiers=("wormholes",),
    )
    _advance_to(composed, null_clock, null_input, 9.99)
    _fire_at(composed, null_clock, null_input, 10.0, math.pi)  # angulo GIRADO (0 + PI)

    state = composed.game_state
    assert state.perfect_count == 1


# -- Ameacas Fantasmas (mirages) ---------------------------------------------


def test_mirages_flag_only_a_deterministic_fraction_of_lanes(tmp_path, null_input, null_clock):
    composed, config = _compose(
        tmp_path, null_input, null_clock,
        [_threat(10.0, lane=0), _threat(10.0, lane=1)],
        active_modifiers=("mirages",),
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 10.0 - config.approach_seconds + 0.01)
    view = threat_pool.active_view()
    is_mirage = {int(view["lane"][r]): bool(view["is_mirage"][r]) for r in range(2)}
    assert is_mirage[0] is True  # lane 0 % 4 == 0
    assert is_mirage[1] is False


def test_mirage_vanishes_silently_just_before_impact_with_no_penalty(tmp_path, null_input, null_clock):
    composed, config = _compose(
        tmp_path, null_input, null_clock, [_threat(10.0, lane=0)], active_modifiers=("mirages",),
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _advance_to(composed, null_clock, null_input, 10.0 - config.mirage_vanish_seconds - 0.005)
    assert threat_pool.count == 1  # ainda nao chegou a hora de sumir

    _advance_to(composed, null_clock, null_input, 10.0 - config.mirage_vanish_seconds + 0.005)
    assert threat_pool.count == 0  # sumiu sozinho

    state = composed.game_state
    assert state.miss_count == 0
    assert state.combo_count == 0
    assert state.health == config.max_health  # nenhum dano


def test_shooting_a_mirage_before_it_vanishes_forces_a_miss(tmp_path, null_input, null_clock):
    composed, config = _compose(
        tmp_path, null_input, null_clock, [_threat(10.0, lane=0)], active_modifiers=("mirages",),
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    angle = 0.0  # lane 0

    # dentro da janela PERFECT normal (0.05s) mas ainda ANTES do
    # desaparecimento (mirage_vanish_seconds=0.03) -- um "fantasma"
    # nunca deveria contar como acerto de verdade.
    _fire_at(composed, null_clock, null_input, 9.96, angle)

    state = composed.game_state
    assert state.perfect_count == 0
    assert state.good_count == 0
    assert state.miss_count == 1
    assert state.combo_count == 0
    assert threat_pool.count == 0  # destruida (como MISS), nao continua viva


def test_mirage_system_has_no_effect_when_the_modifier_is_off(tmp_path, null_input, null_clock):
    composed, config = _compose(
        tmp_path, null_input, null_clock, [_threat(10.0, lane=0)], active_modifiers=("telegraph_rings",),
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 10.0 - config.mirage_vanish_seconds + 0.005)
    assert threat_pool.count == 1  # sem "mirages", ninguem some sozinho


# -- Efeito Elastico (rubber-band) -------------------------------------------


def test_rubber_band_flags_common_threats_but_not_boomerangs(tmp_path, null_input, null_clock):
    # mesmo cuidado de `test_wormholes_flag_common_threats_but_not_boomerangs`
    # -- um DUMMY "basic" a mais absorve a reinterpretacao `[::7]`.
    composed, config = _compose(
        tmp_path, null_input, null_clock,
        [
            _threat(8.0, lane=5),
            _threat(9.0, lane=1, threat_type="rhythm_threat_boomerang"),
            _threat(10.0, lane=0),
        ],
        active_modifiers=("rubber_band", "boomerang"),
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 10.0 - config.approach_seconds + 0.01)
    view = threat_pool.active_view()
    nonlinear = {int(view["lane"][r]): bool(view["nonlinear_approach"][r]) for r in range(3)}
    assert nonlinear[0] is True
    assert nonlinear[1] is False


def test_rubber_band_eases_ahead_of_the_linear_position_at_the_midpoint(tmp_path, null_input, null_clock):
    composed, config = _compose(
        tmp_path, null_input, null_clock, [_threat(10.0, lane=0)], active_modifiers=("rubber_band",),
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    transform_pool = composed.memory_manager.get_pool("transform")

    spawn_time = 10.0 - config.approach_seconds
    midpoint = spawn_time + config.approach_seconds / 2.0
    _advance_to(composed, null_clock, null_input, midpoint)

    entity_index = int(threat_pool.active_entity_indices()[0])
    t_row = transform_pool.dense_row_of(entity_index)
    x = float(transform_pool.active_view()["position_x"][t_row])
    y = float(transform_pool.active_view()["position_y"][t_row])
    actual_radius = _radius(config, x, y)

    linear_radius = config.spawn_radius - 0.5 * (config.spawn_radius - config.core_half_extent - 10.0)
    # ease-out (sin(t*pi/2)): na METADE do tempo ja percorreu MAIS que a
    # metade da distancia -- o raio real fica ABAIXO do que a reta
    # constante do PhysicsSystem generico previria no mesmo instante.
    assert actual_radius < linear_radius - 5.0


def test_rubber_band_system_has_no_effect_when_the_modifier_is_off(tmp_path, null_input, null_clock):
    composed, config = _compose(
        tmp_path, null_input, null_clock, [_threat(10.0, lane=0)], active_modifiers=("telegraph_rings",),
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    transform_pool = composed.memory_manager.get_pool("transform")

    spawn_time = 10.0 - config.approach_seconds
    midpoint = spawn_time + config.approach_seconds / 2.0
    _advance_to(composed, null_clock, null_input, midpoint)
    entity_index = int(threat_pool.active_entity_indices()[0])
    t_row = transform_pool.dense_row_of(entity_index)
    x = float(transform_pool.active_view()["position_x"][t_row])
    y = float(transform_pool.active_view()["position_y"][t_row])
    linear_radius = config.spawn_radius - 0.5 * (config.spawn_radius - config.core_half_extent - 10.0)
    assert abs(_radius(config, x, y) - linear_radius) < 5.0  # linha reta normal, sem easing


# -- Perk Vampirismo ----------------------------------------------------------


def test_vampirism_heals_one_hp_every_n_consecutive_perfects(tmp_path, null_input, null_clock):
    threats = [_threat(3.0, lane=0), _threat(4.0, lane=1), _threat(5.0, lane=2), _threat(6.0, lane=3)]
    composed, config = _compose(
        tmp_path, null_input, null_clock, threats,
        max_health=5, vampirism_combo_threshold=3, vampirism_max_health=5,
    )
    state = composed.game_state

    # 1o tiro: MISS deliberado (sem atirar) -- reduz a vida pra 4 e
    # garante que ha espaco pra curar depois. IMPORTANTE: avanca em
    # passos PEQUENOS ate perto do impacto antes de qualquer disparo --
    # um `dt` unico enorme (ex.: pular direto de 0 pra 3.0) faz a
    # ameaca "tunelar" pela colisao do nucleo num so passo de fisica
    # (o `PhysicsSystem` integraria o deslocamento inteiro de uma vez,
    # sem nenhum frame intermediario onde as caixas realmente se
    # sobrepoem), perdendo o dano por colisao que decide a vida --
    # mesmo cuidado que qualquer outro teste de fluxo real do jogo.
    _advance_to(composed, null_clock, null_input, 3.2)  # deixa a ameaca da lane 0 passar do tempo (MISS de verdade)
    assert state.health == 4
    assert state.combo_count == 0

    for lane, timestamp in ((1, 4.0), (2, 5.0), (3, 6.0)):
        angle = 2.0 * math.pi * lane / config.lane_count
        _fire_at(composed, null_clock, null_input, timestamp, angle)

    assert state.perfect_count == 3
    assert state.combo_count == 3
    assert state.health == 5  # curou exatamente 1 HP ao fechar o 3o PERFECT seguido


def test_vampirism_heal_never_exceeds_the_configured_cap(tmp_path, null_input, null_clock):
    threats = [_threat(3.0, lane=0), _threat(4.0, lane=1)]
    composed, config = _compose(
        tmp_path, null_input, null_clock, threats,
        max_health=3, vampirism_combo_threshold=1, vampirism_max_health=3,
    )
    state = composed.game_state
    assert state.health == 3

    for lane, timestamp in ((0, 3.0), (1, 4.0)):
        angle = 2.0 * math.pi * lane / config.lane_count
        _fire_at(composed, null_clock, null_input, timestamp, angle)

    assert state.perfect_count == 2
    assert state.health == 3  # nunca passa do teto, mesmo curando a cada PERFECT


def test_vampirism_is_inert_when_the_threshold_is_zero(tmp_path, null_input, null_clock):
    composed, config = _compose(
        tmp_path, null_input, null_clock, [_threat(3.0, lane=0)], max_health=5,
    )  # vampirism_combo_threshold default = 0 (desligado)
    _fire_at(composed, null_clock, null_input, 3.0, 0.0)
    state = composed.game_state
    assert state.perfect_count == 1
    assert state.health == 5  # sem perk, sem cura


# -- Estado/catalogo puro (hertzbeats.rogue_lite) ----------------------------


def test_judgment_dodged_is_reused_for_mirage_vanish_not_a_new_enum_value():
    """Confere a decisao de reaproveitar JUDGMENT_DODGED (mesmo veredito
    dos i-frames do Dash: nao pune, nao quebra combo, nao pontua) em vez
    de inventar um enum novo pro desaparecimento de fantasmas."""
    assert JUDGMENT_DODGED not in (JUDGMENT_PENDING, JUDGMENT_MISS, JUDGMENT_PERFECT)
