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

from hertzbeats.components.schemas import PLAYER_STATE_DTYPE, RHYTHM_THREAT_DTYPE
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
from hertzbeats.systems.core_damage_system import CoreDamageSystem
from hertzbeats.systems.judgment_system import JudgmentSystem
from hertzbeats.systems.player_input_system import PlayerInputSystem
from hertzbeats.systems.radial_spawner_system import RadialRhythmSpawnerSystem
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
        "spawner_system",
        "collision_system",
        "player_entity_index",
        "crosshair_entity_index",
    )

    def __init__(
        self,
        world: World,
        memory_manager: MemoryManager,
        game_state: GameState,
        spawner_system: RadialRhythmSpawnerSystem,
        collision_system: CollisionSystem,
        player_entity_index: int,
        crosshair_entity_index: int,
    ) -> None:
        self.world = world
        self.memory_manager = memory_manager
        self.game_state = game_state
        self.spawner_system = spawner_system
        self.collision_system = collision_system
        self.player_entity_index = player_entity_index
        self.crosshair_entity_index = crosshair_entity_index


def compose_world(
    config: HertzConfig,
    input_provider: IInputProvider,
    audio_clock: IAudioClock,
    tutorial_steps: tuple = (),
    stage_ordinal: int = 0,
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

    world = World(memory_manager)
    world.register_archetype(
        "rhythm_threat_radial", ("transform", "velocity", "hitbox", "sprite", "rhythm_threat")
    )
    world.register_archetype("player_core", ("transform", "hitbox", "sprite", "player_state"))
    world.register_archetype("hud_sprite", ("transform", "sprite"))

    # 3. Beatmap: tempos de IMPACTO do JSON viram tempos de SPAWN
    #    (deslocados por approach_seconds) para o cursor do spawner;
    #    o array original de impacto segue paralelo, linha a linha.
    scheduled = BeatmapLoader(config.threat_type_ids).load(Path(config.beatmap_path))
    hit_times = scheduled["timestamp_seconds"].copy()
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
    score_digit_indices, combo_digit_indices, judgment_word_index, health_pip_indices = _create_hud(
        world, memory_manager, config
    )

    # 4. Ordem EXATA de execucao dos sistemas ------------------------
    spawner_system = RadialRhythmSpawnerSystem(
        audio_clock=audio_clock,
        memory_manager=memory_manager,
        scheduled_spawns=scheduled,
        hit_times=hit_times,
        threat_archetype_name="rhythm_threat_radial",
        center_xy=(center_x, center_y),
        spawn_radius=config.spawn_radius,
        core_half_extent=config.core_half_extent,
        lane_count=config.lane_count,
        threat_half_by_type=threat_half_by_type,
        threat_texture_by_type=threat_texture_by_type,
        threat_collision_layer=THREAT_COLLISION_LAYER,
        threat_collision_mask=PLAYER_COLLISION_LAYER,
        max_threats_per_frame=config.max_threats_per_frame,
    )
    collision_system = CollisionSystem(
        memory_manager,
        transform_pool_name="transform",
        hitbox_pool_name="hitbox",
        max_pairs=MAX_COLLISION_PAIRS,
    )

    world.register_system(
        PlayerInputSystem(
            input_provider=input_provider,
            memory_manager=memory_manager,
            player_entity_index=player_entity_index,
            crosshair_entity_index=crosshair_entity_index,
            center_xy=(center_x, center_y),
            crosshair_orbit_radius=config.core_half_extent + 26.0,
            dash_duration_seconds=config.dash_duration_seconds,
            dash_cooldown_seconds=config.dash_cooldown_seconds,
        )
    )
    world.register_system(spawner_system)
    world.register_system(
        JudgmentSystem(
            audio_clock=audio_clock,
            input_provider=input_provider,
            memory_manager=memory_manager,
            game_state=game_state,
            player_entity_index=player_entity_index,
            perfect_window_seconds=config.perfect_window_seconds,
            good_window_seconds=config.good_window_seconds,
            miss_window_seconds=config.miss_window_seconds,
            aim_tolerance_rad=math.radians(config.aim_tolerance_degrees),
            score_perfect=config.score_perfect,
            score_good=config.score_good,
            judgment_display_seconds=config.judgment_display_seconds,
        )
    )
    world.register_system(PhysicsSystem(memory_manager))
    world.register_system(collision_system)
    world.register_system(
        CoreDamageSystem(
            collision_system=collision_system,
            audio_clock=audio_clock,
            memory_manager=memory_manager,
            game_state=game_state,
            player_entity_index=player_entity_index,
            good_window_seconds=config.good_window_seconds,
            judgment_display_seconds=config.judgment_display_seconds,
        )
    )
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

    world.register_system(
        UIRenderSystem(
            memory_manager=memory_manager,
            game_state=game_state,
            score_digit_entity_indices=score_digit_indices,
            combo_digit_entity_indices=combo_digit_indices,
            judgment_word_entity_index=judgment_word_index,
            health_pip_entity_indices=health_pip_indices,
        )
    )

    return ComposedGame(
        world=world,
        memory_manager=memory_manager,
        game_state=game_state,
        spawner_system=spawner_system,
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

    _create_hud_sprite(world, memory_manager, TEX_LABEL_SCORE, 64.0, 36.0)
    score_digit_indices = np.zeros(SCORE_DIGITS, dtype=np.int64)
    score_right_x = 120.0 + SCORE_DIGITS * digit_advance
    for i in range(SCORE_DIGITS):
        score_digit_indices[i] = _create_hud_sprite(
            world, memory_manager, 0, score_right_x - i * digit_advance, 38.0, alpha=0
        )

    _create_hud_sprite(world, memory_manager, TEX_LABEL_COMBO, center_x - 76.0, center_y + 132.0)
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

    return score_digit_indices, combo_digit_indices, judgment_word_index, health_pip_indices


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
        from hertzbeats.bootstrap.hertz_game_loop import HertzGameLoop
        from hertzbeats.stages import load_stages

        config = self._config
        center_x, center_y = config.center_xy

        # 1. Backends concretos.
        renderer = HBPygameRenderer()
        renderer.initialize(config.window_width, config.window_height, config.window_title)
        renderer.set_window_icon("assets/icon.png")
        renderer.configure_playfield(
            center_x,
            center_y,
            config.spawn_radius,
            config.core_half_extent + config.threat_half_extents.get("rhythm_threat_basic", 10.0),
        )

        input_provider = HBPygameInputProvider()
        input_provider.load_bindings(config.input_bindings_path)
        input_provider.configure_aim_origin(center_x, center_y)

        audio_engine = HBPygameAudioEngine()
        audio_clock = audio_engine.get_clock()
        audio_clock.calibrate_latency(config.output_latency_seconds)

        # 2-4. Fases data-driven + fluxo de partida. O HertzGameLoop ja
        # compoe a fase 0 (via `compose_world`) para o fundo do menu.
        stages = load_stages(config.stages_path)
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
