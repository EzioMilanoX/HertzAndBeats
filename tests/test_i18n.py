"""Catalogo de textos (i18n): infraestrutura, nao traducao completa.

O jogo e PT-BR literal em ~94 chamadas de `register_text`; o que existe
aqui e a infraestrutura mais a fiacao dos rotulos ENUMERAVEIS (categorias
do HUB, linhas de multipla escolha). Traduzir os 94 textos inline e uma
passada de conteudo, nao de engenharia.

O teste mais valioso do arquivo e `test_every_locale_covers_every_key`: e
o unico que impede a falha real desta feature, que nao e' um crash -- e um
idioma silenciosamente meio traduzido.
"""
import pytest

from hertzbeats import i18n


@pytest.fixture(autouse=True)
def restore_locale():
    """O locale e estado de MODULO (fixado uma vez na composicao): sem
    restaurar, um teste contaminaria os seguintes."""
    previous = i18n.current_locale()
    yield
    i18n.set_locale(previous)


def test_default_locale_is_portuguese():
    """PT-BR e a fonte da verdade, nao o ingles: o jogo foi escrito em
    portugues e inverter isso seria reescrita gratuita."""
    assert i18n.DEFAULT_LOCALE == "pt_BR"
    assert i18n.DEFAULT_LOCALE in i18n.CATALOG


def test_every_locale_covers_every_key():
    """A invariante que sustenta a feature. A falha real do i18n nao e um
    crash: e um idioma faltando 3 rotulos, que ninguem nota sem jogar o
    jogo inteiro naquele idioma."""
    reference = set(i18n.CATALOG[i18n.DEFAULT_LOCALE])
    for locale, table in i18n.CATALOG.items():
        missing = reference - set(table)
        extra = set(table) - reference
        assert not missing, f"{locale} nao traduz: {sorted(missing)}"
        assert not extra, f"{locale} tem chave que nao existe em {i18n.DEFAULT_LOCALE}: {sorted(extra)}"


def test_no_accents_in_any_value():
    """As texturas usam a fonte embutida do pygame e o resto do jogo ja
    escreve "CALIBRACAO"/"MUSICA" sem acento -- um acento aqui virava
    glifo faltando na tela."""
    for locale, table in i18n.CATALOG.items():
        for key, value in table.items():
            assert value.isascii(), f"{locale}/{key} tem caractere nao-ascii: {value!r}"


def test_translate_uses_the_active_locale():
    i18n.set_locale("en")
    assert i18n.translate("hub.campaign") == "[ CAMPAIGN ]"
    i18n.set_locale("pt_BR")
    assert i18n.translate("hub.campaign") == "[ CAMPANHA ]"


def test_unknown_locale_falls_back_to_the_default():
    """Um idioma digitado errado numa variavel de ambiente nao pode
    impedir o jogo de abrir."""
    assert i18n.set_locale("klingon") == i18n.DEFAULT_LOCALE
    assert i18n.translate("hub.campaign") == "[ CAMPANHA ]"


def test_missing_key_returns_the_key_itself():
    """Feio de proposito: uma chave nova sem traducao aparece na tela como
    `hub.novidade`, impossivel de nao notar -- e sem quebrar o jogo de quem
    so queria jogar."""
    assert i18n.translate("hub.nao_existe") == "hub.nao_existe"


def test_locale_comes_from_the_environment_when_unset(monkeypatch):
    monkeypatch.setenv(i18n.LOCALE_ENV_VAR, "en")
    assert i18n.resolve_locale(None) == "en"
    monkeypatch.setenv(i18n.LOCALE_ENV_VAR, "klingon")
    assert i18n.resolve_locale(None) == i18n.DEFAULT_LOCALE


def test_explicit_locale_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv(i18n.LOCALE_ENV_VAR, "en")
    assert i18n.resolve_locale("pt_BR") == "pt_BR"


def test_labels_for_prefix_strips_the_prefix():
    labels = i18n.labels_for_prefix("hub", locale="pt_BR")
    assert labels["campaign"] == "[ CAMPANHA ]"
    assert "hub.campaign" not in labels


def test_labels_keys_come_from_the_default_locale():
    """Uma traducao incompleta perde o TEXTO, nunca a ENTRADA -- o HUB nao
    pode ficar com uma categoria faltando por causa de idioma."""
    reference = i18n.labels_for_prefix("hub", locale="pt_BR")
    assert set(i18n.labels_for_prefix("hub", locale="en")) == set(reference)


# ------------------------------------------------- fiacao real no renderer


def test_hub_labels_follow_the_active_locale():
    """A prova de ponta a ponta: os rotulos que o `texture_bank` desenha
    saem do catalogo, resolvidos na CONSTRUCAO das texturas (nao no import
    do modulo, que congelaria o idioma do primeiro import)."""
    from hertzbeats.adapters.texture_bank import _hub_category_labels

    i18n.set_locale("en")
    assert _hub_category_labels()["campaign"] == "[ CAMPAIGN ]"
    i18n.set_locale("pt_BR")
    assert _hub_category_labels()["campaign"] == "[ CAMPANHA ]"


def test_hub_labels_cover_every_hub_category():
    """Mesma familia dos guardas de constante duplicada: se uma categoria
    nova entrar em `HUB_CATEGORIES` sem rotulo no catalogo, o HUB
    desenharia um item em branco."""
    from hertzbeats.adapters.texture_bank import _hub_category_labels
    from hertzbeats.bootstrap.hertz_game_loop import HUB_CATEGORIES

    assert set(_hub_category_labels()) == set(HUB_CATEGORIES)


def test_game_mode_labels_cover_both_modes():
    from hertzbeats.adapters.texture_bank import _game_mode_row_labels

    assert set(_game_mode_row_labels()) == {"defender", "lanes"}
