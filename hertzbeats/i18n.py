"""Catalogo de textos da interface (i18n).

Estado do jogo antes disto: todo texto e' PT-BR literal, espalhado por
~94 chamadas de `register_text` e alguns dicionarios de rotulo em
`texture_bank.py`. Nao e' divida tecnica -- e' uma decisao de produto
ainda nao tomada (o jogo pode nunca precisar de outro idioma).

Por isso o que existe aqui e' a INFRAESTRUTURA e a fiacao dos rotulos
ENUMERAVEIS (as categorias do HUB, as linhas de multipla escolha do
Pre-Voo), nao uma traducao completa: os 94 textos inline seguem literais e
sao uma passada de traducao em massa, trabalho de conteudo e nao de
engenharia. Traduzir tudo antes de haver um segundo idioma de verdade
seria inventar requisito.

Duas decisoes que importam:

- **`pt_BR` e' a fonte da verdade**, nao o ingles. O jogo foi escrito em
  portugues (codigo, comentarios, textos) e inverter isso agora seria uma
  reescrita gratuita. Locale ausente cai pra `pt_BR`; chave ausente cai
  pra propria chave, que aparece na tela como `HUB_CAMPAIGN` -- feio de
  proposito, pra ser impossivel de nao notar em teste manual.
- **Sem acentos nos valores.** As texturas do HUD sao renderizadas com a
  fonte embutida do pygame (`pygame.font.Font(None, ...)`), e o resto do
  jogo ja escreve "CALIBRACAO"/"MUSICA" sem acento pelo mesmo motivo --
  manter a convencao evita glifo faltando na tela.

O locale e resolvido UMA vez, na construcao das texturas (nunca por
frame): trocar de idioma exige recompor as texturas, exatamente como
trocar de paleta.
"""
from __future__ import annotations

import os
from typing import Dict, Optional

DEFAULT_LOCALE = "pt_BR"
LOCALE_ENV_VAR = "HERTZ_LOCALE"

CATALOG: Dict[str, Dict[str, str]] = {
    "pt_BR": {
        # HUB Principal -- as 7 categorias grandes
        "hub.campaign": "[ CAMPANHA ]",
        "hub.free_play": "[ FREE PLAY ]",
        "hub.vault": "[ ARQUIVOS (VAULT) ]",
        "hub.calibration": "[ CALIBRACAO ]",
        "hub.ironman": "[ IRONMAN ]",
        "hub.roguelite": "[ ROGUE-LITE ]",
        "hub.download_music": "[ IMPORTAR MUSICA ]",
        # Pre-Voo -- linha de multipla escolha do modo base
        "mode.defender": "<  DEFENSOR  >",
        "mode.lanes": "<  ARCADE 4K  >",
    },
    "en": {
        "hub.campaign": "[ CAMPAIGN ]",
        "hub.free_play": "[ FREE PLAY ]",
        "hub.vault": "[ ARCHIVE (VAULT) ]",
        "hub.calibration": "[ CALIBRATION ]",
        "hub.ironman": "[ IRONMAN ]",
        "hub.roguelite": "[ ROGUE-LITE ]",
        "hub.download_music": "[ IMPORT MUSIC ]",
        "mode.defender": "<  DEFENDER  >",
        "mode.lanes": "<  ARCADE 4K  >",
    },
}

_current_locale = DEFAULT_LOCALE


def available_locales() -> tuple:
    return tuple(sorted(CATALOG))


def resolve_locale(requested: Optional[str] = None) -> str:
    """Locale efetivo: o pedido, senao `HERTZ_LOCALE`, senao o default.

    Um locale desconhecido cai no default em vez de levantar -- um idioma
    digitado errado numa variavel de ambiente nao deve impedir o jogo de
    abrir.
    """
    candidate = requested or os.environ.get(LOCALE_ENV_VAR) or DEFAULT_LOCALE
    return candidate if candidate in CATALOG else DEFAULT_LOCALE


def set_locale(locale: Optional[str]) -> str:
    """Fixa o locale do processo e devolve o efetivo. Chamar na composicao,
    ANTES de construir as texturas -- os textos sao pre-renderizados uma
    vez, entao trocar depois nao muda nada na tela."""
    global _current_locale
    _current_locale = resolve_locale(locale)
    return _current_locale


def current_locale() -> str:
    return _current_locale


def translate(key: str, locale: Optional[str] = None) -> str:
    """Texto de `key`, com fallback em cascata: locale pedido -> `pt_BR` ->
    a propria chave.

    Devolver a chave (e nao string vazia, nem levantar) e deliberado: uma
    chave nova sem traducao aparece na tela como `hub.novidade`, visivel
    demais pra passar batido, sem quebrar o jogo de quem so queria jogar.
    """
    active = resolve_locale(locale) if locale is not None else _current_locale
    table = CATALOG.get(active, {})
    if key in table:
        return table[key]
    return CATALOG[DEFAULT_LOCALE].get(key, key)


def labels_for_prefix(prefix: str, locale: Optional[str] = None) -> Dict[str, str]:
    """`{sufixo: texto}` de todas as chaves sob `prefix` -- o formato que os
    dicionarios de rotulo de `texture_bank` ja consomem (`{"campaign":
    "[ CAMPANHA ]"}`), pra fiacao ficar uma linha em vez de um laco.

    As chaves vem SEMPRE do catalogo `pt_BR` (a fonte da verdade), entao
    uma traducao incompleta perde o texto e nunca a entrada -- o HUB nunca
    fica com uma categoria faltando por causa de idioma.
    """
    dotted = prefix if prefix.endswith(".") else prefix + "."
    return {
        key[len(dotted) :]: translate(key, locale)
        for key in CATALOG[DEFAULT_LOCALE]
        if key.startswith(dotted)
    }
