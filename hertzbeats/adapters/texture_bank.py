"""
Pre-renderizacao das texturas de HUD na tela de carregamento: os
digitos 0-9 e as palavras PERFECT/GOOD/MISS viram Surfaces ESTATICAS
registradas no renderer UMA unica vez. Nenhum `font.render` acontece
depois disso -- o `UIRenderSystem` so escolhe `texture_id` por
aritmetica e o `draw_batch` blita as Surfaces ja prontas.
"""
from __future__ import annotations

import pygame

from hertzbeats.adapters.hb_pygame_renderer import HBPygameRenderer
from hertzbeats.components.texture_ids import (
    MAX_TUTORIAL_STEPS,
    TEX_CROSSHAIR,
    TEX_DIGIT_BASE,
    TEX_HEALTH_PIP,
    TEX_KEY_LABEL_BASE,
    TEX_LABEL_COMBO,
    TEX_LABEL_SCORE,
    TEX_LANE_RECEPTOR,
    TEX_TUTORIAL_BASE,
    TEX_WORD_GOOD,
    TEX_WORD_MISS,
    TEX_WORD_PERFECT,
)

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

    renderer.register_texture(TEX_WORD_PERFECT, word_font.render("PERFECT", True, _PERFECT_COLOR).convert_alpha())
    renderer.register_texture(TEX_WORD_GOOD, word_font.render("GOOD", True, _GOOD_COLOR).convert_alpha())
    renderer.register_texture(TEX_WORD_MISS, word_font.render("MISS", True, _MISS_COLOR).convert_alpha())
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

_SURVIVAL_HOLDS_CONTROL_HINT = (
    "FIQUE dentro da Safe Zone verde e SEGURE E ate o fim -- sair ou soltar e MISS"
)
"""Dica dedicada da Sobrevivencia com Safe Zone: exige ficar parado
dentro da zona E segurar a acao Ancorar."""

_HOLDS_HINT_BY_MODE = {
    "defender": _HOLDS_CONTROL_HINT,
    "lanes": _LANES_HOLDS_CONTROL_HINT,
    "survival": _SURVIVAL_HOLDS_CONTROL_HINT,
}
"""Cada modo interpreta `holds_enabled` de um jeito diferente (ver
`HertzConfig.holds_enabled`) -- a dica de controles precisa acompanhar,
por isso e escolhida pelo `game_mode` da fase e nao so pela flag."""

_MODE_CONTROL_HINTS = {
    "defender": "MOUSE mira  |  CLIQUE atira na batida  |  ESPACO dash",
    "survival": "W A S D movem  |  ESPACO dash atraves das ondas  |  sem tiro",
    "lanes": "A S W D nas colunas, no ritmo das notas",
    "hybrid": "W A S D movem + MOUSE/CLIQUE atiram  |  ESPACO dash",
    "polarity": _POLARITY_CONTROL_HINT,
    "holds": _HOLDS_CONTROL_HINT,
    "lanes_holds": _LANES_HOLDS_CONTROL_HINT,
    "survival_holds": _SURVIVAL_HOLDS_CONTROL_HINT,
}
"""Dica de controles exibida no menu para o MODO/variante da fase
selecionada -- "polarity"/"holds"/"lanes_holds"/"survival_holds" reusam
a MESMA dica das fases curadas equivalentes (mesmas mecanicas, agora
tambem escolhiveis para musicas do jogador via A/D)."""

_MODE_DISPLAY_NAMES = {
    "defender": "O DEFENSOR",
    "survival": "SOBREVIVENCIA",
    "lanes": "ARCADE 4K",
    "hybrid": "HIBRIDO",
    "polarity": "DEFENSOR: POLARIDADE",
    "holds": "DEFENSOR: NOTAS LONGAS",
    "lanes_holds": "ARCADE 4K: NOTAS LONGAS",
    "survival_holds": "SOBREVIVENCIA: SAFE ZONE",
}
"""Nome exibido no seletor de minigame das musicas do jogador."""


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
        if stage.overrides.get("polarity_enabled", False):
            hint_text = _POLARITY_CONTROL_HINT
        elif stage.overrides.get("holds_enabled", False):
            # cada modo interpreta Hold a sua maneira -- a dica segue o
            # `game_mode` da fase, nao so a flag (ver `_HOLDS_HINT_BY_MODE`)
            hint_text = _HOLDS_HINT_BY_MODE.get(stage_mode, _HOLDS_CONTROL_HINT)
        else:
            hint_text = _MODE_CONTROL_HINTS.get(stage_mode, "")
        register_text(f"stage_{i}_hint", hint_font, hint_text, _GOOD_COLOR)

    # calibracao de latencia ao vivo: um aviso por valor (passos de 10 ms)
    for step in range(MAX_LATENCY_STEPS + 1):
        register_text(
            f"latency_{step}", hint_font,
            f"CALIBRACAO DE AUDIO: {step * 10} ms   (+ atrasa o julgamento | - adianta)",
            _PERFECT_COLOR,
        )

    # seletor de minigame das musicas do jogador + indicadores de rolagem
    mode_font = pygame.font.Font(None, 44)
    for mode, mode_name in _MODE_DISPLAY_NAMES.items():
        register_text(f"modename_{mode}", mode_font, f"<  MODO: {mode_name}  >", _PERFECT_COLOR)
        register_text(f"modectl_{mode}", hint_font, _MODE_CONTROL_HINTS[mode], _GOOD_COLOR)
    register_text("scroll_up", hint_font, "^ ^ ^", _LABEL_COLOR)
    register_text("scroll_down", hint_font, "v v v", _LABEL_COLOR)


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
