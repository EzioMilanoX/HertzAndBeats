"""Modo Falange (Undyne): escudo automatico (raio+angulo) que substitui o tiro manual -- ignora cliques, bloqueia sozinho."""
import dataclasses
import math

import pytest
from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine

from hertzbeats.audio.sfx_synth import SFX_SHIELD_EQUIP
from hertzbeats.bootstrap.rhythm_composition_root import compose_world

from tests.conftest import make_config, write_beatmap


def _threat(timestamp: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": timestamp, "threat_type": "rhythm_threat_basic", "lane": lane, "strength": 0.5}


def _compose(tmp_path, null_input, null_clock, threats, audio_engine=None, **overrides):
    beatmap_path = write_beatmap(tmp_path / "phalanx.beatmap.json", threats)
    config = dataclasses.replace(make_config(beatmap_path), active_modifiers=("phalanx",), **overrides)
    return compose_world(config, null_input, null_clock, audio_engine=audio_engine), config


def _toggle_phalanx(composed, null_clock, null_input, dt: float = 0.01) -> None:
    null_input.set_action_held("toggle_phalanx", True)
    null_clock.advance(dt)
    null_input.poll()
    composed.world.step(dt)
    null_input.set_action_held("toggle_phalanx", False)
    null_input.poll()


def _aim_at(null_input, angle: float) -> None:
    null_input.set_axis("aim_x", math.cos(angle))
    null_input.set_axis("aim_y", math.sin(angle))


def _advance(composed, null_clock, null_input, steps: int, dt: float = 0.01) -> None:
    for _ in range(steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)


def _advance_until_resolved(composed, threat_pool, null_clock, null_input, max_steps: int, dt: float = 0.01) -> None:
    """Avanca ate a UNICA ameaca da pool nascer e depois ser resolvida
    (bloqueada OU perdida) ou `max_steps` esgotar -- pra' EXATAMENTE no
    instante em que o desfecho acontece, em vez de continuar avancando e
    deixar efeitos transitorios (Pulso do Nucleo, por exemplo) decairem
    de volta ao normal antes da checagem. `threat_pool.count` comeca em
    0 (nada nasceu ainda) -- so' conta como "resolvida" depois de ter
    visto a ameaca VIVA pelo menos uma vez, senao o loop sairia no
    PRIMEIRO frame por engano."""
    has_spawned = False
    for _ in range(max_steps):
        null_clock.advance(dt)
        null_input.poll()
        composed.world.step(dt)
        if threat_pool.count > 0:
            has_spawned = True
        elif has_spawned:
            return


# -- Alternancia (toggle) -----------------------------------------------


def test_phalanx_mode_starts_disabled(tmp_path, null_input, null_clock):
    composed, _config = _compose(tmp_path, null_input, null_clock, [_threat(3.0)])
    assert composed.game_state.phalanx_mode is False


def test_toggle_key_enables_and_disables_the_mode(tmp_path, null_input, null_clock):
    composed, _config = _compose(tmp_path, null_input, null_clock, [_threat(3.0)])
    _toggle_phalanx(composed, null_clock, null_input)
    assert composed.game_state.phalanx_mode is True
    _toggle_phalanx(composed, null_clock, null_input)
    assert composed.game_state.phalanx_mode is False


def test_toggle_does_nothing_without_the_phalanx_modifier(tmp_path, null_input, null_clock):
    beatmap_path = write_beatmap(tmp_path / "no_phalanx.beatmap.json", [_threat(3.0)])
    config = dataclasses.replace(make_config(beatmap_path), active_modifiers=("telegraph_rings",))
    composed = compose_world(config, null_input, null_clock)
    _toggle_phalanx(composed, null_clock, null_input)
    assert composed.game_state.phalanx_mode is False


def test_toggle_plays_the_equip_sfx_and_shakes_the_camera_both_ways(tmp_path, null_input, null_clock):
    engine = NullAudioEngine()
    composed, config = _compose(tmp_path, null_input, null_clock, [_threat(3.0)], audio_engine=engine)
    # `_toggle_phalanx` avanca 1 frame (dt=0.01) -- o CameraShakeSystem
    # decai o tremor NESSE MESMO frame (`shake_decay_per_second`), entao
    # o valor logo apos o toggle ja e' o pico MENOS 1 passo de decaimento,
    # nunca o pico bruto.
    expected_after_one_frame = config.phalanx_activate_shake_px - config.shake_decay_per_second * 0.01

    _toggle_phalanx(composed, null_clock, null_input)
    assert composed.game_state.phalanx_mode is True
    assert (SFX_SHIELD_EQUIP, 0.8) in engine._one_shots_played
    assert composed.game_state.shake_intensity == pytest.approx(expected_after_one_frame)
    equips_so_far = len(engine._one_shots_played)

    composed.game_state.shake_intensity = 0.0  # simula o decaimento ja consumido
    _toggle_phalanx(composed, null_clock, null_input)
    assert composed.game_state.phalanx_mode is False
    assert len(engine._one_shots_played) == equips_so_far + 1  # MESMO som toca ao sair tambem
    assert composed.game_state.shake_intensity == pytest.approx(expected_after_one_frame)


def test_phalanx_mode_hides_the_crosshair(tmp_path, null_input, null_clock):
    composed, _config = _compose(tmp_path, null_input, null_clock, [_threat(3.0)])
    sprite_pool = composed.memory_manager.get_pool("sprite")
    row = sprite_pool.dense_row_of(composed.crosshair_entity_index)
    assert int(sprite_pool.active_view()["tint_a"][row]) == 255

    _toggle_phalanx(composed, null_clock, null_input)
    assert int(sprite_pool.active_view()["tint_a"][row]) == 0

    _toggle_phalanx(composed, null_clock, null_input)
    assert int(sprite_pool.active_view()["tint_a"][row]) == 255


# -- Bypass do tiro manual -------------------------------------------------


def test_phalanx_mode_ignores_fire_clicks_entirely(tmp_path, null_input, null_clock):
    composed, _config = _compose(tmp_path, null_input, null_clock, [_threat(10.0, lane=0)])
    _toggle_phalanx(composed, null_clock, null_input)

    _aim_at(null_input, math.pi)  # mira longe do lane 0 -- so' pra nao coincidir com um bloqueio
    null_input.set_action_held("fire", True)
    null_clock.advance(0.01)
    null_input.poll()
    composed.world.step(0.01)

    state = composed.game_state
    assert state.perfect_count == 0
    assert state.misfire_count == 0  # nem misfire -- o clique e' IGNORADO por completo


# -- Bloqueio passivo por raio + angulo ------------------------------------


def test_phalanx_blocks_a_threat_that_crosses_the_ring_inside_the_arc(tmp_path, null_input, null_clock):
    composed, _config = _compose(tmp_path, null_input, null_clock, [_threat(10.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _toggle_phalanx(composed, null_clock, null_input)
    _aim_at(null_input, 0.0)  # lane 0 -> angulo 0
    _advance_until_resolved(composed, threat_pool, null_clock, null_input, max_steps=1200)

    assert threat_pool.count == 0
    state = composed.game_state
    assert state.perfect_count == 1
    assert state.combo_count == 1
    assert state.miss_count == 0
    assert state.core_pulse_seconds_left > 0.0  # checado no instante do bloqueio -- ainda nao decaiu


def test_phalanx_does_not_block_a_threat_outside_the_shield_arc(tmp_path, null_input, null_clock):
    composed, config = _compose(tmp_path, null_input, null_clock, [_threat(10.0, lane=0)], max_health=3)
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _toggle_phalanx(composed, null_clock, null_input)
    _aim_at(null_input, math.pi)  # lado OPOSTO do lane 0 -- fora do arco de 45 graus
    _advance_until_resolved(composed, threat_pool, null_clock, null_input, max_steps=1200)

    assert threat_pool.count == 0
    state = composed.game_state
    assert state.perfect_count == 0
    assert state.miss_count == 1  # passou direto -- MISS e dano como de costume
    assert state.health == config.max_health - 1


def test_phalanx_does_not_block_a_threat_outside_the_radius_tolerance(tmp_path, null_input, null_clock):
    """Mira certa (lane 0), mas o escudo so' bloqueia PERTO do anel de
    julgamento -- diminuir a tolerancia pra bem menos que a distancia
    de spawn garante que a ameaca nunca entra na faixa aceita."""
    composed, config = _compose(
        tmp_path, null_input, null_clock, [_threat(10.0, lane=0)],
        max_health=3, phalanx_radius_tolerance_px=0.001,
    )
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")

    _toggle_phalanx(composed, null_clock, null_input)
    _aim_at(null_input, 0.0)
    _advance_until_resolved(composed, threat_pool, null_clock, null_input, max_steps=1200)

    assert threat_pool.count == 0
    state = composed.game_state
    assert state.perfect_count == 0
    assert state.miss_count == 1
    assert state.health == config.max_health - 1


def test_vampirism_perk_heals_during_consecutive_phalanx_blocks(tmp_path, null_input, null_clock):
    threats = [_threat(10.0, lane=0), _threat(11.0, lane=0), _threat(12.0, lane=0)]
    composed, _config = _compose(
        tmp_path, null_input, null_clock, threats,
        max_health=5, vampirism_combo_threshold=3, vampirism_max_health=5,
    )
    composed.game_state.health = 4  # abre espaco pra curar

    _toggle_phalanx(composed, null_clock, null_input)
    _aim_at(null_input, 0.0)
    _advance(composed, null_clock, null_input, 1210)

    state = composed.game_state
    assert state.perfect_count == 3
    assert state.combo_count == 3
    assert state.health == 5  # curou exatamente 1 HP ao fechar o 3o bloqueio seguido


# -- Pulso do nucleo (CameraShakeSystem) ------------------------------------


def test_core_pulse_shrinks_on_block_and_recovers_linearly(tmp_path, null_input, null_clock):
    composed, config = _compose(tmp_path, null_input, null_clock, [_threat(10.0, lane=0)])
    threat_pool = composed.memory_manager.get_pool("rhythm_threat")
    transform_pool = composed.memory_manager.get_pool("transform")
    row = transform_pool.dense_row_of(composed.player_entity_index)
    base_scale = config.core_half_extent / 8.0

    scale_before = float(transform_pool.active_view()["scale_x"][row])
    assert abs(scale_before - base_scale) < 1e-6  # repouso: sem pulso, escala normal

    _toggle_phalanx(composed, null_clock, null_input)
    _aim_at(null_input, 0.0)
    _advance_until_resolved(composed, threat_pool, null_clock, null_input, max_steps=1200)
    assert threat_pool.count == 0  # confirma que o bloqueio (nao o MISS) e' quem resolveu

    scale_at_impact = float(transform_pool.active_view()["scale_x"][row])
    assert scale_at_impact < base_scale  # encolhido logo apos o bloqueio

    _advance(composed, null_clock, null_input, int(config.core_pulse_seconds / 0.01) + 5)
    scale_after = float(transform_pool.active_view()["scale_y"][row])
    assert abs(scale_after - base_scale) < 1e-6  # de volta ao normal


def test_core_pulse_is_inert_outside_the_defender_mode_player_entity(tmp_path, null_input, null_clock):
    """Sem nenhum bloqueio (Modo Falange desligado), o pulso nunca
    dispara -- a escala do nucleo fica parada no valor base o jogo
    inteiro."""
    composed, config = _compose(tmp_path, null_input, null_clock, [_threat(10.0, lane=0)])
    transform_pool = composed.memory_manager.get_pool("transform")
    row = transform_pool.dense_row_of(composed.player_entity_index)
    base_scale = config.core_half_extent / 8.0

    _advance(composed, null_clock, null_input, 1005)
    assert abs(float(transform_pool.active_view()["scale_x"][row]) - base_scale) < 1e-6


# -- Renderer real: dica de controles, rotulo do checkbox, arco do escudo --


def test_phalanx_control_hint_texture_is_registered_for_a_curated_stage():
    """Mesma logica de `test_every_menu_row_has_a_registered_label_texture`
    -- sem a textura, `_blit_centered` desenharia a dica em branco."""
    from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
    from hertzbeats.adapters.texture_bank import build_and_register_overlay_surfaces
    from hertzbeats.stages import StageDef

    stage = StageDef(
        stage_id="s", name="FASE", subtitle="", track_path="", beatmap_path="unused",
        synth=None, beatmap_params={}, overrides={}, active_modifiers=("phalanx",),
    )
    renderer = HBPygameRenderer()
    renderer.initialize(120, 120, "test")
    build_and_register_overlay_surfaces(renderer, (stage,))
    assert renderer._overlay_surfaces.get("stage_0_hint") is not None


def test_phalanx_checkbox_row_has_a_registered_label_texture():
    """`DEFENDER_MODIFIER_ROWS`/`_MODIFIER_ROW_LABELS` precisam
    concordar -- mesma checagem de `test_every_menu_row_has_a_registered_label_texture`,
    trancando so' o modifier novo."""
    from hertzbeats.adapters.texture_bank import _MODIFIER_ROW_LABELS
    from hertzbeats.bootstrap.hertz_game_loop import DEFENDER_MODIFIER_ROWS

    assert "phalanx" in DEFENDER_MODIFIER_ROWS
    assert "phalanx" in _MODIFIER_ROW_LABELS


def test_phalanx_shield_draws_without_crashing_via_real_renderer():
    """`begin_frame`/`_draw_phalanx_shield` com o playfield radial
    configurado e o estado do escudo publicado nao pode levantar --
    mesmo criterio de `test_draw_hub_overlay_renders_every_category_without_crashing`."""
    from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer

    renderer = HBPygameRenderer()
    renderer.initialize(200, 200, "test")
    renderer.set_playfield(
        "radial", center_x=100.0, center_y=100.0, spawn_radius=90.0, judgment_radius=40.0,
    )
    renderer.set_phalanx_state(True, 0.0, math.radians(22.5))
    renderer.begin_frame()
    renderer.end_frame()


def test_phalanx_shield_is_not_drawn_when_inactive():
    """Sem `set_phalanx_state(True, ...)`, `_draw_phalanx_shield` e' um
    no-op completo (o `_phalanx_active` default e' `False`) -- so'
    confirma que nao levanta e nao precisa de estado extra pra isso."""
    from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer

    renderer = HBPygameRenderer()
    renderer.initialize(200, 200, "test")
    renderer.set_playfield(
        "radial", center_x=100.0, center_y=100.0, spawn_radius=90.0, judgment_radius=40.0,
    )
    renderer.begin_frame()
    renderer.end_frame()
