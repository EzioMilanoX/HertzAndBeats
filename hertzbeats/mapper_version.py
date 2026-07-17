"""Versao do MAPEADOR de beatmaps (modulo minusculo e livre de librosa).

Incrementada a cada mudanca na forma de gerar notas a partir do audio;
`music_library.needs_analysis` re-analisa automaticamente musicas cujo
beatmap cacheado veio de um mapeador mais antigo.
"""

MAPPER_VERSION: int = 4
"""v4: Perfis de Extracao multi-camada (engine): musicas do jogador usam
"hybrid" -- esqueleto kick quantizado (groove) + melodia vocal sincopada
(vocal_shred) fundidos com prioridade do kick, cada nota taggeada com
`layer` para roteamento espacial (Arcade: kicks nas bordas, vocais no
centro).

v3: estagio DSP anti-mascaramento (HPSS percussivo + mel grave + PLP +
threshold inteligente). v2: quantizacao na grade + lane por timbre."""
