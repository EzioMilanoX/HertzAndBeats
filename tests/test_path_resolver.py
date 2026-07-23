"""utils.path_resolver: recurso empacotado (get_resource_path, sys._MEIPASS) vs. dado gravavel (get_writable_data_path, pasta do .exe) num build congelado."""
import os
import sys

import pytest

from utils.path_resolver import get_resource_path, get_writable_data_path

# `_PROJECT_ROOT` e' privado (calculado uma unica vez no import a partir
# de `__file__`) -- reimportado aqui so' pra comparar contra o valor
# esperado, nao pra testar o modulo por fora do seu proprio calculo.
from utils import path_resolver as _path_resolver_module


def test_get_resource_path_returns_an_absolute_input_unchanged(tmp_path):
    absolute = str(tmp_path / "already_absolute.json")
    assert get_resource_path(absolute) == absolute


def test_get_writable_data_path_returns_an_absolute_input_unchanged(tmp_path):
    absolute = str(tmp_path / "already_absolute.wav")
    assert get_writable_data_path(absolute) == absolute


def test_get_resource_path_resolves_against_the_project_root_when_not_frozen():
    assert not hasattr(sys, "frozen")  # premissa do teste -- ambiente headless nunca esta congelado
    resolved = get_resource_path("data/stages/stages.json")
    assert resolved == os.path.join(_path_resolver_module._PROJECT_ROOT, "data/stages/stages.json")
    assert os.path.isfile(resolved)  # a raiz calculada bate com o repo de verdade, nao so um valor arbitrario


def test_get_writable_data_path_resolves_against_the_project_root_when_not_frozen():
    resolved = get_writable_data_path("data/sfx/cannon.wav")
    assert resolved == os.path.join(_path_resolver_module._PROJECT_ROOT, "data/sfx/cannon.wav")


def test_get_resource_path_uses_meipass_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    resolved = get_resource_path("assets/icon.png")
    assert resolved == os.path.join(str(tmp_path), "assets/icon.png")


def test_get_writable_data_path_uses_the_executable_directory_when_frozen(monkeypatch, tmp_path):
    """A raiz gravavel NUNCA e' `sys._MEIPASS` (apagado ao sair do
    processo num build --onefile) -- e' a pasta que CONTEM o proprio
    `.exe`, a mesma pasta que sobrevive no disco do jogador entre uma
    execucao e a proxima."""
    fake_exe = tmp_path / "dist" / "HertzAndBeats" / "HertzAndBeats.exe"
    fake_exe.parent.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "meipass_temp"), raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe), raising=False)

    resolved = get_writable_data_path("data/sfx/cannon.wav")
    assert resolved == os.path.join(str(fake_exe.parent), "data/sfx/cannon.wav")
    assert "meipass_temp" not in resolved  # nunca a pasta de extracao temporaria


def test_resource_and_writable_paths_diverge_only_once_frozen(monkeypatch, tmp_path):
    """Fora de um build congelado, as 2 funcoes concordam (mesma raiz de
    projeto) -- so' divergem quando `sys.frozen` existe, exatamente o
    cenario que motivou ter 2 funcoes em vez de uma so'."""
    assert get_resource_path("data/sfx/cannon.wav") == get_writable_data_path("data/sfx/cannon.wav")

    fake_exe = tmp_path / "HertzAndBeats.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "meipass"), raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe), raising=False)

    assert get_resource_path("data/sfx/cannon.wav") != get_writable_data_path("data/sfx/cannon.wav")
