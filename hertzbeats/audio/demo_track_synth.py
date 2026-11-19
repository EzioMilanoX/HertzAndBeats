"""
Sintese DETERMINISTICA das faixas das fases (numpy puro + stdlib wave,
sem librosa). Nenhum .wav e versionado no repositorio: qualquer maquina
reconstroi bit a bit a mesma faixa a partir da especificacao `synth` da
fase -- por isso o beatmap.json gerado pela IA offline sobre ela
permanece valido apos um clone.

A especificacao aceita DUAS formas:

1. Plana (historica): `{"bpm", "bars", "style"}` -- N compassos iguais
   num unico estilo. Mantida bit a bit identica (ha teste de regressao
   por hash em `tests/test_track_sections.py`): a faixa do tema de
   titulo, a da Calibracao e a do tutorial (cujo beatmap e AUTORAL, com
   timestamps casados a ESTA faixa) dependem disso.

2. Seccionada: `{"bpm", "sections": [{"name", "bars", "style",
   "progression", "lead"}, ...]}` -- a faixa passa a ter ESTRUTURA
   (intro/verso/refrao/ponte/climax), cada secao com sua propria
   densidade de bateria, progressao harmonica e camada melodica. E o
   que permite a curva de dificuldade respirar: uma secao `calm` no
   meio de uma faixa `intense` e um alivio real, e o alivio e o que faz
   um climax existir.

Estilos (a densidade da bateria, por secao):
    calm     -- bumbo por batida, caixa em 2/4, sem chimbal, sem drops:
                onsets esparsos e limpos (fase introdutoria).
    standard -- bateria completa + drop a cada 8 compassos.
    intense  -- chimbal em colcheias acentuadas, bumbo dobrado no fim de
                cada 4 compassos e drop a cada 4: mapa denso.

Os drops/fills sao contados RELATIVAMENTE ao inicio da secao, nao ao
inicio da faixa: assim toda secao comeca no seu proprio downbeat de
drop (crash + bumbo pesado), telegrafando a virada pro jogador. Na
forma plana existe uma unica secao implicita comecando no compasso 0, e
o indice relativo coincide com o global -- dai a identidade bit a bit.

Roda 100% fora do loop de gameplay (carregamento/ferramentas offline).
"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

from utils.path_resolver import get_writable_data_path

DEMO_TRACK_BPM: float = 128.0
DEMO_TRACK_BARS: int = 24
DEMO_TRACK_SAMPLE_RATE: int = 44100

# -- Progressoes harmonicas: 4 raizes de baixo, uma por compasso, em La
#    menor. "base" e o loop HISTORICO (i-VI-III-VII) e permanece o
#    default -- trocar esse default mudaria toda faixa plana e
#    invalidaria os beatmaps versionados.
_PROGRESSIONS: Dict[str, Tuple[float, ...]] = {
    # A1 F1 C2 G1 -- i VI III VII: o loop original, neutro e estavel.
    "base": (55.00, 43.65, 65.41, 49.00),
    # F1 C2 G1 A1 -- VI III VII i: as raizes sobem e RESOLVEM na tonica,
    #                o gesto de refrao/climax.
    "lift": (43.65, 65.41, 49.00, 55.00),
    # A1 Bb1 F1 E1 -- o meio-tom A->Bb e a tensao; termina no V (E1) sem
    #                 resolver, deixando a secao "pendurada" (ponte).
    "dark": (55.00, 58.27, 43.65, 41.20),
}
_DEFAULT_PROGRESSION = "base"
_BASS_PROGRESSION_HZ = _PROGRESSIONS[_DEFAULT_PROGRESSION]  # compat historica

_STYLE_PARAMS: Dict[str, Dict] = {
    "calm": {"hats": False, "drop_every_bars": 0, "double_kick_fill": False, "hat_amp": 0.0},
    "standard": {"hats": True, "drop_every_bars": 8, "double_kick_fill": False, "hat_amp": 0.16},
    "intense": {"hats": True, "drop_every_bars": 4, "double_kick_fill": True, "hat_amp": 0.22},
}

# -- Camada melodica ("lead"): a linha que o Perfil de Extracao "hybrid"
#    do mapper separa do groove pra mandar pras colunas CENTRAIS (S/W) do
#    Arcade 4K -- antes dela nao havia nada melodico na faixa pra ele
#    separar (so bateria + baixo em colcheias).
#
#    Escala pentatonica menor por razoes justas sobre a raiz da secao
#    (tonica, terca menor, quarta, quinta, setima menor): deterministico,
#    sem tabela de temperamento igual.
_LEAD_SCALE_RATIOS: Tuple[float, ...] = (1.0, 1.2, 4.0 / 3.0, 1.5, 16.0 / 9.0)
# 3 oitavas acima do baixo. NAO e escolha estetica: e a separacao de
# BANDA que torna o lead seguro. Com raizes de baixo em 41-65 Hz, o lead
# cai em ~330-1250 Hz -- inteiramente ACIMA do corte de ~250 Hz do perfil
# "groove" (mel grave, bumbo+corpo de caixa) e DENTRO da banda 300-8000 Hz
# do "vocal_shred". Medido: a 4.0 (2 oitavas) boa parte da melodia caía
# ABAIXO de 300 Hz e o extrator vocal simplesmente nao a via.
_LEAD_OCTAVE_MULTIPLIER: float = 8.0
# `(offset_em_batidas, grau, duracao_em_batidas)`. Nenhum offset cai em
# batida inteira (0/1/2/3), onde vivem bumbo e caixa.
#
# A mistura de contratempos de COLCHEIA (0.5/1.5/3.5) com um par de
# SEMICOLCHEIAS (2.25/2.75) e deliberada, e a razao e a curadoria, nao a
# sintese: `beatmap_pipeline.merge_note_layers` exige que uma nota vocal
# esteja a `0.5 * min_gap_seconds` de qualquer kick. Com o `min_gap` de
# 0.45 s das fases curadas isso da 0.225 s -- uma semicolcheia a 128 BPM
# dista 0.117 s da batida e e SEMPRE descartada, enquanto uma colcheia
# dista 0.234 s e sobrevive por uma margem de 9 ms. Medido nesta faixa:
# so semicolcheias -> 3 notas vocais no chart; este motivo misto -> 8;
# so colcheias -> 14 (mas uma melodia inteira no contratempo e um pulso,
# nao uma frase). As semicolcheias seguem valendo a pena: os onsets
# EXISTEM no audio (71 dos 232 onsets vocais brutos caem nelas, contra 0
# antes desta camada), so esperam uma fase que baixe `min_gap_seconds`
# na curadoria -- nenhuma mudanca de sintese sera necessaria la.
_LEAD_MOTIF: Tuple[Tuple[float, int, float], ...] = (
    (0.5, 0, 0.45),
    (1.5, 2, 0.45),
    (2.25, 1, 0.30),
    (2.75, 3, 0.40),
    (3.5, 4, 0.65),
)
# Transposicao por compasso: o motivo repete, mas deslocado em graus da
# escala, formando uma frase de 4 compassos em vez de 1 compasso em loop.
_LEAD_PHRASE_DEGREES: Tuple[int, ...] = (0, 2, 1, 3)
_LEAD_AMPLITUDE: float = 0.18
# Ataque de pluck (4 ms), nao de sino. A intuicao inicial foi o oposto --
# ataque LENTO (40 ms) pra nunca criar transiente que o extrator de
# onsets confundisse com batida -- e ela estava errada por otimizar
# demais: com 40 ms a melodia ficava audivel pro jogador e INVISIVEL pro
# extrator (0 onsets nas posicoes exclusivas do lead). O que de fato
# protege o esqueleto ritmico e a banda (ver `_LEAD_OCTAVE_MULTIPLIER`),
# nao o envelope: com o lead acima de 250 Hz, o perfil "groove" nao muda
# NADA com o ataque seco -- verificado em todas as combinacoes varridas,
# kick=58 e BPM=129.20 constantes.
_LEAD_ATTACK_SECONDS: float = 0.004
_LEAD_DECAY: float = 3.2


def _scale_ratio(degree: int) -> float:
    """Razao de frequencia do `degree`-esimo grau da pentatonica menor,
    subindo de oitava quando o grau passa do fim da escala (graus
    negativos descem) -- assim a transposicao da frase nunca precisa de
    aritmetica modular, que dobraria a melodia sobre si mesma."""
    octave, index = divmod(degree, len(_LEAD_SCALE_RATIOS))
    return _LEAD_SCALE_RATIOS[index] * (2.0**octave)


def _resolve_sections(
    bars: Optional[int], style: str, sections: Optional[Sequence[Dict]]
) -> Tuple[Dict, ...]:
    """Normaliza as duas formas de especificacao numa unica lista de
    secoes resolvidas (`start_bar`/`bars`/`style`/`progression`/`lead`).

    Sem `sections`, devolve UMA secao implicita cobrindo os `bars`
    inteiros a partir do compasso 0 -- o que garante que todo indice
    relativo a secao coincida com o indice global e a saida permaneca
    bit a bit identica a historica."""
    if sections is None:
        if bars is None:
            raise ValueError("especificacao de faixa precisa de 'bars' ou 'sections'")
        return (
            {
                "name": "full",
                "start_bar": 0,
                "bars": int(bars),
                "style": style,
                "progression": _PROGRESSIONS[_DEFAULT_PROGRESSION],
                "lead": False,
            },
        )

    if not sections:
        raise ValueError("'sections' nao pode ser vazia")

    resolved = []
    start_bar = 0
    for index, raw in enumerate(sections):
        unknown = set(raw) - _SYNTH_SECTION_KEYS - CURATION_SECTION_KEYS
        if unknown:
            raise ValueError(
                f"chave(s) desconhecida(s) na secao {index}: {sorted(unknown)}; "
                f"validas: {sorted(_SYNTH_SECTION_KEYS | CURATION_SECTION_KEYS)}"
            )
        section_bars = int(raw.get("bars", 0))
        if section_bars <= 0:
            raise ValueError(f"secao {index} precisa de 'bars' > 0")
        section_style = raw.get("style", style)
        if section_style not in _STYLE_PARAMS:
            raise ValueError(
                f"estilo desconhecido {section_style!r} na secao {index}; "
                f"disponiveis: {sorted(_STYLE_PARAMS)}"
            )
        progression_name = raw.get("progression", _DEFAULT_PROGRESSION)
        if progression_name not in _PROGRESSIONS:
            raise ValueError(
                f"progressao desconhecida {progression_name!r} na secao {index}; "
                f"disponiveis: {sorted(_PROGRESSIONS)}"
            )
        resolved.append(
            {
                "name": str(raw.get("name", f"secao{index}")),
                "start_bar": start_bar,
                "bars": section_bars,
                "style": section_style,
                "progression": _PROGRESSIONS[progression_name],
                "lead": bool(raw.get("lead", False)),
            }
        )
        start_bar += section_bars
    return tuple(resolved)


_SYNTH_SECTION_KEYS = frozenset({"name", "bars", "style", "progression", "lead"})
"""Chaves que a SINTESE le numa secao."""

CURATION_SECTION_KEYS = frozenset({"min_gap_seconds", "target_density_per_second"})
"""Chaves que a secao carrega para a CURADORIA do beatmap (lidas por
`offline.beatmap_pipeline`, ignoradas pela sintese).

Moram na propria secao, e nao num bloco separado, porque densidade de
chart e densidade musical sao a mesma decisao: a ponte que respira quer
menos notas, o climax quer mais. Separa-las em dois lugares do JSON
convidaria a dessincronia. A sintese ignora estas chaves, mas
`_resolve_sections` as RECONHECE -- do contrario um typo
(`min_gap_second`) seria silenciosamente ignorado pelos dois lados.
"""


def section_time_windows(synth_spec: Dict) -> Tuple[Tuple[str, float, float, Dict], ...]:
    """Janela de tempo de cada secao: `(nome, inicio_seg, fim_seg, spec_cru)`.

    Pura aritmetica sobre `bpm` e os compassos acumulados -- a MESMA
    formula que `synthesize_track` usa pra posicionar os compassos, entao
    as fronteiras coincidem exatamente com o audio, sem precisar abrir o
    .wav. Faixa plana (sem `sections`) devolve tupla vazia: nao ha
    estrutura pra fatiar.
    """
    sections = synth_spec.get("sections")
    if not sections:
        return ()
    bar_seconds = 4 * (60.0 / float(synth_spec["bpm"]))
    windows = []
    start_bar = 0
    for raw in sections:
        bars = int(raw.get("bars", 0))
        windows.append(
            (
                str(raw.get("name", "")),
                start_bar * bar_seconds,
                (start_bar + bars) * bar_seconds,
                raw,
            )
        )
        start_bar += bars
    return tuple(windows)


def total_bars(synth_spec: Dict) -> int:
    """Total de compassos de uma especificacao, nas DUAS formas -- fonte
    unica de verdade pra duracao da faixa (`bars*4*60/bpm`).

    `stages.read_stage_bpm_and_duration` usa esta funcao em vez de ler
    `spec["bars"]` direto: numa faixa seccionada nao existe campo `bars`
    no topo, e duplicar a soma das secoes la deixaria a duracao mostrada
    no Carrossel silenciosamente errada."""
    sections = synth_spec.get("sections")
    if sections:
        return sum(int(section.get("bars", 0)) for section in sections)
    return int(synth_spec.get("bars", 0))


STEM_INSTRUMENTAL = "instrumental"
STEM_LEAD = "lead"
STEMS = (STEM_INSTRUMENTAL, STEM_LEAD)
"""Stems separaveis de uma faixa sintetizada.

Destravam o Crossfading Vocal, que estava documentado como impossivel
("`pygame.mixer.music` e streaming de canal unico, sem EQ/filtro -- a
implementacao de verdade exige uma 2a camada de audio, que ainda nao
existe"). A conclusao estava certa e a premissa errada: nao existe stem
numa GRAVACAO, mas estas faixas sao SINTETIZADAS -- renderizar so a
bateria+baixo, ou so a melodia, e' pular camadas no mesmo laco.

O desenho que nao toca no relogio de audio: o INSTRUMENTAL toca em
`pygame.mixer.music` e segue sendo a unica fonte de tempo do jogo (nada
no gameplay muda), e o LEAD toca num canal `Sound` a parte, cujo volume
abaixa quando o jogador erra. Abafar a voz vira baixar um volume, nao
filtrar um arquivo.
"""


def _render_unnormalized(
    bpm: float,
    resolved_sections: Tuple[Dict, ...],
    sample_rate: int,
    include_backing: bool,
    include_lead: bool,
) -> np.ndarray:
    """Renderiza a mixagem SEM normalizar, com as camadas pedidas.

    Separado de `synthesize_track` por causa dos stems: a normalizacao
    tem de ser a MESMA nos dois stems e na mixagem completa, senao eles
    nao se equilibram ao tocar juntos (cada um normalizado pelo proprio
    pico sairia com o lead alto demais, e a soma estouraria). Por isso
    quem normaliza e' o chamador, sempre pelo pico da mixagem COMPLETA.
    """
    beat_seconds = 60.0 / bpm
    bar_count = sum(section["bars"] for section in resolved_sections)
    total_seconds = bar_count * 4 * beat_seconds
    n_samples = int(total_seconds * sample_rate)
    mix = np.zeros(n_samples, dtype=np.float64)

    def add_at(start_seconds: float, signal: np.ndarray) -> None:
        start = int(start_seconds * sample_rate)
        end = min(start + signal.shape[0], n_samples)
        if start < n_samples:
            mix[start:end] += signal[: end - start]

    def kick(amplitude: float = 0.9) -> np.ndarray:
        length = int(0.14 * sample_rate)
        tt = np.arange(length) / sample_rate
        freq = 150.0 * np.exp(-tt * 18.0) + 45.0
        return amplitude * np.exp(-tt * 22.0) * np.sin(2.0 * np.pi * np.cumsum(freq) / sample_rate)

    def snare(amplitude: float = 0.55) -> np.ndarray:
        length = int(0.09 * sample_rate)
        tt = np.arange(length) / sample_rate
        # ruido deterministico: seno de alta frequencia com fase caotica fixa
        noise = np.sin(2.0 * np.pi * 3987.0 * tt + np.sin(2.0 * np.pi * 977.0 * tt) * 8.0)
        tone = 0.4 * np.sin(2.0 * np.pi * 190.0 * tt)
        return amplitude * np.exp(-tt * 40.0) * (noise * 0.7 + tone)

    def hat(amplitude: float) -> np.ndarray:
        length = int(0.03 * sample_rate)
        tt = np.arange(length) / sample_rate
        noise = np.sin(2.0 * np.pi * 9123.0 * tt + np.sin(2.0 * np.pi * 3313.0 * tt) * 11.0)
        return amplitude * np.exp(-tt * 90.0) * noise

    def crash(amplitude: float = 0.5) -> np.ndarray:
        length = int(0.6 * sample_rate)
        tt = np.arange(length) / sample_rate
        noise = np.sin(2.0 * np.pi * 6733.0 * tt + np.sin(2.0 * np.pi * 2141.0 * tt) * 13.0)
        return amplitude * np.exp(-tt * 6.0) * noise

    def lead(freq: float, duration_seconds: float) -> np.ndarray:
        length = int(duration_seconds * sample_rate)
        tt = np.arange(length) / sample_rate
        envelope = np.minimum(tt / _LEAD_ATTACK_SECONDS, 1.0) * np.exp(-tt * _LEAD_DECAY)
        timbre = np.sin(2.0 * np.pi * freq * tt) + 0.35 * np.sin(2.0 * np.pi * 2.0 * freq * tt)
        return _LEAD_AMPLITUDE * envelope * timbre

    kick_sig = kick()
    kick_heavy_sig = kick(1.0)
    snare_sig = snare()
    crash_sig = crash()

    for section in resolved_sections:
        params = _STYLE_PARAMS[section["style"]]
        progression = section["progression"]
        hat_sig = hat(params["hat_amp"]) if params["hats"] else None
        drop_every = params["drop_every_bars"]

        for bar_in_section in range(section["bars"]):
            bar_start = (section["start_bar"] + bar_in_section) * 4 * beat_seconds
            bass_freq = progression[bar_in_section % len(progression)]
            is_drop_bar = drop_every > 0 and bar_in_section % drop_every == 0
            is_fill_bar = params["double_kick_fill"] and bar_in_section % 4 == 3

            if include_backing:
                for beat in range(4):
                    beat_start = bar_start + beat * beat_seconds
                    if is_drop_bar and beat == 0:
                        add_at(beat_start, kick_heavy_sig)
                        add_at(beat_start, crash_sig)
                        add_at(beat_start + beat_seconds * 0.5, kick_sig)
                    else:
                        add_at(beat_start, kick_sig)
                        if is_fill_bar:
                            add_at(beat_start + beat_seconds * 0.5, kick_sig)
                    if beat in (1, 3):
                        add_at(beat_start, snare_sig)
                    if hat_sig is not None:
                        add_at(beat_start + beat_seconds * 0.5, hat_sig)

                # baixo continuo em colcheias, envelope curto por nota
                for eighth in range(8):
                    note_start = bar_start + eighth * beat_seconds * 0.5
                    length = int(beat_seconds * 0.45 * sample_rate)
                    tt = np.arange(length) / sample_rate
                    envelope = np.minimum(tt * 60.0, 1.0) * np.exp(-tt * 7.0)
                    add_at(note_start, 0.22 * envelope * np.sin(2.0 * np.pi * bass_freq * tt))

            if include_lead and section["lead"]:
                phrase_degree = _LEAD_PHRASE_DEGREES[bar_in_section % len(_LEAD_PHRASE_DEGREES)]
                lead_root = bass_freq * _LEAD_OCTAVE_MULTIPLIER
                for offset_beats, degree, duration_beats in _LEAD_MOTIF:
                    note_freq = lead_root * _scale_ratio(degree + phrase_degree)
                    add_at(
                        bar_start + offset_beats * beat_seconds,
                        lead(note_freq, duration_beats * beat_seconds),
                    )

    return mix


def _normalization_divisor(full_mix: np.ndarray) -> float:
    """O divisor historico (`pico * 1.1`), ou 1.0 num silencio absoluto."""
    peak = float(np.max(np.abs(full_mix)))
    return peak * 1.1 if peak > 0.0 else 1.0


def synthesize_track(
    bpm: float,
    bars: Optional[int] = None,
    style: str = "standard",
    sample_rate: int = DEMO_TRACK_SAMPLE_RATE,
    sections: Optional[Sequence[Dict]] = None,
    stem: Optional[str] = None,
) -> np.ndarray:
    """Sintetiza uma faixa (mono, float64 em [-1, 1]) com bateria marcada
    para que o extrator de onsets da engine encontre batidas fortes e
    limpas. Drops (acentos de crash + bumbo pesado) rendem onsets de
    strength alta, que o pipeline converte em ameacas pesadas.

    Com `sections`, cada secao traz sua propria densidade de bateria,
    progressao harmonica e camada melodica; sem elas, o comportamento
    historico de N compassos iguais (bit a bit identico).

    Com `stem` (`"instrumental"` ou `"lead"`), devolve so aquela camada --
    mas normalizada pelo pico da mixagem COMPLETA, nao pelo proprio. E o
    que garante a propriedade que o Crossfading Vocal depende:
    `instrumental + lead == mixagem completa`, amostra por amostra. Ver
    `STEMS`.
    """
    resolved_sections = _resolve_sections(bars, style, sections)
    if stem is not None and stem not in STEMS:
        raise ValueError(f"stem desconhecido {stem!r} (validos: {STEMS})")

    full_mix = _render_unnormalized(bpm, resolved_sections, sample_rate, True, True)
    divisor = _normalization_divisor(full_mix)

    if stem is None:
        return full_mix / divisor
    wanted = _render_unnormalized(
        bpm,
        resolved_sections,
        sample_rate,
        include_backing=(stem == STEM_INSTRUMENTAL),
        include_lead=(stem == STEM_LEAD),
    )
    return wanted / divisor


def stem_track_path(track_path: str, stem: str) -> str:
    """`data/tracks/x.wav` + "lead" -> `data/tracks/x@lead.wav`.

    Mesma convencao `@` das variantes de Escala de Tempo
    (`rate_scaling.rate_variant_track_path`), pelo mesmo motivo: arquivo
    proprio, a faixa completa nunca e sobrescrita, e as tres convivem.
    """
    if stem not in STEMS:
        raise ValueError(f"stem desconhecido {stem!r} (validos: {STEMS})")
    path = Path(track_path)
    return str(path.with_name(f"{path.stem}@{stem}{path.suffix}"))


def ensure_stem_tracks(track_path: str, synth_spec: Optional[Dict]) -> Optional[Dict[str, str]]:
    """Garante os 2 stems em disco e devolve `{stem: caminho_resolvido}`.

    `None` quando nao ha `synth_spec` (musica do jogador: nao ha o que
    re-renderizar -- separar stems de um mp3 seria separacao de fontes,
    outra feature inteira) ou quando a faixa nao tem nenhuma secao com
    `lead` (sem melodia, um stem vocal vazio nao serviria pra nada).
    """
    if synth_spec is None:
        return None
    sections = synth_spec.get("sections") or ()
    if not any(section.get("lead") for section in sections):
        return None

    paths = {}
    for stem in STEMS:
        destination = Path(get_writable_data_path(stem_track_path(track_path, stem)))
        if not destination.exists():
            samples = synthesize_track(
                bpm=float(synth_spec["bpm"]),
                bars=int(synth_spec["bars"]) if "bars" in synth_spec else None,
                style=synth_spec.get("style", "standard"),
                sections=synth_spec.get("sections"),
                stem=stem,
            )
            write_wav(samples, destination)
        paths[stem] = str(destination)
    return paths



def percussive_onset_times(synth_spec: Dict) -> np.ndarray:
    """Onde a bateria REALMENTE esta na faixa, em segundos (bumbos + caixas).

    Verdade fundamental, nao estimativa: e a MESMA aritmetica que
    `_render_unnormalized` usa pra posicionar cada golpe, entao coincide
    com o audio por construcao -- sem abrir o .wav, sem DSP, sem erro.

    Existe porque a IA offline erra por um vies MEDIVEL. O extrator de
    onsets da engine deriva o instante do pico do envelope de fluxo
    espectral, que acontece um ou dois frames DEPOIS do transiente real
    (a 44.1 kHz com hop 512, um frame sao 11.6 ms). Medido contra esta
    funcao nas 4 faixas seccionadas: 98% das ameacas caiam ATRASADAS,
    media +18.4 ms, desvio 9.0 ms -- num jogo cuja janela PERFECT e 50 ms,
    isso consome 40% da janela antes de o jogador tocar em nada.

    Com a verdade fundamental em maos o conserto deixa de ser um numero
    chutado: `tools/generate_stage_assets.py` mede o desvio real de cada
    faixa curada e o desconta. Faixa plana (sem `sections`) tambem
    funciona -- ha uma secao implicita.
    """
    resolved = _resolve_sections(
        synth_spec.get("bars"), synth_spec.get("style", "standard"), synth_spec.get("sections")
    )
    beat_seconds = 60.0 / float(synth_spec["bpm"])
    times = set()
    for section in resolved:
        params = _STYLE_PARAMS[section["style"]]
        drop_every = params["drop_every_bars"]
        for bar_in_section in range(section["bars"]):
            bar_start = (section["start_bar"] + bar_in_section) * 4 * beat_seconds
            is_drop_bar = drop_every > 0 and bar_in_section % drop_every == 0
            is_fill_bar = params["double_kick_fill"] and bar_in_section % 4 == 3
            for beat in range(4):
                beat_start = bar_start + beat * beat_seconds
                times.add(beat_start)  # bumbo em toda batida (caixa em 2 e 4 coincide)
                if (is_drop_bar and beat == 0) or is_fill_bar:
                    times.add(beat_start + beat_seconds * 0.5)
    return np.array(sorted(times), dtype=np.float64)


def measure_onset_lag_seconds(
    note_times: np.ndarray, synth_spec: Dict, match_window_seconds: float = 0.06
) -> float:
    """Vies MEDIANO (assinado) entre as notas extraidas e a bateria real.

    Positivo = a IA colocou as notas DEPOIS da batida. Mediana, nao media:
    uma nota que casou com a batida errada (ou um onset espurio) desloca a
    media e nao mexe na mediana.

    Notas a mais de `match_window_seconds` de qualquer batida sao
    IGNORADAS em vez de casadas a forca -- sao notas que a IA achou onde
    nao ha bateria (cauda de crash, comeco de baixo), e arrasta-las pro
    calculo mediria outra coisa. `0.0` quando nada casa.
    """
    truth = percussive_onset_times(synth_spec)
    if truth.shape[0] == 0 or note_times.shape[0] == 0:
        return 0.0
    index = np.searchsorted(truth, note_times).clip(1, truth.shape[0] - 1)
    before, after = truth[index - 1], truth[index]
    nearest = np.where(
        np.abs(note_times - before) < np.abs(note_times - after), before, after
    )
    delta = note_times - nearest
    matched = delta[np.abs(delta) <= match_window_seconds]
    return float(np.median(matched)) if matched.shape[0] else 0.0


def wav_fingerprint(track_path: str) -> str:
    """Impressao digital do AUDIO de uma faixa (sha256 dos bytes do .wav,
    truncado em 16 hex).

    Gravada no `beatmap.json` por `tools/generate_stage_assets.py` e
    conferida por teste. O problema que isto resolve: os `.wav` nao sao
    versionados e os `beatmap.json` sao, entao mudar a sintese sem
    regenerar os beatmaps deixa o jogo fora do tempo da musica -- e
    NENHUM teste de logica falha, porque nada esta invalido, so
    dessincronizado. Foi exatamente a armadilha ao dar estrutura as
    faixas: as ameacas eram extraidas de um audio que deixou de existir.

    Escolhi o hash do AUDIO em vez do hash da especificacao de proposito:
    o audio muda tanto quando a spec muda (`stages.json`) quanto quando a
    MATEMATICA da sintese muda (um motivo de lead novo, outro envelope) --
    o segundo caso e' invisivel pra qualquer hash de spec e nao exige
    lembrar de incrementar nenhum contador de versao a mao.
    """
    import hashlib

    path = Path(get_writable_data_path(track_path))
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def write_wav(samples: np.ndarray, destination: Path, sample_rate: int = DEMO_TRACK_SAMPLE_RATE) -> None:
    """Grava `samples` (float em [-1, 1]) como WAV mono 16-bit."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pcm = (samples * np.iinfo(np.int16).max).astype(np.int16)
    with wave.open(str(destination), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())


def ensure_track(track_path: str, synth_spec: Optional[Dict]) -> str:
    """Garante que a faixa exista em `track_path`, re-sintetizando-a
    deterministicamente a partir de `synth_spec` se necessario. Sem
    `synth_spec` (faixa do usuario), o arquivo precisa existir.

    `track_path` resolvido via `get_writable_data_path` (pasta do
    proprio `.exe` num build congelado, nunca `sys._MEIPASS` -- tanto a
    sintese determinista quanto `musicas/*` do jogador precisam
    sobreviver entre execucoes) -- a string devolvida ja e' a resolvida,
    entao quem chama (`HBPygameAudioEngine.load_track` via override, ou
    os 2 usos diretos de `title_track_path`/`calibration_track_path`)
    nunca resolve de novo por cima (`get_writable_data_path` e'
    idempotente sobre um caminho ja absoluto)."""
    path = Path(get_writable_data_path(track_path))
    if not path.exists():
        if synth_spec is None:
            raise FileNotFoundError(f"faixa de audio nao encontrada: {path}")
        samples = synthesize_track(
            bpm=float(synth_spec["bpm"]),
            bars=int(synth_spec["bars"]) if "bars" in synth_spec else None,
            style=synth_spec.get("style", "standard"),
            sections=synth_spec.get("sections"),
        )
        write_wav(samples, path)
    return str(path)


def synthesize_demo_track(
    bpm: float = DEMO_TRACK_BPM,
    bars: int = DEMO_TRACK_BARS,
    sample_rate: int = DEMO_TRACK_SAMPLE_RATE,
) -> np.ndarray:
    """Compat: a faixa demo original e o estilo `standard` em 128 BPM."""
    return synthesize_track(bpm=bpm, bars=bars, style="standard", sample_rate=sample_rate)


def ensure_demo_track(track_path: str) -> str:
    """Compat: garante a faixa demo (estilo `standard`, 128 BPM, 24 compassos)."""
    return ensure_track(track_path, {"bpm": DEMO_TRACK_BPM, "bars": DEMO_TRACK_BARS, "style": "standard"})


def synthesize_metronome_track(
    bpm: float, bars: int, sample_rate: int = DEMO_TRACK_SAMPLE_RATE
) -> np.ndarray:
    """Meta-Jogo -- tela de Calibracao: faixa de metronomo PURO (so um
    clique seco e limpo em CADA batida, nada mais) -- ao contrario das
    faixas de fase (bateria completa), aqui a clareza do instante exato
    da batida importa mais que qualquer groove, pro jogador acertar a
    tecla no tempo com precisao."""
    beat_seconds = 60.0 / bpm
    total_seconds = bars * 4 * beat_seconds
    n_samples = int(total_seconds * sample_rate)
    mix = np.zeros(n_samples, dtype=np.float64)

    length = int(0.05 * sample_rate)
    tt = np.arange(length) / sample_rate
    click = np.exp(-tt * 90.0) * np.sin(2.0 * np.pi * 1800.0 * tt)

    beat_count = bars * 4
    for beat in range(beat_count):
        start = int(beat * beat_seconds * sample_rate)
        end = min(start + length, n_samples)
        if start < n_samples:
            mix[start:end] += click[: end - start]

    peak = np.max(np.abs(mix))
    if peak > 0.0:
        mix /= peak * 1.05
    return mix


def ensure_metronome_track(track_path: str, bpm: float, bars: int = 64) -> str:
    """Garante a faixa de metronomo da Calibracao, re-sintetizada
    deterministicamente se ausente (mesmo criterio de `ensure_track`,
    inclusive a resolucao via `get_writable_data_path`)."""
    path = Path(get_writable_data_path(track_path))
    if not path.exists():
        write_wav(synthesize_metronome_track(bpm=bpm, bars=bars), path, sample_rate=DEMO_TRACK_SAMPLE_RATE)
    return str(path)
