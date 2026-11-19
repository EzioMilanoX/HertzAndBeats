"""Durabilidade dos 3 arquivos locais graváveis + guarda das constantes duplicadas.

Os dois assuntos moram junto porque sao a mesma especie de falha: um
estrago que NENHUM teste de logica pega, porque nada levanta excecao --
o save simplesmente amanhece vazio, ou o menu simplesmente desenha a
categoria errada. Sao bugs que so aparecem pro jogador.
"""
import json

import pytest

from hertzbeats import player_progress, player_stats, user_settings
from utils.atomic_json import write_json_atomically


# --------------------------------------------------------- escrita atomica


def test_writes_the_payload(tmp_path):
    destination = tmp_path / "save.json"
    write_json_atomically(destination, {"a": 1})
    assert json.loads(destination.read_text(encoding="utf-8")) == {"a": 1}


def test_creates_missing_parent_directories(tmp_path):
    destination = tmp_path / "config" / "nested" / "save.json"
    write_json_atomically(destination, {"a": 1})
    assert destination.exists()


def test_a_crash_mid_write_leaves_the_previous_save_intact(tmp_path, monkeypatch):
    """O teste que justifica o modulo inteiro: com `open(destino, "w")` o
    arquivo era truncado ANTES do conteudo novo existir, entao um crash
    aqui deixava o save existente e vazio -- e todo carregador do jogo
    trata JSON invalido como "comeca do zero", apagando o progresso do
    jogador em silencio."""
    destination = tmp_path / "save.json"
    write_json_atomically(destination, {"progresso": "importante"})

    def explode(*args, **kwargs):
        raise RuntimeError("crash no meio da serializacao")

    monkeypatch.setattr("utils.atomic_json.json.dump", explode)
    with pytest.raises(RuntimeError):
        write_json_atomically(destination, {"progresso": "novo"})

    assert json.loads(destination.read_text(encoding="utf-8")) == {"progresso": "importante"}


def test_a_failed_write_leaves_no_temporary_file_behind(tmp_path, monkeypatch):
    destination = tmp_path / "save.json"

    def explode(*args, **kwargs):
        raise RuntimeError("falha")

    monkeypatch.setattr("utils.atomic_json.json.dump", explode)
    with pytest.raises(RuntimeError):
        write_json_atomically(destination, {"a": 1})

    assert list(tmp_path.iterdir()) == [], "um .tmp orfao ficaria pra tras a cada crash"


def test_temporary_file_shares_the_destination_directory(tmp_path, monkeypatch):
    """`os.replace` so e' atomico dentro do MESMO sistema de arquivos: um
    temporario em %TEMP% (outro volume, caso comum no Windows) perderia a
    atomicidade exatamente onde ela mais importa."""
    destination = tmp_path / "save.json"
    observed = []
    real_open = open

    def spy(path, *args, **kwargs):
        observed.append(str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", spy)
    write_json_atomically(destination, {"a": 1})
    temporaries = [p for p in observed if p.endswith(".tmp")]
    assert temporaries, "esperava um arquivo temporario"
    for path in temporaries:
        assert str(tmp_path) in path


# ------------------------------- os 3 saves reais sobrevivem a um crash


@pytest.mark.parametrize(
    "save_call",
    [
        pytest.param(
            lambda path: player_progress.record_stage_cleared(
                "fase_x", ["holds"], rank="A", path=path
            ),
            id="player_progress",
        ),
        pytest.param(
            lambda path: player_stats.record_match_stats(
                perfect_count=1, shots_fired=2, playtime_seconds=3.0, path=path
            ),
            id="player_stats",
        ),
        pytest.param(
            lambda path: user_settings.save_user_latency(0.12, path=path),
            id="user_settings",
        ),
    ],
)
def test_real_saves_survive_a_crash_mid_write(save_call, tmp_path, monkeypatch):
    """Cada um dos 3 arquivos gravaveis passa pelo helper atomico -- se
    algum voltasse a escrever direto, este teste pegaria."""
    path = str(tmp_path / "arquivo.json")
    save_call(path)  # grava uma vez, de verdade
    before = (tmp_path / "arquivo.json").read_text(encoding="utf-8")
    assert before, "o primeiro save precisa ter escrito algo"

    def explode(*args, **kwargs):
        raise RuntimeError("crash")

    monkeypatch.setattr("utils.atomic_json.json.dump", explode)
    with pytest.raises(RuntimeError):
        save_call(path)

    assert (tmp_path / "arquivo.json").read_text(encoding="utf-8") == before


# ------------------------------------------- constantes duplicadas de proposito


def test_hub_categories_copies_stay_in_sync():
    """`HBPygameRenderer` mantem uma copia da tupla de categorias do HUB
    (o adapter nao importa o bootstrap -- seria o sentido inverso de
    dependencia). O proprio docstring da copia registra que ela JA ficou
    pra tras uma vez, desenhando o HUB errado. Duplicar segue sendo a
    decisao de arquitetura certa; o que faltava era o guarda."""
    from hertzbeats.adapters.hb_pygame_renderer import _HUB_CATEGORIES
    from hertzbeats.bootstrap.hertz_game_loop import HUB_CATEGORIES

    assert _HUB_CATEGORIES == HUB_CATEGORIES


def test_preflight_special_row_copies_stay_in_sync():
    """Mesma familia: os 3 literais das linhas especiais do Pre-Voo (as 2
    de multipla escolha e o botao de Acao), que o renderer desenha sem
    quadrado de marcar. Divergir aqui poe um checkbox no botao de
    Iniciar Fase, ou tira o dele de um modifier de verdade."""
    from hertzbeats.adapters import hb_pygame_renderer as renderer
    from hertzbeats.bootstrap import hertz_game_loop as loop

    assert renderer._GAME_MODE_ROW == loop.GAME_MODE_ROW
    assert renderer._HEAVY_MECHANIC_ROW == loop.HEAVY_MECHANIC_ROW
    assert renderer._START_ROW == loop.START_ROW
