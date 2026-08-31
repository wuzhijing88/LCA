# -*- coding: utf-8 -*-
from utils.window.window_binding_utils import (
    resolve_plugin_bind_hwnds,
    resolve_plugin_input_hwnd_for_display,
)


def test_resolve_plugin_bind_hwnds_defaults_input_to_display():
    assert resolve_plugin_bind_hwnds({"hwnd": 10}) == (10, 10)
    assert resolve_plugin_bind_hwnds(display_hwnd=10) == (10, 10)


def test_resolve_plugin_bind_hwnds_keeps_split_pair(monkeypatch):
    monkeypatch.setattr(
        "utils.window.window_binding_utils.is_window_alive",
        lambda hwnd: int(hwnd) in {10, 20},
    )
    assert resolve_plugin_bind_hwnds({"hwnd": 10, "input_hwnd": 20}) == (10, 20)
    assert resolve_plugin_bind_hwnds({"display_hwnd": 10, "input_hwnd": 20}) == (10, 20)


def test_resolve_plugin_bind_hwnds_falls_back_when_input_dead(monkeypatch):
    monkeypatch.setattr(
        "utils.window.window_binding_utils.is_window_alive",
        lambda hwnd: int(hwnd) == 10,
    )
    assert resolve_plugin_bind_hwnds({"hwnd": 10, "input_hwnd": 20}) == (10, 10)


def test_resolve_plugin_input_hwnd_for_display_reads_bound_windows(monkeypatch):
    monkeypatch.setattr(
        "utils.window.window_binding_utils.is_window_alive",
        lambda hwnd: True,
    )
    config = {
        "bound_windows": [
            {"hwnd": 11, "input_hwnd": 22, "enabled": True},
            {"hwnd": 33, "enabled": True},
        ]
    }
    assert resolve_plugin_input_hwnd_for_display(11, config=config) == 22
    assert resolve_plugin_input_hwnd_for_display(33, config=config) == 33
    assert resolve_plugin_input_hwnd_for_display(99, config=config) == 99
