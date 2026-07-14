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

TEX_THREAT_BASIC: int = 10
"""Ameaca comum (batida/beat)."""

TEX_THREAT_HEAVY: int = 11
"""Ameaca pesada (pico de energia/onset forte)."""

TEX_DIGIT_BASE: int = 100
"""Digito `d` do HUD = `TEX_DIGIT_BASE + d` (0..9), pre-renderizado no
carregamento -- nunca `font.render` dentro do loop."""

TEX_WORD_PERFECT: int = 110
TEX_WORD_GOOD: int = 111
TEX_WORD_MISS: int = 112
TEX_LABEL_SCORE: int = 113
TEX_LABEL_COMBO: int = 114
TEX_HEALTH_PIP: int = 115

JUDGMENT_WORD_TEXTURES: tuple = (0, TEX_WORD_PERFECT, TEX_WORD_GOOD, TEX_WORD_MISS, 0)
"""Mapeia `JUDGMENT_*` (indice) -> textura da palavra correspondente.
Indices PENDING/DODGED nao tem palavra (0 = sem textura). Tupla criada
uma unica vez no carregamento do modulo, indexada por inteiro no loop."""
