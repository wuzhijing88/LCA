# -*- coding: utf-8 -*-
"""Small, explicit debugger pane for the custom script editor."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget


class ScriptDebugPanel(QWidget):
    start_requested = Signal()
    pause_requested = Signal()
    continue_requested = Signal()
    step_requested = Signal()
    stop_requested = Signal()
    breakpoint_requested = Signal(int)

    def __init__(self, editor=None, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.setObjectName("scriptDebugPanel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 2, 4, 2)
        outer.setSpacing(4)
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        self.start_button = self._button("运行", self.start_requested)
        self.pause_button = self._button("暂停", self.pause_requested)
        self.continue_button = self._button("继续", self.continue_requested)
        self.step_button = self._button("单步", self.step_requested)
        self.stop_button = self._button("停止", self.stop_requested)
        for button in (self.start_button, self.pause_button, self.continue_button, self.step_button, self.stop_button): controls.addWidget(button)
        self.breakpoint_button = QPushButton("断点")
        self.breakpoint_button.setObjectName("scriptDebugButton")
        self.breakpoint_button.setAutoDefault(False)
        self.breakpoint_button.setFixedHeight(26)
        self.breakpoint_button.setFixedWidth(50)
        self.breakpoint_button.setCheckable(True)
        self.breakpoint_button.setToolTip("为当前行设置或清除断点")
        self.breakpoint_button.clicked.connect(self._toggle_current_breakpoint)
        controls.addWidget(self.breakpoint_button)
        controls.addStretch(1)
        outer.addLayout(controls)
        # 变量监视：只在暂停时显示；每行一个 名字 = repr，完整内容放进 tooltip。
        self._variables_view = QPlainTextEdit()
        self._variables_view.setObjectName("scriptDebugVariables")
        self._variables_view.setReadOnly(True)
        self._variables_view.setMaximumHeight(120)
        self._variables_view.setPlaceholderText("暂停时显示变量")
        self._variables_view.setVisible(False)
        outer.addWidget(self._variables_view)
        self.setMinimumHeight(30)
        self.set_running(False)

    def _button(self, text, signal):
        button = QPushButton(text); button.setObjectName("scriptDebugButton"); button.setAutoDefault(False); button.setFixedSize(50, 26); button.clicked.connect(signal.emit); return button

    def set_breakpoint_state(self, enabled: bool) -> None:
        self.breakpoint_button.blockSignals(True)
        self.breakpoint_button.setChecked(bool(enabled))
        self.breakpoint_button.setText("清除" if enabled else "断点")
        self.breakpoint_button.blockSignals(False)

    def _toggle_current_breakpoint(self):
        if self.editor is not None:
            self.breakpoint_requested.emit(int(self.editor.textCursor().blockNumber()) + 1)

    def set_running(self, running: bool):
        running = bool(running)
        self.start_button.setEnabled(not running)
        self.start_button.setText("运行中" if running else "运行")
        self.pause_button.setEnabled(running)
        self.continue_button.setEnabled(running)
        self.step_button.setEnabled(running)
        self.stop_button.setEnabled(running)

    def set_stopping(self) -> None:
        """停止请求已发出，但工作线程尚未确认结束。"""
        self.start_button.setEnabled(False)
        self.start_button.setText("停止中")
        for button in (self.pause_button, self.continue_button, self.step_button, self.stop_button):
            button.setEnabled(False)

    def clear(self):
        self.set_running(False)
        self._set_variables(None)

    def update_event(self, event: str, payload: dict):
        if event == "started":
            self.set_running(True)
            self._set_variables(None)
        elif event == "break":
            self._set_variables(payload.get("variables") if isinstance(payload, dict) else None)
        elif event == "continued":
            self._set_variables(None)
        elif event == "stopped":
            self.set_stopping()
            self._set_variables(None)
        elif event == "finished":
            self.set_running(False)
            self._set_variables(None)

    def _set_variables(self, variables) -> None:
        view = getattr(self, "_variables_view", None)
        if view is None:
            return
        if not variables:
            view.clear()
            view.setToolTip("")
            view.setVisible(False)
            return
        text = "\n".join(f"{name} = {value}" for name, value in variables.items())
        view.setPlainText(text)
        view.setToolTip(text)
        view.setVisible(True)
