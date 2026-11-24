"""
Compositor das MUSICAS ORIGINAIS das fases da campanha `trilhas_originais`.

Por que um modulo novo em vez de mais um estilo em `demo_track_synth`: o
sintetizador historico e um GERADOR DE FAIXA DE TREINO -- toda faixa tem o
mesmo bumbo, a mesma caixa, o mesmo baixo em colcheias e o mesmo motivo
pentatonico; o que muda e so a densidade. Para musicas de verdade, com
estilos diferentes entre si (um downtempo lento, um funk com sincopa, um
drum'n'bass), cada musica precisa de instrumentos, groove, harmonia e
melodia PROPRIOS. Composicao 100% original, escrita aqui nota a nota --
nenhum sample, nenhum material de terceiros.

Mesmo contrato do resto do jogo:

- **Deterministico, numpy puro.** O `.wav` nao e versionado; qualquer
  maquina reconstroi a faixa bit a bit a partir da especificacao `synth`
  da fase. Inclusive o RUIDO (caixa, chimbal, palmas): vem de um hash
  inteiro (`_hash_noise`), nunca de `np.random` -- um gerador cujo
  algoritmo muda entre versoes do numpy mudaria o audio e invalidaria o
  `track_fingerprint` dos beatmaps versionados sem nenhum erro visivel.
- **A estrutura e dado.** A especificacao e `{"bpm", "song", "sections":
  [{"name", "bars", "part", "lead", ...}]}`: a ORDEM e o tamanho das
  secoes moram em `stages.json` (e a curadoria por secao, o Treino por
  Secao e a Escala de Tempo continuam funcionando sem saber que a faixa e
  "original"); o conteudo musical de cada `part` mora aqui.
- **Verdade fundamental.** `percussive_onset_times` roda a MESMA
  partitura em modo "seco" (sem renderizar audio), so anotando onde cai
  cada bumbo/caixa/palma -- coincide com o audio por construcao, e e o
  que `tests/test_beat_alignment.py` usa para provar que as notas do
  chart caem na batida.
- **Stems.** `instrumental` e `lead` (a melodia) renderizam camadas
  separadas normalizadas pelo pico da mixagem completa, exatamente como
  `demo_track_synth.synthesize_track` -- o Crossfading Vocal funciona
  igual.

Quem chama e `demo_track_synth` (que despacha pela chave `song`); a CLI
para ouvir/exportar e `tools/compor_faixas.py`.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

SAMPLE_RATE = 44100

LAYER_BACKING = "instrumental"
LAYER_LEAD = "lead"

SECTION_KEYS = frozenset({"name", "bars", "part", "lead"})
"""Chaves que a SINTESE le numa secao de musica original. As de curadoria
(`min_gap_seconds`, `target_density_per_second`) tambem sao aceitas --
validadas por `demo_track_synth`, dona dessa lista."""


# ------------------------------------------------------------ utilidades


def midi_hz(note: float) -> float:
    """Nota MIDI -> Hz (temperamento igual, La4 = 440)."""
    return 440.0 * 2.0 ** ((note - 69.0) / 12.0)


_MASK64 = np.uint64(0xFFFFFFFFFFFFFFFF)


def _hash_noise(length: int, seed: int) -> np.ndarray:
    """Ruido branco DETERMINISTICO em [-1, 1): splitmix64 sobre o indice.

    Aritmetica inteira de 64 bits (o estouro e o proprio algoritmo), entao
    o resultado e identico em qualquer maquina e versao do numpy -- ao
    contrario de `np.random`, cujo algoritmo nao e contrato de API."""
    with np.errstate(over="ignore"):
        z = np.arange(length, dtype=np.uint64) + np.uint64(seed) * np.uint64(0x9E3779B97F4A7C15)
        z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        z = (z ^ (z >> np.uint64(31))) & _MASK64
    return (z >> np.uint64(11)).astype(np.float64) / float(1 << 53) * 2.0 - 1.0


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE


def _env(tt: np.ndarray, attack: float, decay: float) -> np.ndarray:
    """Ataque linear + decaimento exponencial (`decay` em 1/s)."""
    return np.minimum(tt / max(attack, 1e-4), 1.0) * np.exp(-tt * decay)


def _release(signal: np.ndarray, seconds: float = 0.03) -> np.ndarray:
    """Rampa final curta: nota cortada seca estala."""
    n = min(signal.shape[0], int(seconds * SAMPLE_RATE))
    if n > 0:
        signal = signal.copy()
        signal[-n:] *= np.linspace(1.0, 0.0, n)
    return signal


def _additive(freq: float, tt: np.ndarray, harmonics: Sequence[Tuple[int, float]], detune: float = 0.0) -> np.ndarray:
    """Soma de parciais `(multiplo, amplitude)`, descartando o que passa de
    16 kHz (sem aliasing, sem filtro)."""
    out = np.zeros_like(tt)
    for multiple, amplitude in harmonics:
        f = freq * multiple * (1.0 + detune)
        if f < 16000.0:
            out += amplitude * np.sin(2.0 * np.pi * f * tt)
    return out


def _saw_harmonics(count: int, rolloff: float = 1.0) -> Tuple[Tuple[int, float], ...]:
    return tuple((k, 1.0 / (k**rolloff)) for k in range(1, count + 1))


def _square_harmonics(count: int) -> Tuple[Tuple[int, float], ...]:
    return tuple((k, 1.0 / k) for k in range(1, 2 * count, 2))


# ------------------------------------------------------------ instrumentos


def kick(amp: float = 0.9, body_hz: float = 48.0, punch_hz: float = 140.0, decay: float = 18.0) -> np.ndarray:
    tt = _t(0.32)
    freq = punch_hz * np.exp(-tt * 30.0) + body_hz
    phase = 2.0 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    click = 0.25 * np.exp(-tt * 400.0) * _hash_noise(tt.shape[0], 11)
    return amp * (np.exp(-tt * decay) * np.sin(phase) + click)


def snare(amp: float = 0.55, tone_hz: float = 185.0, decay: float = 22.0, seed: int = 21) -> np.ndarray:
    tt = _t(0.22)
    noise = np.diff(_hash_noise(tt.shape[0] + 1, seed))  # 1a diferenca = agudo
    body = np.sin(2.0 * np.pi * tone_hz * tt) * np.exp(-tt * 30.0)
    return amp * (0.55 * noise * np.exp(-tt * decay) + 0.6 * body)


def clap(amp: float = 0.5, seed: int = 31) -> np.ndarray:
    tt = _t(0.25)
    noise = np.diff(_hash_noise(tt.shape[0] + 1, seed)) * 0.7
    env = np.zeros_like(tt)
    for burst in (0.0, 0.009, 0.018):  # 3 maos quase juntas
        local = tt - burst
        env += np.where(local >= 0.0, np.exp(-np.clip(local, 0.0, None) * 140.0), 0.0)
    env += np.exp(-tt * 18.0) * 0.35
    return amp * noise * np.minimum(env, 1.2)


def hat(amp: float = 0.15, decay: float = 80.0, seed: int = 41) -> np.ndarray:
    tt = _t(0.12 if decay > 30.0 else 0.4)
    noise = np.diff(np.diff(_hash_noise(tt.shape[0] + 2, seed)))  # 2a diferenca = bem agudo
    return amp * 0.5 * noise * np.exp(-tt * decay)


def rim(amp: float = 0.3) -> np.ndarray:
    tt = _t(0.05)
    return amp * np.exp(-tt * 120.0) * (np.sin(2.0 * np.pi * 1650.0 * tt) + 0.5 * np.sin(2.0 * np.pi * 520.0 * tt))


def crash(amp: float = 0.4, seed: int = 51) -> np.ndarray:
    tt = _t(1.6)
    noise = np.diff(_hash_noise(tt.shape[0] + 1, seed))
    return amp * 0.6 * noise * np.exp(-tt * 2.6)


def sub_bass(freq: float, seconds: float, amp: float = 0.45) -> np.ndarray:
    tt = _t(seconds)
    raw = np.sin(2.0 * np.pi * freq * tt) + 0.25 * np.sin(4.0 * np.pi * freq * tt)
    return _release(amp * np.tanh(1.4 * raw) * _env(tt, 0.008, 1.2))


def slap_bass(freq: float, seconds: float, amp: float = 0.42) -> np.ndarray:
    """Baixo de funk: o brilho (harmonicos) morre rapido, o corpo fica."""
    tt = _t(seconds)
    body = np.sin(2.0 * np.pi * freq * tt) + 0.5 * np.sin(4.0 * np.pi * freq * tt)
    bright = _additive(freq, tt, ((3, 0.5), (4, 0.35), (5, 0.25), (6, 0.18))) * np.exp(-tt * 28.0)
    return _release(amp * np.tanh(1.2 * (body + bright)) * _env(tt, 0.004, 3.5))


def reese(freq: float, seconds: float, amp: float = 0.30) -> np.ndarray:
    """Baixo de drum'n'bass: dois serrotes desafinados batendo entre si."""
    tt = _t(seconds)
    harmonics = _saw_harmonics(10, rolloff=1.25)
    raw = _additive(freq, tt, harmonics, detune=-0.006) + _additive(freq, tt, harmonics, detune=0.006)
    sub = 1.2 * np.sin(2.0 * np.pi * freq * tt)
    return _release(amp * np.tanh(0.8 * (raw + sub)) * _env(tt, 0.02, 0.4), 0.05)


def epiano(freq: float, seconds: float, amp: float = 0.16) -> np.ndarray:
    """Piano eletrico por FM (modulador 1:1, indice que decai)."""
    tt = _t(seconds)
    index = 1.8 * np.exp(-tt * 6.0)
    tone = np.sin(2.0 * np.pi * freq * tt + index * np.sin(2.0 * np.pi * freq * tt))
    tine = 0.18 * np.sin(2.0 * np.pi * freq * 7.0 * tt) * np.exp(-tt * 30.0)
    return _release(amp * (tone + tine) * _env(tt, 0.004, 1.6), 0.08)


def bell(freq: float, seconds: float, amp: float = 0.22) -> np.ndarray:
    """Sino por FM (razao 3.5 = parcial inarmonico de metal)."""
    tt = _t(seconds)
    index = 2.4 * np.exp(-tt * 4.0)
    tone = np.sin(2.0 * np.pi * freq * tt + index * np.sin(2.0 * np.pi * freq * 3.5 * tt))
    return _release(amp * tone * _env(tt, 0.003, 2.2), 0.06)


def pad(freqs: Sequence[float], seconds: float, amp: float = 0.07) -> np.ndarray:
    tt = _t(seconds)
    out = np.zeros_like(tt)
    for i, freq in enumerate(freqs):
        out += _additive(freq, tt, _saw_harmonics(6, rolloff=1.6), detune=0.002 * (1 if i % 2 else -1))
    attack = min(0.6, seconds * 0.4)
    env = np.minimum(tt / attack, 1.0) * np.minimum((seconds - tt) / attack, 1.0)
    return amp * out * env / max(1, len(freqs)) * 2.0


def stab(freqs: Sequence[float], seconds: float, amp: float = 0.14) -> np.ndarray:
    """Acorde curto de metais/orgao (quadrada com poucos harmonicos)."""
    tt = _t(seconds)
    out = np.zeros_like(tt)
    for freq in freqs:
        out += _additive(freq, tt, _square_harmonics(5))
    return _release(amp * out * _env(tt, 0.006, 5.0) / max(1, len(freqs)) * 2.0)


def pluck(freq: float, seconds: float, amp: float = 0.10) -> np.ndarray:
    tt = _t(seconds)
    bright = _additive(freq, tt, _saw_harmonics(8, rolloff=1.0)) * np.exp(-tt * 18.0)
    body = np.sin(2.0 * np.pi * freq * tt)
    return _release(amp * (0.6 * bright + 0.5 * body) * _env(tt, 0.002, 9.0))


def lead_synth(freq: float, seconds: float, amp: float = 0.16, vibrato: float = 0.004) -> np.ndarray:
    """Lead de quadrada com vibrato que entra depois do ataque."""
    tt = _t(seconds)
    depth = vibrato * np.minimum(tt / 0.25, 1.0)
    phase = 2.0 * np.pi * freq * (tt + depth * np.sin(2.0 * np.pi * 5.5 * tt) / (2.0 * np.pi * 5.5))
    out = np.zeros_like(tt)
    for k, a in _square_harmonics(6):
        if freq * k < 16000.0:
            out += a * np.sin(k * phase)
    env = np.minimum(tt / 0.01, 1.0) * (0.75 + 0.25 * np.exp(-tt * 6.0))
    return _release(amp * out * env, 0.05)


def supersaw(freqs: Sequence[float], seconds: float, amp: float = 0.13) -> np.ndarray:
    tt = _t(seconds)
    out = np.zeros_like(tt)
    for freq in freqs:
        for detune in (-0.008, 0.0, 0.008):
            out += _additive(freq, tt, _saw_harmonics(9, rolloff=1.1), detune=detune)
    return _release(amp * out * _env(tt, 0.01, 1.5) / (3.0 * max(1, len(freqs))) * 2.0, 0.05)


# ------------------------------------------------------------ partitura


class Score:
    """Quadro onde as partes escrevem. Em modo SECO (`render=False`) nada e
    sintetizado: so os golpes de percussao sao anotados -- e assim que a
    verdade fundamental sai da mesma partitura que gera o audio."""

    def __init__(self, bpm: float, total_bars: int, render: bool, layers: Tuple[str, ...]) -> None:
        self.bpm = float(bpm)
        self.beat_seconds = 60.0 / self.bpm
        self.bar_seconds = 4.0 * self.beat_seconds
        self.total_seconds = total_bars * self.bar_seconds
        self.render = render
        self.layers = layers
        self.mix = np.zeros(int(self.total_seconds * SAMPLE_RATE) if render else 0, dtype=np.float64)
        self.drum_hits: List[float] = []
        self._cache: Dict[tuple, np.ndarray] = {}

    def time(self, bar: int, beat: float) -> float:
        """`bar` absoluto 0-indexado, `beat` 0-indexado (0..4)."""
        return bar * self.bar_seconds + beat * self.beat_seconds

    def beats(self, count: float) -> float:
        return count * self.beat_seconds

    def _signal(self, key: tuple, factory: Callable[[], np.ndarray]) -> np.ndarray:
        cached = self._cache.get(key)
        if cached is None:
            cached = factory()
            self._cache[key] = cached
        return cached

    def add(self, seconds: float, key: tuple, factory: Callable[[], np.ndarray], layer: str = LAYER_BACKING) -> None:
        if not self.render or layer not in self.layers:
            return
        signal = self._signal(key, factory)
        start = int(round(seconds * SAMPLE_RATE))
        end = min(start + signal.shape[0], self.mix.shape[0])
        if 0 <= start < self.mix.shape[0]:
            self.mix[start:end] += signal[: end - start]

    def drum(self, bar: int, beat: float, kind: str, amp: float = 1.0, **kwargs) -> None:
        """Golpe de bateria. `kick`/`snare`/`clap` contam como VERDADE
        FUNDAMENTAL (o que o jogador sente como batida); chimbal, aro e
        prato sao textura e nao contam."""
        seconds = self.time(bar, beat)
        if kind in ("kick", "snare", "clap"):
            self.drum_hits.append(seconds)
        factories = {"kick": kick, "snare": snare, "clap": clap, "hat": hat, "rim": rim, "crash": crash}
        instrument = factories[kind]
        frozen = tuple(sorted(kwargs.items()))
        self.add(seconds, (kind, amp, frozen), lambda: instrument(amp=amp * _DEFAULT_AMP[kind], **kwargs))

    def note(self, bar: int, beat: float, instrument: Callable, pitch, length_beats: float,
             layer: str = LAYER_BACKING, **kwargs) -> None:
        """Nota (ou acorde, com `pitch` em tupla de MIDI) de `length_beats`."""
        seconds = self.beats(length_beats)
        if isinstance(pitch, tuple):
            freqs = tuple(midi_hz(p) for p in pitch)
            key = (instrument.__name__, freqs, round(seconds, 6), tuple(sorted(kwargs.items())))
            factory = lambda: instrument(freqs, seconds, **kwargs)  # noqa: E731
        else:
            freq = midi_hz(pitch)
            key = (instrument.__name__, freq, round(seconds, 6), tuple(sorted(kwargs.items())))
            factory = lambda: instrument(freq, seconds, **kwargs)  # noqa: E731
        self.add(self.time(bar, beat), key, factory, layer)


_DEFAULT_AMP = {"kick": 0.9, "snare": 0.55, "clap": 0.5, "hat": 0.15, "rim": 0.3, "crash": 0.4}

PartFn = Callable[[Score, int, int, Dict], None]
"""`part(score, primeiro_compasso_absoluto, compassos, secao_crua)`."""


# ======================================================================
# 1. MARE LENTA -- downtempo/lo-fi a 76 BPM, Re menor (dorico)
#    Boom-bap preguicoso, piano eletrico, sino na melodia. A fase de
#    entrada da campanha: tudo cai em batida ou contratempo de colcheia.
# ======================================================================

_MARE_CHORDS = ((53, 57, 60, 64), (53, 57, 58, 62), (55, 58, 62, 65), (55, 57, 61, 64))  # Dm9 Bbmaj7 Gm7 A7
_MARE_BASS = (38, 34, 31, 33)  # D2 Bb1 G1 A1
# (compasso_da_frase, batida, nota MIDI, duracao em batidas) -- frase de 4 compassos
_MARE_MELODY = (
    (0, 0.5, 69, 1.0), (0, 1.5, 72, 0.5), (0, 2.0, 74, 1.5),
    (1, 0.5, 77, 0.5), (1, 1.0, 74, 1.0), (1, 2.5, 72, 1.5),
    (2, 0.0, 69, 1.0), (2, 1.5, 67, 0.5), (2, 2.0, 69, 0.5), (2, 3.0, 72, 1.0),
    (3, 0.5, 74, 3.0),
)


def _mare_harmony(score: Score, bar: int, i: int, restrike: bool = True) -> None:
    chord = _MARE_CHORDS[i % 4]
    score.note(bar, 0.0, epiano, chord[0], 3.5)
    for p in chord[1:]:
        score.note(bar, 0.0, epiano, p, 3.5, amp=0.12)
    if restrike:
        for p in chord[1:]:
            score.note(bar, 2.5, epiano, p, 1.4, amp=0.07)


def _mare_intro(score: Score, start: int, bars: int, raw: Dict) -> None:
    for i in range(bars):
        _mare_harmony(score, start + i, i, restrike=False)
        score.note(start + i, 0.0, pad, tuple(p - 12 for p in _MARE_CHORDS[i % 4][:3]), 4.0)
        for beat in (1.0, 3.0):
            score.drum(start + i, beat, "rim", 0.6)


def _mare_groove(score: Score, bar: int, i: int, variation: bool) -> None:
    score.drum(bar, 0.0, "kick")
    score.drum(bar, 2.5, "kick", 0.8)
    if variation and i % 2 == 1:
        score.drum(bar, 1.75, "kick", 0.55)  # pegada do bumbo antes do 3
    score.drum(bar, 1.0, "snare")
    score.drum(bar, 3.0, "snare")
    for eighth in range(8):
        score.drum(bar, eighth * 0.5, "hat", 0.9 if eighth % 2 else 0.5, decay=70.0)
    root = _MARE_BASS[i % 4]
    score.note(bar, 0.0, sub_bass, root, 1.5)
    score.note(bar, 2.5, sub_bass, root, 0.5)
    score.note(bar, 3.0, sub_bass, root + 7, 1.0)


def _mare_melody(score: Score, start: int, bars: int, octave: int = 0) -> None:
    for i in range(bars):
        phrase_bar = i % 4
        for mbar, beat, pitch, length in _MARE_MELODY:
            if mbar == phrase_bar:
                score.note(start + i, beat, bell, pitch + octave, length, layer=LAYER_LEAD)


def _mare_tema(score: Score, start: int, bars: int, raw: Dict) -> None:
    score.drum(start, 0.0, "crash", 0.7)
    for i in range(bars):
        _mare_harmony(score, start + i, i)
        _mare_groove(score, start + i, i, variation=False)
    if raw.get("lead"):
        _mare_melody(score, start, bars)


def _mare_ponte(score: Score, start: int, bars: int, raw: Dict) -> None:
    """Respiro: sem caixa, so o bumbo no 1 e um eco no 3."""
    for i in range(bars):
        bar = start + i
        chord = _MARE_CHORDS[(i + 2) % 4]
        score.note(bar, 0.0, pad, chord, 4.0, amp=0.09)
        score.note(bar, 0.0, sub_bass, _MARE_BASS[(i + 2) % 4], 3.5)
        score.drum(bar, 0.0, "kick", 0.85)
        score.drum(bar, 2.0, "rim", 0.5)
        if i % 2 == 1:
            score.drum(bar, 3.0, "kick", 0.6)
    if raw.get("lead"):
        for i in range(bars):
            score.note(start + i, 1.0, bell, (74, 72, 69, 67)[i % 4], 2.0, layer=LAYER_LEAD, amp=0.11)


def _mare_final(score: Score, start: int, bars: int, raw: Dict) -> None:
    score.drum(start, 0.0, "crash", 0.8)
    body = bars - 1
    for i in range(body):
        _mare_harmony(score, start + i, i)
        _mare_groove(score, start + i, i, variation=True)
    if raw.get("lead"):
        _mare_melody(score, start, body, octave=12)
    last = start + body
    score.drum(last, 0.0, "kick")
    score.drum(last, 0.0, "crash", 0.6)
    score.note(last, 0.0, epiano, 50, 3.8)
    for p in (53, 57, 60, 64):
        score.note(last, 0.0, epiano, p, 3.8, amp=0.11)
    score.note(last, 0.0, sub_bass, 38, 3.0)


# ======================================================================
# 2. CONTRATEMPO -- funk/latino a 112 BPM, Mi dorico
#    Bumbo em tresillo (3+3+2 semicolcheias), palmas no 2 e 4, baixo de
#    slap colado no bumbo, metais nos contratempos. A sincopa E a fase.
# ======================================================================

_CONTRA_VERSE = ((52, 55, 59, 62), (57, 61, 64, 67))  # Em7 A7 (vamp dorico i-IV)
_CONTRA_VERSE_BASS = (40, 45)  # E2 A2
_CONTRA_CHORUS = ((60, 64, 67, 71), (62, 66, 69, 72), (59, 62, 66, 69), (52, 55, 59, 62))  # Cmaj7 D7 Bm7 Em7
_CONTRA_CHORUS_BASS = (36, 38, 47, 40)  # C2 D2 B2 E2
_CONTRA_MELODY = (
    (0, 0.75, 71, 0.5), (0, 1.5, 74, 1.0), (0, 3.0, 76, 0.75),
    (1, 0.0, 74, 0.5), (1, 0.75, 71, 0.75), (1, 2.5, 69, 1.25),
    (2, 0.75, 67, 0.5), (2, 1.5, 69, 0.75), (2, 2.5, 71, 0.5), (2, 3.25, 74, 0.5),
    (3, 0.0, 76, 1.25), (3, 1.5, 79, 0.5), (3, 2.0, 76, 1.75),
)


def _contra_drums(score: Score, bar: int, full: bool, fill: bool) -> None:
    score.drum(bar, 0.0, "kick")
    score.drum(bar, 0.75, "kick", 0.75)
    score.drum(bar, 1.5, "kick", 0.9)
    if full:
        score.drum(bar, 2.5, "kick", 0.8)
    score.drum(bar, 1.0, "clap")
    score.drum(bar, 3.0, "clap")
    if fill:
        score.drum(bar, 3.5, "snare", 0.7)
        score.drum(bar, 3.75, "snare", 0.85)
    else:
        score.drum(bar, 3.75, "rim", 0.7)
    for sixteenth in range(16):
        accent = 0.8 if sixteenth % 4 == 2 else (0.35 if sixteenth % 2 else 0.5)
        score.drum(bar, sixteenth * 0.25, "hat", accent, decay=110.0, seed=43)


def _contra_bass(score: Score, bar: int, root: int) -> None:
    score.note(bar, 0.0, slap_bass, root, 0.6)
    score.note(bar, 0.75, slap_bass, root, 0.5)
    score.note(bar, 1.5, slap_bass, root + 12, 0.4)
    score.note(bar, 2.5, slap_bass, root + 10, 0.5)
    score.note(bar, 3.0, slap_bass, root + 7, 0.6)


def _contra_intro(score: Score, start: int, bars: int, raw: Dict) -> None:
    for i in range(bars):
        bar = start + i
        score.drum(bar, 0.0, "kick")
        score.drum(bar, 1.5, "kick", 0.85)
        if i >= 2:
            score.drum(bar, 1.0, "clap", 0.8)
            score.drum(bar, 3.0, "clap", 0.8)
        for sixteenth in range(16):
            score.drum(bar, sixteenth * 0.25, "hat", 0.6 if sixteenth % 4 == 2 else 0.3, decay=110.0, seed=43)
        if i == bars - 1:
            score.drum(bar, 3.5, "snare", 0.6)
            score.drum(bar, 3.75, "snare", 0.75)


def _contra_verso(score: Score, start: int, bars: int, raw: Dict) -> None:
    score.drum(start, 0.0, "crash", 0.6)
    for i in range(bars):
        bar = start + i
        _contra_drums(score, bar, full=(i % 2 == 1), fill=(i == bars - 1))
        _contra_bass(score, bar, _CONTRA_VERSE_BASS[i % 2])
        chord = _CONTRA_VERSE[i % 2]
        for beat in (0.5, 1.5, 2.5, 3.5):  # "guitarra" abafada no contratempo
            for pitch in chord[1:]:
                score.note(bar, beat, pluck, pitch, 0.3, amp=0.035)


def _contra_refrao(score: Score, start: int, bars: int, raw: Dict) -> None:
    score.drum(start, 0.0, "crash", 0.75)
    for i in range(bars):
        bar = start + i
        _contra_drums(score, bar, full=True, fill=(i == bars - 1))
        _contra_bass(score, bar, _CONTRA_CHORUS_BASS[i % 4])
        chord = _CONTRA_CHORUS[i % 4]
        score.note(bar, 1.5, stab, chord, 0.45)
        score.note(bar, 3.5, stab, chord, 0.3, amp=0.10)
        score.note(bar, 0.0, pad, chord, 4.0, amp=0.04)
    if raw.get("lead"):
        for i in range(bars):
            for mbar, beat, pitch, length in _CONTRA_MELODY:
                if mbar == i % 4:
                    score.note(start + i, beat, lead_synth, pitch, length, layer=LAYER_LEAD)


def _contra_quebra(score: Score, start: int, bars: int, raw: Dict) -> None:
    """Quebra: some o bumbo, ficam palmas e baixo -- o jogador respira."""
    for i in range(bars):
        bar = start + i
        score.drum(bar, 1.0, "clap", 0.9)
        score.drum(bar, 3.0, "clap", 0.9)
        root = _CONTRA_VERSE_BASS[i % 2]
        score.note(bar, 0.0, slap_bass, root, 1.0, amp=0.35)
        score.note(bar, 2.5, slap_bass, root + 12, 0.5, amp=0.3)
        score.note(bar, 0.0, pad, _CONTRA_VERSE[i % 2], 4.0, amp=0.08)
        if i == bars - 1:
            for k, beat in enumerate((2.0, 2.5, 3.0, 3.5)):
                score.drum(bar, beat, "snare", 0.5 + 0.1 * k)


def _contra_fim(score: Score, start: int, bars: int, raw: Dict) -> None:
    score.drum(start, 0.0, "kick")
    score.drum(start, 0.0, "crash", 0.8)
    score.note(start, 0.0, slap_bass, 40, 1.5)
    score.note(start, 0.0, stab, (52, 55, 59, 62, 66), 2.0, amp=0.16)


# ======================================================================
# 3. HIPERPULSO -- drum'n'bass a 170 BPM, Fa menor
#    Two-step (bumbo no 1 e no "e" do 3, caixa no 2 e 4), baixo reese,
#    arpejo em semicolcheias, supersaw no drop. A fase dificil.
# ======================================================================

_HIPER_CHORDS = ((65, 68, 72), (61, 65, 68), (58, 61, 65), (60, 64, 67))  # Fm Db Bbm C
_HIPER_BASS = (29, 25, 34, 24)  # F1 Db1 Bb1 C1 (o reese mora embaixo)
_HIPER_MELODY = (
    (0, 0.0, 77, 1.5), (0, 1.5, 80, 1.0), (0, 2.5, 79, 1.5),
    (1, 0.0, 77, 1.0), (1, 1.0, 73, 2.0), (1, 3.0, 72, 1.0),
    (2, 0.0, 73, 1.5), (2, 1.5, 77, 1.0), (2, 2.5, 80, 1.5),
    (3, 0.0, 79, 3.0), (3, 3.0, 76, 1.0),
)


def _hiper_arp(score: Score, bar: int, i: int, amp: float = 0.08) -> None:
    chord = _HIPER_CHORDS[i % 4]
    pattern = (0, 1, 2, 1, 0, 2, 1, 2)
    for sixteenth in range(16):
        pitch = chord[pattern[sixteenth % 8]] + (12 if sixteenth % 8 >= 4 else 0)
        score.note(bar, sixteenth * 0.25, pluck, pitch, 0.3, amp=amp)


def _hiper_intro(score: Score, start: int, bars: int, raw: Dict) -> None:
    for i in range(bars):
        bar = start + i
        score.note(bar, 0.0, pad, _HIPER_CHORDS[i % 4], 4.0, amp=0.08)
        _hiper_arp(score, bar, i, amp=0.05 + 0.01 * i)
        score.drum(bar, 0.0, "kick", 0.8)
        for eighth in range(8):
            score.drum(bar, eighth * 0.5, "hat", 0.4, seed=47)


def _hiper_build(score: Score, start: int, bars: int, raw: Dict) -> None:
    """Quatro no chao: semeia o pulso antes do drop."""
    for i in range(bars):
        bar = start + i
        for beat in range(4):
            score.drum(bar, float(beat), "kick", 0.85)
        score.drum(bar, 1.0, "snare", 0.6)
        score.drum(bar, 3.0, "snare", 0.6)
        for eighth in range(8):
            score.drum(bar, eighth * 0.5 + 0.25, "hat", 0.5, seed=47)
        _hiper_arp(score, bar, i)
        score.note(bar, 0.0, sub_bass, _HIPER_BASS[i % 4] + 12, 4.0, amp=0.35)
        if i == bars - 1:  # rufar de colcheias para o drop
            for k, beat in enumerate((2.0, 2.5, 3.0, 3.5)):
                score.drum(bar, beat, "snare", 0.6 + 0.1 * k)


def _hiper_drop(score: Score, start: int, bars: int, raw: Dict, variant: bool = False) -> None:
    score.drum(start, 0.0, "crash", 0.8)
    for i in range(bars):
        bar = start + i
        score.drum(bar, 0.0, "kick")
        if variant and i % 2 == 1:
            score.drum(bar, 1.5, "kick", 0.85)  # bumbo adiantado: o two-step tropeca
        score.drum(bar, 2.5, "kick", 0.9)
        score.drum(bar, 1.0, "snare", 0.95)
        score.drum(bar, 3.0, "snare", 0.95)
        score.drum(bar, 3.75, "rim", 0.5)
        for eighth in range(8):
            score.drum(bar, eighth * 0.5, "hat", 0.55 if eighth % 2 else 0.35, seed=47)
        if i % 4 == 0 and i:
            score.drum(bar, 0.0, "crash", 0.5)
        score.note(bar, 0.0, reese, _HIPER_BASS[i % 4] + 12, 4.0)
        _hiper_arp(score, bar, i, amp=0.05)
    if raw.get("lead"):
        for i in range(bars):
            for mbar, beat, pitch, length in _HIPER_MELODY:
                if mbar == i % 4:
                    chord = (pitch, pitch - 5) if variant else (pitch,)
                    score.note(start + i, beat, supersaw, chord, length, layer=LAYER_LEAD)


def _hiper_drop2(score: Score, start: int, bars: int, raw: Dict) -> None:
    _hiper_drop(score, start, bars, raw, variant=True)


def _hiper_quebra(score: Score, start: int, bars: int, raw: Dict) -> None:
    for i in range(bars):
        bar = start + i
        score.note(bar, 0.0, pad, _HIPER_CHORDS[i % 4], 4.0, amp=0.11)
        score.note(bar, 0.0, sub_bass, _HIPER_BASS[i % 4] + 12, 4.0, amp=0.3)
        score.drum(bar, 0.0, "kick", 0.9)
        score.drum(bar, 2.0, "snare", 0.5)
        if i == bars - 1:
            for k, beat in enumerate((2.0, 2.5, 3.0, 3.5)):
                score.drum(bar, beat, "snare", 0.6 + 0.1 * k)
    if raw.get("lead"):
        for i in range(bars):
            score.note(start + i, 0.0, bell, _HIPER_CHORDS[i % 4][2] + 12, 3.0, layer=LAYER_LEAD, amp=0.10)


def _hiper_fim(score: Score, start: int, bars: int, raw: Dict) -> None:
    score.drum(start, 0.0, "kick")
    score.drum(start, 0.0, "crash", 0.9)
    score.note(start, 0.0, reese, 41, 3.0)
    score.note(start, 0.0, supersaw, (65, 68, 72), 3.0, amp=0.12)


SONGS: Dict[str, Dict[str, PartFn]] = {
    "mare_lenta": {
        "intro": _mare_intro,
        "tema": _mare_tema,
        "ponte": _mare_ponte,
        "final": _mare_final,
    },
    "contratempo": {
        "intro": _contra_intro,
        "verso": _contra_verso,
        "refrao": _contra_refrao,
        "quebra": _contra_quebra,
        "fim": _contra_fim,
    },
    "hiperpulso": {
        "intro": _hiper_intro,
        "build": _hiper_build,
        "drop": _hiper_drop,
        "drop2": _hiper_drop2,
        "quebra": _hiper_quebra,
        "fim": _hiper_fim,
    },
}
"""Catalogo: musica -> {parte -> funcao}. A ordem/tamanho das partes vem
da especificacao da fase (`sections`), nao daqui."""


# ------------------------------------------------------------ entrada


def _validate(spec: Dict, extra_section_keys: frozenset) -> Tuple[Dict[str, PartFn], Tuple[Dict, ...]]:
    song_id = spec.get("song")
    if song_id not in SONGS:
        raise ValueError(f"musica desconhecida {song_id!r}; disponiveis: {sorted(SONGS)}")
    sections = spec.get("sections")
    if not sections:
        raise ValueError(f"musica {song_id!r} precisa de 'sections'")
    parts = SONGS[song_id]
    allowed = SECTION_KEYS | extra_section_keys
    for index, raw in enumerate(sections):
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"chave(s) desconhecida(s) na secao {index}: {sorted(unknown)}; validas: {sorted(allowed)}")
        if int(raw.get("bars", 0)) <= 0:
            raise ValueError(f"secao {index} precisa de 'bars' > 0")
        part = raw.get("part", raw.get("name"))
        if part not in parts:
            raise ValueError(f"parte {part!r} nao existe em {song_id!r}; disponiveis: {sorted(parts)}")
    return parts, tuple(sections)


def _perform(spec: Dict, render: bool, layers: Tuple[str, ...], extra_section_keys: frozenset) -> Score:
    parts, sections = _validate(spec, extra_section_keys)
    score = Score(float(spec["bpm"]), sum(int(s["bars"]) for s in sections), render, layers)
    bar = 0
    for raw in sections:
        bars = int(raw["bars"])
        parts[raw.get("part", raw.get("name"))](score, bar, bars, raw)
        bar += bars
    return score


def render_song(spec: Dict, stem: Optional[str] = None, extra_section_keys: frozenset = frozenset()) -> np.ndarray:
    """Renderiza a musica (mono float64 em [-1, 1]).

    Com `stem` ("instrumental"/"lead"), so aquela camada -- normalizada
    pelo pico da mixagem COMPLETA, entao `instrumental + lead == mixagem`
    amostra por amostra (o contrato do Crossfading Vocal)."""
    full = _perform(spec, True, (LAYER_BACKING, LAYER_LEAD), extra_section_keys).mix
    peak = float(np.max(np.abs(full)))
    divisor = peak * 1.1 if peak > 0.0 else 1.0
    if stem is None:
        return full / divisor
    if stem not in (LAYER_BACKING, LAYER_LEAD):
        raise ValueError(f"stem desconhecido {stem!r}")
    return _perform(spec, True, (stem,), extra_section_keys).mix / divisor


def percussive_onset_times(spec: Dict, extra_section_keys: frozenset = frozenset()) -> np.ndarray:
    """Onde bumbo/caixa/palma REALMENTE estao, em segundos -- a mesma
    partitura, executada sem renderizar."""
    hits = _perform(spec, False, (), extra_section_keys).drum_hits
    return np.array(sorted(set(round(t, 9) for t in hits)), dtype=np.float64)
