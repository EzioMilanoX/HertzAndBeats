"""DSL de autoria de beatmap: escrever notas a mao, em compasso:batida.

Por que existe: o formato do `beatmap.json` e' trivial
(`{timestamp_seconds, threat_type, lane, strength}`) e o beatmap do
TUTORIAL ja e' autoral -- mas nao havia ferramenta nenhuma.
`tools/make_beatmap.py` so roda a IA. Escrever um chefao a mao significava
calcular `timestamp_seconds` em ponto flutuante com uma calculadora, e um
erro de arredondamento ali nao aparece em teste nenhum: a nota so cai
levemente fora da batida.

A DSL resolve isso escrevendo na unidade em que musica se pensa --
`compasso:batida`, 1-indexado como em qualquer DAW -- e deixando a
aritmetica para o compilador:

    # Chefao, primeira fase
    bpm 150
    lane_count 8

    5:1      basic  0
    5:2.5    heavy  4  0.95     # batida fracionaria = contratempo
    6:1..4:1 basic  2           # repeticao: de 6:1 ate 4 notas, a cada 1 batida

Regras deliberadas:

- `#` comenta ate o fim da linha; linhas vazias sao ignoradas.
- A ORDEM no arquivo nao importa: a saida sai sempre ordenada no tempo,
  porque um chart escrito por secoes tende a ficar fora de ordem e o
  jogo exige `timestamp_seconds` crescente.
- Tipos sao apelidos curtos (`basic`, `heavy`, `bomb`, `heal`), resolvidos
  contra `threat_type_ids` da config -- errar um apelido e' erro de
  compilacao com numero de linha, nunca um `threat_type` invalido no JSON.
- `strength` e' opcional e default 0.5; acima de `heavy_quantile` do
  pipeline e' o que a IA chamaria de acento.

O compilador e' PURO (texto -> dicionario) e nao escreve arquivo: quem
grava e' `tools/compile_beatmap.py`, que tambem roda o linter de
jogabilidade antes de salvar.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

DEFAULT_STRENGTH = 0.5
BEATS_PER_BAR = 4

TYPE_ALIASES: Dict[str, str] = {
    "basic": "rhythm_threat_basic",
    "heavy": "rhythm_threat_heavy",
    "bomb": "rhythm_threat_bomb",
    "heal": "rhythm_threat_heal",
    "boomerang": "rhythm_threat_boomerang",
}
"""Apelidos curtos -> `threat_type` real. Escrever `rhythm_threat_basic`
200 vezes num chart a mao seria ruido; e um apelido errado vira erro de
compilacao, enquanto um `threat_type` digitado errado no JSON so falharia
mais tarde, na validacao de dominio."""


class BeatmapSyntaxError(ValueError):
    """Erro de sintaxe com numero de linha -- a razao principal de a DSL
    existir em vez de se editar JSON a mao."""

    def __init__(self, line_number: int, line: str, problem: str) -> None:
        super().__init__(f"linha {line_number}: {problem}\n  > {line.strip()}")
        self.line_number = line_number
        self.problem = problem


@dataclass(frozen=True)
class AuthoredNote:
    time_seconds: float
    threat_type: str
    lane: int
    strength: float
    line_number: int
    """Preservado ate o linter: um aviso de jogabilidade so e' util se
    apontar a LINHA do arquivo-fonte, nao o indice no array de saida."""


def bar_beat_to_seconds(bar: int, beat: float, bpm: float) -> float:
    """`compasso:batida` (1-indexado) -> segundos. `1:1` e' o instante 0."""
    beat_seconds = 60.0 / bpm
    return ((bar - 1) * BEATS_PER_BAR + (beat - 1.0)) * beat_seconds


def _parse_position(token: str, line_number: int, line: str) -> Tuple[int, float]:
    if ":" not in token:
        raise BeatmapSyntaxError(
            line_number, line, f"posicao {token!r} sem ':' (esperado compasso:batida, ex. 5:2.5)"
        )
    bar_text, beat_text = token.split(":", 1)
    try:
        bar = int(bar_text)
        beat = float(beat_text)
    except ValueError:
        raise BeatmapSyntaxError(line_number, line, f"posicao {token!r} nao numerica") from None
    if bar < 1:
        raise BeatmapSyntaxError(line_number, line, f"compasso {bar} < 1 (a DSL e 1-indexada)")
    if not (1.0 <= beat < BEATS_PER_BAR + 1.0):
        raise BeatmapSyntaxError(
            line_number, line, f"batida {beat} fora de [1, {BEATS_PER_BAR + 1}) do compasso"
        )
    return bar, beat


def compile_beatmap_source(
    source: str, track_id: str, known_types: Optional[Sequence[str]] = None
) -> Dict:
    """Compila a DSL num dicionario no formato do `beatmap.json`.

    `known_types` (normalmente `config.threat_type_ids`) valida os tipos
    resolvidos; sem ele, so os apelidos conhecidos sao aceitos.
    """
    bpm: Optional[float] = None
    lane_count = 8
    notes: List[AuthoredNote] = []

    for line_number, raw_line in enumerate(source.splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        head = parts[0].lower()

        if head == "bpm":
            if len(parts) != 2:
                raise BeatmapSyntaxError(line_number, raw_line, "use: bpm <numero>")
            try:
                bpm = float(parts[1])
            except ValueError:
                raise BeatmapSyntaxError(line_number, raw_line, f"bpm {parts[1]!r} invalido") from None
            if bpm <= 0.0:
                raise BeatmapSyntaxError(line_number, raw_line, "bpm precisa ser > 0")
            continue

        if head == "lane_count":
            if len(parts) != 2 or not parts[1].isdigit() or int(parts[1]) < 1:
                raise BeatmapSyntaxError(line_number, raw_line, "use: lane_count <inteiro >= 1>")
            lane_count = int(parts[1])
            continue

        if bpm is None:
            raise BeatmapSyntaxError(
                line_number, raw_line, "nota antes de declarar `bpm` (o tempo nao seria calculavel)"
            )
        if len(parts) < 3:
            raise BeatmapSyntaxError(
                line_number, raw_line, "use: <compasso:batida> <tipo> <pista> [forca]"
            )

        position, type_alias, lane_text = parts[0], parts[1].lower(), parts[2]
        repeat_count, repeat_step = 1, 1.0
        if ".." in position:
            position, repeat_text = position.split("..", 1)
            if ":" not in repeat_text:
                raise BeatmapSyntaxError(
                    line_number, raw_line, "repeticao usa <pos>..<quantas>:<passo_em_batidas>"
                )
            count_text, step_text = repeat_text.split(":", 1)
            try:
                repeat_count, repeat_step = int(count_text), float(step_text)
            except ValueError:
                raise BeatmapSyntaxError(line_number, raw_line, "repeticao nao numerica") from None
            if repeat_count < 1 or repeat_step <= 0.0:
                raise BeatmapSyntaxError(
                    line_number, raw_line, "repeticao precisa de quantidade >= 1 e passo > 0"
                )

        bar, beat = _parse_position(position, line_number, raw_line)
        threat_type = TYPE_ALIASES.get(type_alias)
        if threat_type is None:
            raise BeatmapSyntaxError(
                line_number,
                raw_line,
                f"tipo {type_alias!r} desconhecido (validos: {sorted(TYPE_ALIASES)})",
            )
        if known_types is not None and threat_type not in known_types:
            raise BeatmapSyntaxError(
                line_number, raw_line, f"tipo {threat_type!r} nao existe na config desta fase"
            )
        try:
            lane = int(lane_text)
        except ValueError:
            raise BeatmapSyntaxError(line_number, raw_line, f"pista {lane_text!r} nao inteira") from None
        if not (0 <= lane < lane_count):
            raise BeatmapSyntaxError(
                line_number, raw_line, f"pista {lane} fora de [0, {lane_count})"
            )
        strength = DEFAULT_STRENGTH
        if len(parts) >= 4:
            try:
                strength = float(parts[3])
            except ValueError:
                raise BeatmapSyntaxError(line_number, raw_line, f"forca {parts[3]!r} invalida") from None
            if not (0.0 <= strength <= 1.0):
                raise BeatmapSyntaxError(line_number, raw_line, f"forca {strength} fora de [0, 1]")

        base_seconds = bar_beat_to_seconds(bar, beat, bpm)
        step_seconds = repeat_step * (60.0 / bpm)
        for index in range(repeat_count):
            notes.append(
                AuthoredNote(
                    time_seconds=base_seconds + index * step_seconds,
                    threat_type=threat_type,
                    lane=lane,
                    strength=strength,
                    line_number=line_number,
                )
            )

    if bpm is None:
        raise BeatmapSyntaxError(0, "", "arquivo sem `bpm`")
    if not notes:
        raise BeatmapSyntaxError(0, "", "arquivo sem nenhuma nota")

    # ordem temporal SEMPRE: um chart escrito por secoes sai fora de ordem
    # com facilidade, e o jogo exige `timestamp_seconds` crescente.
    notes.sort(key=lambda note: note.time_seconds)
    return {
        "version": 1,
        "track_id": track_id,
        "bpm": bpm,
        "threats": [
            {
                "timestamp_seconds": note.time_seconds,
                "threat_type": note.threat_type,
                "lane": note.lane,
                "strength": note.strength,
            }
            for note in notes
        ],
        "_authored_lines": [note.line_number for note in notes],
    }


def lint_authored_beatmap(
    beatmap: Dict,
    min_gap_seconds: float,
    max_mean_density_per_second: float,
    track_duration_seconds: Optional[float] = None,
    end_margin_seconds: float = 1.0,
) -> List[str]:
    """Roda as invariantes de JOGABILIDADE sobre um chart autoral.

    As mesmas regras de `tests/test_playability_invariants.py`, mas
    aplicadas ANTES de jogar e apontando a linha do arquivo-fonte: um
    chart a mao viola o piso de espacamento com uma facilidade enorme (foi
    o que aconteceu com a curadoria por secao autorada a 0.2 s), e
    descobrir isso jogando e' o pior momento possivel.

    Devolve uma lista de problemas legiveis -- vazia = passou.
    """
    problems: List[str] = []
    threats = beatmap["threats"]
    lines = beatmap.get("_authored_lines") or [0] * len(threats)

    for index in range(1, len(threats)):
        gap = threats[index]["timestamp_seconds"] - threats[index - 1]["timestamp_seconds"]
        if 0.0 < gap < min_gap_seconds:
            problems.append(
                f"linha {lines[index]}: gap de {gap:.3f}s da nota anterior "
                f"(minimo jogavel {min_gap_seconds}s)"
            )

    if track_duration_seconds is not None:
        last = threats[-1]["timestamp_seconds"]
        margin = track_duration_seconds - last
        if margin < end_margin_seconds:
            problems.append(
                f"linha {lines[-1]}: ultima nota a {last:.2f}s de uma faixa de "
                f"{track_duration_seconds:.2f}s (margem {margin:.2f}s < {end_margin_seconds}s "
                f"-- risco de softlock no fim)"
            )
        span = max(1e-6, track_duration_seconds)
        density = len(threats) / span
        if density > max_mean_density_per_second:
            problems.append(
                f"densidade media de {density:.2f} notas/s acima do maximo "
                f"jogavel ({max_mean_density_per_second})"
            )

    return problems
