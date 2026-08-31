# -*- coding: utf-8 -*-
from utils.capture.engine_ids import (
    BACKGROUND_SCREENSHOT_ENGINES,
    PLUGIN_SCREENSHOT_ENGINES,
    SUPPORTED_SCREENSHOT_ENGINES,
    canonicalize_screenshot_engine,
    engines_for_ui_group,
    is_background_screenshot_engine,
    is_plugin_screenshot_engine,
    is_supported_screenshot_engine,
    iter_plugin_capture_display_candidates,
    iter_screenshot_engine_ui_groups,
    migrate_screenshot_engine,
    screenshot_engine_label,
    screenshot_engine_ui_group,
)


def test_native_and_plugin_engines_are_supported():
    assert is_supported_screenshot_engine("wgc")
    assert is_supported_screenshot_engine("DX.D3D11")
    assert is_supported_screenshot_engine("opengl.nox")
    assert is_supported_screenshot_engine("normal")
    assert is_supported_screenshot_engine("dx3")
    assert not is_supported_screenshot_engine("unknown")
    assert not is_supported_screenshot_engine("normal.wgc")
    assert not is_supported_screenshot_engine("dx.d3d12")


def test_plugin_engines_are_background_capable():
    for engine in PLUGIN_SCREENSHOT_ENGINES:
        assert is_plugin_screenshot_engine(engine)
        assert is_background_screenshot_engine(engine)
        assert engine in SUPPORTED_SCREENSHOT_ENGINES
        assert engine in BACKGROUND_SCREENSHOT_ENGINES


def test_plugin_gdi_does_not_steal_native_gdi():
    assert "gdi" not in PLUGIN_SCREENSHOT_ENGINES
    assert is_plugin_screenshot_engine("gdi") is False
    assert screenshot_engine_ui_group("gdi") == "原生"
    assert screenshot_engine_label("gdi") == "GDI"
    assert screenshot_engine_label("normal") == "正常"


def test_screenshot_engine_label_covers_plugin_modes():
    assert screenshot_engine_label("dx.d3d11") == "D3D11"
    assert screenshot_engine_label("opengl.nox") == "OpenGL"
    assert screenshot_engine_label("gdi2") == "GDI2"
    assert screenshot_engine_label("dx3") == "DX3"
    assert screenshot_engine_label("wgc") == "WGC"


def test_opengl_variants_hidden_from_ui_but_still_supported():
    assert "opengl" in PLUGIN_SCREENSHOT_ENGINES
    assert "opengl.nox" not in PLUGIN_SCREENSHOT_ENGINES
    assert "opengl.std" not in engines_for_ui_group("插件")
    assert canonicalize_screenshot_engine("opengl.nox") == "opengl"
    assert is_plugin_screenshot_engine("opengl.nox")
    assert iter_plugin_capture_display_candidates("opengl")[0] == "opengl"
    assert "opengl.nox" in iter_plugin_capture_display_candidates("opengl")


def test_dx_family_includes_dx3_not_d3d12():
    candidates = iter_plugin_capture_display_candidates("dx.d3d11")
    assert candidates[0] == "dx.d3d11"
    assert "dx3" in candidates
    assert "dx.d3d12" not in candidates


def test_migrate_legacy_op_engine_ids():
    assert migrate_screenshot_engine("normal.wgc") == "gdi2"
    assert migrate_screenshot_engine("normal.dxgi") == "gdi2"
    assert migrate_screenshot_engine("dx.d3d12") == "dx.d3d11"
    assert migrate_screenshot_engine("opengl.fi") == "opengl"
    assert migrate_screenshot_engine("dx.d3d11") == "dx.d3d11"
    assert migrate_screenshot_engine("wgc") == "wgc"


def test_screenshot_engine_ui_groups_native_and_plugin():
    groups = dict(iter_screenshot_engine_ui_groups())
    assert "原生" in groups and "插件" in groups
    assert "wgc" in groups["原生"]
    assert "normal" in groups["插件"]
    assert "dx.d3d11" in groups["插件"]
    assert "opengl" in groups["插件"]
    assert "normal.wgc" not in groups["插件"]
    assert "gdi" not in groups["插件"]
    background_groups = dict(iter_screenshot_engine_ui_groups(background_only=True))
    assert "gdi" not in background_groups.get("原生", ())
    assert engines_for_ui_group("插件") == PLUGIN_SCREENSHOT_ENGINES
    assert screenshot_engine_ui_group("dx.d3d11") == "插件"
    assert screenshot_engine_ui_group("normal") == "插件"
    assert screenshot_engine_ui_group("wgc") == "原生"
