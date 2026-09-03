# -*- coding: utf-8 -*-
"""在 UI 线程显示插件试绑结果，避免后台线程直接弹窗。"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from utils.plugin.bind_probe import (
    plugin_bind_probe_summary_text,
    plugin_bind_probe_warning_text,
    start_bound_windows_plugin_bind_probe,
    start_plugin_window_bind_probe,
)
from utils.window.hwnd_utils import as_hwnd


class PluginBindProbeBridge(QObject):
    finished = Signal(object)
    batch_finished = Signal(object)


def _show_plugin_bind_probe_warning(widget, text: str) -> None:
    message = str(text or "").strip()
    if not message:
        return
    try:
        if hasattr(widget, "isVisible") and not widget.isVisible():
            return
    except RuntimeError:
        return
    QMessageBox.warning(widget, "插件绑定提示", message)


def _bridge_for(widget, attr: str) -> PluginBindProbeBridge:
    bridge = getattr(widget, attr, None)
    if bridge is None:
        bridge = PluginBindProbeBridge(widget)
        setattr(widget, attr, bridge)
    return bridge


def _reconnect(bridge: PluginBindProbeBridge, signal_name: str, slot) -> None:
    """同一 bridge 只保留最新一个槽，避免旧回调重复触发。"""
    signal = getattr(bridge, signal_name)
    slot_attr = f"_{signal_name}_slot"
    previous = getattr(bridge, slot_attr, None)
    if previous is not None:
        try:
            signal.disconnect(previous)
        except (TypeError, RuntimeError):
            pass
    signal.connect(slot)
    setattr(bridge, slot_attr, slot)


def _call_quietly(callback, payload) -> None:
    if callback is None:
        return
    try:
        callback(payload)
    except Exception:
        pass


def schedule_dialog_plugin_bind_probe(
    widget,
    hwnd,
    config,
    window_info,
    window_title,
    *,
    on_done=None,
) -> None:
    """新加入一个绑定窗口时试绑；失败弹一次提示，随后在 UI 线程调用 on_done(result)。"""
    target = as_hwnd(hwnd)
    if not target:
        return
    bridge = _bridge_for(widget, "_plugin_bind_probe_bridge")

    def _on_ui_thread(result) -> None:
        if result is not None and not result.ok:
            _show_plugin_bind_probe_warning(widget, plugin_bind_probe_warning_text(window_title, result))
        _call_quietly(on_done, result)

    _reconnect(bridge, "finished", _on_ui_thread)
    widget._plugin_bind_probe_thread = start_plugin_window_bind_probe(
        target,
        config,
        window_info=window_info,
        window_title=window_title,
        on_finished=bridge.finished.emit,
    )


def schedule_bound_windows_plugin_bind_probe(
    widget,
    windows,
    config,
    on_done=None,
    *,
    notify: bool = True,
    should_stop=None,
) -> bool:
    """切换到插件或修改插件参数后，对整份绑定列表重新试绑。

    notify=True 时失败合并成一次弹窗；设置页里边改边试用 notify=False，只把结果回给 on_done(results)。
    should_stop() 为真时后台停止且不再打戳、不回调（取消对话框或参数又变了）。返回是否真的启动了试绑。
    """
    bridge = _bridge_for(widget, "_plugin_bind_batch_bridge")

    def _on_ui_thread(results) -> None:
        results = results or []
        if notify:
            summary = plugin_bind_probe_summary_text(results)
            if summary:
                _show_plugin_bind_probe_warning(widget, summary)
        _call_quietly(on_done, results)

    _reconnect(bridge, "batch_finished", _on_ui_thread)
    thread = start_bound_windows_plugin_bind_probe(
        windows,
        config,
        on_finished=bridge.batch_finished.emit,
        should_stop=should_stop,
    )
    widget._plugin_bind_batch_thread = thread
    return thread is not None
