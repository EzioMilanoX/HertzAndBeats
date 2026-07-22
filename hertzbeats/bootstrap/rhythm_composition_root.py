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

import json
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
    SFX_BOMB,
    SFX_CANNON,
    SFX_CANNON_VARIANTS,
    SFX_CLICK,
    SFX_DEFLECT,
    SFX_HEAL,
    SFX_HOLD_BREAK,
    SFX_HOLD_ENGAGE,
    SFX_MISS,
    SFX_NOTE_HIT_VARIANTS,
    SFX_PARRY,
    SFX_SHIELD_BREAK,
    SFX_TAP,
)
from hertzbeats.components.schemas import PLAYER_STATE_DTYPE, RHYTHM_THREAT_DTYPE
from hertzbeats.lane_scratch_clustering import build_lane_schedule_with_scratches
from hertzbeats.modchart import (
    parse_reverse_scroll_events,
    parse_swap_events,
    parse_vision_tunnel_events,
)
from hertzbeats.practice_thinning import thin_schedule_for_practice
from hertzbeats.systems.camera_shake_system import CameraShakeSystem
from hertzbeats.systems.convergence_ring_system import (
    CONVERGENCE_RING_DTYPE,
    ConvergenceRingSystem,
)
from hertzbeats.systems.distraction_system import (
    DISTRACTION_DTYPE,
    DistractionSystem,
    parse_distraction_events,
)
from hertzbeats.systems.lane_choreography_system import LaneChoreographySystem
from hertzbeats.systems.orbital_capture_system import OrbitalCaptureSystem
from hertzbeats.systems.orbital_eclipse_system import OrbitalEclipseSystem
from hertzbeats.systems.parry_impact_system import (
    REFLECTED_COLLISION_LAYER,
    SHIELD_COLLISION_LAYER,
    ParryImpactSystem,
)
from hertzbeats.systems.scratch_judgment_system import ScratchJudgmentSystem
from hertzbeats.systems.shockwave_system import SHOCKWAVE_DTYPE, ShockwaveSystem
from hertzbeats.systems.spark_system import SparkSystem
from hertzbeats.components.texture_ids import (
    MAX_TUTORIAL_STEPS,
    TEX_CROSSHAIR,
    TEX_HEALTH_PIP,
    TEX_LABEL_COMBO,
    TEX_LABEL_SCORE,
    TEX_ORBITAL_ECLIPSE,
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
from hertzbeats.systems.reverse_scroll_system import ReverseScrollSystem
from hertzbeats.systems.tutorial_system import TutorialSystem
from hertzbeats.systems.ui_render_system import UIRenderSystem
from hertzbeats.systems.vision_tunnel_system import VisionTunnelSystem
from hertzbeats.systems.visual_modifier_system import VisualModifierSystem

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
        "lane_choreography_system",
        "lane_geometry_y",
        "spark_system",
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
        lane_choreography_system=None,
        lane_geometry_y=None,
        spark_system=None,
    ) -> None:
        self.world = world
        self.memory_manager = memory_manager
        self.game_state = game_state
        self.spawner_systems = spawner_systems
        self.collision_system = collision_system
        self.player_entity_index = player_entity_index
        self.crosshair_entity_index = crosshair_entity_index
        self.lane_choreography_system = lane_choreography_system
        """`LaneChoreographySystem` da fase (Modcharts + Pistas
        Dinamicas) quando `game_mode == "lanes"`; `None` nos demais
        modos. Exposto para o `HertzGameLoop` sincronizar a decoracao
        de fundo (`renderer.set_playfield`) com a posicao ATUAL das
        colunas a cada frame."""
        self.lane_geometry_y = lane_geometry_y
        """Array `[spawn_y, judgment_line_y]` MUTAVEL (mesma identidade
        lida pelo `LaneNoteSpawnerSystem`/escrita pelo
        `ReverseScrollSystem`) quando `game_mode == "lanes"`; `None` nos
        demais modos. Exposto para o `HertzGameLoop` sincronizar a linha
        de julgamento do fundo com a Inversao de Gravidade."""
        self.spark_system = spark_system
        """Juice Visual -- `SparkSystem` da fase quando `game_mode ==
        "defender"` (`None` no Arcade 4K, que nao tem o conceito de mira/
        crosshair que ancora a rajada). Exposto para o `HertzGameLoop`
        ler `render_arrays()` todo frame e publicar no renderer
        (`_sync_sparks`)."""

    @property
    def spawner_system(self):
        """Atalho de conveniencia: o spawner principal (todo modo tem
        exatamente um -- ver `spawner_systems`)."""
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
        "modchart_events",
        "effective_score_perfect",
        "effective_score_good",
        "lane_choreography_system",
        "lane_geometry_y",
        "spark_system",
    )

    _OPTIONAL_SLOTS = frozenset({"lane_choreography_system", "lane_geometry_y", "spark_system"})
    """Slots preenchidos DEPOIS da construcao (pela propria estrategia
    de modo, ex.: `_compose_lanes_mode` grava `lane_choreography_system`/
    `lane_geometry_y` de volta no `ctx`, `_compose_defender_mode` grava
    `spark_system`) -- unicos que podem faltar em `kwargs`."""

    def __init__(self, **kwargs) -> None:
        for name in self.__slots__:
            if name in self._OPTIONAL_SLOTS:
                setattr(self, name, kwargs.get(name))
            else:
                setattr(self, name, kwargs[name])


def _read_beatmap_bpm(beatmap_path: str, default_bpm: float = 120.0) -> float:
    """Heartbeat (Juice Visual): le SO o campo `bpm` (raiz obrigatoria do
    schema, ver `BeatmapLoader`/`REQUIRED_ROOT_FIELDS`) do proprio
    `beatmap.json` da fase -- fora do loop de gameplay, uma unica vez na
    composicao (`BeatmapLoader.load` descarta esse campo, entao le-lo de
    novo aqui e mais barato que estender o contrato da engine so por
    causa de um efeito cosmetico do jogo). `default_bpm` cobre qualquer
    leitura malsucedida (arquivo ausente/corrompido -- nunca derruba a
    composicao por causa de um pulso visual)."""
    try:
        with open(beatmap_path, "r", encoding="utf-8") as beatmap_file:
            return float(json.load(beatmap_file).get("bpm", default_bpm))
    except (OSError, ValueError, TypeError):
        return default_bpm


def _hide_sprite(memory_manager: MemoryManager, entity_index: int) -> None:
    """Zera o alfa do sprite de uma entidade persistente (o modo decide
    o que fica visivel: mira no Defensor, nada no Arcade, ...)."""
    sprite_pool = memory_manager.get_pool("sprite")
    row = sprite_pool.dense_row_of(entity_index)
    sprite_pool.active_view()["tint_a"][row] = 0


def _compose_defender_mode(ctx: _ModeContext):
    """MODO 1 -- O Defensor (estilo BPM/Hellsinger): nucleo fixo no
    centro, ameacas radiais 360, mira livre + tiro na batida; misfire
    zera o combo. Ordem: PlayerInput -> Spawner radial -> [TelegraphRings]
    -> [JudgmentRadius] -> Judgment -> [OrbitalCapture] -> Physics ->
    [OrbitalEclipse] -> Collision -> [ParryImpact] -> [Shockwave] ->
    CoreDamage.

    MECANICAS MODULARES: `config.active_modifiers` (lista de strings da
    fase, ver catalogo em `HertzConfig`) e resolvido num UNICO
    `frozenset` aqui no topo -- o resto da funcao so testa
    `"x" in modifiers` (ou os booleanos locais derivados dele), igual a
    testar um antigo `config.polarity_enabled`/`config.holds_enabled`,
    so que agora e a PRESENCA na lista que decide, nao um campo fixo do
    dataclass. Cada `if` abaixo registra um sistema A MAIS (nunca troca
    um sistema por outro) -- a ORDEM de registro nunca muda entre fases,
    so QUANTOS sistemas entram nela. Zero-GC preservado: nenhuma
    resolucao de modifier aloca por FRAME (tudo aqui roda uma unica vez,
    na composicao/carregamento da fase)."""
    config = ctx.config
    center_x, center_y = config.center_xy

    modifiers = frozenset(config.active_modifiers)
    polarity_enabled = "polarity" in modifiers
    telegraph_rings_enabled = "telegraph_rings" in modifiers
    # Dependencias tecnicas: um modifier que precisa de "polarity" mas a
    # fase esqueceu de liga-la degrada para no-op silencioso (nunca
    # lanca erro) -- mesma filosofia graciosa de `orbit_threat_type_id`
    # de antes desta refatoracao.
    orbital_shields_enabled = "orbital_shields" in modifiers and polarity_enabled
    twin_threats_enabled = "twin_threats" in modifiers and polarity_enabled
    overload_enabled = "overload" in modifiers and polarity_enabled
    orbital_eclipses_enabled = "orbital_eclipses" in modifiers and config.orbital_eclipse_count > 0
    vision_tunnel_enabled = "vision_tunnel" in modifiers
    # Notas Longas (Hold): MUTUAMENTE EXCLUSIVO com Polaridade/Parry por
    # convencao de fase (ambos reusam o mesmo threat_type "pesada", cada
    # fase liga so UM dos dois -- nunca validado em runtime, e uma
    # responsabilidade de curadoria do `stages.json`).
    holds_enabled = "holds" in modifiers

    scheduled = _reinterpret_scheduled_for_modifiers(ctx.scheduled, config, modifiers)

    spawner_system = RadialRhythmSpawnerSystem(
        audio_clock=ctx.audio_clock,
        memory_manager=ctx.memory_manager,
        scheduled_spawns=scheduled,
        hit_times=ctx.hit_times,
        threat_archetype_name="rhythm_threat_radial",
        center_xy=(center_x, center_y),
        spawn_radius=config.spawn_radius,
        game_state=ctx.game_state,
        lane_count=config.lane_count,
        threat_half_by_type=ctx.threat_half_by_type,
        threat_texture_by_type=ctx.threat_texture_by_type,
        threat_collision_layer=THREAT_COLLISION_LAYER,
        threat_collision_mask=PLAYER_COLLISION_LAYER,
        max_threats_per_frame=config.max_threats_per_frame,
        ring_archetype_name="convergence_ring",
        hold_threat_type_id=(
            config.threat_type_ids.get("rhythm_threat_heavy") if holds_enabled else None
        ),
        hold_duration_seconds=config.hold_duration_seconds,
        polarity_enabled=polarity_enabled,
        orbit_threat_type_id=(
            config.threat_type_ids.get("rhythm_threat_orbit") if orbital_shields_enabled else None
        ),
        twin_threat_type_id=(
            config.threat_type_ids.get("rhythm_threat_twin") if twin_threats_enabled else None
        ),
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
            game_state=ctx.game_state,
            dash_duration_seconds=config.dash_duration_seconds,
            dash_cooldown_seconds=config.dash_cooldown_seconds,
        )
    )
    ctx.world.register_system(spawner_system)
    # Juice Visual -- Sparks: sempre registrado (mesma filosofia "sempre
    # ligado, cosmetico puro" do CameraShakeSystem) -- pool fixo,
    # NUNCA participa de colisao/julgamento, so `JudgmentSystem` chama
    # `emit_burst` diretamente a cada acerto PERFEITO.
    spark_system = SparkSystem(
        pool_size=config.spark_pool_size,
        lifetime_seconds=config.spark_lifetime_seconds,
        max_length=config.spark_max_length_px,
    )
    ctx.world.register_system(spark_system)
    # Aneis de Convergencia ("telegraph_rings"): SO decoracao-aviso, zero
    # impacto no julgamento -- opt-in explicito agora (antes era
    # incondicional em todo Defensor); uma fase sem o modifier so nao
    # ganha o anel neon, o resto do combate e identico.
    if telegraph_rings_enabled:
        ctx.world.register_system(
            ConvergenceRingSystem(
                audio_clock=ctx.audio_clock,
                memory_manager=ctx.memory_manager,
                spawn_radius=config.spawn_radius,
                judgment_ring_radius=judgment_ring_radius,
            )
        )
    # Colapso de Visao ("vision_tunnel", Tolerancia Organica): sem o
    # modifier, `GameState.tunnel_radius` fica parado no valor BASE
    # (campo totalmente aberto) pra sempre -- registrar o sistema so
    # muda algo se houver eventos `vision_tunnel` no `modchart_events`
    # da fase. Puramente COSMETICO: NUNCA usa `judgment_ring_radius`
    # (fisico) como base -- a diagonal centro->canto da janela garante
    # que o campo "aberto" cobre a tela inteira, nada escondido.
    if vision_tunnel_enabled:
        ctx.world.register_system(
            VisionTunnelSystem(
                audio_clock=ctx.audio_clock,
                game_state=ctx.game_state,
                # a mesma diagonal centro->canto ja usada para
                # inicializar `GameState.tunnel_radius` -- reusada aqui
                # em vez de recalculada, um so lugar de verdade.
                base_radius=ctx.game_state.tunnel_radius,
                collapse_events=parse_vision_tunnel_events(ctx.modchart_events),
            )
        )
    # Polaridade + Parry Perfeito ("polarity"): disparo azul/rosa,
    # pesadas viram Parry em vez de destruidas, Ressonancia/Overdrive e
    # Juice de Hitlag -- tudo automatico junto deste UNICO modifier (sao
    # inseparaveis: o Parry E a defesa universal contra pesadas
    # justamente porque a Polaridade torna as comuns sensiveis a cor).
    heavy_threat_type_id = (
        config.threat_type_ids.get("rhythm_threat_heavy") if polarity_enabled else None
    )
    orbit_threat_type_id = (
        config.threat_type_ids.get("rhythm_threat_orbit") if orbital_shields_enabled else None
    )
    hold_threat_type_id = (
        config.threat_type_ids.get("rhythm_threat_heavy") if holds_enabled else None
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
            score_perfect=ctx.effective_score_perfect,
            score_good=ctx.effective_score_good,
            judgment_display_seconds=config.judgment_display_seconds,
            misfire_breaks_combo=config.misfire_breaks_combo,
            misfire_jam_seconds=config.misfire_jam_seconds,
            audio_engine=ctx.audio_engine,
            shot_sound_ids=SFX_CANNON_VARIANTS,
            jam_sound_id=SFX_CLICK,
            miss_sound_id=SFX_MISS,
            polarity_enabled=polarity_enabled,
            fire_alt_action_name=config.fire_alt_action_name,
            heavy_threat_type_id=heavy_threat_type_id,
            deflect_sound_id=SFX_DEFLECT,
            parry_sound_id=SFX_PARRY,
            reflected_collision_layer=REFLECTED_COLLISION_LAYER if polarity_enabled else None,
            reflected_collision_mask=THREAT_COLLISION_LAYER if polarity_enabled else None,
            hold_threat_type_id=hold_threat_type_id,
            hold_aim_tolerance_rad=math.radians(config.hold_aim_tolerance_degrees),
            hold_break_shake_px=config.hold_break_shake_px,
            hold_grace_seconds=config.hold_grace_seconds,
            rumble_low_freq=config.rumble_low_freq,
            rumble_high_freq=config.rumble_high_freq,
            rumble_duration_seconds=config.rumble_duration_seconds,
            hold_engage_sound_id=SFX_HOLD_ENGAGE,
            hold_break_sound_id=SFX_HOLD_BREAK,
            practice_mode=config.practice_mode,
            hitlag_freeze_frames=config.parry_hitlag_freeze_frames if polarity_enabled else 0,
            orbit_threat_type_id=orbit_threat_type_id,
            shield_collision_layer=SHIELD_COLLISION_LAYER if orbit_threat_type_id is not None else None,
            shield_collision_mask=THREAT_COLLISION_LAYER if orbit_threat_type_id is not None else None,
            spark_system=spark_system,
            crosshair_entity_index=ctx.crosshair_entity_index,
            spark_burst_count=config.spark_burst_count,
        )
    )
    # Captura Orbital ("orbital_shields"): mesmo padrao de
    # `ReverseScrollSystem`/`LaneChoreographySystem` -- sobrescreve
    # `position_x/y` DIRETAMENTE, ANTES do `PhysicsSystem` generico (que
    # e um no-op para essas linhas, ja com velocidade zerada pela
    # captura) -- evita tocar a engine.
    if orbital_shields_enabled:
        ctx.world.register_system(
            OrbitalCaptureSystem(
                audio_clock=ctx.audio_clock,
                memory_manager=ctx.memory_manager,
                center_xy=(center_x, center_y),
                orbit_radius=config.orbit_radius,
                angular_speed_rad_per_sec=config.orbit_angular_speed_rad_per_sec,
            )
        )
    ctx.world.register_system(PhysicsSystem(ctx.memory_manager))

    # Eclipses Orbitais ("orbital_eclipses"): ao CONTRARIO da Captura
    # Orbital acima, aqui a rotacao passa PELO `PhysicsSystem` generico
    # (`velocity.angular` constante -> `rotation_rad` integrado de
    # graca) -- entao o `OrbitalEclipseSystem` (conversao angulo->posicao)
    # precisa rodar DEPOIS dele, nao antes.
    eclipse_entity_indices = None
    if orbital_eclipses_enabled:
        eclipse_entity_indices = _create_orbital_eclipse_entities(ctx.world, ctx.memory_manager, config)
        ctx.world.register_system(
            OrbitalEclipseSystem(
                memory_manager=ctx.memory_manager,
                center_xy=(center_x, center_y),
                orbit_radius=config.orbital_eclipse_radius,
                eclipse_entity_indices=eclipse_entity_indices,
            )
        )

    ctx.world.register_system(collision_system)
    if polarity_enabled:
        ctx.world.register_system(
            ParryImpactSystem(
                collision_system=collision_system,
                memory_manager=ctx.memory_manager,
                game_state=ctx.game_state,
                player_entity_index=ctx.player_entity_index,
                center_xy=(center_x, center_y),
                spawn_radius=config.spawn_radius,
                score_per_kill=ctx.effective_score_good,
                impact_shake_px=config.parry_impact_shake_px,
            )
        )
    # Overload do Nucleo ("overload"): reaproveita o ShockwaveSystem do
    # Pulso de Impacto (extinta Sobrevivencia) -- MODIFIER PROPRIO agora
    # (antes vinha de graca dentro do bloco de Polaridade); ainda exige
    # "polarity" (a Ressonancia, seu "combustivel", so existe entao).
    if overload_enabled:
        shockwave_entity_indices = _create_shockwave_pool(
            ctx.world, ctx.memory_manager, config.shockwave_pool_size
        )
        ctx.world.register_system(
            ShockwaveSystem(
                collision_system=collision_system,
                memory_manager=ctx.memory_manager,
                game_state=ctx.game_state,
                player_entity_index=ctx.player_entity_index,
                shockwave_entity_indices=shockwave_entity_indices,
                min_radius=config.shockwave_min_radius,
                max_radius=config.shockwave_max_radius,
                duration_seconds=config.shockwave_duration_seconds,
                score_per_kill=ctx.effective_score_good,
                heavy_threat_type_id=heavy_threat_type_id,
                orbit_threat_type_id=orbit_threat_type_id,
                trigger_shake_px=config.shockwave_trigger_shake_px,
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
            damage_shake_px=config.core_damage_shake_px,
            audio_engine=ctx.audio_engine,
            dodge_sound_id=SFX_DEFLECT,
            miss_sound_id=SFX_MISS,
        )
    )
    ctx.spark_system = spark_system
    return (spawner_system,), collision_system


def _reinterpret_scheduled_for_modifiers(scheduled: np.ndarray, config: HertzConfig, modifiers) -> np.ndarray:
    """Gemeos de Polaridade ("twin_threats") e Escudos Rotativos
    ("orbital_shields") nunca sao emitidos pelo mapeador OFFLINE da IA
    (vocabulario so tem "basic"/"heavy") -- mesma reinterpretacao 100%
    GAME-side ja usada por Notas Toxicas/Cura/Scratch: o `beatmap.json`
    em disco nunca muda, so a INTERPRETACAO do `threat_type` de algumas
    linhas ja agendadas. Reescreve uma fracao DETERMINISTICA (a cada
    Nesima ocorrencia, nunca por sorteio) do array recebido -- devolve
    SEMPRE uma copia nova, nunca muta `scheduled` (compartilhado com
    `ctx.hit_times` por indice de linha) mesmo quando nenhum modifier
    relevante esta ativo."""
    orbital_shields_enabled = "orbital_shields" in modifiers and "polarity" in modifiers
    twin_threats_enabled = "twin_threats" in modifiers and "polarity" in modifiers
    if not orbital_shields_enabled and not twin_threats_enabled:
        return scheduled

    scheduled = scheduled.copy()
    threat_type_ids = config.threat_type_ids
    threat_type_col = scheduled["threat_type"]

    if orbital_shields_enabled:
        orbit_id = threat_type_ids.get("rhythm_threat_orbit")
        heavy_id = threat_type_ids.get("rhythm_threat_heavy")
        if orbit_id is not None and heavy_id is not None:
            heavy_rows = np.flatnonzero(threat_type_col == heavy_id)
            threat_type_col[heavy_rows[::3]] = orbit_id  # a cada 3a pesada vira Escudo

    if twin_threats_enabled:
        twin_id = threat_type_ids.get("rhythm_threat_twin")
        basic_id = threat_type_ids.get("rhythm_threat_basic")
        if twin_id is not None and basic_id is not None:
            basic_rows = np.flatnonzero(threat_type_col == basic_id)
            threat_type_col[basic_rows[::5]] = twin_id  # a cada 5a comum vira Gemeos

    return scheduled


def _create_shockwave_pool(world: World, memory_manager: MemoryManager, pool_size: int) -> np.ndarray:
    """Pre-cria `pool_size` entidades de onda de choque (Overload do
    Nucleo), inicialmente INATIVAS (hitbox/sprite zerados pelo proprio
    `MemoryManager` -- camada/mascara 0 e alfa 0 sao o "invisivel/sem
    colisao" default de uma linha nova). Disciplina Zero-GC MAIS
    ESTRITA que o resto do jogo: este pool fixo e reaproveitado para
    sempre em round-robin pelo `ShockwaveSystem`, nunca criado/destruido
    durante a partida."""
    indices = np.zeros(pool_size, dtype=np.int64)
    for i in range(pool_size):
        indices[i] = unpack_index(world.create_entity("shockwave"))
    return indices


def _create_orbital_eclipse_entities(
    world: World, memory_manager: MemoryManager, config: HertzConfig
) -> np.ndarray:
    """Pre-cria `orbital_eclipse_count` obstaculos (Eclipses Orbitais),
    distribuidos em angulos UNIFORMES ao redor do circulo
    (`TAU * i / count`) -- todos giram JUNTOS depois (mesma
    `rotation_speed`), preservando o espacamento relativo entre si para
    sempre. `velocity.linear_x/y` fica ZERADO (a translacao do
    `PhysicsSystem` generico e um no-op para eles -- so o angulo
    integra); `velocity.angular` e a UNICA fonte de movimento, constante
    desde a criacao. Zero-GC: laco escalar sobre uma contagem tipicamente
    pequena (1-3), so na composicao (fase de carregamento)."""
    count = config.orbital_eclipse_count
    indices = np.zeros(count, dtype=np.int64)
    transform_pool = memory_manager.get_pool("transform")
    velocity_pool = memory_manager.get_pool("velocity")
    hitbox_pool = memory_manager.get_pool("hitbox")
    sprite_pool = memory_manager.get_pool("sprite")

    for i in range(count):
        packed = world.create_entity("orbital_eclipse")
        entity_index = unpack_index(packed)
        indices[i] = entity_index
        angle = 2.0 * math.pi * i / count

        transform_row = transform_pool.dense_row_of(entity_index)
        transform_view = transform_pool.active_view()
        transform_view["rotation_rad"][transform_row] = angle
        transform_view["scale_x"][transform_row] = config.orbital_eclipse_half_width / 8.0
        transform_view["scale_y"][transform_row] = config.orbital_eclipse_half_height / 8.0

        velocity_row = velocity_pool.dense_row_of(entity_index)
        velocity_view = velocity_pool.active_view()
        velocity_view["linear_x"][velocity_row] = 0.0
        velocity_view["linear_y"][velocity_row] = 0.0
        velocity_view["angular"][velocity_row] = config.orbital_eclipse_rotation_speed_rad_per_sec

        hitbox_row = hitbox_pool.dense_row_of(entity_index)
        hitbox_view = hitbox_pool.active_view()
        hitbox_view["half_width"][hitbox_row] = config.orbital_eclipse_half_width
        hitbox_view["half_height"][hitbox_row] = config.orbital_eclipse_half_height
        hitbox_view["collision_layer"][hitbox_row] = SHIELD_COLLISION_LAYER
        hitbox_view["collision_mask"][hitbox_row] = REFLECTED_COLLISION_LAYER

        sprite_row = sprite_pool.dense_row_of(entity_index)
        sprite_view = sprite_pool.active_view()
        sprite_view["texture_id"][sprite_row] = TEX_ORBITAL_ECLIPSE
        sprite_view["tint_r"][sprite_row] = 120
        sprite_view["tint_g"][sprite_row] = 40
        sprite_view["tint_b"][sprite_row] = 160
        sprite_view["tint_a"][sprite_row] = 255
        sprite_view["layer_z"][sprite_row] = 18

    return indices


def _create_distraction_pool(world: World, memory_manager: MemoryManager, pool_size: int) -> np.ndarray:
    """Pre-cria `pool_size` entidades de Obstrucao Visual (jumpscare),
    inicialmente INATIVAS (`tint_a=0` default de uma linha nova de
    sprite) -- disciplina Zero-GC MAIS ESTRITA que o resto do jogo:
    pool fixo, reaproveitado para sempre em round-robin pelo
    `DistractionSystem`, nunca criado/destruido durante a partida."""
    indices = np.zeros(pool_size, dtype=np.int64)
    for i in range(pool_size):
        indices[i] = unpack_index(world.create_entity("distraction"))
    return indices


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
    modifiers = frozenset(config.active_modifiers)
    holds_enabled = "holds" in modifiers
    base_spawn_y = -24.0
    judgment_line_y = config.window_height - config.judgment_line_offset
    lane_center_xs = lane_center_positions(config)
    # buffer MUTAVEL compartilhado por IDENTIDADE com o spawner E o
    # `LaneChoreographySystem` -- Modcharts/Pistas Dinamicas reescrevem
    # este array por inteiro todo frame; `lane_center_xs` acima segue
    # imutavel (a base para os calculos de offset).
    current_lane_xs = lane_center_xs.copy()
    # idem no eixo Y: `ReverseScrollSystem` (Inversao de Gravidade)
    # reescreve [spawn_y, judgment_line_y] todo frame; os dois valores
    # BASE acima seguem imutaveis (referencia para o espelhamento).
    current_geometry_y = np.array([base_spawn_y, judgment_line_y], dtype=np.float64)
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
    # Notas Toxicas (Bombas) e Notas de Cura: opt-in via "bombs"/"heal"
    # em `active_modifiers` (antes era so presenca do tipo em
    # `threat_type_ids`, que e GLOBAL e portanto sempre verdadeiro --
    # agora o modifier e o que de fato liga/desliga por fase).
    bomb_type_id = config.threat_type_ids.get("rhythm_threat_bomb") if "bombs" in modifiers else None
    heal_type_id = config.threat_type_ids.get("rhythm_threat_heal") if "heal" in modifiers else None

    spawner_system = LaneNoteSpawnerSystem(
        audio_clock=ctx.audio_clock,
        memory_manager=ctx.memory_manager,
        scheduled_spawns=scheduled_out,
        hit_times=hit_times_out,
        threat_archetype_name="rhythm_threat_radial",
        lane_center_xs=current_lane_xs,
        geometry_y=current_geometry_y,
        note_half_by_type=ctx.threat_half_by_type,
        lane_tints_rgb=lane_tints_rgb,
        max_threats_per_frame=config.max_threats_per_frame,
        is_hold_by_row=is_hold_out,
        hold_end_by_row=hold_end_out,
        hold_threat_type_id=heavy_type_id if holds_enabled else None,
        hold_duration_seconds=config.hold_duration_seconds,
        hold_visual_max_fraction=config.lane_hold_visual_max_fraction,
        bomb_threat_type_id=bomb_type_id,
        heal_threat_type_id=heal_type_id,
    )

    # nucleo e mira nao participam deste modo; receptores + rotulos de
    # tecla marcam a linha de julgamento (entidades de HUD comuns) --
    # os indices sao guardados para as "Pistas Dinamicas"/Modcharts
    # reposicionarem a linha inteira junto com as colunas.
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
            score_perfect=ctx.effective_score_perfect,
            score_good=ctx.effective_score_good,
            judgment_display_seconds=config.judgment_display_seconds,
            audio_engine=ctx.audio_engine,
            ghost_tap_sound_id=SFX_TAP,
            holds_enabled=holds_enabled,
            practice_mode=config.practice_mode,
            hold_break_shake_px=config.hold_break_shake_px,
            lane_shield_depleted_shake_px=config.lane_shield_depleted_shake_px,
            rumble_low_freq=config.rumble_low_freq,
            rumble_high_freq=config.rumble_high_freq,
            rumble_duration_seconds=config.rumble_duration_seconds,
            hold_engage_sound_id=SFX_HOLD_ENGAGE,
            hold_break_sound_id=SFX_HOLD_BREAK,
            shield_break_sound_id=SFX_SHIELD_BREAK,
            bomb_threat_type_id=bomb_type_id,
            bomb_hit_shake_px=config.bomb_hit_shake_px,
            bomb_blindness_seconds=config.bomb_blindness_seconds,
            bomb_hit_sound_id=SFX_BOMB,
            heal_threat_type_id=heal_type_id,
            max_health=config.max_health,
            heal_amount=config.heal_amount,
            heal_sound_id=SFX_HEAL,
            note_hit_sound_ids=SFX_NOTE_HIT_VARIANTS,
            miss_sound_id=SFX_MISS,
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
            score_perfect=ctx.effective_score_perfect,
        )
    )
    # Pistas Dinamicas: o balanco reage aos MESMOS instantes que abrem
    # uma nota de Scratch (o "solo/glitch" do enunciado) -- nenhum campo
    # novo de beatmap, so reaproveita `hit_times_out` filtrado por
    # `is_hold_out`.
    trigger_times = hit_times_out[is_hold_out]
    choreography_system = LaneChoreographySystem(
        audio_clock=ctx.audio_clock,
        memory_manager=ctx.memory_manager,
        base_lane_xs=lane_center_xs,
        current_lane_xs=current_lane_xs,
        trigger_times=trigger_times,
        amplitude_px=config.lane_sway_amplitude_px,
        decay_per_second=config.lane_sway_decay_per_second,
        receptor_entity_indices=receptor_entity_indices,
        key_label_entity_indices=key_label_entity_indices,
        swap_events=parse_swap_events(ctx.modchart_events),
    )
    ctx.world.register_system(choreography_system)
    ctx.lane_choreography_system = choreography_system
    ctx.lane_geometry_y = current_geometry_y
    if config.stutter_scroll_enabled or config.hidden_notes_enabled:
        ctx.world.register_system(
            VisualModifierSystem(
                audio_clock=ctx.audio_clock,
                memory_manager=ctx.memory_manager,
                game_state=ctx.game_state,
                frequency_hz=config.stutter_scroll_frequency_hz,
                amplitude_px=config.stutter_scroll_amplitude_px,
                hidden_notes_enabled=config.hidden_notes_enabled,
                hidden_fade_seconds=config.hidden_fade_seconds,
            )
        )
    # Inversao de Gravidade (Reverse Scroll): espelha spawn/linha de
    # julgamento em tempo real -- `current_geometry_y` e a MESMA
    # identidade lida pelo spawner acima.
    ctx.world.register_system(
        ReverseScrollSystem(
            audio_clock=ctx.audio_clock,
            memory_manager=ctx.memory_manager,
            base_spawn_y=base_spawn_y,
            base_judgment_line_y=judgment_line_y,
            window_height=config.window_height,
            current_geometry_y=current_geometry_y,
            reverse_events=parse_reverse_scroll_events(ctx.modchart_events),
            receptor_entity_indices=receptor_entity_indices,
            key_label_entity_indices=key_label_entity_indices,
        )
    )
    # Obstrucoes Visuais (jumpscares): pool fixo de entidades pre-alocado
    # aqui mesmo (disciplina Zero-GC mais estrita: nunca criado/destruido
    # durante a partida), o modo so registra o sistema que consome os
    # eventos "distraction" de `modchart_events`.
    distraction_events = parse_distraction_events(ctx.modchart_events)
    distraction_entity_indices = _create_distraction_pool(
        ctx.world, ctx.memory_manager, config.distraction_pool_size
    )
    ctx.world.register_system(
        DistractionSystem(
            audio_clock=ctx.audio_clock,
            memory_manager=ctx.memory_manager,
            distraction_events=distraction_events,
            distraction_entity_indices=distraction_entity_indices,
            window_width=config.window_width,
            window_height=config.window_height,
            layer_z=HUD_LAYER_Z + 20,
        )
    )
    ctx.world.register_system(PhysicsSystem(ctx.memory_manager))
    return (spawner_system,), None


MODE_COMPOSERS = {
    "defender": _compose_defender_mode,
    "lanes": _compose_lanes_mode,
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
    modchart_events: tuple = (),
) -> ComposedGame:
    """Composicao PURA (sem pygame): pools, arquetipos, entidades
    persistentes (nucleo, mira, HUD), beatmap e a ordem exata dos
    sistemas. Backends concretos entram por parametro -- os testes
    injetam Null*, o `build()` injeta Pygame*.

    `tutorial_steps` (da definicao da fase) liga o modo tutorial: cria o
    sprite-banner de instrucoes e registra o `TutorialSystem`;
    `stage_ordinal` enderessa a faixa de texturas de texto da fase.
    `modchart_events` (da definicao da fase, `StageDef.modchart_events`)
    liga os eventos de Modchart (troca de colunas com Lerp) no
    `LaneChoreographySystem` quando `game_mode == "lanes"` -- dado
    100% game-side, nao existe no `beatmap.json` da engine.
    """
    center_x, center_y = config.center_xy

    # Meta-Jogo -- Multiplicador de Pontuacao: resolvido no Pre-Voo
    # (`hertz_game_loop.compute_score_multiplier`, a partir dos
    # modifiers/Modo Treino escolhidos) e aplicado UMA vez aqui --
    # score_perfect/score_good EFETIVOS (`ctx.effective_score_*`)
    # substituem os valores crus de `config` em todo sistema que
    # pontua, nunca recalculado por acerto em tempo real.
    effective_score_perfect = max(1, round(config.score_perfect * config.score_multiplier))
    effective_score_good = max(1, round(config.score_good * config.score_multiplier))

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
        "distraction", DISTRACTION_DTYPE, dense_capacity=max(config.distraction_pool_size, 1)
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
    world.register_archetype("distraction", ("transform", "sprite", "distraction"))
    world.register_archetype("shockwave", ("transform", "hitbox", "sprite", "shockwave"))
    world.register_archetype("orbital_eclipse", ("transform", "velocity", "hitbox", "sprite"))

    # 3. Beatmap: tempos de IMPACTO do JSON viram tempos de SPAWN
    #    (deslocados por approach_seconds) para o cursor do spawner;
    #    o array original de impacto segue paralelo, linha a linha.
    scheduled = BeatmapLoader(config.threat_type_ids).load(Path(config.beatmap_path))
    hit_times = scheduled["timestamp_seconds"].copy()
    bpm = _read_beatmap_bpm(config.beatmap_path)
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

    game_state = GameState(
        max_health=config.max_health,
        shield_charges=config.lane_shield_max_charges if "holds" in config.active_modifiers else 0,
        resonance_chain_threshold=config.resonance_chain_threshold,
        # Raio FIXO de sempre (nucleo + meio-tamanho da ameaca comum),
        # nunca mutado depois (ver docstring de `GameState.
        # current_judgment_radius`); nos modos fora do Defensor fica
        # parado neste valor, nunca lido.
        judgment_radius=config.core_half_extent + config.threat_half_extents.get("rhythm_threat_basic", 10.0),
        # Colapso de Visao: valor BASE "campo totalmente aberto" -- a
        # diagonal INTEIRA da janela (folgada o bastante para cobrir
        # qualquer canto partindo do centro, sem risco de arredondamento
        # deixar frestas pretas nos cantos), SEMPRE passado (nao so
        # quando "vision_tunnel" esta ativo) para que o renderer nunca
        # veja um raio pequeno demais (o que enegreceria parte da arena)
        # numa fase sem o modifier; so o `VisionTunnelSystem` (opt-in) o
        # encolhe de verdade.
        tunnel_radius=math.hypot(config.window_width, config.window_height),
        # Heartbeat (Juice Visual): bpm do PROPRIO beatmap.json da fase
        # (`_read_beatmap_bpm`, lido uma unica vez aqui na composicao,
        # nunca em runtime) -- `beat_phase` (`HertzGameLoop._sync_beat_phase`)
        # deriva dele.
        bpm=bpm,
    )

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
        modchart_events=modchart_events,
        effective_score_perfect=effective_score_perfect,
        effective_score_good=effective_score_good,
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

    # Screen Shake: decaimento comum aos 2 modos, independente de quem
    # aciona `GameState.trigger_shake` -- qualquer mecanica so precisa
    # chamar o mesmo metodo, sem registrar nada extra aqui.
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
            combo_bump_threshold=config.combo_bump_threshold,
            combo_bump_seconds=config.combo_bump_seconds,
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
        lane_choreography_system=context.lane_choreography_system,
        lane_geometry_y=context.lane_geometry_y,
        spark_system=context.spark_system,
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
            build_and_register_vignette_surface,
        )
        from hertzbeats.audio.demo_track_synth import ensure_metronome_track, ensure_track
        from hertzbeats.audio.sfx_synth import (
            SFX_BOMB,
            SFX_CANNON,
            SFX_CANNON_VARIANTS,
            SFX_CLICK,
            SFX_DEFLECT,
            SFX_HEAL,
            SFX_HOLD_BREAK,
            SFX_HOLD_ENGAGE,
            SFX_MISS,
            SFX_NOTE_HIT_VARIANTS,
            SFX_PARRY,
            SFX_SHIELD_BREAK,
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
            SFX_CANNON, SFX_CLICK, SFX_TAP, SFX_DEFLECT, SFX_PARRY,
            SFX_HOLD_ENGAGE, SFX_HOLD_BREAK, SFX_SHIELD_BREAK, SFX_BOMB, SFX_HEAL,
            SFX_MISS, *SFX_CANNON_VARIANTS, *SFX_NOTE_HIT_VARIANTS,
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

        # Tela de Titulo (BGM em loop) + Calibracao (metronomo puro):
        # faixas dedicadas, re-sintetizadas deterministicamente se
        # ausentes -- mesmo criterio das faixas de fase (nunca
        # versionadas no repositorio).
        title_track_path = ensure_track("data/tracks/title_theme.wav", {"bpm": 96.0, "bars": 16, "style": "calm"})
        calibration_track_path = ensure_metronome_track(
            "data/tracks/calibration_metronome.wav", bpm=config.calibration_bpm
        )

        game_loop = HertzGameLoop(
            base_config=config,
            stages=stages,
            renderer=renderer,
            input_provider=input_provider,
            audio_engine=audio_engine,
            audio_clock=audio_clock,
            title_track_path=title_track_path,
            calibration_track_path=calibration_track_path,
        )

        # Texturas de HUD, overlays e textos de tutorial pre-renderizados
        # (tela de carregamento).
        build_and_register_hud_textures(renderer)
        build_and_register_overlay_surfaces(renderer, stages)
        build_and_register_tutorial_textures(renderer, stages)
        build_and_register_vignette_surface(renderer, config)

        return game_loop, audio_engine
