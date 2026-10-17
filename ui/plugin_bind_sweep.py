# -*- coding: utf-8 -*-
"""插件模式绑定工具：选窗后依次试参，成功则填入执行模式页，全部失败则绑定失败。"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from utils.plugin.bind_sweep import (
    PluginBindCandidate,
    PluginBindSweepResult,
    iter_plugin_bind_sweep_candidates,
    plugin_bind_candidate_from_config,
    plugin_bind_candidate_label,
    sweep_plugin_window_bind,
)
from utils.window.hwnd_utils import as_hwnd

logger = logging.getLogger(__name__)


class PluginBindSweepBridge(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)


class PluginBindSweepDialog(QDialog):
    def __init__(self, parent, total: int):
        super().__init__(parent)
        self.setObjectName("pluginBindSweepDialog")
        self.setWindowTitle("绑定窗口")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(420)
        self._stop = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        self._label = QLabel("正在测试绑定参数…")
        self._label.setObjectName("plugin_bind_sweep_label")
        self._label.setWordWrap(True)
        layout.addWidget(self._label)
        self._bar = QProgressBar(self)
        self._bar.setObjectName("plugin_bind_sweep_bar")
        self._bar.setRange(0, max(1, int(total or 0)))
        self._bar.setValue(0)
        layout.addWidget(self._bar)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消", self)
        cancel.setObjectName("plugin_bind_sweep_cancel_button")
        cancel.clicked.connect(self._on_cancel)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def set_stop_event(self, stop: threading.Event) -> None:
        self._stop = stop

    def set_progress(self, current: int, total: int, text: str) -> None:
        if total > 0:
            self._bar.setRange(0, int(total))
        self._bar.setValue(max(0, int(current)))
        self._label.setText(str(text or "").strip() or "正在测试绑定参数…")

    def _on_cancel(self) -> None:
        self._request_stop()
        self._label.setText("正在停止绑定…")

    def _request_stop(self) -> None:
        stop = self._stop
        if stop is not None:
            stop.set()

    def closeEvent(self, event) -> None:
        self._request_stop()
        super().closeEvent(event)


def _combo_set_data(combo, value) -> None:
    index = combo.findData(value)
    if index < 0:
        raise ValueError(f"绑定参数不在当前选项中: {value!r}")
    combo.setCurrentIndex(index)


def _require_combo_data(combo, value, name: str) -> None:
    actual = combo.currentData()
    if actual != value:
        raise ValueError(f"{name}未更新为 {value!r}，当前为 {actual!r}")


def _store_winner_in_config(widget, winner: PluginBindCandidate) -> None:
    config = getattr(widget, "current_config", None)
    if not isinstance(config, dict):
        return
    config["plugin_bind_kind"] = winner.kind
    config["plugin_mouse"] = winner.mouse
    config["plugin_keypad"] = winner.keypad
    config["plugin_bind_mode"] = winner.mode
    config["screenshot_engine"] = winner.display
    config["plugin_input_display"] = winner.display
    config["plugin_input_display_follow"] = True


def apply_plugin_bind_sweep_winner(widget, winner: PluginBindCandidate) -> None:
    """把探测到的参数写进执行模式页下拉框，并同步到对话框配置副本。"""
    widget._plugin_bind_params_ignore_edits = True
    try:
        previous_kind = getattr(widget, "_plugin_bind_kind_active", None)
        if (
            previous_kind
            and previous_kind != winner.kind
            and hasattr(widget, "_remember_plugin_bind_kind_values")
        ):
            widget._remember_plugin_bind_kind_values(previous_kind)

        kind_combo = widget.plugin_bind_kind_combo
        kind_combo.blockSignals(True)
        try:
            _combo_set_data(kind_combo, winner.kind)
        finally:
            kind_combo.blockSignals(False)
        widget._plugin_bind_kind_active = winner.kind

        if not hasattr(widget, "_refresh_plugin_bind_param_combos"):
            raise ValueError("执行模式页尚未初始化插件参数")
        widget._refresh_plugin_bind_param_combos(
            preferred_mouse=winner.mouse,
            preferred_keypad=winner.keypad,
            preferred_display=winner.display,
            preferred_mode=winner.mode,
            preferred_shot=winner.display,
        )
        if hasattr(widget, "plugin_input_display_follow_check"):
            widget.plugin_input_display_follow_check.setChecked(True)
        if hasattr(widget, "_sync_plugin_input_display_follow"):
            widget._sync_plugin_input_display_follow()
        if hasattr(widget, "_remember_plugin_bind_kind_values"):
            widget._remember_plugin_bind_kind_values(winner.kind)

        _require_combo_data(widget.plugin_bind_kind_combo, winner.kind, "绑定方式")
        _require_combo_data(widget.plugin_screenshot_engine_combo, winner.display, "截图引擎")
        _require_combo_data(widget.plugin_mouse_combo, winner.mouse, "鼠标模式")
        _require_combo_data(widget.plugin_keypad_combo, winner.keypad, "键盘模式")
        _require_combo_data(widget.plugin_bind_mode_combo, winner.mode, "绑定模式")
        _store_winner_in_config(widget, winner)
        logger.info("已将绑定参数写入执行模式：%s", plugin_bind_candidate_label(winner))
    finally:
        widget._plugin_bind_params_ignore_edits = False
    if hasattr(widget, "_persist_plugin_bind_live_settings"):
        widget._persist_plugin_bind_live_settings(include_params=True)


def stop_settings_plugin_bind_sweep(widget) -> None:
    stop = getattr(widget, "_plugin_bind_sweep_stop", None)
    if stop is not None:
        stop.set()
    dialog = getattr(widget, "_plugin_bind_sweep_dialog", None)
    if dialog is not None:
        widget._plugin_bind_sweep_dialog = None
        try:
            dialog.close()
        except RuntimeError:
            pass
        try:
            dialog.deleteLater()
        except RuntimeError:
            pass
    bridge = getattr(widget, "_plugin_bind_sweep_bridge", None)
    if bridge is None:
        return
    for name in ("progress", "finished"):
        signal = getattr(bridge, name)
        try:
            signal.disconnect()
        except (TypeError, RuntimeError):
            pass


def start_picker_plugin_bind_sweep(
    widget,
    hwnd,
    title: str = "",
    *,
    on_finished: Optional[Callable[[PluginBindSweepResult], None]] = None,
    user_params_only: bool = False,
) -> bool:
    """绑定工具选窗后启动试参。已有探测在跑时不再开第二次。"""
    running = getattr(widget, "_plugin_bind_sweep_thread", None)
    if running is not None and running.is_alive():
        return False
    target = as_hwnd(hwnd)
    try:
        config = widget.get_settings()
    except Exception as exc:
        result = PluginBindSweepResult(False, False, None, 0, 0, f"读取当前插件参数失败：{exc}")
        if on_finished is not None:
            on_finished(result)
        return False

    extra_candidates = None
    if user_params_only:
        current = plugin_bind_candidate_from_config(config)
        if current is None:
            result = PluginBindSweepResult(False, False, None, 0, 0, "当前插件参数无法用于绑定")
            if on_finished is not None:
                on_finished(result)
            return False
        extra_candidates = (current,)
        total = 1
    else:
        total = len(iter_plugin_bind_sweep_candidates(config))
    stop = threading.Event()
    widget._plugin_bind_sweep_stop = stop
    if hasattr(widget, "_remember_plugin_probe_stamps"):
        widget._remember_plugin_probe_stamps()

    dialog = PluginBindSweepDialog(widget, total)
    dialog.set_stop_event(stop)
    widget._plugin_bind_sweep_dialog = dialog

    bridge = getattr(widget, "_plugin_bind_sweep_bridge", None)
    if bridge is None:
        bridge = PluginBindSweepBridge(widget)
        widget._plugin_bind_sweep_bridge = bridge
    try:
        bridge.progress.disconnect()
    except (TypeError, RuntimeError):
        pass
    try:
        bridge.finished.disconnect()
    except (TypeError, RuntimeError):
        pass

    def _on_progress(current: int, total_count: int, text: str) -> None:
        current_dialog = getattr(widget, "_plugin_bind_sweep_dialog", None)
        if current_dialog is None:
            return
        try:
            current_dialog.set_progress(current, total_count, text)
        except RuntimeError:
            return

    def _on_ui_finished(result) -> None:
        stop_settings_plugin_bind_sweep(widget)
        try:
            hidden = not widget.isVisible()
        except RuntimeError:
            return
        if not isinstance(result, PluginBindSweepResult):
            return
        if hidden:
            try:
                widget.show()
            except RuntimeError:
                return
        if on_finished is None:
            return
        try:
            on_finished(result)
        except Exception:
            logger.debug("绑定工具试参完成回调异常", exc_info=True)

    bridge.progress.connect(_on_progress)
    bridge.finished.connect(_on_ui_finished)

    def _worker() -> None:
        def _progress(index: int, total_count: int, candidate: PluginBindCandidate) -> None:
            bridge.progress.emit(
                int(index),
                int(total_count),
                f"正在测试 {index}/{total_count}：{plugin_bind_candidate_label(candidate)}",
            )

        try:
            result = sweep_plugin_window_bind(
                target,
                config,
                should_stop=stop.is_set,
                on_progress=_progress,
                candidates=extra_candidates,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("绑定工具试参线程异常", exc_info=True)
            result = PluginBindSweepResult(
                False, False, None, 0, total, f"{exc.__class__.__name__}: {exc}"
            )
        if stop.is_set() and not result.ok:
            result = PluginBindSweepResult(
                False,
                True,
                None,
                result.tried,
                result.total,
                "已取消绑定",
            )
        bridge.finished.emit(result)

    worker = threading.Thread(target=_worker, name="plugin-bind-sweep", daemon=True)
    widget._plugin_bind_sweep_thread = worker
    worker.start()
    dialog.show()
    return True
