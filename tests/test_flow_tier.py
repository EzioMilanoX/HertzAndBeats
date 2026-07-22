"""Flow State: o tier de 50 combos extras chega ao renderer TODO frame, nao so na transicao."""
from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from hertzbeats.bootstrap.hertz_game_loop import HertzGameLoop
from hertzbeats.stages import StageDef

from tests.conftest import make_config, write_beatmap

DT = 0.016


class _RecordingRenderer(NullRenderer):
    """Dublê de teste: grava as chamadas de `set_flow_tier` (metodo
    especifico do Hertz & Beats, nao faz parte da ABC `IRenderer` --
    `NullRenderer` nao o possui, entao o `hasattr` de `_advance_flow_state`
    so acha isso aqui)."""

    def __init__(self) -> None:
        super().__init__()
        self.flow_tiers = []

    def set_flow_tier(self, tier: int) -> None:
        self.flow_tiers.append(tier)


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": timestamp, "threat_type": "rhythm_threat_basic", "lane": lane, "strength": 0.5}


def _make_lanes_loop(tmp_path, null_input):
    beatmap_path = write_beatmap(tmp_path / "l.beatmap.json", [_basic(99.0)])
    stage = StageDef(
        stage_id="s0", name="FASE 0", subtitle="", track_path=str(tmp_path / "s0.wav"),
        beatmap_path=str(beatmap_path), synth={"bpm": 120.0, "bars": 1}, beatmap_params={},
        overrides={"game_mode": "lanes"},
    )
    audio_engine = NullAudioEngine()
    clock = audio_engine.get_clock()
    renderer = _RecordingRenderer()
    loop = HertzGameLoop(
        base_config=make_config(beatmap_path),
        stages=(stage,),
        renderer=renderer,
        input_provider=null_input,
        audio_engine=audio_engine,
        audio_clock=clock,
        player_progress_path=str(tmp_path / "player_progress.json"),
        player_stats_path=str(tmp_path / "player_lifetime_stats.json"),
        user_settings_path=str(tmp_path / "user_settings.json"),
    )
    loop.start_stage(0)
    return loop, renderer


def test_tier_is_zero_before_reaching_the_flow_threshold(tmp_path, null_input):
    loop, renderer = _make_lanes_loop(tmp_path, null_input)
    loop.composed.game_state.combo_count = 10  # abaixo do limiar (50)
    null_input.poll()
    loop.advance_frame(DT)
    assert renderer.flow_tiers[-1] == 0


def test_tier_is_one_exactly_at_the_threshold(tmp_path, null_input):
    loop, renderer = _make_lanes_loop(tmp_path, null_input)
    loop.composed.game_state.combo_count = 50
    null_input.poll()
    loop.advance_frame(DT)
    assert renderer.flow_tiers[-1] == 1


def test_tier_advances_within_flow_without_leaving_and_re_entering(tmp_path, null_input):
    """O tier sobe DENTRO do Flow (sem cruzar o limiar de novo) --
    diferente da transicao de entrada/saida (volume/escurecimento), que
    so dispara na BORDA."""
    loop, renderer = _make_lanes_loop(tmp_path, null_input)
    loop.composed.game_state.combo_count = 50
    null_input.poll()
    loop.advance_frame(DT)
    assert renderer.flow_tiers[-1] == 1

    loop.composed.game_state.combo_count = 101  # 2 limiares completos + resto
    null_input.poll()
    loop.advance_frame(DT)
    assert renderer.flow_tiers[-1] == 2


def test_tier_resets_to_zero_after_a_miss_breaks_the_combo(tmp_path, null_input):
    loop, renderer = _make_lanes_loop(tmp_path, null_input)
    loop.composed.game_state.combo_count = 120
    null_input.poll()
    loop.advance_frame(DT)
    assert renderer.flow_tiers[-1] == 2

    loop.composed.game_state.combo_count = 0  # Miss zera o combo
    null_input.poll()
    loop.advance_frame(DT)
    assert renderer.flow_tiers[-1] == 0
