"""scratch_energy tem 3 fontes independentes (mouse/roda/teclas alternadas) -- combinadas por max()."""
import pygame
import pytest

from hertzbeats.adapters.hb_pygame_input_provider import (
    HBPygameInputProvider,
    advance_alternating_energy,
    apply_energy_pulse,
)


def test_energy_pulse_saturates_at_one():
    assert apply_energy_pulse(0.0, gained=2.0, decay=0.0) == 1.0


def test_energy_pulse_decays_and_floors_at_zero():
    result = apply_energy_pulse(0.2, gained=0.0, decay=0.5)
    assert result == 0.0  # nao vai negativo


def test_energy_pulse_combines_gain_and_decay_in_the_same_call():
    result = apply_energy_pulse(0.3, gained=0.4, decay=0.2)
    assert abs(result - 0.5) < 1e-9


def test_alternating_energy_ignores_the_same_side_repeated():
    energy, side = advance_alternating_energy(
        0.0, last_side=None, left_pressed=True, right_pressed=False,
        energy_on_switch=1.0, decay=0.0,
    )
    assert side == "left"
    # pressiona ESQUERDA de novo (mesmo lado): nao e uma alternancia
    energy, side = advance_alternating_energy(
        energy, last_side=side, left_pressed=True, right_pressed=False,
        energy_on_switch=1.0, decay=0.0,
    )
    assert energy == 0.0  # so o decay (0.0) aplicou, sem novo pulso


def test_alternating_energy_spikes_on_a_genuine_switch():
    energy, side = advance_alternating_energy(
        0.0, last_side=None, left_pressed=True, right_pressed=False,
        energy_on_switch=1.0, decay=0.1,
    )
    assert side == "left"
    energy, side = advance_alternating_energy(
        energy, last_side=side, left_pressed=False, right_pressed=True,
        energy_on_switch=1.0, decay=0.1,
    )
    assert side == "right"
    assert abs(energy - 0.9) < 1e-9  # 1.0 (troca valida) - 0.1 (decay)


def test_alternating_energy_decays_without_any_press():
    energy, side = advance_alternating_energy(
        0.6, last_side="left", left_pressed=False, right_pressed=False,
        energy_on_switch=1.0, decay=0.25,
    )
    assert abs(energy - 0.35) < 1e-9
    assert side == "left"  # ultimo lado nao muda sem um novo aperto


@pytest.fixture
def hb_input_provider(tmp_path):
    if not pygame.display.get_init():
        pygame.display.init()
    bindings_path = tmp_path / "bindings.json"
    bindings_path.write_text(
        '{"scratch_left": "KEY_Z", "scratch_right": "KEY_X", "fire": "MOUSE_LEFT"}',
        encoding="utf-8",
    )
    provider = HBPygameInputProvider()
    provider.load_bindings(str(bindings_path))
    provider.configure_aim_origin(0.0, 0.0)
    return provider


def test_real_provider_polls_without_crashing_and_starts_at_zero_energy(hb_input_provider):
    hb_input_provider.poll()  # nao deve levantar mesmo sem nenhum input real
    assert hb_input_provider.get_axis("scratch_energy") == 0.0
    hb_input_provider.poll()
    assert hb_input_provider.get_axis("scratch_energy") == 0.0
