"""GameLoop da engine estendido com o fluxo de partida: menu de fases, pausa, derrota e resultados."""
from __future__ import annotations

import time
from typing import Optional, Tuple

from ouroboros.bootstrap.game_loop import GameLoop
from ouroboros.interfaces.audio_clock import IAudioClock
from ouroboros.interfaces.audio_engine import IAudioEngine
from ouroboros.interfaces.input_provider import IInputProvider
from ouroboros.interfaces.renderer import IRenderer

from hertzbeats.audio.demo_track_synth import ensure_track
from hertzbeats.bootstrap.rhythm_composition_root import ComposedGame, compose_world
from hertzbeats.config import HertzConfig
from hertzbeats.stages import StageDef, resolve_stage_config

FLOW_MENU = "menu"
FLOW_PLAYING = "playing"
FLOW_PAUSED = "paused"
FLOW_GAME_OVER = "game_over"
FLOW_RESULTS = "results"

_RESULTS_GRACE_SECONDS = 1.0
"""Pausa dramatica entre a ultima ameaca resolvida e a tela de resultados."""


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
        self._selected_stage = 0
        self._loaded_stage = 0
        self._flow = FLOW_MENU
        self._results_grace = 0.0
        self._composed: Optional[ComposedGame] = None

        composed = self._compose_stage(0)
        super().__init__(
            composed.world,
            renderer,
            input_provider,
            audio_engine,
            target_fps=base_config.target_fps,
        )

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

    def _compose_stage(self, stage_index: int) -> ComposedGame:
        """Recompoe o `World` inteiro para a fase `stage_index` e garante
        que a faixa exista (re-sintese deterministica se necessario)."""
        stage = self._stages[stage_index]
        stage_config = resolve_stage_config(self._base_config, stage)
        if stage.track_path:
            ensure_track(stage.track_path, stage.synth)
        composed = compose_world(
            stage_config,
            self._input_provider,
            self._audio_clock,
            tutorial_steps=stage.tutorial_steps,
            stage_ordinal=stage_index,
        )
        self._composed = composed
        self._loaded_stage = stage_index
        self._world = composed.world  # GameLoop renderiza sempre o world da fase carregada
        return composed

    def _start_stage(self, stage_index: int) -> None:
        """Recompoe a fase e inicia a musica do zero -> PLAYING."""
        self._compose_stage(stage_index)
        stage = self._stages[stage_index]
        if stage.track_path:
            self._audio_engine.load_track(stage.stage_id, stage.track_path)
            self._audio_engine.play_track(stage.stage_id)
        self._flow = FLOW_PLAYING
        self._results_grace = 0.0

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

    def advance_frame(self, delta_time: float) -> None:
        """Um frame do fluxo: trata as acoes de meta-jogo do estado atual
        e, apenas em PLAYING, avanca a simulacao (`world.step`)."""
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

        threat_pool = self._composed.memory_manager.get_pool("rhythm_threat")
        if self._composed.spawner_system.is_finished and threat_pool.count == 0:
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
            self._renderer.set_overlay(overlay_mode, self._selected_stage, len(self._stages))

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
