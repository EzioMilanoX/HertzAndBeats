"""Polaridade (Ikaruga) + Parry Perfeito: cor certa destroi, cor errada e Deflect, pesada reflete."""
import dataclasses
import math

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from hertzbeats.components.schemas import POLARITY_BLUE, POLARITY_PINK

from tests.conftest import make_config, write_beatmap

_LANE_COUNT = 8  # mesmo default de make_config/HertzConfig.lane_count
_TAU = 2.0 * math.pi


def _basic(timestamp: float, lane: int) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_basic",
        "lane": lane,
        "strength": 0.5,
    }


def _heavy(timestamp: float, lane: int = 0) -> dict:
    return {
        "timestamp_seconds": timestamp,
        "threat_type": "rhythm_threat_heavy",
        "lane": lane,
        "strength": 0.9,
    }


def _compose_polarity(tmp_path, null_input, null_clock, threats):
    beatmap_path = write_beatmap(tmp_path / "p.beatmap.json", threats)
    config = dataclasses.replace(make_config(beatmap_path), polarity_enabled=True)
    return compose_world(config, null_input, null_clock), config


def _aim_for_lane(lane: int) -> tuple:
    """Vetor unitario (cos, sin) exatamente sobre o angulo de spawn da
    `lane` (`tau * lane / lane_count`, a mesma formula do spawner) --
    necessario porque so a lane 0 se alinha com o eixo (1, 0)."""
    angle = _TAU * (lane % _LANE_COUNT) / _LANE_COUNT
    return math.cos(angle), math.sin(angle)


def _advance_to(composed, null_clock, null_input, target_seconds: float, dt: float = 0.01) -> None:
    """Avanca o relogio E a fisica JUNTOS, em passos PEQUENOS do
    tamanho de um frame real, ate `target_seconds` -- SEM tocar em
    nenhuma acao de input. Usado para deixar ameacas viajarem/spawnarem
    de forma realista. Um UNICO salto de `delta_time` grande quebraria
    a matematica do spawner radial: uma ameaca criada A META do salto
    calcularia sua velocidade para o pouco tempo de viagem RESTANTE,
    mas o `PhysicsSystem` do MESMO `step()` aplicaria essa velocidade
    pelo `delta_time` INTEIRO do salto -- arremessando-a para muito
    alem da arena antes do primeiro frame real."""
    remaining = target_seconds - null_clock.now_seconds()
    steps = int(round(remaining / dt))
    for _ in range(steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)


def _fire_at(composed, null_clock, null_input, target_seconds: float, action_name: str, aim_x: float, aim_y: float) -> None:
    """Avanca o ULTIMO trecho (pequeno) ate `target_seconds` num UNICO
    passo em que `action_name` fica "apertado neste frame" -- e o
    equivalente do jogador clicar exatamente no instante certo. Manter
    o aperto de botao ISOLADO do avanco de viagem (`_advance_to`) evita
    que o botao fique "apenas segurado" (borda ja consumida) quando o
    relogio finalmente cruza a janela de julgamento."""
    dt = target_seconds - null_clock.now_seconds()
    null_input.set_axis("aim_x", aim_x)
    null_input.set_axis("aim_y", aim_y)
    null_input.set_action_held(action_name, True)
    null_clock.advance(dt)
    null_input.poll()
    composed.world.step(dt)


def test_matching_color_destroys_basic_threat(tmp_path, null_input, null_clock):
    # lane 6 (>= lane_count/2=4) -> POLARITY_BLUE, destruida por "fire"
    composed, _ = _compose_polarity(tmp_path, null_input, null_clock, [_basic(3.0, lane=6)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 1.0)
    assert threat_pool.count == 1
    assert int(threat_pool.active_view()["polarity_id"][0]) == POLARITY_BLUE

    aim_x, aim_y = _aim_for_lane(6)
    _advance_to(composed, null_clock, null_input, 2.96)
    _fire_at(composed, null_clock, null_input, 2.97, "fire", aim_x, aim_y)

    state = composed.game_state
    assert state.score == 300
    assert state.perfect_count == 1
    assert threat_pool.count == 0


def test_wrong_color_is_deflect_not_destroy(tmp_path, null_input, null_clock):
    # lane 6 -> BLUE; disparar "fire_alt" (ROSA) no tempo/mira certos nao acerta
    composed, _ = _compose_polarity(tmp_path, null_input, null_clock, [_basic(3.0, lane=6)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 1.0)
    state = composed.game_state
    state.combo_count = 5

    aim_x, aim_y = _aim_for_lane(6)
    _advance_to(composed, null_clock, null_input, 2.96)
    _fire_at(composed, null_clock, null_input, 2.97, "fire_alt", aim_x, aim_y)

    assert state.score == 0
    assert state.deflect_count == 1
    assert state.misfire_count == 0
    assert state.combo_count == 5  # deflect nao pune nem quebra combo
    assert threat_pool.count == 1  # a ameaca segue viva, pode ser acertada depois


def test_matching_pink_color_destroys_low_lane_threat(tmp_path, null_input, null_clock):
    # lane 1 (< lane_count/2=4) -> POLARITY_PINK, destruida por "fire_alt"
    composed, _ = _compose_polarity(tmp_path, null_input, null_clock, [_basic(3.0, lane=1)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 1.0)
    assert int(threat_pool.active_view()["polarity_id"][0]) == POLARITY_PINK

    aim_x, aim_y = _aim_for_lane(1)
    _advance_to(composed, null_clock, null_input, 2.96)
    _fire_at(composed, null_clock, null_input, 2.97, "fire_alt", aim_x, aim_y)

    assert composed.game_state.perfect_count == 1
    assert threat_pool.count == 0


def test_heavy_threat_accepts_either_color_and_reflects_instead_of_dying(tmp_path, null_input, null_clock):
    composed, _ = _compose_polarity(tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    velocity_pool = composed.memory_manager.get_pool("velocity")
    _advance_to(composed, null_clock, null_input, 2.98)  # spawnada e quase no nucleo
    assert threat_pool.count == 1
    entity_index = int(threat_pool.active_entity_indices()[0])
    v_row = velocity_pool.dense_row_of(entity_index)
    velocity_before = float(velocity_pool.active_view()["linear_x"][v_row])
    assert velocity_before < 0.0  # viajando PARA o centro (lane 0 nasce do lado +x)

    _fire_at(composed, null_clock, null_input, 2.99, "fire", 1.0, 0.0)  # QUALQUER cor serve para o parry

    state = composed.game_state
    assert state.parry_count == 1
    assert state.combo_count == 1
    assert threat_pool.count == 1  # nao foi destruida -- ainda viva, agora refletida
    row = threat_pool.dense_row_of(entity_index)
    assert bool(threat_pool.active_view()["is_reflected"][row]) is True

    velocity_after = float(velocity_pool.active_view()["linear_x"][v_row])
    assert velocity_after == -velocity_before  # velocidade invertida (agora para fora)


def test_heavy_threat_requires_the_tighter_perfect_window(tmp_path, null_input, null_clock):
    """Fora da janela PERFECT (mas dentro da GOOD generica) nao ha parry
    nem destruicao -- pesadas so aceitam o timing mais estreito."""
    composed, _ = _compose_polarity(tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 1.0)  # spawna a pesada

    _fire_at(composed, null_clock, null_input, 2.92, "fire", 1.0, 0.0)  # delta=0.08: good, fora do perfect(0.05)

    state = composed.game_state
    assert state.parry_count == 0
    assert state.misfire_count == 1  # nenhuma candidata valida -> misfire
    assert threat_pool.count == 1


def test_reflected_projectile_is_not_swept_as_overdue_miss(tmp_path, null_input, null_clock):
    """O projetil refletido continua com `target_hit_time_sec` do
    instante ORIGINAL (agora no passado) -- a varredura generica de MISS
    nao pode destrui-lo por isso (bug historico corrigido nesta sessao)."""
    composed, _ = _compose_polarity(tmp_path, null_input, null_clock, [_heavy(3.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    _advance_to(composed, null_clock, null_input, 2.98)

    _fire_at(composed, null_clock, null_input, 2.99, "fire", 1.0, 0.0)
    assert threat_pool.count == 1
    assert composed.game_state.parry_count == 1

    # bem alem da janela de miss do instante ORIGINAL (3.0) -- se a
    # varredura generica tratasse o refletido como uma vitima pendente
    # comum, ele teria sido destruido ao longo deste avanco.
    null_input.set_action_held("fire", False)
    _advance_to(composed, null_clock, null_input, 3.5)

    assert threat_pool.count == 1
    assert composed.game_state.miss_count == 0


def test_parry_reflected_projectile_destroys_threat_in_its_path(tmp_path, null_input, null_clock):
    """Parry Perfeito: o projetil refletido varre o caminho de volta e
    destroi outra ameaca DEFENSOR pendente que cruzar seu caminho
    (`ParryImpactSystem`, via a MESMA camada de colisao generica)."""
    composed, _ = _compose_polarity(
        tmp_path, null_input, null_clock,
        [_heavy(3.0, lane=0), _basic(3.6, lane=0)],
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    transform_pool = composed.memory_manager.get_pool("transform")

    _advance_to(composed, null_clock, null_input, 2.98)  # ambas ja spawnadas
    assert threat_pool.count == 2

    # identifica pelo threat_type (heavy=1, basic=0 na config de teste)
    entity_indices = list(threat_pool.active_entity_indices())
    heavy_index = None
    basic_index = None
    for entity_index in entity_indices:
        entity_index = int(entity_index)
        row = threat_pool.dense_row_of(entity_index)
        if int(threat_pool.active_view()["threat_type"][row]) == 1:
            heavy_index = entity_index
        else:
            basic_index = entity_index
    assert heavy_index is not None and basic_index is not None

    _fire_at(composed, null_clock, null_input, 2.99, "fire", 1.0, 0.0)  # PERFECT no pesado -> reflete

    heavy_row = threat_pool.dense_row_of(heavy_index)
    assert bool(threat_pool.active_view()["is_reflected"][heavy_row]) is True
    assert threat_pool.count == 2  # ainda nao colidiu com nada

    # forca o encontro: teleporta o basic para EXATAMENTE a posicao atual
    # do projetil refletido (mesma lane => mesma linha radial, y identico)
    heavy_t_row = transform_pool.dense_row_of(heavy_index)
    heavy_x = float(transform_pool.active_view()["position_x"][heavy_t_row])
    heavy_y = float(transform_pool.active_view()["position_y"][heavy_t_row])
    basic_t_row = transform_pool.dense_row_of(basic_index)
    transform_pool.active_view()["position_x"][basic_t_row] = heavy_x
    transform_pool.active_view()["position_y"][basic_t_row] = heavy_y

    score_before = composed.game_state.score
    null_input.set_action_held("fire", False)
    null_input.poll()
    composed.world.step(0.0)  # colisao no MESMO lugar, sem mover nada

    assert threat_pool.count == 1  # o basic foi destruido pelo impacto
    remaining_index = int(threat_pool.active_entity_indices()[0])
    assert remaining_index == heavy_index  # o refletido sobrevive, segue viajando
    assert composed.game_state.score > score_before


def test_parry_reflected_projectile_impact_triggers_camera_shake(tmp_path, null_input, null_clock):
    composed, config = _compose_polarity(
        tmp_path, null_input, null_clock,
        [_heavy(3.0, lane=0), _basic(3.6, lane=0)],
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    transform_pool = composed.memory_manager.get_pool("transform")

    _advance_to(composed, null_clock, null_input, 2.98)
    entity_indices = list(threat_pool.active_entity_indices())
    heavy_index = None
    basic_index = None
    for entity_index in entity_indices:
        entity_index = int(entity_index)
        row = threat_pool.dense_row_of(entity_index)
        if int(threat_pool.active_view()["threat_type"][row]) == 1:
            heavy_index = entity_index
        else:
            basic_index = entity_index

    _fire_at(composed, null_clock, null_input, 2.99, "fire", 1.0, 0.0)  # PERFECT -> reflete

    heavy_t_row = transform_pool.dense_row_of(heavy_index)
    heavy_x = float(transform_pool.active_view()["position_x"][heavy_t_row])
    heavy_y = float(transform_pool.active_view()["position_y"][heavy_t_row])
    basic_t_row = transform_pool.dense_row_of(basic_index)
    transform_pool.active_view()["position_x"][basic_t_row] = heavy_x
    transform_pool.active_view()["position_y"][basic_t_row] = heavy_y

    null_input.set_action_held("fire", False)
    null_input.poll()
    composed.world.step(0.0)  # impacto do refletido no basic

    assert composed.game_state.shake_intensity == config.parry_impact_shake_px
