"""Versao do MAPEADOR de beatmaps (modulo minusculo e livre de librosa).

Incrementada a cada mudanca na forma de gerar notas a partir do audio;
`music_library.needs_analysis` re-analisa automaticamente musicas cujo
beatmap cacheado veio de um mapeador mais antigo.
"""

MAPPER_VERSION: int = 3
"""v3: estagio DSP anti-mascaramento -- HPSS (so componente percussiva),
envelope de onset em mel grave/medio (fmax ~250 Hz: bumbo/caixa, sem
chimbal), grade pelos pulsos do PLP (robusto a acelerandos/sincopa) e
threshold inteligente (intervalo + amplitude) nos picos.

v2: notas QUANTIZADAS na grade de batidas (colcheias), lane por timbre
(centroide espectral) -- em vez de onsets crus e lane em carrossel."""
