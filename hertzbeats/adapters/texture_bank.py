"""
Pre-renderizacao das texturas de HUD na tela de carregamento: os
digitos 0-9 e as palavras PERFECT/GOOD/MISS viram Surfaces ESTATICAS
registradas no renderer UMA unica vez. Nenhum `font.render` acontece
depois disso -- o `UIRenderSystem` so escolhe `texture_id` por
aritmetica e o `draw_batch` blita as Surfaces ja prontas.
"""
from __future__ import annotations

import random

import pygame

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.components.texture_ids import (
    BUMP_FADE_STEPS,
    MAX_TUTORIAL_STEPS,
    TEX_CROSSHAIR,
    TEX_DIGIT_BASE,
    TEX_DIGIT_BUMP_BASE,
    TEX_DISTRACTION_SPLAT,
    TEX_HEALTH_PIP,
    TEX_KEY_LABEL_BASE,
    TEX_LABEL_COMBO,
    TEX_LABEL_SCORE,
    TEX_LANE_RECEPTOR,
    TEX_TUTORIAL_BASE,
    TEX_WORD_DODGE,
    TEX_WORD_GOOD,
    TEX_WORD_MISS,
    TEX_WORD_PERFECT,
)
from hertzbeats.game_state import RANK_ORDER
from hertzbeats.palettes import PALETTE_CATALOG
from hertzbeats.stages import campaign_ids

LANE_KEY_LABELS = ("A", "S", "W", "D")
"""Rotulos exibidos sob os receptores do Arcade 4K (espelham os
bindings padrao `lane_0..lane_3`). Ordem herdada do FNF: as colunas
esquerda->direita correspondem a <- v ^ -> = A S W D."""

MAX_LATENCY_STEPS = 30
"""Passos de 10 ms da calibracao ao vivo (0..300 ms), um texto
pre-renderizado por valor -- nenhum font.render durante o jogo."""

_DIGIT_COLOR = (235, 235, 255)
_LABEL_COLOR = (130, 125, 170)
_PERFECT_COLOR = (255, 214, 64)
_GOOD_COLOR = (64, 255, 214)
_MISS_COLOR = (255, 80, 96)
_DODGE_COLOR = (70, 225, 225)
"""Mesmo ciano da Captura Orbital (tint de escudo) -- "defesa habilidosa",
distinto tanto do dourado de PERFECT quanto do vermelho de MISS."""

_PINK_COLOR = (255, 105, 180)
"""Developer Tools -- badge "[ DEV ]" LIGADO (rosa) -- distinto do
dourado (`_PERFECT_COLOR`, foco de menu/PERFECT) e do verde
(`_GOOD_COLOR`, cheat ATIVO no painel lateral), sem overlap semantico
com nenhuma outra cor ja estabelecida."""

_RANK_COLORS = {
    "SS": (255, 235, 120), "S": _PERFECT_COLOR, "A": _GOOD_COLOR,
    "B": (140, 160, 255), "C": (255, 170, 90), "D": _MISS_COLOR, "-": _LABEL_COLOR,
}
"""Meta-Jogo -- Ranks: uma cor por letra de `compute_rank` (`RANK_ORDER`
+ "-", a fase sem nenhuma nota resolvida) -- dourado nos 2 melhores,
esmaecendo ate vermelho no pior."""
assert set(_RANK_COLORS) == set(RANK_ORDER) | {"-"}


def build_and_register_hud_textures(renderer: HBPygameRenderer) -> None:
    """Renderiza e registra todas as texturas de HUD. Chamado UMA vez na
    composicao, depois de `renderer.initialize` (precisa do display
    ativo para `convert_alpha`)."""
    if not pygame.font.get_init():
        pygame.font.init()

    digit_font = pygame.font.Font(None, 46)
    word_font = pygame.font.Font(None, 64)
    label_font = pygame.font.Font(None, 28)

    for digit in range(10):
        surface = digit_font.render(str(digit), True, _DIGIT_COLOR).convert_alpha()
        renderer.register_texture(TEX_DIGIT_BASE + digit, surface)

    # UI Bump (Juice Visual): estagios PRE-renderizados de digito
    # "em destaque" (combo cruzando um multiplo de 50), do dourado puro
    # (estagio 0) esmaecendo rumo a cor branca normal do digito (o
    # digito branco de sempre, `TEX_DIGIT_BASE`, e o estagio FINAL --
    # nao duplicado aqui). `UIRenderSystem` so escolhe qual base somar
    # por aritmetica, nunca recolore em tempo real.
    for stage in range(BUMP_FADE_STEPS):
        fraction = 1.0 - (stage / BUMP_FADE_STEPS)  # 1.0 no estagio 0 -> quase 0 no ultimo
        color = tuple(
            int(digit_color + (gold - digit_color) * fraction)
            for digit_color, gold in zip(_DIGIT_COLOR, _PERFECT_COLOR)
        )
        for digit in range(10):
            surface = digit_font.render(str(digit), True, color).convert_alpha()
            renderer.register_texture(TEX_DIGIT_BUMP_BASE + stage * 10 + digit, surface)

    renderer.register_texture(TEX_WORD_PERFECT, word_font.render("PERFECT", True, _PERFECT_COLOR).convert_alpha())
    renderer.register_texture(TEX_WORD_GOOD, word_font.render("GOOD", True, _GOOD_COLOR).convert_alpha())
    renderer.register_texture(TEX_WORD_MISS, word_font.render("MISS", True, _MISS_COLOR).convert_alpha())
    renderer.register_texture(TEX_WORD_DODGE, word_font.render("DODGE", True, _DODGE_COLOR).convert_alpha())
    renderer.register_texture(TEX_LABEL_SCORE, label_font.render("SCORE", True, _LABEL_COLOR).convert_alpha())
    renderer.register_texture(TEX_LABEL_COMBO, label_font.render("COMBO", True, _LABEL_COLOR).convert_alpha())

    crosshair = pygame.Surface((22, 22), pygame.SRCALPHA)
    pygame.draw.circle(crosshair, (255, 255, 255), (11, 11), 10, 2)
    pygame.draw.circle(crosshair, (255, 214, 64), (11, 11), 3)
    renderer.register_texture(TEX_CROSSHAIR, crosshair.convert_alpha())

    pip = pygame.Surface((18, 18), pygame.SRCALPHA)
    pygame.draw.circle(pip, (255, 80, 96), (9, 9), 8)
    pygame.draw.circle(pip, (255, 180, 190), (9, 9), 8, 2)
    renderer.register_texture(TEX_HEALTH_PIP, pip.convert_alpha())

    receptor = pygame.Surface((52, 52), pygame.SRCALPHA)
    pygame.draw.circle(receptor, (200, 195, 240), (26, 26), 23, 3)
    pygame.draw.circle(receptor, (90, 70, 160), (26, 26), 18, 1)
    renderer.register_texture(TEX_LANE_RECEPTOR, receptor.convert_alpha())

    key_font = pygame.font.Font(None, 42)
    for lane, key_label in enumerate(LANE_KEY_LABELS):
        surface = key_font.render(key_label, True, (225, 220, 250)).convert_alpha()
        renderer.register_texture(TEX_KEY_LABEL_BASE + lane, surface)

    # Obstrucao Visual (jumpscare): mancha de tinta procedural -- varios
    # circulos irregulares sobrepostos, gerados por um RNG PROPRIO (seed
    # fixa) para nao mexer no estado global de `random` e para o
    # visual ser deterministico entre builds, mesmo criterio da sintese
    # de SFX/faixas do resto do jogo.
    splat_size = 220
    splat = pygame.Surface((splat_size, splat_size), pygame.SRCALPHA)
    rng = random.Random(1337)
    center = splat_size / 2.0
    for _ in range(9):
        offset_x = rng.uniform(-splat_size * 0.28, splat_size * 0.28)
        offset_y = rng.uniform(-splat_size * 0.28, splat_size * 0.28)
        radius = rng.uniform(splat_size * 0.14, splat_size * 0.32)
        alpha = rng.randint(190, 235)
        pygame.draw.circle(
            splat, (10, 8, 16, alpha), (int(center + offset_x), int(center + offset_y)), int(radius)
        )
    renderer.register_texture(TEX_DISTRACTION_SPLAT, splat.convert_alpha())


_VIGNETTE_COLOR = (5, 3, 10, 255)
"""Cor opaca do Vignette Flash -- quase preto, mesmo tom base da arena
(`begin_frame`) para nao criar um contraste artificial nas bordas."""

_VIGNETTE_HOLE_FRACTION = 0.16
"""Raio do buraco iluminado, como fracao do menor lado da janela."""


def build_and_register_vignette_surface(renderer: HBPygameRenderer, config) -> None:
    """Vignette Flash ("Cegueira Ritmica", Arcade 4K -- Notas Toxicas):
    Surface do TAMANHO DA JANELA, opaca e quase preta, com um buraco
    circular TOTALMENTE TRANSPARENTE focado na linha de julgamento do
    Arcade 4K -- o jogador so consegue ler as notas dentro do circulo
    iluminado enquanto `GameState.blindness_timer_sec > 0`.

    Pre-renderizada UMA UNICA vez no carregamento (nunca por frame):
    `pygame.draw.circle` com alfa 0 sobre uma Surface `SRCALPHA`
    escreve os pixels diretamente (nao mescla), entao o circulo vira um
    buraco de verdade -- nao um circulo "desenhado por cima"."""
    width, height = config.window_width, config.window_height
    judgment_y = config.window_height - config.judgment_line_offset

    surface = pygame.Surface((width, height), pygame.SRCALPHA)
    surface.fill(_VIGNETTE_COLOR)
    hole_radius = int(min(width, height) * _VIGNETTE_HOLE_FRACTION)
    pygame.draw.circle(surface, (0, 0, 0, 0), (width // 2, int(judgment_y)), hole_radius)
    renderer.set_vignette_surface(surface.convert_alpha())


_POLARITY_CONTROL_HINT = (
    "MOUSE mira  |  CLIQUE ESQ = AZUL, CLIQUE DIR = ROSA  |  PARRY em pesadas no tempo exato"
)
"""Dica dedicada da fase de Polaridade -- o mesmo modo Defensor ganha um
segundo botao de cor, entao a dica generica de "defender" nao basta."""

_HOLDS_CONTROL_HINT = (
    "SEGURE o CLIQUE e a MIRA sobre a ameaca pesada ate ela se esgotar -- soltar e MISS na hora"
)
"""Dica dedicada da fase de Notas Longas -- Hold exige SUSTENTAR
gatilho+mira, bem diferente do clique instantaneo do Defensor comum."""

_LANES_HOLDS_CONTROL_HINT = (
    "SEGURE a tecla da coluna na nota CIANO ate o fim -- soltar antes gasta uma carga do Shield"
)
"""Dica dedicada do Arcade 4K com Notas Longas: a tecla precisa
continuar pressionada, nao e mais um toque instantaneo."""

# -- 3o pacote hardcore do Defensor (Gemeos/Eclipses/Overload/Escudos):
#    nenhum deles introduz um controle NOVO alem do que a Polaridade ja
#    usa (clique esq/dir + Parry no tempo certo) -- cada dica so ACRESCE
#    a frase de Polaridade com o que aquele modifier muda no campo de
#    batalha, nunca a substitui por completo (perder a mencao a
#    "CLIQUE ESQ=AZUL, DIR=ROSA" numa fase que ainda tem Polaridade
#    ativa seria uma regressao de informacao, nao uma dica mais focada).
_ORBITAL_SHIELDS_CONTROL_HINT = (
    "CLIQUE ESQ/DIR  |  PARRY em ameaca CIANO vira Escudo Rotativo permanente"
)
_TWIN_THREATS_CONTROL_HINT = (
    "MOUSE mira  |  CLIQUE ESQ/DIR  |  ameacas nascem em PARES opostos -- cubra os dois lados"
)
_ORBITAL_ECLIPSES_CONTROL_HINT = (
    "CLIQUE ESQ/DIR  |  barreiras ROXAS orbitam o nucleo e bloqueiam seu Parry refletido"
)
_OVERLOAD_CONTROL_HINT = (
    "CLIQUE ESQ/DIR enche a Ressonancia  |  ESPACO (Dash) com a barra cheia = Overload"
)
"""4 hints acima medidos com `pygame.font.Font(None, 28).size(...)` contra
a largura padrao da janela (960px) -- todos abaixo de ~910px (mesma faixa
dos hints ja existentes, 886-894px) para nunca estourar as bordas do
`_blit_centered` (que so centraliza, nunca quebra linha nem escala)."""

_PHALANX_CONTROL_HINT = (
    "C alterna o Escudo  |  MOUSE mira o arco  |  bloqueia sozinho -- sem clique"
)
"""Modo Falange (Undyne): o UNICO modifier que troca o controle de
disparo por COMPLETO (nada de clique) -- por isso vence QUALQUER outro
na prioridade de dica abaixo, mais ainda que o Overload."""

_HOLDS_HINT_BY_MODE = {
    "defender": _HOLDS_CONTROL_HINT,
    "lanes": _LANES_HOLDS_CONTROL_HINT,
}
"""Cada modo interpreta o modifier "holds" de um jeito diferente (ver
`HertzConfig.active_modifiers`) -- a dica de controles precisa
acompanhar, por isso e escolhida pelo `game_mode` da fase e nao so pelo
modifier."""

_GENERIC_GAME_MODE_HINTS = {
    "defender": "MOUSE mira  |  CLIQUE atira na batida  |  ESPACO dash",
    "lanes": "A S W D nas colunas, no ritmo das notas",
}
"""Dica-fallback para uma fase CURADA sem nenhum modifier ligado (so o
`game_mode` puro) -- usada pelo loop de `stage_{i}_hint` abaixo. O
seletor de minigame das musicas do jogador (painel de checkboxes) tem
seu PROPRIO texto por linha, ver `_MODIFIER_ROW_LABELS` e
`_GAME_MODE_ROW_LABELS`."""

_MODIFIER_ROW_LABELS = {
    "telegraph_rings": "Aneis de Convergencia",
    "orbital_shields": "Escudos Rotativos (exige Polaridade)",
    "twin_threats": "Gemeos de Polaridade (exige Polaridade)",
    "orbital_eclipses": "Eclipses Orbitais",
    "overload": "Overload do Nucleo (exige Polaridade)",
    "boomerang": "Ameacas Bumerangue (deixe ir, atire na volta)",
    "corrupcao": "Corrupcao (estatica visual na tela)",
    "roleta_russa": "Roleta Russa (1 de vida -- qualquer erro e Game Over)",
    "phalanx": "Modo Falange (C alterna: escudo automatico em vez de tiro)",
}
"""Rotulo de CADA linha BOOLEANA (checkbox) do menu de opcoes do
seletor de minigame -- um por modifier de
`hertz_game_loop.DEFENDER_MODIFIER_ROWS`/`LANES_MODIFIER_ROWS`. NAO
inclui "polarity"/"holds" -- viraram a multipla escolha
`HEAVY_MECHANIC_ROW` (ver `_HEAVY_MECHANIC_ROW_LABELS`), mutuamente
exclusivas por natureza da propria estrutura (nunca dá pra escolher as
duas ao mesmo tempo, ao contrario de 2 checkboxes independentes com
logica de "desliga o outro" escondida). Nao inclui o glifo de caixinha
(marcado/desmarcado) -- isso e desenhado em TEMPO REAL por
`HBPygameRenderer` (mesmo padrao de `_draw_inner_square`/
`_draw_inner_triangle`, um retangulo simples nao precisa de
font.render). Modifiers que dependem de "polarity"
("orbital_shields"/"twin_threats"/"overload") dizem isso no proprio
rotulo -- mais simples que uma segunda textura "desabilitado"."""

_GAME_MODE_ROW_LABELS = {
    "defender": "<  DEFENSOR  >",
    "lanes": "<  ARCADE 4K  >",
}
"""Rotulo da linha ESPECIAL `GAME_MODE_ROW` (sempre a 1a do menu de
opcoes) -- multipla escolha (A/D alternam Defensor/Arcade 4K), por isso
o estilo de seta "< X >" em vez de um checkbox."""

_HEAVY_MECHANIC_ROW_LABELS = {
    "none": "<  Nenhuma  >",
    "polarity": "<  Polaridade  >",
    "holds": "<  Holds  >",
}
"""Rotulo da linha ESPECIAL `HEAVY_MECHANIC_ROW` (sempre a 2a do menu de
opcoes) -- outra multipla escolha (A/D alternam Nenhuma/Polaridade/
Holds), mesmo estilo de seta de `_GAME_MODE_ROW_LABELS`. Substitui os
antigos checkboxes independentes "polarity"/"holds" -- as duas
mecanicas sao mutuamente exclusivas (mesmo `threat_type` "pesada"), uma
multipla escolha de 3 valores torna isso estrutural."""

_HUB_CATEGORY_LABELS = {
    "campaign": "[ CAMPANHA ]",
    "free_play": "[ FREE PLAY ]",
    "vault": "[ ARQUIVOS (VAULT) ]",
    "calibration": "[ CALIBRACAO ]",
    "ironman": "[ IRONMAN ]",
    "roguelite": "[ ROGUE-LITE ]",
    "download_music": "[ IMPORTAR MUSICA ]",
}
"""HUB Principal: rotulo de cada uma das 7 categorias grandes
(`hertz_game_loop.HUB_CATEGORIES`), na MESMA ordem fixa. "ironman"/
"roguelite" nao tem tela propria -- confirma-las ja inicia o gauntlet/
a corrida. "download_music" leva a `FLOW_DOWNLOAD_HUB` (Pipeline de
Importacao Direta)."""

_ROGUE_PERK_LABELS = {
    "vampirism_threshold": "VAMPIRISMO -- cura 1 de vida a cada 10 PERFECTs seguidos",
    "perfect_window_multiplier": "JANELA AMPLIADA -- +15% na janela do PERFECT",
}
"""Rogue-lite Endgame -- Recompensa: rotulo de cada Perk do catalogo
(`hertzbeats.rogue_lite.ROGUE_PERK_CATALOG`) -- textura ESTATICA (so 2
Perks existem, nenhum valor dinamico precisa de `font.render` no loop)."""

_ROGUE_MODIFIER_LABELS = {
    "wormholes": "BURACOS DE MINHOCA",
    "mirages": "AMEACAS FANTASMAS",
    "rubber_band": "EFEITO ELASTICO",
}
"""Rogue-lite Endgame -- Mapa: rotulo de cada modifier de Mind Games
forcado numa opcao de musica (`hertzbeats.rogue_lite.roll_map_choices`)."""

_SCORE_MULTIPLIER_MIN = 0.10
_SCORE_MULTIPLIER_STEP = 0.05
_SCORE_MULTIPLIER_STEPS = 40
"""Pre-Voo -- Multiplicador de Pontuacao: DUPLICA de proposito as
constantes privadas de `hb_pygame_renderer._draw_preflight_overlay`
(mesmo criterio de `MAX_LATENCY_STEPS` acima, que ja duplica o limite de
`hertz_game_loop._LATENCY_MAX_SECONDS`) -- o adapter de texturas nao
importa estado privado do renderer, so respeita a MESMA faixa por
convencao/comentario."""

_START_ROW_LABEL = ">>>  INICIAR FASE  <<<"
"""Rotulo da linha ESPECIAL `START_ROW` (sempre a ULTIMA do menu de
opcoes) -- o UNICO lugar onde ESPACO/ENTER de fato inicia a fase de uma
musica do jogador (ver `HertzGameLoop._advance_menu_options`). ASCII
puro de proposito: os glifos Unicode de "play"/triangulo (▶ U+25B6, ◀
U+25C0) viram um quadrado vazio ("tofu") na fonte PADRAO do pygame
(`pygame.font.Font(None, ...)`, sem arquivo de fonte custom) --
verificado empiricamente antes de escolher este rotulo."""


def build_and_register_overlay_surfaces(renderer: HBPygameRenderer, stages) -> None:
    """Pre-renderiza as superficies dos overlays de meta-jogo (menu de
    fases, PAUSADO, GAME OVER, FASE CONCLUIDA e dicas de tecla). Chamado
    UMA vez na composicao -- o desenho por frame e so blit."""
    if not pygame.font.get_init():
        pygame.font.init()

    title_font = pygame.font.Font(None, 88)
    big_font = pygame.font.Font(None, 84)
    stage_font = pygame.font.Font(None, 40)
    hint_font = pygame.font.Font(None, 28)

    def register_text(key, font, text, color):
        renderer.register_overlay_surface(key, font.render(text, True, color).convert_alpha())

    register_text("title", title_font, "HERTZ & BEATS", _DIGIT_COLOR)
    register_text("subtitle", hint_font, "defesa de perimetro no ritmo da musica", _LABEL_COLOR)
    register_text("paused", big_font, "PAUSADO", _DIGIT_COLOR)
    register_text("game_over", big_font, "GAME OVER", _MISS_COLOR)
    register_text("results", big_font, "FASE CONCLUIDA", _GOOD_COLOR)
    # Meta-Jogo -- Ranks: uma textura por letra possivel de `compute_rank`
    # (incluindo "-", a fase sem nenhuma nota resolvida), cor por faixa
    # de desempenho -- dourado nos 2 melhores, esmaecendo ate vermelho.
    rank_font = pygame.font.Font(None, 96)
    for rank_letter, rank_color in _RANK_COLORS.items():
        register_text(f"rank_{rank_letter}", rank_font, rank_letter, rank_color)
    register_text(
        "hint_menu", hint_font,
        "SETAS ou W/S escolhem  |  ENTER, ESPACO ou CLIQUE jogam  |  ESC sai", _LABEL_COLOR,
    )
    register_text("hint_paused", hint_font, "ESC continua  |  M volta ao menu", _LABEL_COLOR)
    register_text("flow_shatter", big_font, "VIDRO QUEBRADO!", _MISS_COLOR)
    register_text("practice_on", hint_font, "MODO TREINO: LIGADO (T)  -- menos notas, sem dano", _GOOD_COLOR)
    register_text("practice_off", hint_font, "MODO TREINO: DESLIGADO (T)", _LABEL_COLOR)
    register_text("hint_end", hint_font, "R tenta de novo  |  M volta ao menu", _LABEL_COLOR)
    register_text(
        "hint_results", hint_font,
        "ENTER proxima fase  |  R repete  |  M volta ao menu", _LABEL_COLOR,
    )

    for i, stage in enumerate(stages):
        label = f"{stage.name}   {stage.subtitle}" if stage.subtitle else stage.name
        register_text(f"stage_{i}", stage_font, label, _LABEL_COLOR)
        register_text(f"stage_{i}_sel", stage_font, f"> {label} <", _PERFECT_COLOR)
        stage_mode = stage.overrides.get("game_mode", "defender")
        # Prioridade do mais especifico/novo pro mais generico -- uma
        # fase pode ter VARIOS modifiers ao mesmo tempo (ex.: "5 -
        # Pesadelo" tem todos), mas so ha espaco pra UMA linha de dica;
        # Overload vence porque e o UNICO que muda um controle de
        # verdade (uso do Dash), os demais so mudam o que acontece no
        # campo de batalha em cima do mesmo clique esq/dir de Polaridade.
        if "phalanx" in stage.active_modifiers:
            hint_text = _PHALANX_CONTROL_HINT
        elif "overload" in stage.active_modifiers:
            hint_text = _OVERLOAD_CONTROL_HINT
        elif "orbital_shields" in stage.active_modifiers:
            hint_text = _ORBITAL_SHIELDS_CONTROL_HINT
        elif "twin_threats" in stage.active_modifiers:
            hint_text = _TWIN_THREATS_CONTROL_HINT
        elif "orbital_eclipses" in stage.active_modifiers:
            hint_text = _ORBITAL_ECLIPSES_CONTROL_HINT
        elif "polarity" in stage.active_modifiers:
            hint_text = _POLARITY_CONTROL_HINT
        elif "holds" in stage.active_modifiers:
            # cada modo interpreta Hold a sua maneira -- a dica segue o
            # `game_mode` da fase, nao so o modifier (ver `_HOLDS_HINT_BY_MODE`)
            hint_text = _HOLDS_HINT_BY_MODE.get(stage_mode, _HOLDS_CONTROL_HINT)
        else:
            hint_text = _GENERIC_GAME_MODE_HINTS.get(stage_mode, "")
        register_text(f"stage_{i}_hint", hint_font, hint_text, _GOOD_COLOR)

        # Fases e Campanhas: frase curta de imersao/lore da fase (`StageDef.
        # description`), mostrada no Carrossel logo abaixo do nome em foco.
        # String vazia (musicas do jogador, ou uma fase curada sem lore
        # escrita) so' renderiza uma textura de largura ~0 -- inofensivo,
        # mesmo criterio de `stage_{i}_hint` com `hint_text=""`.
        register_text(f"stage_{i}_description", hint_font, stage.description, _LABEL_COLOR)

        # Progressao de Campanha -- Lado B/Remix: so fases curadas com
        # `StageDef.b_side_name` ganham as 2 texturas (dica de toggle A/D
        # + o proprio nome, mostrado quando escolhido) -- cor de perigo
        # (_MISS_COLOR) de proposito, sinalizando a dificuldade mais dura
        # antes mesmo do jogador confirmar o toggle.
        if stage.b_side_name is not None:
            register_text(
                f"stage_{i}_b_side_hint", hint_font,
                "A/D: LADO B DISPONIVEL (mais dificil)", _MISS_COLOR,
            )
            register_text(f"stage_{i}_b_side_name", stage_font, stage.b_side_name, _MISS_COLOR)

    # calibracao de latencia ao vivo: um aviso por valor (passos de 10 ms)
    for step in range(MAX_LATENCY_STEPS + 1):
        register_text(
            f"latency_{step}", hint_font,
            f"CALIBRACAO DE AUDIO: {step * 10} ms   (+ atrasa o julgamento | - adianta)",
            _PERFECT_COLOR,
        )

    # seletor de minigame das musicas do jogador: menu de opcoes
    # (GAME_MODE_ROW + HEAVY_MECHANIC_ROW de multipla escolha, modifiers
    # booleanos e START_ROW) + indicadores de rolagem da lista de fases.
    for game_mode, label in _GAME_MODE_ROW_LABELS.items():
        register_text(f"modifier_row_game_mode_{game_mode}", hint_font, label, _PERFECT_COLOR)
    for heavy_mechanic, label in _HEAVY_MECHANIC_ROW_LABELS.items():
        register_text(f"modifier_row_heavy_mechanic_{heavy_mechanic}", hint_font, label, _PERFECT_COLOR)
    register_text("modifier_row_start", hint_font, _START_ROW_LABEL, _PERFECT_COLOR)
    for modifier_name, label in _MODIFIER_ROW_LABELS.items():
        register_text(f"modifier_row_{modifier_name}", hint_font, label, _GOOD_COLOR)
    register_text("scroll_up", hint_font, "^ ^ ^", _LABEL_COLOR)
    register_text("scroll_down", hint_font, "v v v", _LABEL_COLOR)

    # -- O Novo Fluxo de Menus (Experiencia Arcade) -----------------------

    register_text("press_space", hint_font, "PRESSIONE ESPACO", _DIGIT_COLOR)
    register_text("stage_locked", hint_font, "TRANCADA -- vença a fase anterior primeiro", _MISS_COLOR)
    register_text("auto_play_active", hint_font, "[ AUTO-PLAY ]", _PERFECT_COLOR)
    """Developer Tools -- Auto-Play (Modo Deus): indicador piscante
    exibido durante FLOW_PLAYING enquanto `GameState.bot_mode` estiver
    ligado (`HBPygameRenderer.end_frame`, mesmo criterio de piscar de
    `press_space` -- alfa em seno sobre o relogio de parede)."""

    # Developer Tools -- gate mestre dos cheats: badge "[ DEV ]" (SEMPRE
    # visivel, cor conforme ligado/desligado), flashes de confirmacao
    # (`_notice_key`, mesmo mecanismo de "stage_locked") e o painel
    # lateral listando os 3 cheats -- 2 variantes por linha (normal/
    # ATIVA em verde) so' pras 2 que tem um estado persistente pra
    # destacar (Auto-Play/Unlock All); Reset de Save e' uma acao unica,
    # sem "ligado/desligado" pra destacar.
    register_text("dev_badge_on", hint_font, "[ DEV ]", _PINK_COLOR)
    register_text("dev_badge_off", hint_font, "[ DEV ]", _LABEL_COLOR)
    register_text("dev_mode_on_notice", hint_font, "MODO DEV ATIVADO", _PERFECT_COLOR)
    register_text("dev_mode_off_notice", hint_font, "MODO DEV DESATIVADO", _LABEL_COLOR)
    register_text("cheat_unlock_all_notice", hint_font, "CHEAT ATIVADO", _PERFECT_COLOR)
    register_text("cheat_wipe_save_notice", hint_font, "SAVE APAGADO", _MISS_COLOR)
    register_text("dev_panel_title", hint_font, "CHEATS DISPONIVEIS", _DIGIT_COLOR)
    register_text("dev_panel_bot_mode", hint_font, "F12: Auto-Play (Modo Deus)", _LABEL_COLOR)
    register_text("dev_panel_bot_mode_active", hint_font, "F12: Auto-Play (Modo Deus)", _GOOD_COLOR)
    register_text("dev_panel_unlock_all", hint_font, "F9: Desbloquear Tudo", _LABEL_COLOR)
    register_text("dev_panel_unlock_all_active", hint_font, "F9: Desbloquear Tudo", _GOOD_COLOR)
    register_text("dev_panel_wipe_save", hint_font, "CTRL+SHIFT+DEL: Reset de Save", _LABEL_COLOR)
    register_text("unlock_all_persistent_badge", hint_font, "[ TUDO DESBLOQUEADO ]", _GOOD_COLOR)
    """Developer Tools -- Unlock All: badge PERSISTENTE (abaixo de
    "[ DEV ]", canto superior direito) enquanto `_debug_unlock_all`
    estiver ligado -- ao contrario do flash de 1.8s ou do painel lateral
    (que some assim que o gate mestre desliga), este fica visivel
    INDEPENDENTE do gate, ja que o desbloqueio e' permanente pelo resto
    da sessao. Existe porque o efeito de verdade (destrancar fases) so'
    aparece ao navegar ate uma fase de Campanha -- sem isso, nao ha jeito
    de confirmar de relance se o cheat esta ativo."""

    register_text("slash", stage_font, "/", _LABEL_COLOR)
    register_text("colon", stage_font, ":", _LABEL_COLOR)

    # Pipeline de Importacao Direta (FLOW_DOWNLOAD_HUB): titulo fixo da
    # tela + os 4 alertas de estado (Aguardando/Buscando Previa/
    # Baixando/Sucesso) + os hints por sub-estado + o aviso transiente
    # de URL invalida (`_notice_key`, mesmo mecanismo de "stage_locked").
    # Titulo/canal da Previa e a mensagem de erro sao DINAMICOS --
    # renderizados sob demanda em `HBPygameRenderer.set_download_preview`/
    # `set_download_error`, nunca aqui (nao sao strings fixas conhecidas
    # de antemao).
    register_text("download_hub_title", big_font, "IMPORTAR DO YOUTUBE", _DIGIT_COLOR)
    register_text("download_hub_waiting", hint_font, "AGUARDANDO LINK...", _LABEL_COLOR)
    register_text("download_hub_fetching_preview", hint_font, "BUSCANDO PREVIA...", _LABEL_COLOR)
    register_text("download_hub_downloading", hint_font, "BAIXANDO AUDIO E GERANDO BEATMAP...", _LABEL_COLOR)
    register_text("download_hub_success", hint_font, "SUCESSO!", _GOOD_COLOR)
    register_text("download_hub_error_title", hint_font, "FALHA NA IMPORTACAO", _MISS_COLOR)
    register_text(
        "hint_download_hub_waiting", hint_font,
        "Copie uma URL do YouTube e pressione CTRL+V  |  ESC volta ao HUB", _LABEL_COLOR,
    )
    register_text(
        "hint_download_hub_confirm", hint_font,
        "[ ENTER ] Confirmar Download  |  [ ESC ] Cancelar", _PERFECT_COLOR,
    )
    register_text("hint_download_hub_back", hint_font, "ENTER ou ESC volta", _LABEL_COLOR)
    register_text("invalid_url_notice", hint_font, "URL Invalida", _MISS_COLOR)

    # HUB Principal: 4 categorias grandes, normal + foco ("_sel", MESMO
    # estilo "> X <" dourado das linhas de fase do antigo menu unico).
    for category, label in _HUB_CATEGORY_LABELS.items():
        register_text(f"hub_category_{category}", stage_font, label, _LABEL_COLOR)
        register_text(f"hub_category_{category}_sel", stage_font, f"> {label} <", _PERFECT_COLOR)
    register_text(
        "hint_hub", hint_font,
        "SETAS ou W/S escolhem  |  ENTER ou ESPACO confirma  |  ESC volta ao Titulo", _LABEL_COLOR,
    )

    # Rogue-lite Endgame: titulos/rotulos ESTATICOS das 2 telas novas
    # (Mapa/Recompensa) -- os nomes das musicas sorteadas reusam as
    # texturas `stage_{i}`/`stage_{i}_sel` ja registradas acima (todo
    # `StageDef`, incluindo musicas do jogador, ja tem a sua).
    register_text("roguelite_map_title", big_font, "MAPA ROGUE-LITE", _DIGIT_COLOR)
    register_text("roguelite_reward_title", big_font, "ESCOLHA UM PERK", _GOOD_COLOR)
    register_text("label_rogue_health", hint_font, "VIDA:", _LABEL_COLOR)
    register_text("label_rogue_level", hint_font, "NIVEL:", _LABEL_COLOR)
    for modifier_name, label in _ROGUE_MODIFIER_LABELS.items():
        register_text(f"roguelite_modifier_{modifier_name}", hint_font, label, _MISS_COLOR)
    for perk_id, label in _ROGUE_PERK_LABELS.items():
        register_text(f"roguelite_perk_{perk_id}", stage_font, label, _LABEL_COLOR)
        register_text(f"roguelite_perk_{perk_id}_sel", stage_font, f"> {label} <", _PERFECT_COLOR)
    register_text(
        "hint_roguelite_map", hint_font,
        "SETAS escolhem a musica  |  ENTER joga  |  ESC encerra a corrida", _LABEL_COLOR,
    )
    register_text(
        "hint_roguelite_reward", hint_font,
        "SETAS escolhem o Perk  |  ENTER confirma  |  ESC encerra a corrida", _LABEL_COLOR,
    )

    # Carrossel: um cabecalho POR campanha (`StageDef.campaign_id`,
    # auto-derivado do proprio id -- "defender_core" -> "CAMPANHA:
    # DEFENDER CORE" -- nunca hardcoded, entao uma campanha nova em
    # `stages.json` sempre ganha cabecalho, nunca fica em branco) + Free
    # Play + estado vazio (nenhuma musica em musicas/) + dicas de
    # navegacao/troca de visao.
    for c_id in campaign_ids(stages):
        label = "CAMPANHA: " + c_id.replace("_", " ").upper()
        register_text(f"carousel_category_{c_id}", hint_font, label, _LABEL_COLOR)
    register_text("carousel_category_free_play", hint_font, "FREE PLAY", _LABEL_COLOR)
    register_text("carousel_empty", stage_font, "Nenhuma musica encontrada em musicas/", _LABEL_COLOR)
    register_text("carousel_locked_badge", stage_font, "FASE TRANCADA", _MISS_COLOR)
    register_text(
        "hint_carousel", hint_font,
        "SETAS ou W/S escolhem  |  ENTER ou ESPACO confirma  |  ESC volta ao HUB", _LABEL_COLOR,
    )
    register_text(
        "hint_carousel_switch_view", hint_font,
        "Q/E ou TAB: trocar campanha/Free Play", _LABEL_COLOR,
    )
    register_text("label_bpm", stage_font, "BPM", _LABEL_COLOR)
    register_text("label_duration", stage_font, "DURACAO", _LABEL_COLOR)

    # Pre-Voo: previa ao vivo do Multiplicador de Pontuacao (passos de
    # 0.05, mesmo criterio de `latency_{step}` acima) + dicas por tipo de
    # fase (musica do jogador com painel completo vs. fase curada so-
    # leitura).
    for step in range(_SCORE_MULTIPLIER_STEPS + 1):
        value = _SCORE_MULTIPLIER_MIN + step * _SCORE_MULTIPLIER_STEP
        color = _GOOD_COLOR if value >= 1.0 else _MISS_COLOR
        register_text(f"score_multiplier_{step}", hint_font, f"MULTIPLICADOR DE PONTUACAO: x{value:.2f}", color)
    register_text(
        "hint_preflight_options", hint_font,
        "SETAS escolhem  |  A/D altera  |  ENTER liga/inicia  |  ESC volta ao Carrossel", _LABEL_COLOR,
    )
    register_text(
        "hint_preflight_curated", hint_font,
        "ENTER ou ESPACO inicia a fase  |  ESC volta ao Carrossel", _LABEL_COLOR,
    )

    # Arquivos (Vault): agregados globais de player_progress.json.
    register_text("vault_title", big_font, "ARQUIVOS (VAULT)", _DIGIT_COLOR)
    register_text("label_cleared", hint_font, "FASES VENCIDAS", _LABEL_COLOR)
    register_text("label_medals", hint_font, "MEDALHAS", _LABEL_COLOR)
    register_text("label_lifetime_perfect", hint_font, "PERFECTS NA VIDA", _PERFECT_COLOR)
    register_text("label_lifetime_shots", hint_font, "TIROS DISPARADOS", _LABEL_COLOR)
    register_text("label_lifetime_playtime", hint_font, "TEMPO JOGADO", _LABEL_COLOR)
    register_text("label_palette", hint_font, "PALETA (A/D troca entre as desbloqueadas)", _LABEL_COLOR)
    for palette_id, palette in PALETTE_CATALOG.items():
        register_text(f"palette_name_{palette_id}", stage_font, palette["label"], _PERFECT_COLOR)
    register_text("hint_vault", hint_font, "A/D troca paleta  |  ENTER, ESPACO ou ESC volta ao HUB", _LABEL_COLOR)

    # Calibracao: instrucao fixa + contador de toques + feedback de
    # cedo/tarde/no tempo do ULTIMO toque (3 texturas discretas).
    register_text(
        "calibration_hint", hint_font,
        "Acompanhe o metronomo e aperte ESPACO no tempo de cada batida", _DIGIT_COLOR,
    )
    register_text("label_taps", hint_font, "TOQUES DADOS", _LABEL_COLOR)
    register_text("calibration_early", hint_font, "CEDO", _DODGE_COLOR)
    register_text("calibration_late", hint_font, "TARDE", _MISS_COLOR)
    register_text("calibration_ontime", hint_font, "NO TEMPO", _GOOD_COLOR)
    register_text("hint_calibration", hint_font, "ESC volta ao HUB", _LABEL_COLOR)

    # Progressao de Campanha -- Ironman: aviso "IRONMAN: FASE N/M" ao
    # iniciar CADA fase do gauntlet (`HertzGameLoop._start_ironman_next_stage`,
    # mesmo mecanismo de `_notice_key` do aviso de fase trancada acima) --
    # `M` e' FIXO (fases curadas exceto o tutorial), uma textura por `N`
    # possivel, mesmo criterio de `latency_{step}`/`score_multiplier_{step}`.
    ironman_total = sum(1 for s in stages if not s.selectable_mode and not s.tutorial_steps)
    for n in range(1, ironman_total + 1):
        register_text(f"ironman_progress_{n}", hint_font, f"IRONMAN: FASE {n}/{ironman_total}", _MISS_COLOR)


def build_and_register_tutorial_textures(renderer: HBPygameRenderer, stages) -> None:
    """Pre-renderiza os textos de instrucao de TODAS as fases com
    tutorial: o passo `j` da fase `i` vira a textura
    `TEX_TUTORIAL_BASE + i * MAX_TUTORIAL_STEPS + j`, consumida pelo
    `TutorialSystem` durante o gameplay sem nenhum font.render."""
    if not pygame.font.get_init():
        pygame.font.init()
    banner_font = pygame.font.Font(None, 38)

    for stage_index, stage in enumerate(stages):
        steps = stage.tutorial_steps
        if len(steps) > MAX_TUTORIAL_STEPS:
            raise ValueError(
                f"fase {stage.stage_id}: {len(steps)} passos de tutorial excedem MAX_TUTORIAL_STEPS"
            )
        for step_index, step in enumerate(steps):
            surface = banner_font.render(step["text"], True, _PERFECT_COLOR).convert_alpha()
            renderer.register_texture(
                TEX_TUTORIAL_BASE + stage_index * MAX_TUTORIAL_STEPS + step_index, surface
            )
