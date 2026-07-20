"""Especializacao radial do RhythmSpawnerSystem: nasce na borda, toca o nucleo exatamente na batida."""
from __future__ import annotations

import math

import numpy as np

from ouroboros.core.memory.handles import PackedEntityId, unpack_index
from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock
from ouroboros.rhythm.runtime.rhythm_spawner_system import RhythmSpawnerSystem

from hertzbeats.components.schemas import (
    JUDGMENT_PENDING,
    MODE_TAG_DEFENDER,
    PHASE_LETHAL,
    POLARITY_BLUE,
    POLARITY_PINK,
)
from hertzbeats.components.texture_ids import (
    TEX_CONVERGENCE_RING,
    TEX_THREAT_BASIC,
    TEX_THREAT_HEAVY,
    TEX_THREAT_POLARITY_BLUE,
    TEX_THREAT_POLARITY_PINK,
)
from hertzbeats.game_state import GameState

_TAU = 2.0 * math.pi


class RadialRhythmSpawnerSystem(RhythmSpawnerSystem):
    """
    E o `RhythmSpawnerSystem` da engine (herda cursor monotonico,
    compensacao de latencia e idempotencia inalterados), estendido com a
    materializacao RADIAL de cada ameaca no momento do disparo:

        - O array agendado passado a base class contem TEMPOS DE SPAWN
          (`hit_time - approach_seconds`, com clamp em 0.0), preparado
          na composicao. `hit_times` (parametro deste construtor) guarda
          os tempos de IMPACTO originais do beatmap, paralelos linha a
          linha.
        - No spawn, a ameaca nasce na borda (`spawn_radius` a partir do
          centro), no angulo derivado da `lane` extraida pela IA
          (`angulo = TAU * lane / lane_count`), e recebe uma velocidade
          constante MATEMATICAMENTE calculada para que sua borda toque o
          anel do nucleo exatamente em `target_hit_time_sec`::

              distancia_util = spawn_radius - (core_half + threat_half)
              velocidade     = distancia_util / (hit_time - agora_efetivo)

          Como o tempo restante e medido contra o `IAudioClock` ja
          compensado de latencia, um spawn atrasado por um frame lento
          simplesmente viaja proporcionalmente mais rapido -- o impacto
          continua cravado na batida.

    Zero-GC: toda a inicializacao e feita com escritas escalares
    primitivas nas linhas densas recem-anexadas (mesmo padrao do
    `_create_threat_entity` original); pools e arrays de afinacao por
    tipo de ameaca sao resolvidos UMA unica vez aqui no construtor.
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        memory_manager: MemoryManager,
        scheduled_spawns: np.ndarray,
        hit_times: np.ndarray,
        threat_archetype_name: str,
        center_xy: tuple,
        spawn_radius: float,
        game_state: GameState,
        lane_count: int,
        threat_half_by_type: np.ndarray,
        threat_texture_by_type: np.ndarray,
        threat_collision_layer: int,
        threat_collision_mask: int,
        max_threats_per_frame: int,
        min_travel_seconds: float = 0.05,
        ring_archetype_name: str = None,
        hold_threat_type_id: int = None,
        hold_duration_seconds: float = 0.0,
        polarity_enabled: bool = False,
        orbit_threat_type_id: int = None,
        twin_threat_type_id: int = None,
    ) -> None:
        """`scheduled_spawns` e o array `SCHEDULED_THREAT_DTYPE` com
        timestamps ja deslocados para tempos de spawn; `hit_times`
        (float64, mesma ordem) preserva os instantes de impacto. Ambos
        sao materializados pelo `BeatmapLoader` + composicao, fora do
        loop. `threat_half_by_type`/`threat_texture_by_type` sao arrays
        indexados por `threat_type` (afinacao data-driven ja resolvida).

        Notas Longas (Holds, opt-in via "holds" em `HertzConfig.active_modifiers`):
        `hold_threat_type_id` (quando fornecido) marca QUAL `threat_type`
        vira Hold -- reusa o mesmo id de "pesada" ja usado pelo Parry
        (`config.threat_type_ids["rhythm_threat_heavy"]`), nao um
        terceiro tipo novo. Ameacas desse tipo nascem com
        `duration_sec = hold_duration_seconds` (> 0 marca Hold para o
        `JudgmentSystem`); as demais nascem com `duration_sec = 0.0`
        (default de pool zerada, nota comum).

        COLAPSO DO ANEL DE JULGAMENTO: `game_state` substitui o antigo
        `core_half_extent` fixo -- a distancia de viagem de CADA ameaca
        nova e calculada contra `game_state.current_judgment_radius`
        (mutavel, ver `JudgmentRadiusSystem`), nunca uma constante
        capturada no construtor. So ameacas NOVAS sentem uma mudanca de
        raio (a velocidade e calculada uma unica vez no spawn); ameacas
        ja em voo mantem sua velocidade original.

        GEMEOS DE POLARIDADE (opt-in via `twin_threat_type_id`): um
        evento do beatmap com esse `threat_type` materializa DUAS
        entidades no MESMO frame, mesmo `target_hit_time_sec`, em lanes
        DIAMETRALMENTE OPOSTAS (`lane` e `lane + lane_count/2`) -- como
        a polaridade e derivada da METADE do bucket de timbre de `lane`
        (ver `_materialize_threat`), a lane espelhada cai SEMPRE no
        bucket oposto, entao as duas nascem automaticamente em cores
        opostas sem nenhuma logica extra de cor.
        """
        super().__init__(
            audio_clock=audio_clock,
            scheduled_threats=scheduled_spawns,
            threat_archetype_name=threat_archetype_name,
            lane_pool_name="rhythm_threat",
            threat_type_pool_name="rhythm_threat",
            max_threats_per_frame=max_threats_per_frame,
        )
        self._transform_pool = memory_manager.get_pool("transform")
        self._velocity_pool = memory_manager.get_pool("velocity")
        self._hitbox_pool = memory_manager.get_pool("hitbox")
        self._sprite_pool = memory_manager.get_pool("sprite")
        self._threat_pool = memory_manager.get_pool("rhythm_threat")

        self._hit_times = hit_times
        self._center_x = float(center_xy[0])
        self._center_y = float(center_xy[1])
        self._spawn_radius = float(spawn_radius)
        self._game_state = game_state
        self._lane_count = int(lane_count)
        self._threat_half_by_type = threat_half_by_type
        self._threat_texture_by_type = threat_texture_by_type
        self._threat_collision_layer = int(threat_collision_layer)
        self._threat_collision_mask = int(threat_collision_mask)
        self._min_travel_seconds = float(min_travel_seconds)
        self._ring_archetype_name = ring_archetype_name
        self._ring_pool = (
            memory_manager.get_pool("convergence_ring") if ring_archetype_name else None
        )
        self._hold_threat_type_id = hold_threat_type_id
        self._hold_duration_seconds = float(hold_duration_seconds)
        self._polarity_enabled = bool(polarity_enabled)
        self._orbit_threat_type_id = orbit_threat_type_id
        self._twin_threat_type_id = twin_threat_type_id

    def _create_threat_entity(self, world: World, row_index: int) -> PackedEntityId:
        """Cria a entidade via base class (que escreve `lane`/
        `threat_type` na pool `rhythm_threat`) e delega a
        `_materialize_threat` o resto (posicao, velocidade, hitbox,
        sprite, campos ritmicos).

        GEMEOS DE POLARIDADE: se o `threat_type` desta linha e
        `twin_threat_type_id`, uma SEGUNDA entidade e criada aqui mesmo
        (fora do cursor monotonico da base class -- este evento do
        beatmap continua contando como UM disparo so) numa lane
        DIAMETRALMENTE OPOSTA, com o MESMO `target_hit_time_sec`.
        """
        packed = super()._create_threat_entity(world, row_index)
        entity_index = unpack_index(packed)

        threat_row = self._threat_pool.dense_row_of(entity_index)
        threat_view = self._threat_pool.active_view()
        threat_type = int(threat_view["threat_type"][threat_row])
        lane = int(threat_view["lane"][threat_row])

        hit_time = float(self._hit_times[row_index])
        strength = float(self._scheduled_threats["strength"][row_index])
        self._materialize_threat(world, entity_index, packed, threat_row, lane, threat_type, hit_time, strength)

        if self._twin_threat_type_id is not None and threat_type == self._twin_threat_type_id:
            mirror_lane = (lane + self._lane_count // 2) % self._lane_count
            twin_packed = world.create_entity(self._threat_archetype_name)
            twin_index = unpack_index(twin_packed)
            twin_row = self._threat_pool.dense_row_of(twin_index)
            twin_view = self._threat_pool.active_view()
            twin_view["lane"][twin_row] = mirror_lane
            twin_view["threat_type"][twin_row] = threat_type
            self._materialize_threat(
                world, twin_index, twin_packed, twin_row, mirror_lane, threat_type, hit_time, strength
            )

        return packed

    def _materialize_threat(
        self,
        world: World,
        entity_index: int,
        packed: PackedEntityId,
        threat_row: int,
        lane: int,
        threat_type: int,
        hit_time: float,
        strength: float,
    ) -> None:
        """Materializa UMA ameaca radial ja criada (posicao na borda,
        velocidade em direcao ao nucleo, hitbox/sprite por tipo, e os
        campos ritmicos consumidos por `JudgmentSystem`/`CoreDamageSystem`)
        -- extraido de `_create_threat_entity` para ser chamado DUAS
        vezes no mesmo frame pelos Gemeos de Polaridade, uma por
        entidade, cada uma com sua PROPRIA `lane` (e portanto seu
        proprio angulo/polaridade)."""
        time_remaining = hit_time - self._compute_effective_time()
        if time_remaining < self._min_travel_seconds:
            time_remaining = self._min_travel_seconds

        threat_half = float(self._threat_half_by_type[threat_type])
        # Colapso do Anel de Julgamento: a distancia de viagem mira o
        # raio ATUAL (mutavel) do anel, nao mais uma constante fixa --
        # so ameacas NOVAS sentem a mudanca (velocidade e calculada uma
        # unica vez, aqui, no spawn).
        travel_distance = self._spawn_radius - self._game_state.current_judgment_radius
        speed = travel_distance / time_remaining

        angle = _TAU * (lane % self._lane_count) / self._lane_count
        direction_x = math.cos(angle)
        direction_y = math.sin(angle)
        spawn_x = self._center_x + direction_x * self._spawn_radius
        spawn_y = self._center_y + direction_y * self._spawn_radius

        threat_view = self._threat_pool.active_view()
        threat_view["mode_tag"][threat_row] = MODE_TAG_DEFENDER
        threat_view["phase"][threat_row] = PHASE_LETHAL
        threat_view["strength"][threat_row] = strength
        # Polaridade: reusa o BUCKET DE TIMBRE que a IA ja atribuiu a
        # `lane` (assign_lanes no mapeador -- grave -> bucket baixo,
        # agudo -> bucket alto) -- zero analise extra. Metade inferior
        # dos buckets = grave = ROSA; metade superior = agudo = AZUL.
        # Gemeos de Polaridade: a lane ESPELHADA (`lane + lane_count/2`)
        # cai SEMPRE no bucket oposto, entao as duas entidades nascem em
        # cores opostas automaticamente, sem branch extra aqui.
        threat_view["polarity_id"][threat_row] = (
            POLARITY_PINK if (lane % self._lane_count) < self._lane_count / 2.0 else POLARITY_BLUE
        )
        threat_view["is_reflected"][threat_row] = False
        threat_view["duration_sec"][threat_row] = (
            self._hold_duration_seconds
            if (self._hold_threat_type_id is not None and threat_type == self._hold_threat_type_id)
            else 0.0
        )
        threat_view["target_hit_time_sec"][threat_row] = hit_time
        threat_view["expire_time_sec"][threat_row] = hit_time  # telemetria neste modo
        threat_view["spawn_angle_rad"][threat_row] = angle
        threat_view["is_hit"][threat_row] = False
        threat_view["judgment"][threat_row] = JUDGMENT_PENDING
        threat_view["packed_handle"][threat_row] = packed

        transform_row = self._transform_pool.dense_row_of(entity_index)
        transform_view = self._transform_pool.active_view()
        transform_view["position_x"][transform_row] = spawn_x
        transform_view["position_y"][transform_row] = spawn_y
        transform_view["rotation_rad"][transform_row] = angle
        scale = threat_half / 8.0
        transform_view["scale_x"][transform_row] = scale
        transform_view["scale_y"][transform_row] = scale

        velocity_row = self._velocity_pool.dense_row_of(entity_index)
        velocity_view = self._velocity_pool.active_view()
        velocity_view["linear_x"][velocity_row] = -direction_x * speed
        velocity_view["linear_y"][velocity_row] = -direction_y * speed
        velocity_view["angular"][velocity_row] = 0.0

        hitbox_row = self._hitbox_pool.dense_row_of(entity_index)
        hitbox_view = self._hitbox_pool.active_view()
        hitbox_view["half_width"][hitbox_row] = threat_half
        hitbox_view["half_height"][hitbox_row] = threat_half
        hitbox_view["collision_layer"][hitbox_row] = self._threat_collision_layer
        hitbox_view["collision_mask"][hitbox_row] = self._threat_collision_mask

        base_texture_id = (
            self._threat_texture_by_type[threat_type]
            if threat_type < self._threat_texture_by_type.shape[0]
            else TEX_THREAT_BASIC
        )
        sprite_row = self._sprite_pool.dense_row_of(entity_index)
        sprite_view = self._sprite_pool.active_view()
        # Captura Orbital: tint ciano DISTINTO desde o spawn -- "isto e
        # um alvo de Parry especial", antes mesmo da captura. Checado
        # ANTES do ramo de Polaridade: um Escudo aceita QUALQUER cor (a
        # janela PERFECT-apenas do `JudgmentSystem` ja cuida disso), seu
        # visual nao deve trocar para azul/rosa por engano.
        if self._orbit_threat_type_id is not None and threat_type == self._orbit_threat_type_id:
            sprite_view["texture_id"][sprite_row] = base_texture_id
            sprite_view["tint_r"][sprite_row] = 70
            sprite_view["tint_g"][sprite_row] = 225
            sprite_view["tint_b"][sprite_row] = 225
        # Polaridade: pesadas (Parry, aceitam QUALQUER cor) mantem o
        # visual heavy de sempre -- so as comuns (cuja cor IMPORTA para
        # o julgamento) ganham a forma+tint real azul/rosa (Gemeos
        # inclusos: nascem com `threat_type` proprio, mas NAO e o de
        # pesada/orbital, entao caem neste ramo normalmente).
        # Acessibilidade a daltonismo: a forma (triangulo/quadrado) nunca
        # depende so do tint -- ver `HBPygameRenderer.draw_batch`.
        elif self._polarity_enabled and base_texture_id != TEX_THREAT_HEAVY:
            is_pink = int(threat_view["polarity_id"][threat_row]) == POLARITY_PINK
            sprite_view["texture_id"][sprite_row] = (
                TEX_THREAT_POLARITY_PINK if is_pink else TEX_THREAT_POLARITY_BLUE
            )
            if is_pink:
                sprite_view["tint_r"][sprite_row] = 255
                sprite_view["tint_g"][sprite_row] = 90
                sprite_view["tint_b"][sprite_row] = 190
            else:
                sprite_view["tint_r"][sprite_row] = 70
                sprite_view["tint_g"][sprite_row] = 140
                sprite_view["tint_b"][sprite_row] = 255
        else:
            sprite_view["texture_id"][sprite_row] = base_texture_id
            sprite_view["tint_r"][sprite_row] = 255
            sprite_view["tint_g"][sprite_row] = 64 + int(120.0 * (1.0 - strength))
            sprite_view["tint_b"][sprite_row] = 80
        sprite_view["tint_a"][sprite_row] = 255
        sprite_view["layer_z"][sprite_row] = 20

        if self._ring_archetype_name is not None:
            self._spawn_convergence_ring(world, hit_time, time_remaining, sprite_view, sprite_row)

    def _spawn_convergence_ring(
        self, world: World, hit_time: float, travel_seconds: float,
        threat_sprite_view, threat_sprite_row: int,
    ) -> None:
        """Anel-aviso centrado no nucleo, na COR da ameaca: o
        `ConvergenceRingSystem` encolhe seu raio ate o anel de julgamento
        exatamente em `hit_time` (mesma base de tempo do julgamento)."""
        ring_packed = world.create_entity(self._ring_archetype_name)
        ring_index = unpack_index(ring_packed)

        ring_row = self._ring_pool.dense_row_of(ring_index)
        ring_view = self._ring_pool.active_view()
        ring_view["target_hit_time_sec"][ring_row] = hit_time
        ring_view["travel_seconds"][ring_row] = travel_seconds
        ring_view["packed_handle"][ring_row] = ring_packed

        transform_row = self._transform_pool.dense_row_of(ring_index)
        transform_view = self._transform_pool.active_view()
        transform_view["position_x"][transform_row] = self._center_x
        transform_view["position_y"][transform_row] = self._center_y
        transform_view["scale_x"][transform_row] = self._spawn_radius / 8.0
        transform_view["scale_y"][transform_row] = self._spawn_radius / 8.0

        sprite_row = self._sprite_pool.dense_row_of(ring_index)
        sprite_view = self._sprite_pool.active_view()
        sprite_view["texture_id"][sprite_row] = TEX_CONVERGENCE_RING
        sprite_view["tint_r"][sprite_row] = threat_sprite_view["tint_r"][threat_sprite_row]
        sprite_view["tint_g"][sprite_row] = threat_sprite_view["tint_g"][threat_sprite_row]
        sprite_view["tint_b"][sprite_row] = threat_sprite_view["tint_b"][threat_sprite_row]
        sprite_view["tint_a"][sprite_row] = 88
        sprite_view["layer_z"][sprite_row] = 6  # atras das ameacas e do nucleo
