"""GameLoop da engine estendido com o fluxo de partida: menu de fases, pausa, derrota e resultados."""
from __future__ import annotations

import dataclasses
import time
from typing import Optional, Tuple

from ouroboros.bootstrap.game_loop import GameLoop
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

MODE_CYCLE = ("defender", "survival", "lanes", "hybrid")
"""Ordem em que A/D alternam o modo nas musicas do jogador."""


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
        self._composed: Optional[ComposedGame] = None

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

    def _compose_stage(self, stage_index: int) -> ComposedGame:
        """Recompoe o `World` inteiro para a fase `stage_index` e garante
        que a faixa exista (re-sintese deterministica se necessario)."""
        stage = self._stages[stage_index]
        stage_config = resolve_stage_config(self._base_config, stage)
        if stage.selectable_mode:
            stage_config = dataclasses.replace(stage_config, game_mode=self.chosen_mode(stage_index))
        if stage.track_path:
            ensure_track(stage.track_path, stage.synth)
        composed = compose_world(
            stage_config,
            self._input_provider,
            self._audio_clock,
            tutorial_steps=stage.tutorial_steps,
            stage_ordinal=stage_index,
            audio_engine=self._audio_engine,
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
        if mode in ("defender", "hybrid"):
            kind = "radial" if mode == "defender" else "radial_arena"
            center_x, center_y = config.center_xy
            renderer.set_playfield(
                kind,
                center_x=center_x,
                center_y=center_y,
                spawn_radius=config.spawn_radius,
                judgment_radius=config.core_half_extent
                + config.threat_half_extents.get("rhythm_threat_basic", 10.0),
                width=config.window_width,
                height=config.window_height,
            )
        elif mode == "survival":
            renderer.set_playfield("arena", width=config.window_width, height=config.window_height)
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

    def _start_stage(self, stage_index: int) -> None:
        """Recompoe a fase e inicia a musica do zero -> PLAYING."""
        self._compose_stage(stage_index)
        self._apply_playfield()
        stage = self._stages[stage_index]
        if stage.track_path:
            self._audio_engine.load_track(stage.stage_id, stage.track_path)
            self._audio_engine.play_track(stage.stage_id)
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

        # musicas do jogador: A/D (ou setas) alternam o minigame
        if self._stages[self._selected_stage].selectable_mode:
            direction = 0
            if inp.is_action_pressed("menu_right"):
                direction = 1
            if inp.is_action_pressed("menu_left"):
                direction = -1
            if direction != 0:
                current = self._chosen_mode_index.get(self._selected_stage, 0)
                self._chosen_mode_index[self._selected_stage] = (current + direction) % len(MODE_CYCLE)

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
            selected_mode = (
                self.chosen_mode(self._selected_stage)
                if self._stages[self._selected_stage].selectable_mode
                else None
            )
            self._renderer.set_overlay(
                overlay_mode, self._selected_stage, len(self._stages), selected_mode=selected_mode
            )
        if hasattr(self._renderer, "set_notice"):
            self._renderer.set_notice(self._notice_key if self._notice_timer > 0.0 else None)

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
            self._render_frame()

            elapsed = time.perf_counter() - now
            if min_frame_seconds > elapsed:
                time.sleep(min_frame_seconds - elapsed)
