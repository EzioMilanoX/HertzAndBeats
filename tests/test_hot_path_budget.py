"""Orcamento do hot-path: o loop de gameplay nao aloca e nao demora.

Toda a arquitetura do jogo foi desenhada em torno de uma promessa (pools
fixas pre-alocadas, buffers `out=`, cursores monotonicos, nenhuma Surface
nova por frame) que NENHUM teste guardava. Uma regressao aqui nao quebra
nada de forma visivel num teste de logica -- ela vira engasgo de frame no
meio de uma musica, que e' justamente o pior lugar possivel num jogo
ritmico.

Os limites vem de MEDICAO, com folga deliberada, e nao de um numero
bonito: no baseline desta revisao o loop completo (200 ameacas agendadas,
~8 vivas em regime) roda a 0.40 ms e aloca 25 B por frame. Os tetos estao
1 a 2 ordens de grandeza acima disso -- imunes a ruido de maquina
carregada, mas apertados o bastante pra pegar o erro real que se quer
evitar: um `np.array`/lista NOVA por frame dentro de um `ISystem.update`
(centenas de bytes no minimo), ou um laco que passou a ser O(n^2).
"""
import dataclasses
import gc
import time
import tracemalloc

import pytest

from hertzbeats.bootstrap.rhythm_composition_root import compose_world
from tests.conftest import make_config, write_beatmap

WARMUP_FRAMES = 400
"""Frames descartados antes de medir: o regime permanente e' o que
importa. Antes disso ainda ha spawn inicial e caches assentando -- medir
a partida do zero mediria a composicao, nao o hot-path."""

MEASURED_FRAMES = 600
FRAME_DELTA = 0.016

MAX_BYTES_PER_FRAME = 500.0
"""Baseline medido: 25 B/frame. 20x de folga."""

MAX_MEAN_FRAME_MILLISECONDS = 8.0
"""Baseline medido: 0.40 ms/frame, com orcamento de 16.7 ms a 60 fps.
20x de folga sobre o medido e ainda metade do orcamento real."""

HEAVY_MODIFIERS = (
    "telegraph_rings",
    "polarity",
    "orbital_shields",
    "twin_threats",
    "overload",
    "vision_tunnel",
)
"""O caminho CARO: quanto mais sistemas registrados, mais trabalho por
frame. Se algum modificador introduzir alocacao por frame, e aqui que
aparece -- a filosofia "so paga quem usa" precisa valer de fato."""


def _busy_track(count: int = 200) -> list:
    return [
        {
            "timestamp_seconds": 3.0 + i * 0.25,
            "threat_type": "rhythm_threat_heavy" if i % 5 == 4 else "rhythm_threat_basic",
            "lane": i % 8,
            "strength": 0.9 if i % 5 == 4 else 0.5,
        }
        for i in range(count)
    ]


def _run_and_measure(composed, clock, frames: int):
    """Mede alocacao e tempo de `frames` passos EM REGIME (o warmup ja
    rodou). Devolve `(bytes_por_frame, ms_medio_por_frame)`."""
    gc.collect()
    tracemalloc.start()
    try:
        allocated_before = tracemalloc.get_traced_memory()[0]
        started = time.perf_counter()
        for _ in range(frames):
            clock.advance(FRAME_DELTA)
            composed.world.step(FRAME_DELTA)
        elapsed = time.perf_counter() - started
        allocated_after = tracemalloc.get_traced_memory()[0]
    finally:
        tracemalloc.stop()
    return (allocated_after - allocated_before) / frames, (elapsed / frames) * 1000.0


@pytest.fixture
def stepped_world(tmp_path, null_input, null_clock):
    """Compoe o jogo completo e adianta ate o regime permanente."""

    def _build(modifiers=()):
        config = make_config(write_beatmap(tmp_path / "perf.beatmap.json", _busy_track()))
        if modifiers:
            config = dataclasses.replace(config, active_modifiers=tuple(modifiers))
        composed = compose_world(config, null_input, null_clock)
        null_input.poll()
        for _ in range(WARMUP_FRAMES):
            null_clock.advance(FRAME_DELTA)
            composed.world.step(FRAME_DELTA)
        return composed

    return _build


@pytest.mark.parametrize(
    "modifiers", [pytest.param((), id="base"), pytest.param(HEAVY_MODIFIERS, id="pesado")]
)
def test_gameplay_frame_does_not_allocate(stepped_world, null_clock, modifiers):
    """A promessa Zero-GC, medida. Uma alocacao por frame aqui e' um
    `np.array`/lista criada dentro de um `update()` -- exatamente o que as
    pools pre-alocadas e os buffers `out=` existem pra evitar."""
    composed = stepped_world(modifiers)
    bytes_per_frame, _ = _run_and_measure(composed, null_clock, MEASURED_FRAMES)
    assert bytes_per_frame < MAX_BYTES_PER_FRAME, (
        f"{bytes_per_frame:.1f} B alocados por frame (teto {MAX_BYTES_PER_FRAME:.0f} B) -- "
        f"algum sistema passou a alocar dentro do loop de gameplay"
    )


@pytest.mark.parametrize(
    "modifiers", [pytest.param((), id="base"), pytest.param(HEAVY_MODIFIERS, id="pesado")]
)
def test_gameplay_frame_stays_inside_the_60fps_budget(stepped_world, null_clock, modifiers):
    composed = stepped_world(modifiers)
    _, mean_ms = _run_and_measure(composed, null_clock, MEASURED_FRAMES)
    assert mean_ms < MAX_MEAN_FRAME_MILLISECONDS, (
        f"{mean_ms:.2f} ms medios por frame (teto {MAX_MEAN_FRAME_MILLISECONDS:.1f} ms) -- "
        f"o orcamento a 60 fps e' 16.7 ms para TUDO, render incluido"
    )


def test_allocation_does_not_grow_with_frame_count(stepped_world, null_clock):
    """Guarda contra vazamento LENTO: um acumulador que cresce por frame
    (uma lista de historico, um dict que nunca e' limpo) passaria no teste
    de teto acima se o teto fosse generoso, mas a alocacao TOTAL cresceria
    linear com o numero de frames. Aqui 4x mais frames nao pode custar
    muito mais por frame."""
    composed = stepped_world(())
    short_rate, _ = _run_and_measure(composed, null_clock, 150)
    long_rate, _ = _run_and_measure(composed, null_clock, 600)
    assert long_rate < max(short_rate, 50.0) * 3.0, (
        f"alocacao por frame subiu de {short_rate:.1f} B para {long_rate:.1f} B ao rodar "
        f"mais tempo -- sinal de estrutura que cresce a cada frame"
    )
