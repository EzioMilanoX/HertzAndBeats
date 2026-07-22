"""Audio Ducking: um MISS/dano abaixa a musica para duck_volume_fraction, restaurando gradualmente."""
import pytest

from ouroboros.interfaces.null.null_audio_engine import NullAudioEngine
from ouroboros.interfaces.null.null_renderer import NullRenderer

from hertzbeats.bootstrap.hertz_game_loop import HertzGameLoop, compute_duck_multiplier
from hertzbeats.stages import StageDef

from tests.conftest import make_config, write_beatmap

DT = 0.016


class _VolumeTrackingAudioEngine(NullAudioEngine):
    """`NullAudioEngine` (sem `set_track_volume` na engine base) estendida
    so o suficiente para gravar cada chamada -- o MESMO papel de
    `HBPygameAudioEngine.set_track_volume` real, sem tocar pygame."""

    def __init__(self) -> None:
        super().__init__()
        self.volumes = []

    def set_track_volume(self, volume: float) -> None:
        self.volumes.append(volume)


def _basic(timestamp: float, lane: int = 0) -> dict:
    return {"timestamp_seconds": timestamp, "threat_type": "rhythm_threat_basic", "lane": lane, "strength": 0.5}


@pytest.fixture
def flow_game(tmp_path, null_input):
    def _make(threats):
        beatmap_path = write_beatmap(tmp_path / "stage.beatmap.json", threats)
        stage = StageDef(
            stage_id="stage0", name="FASE 0", subtitle="", track_path=str(tmp_path / "stage.wav"),
            beatmap_path=str(beatmap_path), synth={"bpm": 120.0, "bars": 4}, beatmap_params={},
            overrides={},
        )
        audio_engine = _VolumeTrackingAudioEngine()
        clock = audio_engine.get_clock()
        loop = HertzGameLoop(
            base_config=make_config(beatmap_path), stages=(stage,), renderer=NullRenderer(),
            input_provider=null_input, audio_engine=audio_engine, audio_clock=clock,
        )
        return loop, clock, audio_engine

    return _make


# -- funcao pura -----------------------------------------------------------


def test_duck_multiplier_is_minimum_right_when_the_timer_is_fresh():
    assert compute_duck_multiplier(0.5, 0.5, 0.3) == pytest.approx(0.3)


def test_duck_multiplier_recovers_to_normal_as_the_timer_decays():
    assert compute_duck_multiplier(0.25, 0.5, 0.3) == pytest.approx(0.65)  # meio caminho
    assert compute_duck_multiplier(0.0, 0.5, 0.3) == pytest.approx(1.0)  # totalmente restaurado


def test_duck_multiplier_is_a_no_op_outside_the_ducking_window():
    assert compute_duck_multiplier(0.0, 0.5, 0.3) == 1.0
    assert compute_duck_multiplier(-0.1, 0.5, 0.3) == 1.0
    assert compute_duck_multiplier(0.5, 0.0, 0.3) == 1.0  # duracao 0 -- opt-out


# -- integracao: um MISS de verdade abaixa e restaura o volume --------------


def _jump_to(loop, clock, null_input, exact_seconds: float) -> None:
    """Pula o relogio de audio para um instante EXATO (`set_now_seconds`,
    sem depender de somar `dt` em passos -- arredondamento de ponto
    flutuante num loop de `advance(dt)` pode facilmente ultrapassar um
    limiar de 0.01-0.15s por acidente) e roda UM frame com `delta_time`
    IGUAL ao salto real do relogio -- assim os timers de FRAME (o
    ducking, `game feel`) decaem de forma consistente com o tempo que
    "passou", exatamente como aconteceria num jogo real onde os dois
    relogios avancam juntos a cada frame."""
    dt = exact_seconds - clock.now_seconds()
    clock.set_now_seconds(exact_seconds)
    null_input.poll()
    loop.advance_frame(dt)
    loop._sync_track_volume(dt)


def test_a_miss_ducks_the_track_volume_and_it_recovers_over_time(flow_game, null_input):
    loop, clock, audio_engine = flow_game([_basic(3.0)])
    loop.start_stage(0)
    assert loop.flow == "playing"

    # miss_window default e 0.15s (hit_time=3.0)
    _jump_to(loop, clock, null_input, 3.149)
    assert loop._composed.game_state.miss_count == 0
    _jump_to(loop, clock, null_input, 3.152)
    assert loop._composed.game_state.miss_count == 1
    # o Defensor nunca entra em Flow -- toca na base normal (`1 -
    # flow_volume_boost`, o "headroom" reservado ao swell) MULTIPLICADA
    # pelo ducking, nao o ducking sozinho.
    expected_ducked = loop._flow_base_volume() * loop._stage_config.duck_volume_fraction
    assert audio_engine.volumes[-1] == pytest.approx(expected_ducked, abs=0.02)

    # avanca alem da duracao do ducking (0.5s default) -- volume restaurado
    duck_duration = loop._stage_config.duck_duration_seconds
    _jump_to(loop, clock, null_input, 3.152 + duck_duration + 0.05)
    assert audio_engine.volumes[-1] == pytest.approx(loop._flow_base_volume(), abs=0.02)


def test_a_second_miss_before_recovery_restarts_the_ducking_window(flow_game, null_input):
    loop, clock, audio_engine = flow_game([_basic(3.0), _basic(3.3)])
    loop.start_stage(0)

    _jump_to(loop, clock, null_input, 3.152)
    assert loop._composed.game_state.miss_count == 1
    first_miss_timer = loop._duck_timer_seconds

    # deixa o 1o ducking decair uma fracao, mas NAO se recuperar por
    # completo, antes do 2o MISS (target 3.3 + miss_window 0.15 = 3.45)
    _jump_to(loop, clock, null_input, 3.452)
    assert loop._composed.game_state.miss_count == 2
    # o timer voltou pra perto do MAXIMO -- nao continuou de onde o 1o parou
    assert loop._duck_timer_seconds > first_miss_timer
