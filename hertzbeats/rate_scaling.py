"""Escala de tempo (tocar a fase mais devagar) -- acessibilidade.

Desacelerar a musica e' a alavanca de acessibilidade mais usada do genero
ritmico, e aqui ela sai quase de graca por uma razao especifica: as faixas
curadas nao sao gravacoes, sao SINTETIZADAS deterministicamente. Pedir a
mesma especificacao com `bpm * rate` produz uma faixa limpa, sem nenhum
artefato de resampling -- nada de vocoder de fase, nada de metal na
bateria. Uma faixa gravada exigiria time-stretch de verdade; esta so
exige aritmetica.

O que muda, e o que nao muda:

- A FAIXA e re-sintetizada num arquivo proprio (`...@0.75.wav`), entao a
  original nunca e sobrescrita e as duas convivem em disco.
- Os INSTANTES do beatmap sao divididos pela taxa (0.75x => tudo 1.33x
  mais tarde), na MESMA costura onde o Modo Treino ja mexia no schedule:
  interpretacao game-side sobre dados que a IA ja produziu, o
  `beatmap.json` versionado nunca muda.
- `approach_seconds` NAO escala. E' tempo de voo real da ameaca, medido em
  segundos de relogio, nao em batidas -- e a janela de julgamento
  tambem nao, pelo mesmo motivo. Na pratica isso e' o efeito desejado:
  a 0.75x o jogador ganha as mesmas janelas com mais espaco entre notas.
- O BPM mostrado no HUD escala, senao o metronomo/heartbeat visual
  contradiria o que se ouve.

Musica do jogador (`synth=None`) nao pode ser escalada: nao ha
especificacao pra re-sintetizar, e resamplear um mp3 aqui seria outra
feature. Nesse caso a taxa e' ignorada (degradacao graciosa, como o resto
do jogo faz com features opcionais).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

MIN_PLAYBACK_RATE = 0.5
MAX_PLAYBACK_RATE = 1.0
"""Limites da taxa. O teto e' 1.0 de proposito: acelerar a faixa nao e'
acessibilidade, e mudaria o balanceamento de toda fase curada (as janelas
de julgamento nao escalam -- ver o docstring do modulo). Um modo
"hiper" acelerado seria uma decisao de design separada."""


def is_scaled(rate: float) -> bool:
    """True quando a taxa muda algo de fato. Comparacao com tolerancia
    porque a taxa vem de JSON/CLI e `0.9999999` nao deve gerar uma faixa
    inteira nova em disco."""
    return abs(float(rate) - 1.0) > 1e-6


def clamp_rate(rate: float) -> float:
    return max(MIN_PLAYBACK_RATE, min(MAX_PLAYBACK_RATE, float(rate)))


def scaled_synth_spec(synth_spec: Optional[Dict], rate: float) -> Optional[Dict]:
    """A MESMA especificacao com o BPM escalado -- as secoes (compassos,
    estilo, progressao, lead) ficam intactas, entao a estrutura musical
    sobrevive: a ponte segue sendo 4 compassos de respiro, so mais longos.
    """
    if synth_spec is None or not is_scaled(rate):
        return synth_spec
    scaled = dict(synth_spec)
    scaled["bpm"] = float(synth_spec["bpm"]) * float(rate)
    return scaled


def rate_variant_track_path(track_path: str, rate: float) -> str:
    """`data/tracks/x.wav` + 0.75 -> `data/tracks/x@0.75.wav`.

    Arquivo separado (nunca sobrescrever a faixa a 1.0x): as duas taxas
    coexistem, e alternar a taxa no menu nao paga re-sintese de novo a
    cada troca -- a segunda vez o arquivo ja esta em disco.
    """
    if not is_scaled(rate):
        return track_path
    path = Path(track_path)
    return str(path.with_name(f"{path.stem}@{float(rate):.2f}{path.suffix}"))


def scale_schedule_for_rate(
    scheduled: np.ndarray, hit_times: np.ndarray, rate: float
) -> Tuple[np.ndarray, np.ndarray]:
    """Estica os instantes do beatmap para a faixa desacelerada.

    Dividir por `rate` (nao multiplicar): a 0.75x a musica dura 1/0.75 =
    1.33x mais, entao cada batida chega 1.33x mais tarde. Devolve copias,
    no mesmo contrato de `practice_thinning.thin_schedule_for_practice`
    (arrays paralelos linha a linha, chamado UMA vez na composicao).
    """
    if not is_scaled(rate):
        return scheduled.copy(), hit_times.copy()
    factor = 1.0 / float(rate)
    scaled = scheduled.copy()
    scaled["timestamp_seconds"] = scaled["timestamp_seconds"] * factor
    return scaled, hit_times * factor
