# -*- coding: utf-8 -*-
"""截图引擎标识。原生引擎与插件 BindWindow display 共用同一套校验。"""

from __future__ import annotations

from typing import Iterable

NATIVE_SCREENSHOT_ENGINES = ("wgc", "printwindow", "gdi", "dxgi")

PLUGIN_SCREENSHOT_ENGINES = (
    "normal",
    "gdi2",
    "dx",
    "dx2",
    "dx3",
    "dx.d3d9",
    "dx.d3d10",
    "dx.d3d11",
    "opengl",
)

PLUGIN_SCREENSHOT_ENGINE_ALIASES = (
    "opengl.std",
    "opengl.nox",
    "opengl.es",
)

SUPPORTED_SCREENSHOT_ENGINES = (
    NATIVE_SCREENSHOT_ENGINES + PLUGIN_SCREENSHOT_ENGINES + PLUGIN_SCREENSHOT_ENGINE_ALIASES
)
BACKGROUND_SCREENSHOT_ENGINES = (
    ("wgc", "printwindow") + PLUGIN_SCREENSHOT_ENGINES + PLUGIN_SCREENSHOT_ENGINE_ALIASES
)

_PLUGIN_OPENGL_FAMILY = (
    "opengl",
    "opengl.std",
    "opengl.nox",
    "opengl.es",
)
_PLUGIN_DX_FAMILY = (
    "dx.d3d9",
    "dx.d3d10",
    "dx.d3d11",
    "dx",
    "dx2",
    "dx3",
)

_SCREENSHOT_ENGINE_LABELS = {
    "wgc": "WGC",
    "printwindow": "PrintWindow",
    "gdi": "GDI",
    "dxgi": "DXGI",
    "normal": "正常",
    "gdi2": "GDI2",
    "dx": "DX",
    "dx2": "DX2",
    "dx3": "DX3",
    "dx.d3d9": "D3D9",
    "dx.d3d10": "D3D10",
    "dx.d3d11": "D3D11",
    "opengl": "OpenGL",
    "opengl.std": "OpenGL",
    "opengl.nox": "OpenGL",
    "opengl.es": "OpenGL",
}

_LEGACY_ENGINE_MIGRATION = {
    "normal.wgc": "gdi2",
    "normal.dxgi": "gdi2",
    "dx.d3d12": "dx.d3d11",
    "opengl.fi": "opengl",
}

SCREENSHOT_ENGINE_UI_GROUPS = (
    ("原生", NATIVE_SCREENSHOT_ENGINES),
    ("插件", PLUGIN_SCREENSHOT_ENGINES),
)

_SUPPORTED_SET = frozenset(SUPPORTED_SCREENSHOT_ENGINES)
_PLUGIN_SET = frozenset(PLUGIN_SCREENSHOT_ENGINES + PLUGIN_SCREENSHOT_ENGINE_ALIASES)
_NATIVE_SET = frozenset(NATIVE_SCREENSHOT_ENGINES)
_BACKGROUND_SET = frozenset(BACKGROUND_SCREENSHOT_ENGINES)
_OPENGL_ALIAS_SET = frozenset(PLUGIN_SCREENSHOT_ENGINE_ALIASES)


def normalize_screenshot_engine(engine: object) -> str:
    return str(engine or "").strip().lower()


def canonicalize_screenshot_engine(engine: object) -> str:
    mode = normalize_screenshot_engine(engine)
    if mode in _OPENGL_ALIAS_SET or mode.startswith("opengl."):
        return "opengl"
    return mode


def migrate_screenshot_engine(engine: object) -> str:
    mode = normalize_screenshot_engine(engine)
    return _LEGACY_ENGINE_MIGRATION.get(mode, mode)


def is_supported_screenshot_engine(engine: object) -> bool:
    return normalize_screenshot_engine(engine) in _SUPPORTED_SET


def is_plugin_screenshot_engine(engine: object) -> bool:
    return normalize_screenshot_engine(engine) in _PLUGIN_SET


def is_native_screenshot_engine(engine: object) -> bool:
    return normalize_screenshot_engine(engine) in _NATIVE_SET


def is_background_screenshot_engine(engine: object) -> bool:
    return normalize_screenshot_engine(engine) in _BACKGROUND_SET


def screenshot_engine_label(engine: object) -> str:
    normalized = normalize_screenshot_engine(engine)
    return _SCREENSHOT_ENGINE_LABELS.get(normalized, normalized or "未知引擎")


def iter_supported_screenshot_engines() -> Iterable[str]:
    return SUPPORTED_SCREENSHOT_ENGINES


def iter_screenshot_engine_ui_groups(*, background_only: bool = False) -> Iterable[tuple[str, tuple[str, ...]]]:
    for title, engines in SCREENSHOT_ENGINE_UI_GROUPS:
        filtered = engines_for_ui_group(title, background_only=background_only)
        if filtered:
            yield title, filtered


def engines_for_ui_group(group_title: object, *, background_only: bool = False) -> tuple[str, ...]:
    title = str(group_title or "").strip()
    for group_name, engines in SCREENSHOT_ENGINE_UI_GROUPS:
        if group_name != title:
            continue
        if background_only:
            return tuple(engine for engine in engines if is_background_screenshot_engine(engine))
        return tuple(engines)
    return ()


def screenshot_engine_ui_group(engine: object) -> str:
    if is_plugin_screenshot_engine(engine):
        return "插件"
    if is_native_screenshot_engine(engine):
        return "原生"
    return "原生"


def iter_plugin_capture_display_candidates(display: object) -> tuple[str, ...]:
    mode = normalize_screenshot_engine(display)
    if not mode:
        return ()
    if mode in _PLUGIN_OPENGL_FAMILY or mode.startswith("opengl"):
        family = _PLUGIN_OPENGL_FAMILY
    elif mode in _PLUGIN_DX_FAMILY or mode.startswith("dx"):
        family = _PLUGIN_DX_FAMILY
    else:
        return (mode,)
    ordered = [mode]
    for item in family:
        if item not in ordered:
            ordered.append(item)
    return tuple(ordered)


# Thin aliases until Task 8 rewires imports across the dirty tree.
is_op_screenshot_engine = is_plugin_screenshot_engine
iter_op_capture_display_candidates = iter_plugin_capture_display_candidates
