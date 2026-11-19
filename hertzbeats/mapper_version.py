"""Versao do MAPEADOR de beatmaps (modulo minusculo e livre de librosa).

Incrementada a cada mudanca na forma de gerar notas a partir do audio;
`music_library.needs_analysis` re-analisa automaticamente musicas cujo
beatmap cacheado veio de um mapeador mais antigo.
"""

MAPPER_VERSION: int = 9
"""v9: TRANSCRICAO FIEL. O beatmap em disco deixa de ser o chart jogavel e
passa a ser a melhor representacao da musica que a IA consegue: grade
uniforme derivada do BPM (nao dos pulsos esparsos do PLP), subdivisao em
fusas, e sem o piso de jogabilidade -- que agora e aplicado na COMPOSICAO,
ciente do modo (`playability_reduction`). Medido num piano solo: cobertura
dos ataques reais de 56% para 100%, com 0% de notas fantasma.

v8: piso jogavel garantido tambem na FUSAO de camadas. A fusao aceitava
uma nota vocal a metade do gap minimo de um kick, produzindo gaps de 255 ms
com piso de 300 ms -- notas dentro da janela de julgamento uma da outra.

v7: tolerancia de snap 0.08 -> 0.04 s (abaixo da janela PERFECT de
50 ms). Com 0.08 a nota era gravada no ponto da GRADE ate 80 ms longe do
ataque que a justificou -- notas que o jogador ve e nao ouve. Medido:
4.8% -> 0.0% de notas a mais de 50 ms de qualquer ataque real. Espacamento
minimo tambem passou de 0.90 para 0.75 batidas (mais cobertura, zero
fantasma).

v6: espacamento minimo em BATIDAS em vez de segundos. O default de
0.45 s valia 1.14 batidas a 152 BPM -- impossivel marcar batidas
consecutivas, entao o chart pulava batida irregularmente e a musica nao
tinha pulso (cada nota certa, o conjunto sem ritmo). Medido num piano solo:
regularidade dos intervalos subiu de 30% para 63%.

v5: correcao do vies do extrator de onsets. Medido contra a verdade
fundamental das faixas sintetizadas: 98% das notas saiam ATRASADAS, media
+18.4 ms -- 40% da janela PERFECT de 50 ms gasta antes de o jogador tocar
em nada. `DEFAULT_ONSET_LAG_SECONDS` desconta isso. Cache de musica do
jogador reanalisa sozinho por causa deste bump.

v4: Perfis de Extracao multi-camada (engine): musicas do jogador usam
"hybrid" -- esqueleto kick quantizado (groove) + melodia vocal sincopada
(vocal_shred) fundidos com prioridade do kick, cada nota taggeada com
`layer` para roteamento espacial (Arcade: kicks nas bordas, vocais no
centro).

v3: estagio DSP anti-mascaramento (HPSS percussivo + mel grave + PLP +
threshold inteligente). v2: quantizacao na grade + lane por timbre."""
