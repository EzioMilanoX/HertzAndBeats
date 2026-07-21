"""
Identificadores logicos de textura compartilhados entre os sistemas de
gameplay (que so escrevem inteiros em `sprite.texture_id`) e o adapter
de renderizacao (que resolve cada inteiro para uma Surface pre-
renderizada ou uma forma procedural). Modulo PURO: nao importa pygame,
para que sistemas e testes headless o usem sem backend grafico.
"""
from __future__ import annotations

TEX_PLAYER_CORE: int = 1
"""Nucleo do jogador no centro da arena."""

TEX_CROSSHAIR: int = 2
"""Indicador da mira 360 orbitando o nucleo."""

TEX_LANE_RECEPTOR: int = 3
"""Receptor (anel) de uma coluna na linha de julgamento do modo Arcade 4K."""

TEX_CONVERGENCE_RING: int = 4
"""Anel de convergencia do Defensor (contorno procedural; raio = 8*escala),
encolhendo ate o anel de julgamento no instante do hit."""

TEX_KEY_LABEL_BASE: int = 140
"""Rotulo da tecla da coluna `k` do Arcade 4K = `TEX_KEY_LABEL_BASE + k`."""

TEX_THREAT_BASIC: int = 10
"""Ameaca comum (batida/beat)."""

TEX_THREAT_HEAVY: int = 11
"""Ameaca pesada (pico de energia/onset forte)."""

TEX_THREAT_POLARITY_BLUE: int = 12
"""Ameaca comum da fase Polaridade, timbre AGUDO: circulo azul com um
TRIANGULO interno -- acessibilidade para daltonismo (Azul/Rosa nao pode
depender so da cor), destruida pelo gatilho azul (`fire`)."""

TEX_THREAT_POLARITY_PINK: int = 13
"""Ameaca comum da fase Polaridade, timbre GRAVE: circulo rosa com um
QUADRADO interno -- mesma logica de acessibilidade, destruida pelo
gatilho rosa (`fire_alt`)."""

TEX_PLAYER_CORE_BLUE: int = 14
"""Nucleo do jogador na fase Polaridade, logo apos disparar o gatilho
AZUL -- mesmo triangulo interno das ameacas azuis, reforcando "voce
esta na cor azul agora"."""

TEX_PLAYER_CORE_PINK: int = 15
"""Nucleo do jogador na fase Polaridade, logo apos disparar o gatilho
ROSA -- mesmo quadrado interno das ameacas rosas."""

TEX_DIGIT_BASE: int = 100
"""Digito `d` do HUD = `TEX_DIGIT_BASE + d` (0..9), pre-renderizado no
carregamento -- nunca `font.render` dentro do loop."""

TEX_WORD_PERFECT: int = 110
TEX_WORD_GOOD: int = 111
TEX_WORD_MISS: int = 112
TEX_LABEL_SCORE: int = 113
TEX_LABEL_COMBO: int = 114
TEX_HEALTH_PIP: int = 115
TEX_WORD_DODGE: int = 116
"""Auditoria de Game Design (Tolerancia Organica): antes desta palavra
existir, um Dash que atravessava uma ameaca durante os i-frames
(`JUDGMENT_DODGED`) nao dava NENHUM feedback -- indistinguivel de um
glitch. Reusa o mesmo padrao das outras palavras de julgamento."""

JUDGMENT_WORD_TEXTURES: tuple = (0, TEX_WORD_PERFECT, TEX_WORD_GOOD, TEX_WORD_MISS, TEX_WORD_DODGE, 0)
"""Mapeia `JUDGMENT_*` (indice) -> textura da palavra correspondente.
Indice PENDING nao tem palavra (0 = sem textura); SURVIVED (Arcade 4K --
Bombas) tambem fica em 0 DE PROPOSITO -- e o "jogo correto" silencioso
por design (ver `JUDGMENT_SURVIVED`), nao um esquecimento. Tupla criada
uma unica vez no carregamento do modulo, indexada por inteiro no loop."""

TEX_DISTRACTION_SPLAT: int = 16
"""Obstrucao visual (jumpscare) do Arcade 4K: mancha de tinta
procedural, desenhada sobre TUDO (layer_z acima do HUD) por um instante
curto, num ponto aleatorio-mas-deterministico da tela."""

TEX_ORBITAL_ECLIPSE: int = 17
"""Eclipse Orbital (Defensor -- Barreira Dinamica): sem forma especial
registrada, cai no fallback procedural de `HBPygameRenderer.draw_batch`
(escala anisotropica = barra) -- so precisa de um id proprio para nao
colidir com nenhuma outra textura/forma."""

TEX_TUTORIAL_BASE: int = 200
"""Textos de instrucao do tutorial, pre-renderizados na composicao:
o passo `j` da fase de indice `i` usa
`TEX_TUTORIAL_BASE + i * MAX_TUTORIAL_STEPS + j`."""

MAX_TUTORIAL_STEPS: int = 32
"""Passos maximos de tutorial por fase (dimensiona a faixa de ids)."""
