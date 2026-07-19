"""Modo Arcade 4K: notas caem em 4 colunas rumo a linha de julgamento (estilo FNF/VSRG)."""
from __future__ import annotations

import math

import numpy as np

from ouroboros.core.memory.handles import PackedEntityId, unpack_index
from ouroboros.core.memory.memory_manager import MemoryManager
from ouroboros.core.world import World
from ouroboros.interfaces.audio_clock import IAudioClock
from ouroboros.rhythm.runtime.rhythm_spawner_system import RhythmSpawnerSystem

from hertzbeats.components.schemas import JUDGMENT_PENDING, MODE_TAG_LANES

LANE_COUNT_4K: int = 4
"""Numero fixo de colunas do modo Arcade (D/F/J/K)."""


class LaneNoteSpawnerSystem(RhythmSpawnerSystem):
    """
    Estrategia de spawn do modo Arcade 4K sobre o MESMO `beatmap.json`:
    e o `RhythmSpawnerSystem` da engine materializando cada evento como
    uma NOTA que cai verticalmente e cruza a linha de julgamento
    exatamente em `target_hit_time_sec`.

    Interpretacao espacial dos campos do beatmap:
        - `lane % 4` escolhe a coluna (distribuicao deterministica dos
          dados do JSON). O campo `lane` da pool e REESCRITO com a
          coluna final (0..3) para o `LaneJudgmentSystem` comparar por
          igualdade vetorizada.
        - ROTEAMENTO POR CAMADA (beatmaps "hybrid" da engine): quando o
          beatmap traz a tag `layer`, kicks vao para as EXTREMIDADES
          (colunas 0/3 -- maos externas seguram o groove) e vocais para
          o CENTRO (colunas 1/2 -- a melodia corre por dentro), com a
          paridade da lane original escolhendo o lado. Beatmaps de
          camada unica mantem a distribuicao por timbre.
        - `threat_type`/`strength` ditam o tamanho/brilho da nota.

    Cinematica: `velocidade_y = (linha_julgamento - y_spawn) / tempo_restante`
    (mesma compensacao de atraso de frame dos outros modos: spawn tardio
    cai proporcionalmente mais rapido e cruza a linha na batida).
    """

    def __init__(
        self,
        audio_clock: IAudioClock,
        memory_manager: MemoryManager,
        scheduled_spawns: np.ndarray,
        hit_times: np.ndarray,
        threat_archetype_name: str,
        lane_center_xs: np.ndarray,
        spawn_y: float,
        judgment_line_y: float,
        note_half_by_type: np.ndarray,
        lane_tints_rgb: np.ndarray,
        max_threats_per_frame: int,
        min_travel_seconds: float = 0.05,
        is_hold_by_row: np.ndarray = None,
        hold_end_by_row: np.ndarray = None,
        hold_threat_type_id: int = None,
        hold_duration_seconds: float = 0.0,
        hold_visual_max_fraction: float = 0.35,
    ) -> None:
        """`lane_center_xs` (float64, len 4) e `lane_tints_rgb`
        (uint8, shape (4,3)) sao pre-computados na composicao.

        `is_hold_by_row`/`hold_end_by_row` (opcionais, paralelos a
        `scheduled_spawns`/`hit_times`): marcam quais linhas sao notas
        de SCRATCH (clusters de pesadas fundidos por
        `lane_scratch_clustering`) e o instante em que o hold termina.
        Vivem FORA do `SCHEDULED_THREAT_DTYPE` da engine -- schema
        neutro, so este produto sabe o que e um "hold".

        NOTA LONGA CLASSICA (`duration_sec`, opt-in via
        `hold_threat_type_id`, mutuamente exclusiva do Scratch por
        construcao -- ver `_create_threat_entity`): toda pesada que NAO
        entrou num cluster de Scratch vira uma nota longa comum de
        tecla sustentada (`duration_sec = hold_duration_seconds`), a
        interpretacao do Arcade 4K para o mesmo campo mode-agnostico que
        o Defensor ja usa para o Hold por fire+mira sustentados.

        A barra caida representaria `hold_duration_seconds` na MESMA
        velocidade de queda da nota -- sem teto, uma duracao comparavel
        a `approach_seconds` cobriria quase a tela inteira.
        `hold_visual_max_fraction` limita o comprimento RENDERIZADO da
        barra a essa fracao da distancia total de queda; a duracao real
        exigida do jogador nunca muda, so o desenho.
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
        self._lane_center_xs = lane_center_xs
        self._spawn_y = float(spawn_y)
        self._judgment_line_y = float(judgment_line_y)
        self._note_half_by_type = note_half_by_type
        self._lane_tints_rgb = lane_tints_rgb
        self._min_travel_seconds = float(min_travel_seconds)
        self._is_hold_by_row = is_hold_by_row
        self._hold_end_by_row = hold_end_by_row
        self._hold_threat_type_id = hold_threat_type_id
        self._hold_duration_seconds = float(hold_duration_seconds)
        self._hold_visual_max_px = (self._judgment_line_y - self._spawn_y) * float(hold_visual_max_fraction)
        # roteamento kick/vocal so faz sentido em beatmaps MULTI-camada;
        # num mapa de camada unica ele colapsaria tudo em 2 colunas
        self._route_by_layer = bool(np.any(scheduled_spawns["layer"] != 0)) if scheduled_spawns.shape[0] else False

    def _create_threat_entity(self, world: World, row_index: int) -> PackedEntityId:
        """Materializa a nota do evento `row_index` na sua coluna."""
        packed = super()._create_threat_entity(world, row_index)
        entity_index = unpack_index(packed)

        threat_row = self._threat_pool.dense_row_of(entity_index)
        threat_view = self._threat_pool.active_view()
        threat_type = int(threat_view["threat_type"][threat_row])
        original_lane = int(threat_view["lane"][threat_row])
        if self._route_by_layer:
            # kick -> extremidades (0/3), vocal -> centro (1/2); a
            # paridade da lane de timbre escolhe o lado
            if int(self._scheduled_threats["layer"][row_index]) == 1:  # vocal
                lane = 1 + (original_lane % 2)
            else:
                lane = 3 * (original_lane % 2)
        else:
            lane = original_lane % LANE_COUNT_4K
        threat_view["lane"][threat_row] = lane  # coluna 0..3 para o julgamento

        hit_time = float(self._hit_times[row_index])
        time_remaining = hit_time - self._compute_effective_time()
        if time_remaining < self._min_travel_seconds:
            time_remaining = self._min_travel_seconds
        fall_speed = (self._judgment_line_y - self._spawn_y) / time_remaining

        is_hold = bool(self._is_hold_by_row[row_index]) if self._is_hold_by_row is not None else False
        hold_end = float(self._hold_end_by_row[row_index]) if is_hold else hit_time

        # Nota longa classica: so pesadas que NAO foram fundidas num
        # cluster de Scratch (`is_hold=False`) podem ser reinterpretadas
        # -- as duas mecanicas nunca disputam a mesma linha.
        is_classic_hold = (
            not is_hold
            and self._hold_threat_type_id is not None
            and threat_type == self._hold_threat_type_id
        )
        duration_sec = self._hold_duration_seconds if is_classic_hold else 0.0
        classic_hold_end = hit_time + duration_sec if is_classic_hold else hit_time

        strength = float(self._scheduled_threats["strength"][row_index])
        threat_view["mode_tag"][threat_row] = MODE_TAG_LANES
        threat_view["strength"][threat_row] = strength
        threat_view["target_hit_time_sec"][threat_row] = hit_time
        threat_view["expire_time_sec"][threat_row] = hold_end
        threat_view["duration_sec"][threat_row] = duration_sec
        threat_view["spawn_angle_rad"][threat_row] = math.pi / 2.0  # caindo (tela, y para baixo)
        threat_view["is_hit"][threat_row] = False
        threat_view["is_hold"][threat_row] = is_hold
        threat_view["judgment"][threat_row] = JUDGMENT_PENDING
        threat_view["packed_handle"][threat_row] = packed

        note_half = float(self._note_half_by_type[threat_type])
        transform_row = self._transform_pool.dense_row_of(entity_index)
        transform_view = self._transform_pool.active_view()
        transform_view["position_x"][transform_row] = float(self._lane_center_xs[lane])
        transform_view["position_y"][transform_row] = self._spawn_y
        # notas 1.7x maiores que o meio-tamanho logico: legibilidade da
        # queda importa mais que o volume exato (nao ha colisao no 4K).
        # Scratch (hold): a barra e esticada ao longo de Y pela duracao
        # do hold * velocidade de queda -- aproximacao ESTATICA (nao
        # encolhe conforme cai), suficiente para o efeito visual de
        # "nota longa" sem complicar a cinematica.
        if is_hold:
            hold_span_px = (hold_end - hit_time) * fall_speed
            transform_view["scale_x"][transform_row] = note_half * 1.1 / 8.0
            transform_view["scale_y"][transform_row] = max(note_half * 1.7, hold_span_px / 2.0) / 8.0
        elif is_classic_hold:
            # teto de comprimento visual (ver docstring do construtor):
            # a duracao exigida do jogador (`duration_sec`) nao muda,
            # so o quanto da queda a barra ocupa na tela.
            hold_span_px = min((classic_hold_end - hit_time) * fall_speed, self._hold_visual_max_px)
            transform_view["scale_x"][transform_row] = note_half * 1.1 / 8.0
            transform_view["scale_y"][transform_row] = max(note_half * 1.7, hold_span_px / 2.0) / 8.0
        else:
            transform_view["scale_x"][transform_row] = note_half * 1.7 / 8.0
            transform_view["scale_y"][transform_row] = note_half * 1.7 / 8.0

        velocity_row = self._velocity_pool.dense_row_of(entity_index)
        velocity_view = self._velocity_pool.active_view()
        velocity_view["linear_x"][velocity_row] = 0.0
        velocity_view["linear_y"][velocity_row] = fall_speed
        velocity_view["angular"][velocity_row] = 0.0

        # sem CollisionSystem neste modo: hitbox neutra (layer/mask 0)
        hitbox_row = self._hitbox_pool.dense_row_of(entity_index)
        hitbox_view = self._hitbox_pool.active_view()
        hitbox_view["half_width"][hitbox_row] = note_half
        hitbox_view["half_height"][hitbox_row] = note_half
        hitbox_view["collision_layer"][hitbox_row] = 0
        hitbox_view["collision_mask"][hitbox_row] = 0

        sprite_row = self._sprite_pool.dense_row_of(entity_index)
        sprite_view = self._sprite_pool.active_view()
        sprite_view["texture_id"][sprite_row] = 0  # circulo/barra procedural
        if is_hold:
            # branco/dourado vibrante: destaca a nota de scratch das
            # demais (a "mesa do DJ")
            sprite_view["tint_r"][sprite_row] = 255
            sprite_view["tint_g"][sprite_row] = 240
            sprite_view["tint_b"][sprite_row] = 180
        elif is_classic_hold:
            # ciano: distingue a nota longa classica (tecla sustentada)
            # tanto do Scratch (dourado) quanto das notas normais (cor
            # da coluna)
            sprite_view["tint_r"][sprite_row] = 120
            sprite_view["tint_g"][sprite_row] = 230
            sprite_view["tint_b"][sprite_row] = 255
        else:
            sprite_view["tint_r"][sprite_row] = self._lane_tints_rgb[lane, 0]
            sprite_view["tint_g"][sprite_row] = self._lane_tints_rgb[lane, 1]
            sprite_view["tint_b"][sprite_row] = self._lane_tints_rgb[lane, 2]
        sprite_view["tint_a"][sprite_row] = 255
        sprite_view["layer_z"][sprite_row] = 20

        return packed
