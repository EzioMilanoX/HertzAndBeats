"""GameLoop da engine estendido com o fluxo de partida: menu de fases, pausa, derrota e resultados."""
from __future__ import annotations

import dataclasses
import random
import time
from typing import Optional, Tuple

import numpy as np

from ouroboros.bootstrap.game_loop import (
    _EMPTY_F32,
    _EMPTY_I16,
    _EMPTY_RGBA,
    _EMPTY_U32,
    _EMPTY_XY,
    GameLoop,
)
from ouroboros.core.memory.component_pool import intersect_entity_indices
from ouroboros.interfaces.audio_clock import IAudioClock
from ouroboros.interfaces.audio_engine import IAudioEngine
from ouroboros.interfaces.input_provider import IInputProvider
from ouroboros.interfaces.renderer import IRenderer

from hertzbeats.audio.demo_track_synth import ensure_track
from hertzbeats.bootstrap.rhythm_composition_root import (
    ComposedGame,
    compose_world,
    lane_center_positions,
)
from hertzbeats.components.schemas import MODE_TAG_LANES
from hertzbeats.config import HertzConfig
from hertzbeats.stages import StageDef, resolve_stage_config

FLOW_MENU = "menu"
FLOW_PLAYING = "playing"
FLOW_PAUSED = "paused"
FLOW_GAME_OVER = "game_over"
FLOW_RESULTS = "results"

_RESULTS_GRACE_SECONDS = 1.0
"""Pausa dramatica entre a ultima ameaca resolvida e a tela de resultados."""

_LATENCY_STEP_SECONDS = 0.01
_LATENCY_MAX_SECONDS = 0.30
_NOTICE_SECONDS = 1.6

MODE_CYCLE = (
    "defender",
    "lanes",
    "polarity",
    "holds",
    "lanes_holds",
)
"""Ordem em que A/D alternam o modo nas musicas do jogador. As variantes
finais continuam sendo os modos base por baixo -- so acrescentam
`polarity_enabled`/`holds_enabled` (ver `MODE_VARIANT_OVERRIDES`) --
mesmas mecanicas das fases curadas."""

MODE_VARIANT_OVERRIDES = {
    "defender": {"game_mode": "defender"},
    "lanes": {"game_mode": "lanes"},
    "polarity": {"game_mode": "defender", "polarity_enabled": True},
    "holds": {"game_mode": "defender", "holds_enabled": True},
    "lanes_holds": {"game_mode": "lanes", "holds_enabled": True},
}
"""Campos de `HertzConfig` sobrescritos por variante escolhida no menu
das musicas do jogador -- resolvido UMA vez por `_compose_stage`, o
mesmo `dataclasses.replace` que as fases curadas usam via `overrides`
de `stages.json`. `polarity_enabled`/`holds_enabled` nao aparecem nas
variantes que nao os usam porque a config BASE ja os tem como `False`
(nenhuma leva residual entre trocas: `stage_config` e reconstruida do
zero a cada `_compose_stage`). "lanes_holds": Hold classico + Shield no
Arcade 4K, agora disponivel para QUALQUER musica sua."""


class HertzGameLoop(GameLoop):
    """
    `GameLoop` da engine estendido com a maquina de estados da partida:

        MENU -> (confirmar) -> PLAYING <-> PAUSED
        PLAYING -> vida zerada -> GAME_OVER -> (R) repete / (M) menu
        PLAYING -> fase limpa  -> RESULTS  -> (ENTER) proxima fase /
                                              (R) repete / (M) menu

    Papel arquitetural: o fluxo NAO vive em nenhum `ISystem` -- sistemas
    julgam UMA fase em andamento; trocar/reiniciar fase e recomposicao
    (fase de carregamento, onde alocar e permitido). Cada
    `_start_stage` recompoe o `World` inteiro via `compose_world` (pools
    novas, `GameState` zerado, cursor do spawner em 0) e reinicia a
    faixa do zero -- nenhum estado de partida anterior sobrevive por
    acidente.

    PAUSA SEM DRIFT: pausar congela a musica (`pause_track`, quando o
    backend oferece -- `pygame.mixer.music.pause` congela `get_pos`).
    Como TODOS os sistemas ritmicos leem exclusivamente o `IAudioClock`,
    o gameplay inteiro congela em sincronia; ao retomar, nada precisa
    ser re-calibrado. `world.step` simplesmente nao e chamado enquanto
    pausado/menu/telas finais -- mas o frame continua sendo renderizado
    (arena visivel ao fundo dos overlays).

    Os overlays (menu/PAUSADO/GAME OVER/FASE CONCLUIDA) sao desenhados
    pelo adapter concreto via `set_overlay` (superficies pre-
    renderizadas na composicao); com um renderer sem esse metodo (ex.:
    `NullRenderer` nos testes headless), o fluxo roda identico, apenas
    sem apresentacao.
    """

    def __init__(
        self,
        base_config: HertzConfig,
        stages: Tuple[StageDef, ...],
        renderer: IRenderer,
        input_provider: IInputProvider,
        audio_engine: IAudioEngine,
        audio_clock: IAudioClock,
    ) -> None:
        """Compoe a fase 0 imediatamente (sem tocar musica) para que o
        menu ja tenha uma arena renderizavel ao fundo."""
        self._base_config = base_config
        self._stages = stages
        self._audio_clock = audio_clock
        self._input_provider = input_provider  # tambem setado por GameLoop.__init__
        self._audio_engine = audio_engine  # idem -- precisa existir ANTES de _compose_stage(0) abaixo
        self._selected_stage = 0
        self._loaded_stage = 0
        self._flow = FLOW_MENU
        self._results_grace = 0.0
        self._notice_key: Optional[str] = None
        self._notice_timer = 0.0
        self._chosen_mode_index = {}  # fase selectable_mode -> indice em MODE_CYCLE
        self._practice_mode: dict = {}  # fase selectable_mode -> Modo Treino ligado?
        self._composed: Optional[ComposedGame] = None
        self._was_in_flow = False
        self._was_frozen = False

        composed = self._compose_stage(0)
        super().__init__(
            composed.world,
            renderer,
            input_provider,
            audio_engine,
            target_fps=base_config.target_fps,
        )
        self._apply_playfield()

    @property
    def flow(self) -> str:
        """Estado atual do fluxo de partida (telemetria/testes)."""
        return self._flow

    @property
    def composed(self) -> ComposedGame:
        """Composicao da fase atualmente carregada."""
        return self._composed

    @property
    def selected_stage(self) -> int:
        """Indice da fase selecionada no menu."""
        return self._selected_stage

    @property
    def loaded_stage(self) -> int:
        """Indice da fase atualmente composta/carregada."""
        return self._loaded_stage

    # -- carga/troca de fase (fase de carregamento: alocacao permitida) --

    def chosen_mode(self, stage_index: int) -> str:
        """Modo escolhido no menu para uma fase `selectable_mode` (as
        musicas do jogador); fases curadas usam o modo dos overrides."""
        return MODE_CYCLE[self._chosen_mode_index.get(stage_index, 0) % len(MODE_CYCLE)]

    def practice_mode_on(self, stage_index: int) -> bool:
        """Modo Treino ligado para uma fase `selectable_mode` (musicas
        do jogador) -- densidade de onsets reduzida e sem dano de vida.
        Fases curadas do repositorio nunca tem Modo Treino (so a fase
        escolhida no menu, tecla T)."""
        return self._practice_mode.get(stage_index, False)

    def _compose_stage(self, stage_index: int) -> ComposedGame:
        """Recompoe o `World` inteiro para a fase `stage_index` e garante
        que a faixa exista (re-sintese deterministica se necessario)."""
        stage = self._stages[stage_index]
        stage_config = resolve_stage_config(self._base_config, stage)
        if stage.selectable_mode:
            stage_config = dataclasses.replace(
                stage_config,
                practice_mode=self._practice_mode.get(stage_index, False),
                **MODE_VARIANT_OVERRIDES[self.chosen_mode(stage_index)],
            )
        if stage.track_path:
            ensure_track(stage.track_path, stage.synth)
        composed = compose_world(
            stage_config,
            self._input_provider,
            self._audio_clock,
            tutorial_steps=stage.tutorial_steps,
            stage_ordinal=stage_index,
            audio_engine=self._audio_engine,
            modchart_events=stage.modchart_events,
        )
        self._composed = composed
        self._stage_config = stage_config
        self._loaded_stage = stage_index
        self._world = composed.world  # GameLoop renderiza sempre o world da fase carregada
        return composed

    def _apply_playfield(self) -> None:
        """Sincroniza a decoracao de arena do renderer com o MODO da fase
        carregada (no-op com renderer sem suporte, ex. NullRenderer)."""
        renderer = getattr(self, "_renderer", None)
        if renderer is None or not hasattr(renderer, "set_playfield"):
            return
        config = self._stage_config
        mode = config.game_mode
        if mode == "defender":
            center_x, center_y = config.center_xy
            renderer.set_playfield(
                "radial",
                center_x=center_x,
                center_y=center_y,
                spawn_radius=config.spawn_radius,
                judgment_radius=config.core_half_extent
                + config.threat_half_extents.get("rhythm_threat_basic", 10.0),
                width=config.window_width,
                height=config.window_height,
            )
        elif mode == "lanes":
            renderer.set_playfield(
                "lanes",
                lane_xs=lane_center_positions(config).tolist(),
                lane_half_width=config.lane_spacing * 0.42,
                judgment_y=config.window_height - config.judgment_line_offset,
                width=config.window_width,
                height=config.window_height,
            )
        else:
            renderer.set_playfield(None)

    def _sync_lane_playfield(self) -> None:
        """Modcharts (Arcade 4K): mantem a decoracao de fundo das
        colunas (`renderer.set_playfield("lanes", ...)`) em sincronia
        com a posicao ATUAL calculada pelo `LaneChoreographySystem`
        (Swap com Lerp + Pistas Dinamicas) e, no eixo Y, pelo
        `ReverseScrollSystem` (Inversao de Gravidade) -- sem isso, a
        decoracao de fundo ficaria parada enquanto notas/receptores se
        movem por cima dela. No-op fora do modo Arcade 4K ou com um
        renderer sem suporte a playfield (ex. NullRenderer)."""
        if self._composed is None or self._stage_config.game_mode != "lanes":
            return
        choreography = self._composed.lane_choreography_system
        renderer = getattr(self, "_renderer", None)
        if choreography is None or renderer is None or not hasattr(renderer, "set_playfield"):
            return
        config = self._stage_config
        geometry_y = self._composed.lane_geometry_y
        judgment_y = (
            float(geometry_y[1]) if geometry_y is not None
            else config.window_height - config.judgment_line_offset
        )
        renderer.set_playfield(
            "lanes",
            lane_xs=choreography.current_lane_xs.tolist(),
            lane_half_width=config.lane_spacing * 0.42,
            judgment_y=judgment_y,
            width=config.window_width,
            height=config.window_height,
        )

    def _flow_base_volume(self) -> float:
        """Volume 'normal' da faixa fora do Flow State: um pouco abaixo
        do maximo, para que a entrada no Flow tenha um SWELL real ate
        1.0 (ver `HBPygameAudioEngine.set_track_volume`)."""
        return max(0.0, 1.0 - self._stage_config.flow_volume_boost)

    def _start_stage(self, stage_index: int) -> None:
        """Recompoe a fase e inicia a musica do zero -> PLAYING."""
        self._compose_stage(stage_index)
        self._apply_playfield()
        stage = self._stages[stage_index]
        if stage.track_path:
            self._audio_engine.load_track(stage.stage_id, stage.track_path)
            self._audio_engine.play_track(stage.stage_id)
        self._was_in_flow = False
        if hasattr(self._audio_engine, "set_track_volume"):
            self._audio_engine.set_track_volume(self._flow_base_volume())
        if hasattr(self._renderer, "set_flow_mode"):
            self._renderer.set_flow_mode(False)
        self._flow = FLOW_PLAYING
        self._results_grace = 0.0

    def start_stage(self, stage_index: int) -> None:
        """Entrada publica: pula o menu e inicia `stage_index` direto
        (usada pelo atalho de CLI `--stage`)."""
        self._selected_stage = stage_index % len(self._stages)
        self._start_stage(self._selected_stage)

    def _stop_music(self) -> None:
        stage = self._stages[self._loaded_stage]
        if stage.track_path:
            self._audio_engine.stop_track(stage.stage_id)

    def _pause_music(self) -> None:
        if hasattr(self._audio_engine, "pause_track"):
            self._audio_engine.pause_track()

    def _resume_music(self) -> None:
        if hasattr(self._audio_engine, "resume_track"):
            self._audio_engine.resume_track()

    # -- maquina de estados por frame ------------------------------------

    def _adjust_latency(self, direction: int) -> None:
        """Calibracao AO VIVO da latencia de audio (teclas +/-): se as
        ameacas parecem chegar ANTES do som, aumente; DEPOIS, diminua.
        O novo valor vale imediatamente (spawner/julgamento leem o
        relogio compensado) e e persistido ao sair do jogo."""
        current = self._audio_clock.get_output_latency_seconds()
        new_value = current + direction * _LATENCY_STEP_SECONDS
        new_value = min(max(round(new_value, 2), 0.0), _LATENCY_MAX_SECONDS)
        self._audio_clock.calibrate_latency(new_value)
        self._notice_key = f"latency_{int(round(new_value * 100))}"
        self._notice_timer = _NOTICE_SECONDS

    def _handle_latency_keys(self) -> None:
        inp = self._input_provider
        if inp.is_action_pressed("latency_up"):
            self._adjust_latency(+1)
        if inp.is_action_pressed("latency_down"):
            self._adjust_latency(-1)

    def advance_frame(self, delta_time: float) -> None:
        """Um frame do fluxo: trata as acoes de meta-jogo do estado atual
        e, apenas em PLAYING, avanca a simulacao (`world.step`)."""
        if self._notice_timer > 0.0:
            self._notice_timer -= delta_time
        if self._flow in (FLOW_PLAYING, FLOW_PAUSED):
            self._handle_latency_keys()
        if self._flow == FLOW_MENU:
            self._advance_menu()
        elif self._flow == FLOW_PLAYING:
            self._advance_playing(delta_time)
        elif self._flow == FLOW_PAUSED:
            self._advance_paused()
        elif self._flow == FLOW_GAME_OVER:
            self._advance_game_over()
        elif self._flow == FLOW_RESULTS:
            self._advance_results()

    def _advance_menu(self) -> None:
        inp = self._input_provider
        stage_count = len(self._stages)
        if inp.is_action_pressed("menu_down"):
            self._selected_stage = (self._selected_stage + 1) % stage_count
        if inp.is_action_pressed("menu_up"):
            self._selected_stage = (self._selected_stage - 1) % stage_count

        # musicas do jogador: A/D (ou setas) alternam o minigame; T liga/
        # desliga o Modo Treino (densidade reduzida + sem dano de vida --
        # util para uma fase recem-mapeada pela IA e ainda desconhecida).
        if self._stages[self._selected_stage].selectable_mode:
            direction = 0
            if inp.is_action_pressed("menu_right"):
                direction = 1
            if inp.is_action_pressed("menu_left"):
                direction = -1
            if direction != 0:
                current = self._chosen_mode_index.get(self._selected_stage, 0)
                self._chosen_mode_index[self._selected_stage] = (current + direction) % len(MODE_CYCLE)
            if inp.is_action_pressed("toggle_practice"):
                self._practice_mode[self._selected_stage] = not self.practice_mode_on(self._selected_stage)

        if inp.is_action_pressed("confirm") or inp.is_action_pressed("fire"):
            self._start_stage(self._selected_stage)
        elif inp.is_action_pressed("pause"):
            self.stop()  # ESC no menu encerra o jogo

    def _advance_playing(self, delta_time: float) -> None:
        inp = self._input_provider
        if inp.is_action_pressed("pause"):
            self._flow = FLOW_PAUSED
            self._pause_music()
            return

        self._world.step(delta_time)

        state = self._composed.game_state
        self._advance_flow_state(state)
        if state.health <= 0:
            self._flow = FLOW_GAME_OVER
            self._stop_music()
            return

        # Fase concluida quando TODOS os spawners consumiram seus
        # beatmaps (o Hibrido tem dois) E (todas as ameacas foram
        # resolvidas OU a musica acabou). O segundo caso e o guard
        # anti-softlock: quando a faixa termina, o relogio de audio
        # congela (pygame get_pos() volta -1 -> 0) e qualquer ameaca
        # restante ficaria eternamente sem veredito -- a fase encerra
        # mesmo assim, pela carencia em tempo real de frame.
        threat_pool = self._composed.memory_manager.get_pool("rhythm_threat")
        music_over = not self._audio_clock.is_playing()
        if self._composed.all_spawners_finished and (threat_pool.count == 0 or music_over):
            self._results_grace += delta_time
            if self._results_grace >= _RESULTS_GRACE_SECONDS:
                self._flow = FLOW_RESULTS
        else:
            self._results_grace = 0.0

    def _advance_flow_state(self, state) -> None:
        """Flow State ("vidro quebrado", Arcade 4K): detecta a
        TRANSICAO de combo cruzando `flow_combo_threshold` (o
        `UIRenderSystem` ja decide isso por conta propria a cada frame
        para o HUD -- aqui so replicamos a mesma condicao para acionar os
        efeitos que vivem FORA do ECS: swell/restauracao de volume da
        faixa e escurecimento de fundo do renderer; a saida (um Miss
        zera o combo) dispara o aviso de "vidro quebrado".

        Sem HUD, o jogador perde a nocao de progresso alem do limiar --
        `tier` (`combo // limiar`, 0 fora do Flow) e sincronizado com o
        renderer TODO frame (nao so na transicao: o tier sobe DENTRO do
        Flow, sem cruzar o limiar de novo), pulsando a linha de
        julgamento a cada 50 acertos extras."""
        config = self._stage_config
        if config.game_mode != "lanes":
            return
        in_flow_now = state.combo_count >= config.flow_combo_threshold
        if hasattr(self._renderer, "set_flow_tier"):
            tier = (state.combo_count // config.flow_combo_threshold) if in_flow_now else 0
            self._renderer.set_flow_tier(tier)
        if in_flow_now == self._was_in_flow:
            return
        if hasattr(self._audio_engine, "set_track_volume"):
            self._audio_engine.set_track_volume(1.0 if in_flow_now else self._flow_base_volume())
        if hasattr(self._renderer, "set_flow_mode"):
            self._renderer.set_flow_mode(in_flow_now)
        if not in_flow_now:
            self._notice_key = "flow_shatter"
            self._notice_timer = config.flow_shatter_seconds
        self._was_in_flow = in_flow_now

    def _advance_paused(self) -> None:
        inp = self._input_provider
        if inp.is_action_pressed("pause"):
            self._flow = FLOW_PLAYING
            self._resume_music()
        elif inp.is_action_pressed("to_menu"):
            self._stop_music()
            self._flow = FLOW_MENU

    def _advance_game_over(self) -> None:
        inp = self._input_provider
        if inp.is_action_pressed("retry"):
            self._start_stage(self._loaded_stage)
        elif inp.is_action_pressed("to_menu") or inp.is_action_pressed("pause"):
            self._flow = FLOW_MENU

    def _advance_results(self) -> None:
        inp = self._input_provider
        if inp.is_action_pressed("confirm"):
            self._selected_stage = (self._loaded_stage + 1) % len(self._stages)
            self._start_stage(self._selected_stage)
        elif inp.is_action_pressed("retry"):
            self._start_stage(self._loaded_stage)
        elif inp.is_action_pressed("to_menu") or inp.is_action_pressed("pause"):
            self._stop_music()
            self._flow = FLOW_MENU

    # -- laco principal ---------------------------------------------------

    def _sync_overlay(self) -> None:
        """Publica o estado do fluxo no renderer concreto (no-op com um
        renderer sem suporte a overlay, ex. NullRenderer)."""
        if hasattr(self._renderer, "set_overlay"):
            overlay_mode = None if self._flow == FLOW_PLAYING else self._flow
            is_selectable = self._stages[self._selected_stage].selectable_mode
            selected_mode = self.chosen_mode(self._selected_stage) if is_selectable else None
            practice_enabled = self.practice_mode_on(self._selected_stage) if is_selectable else None
            self._renderer.set_overlay(
                overlay_mode, self._selected_stage, len(self._stages),
                selected_mode=selected_mode, practice_enabled=practice_enabled,
            )
        if hasattr(self._renderer, "set_notice"):
            self._renderer.set_notice(self._notice_key if self._notice_timer > 0.0 else None)

    def _sync_camera_shake(self) -> None:
        """Traduz `GameState.shake_intensity` (decaido pelo
        `CameraShakeSystem` a cada `world.step`, comum aos 3 modos) num
        offset ALEATORIO real via `IRenderer.set_camera_offset` -- metodo
        JA EXISTENTE na engine (ROADMAP M1/M2), so nunca tinha um
        chamador no jogo ate agora. Mesma familia de sincronizacao
        apresentacao<-estado de `_sync_overlay` (nunca dentro de um
        `ISystem`); `random.uniform` aqui e puramente cosmetico -- nao
        decide nenhum veredito de jogabilidade, entao nao esta sob a
        disciplina Zero-GC do gameplay."""
        if not hasattr(self._renderer, "set_camera_offset") or self._composed is None:
            return
        intensity = self._composed.game_state.shake_intensity
        if intensity <= 0.0:
            self._renderer.set_camera_offset(0.0, 0.0)
            return
        self._renderer.set_camera_offset(
            random.uniform(-intensity, intensity), random.uniform(-intensity, intensity)
        )

    def _sync_blindness(self) -> None:
        """Vignette Flash: traduz `GameState.is_blinded` (decaido pelo
        `CameraShakeSystem` a cada `world.step`) num liga/desliga real
        via `IRenderer.set_blindness_active` -- mesma familia de
        sincronizacao apresentacao<-estado de `_sync_camera_shake`."""
        if not hasattr(self._renderer, "set_blindness_active") or self._composed is None:
            return
        self._renderer.set_blindness_active(self._composed.game_state.is_blinded)

    def _sync_hitlag(self) -> None:
        """Juice de Parry (Hitlag Visual Simulado): traduz
        `GameState.visual_freeze_frames` (decaido pelo `CameraShakeSystem`
        a cada `world.step`, comum aos 3 modos) num liga/desliga real via
        `IRenderer.set_freeze_active` -- mesma familia de sincronizacao
        de `_sync_camera_shake`/`_sync_blindness`. A TRANSICAO de
        congelado->normal e detectada AQUI (`_was_frozen`, mesmo padrao
        ja usado por `_was_in_flow` no Flow State) para armar o flash de
        cor invertida por EXATAMENTE 1 frame -- o instante em que "a
        tela volta". `GameState.invert_colors` e consumido (resetado a
        `False`) no exato momento em que o flash e armado, nunca por
        nenhum `ISystem`."""
        if self._composed is None:
            return
        state = self._composed.game_state
        freeze_active = state.visual_freeze_frames > 0
        if hasattr(self._renderer, "set_freeze_active"):
            self._renderer.set_freeze_active(freeze_active)

        just_unfroze = self._was_frozen and not freeze_active
        flash = just_unfroze and state.invert_colors
        if hasattr(self._renderer, "set_color_invert"):
            self._renderer.set_color_invert(flash)
        if flash:
            state.invert_colors = False
        self._was_frozen = freeze_active

    def _render_frame(self) -> None:
        """Override do `GameLoop` da engine: MESMA coleta SoA de
        `transform`+`sprite`, mas aplicando o Stutter Scroll (ruido
        visual em Y, Arcade 4K) so NESTE array temporario, no momento
        do `draw_batch` -- `transform.position_y` (a fisica real que o
        `PhysicsSystem`/`LaneJudgmentSystem` usam) nunca e escrito
        aqui, entao nao ha deriva acumulada frame a frame (o mesmo
        cuidado pedido para o efeito)."""
        transform_pool = self._world.get_pool("transform")
        sprite_pool = self._world.get_pool("sprite")
        entity_indices = intersect_entity_indices(transform_pool, sprite_pool)
        count = int(entity_indices.shape[0])

        self._renderer.begin_frame()
        if count == 0:
            self._renderer.draw_batch(_EMPTY_XY, _EMPTY_F32, _EMPTY_XY, _EMPTY_U32, _EMPTY_RGBA, _EMPTY_I16, 0)
        else:
            t_rows = transform_pool.dense_rows_of(entity_indices)
            s_rows = sprite_pool.dense_rows_of(entity_indices)
            t_view = transform_pool.active_view()
            s_view = sprite_pool.active_view()

            positions_xy = np.stack([t_view["position_x"][t_rows], t_view["position_y"][t_rows]], axis=1)
            stutter_offset = 0.0
            if self._composed is not None:
                stutter_offset = self._composed.game_state.lane_stutter_offset_y
            if stutter_offset != 0.0:
                self._apply_lane_stutter(positions_xy, entity_indices, stutter_offset)
            rotations_rad = t_view["rotation_rad"][t_rows]
            scales_xy = np.stack([t_view["scale_x"][t_rows], t_view["scale_y"][t_rows]], axis=1)
            texture_ids = s_view["texture_id"][s_rows]
            tint_rgba = np.stack(
                [s_view["tint_r"][s_rows], s_view["tint_g"][s_rows], s_view["tint_b"][s_rows], s_view["tint_a"][s_rows]],
                axis=1,
            )
            layer_z = s_view["layer_z"][s_rows]
            self._renderer.draw_batch(positions_xy, rotations_rad, scales_xy, texture_ids, tint_rgba, layer_z, count)
        self._renderer.end_frame()

    def _apply_lane_stutter(self, positions_xy, entity_indices, stutter_offset: float) -> None:
        """Soma `stutter_offset` na coluna Y so das entidades que SAO
        notas do Arcade 4K (`rhythm_threat`, `mode_tag==MODE_TAG_LANES`)
        dentro do batch de renderizacao -- HUD/receptores/nucleo ficam
        de fora. `positions_xy` e o array TEMPORARIO montado por
        `_render_frame` para este frame (nunca a pool)."""
        threat_pool = self._world.get_pool("rhythm_threat")
        active_count = threat_pool.count
        if active_count == 0:
            return
        threat_view = threat_pool.active_view()
        is_lanes = threat_view["mode_tag"] == MODE_TAG_LANES
        if not np.any(is_lanes):
            return
        lanes_entity_indices = threat_pool.active_entity_indices()[is_lanes]
        mask = np.isin(entity_indices, lanes_entity_indices)
        positions_xy[mask, 1] += stutter_offset

    def run(self) -> None:
        """Mesmo timing do `GameLoop.run` da engine (perf_counter + cap
        de fps), com `advance_frame` no lugar do `world.step`
        incondicional. A renderizacao acontece em TODO estado -- a arena
        fica visivel ao fundo dos overlays."""
        self._running = True
        min_frame_seconds = 1.0 / self._target_fps if self._target_fps > 0 else 0.0
        last_time = time.perf_counter()

        while self._running and not self._input_provider.wants_quit():
            self._input_provider.poll()

            now = time.perf_counter()
            delta_time = now - last_time
            last_time = now

            self.advance_frame(delta_time)
            self._sync_overlay()
            self._sync_camera_shake()
            self._sync_blindness()
            self._sync_hitlag()
            self._sync_lane_playfield()
            self._render_frame()

            elapsed = time.perf_counter() - now
            if min_frame_seconds > elapsed:
                time.sleep(min_frame_seconds - elapsed)
