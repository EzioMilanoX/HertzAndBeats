"""
Gera beatmaps do Hertz & Beats com a IA offline da engine -- MAPEADOR v2.

Por que v2: o mapeador original escolhia os ONSETS crus mais fortes.
Onsets marcam qualquer ataque (voz, chimbal, ruido) e o extrator ainda
os backtrackeia para o vale de energia ANTES do ataque -- notas caiam
sistematicamente adiantadas e fora da pulsacao, e o jogo "parecia
dessincronizado" mesmo com o relogio perfeito. O v2 faz o que os jogos
de ritmo reais fazem:

    1. GRADE: o beat-tracker da engine fornece os instantes das batidas;
       subdividimos em colcheias (`subdivisions=2`). TODA nota nasce em
       um ponto da grade -- nunca no timestamp cru do onset.
    2. ENERGIA: cada ponto da grade recebe a forca do onset mais forte a
       ate `snap_tolerance` dele; pontos sem evento musical ficam vazios.
    3. SELECAO: os melhores pontos (forca + bonus por cair NA batida)
       ate a densidade-alvo, com espacamento minimo e janela jogavel.
    4. LANE PELO TIMBRE: o centroide espectral no instante da nota
       escolhe a coluna/direcao (grave -> esquerda/baixo, agudo ->
       direita/cima) por quantis da propria musica: o mesmo som repete a
       mesma lane (padroes musicais viram padroes de jogo), com
       anti-jack para nao exigir repeticoes impossiveis.

As etapas 1-4 sao FUNCOES PURAS sobre arrays (testaveis sem librosa);
librosa entra apenas via os extratores da engine e no centroide.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from ouroboros.rhythm.offline.audio_loader import AudioLoader
from ouroboros.rhythm.offline.beatmap_schema import BeatmapValidator, ScheduledThreatDefinition
from ouroboros.rhythm.offline.beatmap_writer import BeatmapWriter
from ouroboros.rhythm.offline.bpm_extractor import BpmExtractor
from ouroboros.rhythm.offline.extraction_profiles import (
    EXTRACTION_PROFILES,
    LAYER_KICK,
    LAYER_VOCAL,
    estimate_bpm_from_pulses,
    extract_with_profile,
)
from ouroboros.rhythm.offline.onset_extractor import OnsetExtractor

from hertzbeats.audio.demo_track_synth import section_time_windows
from hertzbeats.mapper_version import MAPPER_VERSION

THREAT_TYPE_BASIC = "rhythm_threat_basic"
THREAT_TYPE_HEAVY = "rhythm_threat_heavy"

ON_BEAT_SCORE_BONUS = 0.35
"""Bonus de selecao para pontos que caem NA batida (vs colcheia): a
espinha do mapa deve ser a pulsacao, subdivisoes entram como tempero."""


# ------------------------------------------------------------------ puras

def build_beat_grid(beat_times: np.ndarray, subdivisions: int = 2) -> Tuple[np.ndarray, np.ndarray]:
    """Constroi a grade ritmica a partir dos instantes de batida do
    beat-tracker: cada intervalo entre batidas consecutivas e dividido em
    `subdivisions` partes iguais. Retorna `(grid_times, on_beat)` --
    `on_beat[i]` True quando o ponto e uma batida inteira."""
    beat_times = np.asarray(beat_times, dtype=np.float64)
    if beat_times.shape[0] < 2:
        return beat_times.copy(), np.ones(beat_times.shape[0], dtype=bool)

    grid = []
    on_beat = []
    for i in range(beat_times.shape[0] - 1):
        start, end = beat_times[i], beat_times[i + 1]
        for k in range(subdivisions):
            grid.append(start + (end - start) * k / subdivisions)
            on_beat.append(k == 0)
    grid.append(beat_times[-1])
    on_beat.append(True)
    return np.asarray(grid, dtype=np.float64), np.asarray(on_beat, dtype=bool)


def build_uniform_grid(
    bpm: float,
    span_start_seconds: float,
    span_end_seconds: float,
    subdivisions: int,
    phase_reference_times: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """Grade REGULAR no BPM detectado, com a fase travada nos pulsos reais.

    Substitui `build_beat_grid` (que interpola entre pulsos CONSECUTIVOS do
    beat-tracker) porque aquela abordagem herda a esparsez do detector de
    pulso. Medido num piano solo de 183 s: o PLP achou 75 pulsos -- piano nao
    tem bumbo pra dar pulso forte -- e a grade resultante tinha 149 pontos,
    um teto de 0.81 nota/s para 942 onsets detectados. Nenhum parametro de
    densidade conseguia furar esse teto, porque nao havia CASA na grade.

    A fase vem da media CIRCULAR dos pulsos modulo o periodo da batida: e o
    jeito correto de achar "onde caem os tempos" a partir de deteccoes
    ruidosas -- media aritmetica de valores que dao a volta em 0 (um pulso a
    0.01 e outro a 0.39 de um periodo de 0.40) daria o meio errado.

    `on_beat` marca batidas inteiras; as subdivisoes entre elas ficam False,
    e e' isso que `select_slots` usa pra preferir o tempo forte quando
    precisa escolher.
    """
    if bpm <= 0.0 or span_end_seconds <= span_start_seconds:
        return np.zeros(0), np.zeros(0, dtype=bool)

    beat_seconds = 60.0 / float(bpm)
    step = beat_seconds / max(1, int(subdivisions))

    offset = 0.0
    reference = np.asarray(phase_reference_times, dtype=np.float64)
    if reference.shape[0] > 0:
        angles = 2.0 * np.pi * (reference % beat_seconds) / beat_seconds
        offset = float(np.angle(np.mean(np.exp(1j * angles))) / (2.0 * np.pi) * beat_seconds)

    first_index = int(np.floor((span_start_seconds - offset) / step))
    last_index = int(np.ceil((span_end_seconds - offset) / step))
    indices = np.arange(first_index, last_index + 1)
    grid = offset + indices * step
    inside = (grid >= span_start_seconds) & (grid <= span_end_seconds)
    grid = grid[inside]
    on_beat = (indices[inside] % max(1, int(subdivisions))) == 0
    return grid, on_beat


def snap_onsets_to_grid(
    grid_times: np.ndarray,
    onset_times: np.ndarray,
    onset_strengths: np.ndarray,
    snap_tolerance: float = 0.08,
) -> Tuple[np.ndarray, np.ndarray]:
    """Para cada ponto da grade: `(forca, tem_evento)`. `tem_evento` e
    um booleano proprio -- a normalizacao de strength da engine colapsa
    a maioria dos onsets em ~0.0, entao "forca zero" NAO significa "nada
    aconteceu ali". O TEMPO da nota sera o da GRADE; o onset so vota em
    quais pontos importam -- e assim que o vies de backtracking dos
    onsets deixa de dessincronizar as notas."""
    slot_strengths = np.zeros(grid_times.shape[0], dtype=np.float64)
    slot_has_event = np.zeros(grid_times.shape[0], dtype=bool)
    if onset_times.shape[0] == 0:
        return slot_strengths, slot_has_event
    order = np.argsort(onset_times)
    sorted_times = np.asarray(onset_times, dtype=np.float64)[order]
    sorted_strengths = np.asarray(onset_strengths, dtype=np.float64)[order]

    for slot_index in range(grid_times.shape[0]):
        slot_time = grid_times[slot_index]
        left = np.searchsorted(sorted_times, slot_time - snap_tolerance, side="left")
        right = np.searchsorted(sorted_times, slot_time + snap_tolerance, side="right")
        if right > left:
            slot_strengths[slot_index] = float(np.max(sorted_strengths[left:right]))
            slot_has_event[slot_index] = True
    return slot_strengths, slot_has_event


def select_slots(
    grid_times: np.ndarray,
    on_beat: np.ndarray,
    slot_strengths: np.ndarray,
    slot_has_event: np.ndarray,
    min_start_seconds: float,
    max_end_seconds: float,
    min_gap_seconds: float,
    target_density_per_second: float,
) -> List[int]:
    """Escolhe os pontos da grade que viram notas: guloso por
    `forca + bonus_na_batida`, respeitando janela jogavel, espacamento
    minimo e densidade-alvo. So pontos COM evento musical
    (`slot_has_event`) sao elegiveis. Retorna indices em ordem temporal."""
    playable_span = max(0.0, max_end_seconds - min_start_seconds)
    max_slots = int(round(target_density_per_second * playable_span))
    if max_slots <= 0:
        return []

    scores = slot_strengths + np.where(on_beat, ON_BEAT_SCORE_BONUS, 0.0)
    by_score = sorted(
        range(grid_times.shape[0]), key=lambda i: float(scores[i]), reverse=True
    )
    accepted_times: List[float] = []
    accepted: List[int] = []
    for slot_index in by_score:
        if len(accepted) >= max_slots:
            break
        if not slot_has_event[slot_index]:
            continue  # ponto sem evento musical: nunca vira nota
        slot_time = float(grid_times[slot_index])
        if slot_time < min_start_seconds or slot_time > max_end_seconds:
            continue
        insert_at = bisect.bisect_left(accepted_times, slot_time)
        if insert_at > 0 and slot_time - accepted_times[insert_at - 1] < min_gap_seconds:
            continue
        if insert_at < len(accepted_times) and accepted_times[insert_at] - slot_time < min_gap_seconds:
            continue
        accepted_times.insert(insert_at, slot_time)
        accepted.append(slot_index)

    return sorted(accepted, key=lambda i: float(grid_times[i]))


def select_strongest_unquantized(
    times: np.ndarray,
    strengths: np.ndarray,
    min_start_seconds: float,
    max_end_seconds: float,
    min_gap_seconds: float,
    max_notes: int,
) -> List[int]:
    """Selecao SEM grade (camada vocal / plano B): os eventos mais
    fortes, gulosos, com espacamento minimo e janela jogavel -- abraca a
    sincopa em vez de quantizar. Retorna indices em ordem temporal."""
    if max_notes <= 0:
        return []
    order = sorted(range(times.shape[0]), key=lambda i: float(strengths[i]), reverse=True)
    accepted_times: List[float] = []
    accepted: List[int] = []
    for index in order:
        if len(accepted) >= max_notes:
            break
        t = float(times[index])
        if t < min_start_seconds or t > max_end_seconds:
            continue
        pos = bisect.bisect_left(accepted_times, t)
        if pos > 0 and t - accepted_times[pos - 1] < min_gap_seconds:
            continue
        if pos < len(accepted_times) and accepted_times[pos] - t < min_gap_seconds:
            continue
        accepted_times.insert(pos, t)
        accepted.append(index)
    return sorted(accepted, key=lambda i: float(times[i]))


def enforce_minimum_separation(
    times: np.ndarray, strengths: np.ndarray, layers: List[str], minimum_seconds: float
) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """Passagem FINAL: varre o chart ja fundido em ordem e descarta toda
    nota que caia a menos de `minimum_seconds` da ultima ACEITA.

    Existe por duas brechas que nem a selecao por janela nem a fusao
    fecham:

    1. A fusao aceita uma nota vocal a `0.5 * min_gap` de um kick -- com o
       gap de 0.45 s das fases curadas isso da 0.225 s, ABAIXO do piso
       jogavel de 0.30 s que `tests/test_playability_invariants.py`
       protege. Medido: um gap real de 0.232 s apareceu no verso.
    2. A selecao por SECAO nao ve as vizinhas, entao dois kicks podem
       ficar colados na FRONTEIRA entre duas janelas -- cada um legitimo
       dentro da sua secao, injogaveis juntos.

    Prioridade temporal (nunca por forca) de proposito: manter a nota
    ANTERIOR preserva o alinhamento do downbeat, e um chart que perde o
    downbeat pra manter um onset mais forte soa errado mesmo estando
    "mais certo" no papel.
    """
    if minimum_seconds <= 0.0 or times.shape[0] == 0:
        return times, strengths, layers
    keep = [0]
    last_kept = float(times[0])
    for i in range(1, times.shape[0]):
        if float(times[i]) - last_kept >= minimum_seconds:
            keep.append(i)
            last_kept = float(times[i])
    indices = np.asarray(keep, dtype=np.int64)
    return times[indices], strengths[indices], [layers[i] for i in keep]


def merge_note_layers(
    kick_times: np.ndarray,
    kick_strengths: np.ndarray,
    vocal_times: np.ndarray,
    vocal_strengths: np.ndarray,
    min_separation_seconds: float,
) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """Funde as camadas do perfil "hybrid" com PRIORIDADE do kick: as
    notas de groove (quantizadas) entram todas; uma nota vocal so entra
    se ficar a pelo menos `min_separation_seconds` de qualquer nota ja
    aceita (o esqueleto ritmico nunca e empurrado pela melodia).
    Retorna `(tempos, forcas, layers)` em ordem temporal."""
    accepted_times: List[float] = [float(t) for t in kick_times]
    merged = [
        (float(kick_times[i]), float(kick_strengths[i]), LAYER_KICK)
        for i in range(kick_times.shape[0])
    ]
    for i in range(vocal_times.shape[0]):
        t = float(vocal_times[i])
        pos = bisect.bisect_left(accepted_times, t)
        if pos > 0 and t - accepted_times[pos - 1] < min_separation_seconds:
            continue
        if pos < len(accepted_times) and accepted_times[pos] - t < min_separation_seconds:
            continue
        accepted_times.insert(pos, t)
        merged.append((t, float(vocal_strengths[i]), LAYER_VOCAL))

    merged.sort(key=lambda item: item[0])
    times = np.asarray([item[0] for item in merged], dtype=np.float64)
    strengths = np.asarray([item[1] for item in merged], dtype=np.float64)
    layers = [item[2] for item in merged]
    return times, strengths, layers


def assign_lanes(
    slot_times: np.ndarray,
    slot_centroids: np.ndarray,
    lane_count: int = 8,
    anti_jack_gap_seconds: float = 0.22,
) -> List[int]:
    """Lane pelo TIMBRE: os centroides espectrais da propria musica sao
    divididos em `lane_count` quantis -- som grave vira lane baixa, som
    agudo vira lane alta, e o MESMO som repete a MESMA lane (padrao
    musical = padrao de jogo). Anti-jack: nota na mesma lane da anterior
    com gap menor que `anti_jack_gap_seconds` desloca para a vizinha."""
    n = slot_times.shape[0]
    if n == 0:
        return []
    quantiles = np.quantile(slot_centroids, np.linspace(0.0, 1.0, lane_count + 1)[1:-1])
    lanes = np.searchsorted(quantiles, slot_centroids, side="right").astype(int)

    result = []
    for i in range(n):
        lane = int(lanes[i])
        if result and lane == result[-1] and float(slot_times[i] - slot_times[i - 1]) < anti_jack_gap_seconds:
            lane = (lane + 1) % lane_count
        result.append(lane)
    return result


# ------------------------------------------------------------ com librosa

def _spectral_centroids_at(audio, times: np.ndarray) -> np.ndarray:
    """Centroide espectral (Hz) da musica no instante de cada nota."""
    import librosa  # offline-only

    hop_length = 512
    centroids = librosa.feature.spectral_centroid(
        y=audio.samples, sr=audio.sample_rate, hop_length=hop_length
    )[0]
    frame_times = librosa.frames_to_time(
        np.arange(centroids.shape[0]), sr=audio.sample_rate, hop_length=hop_length
    )
    indices = np.clip(np.searchsorted(frame_times, times), 0, centroids.shape[0] - 1)
    return centroids[indices]


TRANSCRIPTION_SUBDIVISIONS = 8
TRANSCRIPTION_MIN_GAP_BEATS = 0.24
"""Configuracao da TRANSCRICAO (nao do chart jogavel).

Separar transcricao de jogabilidade foi a mudanca que destravou tudo. Antes,
o piso de jogabilidade (300 ms) era aplicado DENTRO da selecao, e por isso
destruia informacao de forma irreversivel: pedir 0.24 batidas de
espacamento dava o mesmo resultado que pedir 0.75, porque os dois eram
elevados a 300 ms. O beatmap em disco era, ao mesmo tempo, a melhor
transcricao possivel e o chart jogavel -- e nao pode ser as duas coisas.

Agora o beatmap em disco e' a transcricao FIEL, e a reducao para o que e
jogavel acontece na composicao, ciente do modo
(`hertzbeats.playability_reduction`).

Medido num piano solo (183 s, 1051 onsets detectados):

  grade dos pulsos, sub=2, piso 300 ms ->  216 notas, cobertura  56%
  grade uniforme,   sub=4, piso 300 ms ->  428 notas, cobertura  68%
  grade uniforme,   sub=8, piso 300 ms ->  469 notas, cobertura  74%
  grade uniforme,   sub=8, SEM piso    ->  951 notas, cobertura 100%

Zero notas fantasma em todas as configuracoes -- a fidelidade subiu sem
custo nenhum de precisao.

`sub=8` (fusas) e nao 16: com 16 a contagem sobe para 1882 notas sem ganho
de cobertura, ou seja, passa a inventar subdivisao que a musica nao tem.
"""

DEFAULT_SNAP_TOLERANCE_SECONDS = 0.04
"""Distancia maxima entre um ataque real e o ponto da grade em que ele
vira nota.

Era 0.08 s, e isso produzia NOTAS FANTASMA -- notas que o jogador ve mas
nao ouve. A nota e gravada no instante da GRADE, nao do ataque: com 80 ms
de tolerancia, um ataque a 80 ms do ponto de grade ainda "preenchia" aquele
ponto, e a nota nascia 80 ms longe do som que a justificou. A janela
PERFECT do jogo e 50 ms -- ou seja, a nota podia cair FORA da propria
janela em que o som acontece.

A regra e simples e nao tinha sido aplicada: a tolerancia de snap precisa
ser MENOR que a janela PERFECT, senao quantizar move a nota para fora do
evento que a gerou.

Medido numa faixa de rhythm game a 161 BPM: com 0.08 s, 4.8% das notas
ficavam a mais de 50 ms de qualquer ataque real; com 0.04 s, 0.0% -- e a
cobertura dos ataques fortes ainda SUBIU de leve (80.1% -> 80.9%), porque
notas mal-encaixadas deixaram de gastar espacamento minimo que valia mais
para vizinhas bem-encaixadas."""

MIN_PLAYABLE_GAP_SECONDS = 0.30
"""Piso de jogabilidade: ameacas mais juntas que isto caem dentro da janela
de julgamento uma da outra. Mesmo valor que
`tests/test_playability_invariants.py` protege."""

DEFAULT_MIN_GAP_BEATS = 0.75
"""Espacamento minimo entre notas, em BATIDAS -- nao em segundos.

O bug que isto conserta: um `min_gap_seconds` fixo significa coisas
DIFERENTES em cada tempo. A 0.45 s (o default historico):

    90 BPM -> 0.68 batidas   (cabe 1 nota por batida)
   120 BPM -> 0.90 batidas   (cabe 1 nota por batida)
   152 BPM -> 1.14 batidas   (IMPOSSIVEL tocar 2 batidas seguidas)
   180 BPM -> 1.35 batidas   (pior ainda)

Acima de 1 batida o chart nao pode marcar batidas consecutivas -- e como a
selecao escolhe por FORCA, ele pula de forma irregular: toca na 1, depois na
3, depois na 4, depois na 2. Cada nota individual cai num ataque real do
audio (medido: 81% a menos de 10 ms), mas o conjunto nao forma PULSO. O
jogador sente exatamente isso: "as notas estao certas mas nao parece
sincronizado".

Medido num piano solo a 152 BPM, variando so este parametro:

    1.15 batidas -> IOI mediano 789 ms (2 batidas!), regularidade 30%
    1.00 batidas -> IOI mediano 604 ms,              regularidade 25%
    0.90 batidas -> IOI mediano 418 ms (1 batida),   regularidade 63%
    0.75 batidas -> IOI mediano 418 ms,              regularidade 63%

Medido depois, com a tolerancia de snap corrigida: 0.75 batidas cobre mais
ataques fortes que 0.90 nas duas familias de musica testadas (rhythm game
161 BPM: 80.9% -> 83.3%; piano solo 152 BPM: 57.9% -> 58.1%), sem nenhuma
nota fantasma. Por isso o default e 0.75 e nao 0.90.

O 1.00 ser PIOR que 1.15 nao e ruido: no limite exato, o jitter dos onsets
faz o seletor aceitar algumas batidas consecutivas e rejeitar outras -- o
maximo de irregularidade possivel. Por isso o default e 0.9 e nao 1.0:
precisa de folga abaixo da batida, nao de igualdade.

Em musica muito rapida o piso de jogabilidade vence (a 200 BPM, 0.9 batidas
= 0.27 s < 0.30 s) e pular batida volta a ser inevitavel -- ai e limite do
jogo, nao da analise.
"""

DEFAULT_ONSET_LAG_SECONDS = 0.018
"""Atraso SISTEMATICO do extrator de onsets, em segundos.

Nao e chute: medido contra a verdade fundamental das faixas sintetizadas
(`demo_track_synth.percussive_onset_times`, que sabe exatamente onde cada
bumbo esta). Em 213 notas de 4 faixas, 98% caiam ATRASADAS -- media
+18.4 ms, desvio 9.0 ms.

A causa e a convencao de frame do DSP, nao a musica: o instante vem do
PICO do envelope de fluxo espectral, que acontece 1-2 frames depois do
transiente que o gerou (hop 512 a 44.1 kHz = 11.6 ms por frame). Por isso
o vies e praticamente o mesmo em faixas de BPM e estilo diferentes -- e
por isso vale como default tambem pra musica do jogador, onde nao existe
verdade fundamental pra medir.

Nas faixas CURADAS este default nem e usado: `generate_stage_assets.py`
mede o desvio real de cada faixa e desconta exatamente aquele. A constante
serve pra `music_library` (musica do jogador), onde medir e impossivel.

Num jogo cuja janela PERFECT e 50 ms, 18 ms de vies consomem 40% da janela
antes de o jogador tocar em nada -- era a diferenca entre "a IA acerta a
batida" e "quase".
"""


@dataclass(frozen=True)
class _CurationWindow:
    """Uma janela de tempo com seus proprios parametros de curadoria."""

    name: str
    start_seconds: float
    end_seconds: float
    min_gap_seconds: float
    density: float

    @property
    def span_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)


def _build_curation_windows(
    synth_spec: Optional[Dict],
    min_start_seconds: float,
    max_end_seconds: float,
    min_gap_seconds: float,
    target_density_per_second: float,
) -> List[_CurationWindow]:
    """Uma janela por secao musical, recortadas contra a faixa jogavel.

    Cada secao pode declarar `min_gap_seconds`/`target_density_per_second`
    proprios; o que ela nao declarar herda o parametro global. Secoes que
    caem inteiramente fora de `[min_start_seconds, max_end_seconds)` (a
    intro antes do primeiro instante jogavel, a cauda depois da margem
    final) sao descartadas -- sem isso, uma janela de span zero pediria
    `max_notes=0` e so gastaria trabalho.

    Sem faixa seccionada, devolve a UNICA janela global: o comportamento
    historico, e a razao de a saida seguir bit a bit identica pras faixas
    planas.
    """
    windows: List[_CurationWindow] = []
    for name, start, end, raw in section_time_windows(synth_spec or {}):
        clipped_start = max(start, min_start_seconds)
        clipped_end = min(end, max_end_seconds)
        if clipped_end - clipped_start <= 0.0:
            continue
        windows.append(
            _CurationWindow(
                name=name,
                start_seconds=clipped_start,
                end_seconds=clipped_end,
                min_gap_seconds=float(raw.get("min_gap_seconds", min_gap_seconds)),
                density=float(raw.get("target_density_per_second", target_density_per_second)),
            )
        )
    if not windows:
        windows.append(
            _CurationWindow(
                name="",
                start_seconds=min_start_seconds,
                end_seconds=max_end_seconds,
                min_gap_seconds=min_gap_seconds,
                density=target_density_per_second,
            )
        )
    return windows


def generate_beatmap(
    audio_path: Path,
    output_path: Path,
    track_id: str,
    lane_count: int = 8,
    min_gap_seconds: float = 0.45,
    min_start_seconds: float = 2.5,
    target_density_per_second: float = 1.4,
    end_margin_seconds: float = 1.2,
    heavy_quantile: float = 0.92,
    subdivisions: int = 2,
    snap_tolerance_seconds: float = DEFAULT_SNAP_TOLERANCE_SECONDS,
    profile: str = "groove",
    hybrid_kick_share: float = 0.60,
    synth_spec: Optional[Dict] = None,
    min_note_separation_seconds: Optional[float] = None,
    onset_lag_seconds: float = 0.0,
    min_gap_beats: Optional[float] = None,
    target_density_per_beat: Optional[float] = None,
    grid_mode: str = "pulses",
    playability_floor_seconds: float = MIN_PLAYABLE_GAP_SECONDS,
) -> dict:
    """Roda a IA da engine sobre `audio_path` com o PERFIL DE EXTRACAO
    pedido e grava um beatmap.json.

    Perfis (a matematica vive na engine, `extraction_profiles`; aqui e
    so interpretacao/curadoria):
        "groove"      -- notas QUANTIZADAS na grade do PLP percussivo
                         (faixas guiadas por bumbo), camada "kick".
        "vocal_shred" -- notas SEM quantizacao nos onsets da melodia
                         (faixas guiadas por voz/synth, estilo FNF),
                         camada "vocal".
        "hybrid"      -- esqueleto kick quantizado (`hybrid_kick_share`
                         da densidade) + melodia vocal sincopada por
                         cima, fundidas com prioridade do kick; cada
                         nota carrega a tag `layer` para o roteamento
                         espacial do jogo.

    CURADORIA POR SECAO (`synth_spec`): com uma faixa seccionada
    (`{"bpm", "sections": [...]}`), a selecao de notas roda uma vez POR
    SECAO, cada uma com seu proprio `min_gap_seconds`/
    `target_density_per_second` (declarados na propria secao em
    `stages.json`, com os parametros globais como default). E o que faz a
    dificuldade do chart seguir a MUSICA em vez de ser uniforme: uma
    ponte `calm` respira com gap largo, um climax `intense` aperta e
    libera as semicolcheias da melodia, que um gap global de 0.45 s
    descartaria sempre.

    Sem `synth_spec` (ou faixa plana), roda uma unica janela cobrindo
    `[min_start_seconds, max_end_seconds)` com os parametros globais --
    exatamente o comportamento historico, bit a bit.

    `min_note_separation_seconds` (opt-in, default `None` = desligado)
    aplica `enforce_minimum_separation` no chart final. Fica opcional de
    proposito: liga-lo por default mudaria TODO beatmap ja cacheado de
    musica do jogador (que usa o perfil "hybrid") e exigiria bumpar
    `MAPPER_VERSION`. Ver o docstring daquela funcao para as duas brechas
    que ela fecha.

    `min_gap_beats`/`target_density_per_beat` expressam espacamento e
    densidade em BATIDAS em vez de segundos, resolvidos contra o BPM que a
    extracao detectou. E o que faz o chart seguir o PULSO da musica em vez
    de uma constante cega ao tempo -- ver `DEFAULT_MIN_GAP_BEATS` para a
    medicao que justifica o valor. Ambos `None` (default) preservam o
    comportamento absoluto historico.

    `onset_lag_seconds` desconta o atraso SISTEMATICO do extrator de cada
    instante gravado (ver `DEFAULT_ONSET_LAG_SECONDS`). Default 0.0 =
    desligado, preservando o comportamento historico de quem chamar sem
    pedir a correcao.

    Retorna um resumo primitivo (bpm, contagens por camada) para a CLI."""
    if profile not in EXTRACTION_PROFILES:
        raise ValueError(f"perfil desconhecido: {profile!r} (validos: {EXTRACTION_PROFILES})")

    audio = AudioLoader().load(Path(audio_path))
    track_duration = audio.samples.shape[0] / float(audio.sample_rate)
    max_end_seconds = track_duration - end_margin_seconds
    playable_span = max(0.0, max_end_seconds - min_start_seconds)

    # Estagio DSP na ENGINE; fallback para os extratores genericos
    # (audio exotico nunca derruba a analise).
    try:
        layers = {layer.layer: layer for layer in extract_with_profile(audio, profile).layers}
        dsp_stage = f"profile:{profile}"
    except Exception as exc:
        print(f"[mapper] perfil '{profile}' falhou ({exc}); usando extratores genericos")
        layers = {}
        dsp_stage = "generic-fallback"

    kick_layer = layers.get(LAYER_KICK)
    vocal_layer = layers.get(LAYER_VOCAL)

    # -- espacamento RELATIVO AO TEMPO (ver `DEFAULT_MIN_GAP_BEATS`) ----
    # Resolvido aqui porque o BPM da camada de groove ja existe -- vem da
    # extracao, antes de qualquer selecao. Sem BPM confiavel (perfil
    # vocal_shred, audio sem pulso), mantem os valores absolutos.
    beat_bpm = kick_layer.tempo_bpm_estimate if kick_layer is not None else 0.0
    if beat_bpm > 0.0 and (min_gap_beats is not None or target_density_per_beat is not None):
        beat_seconds = 60.0 / float(beat_bpm)
        if min_gap_beats is not None:
            # o piso e PARAMETRO, nao constante: a transcricao fiel precisa
            # poder ignora-lo (`playability_floor_seconds=0.0`) e deixar a
            # reducao para um estagio posterior, consciente de modo. Com o
            # piso embutido aqui, pedir 0.24 batidas dava o MESMO resultado
            # que pedir 0.75 -- os dois eram elevados a 0.30 s.
            min_gap_seconds = max(
                float(playability_floor_seconds), float(min_gap_beats) * beat_seconds
            )
        if target_density_per_beat is not None:
            target_density_per_second = float(target_density_per_beat) / beat_seconds

    # -- janelas de curadoria: uma por secao musical, ou uma so global --
    curation_windows = _build_curation_windows(
        synth_spec, min_start_seconds, max_end_seconds, min_gap_seconds, target_density_per_second
    )

    # -- camada kick: quantizada na grade dos pulsos do PLP ------------
    kick_times = np.zeros(0)
    kick_strengths = np.zeros(0)
    on_beat_count = 0
    quantized = False
    vocal_times = np.zeros(0)
    vocal_strengths = np.zeros(0)
    if kick_layer is not None and kick_layer.pulse_timestamps_seconds.shape[0] >= 8:
        # A grade e o snap sao GLOBAIS (dependem do pulso da faixa
        # inteira, nao da secao) -- calculados uma vez, fora do laco; so a
        # SELECAO e por janela.
        if grid_mode == "uniform" and kick_layer.tempo_bpm_estimate > 0.0:
            grid_times, on_beat = build_uniform_grid(
                kick_layer.tempo_bpm_estimate,
                min_start_seconds,
                max_end_seconds,
                subdivisions,
                kick_layer.pulse_timestamps_seconds,
            )
        else:
            grid_times, on_beat = build_beat_grid(
                kick_layer.pulse_timestamps_seconds, subdivisions=subdivisions
            )
        slot_strengths, slot_has_event = snap_onsets_to_grid(
            grid_times,
            kick_layer.onset_timestamps_seconds,
            kick_layer.onset_strengths,
            snap_tolerance=snap_tolerance_seconds,
        )
        kick_parts = []
        strength_parts = []
        for window in curation_windows:
            kick_budget = window.density * (hybrid_kick_share if vocal_layer is not None else 1.0)
            chosen = select_slots(
                grid_times, on_beat, slot_strengths, slot_has_event,
                min_start_seconds=window.start_seconds,
                max_end_seconds=window.end_seconds,
                min_gap_seconds=window.min_gap_seconds,
                target_density_per_second=kick_budget,
            )
            kick_parts.append(grid_times[chosen])
            strength_parts.append(slot_strengths[chosen])
            on_beat_count += int(np.count_nonzero(on_beat[chosen]))
        kick_times = np.concatenate(kick_parts) if kick_parts else np.zeros(0)
        kick_strengths = np.concatenate(strength_parts) if strength_parts else np.zeros(0)
        quantized = True

    # -- camada vocal: sincopada, sem grade ----------------------------
    if vocal_layer is not None:
        vocal_share = 1.0 if kick_layer is None else (1.0 - hybrid_kick_share)
        vocal_parts = []
        vocal_strength_parts = []
        for window in curation_windows:
            vocal_chosen = select_strongest_unquantized(
                vocal_layer.onset_timestamps_seconds,
                vocal_layer.onset_strengths,
                min_start_seconds=window.start_seconds,
                max_end_seconds=window.end_seconds,
                min_gap_seconds=window.min_gap_seconds,
                max_notes=int(round(window.density * vocal_share * window.span_seconds)),
            )
            vocal_parts.append(vocal_layer.onset_timestamps_seconds[vocal_chosen])
            vocal_strength_parts.append(vocal_layer.onset_strengths[vocal_chosen])
        vocal_times = np.concatenate(vocal_parts) if vocal_parts else np.zeros(0)
        vocal_strengths = np.concatenate(vocal_strength_parts) if vocal_strength_parts else np.zeros(0)

    # -- fallback generico (sem camada alguma) -------------------------
    generic_bpm = None
    if kick_layer is None and vocal_layer is None:
        bpm_result = BpmExtractor().extract(audio)
        generic_bpm = float(bpm_result.bpm)
        onset_result = OnsetExtractor().extract(audio)
        beat_times = np.asarray(bpm_result.beat_timestamps_seconds, dtype=np.float64)
        if beat_times.shape[0] >= 8:
            grid_times, on_beat = build_beat_grid(beat_times, subdivisions=subdivisions)
            slot_strengths, slot_has_event = snap_onsets_to_grid(
                grid_times, onset_result.onset_timestamps_seconds,
                onset_result.onset_strengths, snap_tolerance=snap_tolerance_seconds,
            )
            chosen = select_slots(
                grid_times, on_beat, slot_strengths, slot_has_event,
                min_start_seconds=min_start_seconds, max_end_seconds=max_end_seconds,
                min_gap_seconds=min_gap_seconds,
                target_density_per_second=target_density_per_second,
            )
            kick_times = grid_times[chosen]
            kick_strengths = slot_strengths[chosen]
            on_beat_count = int(np.count_nonzero(on_beat[chosen]))
            quantized = True
        else:
            chosen = select_strongest_unquantized(
                onset_result.onset_timestamps_seconds, onset_result.onset_strengths,
                min_start_seconds, max_end_seconds, min_gap_seconds,
                int(round(target_density_per_second * playable_span)),
            )
            kick_times = onset_result.onset_timestamps_seconds[chosen]
            kick_strengths = onset_result.onset_strengths[chosen]

    # -- fusao multi-camada com prioridade do esqueleto ritmico --------
    # A fusao usa a MENOR separacao entre as janelas: com um unico valor
    # global (o antigo `0.5 * min_gap_seconds`), a secao mais folgada
    # ditaria o corte pra faixa inteira e apagaria justamente as notas
    # densas que uma secao apertada acabou de escolher de proposito.
    note_times, note_strengths, note_layers = merge_note_layers(
        kick_times, kick_strengths, vocal_times, vocal_strengths,
        min_separation_seconds=0.5 * min(w.min_gap_seconds for w in curation_windows),
    )
    if min_note_separation_seconds is not None:
        note_times, note_strengths, note_layers = enforce_minimum_separation(
            note_times, note_strengths, note_layers, float(min_note_separation_seconds)
        )

    if kick_layer is not None and kick_layer.tempo_bpm_estimate > 0.0:
        detected_bpm = kick_layer.tempo_bpm_estimate
    elif generic_bpm is not None:
        detected_bpm = generic_bpm
    else:
        detected_bpm = estimate_bpm_from_pulses(note_times)  # vocal_shred: so metadado

    centroids = (
        _spectral_centroids_at(audio, note_times) if note_times.shape[0] else np.zeros(0)
    )
    lanes = assign_lanes(note_times, centroids, lane_count=lane_count)

    # Pesadas por QUANTIL, nunca por limiar absoluto: cada estagio de
    # extracao normaliza forcas numa escala propria (o generico colapsa
    # em ~0, o percussivo satura em ~1) -- um corte fixo ou marca tudo
    # ou nada. Os acentos reais sao o topo da distribuicao DA PROPRIA
    # musica, com guarda para distribuicoes achatadas (sem acento claro
    # -> sem pesadas).
    if note_times.shape[0]:
        heavy_cutoff = float(np.quantile(note_strengths, heavy_quantile))
        strength_median = float(np.median(note_strengths))
    else:
        heavy_cutoff = np.inf
        strength_median = 0.0

    threats: List[ScheduledThreatDefinition] = []
    heavy_count = 0
    for i in range(note_times.shape[0]):
        strength = float(min(max(note_strengths[i], 0.0), 1.0))
        is_heavy = strength >= heavy_cutoff and strength > strength_median + 1e-6
        heavy_count += int(is_heavy)
        threats.append(
            ScheduledThreatDefinition(
                # correcao do vies do extrator aplicada AQUI, no instante
                # gravado -- e nao antes: `lanes`/`centroids` amostram o
                # audio na posicao ORIGINAL da nota, e desloca-los faria a
                # pista ser decidida por um trecho de audio vizinho.
                timestamp_seconds=max(0.0, float(note_times[i]) - onset_lag_seconds),
                threat_type=THREAT_TYPE_HEAVY if is_heavy else THREAT_TYPE_BASIC,
                lane=int(lanes[i]),
                strength=strength,
                layer=note_layers[i],
            )
        )

    validator = BeatmapValidator()
    beatmap_dict = validator.build_beatmap_dict(
        track_id=track_id,
        bpm=float(detected_bpm),
        threats=tuple(threats),
    )
    beatmap_dict["mapper_version"] = MAPPER_VERSION
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    BeatmapWriter(validator).write(beatmap_dict, output_path)

    return {
        "bpm": float(detected_bpm),
        "profile": profile,
        "threat_count": len(threats),
        "kick_count": sum(1 for layer_tag in note_layers if layer_tag == LAYER_KICK),
        "vocal_count": sum(1 for layer_tag in note_layers if layer_tag == LAYER_VOCAL),
        "heavy_count": heavy_count,
        "on_beat_count": on_beat_count,
        "quantized": quantized,
        "dsp_stage": dsp_stage,
        "output_path": str(output_path),
    }
