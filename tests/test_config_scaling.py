"""fit_config_to_display: a geometria inteira encolhe junto quando o monitor e menor que a janela."""
from hertzbeats.config import fit_config_to_display

from tests.conftest import make_config


def test_large_display_keeps_config_untouched(tmp_path):
    config = make_config(tmp_path / "x.json")
    fitted = fit_config_to_display(config, 1920, 1080)
    assert fitted is config  # 960x960 cabe em 1080p (1080 - 90 > 960)


def test_small_display_scales_window_and_geometry_uniformly(tmp_path):
    config = make_config(tmp_path / "x.json")
    fitted = fit_config_to_display(config, 1366, 768)

    usable = 768 - 90
    assert fitted.window_width == usable
    assert fitted.window_height == usable

    scale = usable / 960.0
    assert abs(fitted.spawn_radius - config.spawn_radius * scale) < 1e-6
    assert abs(fitted.core_half_extent - config.core_half_extent * scale) < 1e-6
    for name, half in config.threat_half_extents.items():
        assert abs(fitted.threat_half_extents[name] - half * scale) < 1e-6

    # proporcoes preservadas: a arena continua coerente em qualquer escala
    assert abs(
        fitted.spawn_radius / fitted.window_width - config.spawn_radius / config.window_width
    ) < 1e-9

    # afinacao TEMPORAL intocada: julgamento/aproximacao nao mudam com a tela
    assert fitted.approach_seconds == config.approach_seconds
    assert fitted.perfect_window_seconds == config.perfect_window_seconds
    assert fitted.max_health == config.max_health


def test_narrow_display_is_limited_by_width(tmp_path):
    config = make_config(tmp_path / "x.json")
    fitted = fit_config_to_display(config, 700, 2000)
    assert fitted.window_width == 700 - 20
