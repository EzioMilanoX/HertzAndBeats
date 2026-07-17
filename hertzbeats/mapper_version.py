"""Versao do MAPEADOR de beatmaps (modulo minusculo e livre de librosa).

Incrementada a cada mudanca na forma de gerar notas a partir do audio;
`music_library.needs_analysis` re-analisa automaticamente musicas cujo
beatmap cacheado veio de um mapeador mais antigo.
"""

MAPPER_VERSION: int = 2
"""v2: notas QUANTIZADAS na grade de batidas do beat-tracker (colcheias),
com lane escolhida pelo timbre (centroide espectral) -- em vez de onsets
crus (backtrackeados = adiantados) e lane em carrossel."""
