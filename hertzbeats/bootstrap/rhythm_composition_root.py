"""
rhythm_composition_root: o "cimento" que une a Ouroboros Engine ao
Hertz & Beats. Unico modulo do jogo -- alem de `hertzbeats.adapters` --
que instancia backends concretos (Pygame*), espelhando o papel do
`CompositionRoot` da engine.

Sequencia executada por `RhythmCompositionRoot.build()`:
    1. Instancia `PygameAudioEngine` e o renderer/input Pygame do jogo.
    2. Instancia o `MemoryManager` (alocando as pools de Hitbox,
       Transform, RhythmThreat, ...).
    3. Carrega o `beatmap.json` via `BeatmapLoader` da engine.
    4. Registra a ordem EXATA de execucao dos sistemas:
         PlayerInputSystem        (le teclado/mouse)
         RadialRhythmSpawnerSystem(le o relogio e acorda ameacas na batida)
         JudgmentSystem           (input x batida -> PERFECT/GOOD/MISS)
         PhysicsSystem            (move as ameacas nao destruidas)
         CollisionSystem          (detecta ameaca que passou do ponto)
         CoreDamageSystem         (pune o jogador pelo par detectado)
         UIRenderSystem           (monta os arrays de HUD do placar)
    5. Devolve o `HertzGameLoop` pronto: `while rodando: world.step(dt)`
       sob a maquina de estados de partida (menu de fases, pausa,
       derrota, resultados).

A parte pura (`compose_world`) e separada da parte Pygame para que os
testes headless componham o jogo INTEIRO com backends Null.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ouroboros.core.components.schemas import COMPONENT_SCHEMAS
from ouroboros.core.memory.handles import unpack_index
from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.systems.collision_system import CollisionSystem
from ouroboros.core.systems.physics_system import PhysicsSystem
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock
from ouroboros.interfaces.input_provider import IInputProvider
from ouroboros.rhythm.runtime.beatmap_loader import BeatmapLoader

from hertzbeats.audio.sfx_synth import (
    SFX_CANNON,
    SFX_CLICK,
    SFX_DEFLECT,
    SFX_GRAZE,
    SFX_HOLD_BREAK,
    SFX_HOLD_ENGAGE,
    SFX_PARRY,
    SFX_TAP,
)
from hertzbeats.components.schemas import PLAYER_STATE_DTYPE, RHYTHM_THREAT_DTYPE
from hertzbeats.lane_scratch_clustering import build_lane_schedule_with_scratches
from hertzbeats.practice_thinning import thin_schedule_for_practice
from hertzbeats.systems.camera_shake_system import CameraShakeSystem
from hertzbeats.systems.convergence_ring_system import (
    CONVERGENCE_RING_DTYPE,
    ConvergenceRingSystem,
)
from hertzbeats.systems.graze_system import GrazeSystem
from hertzbeats.systems.lane_choreography_system import LaneChoreographySystem
from hertzbeats.systems.parry_impact_system import REFLECTED_COLLISION_LAYER, ParryImpactSystem
from hertzbeats.systems.scratch_judgment_system import ScratchJudgmentSystem
from hertzbeats.systems.shockwave_system import SHOCKWAVE_DTYPE, ShockwaveSystem
from hertzbeats.systems.wall_phase_system import WallPhaseSystem
from hertzbeats.components.texture_ids import (
    MAX_TUTORIAL_STEPS,
    TEX_CROSSHAIR,
    TEX_HEALTH_PIP,
    TEX_LABEL_COMBO,
    TEX_LABEL_SCORE,
    TEX_PLAYER_CORE,
    TEX_THREAT_BASIC,
    TEX_THREAT_HEAVY,
    TEX_TUTORIAL_BASE,
)
from hertzbeats.config import HertzConfig
from hertzbeats.game_state import GameState
from hertzbeats.components.texture_ids import TEX_KEY_LABEL_BASE, TEX_LANE_RECEPTOR
from hertzbeats.systems.core_damage_system import CoreDamageSystem
from hertzbeats.systems.judgment_system import JudgmentSystem
from hertzbeats.systems.lane_judgment_system import LaneJudgmentSystem
from hertzbeats.systems.lane_note_spawner_system import LANE_COUNT_4K, LaneNoteSpawnerSystem
from hertzbeats.systems.player_input_system import PlayerInputSystem
from hertzbeats.systems.radial_spawner_system import RadialRhythmSpawnerSystem
from hertzbeats.systems.survival_damage_system import SurvivalDamageSystem
from hertzbeats.systems.survival_player_system import SurvivalPlayerSystem
from hertzbeats.systems.survival_spawner_system import SurvivalSpawnerSystem
from hertzbeats.systems.tutorial_system import TutorialSystem
from hertzbeats.systems.ui_render_system import UIRenderSystem

PLAYER_COLLISION_LAYER = 1
THREAT_COLLISION_LAYER = 4
MAX_COLLISION_PAIRS = 1024
SCORE_DIGITS = 7
COMBO_DIGITS = 4
HUD_LAYER_Z = 100
_THREAT_TEXTURE_BY_NAME = {
    "rhythm_threat_basic": TEX_THREAT_BASIC,
    "rhythm_threat_heavy": TEX_THREAT_HEAVY,
}


class ComposedGame:
    """Referencias resultantes da composicao pura, para o `build()`
    concreto, para o `__main__` (placar final) e para testes headless."""

    __slots__ = (
        "world",
        "memory_manager",
        "game_state",
        "spawner_systems",
        "collision_system",
        "player_entity_index",
        "crosshair_entity_index",
    )

    def __init__(
        self,
        world: World,
        memory_manager: MemoryManager,
        game_state: GameState,
        spawner_systems: tuple,
        collision_system: CollisionSystem,
        player_entity_index: int,
        crosshair_entity_index: int,
    ) -> None:
        self.world = world
        self.memory_manager = memory_manager
        self.game_state = game_state
        self.spawner_systems = spawner_systems
        self.collision_system = collision_system
        self.player_entity_index = player_entity_index
        self.crosshair_entity_index = crosshair_entity_index

    @property
    def spawner_system(self):
        """Atalho de conveniencia: o spawner principal (modos puros tem
        exatamente um; o Hibrido tem dois -- ver `spawner_systems`)."""
        return self.spawner_systems[0]

    @property
    def all_spawners_finished(self) -> bool:
        """True quando TODOS os spawners consumiram seus beatmaps."""
        for spawner in self.spawner_systems:
            if not spawner.is_finished:
                return False
        return True


class _ModeContext:
    """Pacote de referencias comuns entregue a cada estrategia de modo
    (`MODE_COMPOSERS`): tudo que uma estrategia precisa para registrar
    seus sistemas na ordem certa, sem parametros posicionais frageis."""

    __slots__ = (
        "config",
        "world",
        "memory_manager",
        "input_provider",
        "audio_clock",
        "audio_engine",
        "game_state",
        "scheduled",
        "hit_times",
        "threat_half_by_type",
        "threat_texture_by_type",
        "player_entity_index",
        "crosshair_entity_index",
    )

    def __init__(self, **kwargs) -> None:
        for name in self.__slots__:
            setattr(self, name, kwargs[name])


def _hide_sprite(memory_manager: MemoryManager, entity_index: int) -> None:
    """Zera o alfa do sprite de uma entidade persistente (o modo decide
    o que fica visivel: mira no Defensor, nada no Arcade, ...)."""
    sprite_pool = memory_manager.get_pool("sprite")
    row = sprite_pool.dense_row_of(entity_index)
    sprite_pool.active_view()["tint_a"][row] = 0


def _compose_defender_mode(ctx: _ModeContext):
    """MODO 1 -- O Defensor (estilo BPM/Hellsinger): nucleo fixo no
    centro, ameacas radiais 360, mira livre + tiro na batida; misfire
    zera o combo. Ordem: PlayerInput -> Spawner radial -> Judgment ->
    Physics -> Collision -> CoreDamage."""
    config = ctx.config
    center_x, center_y = config.center_xy

    spawner_system = RadialRhythmSpawnerSystem(
        audio_clock=ctx.audio_clock,
        memory_manager=ctx.memory_manager,
        scheduled_spawns=ctx.scheduled,
        hit_times=ctx.hit_times,
        threat_archetype_name="rhythm_threat_radial",
        center_xy=(center_x, center_y),
        spawn_radius=config.spawn_radius,
        core_half_extent=config.core_half_extent,
        lane_count=config.lane_count,
        threat_half_by_type=ctx.threat_half_by_type,
        threat_texture_by_type=ctx.threat_texture_by_type,
        threat_collision_layer=THREAT_COLLISION_LAYER,
        threat_collision_mask=PLAYER_COLLISION_LAYER,
        max_threats_per_frame=config.max_threats_per_frame,
        ring_archetype_name="convergence_ring",
        hold_threat_type_id=(
            config.threat_type_ids.get("rhythm_threat_heavy") if config.holds_enabled else None
        ),
        hold_duration_seconds=config.hold_duration_seconds,
        polarity_enabled=config.polarity_enabled,
    )
    collision_system = CollisionSystem(
        ctx.memory_manager,
        transform_pool_name="transform",
        hitbox_pool_name="hitbox",
        max_pairs=MAX_COLLISION_PAIRS,
    )

    # A mira orbita EXATAMENTE sobre o anel de julgamento (nucleo +
    # ameaca basica): "atire quando a ameaca tocar a sua mira" e a
    # mecanica literal, nao so uma metafora visual.
    judgment_ring_radius = config.core_half_extent + config.threat_half_extents.get(
        "rhythm_threat_basic", 10.0
    )
    ctx.world.register_system(
        PlayerInputSystem(
            input_provider=ctx.input_provider,
            memory_manager=ctx.memory_manager,
            player_entity_index=ctx.player_entity_index,
            crosshair_entity_index=ctx.crosshair_entity_index,
            center_xy=(center_x, center_y),
            crosshair_orbit_radius=judgment_ring_radius,
            dash_duration_seconds=config.dash_duration_seconds,
            dash_cooldown_seconds=config.dash_cooldown_seconds,
        )
    )
    ctx.world.register_system(spawner_system)
    ctx.world.register_system(
        ConvergenceRingSystem(
            audio_clock=ctx.audio_clock,
            memory_manager=ctx.memory_manager,
            spawn_radius=config.spawn_radius,
            judgment_ring_radius=judgment_ring_radius,
        )
    )
    # Polaridade + Parry Perfeito (opt-in por fase, `polarity_enabled`):
    # um UNICO flag liga as duas mecanicas -- reflete a decisao de design
    # de que sao inseparaveis no enunciado (o Parry E a defesa universal
    # contra pesadas justamente porque a Polaridade torna as basicas
    # sensiveis a cor).
    heavy_threat_type_id = (
        config.threat_type_ids.get("rhythm_threat_heavy") if config.polarity_enabled else None
    )
    # Notas Longas (Hold, opt-in por fase, `holds_enabled`): mutuamente
    # exclusivo com Polaridade/Parry por convencao de fase (ambos reusam
    # o mesmo threat_type "pesada", mas cada fase liga so UM dos dois).
    hold_threat_type_id = (
        config.threat_type_ids.get("rhythm_threat_heavy") if config.holds_enabled else None
    )
    ctx.world.register_system(
        JudgmentSystem(
            audio_clock=ctx.audio_clock,
            input_provider=ctx.input_provider,
            memory_manager=ctx.memory_manager,
            game_state=ctx.game_state,
            player_entity_index=ctx.player_entity_index,
            perfect_window_seconds=config.perfect_window_seconds,
            good_window_seconds=config.good_window_seconds,
            miss_window_seconds=config.miss_window_seconds,
            aim_tolerance_rad=math.radians(config.aim_tolerance_degrees),
            score_perfect=config.score_perfect,
            score_good=config.score_good,
            judgment_display_seconds=config.judgment_display_seconds,
            misfire_breaks_combo=config.misfire_breaks_combo,
            misfire_jam_seconds=config.misfire_jam_seconds,
            audio_engine=ctx.audio_engine,
            shot_sound_id=SFX_CANNON,
            jam_sound_id=SFX_CLICK,
            polarity_enabled=config.polarity_enabled,
            fire_alt_action_name=config.fire_alt_action_name,
            heavy_threat_type_id=heavy_threat_type_id,
            deflect_sound_id=SFX_DEFLECT,
            parry_sound_id=SFX_PARRY,
            reflected_collision_layer=REFLECTED_COLLISION_LAYER if config.polarity_enabled else None,
            reflected_collision_mask=THREAT_COLLISION_LAYER if config.polarity_enabled else None,
            hold_threat_type_id=hold_threat_type_id,
            hold_aim_tolerance_rad=math.radians(config.hold_aim_tolerance_degrees),
            hold_break_shake_px=config.hold_break_shake_px,
            rumble_low_freq=config.rumble_low_freq,
            rumble_high_freq=config.rumble_high_freq,
            rumble_duration_seconds=config.rumble_duration_seconds,
            hold_engage_sound_id=SFX_HOLD_ENGAGE,
            hold_break_sound_id=SFX_HOLD_BREAK,
        )
    )
    ctx.world.register_system(PhysicsSystem(ctx.memory_manager))
    ctx.world.register_system(collision_system)
    if config.polarity_enabled:
        ctx.world.register_system(
            ParryImpactSystem(
                collision_system=collision_system,
                memory_manager=ctx.memory_manager,
                game_state=ctx.game_state,
                player_entity_index=ctx.player_entity_index,
                center_xy=(center_x, center_y),
                spawn_radius=config.spawn_radius,
                score_per_kill=config.score_good,
            )
        )
    ctx.world.register_system(
        CoreDamageSystem(
            collision_system=collision_system,
            audio_clock=ctx.audio_clock,
            memory_manager=ctx.memory_manager,
            game_state=ctx.game_state,
            player_entity_index=ctx.player_entity_index,
            good_window_seconds=config.good_window_seconds,
            judgment_display_seconds=config.judgment_display_seconds,
            practice_mode=config.practice_mode,
        )
    )
    return (spawner_system,), collision_system


def _create_shockwave_pool(world: World, memory_manager: MemoryManager, pool_size: int) -> np.ndarray:
    """Pre-cria `pool_size` entidades de onda de choque (Pulso de
    Impacto), inicialmente INATIVAS (hitbox/sprite zerados pelo proprio
    `MemoryManager` -- camada/mascara 0 e alfa 0 sao o "invisivel/sem
    colisao" default de uma linha nova). Disciplina Zero-GC MAIS
    ESTRITA que o resto do jogo: este pool fixo e reaproveitado para
    sempre em round-robin pelo `ShockwaveSystem`, nunca criado/destruido
    durante a partida."""
    indices = np.zeros(pool_size, dtype=np.int64)
    for i in range(pool_size):
        indices[i] = unpack_index(world.create_entity("shockwave"))
    return indices


def _compose_survival_mode(ctx: _ModeContext):
    """MODO 2 -- Sobrevivencia Pura (estilo Just Shapes & Beats):
    movimento livre, paredes de som varrem a arena cruzando o centro na
    batida; sem botao de ataque -- julgamento 100% via CollisionSystem,
    Dash com i-frames atravessa. Ordem: SurvivalPlayer -> Spawner de
    varreduras -> Physics -> Collision -> SurvivalDamage."""
    config = ctx.config

    # espessura da barra por tipo: derivada dos meios-tamanhos radiais,
    # mais fina -- e SEMPRE atravessavel com um dash bem cronometrado
    bar_half_by_type = np.maximum(ctx.threat_half_by_type * 0.7, 5.0)

    spawner_system = SurvivalSpawnerSystem(
        audio_clock=ctx.audio_clock,
        memory_manager=ctx.memory_manager,
        scheduled_spawns=ctx.scheduled,
        hit_times=ctx.hit_times,
        threat_archetype_name="rhythm_threat_radial",
        arena_width=float(config.window_width),
        arena_height=float(config.window_height),
        bar_half_by_type=bar_half_by_type,
        threat_collision_layer=THREAT_COLLISION_LAYER,
        threat_collision_mask=PLAYER_COLLISION_LAYER,
        max_threats_per_frame=config.max_threats_per_frame,
        strike_seconds=config.survival_strike_seconds,
    )
    collision_system = CollisionSystem(
        ctx.memory_manager,
        transform_pool_name="transform",
        hitbox_pool_name="hitbox",
        max_pairs=MAX_COLLISION_PAIRS,
    )

    _hide_sprite(ctx.memory_manager, ctx.crosshair_entity_index)  # sem mira neste modo

    survival_player_system = SurvivalPlayerSystem(
        input_provider=ctx.input_provider,
        memory_manager=ctx.memory_manager,
        player_entity_index=ctx.player_entity_index,
        arena_width=float(config.window_width),
        arena_height=float(config.window_height),
        move_speed=config.survival_move_speed,
        dash_speed=config.survival_dash_speed,
        dash_duration_seconds=config.dash_duration_seconds,
        dash_cooldown_seconds=config.dash_cooldown_seconds,
        audio_clock=ctx.audio_clock,
        on_beat_window_seconds=config.dash_beat_window_seconds,
        audio_engine=ctx.audio_engine,
        offbeat_sound_id=SFX_CLICK,
    )
    ctx.world.register_system(survival_player_system)
    ctx.world.register_system(spawner_system)
    ctx.world.register_system(
        WallPhaseSystem(  # ANTES da colisao: a virada aviso->letal vale no frame do onset
            audio_clock=ctx.audio_clock,
            memory_manager=ctx.memory_manager,
            lethal_collision_layer=THREAT_COLLISION_LAYER,
            lethal_collision_mask=PLAYER_COLLISION_LAYER,
        )
    )
    ctx.world.register_system(PhysicsSystem(ctx.memory_manager))
    ctx.world.register_system(collision_system)
    ctx.world.register_system(
        GrazeSystem(
            memory_manager=ctx.memory_manager,
            game_state=ctx.game_state,
            player_entity_index=ctx.player_entity_index,
            graze_margin=config.graze_margin,
            fever_gain_per_graze=config.fever_gain_per_graze,
            fever_decay_per_second=config.fever_decay_per_second,
            fever_score_multiplier=config.fever_score_multiplier,
            graze_score_per_hit=config.graze_score_per_hit,
            audio_engine=ctx.audio_engine,
            graze_sound_id=SFX_GRAZE,
        )
    )
    shockwave_entity_indices = _create_shockwave_pool(
        ctx.world, ctx.memory_manager, config.shockwave_pool_size
    )
    ctx.world.register_system(
        ShockwaveSystem(
            collision_system=collision_system,
            memory_manager=ctx.memory_manager,
            game_state=ctx.game_state,
            survival_player_system=survival_player_system,
            player_entity_index=ctx.player_entity_index,
            shockwave_entity_indices=shockwave_entity_indices,
            min_radius=config.shockwave_min_radius,
            max_radius=config.shockwave_max_radius,
            duration_seconds=config.shockwave_duration_seconds,
            heavy_threat_type_id=config.threat_type_ids.get("rhythm_threat_heavy", -1),
            score_per_kill=config.score_good,
        )
    )
    ctx.world.register_system(
        SurvivalDamageSystem(
            collision_system=collision_system,
            audio_clock=ctx.audio_clock,
            memory_manager=ctx.memory_manager,
            game_state=ctx.game_state,
            player_entity_index=ctx.player_entity_index,
            score_survive=config.score_good,
            judgment_display_seconds=config.judgment_display_seconds,
            practice_mode=config.practice_mode,
        )
    )
    return (spawner_system,), collision_system


def lane_center_positions(config: HertzConfig) -> np.ndarray:
    """Posicoes X centrais das 4 colunas do Arcade 4K (compartilhado
    entre a composicao do modo e a decoracao de arena do adapter)."""
    center_x, _ = config.center_xy
    return np.array(
        [
            center_x + (lane - (LANE_COUNT_4K - 1) / 2.0) * config.lane_spacing
            for lane in range(LANE_COUNT_4K)
        ],
        dtype=np.float64,
    )


def _compose_lanes_mode(ctx: _ModeContext):
    """MODO 3 -- Arcade Classico 4K (estilo FNF/VSRG): 4 colunas fixas,
    notas caem ate a linha de julgamento, teclas D/F/J/K por coluna.
    Sem CollisionSystem: o julgamento e temporal por coluna. Ordem:
    Spawner de notas -> LaneJudgment -> Physics."""
    config = ctx.config
    judgment_line_y = config.window_height - config.judgment_line_offset
    lane_center_xs = lane_center_positions(config)
    lane_tints_rgb = np.array(
        [[255, 214, 64], [64, 255, 214], [167, 139, 250], [255, 80, 96]], dtype=np.uint8
    )

    # Notas de Scratch ("mesa do DJ"): funde clusters de pesadas
    # consecutivas (os "solos insanos" que a IA ja concentra num trecho
    # curto) numa UNICA nota longa -- pura interpretacao GAME-side, o
    # beatmap.json e o mapeador nao mudam nada.
    heavy_type_id = config.threat_type_ids.get("rhythm_threat_heavy", -1)
    scheduled_out, hit_times_out, is_hold_out, hold_end_out = build_lane_schedule_with_scratches(
        ctx.scheduled,
        ctx.hit_times,
        heavy_type_id,
        config.scratch_cluster_gap_seconds,
        config.scratch_min_cluster_size,
        config.scratch_hold_tail_seconds,
    )

    spawner_system = LaneNoteSpawnerSystem(
        audio_clock=ctx.audio_clock,
        memory_manager=ctx.memory_manager,
        scheduled_spawns=scheduled_out,
        hit_times=hit_times_out,
        threat_archetype_name="rhythm_threat_radial",
        lane_center_xs=lane_center_xs,
        spawn_y=-24.0,
        judgment_line_y=judgment_line_y,
        note_half_by_type=ctx.threat_half_by_type,
        lane_tints_rgb=lane_tints_rgb,
        max_threats_per_frame=config.max_threats_per_frame,
        is_hold_by_row=is_hold_out,
        hold_end_by_row=hold_end_out,
    )

    # nucleo e mira nao participam deste modo; receptores + rotulos de
    # tecla marcam a linha de julgamento (entidades de HUD comuns) --
    # os indices sao guardados para as "Pistas Dinamicas" reposicionarem
    # a linha inteira junto com as colunas.
    _hide_sprite(ctx.memory_manager, ctx.player_entity_index)
    _hide_sprite(ctx.memory_manager, ctx.crosshair_entity_index)
    receptor_entity_indices = np.zeros(LANE_COUNT_4K, dtype=np.int64)
    key_label_entity_indices = np.zeros(LANE_COUNT_4K, dtype=np.int64)
    for lane in range(LANE_COUNT_4K):
        receptor_entity_indices[lane] = _create_hud_sprite(
            ctx.world, ctx.memory_manager, TEX_LANE_RECEPTOR,
            float(lane_center_xs[lane]), judgment_line_y, layer_z=HUD_LAYER_Z - 1,
        )
        key_label_entity_indices[lane] = _create_hud_sprite(
            ctx.world, ctx.memory_manager, TEX_KEY_LABEL_BASE + lane,
            float(lane_center_xs[lane]), judgment_line_y + 46.0, layer_z=HUD_LAYER_Z - 1,
        )

    ctx.world.register_system(spawner_system)
    ctx.world.register_system(
        LaneJudgmentSystem(
            audio_clock=ctx.audio_clock,
            input_provider=ctx.input_provider,
            memory_manager=ctx.memory_manager,
            game_state=ctx.game_state,
            perfect_window_seconds=config.perfect_window_seconds,
            good_window_seconds=config.good_window_seconds,
            miss_window_seconds=config.miss_window_seconds,
            score_perfect=config.score_perfect,
            score_good=config.score_good,
            judgment_display_seconds=config.judgment_display_seconds,
            audio_engine=ctx.audio_engine,
            ghost_tap_sound_id=SFX_TAP,
        )
    )
    ctx.world.register_system(
        ScratchJudgmentSystem(
            audio_clock=ctx.audio_clock,
            input_provider=ctx.input_provider,
            memory_manager=ctx.memory_manager,
            game_state=ctx.game_state,
            min_energy=config.scratch_min_energy,
            judgment_display_seconds=config.judgment_display_seconds,
            score_perfect=config.score_perfect,
        )
    )
    # Pistas Dinamicas: o balanco reage aos MESMOS instantes que abrem
    # uma nota de Scratch (o "solo/glitch" do enunciado) -- nenhum campo
    # novo de beatmap, so reaproveita `hit_times_out` filtrado por
    # `is_hold_out`.
    trigger_times = hit_times_out[is_hold_out]
    ctx.world.register_system(
        LaneChoreographySystem(
            audio_clock=ctx.audio_clock,
            memory_manager=ctx.memory_manager,
            lane_center_xs=lane_center_xs,
            trigger_times=trigger_times,
            amplitude_px=config.lane_sway_amplitude_px,
            decay_per_second=config.lane_sway_decay_per_second,
            receptor_entity_indices=receptor_entity_indices,
            key_label_entity_indices=key_label_entity_indices,
        )
    )
    ctx.world.register_system(PhysicsSystem(ctx.memory_manager))
    return (spawner_system,), None


def _compose_hybrid_mode(ctx: _ModeContext):
    """MODO 4 -- Hibrido (Defensor + Sobrevivencia alternando por SECAO
    da musica): o beatmap e PARTICIONADO na composicao -- eventos de
    secoes pares viram ameacas radiais (atire na batida), os de secoes
    impares viram paredes de som (dashe atraves). Dois spawners
    coexistem, cada um consumindo APENAS a sua particao pre-filtrada
    (zero decisao de modo em runtime); os juizes se ignoram mutuamente
    via `mode_tag`. O jogador MOVE o corpo (WASD/dash, i-frames) e mira
    a torreta do nucleo com o mouse -- 'voce e o escudo movel do
    nucleo'. Ordem: SurvivalPlayer (corpo) -> PlayerInput (mira, sem
    dash) -> Spawner radial -> Spawner de varreduras -> Judgment ->
    Physics -> Collision -> CoreDamage -> SurvivalDamage."""
    config = ctx.config
    center_x, center_y = config.center_xy

    # particao por secao musical, sobre os tempos de IMPACTO (a janela
    # de spawn atravessa a fronteira de secao sem problema algum)
    section_index = np.floor_divide(ctx.hit_times, config.mixed_section_seconds).astype(np.int64)
    defender_rows = np.flatnonzero(section_index % 2 == 0)
    survival_rows = np.flatnonzero(section_index % 2 == 1)
    defender_scheduled = ctx.scheduled[defender_rows]
    defender_hits = ctx.hit_times[defender_rows]
    survival_scheduled = ctx.scheduled[survival_rows]
    survival_hits = ctx.hit_times[survival_rows]

    radial_spawner = RadialRhythmSpawnerSystem(
        audio_clock=ctx.audio_clock,
        memory_manager=ctx.memory_manager,
        scheduled_spawns=defender_scheduled,
        hit_times=defender_hits,
        threat_archetype_name="rhythm_threat_radial",
        center_xy=(center_x, center_y),
        spawn_radius=config.spawn_radius,
        core_half_extent=config.core_half_extent,
        lane_count=config.lane_count,
        threat_half_by_type=ctx.threat_half_by_type,
        threat_texture_by_type=ctx.threat_texture_by_type,
        threat_collision_layer=THREAT_COLLISION_LAYER,
        threat_collision_mask=PLAYER_COLLISION_LAYER,
        max_threats_per_frame=config.max_threats_per_frame,
        ring_archetype_name="convergence_ring",
        polarity_enabled=config.polarity_enabled,
    )
    wall_spawner = SurvivalSpawnerSystem(
        audio_clock=ctx.audio_clock,
        memory_manager=ctx.memory_manager,
        scheduled_spawns=survival_scheduled,
        hit_times=survival_hits,
        threat_archetype_name="rhythm_threat_radial",
        arena_width=float(config.window_width),
        arena_height=float(config.window_height),
        bar_half_by_type=np.maximum(ctx.threat_half_by_type * 0.7, 5.0),
        threat_collision_layer=THREAT_COLLISION_LAYER,
        threat_collision_mask=PLAYER_COLLISION_LAYER,
        max_threats_per_frame=config.max_threats_per_frame,
        strike_seconds=config.survival_strike_seconds,
    )
    collision_system = CollisionSystem(
        ctx.memory_manager,
        transform_pool_name="transform",
        hitbox_pool_name="hitbox",
        max_pairs=MAX_COLLISION_PAIRS,
    )

    judgment_ring_radius = config.core_half_extent + config.threat_half_extents.get(
        "rhythm_threat_basic", 10.0
    )
    survival_player_system = SurvivalPlayerSystem(
        input_provider=ctx.input_provider,
        memory_manager=ctx.memory_manager,
        player_entity_index=ctx.player_entity_index,
        arena_width=float(config.window_width),
        arena_height=float(config.window_height),
        move_speed=config.survival_move_speed,
        dash_speed=config.survival_dash_speed,
        dash_duration_seconds=config.dash_duration_seconds,
        dash_cooldown_seconds=config.dash_cooldown_seconds,
        audio_clock=ctx.audio_clock,
        on_beat_window_seconds=config.dash_beat_window_seconds,
        audio_engine=ctx.audio_engine,
        offbeat_sound_id=SFX_CLICK,
    )
    ctx.world.register_system(survival_player_system)
    ctx.world.register_system(
        PlayerInputSystem(
            input_provider=ctx.input_provider,
            memory_manager=ctx.memory_manager,
            player_entity_index=ctx.player_entity_index,
            crosshair_entity_index=ctx.crosshair_entity_index,
            center_xy=(center_x, center_y),
            crosshair_orbit_radius=judgment_ring_radius,
            dash_duration_seconds=config.dash_duration_seconds,
            dash_cooldown_seconds=config.dash_cooldown_seconds,
            manage_dash=False,  # dash/i-frames/tint pertencem ao SurvivalPlayer
        )
    )
    ctx.world.register_system(radial_spawner)
    ctx.world.register_system(wall_spawner)
    ctx.world.register_system(
        ConvergenceRingSystem(
            audio_clock=ctx.audio_clock,
            memory_manager=ctx.memory_manager,
            spawn_radius=config.spawn_radius,
            judgment_ring_radius=judgment_ring_radius,
        )
    )
    ctx.world.register_system(
        WallPhaseSystem(  # ANTES da colisao: virada aviso->letal vale no frame do onset
            audio_clock=ctx.audio_clock,
            memory_manager=ctx.memory_manager,
            lethal_collision_layer=THREAT_COLLISION_LAYER,
            lethal_collision_mask=PLAYER_COLLISION_LAYER,
        )
    )
    heavy_threat_type_id = (
        config.threat_type_ids.get("rhythm_threat_heavy") if config.polarity_enabled else None
    )
    ctx.world.register_system(
        JudgmentSystem(
            audio_clock=ctx.audio_clock,
            input_provider=ctx.input_provider,
            memory_manager=ctx.memory_manager,
            game_state=ctx.game_state,
            player_entity_index=ctx.player_entity_index,
            perfect_window_seconds=config.perfect_window_seconds,
            good_window_seconds=config.good_window_seconds,
            miss_window_seconds=config.miss_window_seconds,
            aim_tolerance_rad=math.radians(config.aim_tolerance_degrees),
            score_perfect=config.score_perfect,
            score_good=config.score_good,
            judgment_display_seconds=config.judgment_display_seconds,
            misfire_breaks_combo=config.misfire_breaks_combo,
            misfire_jam_seconds=config.misfire_jam_seconds,
            audio_engine=ctx.audio_engine,
            shot_sound_id=SFX_CANNON,
            jam_sound_id=SFX_CLICK,
            polarity_enabled=config.polarity_enabled,
            fire_alt_action_name=config.fire_alt_action_name,
            heavy_threat_type_id=heavy_threat_type_id,
            deflect_sound_id=SFX_DEFLECT,
            parry_sound_id=SFX_PARRY,
            reflected_collision_layer=REFLECTED_COLLISION_LAYER if config.polarity_enabled else None,
            reflected_collision_mask=THREAT_COLLISION_LAYER if config.polarity_enabled else None,
        )
    )
    ctx.world.register_system(PhysicsSystem(ctx.memory_manager))
    ctx.world.register_system(collision_system)
    ctx.world.register_system(
        GrazeSystem(
            memory_manager=ctx.memory_manager,
            game_state=ctx.game_state,
            player_entity_index=ctx.player_entity_index,
            graze_margin=config.graze_margin,
            fever_gain_per_graze=config.fever_gain_per_graze,
            fever_decay_per_second=config.fever_decay_per_second,
            fever_score_multiplier=config.fever_score_multiplier,
            graze_score_per_hit=config.graze_score_per_hit,
            audio_engine=ctx.audio_engine,
            graze_sound_id=SFX_GRAZE,
        )
    )
    shockwave_entity_indices = _create_shockwave_pool(
        ctx.world, ctx.memory_manager, config.shockwave_pool_size
    )
    ctx.world.register_system(
        ShockwaveSystem(
            collision_system=collision_system,
            memory_manager=ctx.memory_manager,
            game_state=ctx.game_state,
            survival_player_system=survival_player_system,
            player_entity_index=ctx.player_entity_index,
            shockwave_entity_indices=shockwave_entity_indices,
            min_radius=config.shockwave_min_radius,
            max_radius=config.shockwave_max_radius,
            duration_seconds=config.shockwave_duration_seconds,
            heavy_threat_type_id=config.threat_type_ids.get("rhythm_threat_heavy", -1),
            score_per_kill=config.score_good,
        )
    )
    ctx.world.register_system(
        CoreDamageSystem(
            collision_system=collision_system,
            audio_clock=ctx.audio_clock,
            memory_manager=ctx.memory_manager,
            game_state=ctx.game_state,
            player_entity_index=ctx.player_entity_index,
            good_window_seconds=config.good_window_seconds,
            judgment_display_seconds=config.judgment_display_seconds,
            practice_mode=config.practice_mode,
        )
    )
    if config.polarity_enabled:
        ctx.world.register_system(
            ParryImpactSystem(
                collision_system=collision_system,
                memory_manager=ctx.memory_manager,
                game_state=ctx.game_state,
                player_entity_index=ctx.player_entity_index,
                center_xy=(center_x, center_y),
                spawn_radius=config.spawn_radius,
                score_per_kill=config.score_good,
            )
        )
    ctx.world.register_system(
        SurvivalDamageSystem(
            collision_system=collision_system,
            audio_clock=ctx.audio_clock,
            memory_manager=ctx.memory_manager,
            game_state=ctx.game_state,
            player_entity_index=ctx.player_entity_index,
            score_survive=config.score_good,
            judgment_display_seconds=config.judgment_display_seconds,
            practice_mode=config.practice_mode,
        )
    )
    return (radial_spawner, wall_spawner), collision_system


MODE_COMPOSERS = {
    "defender": _compose_defender_mode,
    "survival": _compose_survival_mode,
    "lanes": _compose_lanes_mode,
    "hybrid": _compose_hybrid_mode,
}
"""Registro de estrategias de modo: `HertzConfig.game_mode` (por fase,
via `overrides` em stages.json) -> funcao que registra os sistemas do
modo e retorna `(spawners, collision_system|None)`. O
'GameModeStrategy' da arquitetura, resolvido em tempo de composicao."""


def compose_world(
    config: HertzConfig,
    input_provider: IInputProvider,
    audio_clock: IAudioClock,
    tutorial_steps: tuple = (),
    stage_ordinal: int = 0,
    audio_engine=None,
) -> ComposedGame:
    """Composicao PURA (sem pygame): pools, arquetipos, entidades
    persistentes (nucleo, mira, HUD), beatmap e a ordem exata dos
    sistemas. Backends concretos entram por parametro -- os testes
    injetam Null*, o `build()` injeta Pygame*.

    `tutorial_steps` (da definicao da fase) liga o modo tutorial: cria o
    sprite-banner de instrucoes e registra o `TutorialSystem`;
    `stage_ordinal` enderessa a faixa de texturas de texto da fase.
    """
    center_x, center_y = config.center_xy

    # 2. MemoryManager: pools genericas do nucleo + pools do produto.
    memory_manager = MemoryManager(entity_capacity=config.entity_capacity)
    for pool_name, dtype in COMPONENT_SCHEMAS.items():
        memory_manager.create_pool(pool_name, dtype)
    memory_manager.create_pool("rhythm_threat", RHYTHM_THREAT_DTYPE, dense_capacity=config.max_threats)
    memory_manager.create_pool("player_state", PLAYER_STATE_DTYPE, dense_capacity=4)
    memory_manager.create_pool(
        "convergence_ring", CONVERGENCE_RING_DTYPE, dense_capacity=config.max_threats
    )
    memory_manager.create_pool(
        "shockwave", SHOCKWAVE_DTYPE, dense_capacity=max(config.shockwave_pool_size, 1)
    )

    world = World(memory_manager)
    world.register_archetype(
        "rhythm_threat_radial", ("transform", "velocity", "hitbox", "sprite", "rhythm_threat")
    )
    world.register_archetype("convergence_ring", ("transform", "sprite", "convergence_ring"))
    world.register_archetype("player_core", ("transform", "hitbox", "sprite", "player_state"))
    world.register_archetype("hud_sprite", ("transform", "sprite"))
    world.register_archetype("shockwave", ("transform", "hitbox", "sprite", "shockwave"))

    # 3. Beatmap: tempos de IMPACTO do JSON viram tempos de SPAWN
    #    (deslocados por approach_seconds) para o cursor do spawner;
    #    o array original de impacto segue paralelo, linha a linha.
    scheduled = BeatmapLoader(config.threat_type_ids).load(Path(config.beatmap_path))
    hit_times = scheduled["timestamp_seconds"].copy()
    if config.practice_mode:
        # Modo Treino: reduz a densidade de onsets ANTES de qualquer
        # spawner ver o beatmap -- pura interpretacao game-side, o
        # arquivo original no disco nunca muda.
        scheduled, hit_times = thin_schedule_for_practice(
            scheduled, hit_times, config.practice_density_keep_fraction
        )
    np.subtract(scheduled["timestamp_seconds"], config.approach_seconds, out=scheduled["timestamp_seconds"])
    np.maximum(scheduled["timestamp_seconds"], 0.0, out=scheduled["timestamp_seconds"])

    # Afinacao por tipo de ameaca (data-driven), resolvida em arrays
    # indexados por threat_type para consumo escalar no spawn.
    max_type_id = max(config.threat_type_ids.values())
    threat_half_by_type = np.full(max_type_id + 1, 10.0, dtype=np.float64)
    threat_texture_by_type = np.full(max_type_id + 1, TEX_THREAT_BASIC, dtype=np.int64)
    for type_name, type_id in config.threat_type_ids.items():
        threat_half_by_type[type_id] = config.threat_half_extents.get(type_name, 10.0)
        threat_texture_by_type[type_id] = _THREAT_TEXTURE_BY_NAME.get(type_name, TEX_THREAT_BASIC)

    game_state = GameState(max_health=config.max_health)

    # Entidades persistentes -----------------------------------------
    player_entity_index = _create_player_core(world, memory_manager, config)
    crosshair_entity_index = _create_hud_sprite(
        world, memory_manager, TEX_CROSSHAIR, center_x, center_y, layer_z=HUD_LAYER_Z + 1
    )
    (
        score_digit_indices,
        combo_digit_indices,
        judgment_word_index,
        health_pip_indices,
        score_label_index,
        combo_label_index,
    ) = _create_hud(world, memory_manager, config)

    # 4. Ordem EXATA de execucao dos sistemas, escolhida pela ESTRATEGIA
    #    DE MODO (`MODE_COMPOSERS`): a IA dita o tempo (mesmo beatmap);
    #    o modo dita a interpretacao espacial/de input. A estrategia e
    #    resolvida UMA vez aqui na composicao -- zero branch por evento
    #    no hot-path.
    mode_composer = MODE_COMPOSERS.get(config.game_mode)
    if mode_composer is None:
        raise ValueError(
            f"game_mode desconhecido: {config.game_mode!r} (validos: {sorted(MODE_COMPOSERS)})"
        )
    context = _ModeContext(
        config=config,
        world=world,
        memory_manager=memory_manager,
        input_provider=input_provider,
        audio_clock=audio_clock,
        audio_engine=audio_engine,
        game_state=game_state,
        scheduled=scheduled,
        hit_times=hit_times,
        threat_half_by_type=threat_half_by_type,
        threat_texture_by_type=threat_texture_by_type,
        player_entity_index=player_entity_index,
        crosshair_entity_index=crosshair_entity_index,
    )
    spawner_systems, collision_system = mode_composer(context)
    if tutorial_steps:
        banner_entity_index = _create_hud_sprite(
            world, memory_manager, 0, center_x, 96.0, alpha=0
        )
        step_until_seconds = np.array(
            [step["until_seconds"] for step in tutorial_steps], dtype=np.float64
        )
        texture_base = TEX_TUTORIAL_BASE + stage_ordinal * MAX_TUTORIAL_STEPS
        step_texture_ids = np.arange(texture_base, texture_base + len(tutorial_steps), dtype=np.int64)
        world.register_system(
            TutorialSystem(
                audio_clock=audio_clock,
                memory_manager=memory_manager,
                banner_entity_index=banner_entity_index,
                step_until_seconds=step_until_seconds,
                step_texture_ids=step_texture_ids,
            )
        )

    # Screen Shake: decaimento comum aos 3 modos, independente de quem
    # aciona `GameState.trigger_shake` (Hold quebrado no Defensor hoje;
    # qualquer mecanica futura de Sobrevivencia/Arcade so precisa chamar
    # o mesmo metodo, sem registrar nada extra aqui).
    world.register_system(CameraShakeSystem(game_state, config.shake_decay_per_second))

    world.register_system(
        UIRenderSystem(
            memory_manager=memory_manager,
            game_state=game_state,
            score_digit_entity_indices=score_digit_indices,
            combo_digit_entity_indices=combo_digit_indices,
            judgment_word_entity_index=judgment_word_index,
            health_pip_entity_indices=health_pip_indices,
            show_health_pips=(config.game_mode != "lanes"),
            # Flow State ("vidro quebrado") e exclusivo do Arcade 4K --
            # nos demais modos o limiar fica None e o UIRenderSystem
            # nunca entra no ramo de ocultacao total.
            flow_combo_threshold=(config.flow_combo_threshold if config.game_mode == "lanes" else None),
            score_label_entity_index=score_label_index,
            combo_label_entity_index=combo_label_index,
        )
    )

    return ComposedGame(
        world=world,
        memory_manager=memory_manager,
        game_state=game_state,
        spawner_systems=spawner_systems,
        collision_system=collision_system,
        player_entity_index=player_entity_index,
        crosshair_entity_index=crosshair_entity_index,
    )


def _create_player_core(world: World, memory_manager: MemoryManager, config: HertzConfig) -> int:
    """Cria a entidade do nucleo no centro da arena e retorna seu indice."""
    center_x, center_y = config.center_xy
    packed = world.create_entity("player_core")
    entity_index = unpack_index(packed)

    transform_pool = memory_manager.get_pool("transform")
    row = transform_pool.dense_row_of(entity_index)
    view = transform_pool.active_view()
    view["position_x"][row] = center_x
    view["position_y"][row] = center_y
    view["scale_x"][row] = config.core_half_extent / 8.0
    view["scale_y"][row] = config.core_half_extent / 8.0

    hitbox_pool = memory_manager.get_pool("hitbox")
    row = hitbox_pool.dense_row_of(entity_index)
    view = hitbox_pool.active_view()
    view["half_width"][row] = config.core_half_extent
    view["half_height"][row] = config.core_half_extent
    view["collision_layer"][row] = PLAYER_COLLISION_LAYER
    view["collision_mask"][row] = THREAT_COLLISION_LAYER

    sprite_pool = memory_manager.get_pool("sprite")
    row = sprite_pool.dense_row_of(entity_index)
    view = sprite_pool.active_view()
    view["texture_id"][row] = TEX_PLAYER_CORE
    view["tint_r"][row] = 240
    view["tint_g"][row] = 240
    view["tint_b"][row] = 255
    view["tint_a"][row] = 255
    view["layer_z"][row] = 10

    return entity_index


def _create_hud_sprite(
    world: World,
    memory_manager: MemoryManager,
    texture_id: int,
    position_x: float,
    position_y: float,
    layer_z: int = HUD_LAYER_Z,
    alpha: int = 255,
) -> int:
    """Cria uma entidade de HUD (`transform` + `sprite`) com posicao fixa
    escrita UMA unica vez aqui; retorna o indice da entidade."""
    packed = world.create_entity("hud_sprite")
    entity_index = unpack_index(packed)

    transform_pool = memory_manager.get_pool("transform")
    row = transform_pool.dense_row_of(entity_index)
    view = transform_pool.active_view()
    view["position_x"][row] = position_x
    view["position_y"][row] = position_y
    view["scale_x"][row] = 1.0
    view["scale_y"][row] = 1.0

    sprite_pool = memory_manager.get_pool("sprite")
    row = sprite_pool.dense_row_of(entity_index)
    view = sprite_pool.active_view()
    view["texture_id"][row] = texture_id
    view["tint_r"][row] = 255
    view["tint_g"][row] = 255
    view["tint_b"][row] = 255
    view["tint_a"][row] = alpha
    view["layer_z"][row] = layer_z

    return entity_index


def _create_hud(world: World, memory_manager: MemoryManager, config: HertzConfig):
    """Cria todas as entidades de HUD com layout fixo e devolve os
    arrays de indices (digito menos significativo primeiro) consumidos
    pelo `UIRenderSystem`."""
    center_x, center_y = config.center_xy
    digit_advance = 24.0

    score_label_index = _create_hud_sprite(world, memory_manager, TEX_LABEL_SCORE, 64.0, 36.0)
    score_digit_indices = np.zeros(SCORE_DIGITS, dtype=np.int64)
    score_right_x = 120.0 + SCORE_DIGITS * digit_advance
    for i in range(SCORE_DIGITS):
        score_digit_indices[i] = _create_hud_sprite(
            world, memory_manager, 0, score_right_x - i * digit_advance, 38.0, alpha=0
        )

    combo_label_index = _create_hud_sprite(
        world, memory_manager, TEX_LABEL_COMBO, center_x - 76.0, center_y + 132.0
    )
    combo_digit_indices = np.zeros(COMBO_DIGITS, dtype=np.int64)
    combo_right_x = center_x + 84.0
    for i in range(COMBO_DIGITS):
        combo_digit_indices[i] = _create_hud_sprite(
            world, memory_manager, 0, combo_right_x - i * digit_advance, 132.0 + center_y, alpha=0
        )

    judgment_word_index = _create_hud_sprite(
        world, memory_manager, 0, center_x, center_y - 130.0, alpha=0
    )

    health_pip_indices = np.zeros(config.max_health, dtype=np.int64)
    for i in range(config.max_health):
        health_pip_indices[i] = _create_hud_sprite(
            world, memory_manager, TEX_HEALTH_PIP, config.window_width - 44.0 - i * 26.0, 40.0
        )

    return (
        score_digit_indices,
        combo_digit_indices,
        judgment_word_index,
        health_pip_indices,
        score_label_index,
        combo_label_index,
    )


class RhythmCompositionRoot:
    """Composicao CONCRETA (Pygame) do Hertz & Beats -- ver docstring do
    modulo para a sequencia exata. As FASES (`data/stages/stages.json`)
    e o fluxo de partida (menu/pausa/derrota/resultados) vivem no
    `HertzGameLoop`, que recompoe o `World` via `compose_world` a cada
    fase iniciada/reiniciada."""

    def __init__(self, config: HertzConfig) -> None:
        """Guarda `config`; nada pesado e construido antes de `build()`."""
        self._config = config

    def build(self):
        """Monta o jogo completo e retorna `(game_loop, audio_engine)`
        prontos para `run()` (o menu de fases assume a partir dai)."""
        # Imports locais: manter `compose_world` importavel em ambiente
        # headless sem pygame instalado/inicializado.
        from hertzbeats.adapters.hb_pygame_audio_engine import HBPygameAudioEngine
        from hertzbeats.adapters.hb_pygame_input_provider import HBPygameInputProvider
        from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
        from hertzbeats.adapters.texture_bank import (
            build_and_register_hud_textures,
            build_and_register_overlay_surfaces,
            build_and_register_tutorial_textures,
        )
        from hertzbeats.audio.demo_track_synth import ensure_track
        from hertzbeats.audio.sfx_synth import (
            SFX_CANNON,
            SFX_CLICK,
            SFX_DEFLECT,
            SFX_GRAZE,
            SFX_HOLD_BREAK,
            SFX_HOLD_ENGAGE,
            SFX_PARRY,
            SFX_TAP,
            ensure_sfx,
        )
        from hertzbeats.bootstrap.hertz_game_loop import HertzGameLoop
        from hertzbeats.config import fit_config_to_display
        from hertzbeats.stages import load_stages

        # A geometria toda encolhe junto se o monitor nao comportar a
        # janela configurada (ex.: 960x960 numa tela de 768 de altura).
        display_width, display_height = HBPygameRenderer.probe_display_size()
        config = fit_config_to_display(self._config, display_width, display_height)
        self._config = config
        center_x, center_y = config.center_xy

        # 1. Backends concretos. (A decoracao de arena e POR MODO,
        # sincronizada pelo HertzGameLoop a cada troca de fase.)
        renderer = HBPygameRenderer()
        renderer.initialize(config.window_width, config.window_height, config.window_title)
        renderer.set_window_icon("assets/icon.png")

        input_provider = HBPygameInputProvider()
        input_provider.load_bindings(config.input_bindings_path)
        input_provider.configure_aim_origin(center_x, center_y)

        from hertzbeats.user_settings import load_user_latency

        audio_engine = HBPygameAudioEngine()
        audio_clock = audio_engine.get_clock()
        # calibracao local do jogador (teclas +/- em jogo, persistida)
        # tem prioridade sobre o default da config
        saved_latency = load_user_latency()
        audio_clock.calibrate_latency(
            saved_latency if saved_latency is not None else config.output_latency_seconds
        )

        # SFX sintetizados deterministicamente (Gun Sync, misfire, ghost
        # tap): garantidos e PRE-CARREGADOS aqui -- o primeiro
        # play_one_shot em jogo nao pode pagar o custo de I/O e sair fora
        # do tempo.
        ensure_sfx()
        for sound_id in (
            SFX_CANNON, SFX_CLICK, SFX_TAP, SFX_DEFLECT, SFX_PARRY, SFX_GRAZE,
            SFX_HOLD_ENGAGE, SFX_HOLD_BREAK,
        ):
            audio_engine.preload_one_shot(sound_id)

        # 2-4. Fases data-driven + musicas do jogador + fluxo de partida.
        # O HertzGameLoop ja compoe a fase 0 (via `compose_world`) para o
        # fundo do menu. Todas as faixas sao garantidas AQUI (tela de
        # carregamento) para nao haver hitch no primeiro start de fase;
        # musicas novas em `musicas/` passam pela IA agora, com aviso na
        # janela (cacheado: proximas aberturas sao instantaneas).
        from hertzbeats.music_library import scan_user_songs

        stages = load_stages(config.stages_path)
        for stage in stages:
            if stage.track_path:
                ensure_track(stage.track_path, stage.synth)
        user_songs = scan_user_songs(
            on_progress=lambda name: renderer.show_loading_message(
                f"Analisando '{name}' com a IA (so na primeira vez)..."
            )
        )
        stages = stages + user_songs
        game_loop = HertzGameLoop(
            base_config=config,
            stages=stages,
            renderer=renderer,
            input_provider=input_provider,
            audio_engine=audio_engine,
            audio_clock=audio_clock,
        )

        # Texturas de HUD, overlays e textos de tutorial pre-renderizados
        # (tela de carregamento).
        build_and_register_hud_textures(renderer)
        build_and_register_overlay_surfaces(renderer, stages)
        build_and_register_tutorial_textures(renderer, stages)

        return game_loop, audio_engine
