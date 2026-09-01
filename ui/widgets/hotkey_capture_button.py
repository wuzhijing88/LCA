from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QPushButton

from app_core.hotkey_spec import (
    CANCEL_HOTKEY,
    display_hotkey,
    is_cancel_hotkey,
    normalize_hotkey,
    set_hotkey_capture_active,
    spec_from_qt_key,
    spec_from_qt_mouse,
)


class HotkeyCaptureButton(QPushButton):
    """点击后监听下一枚按键/组合键；Esc 关闭监听且不能被绑定。"""

    changed = Signal(str)

    def __init__(self, value: str = "", parent=None, *, except_hotkey: str = CANCEL_HOTKEY):
        super().__init__(parent)
        self.setObjectName("HotkeyCaptureButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # 不要 setFixedHeight：全局 QPushButton padding 上下各 6px，固定 28 会裁掉底部圆角
        self.setMinimumHeight(32)
        self.setMinimumWidth(140)
        self._value = normalize_hotkey(value)
        self._except_hotkey = normalize_hotkey(except_hotkey) or CANCEL_HOTKEY
        self._listening = False
        self._refresh_text()
        self.clicked.connect(self._on_clicked)

    def key_value(self) -> str:
        return self._value

    def currentData(self):
        return self._value

    def currentText(self) -> str:
        return display_hotkey(self._value)

    def set_except_hotkey(self, value: str) -> None:
        self._except_hotkey = normalize_hotkey(value) or CANCEL_HOTKEY

    def set_key(self, value: str, *, emit: bool = False) -> None:
        spec = normalize_hotkey(value)
        if spec == self._value:
            self._refresh_text()
            return
        self._value = spec
        self._refresh_text()
        if emit:
            self.changed.emit(self._value)

    def is_listening(self) -> bool:
        return self._listening

    def stop_listening(self, *, restore: bool = True) -> None:
        if not self._listening:
            return
        self._listening = False
        set_hotkey_capture_active(False)
        try:
            self.releaseKeyboard()
        except Exception:
            pass
        self.setProperty("listening", False)
        self.style().unpolish(self)
        self.style().polish(self)
        if restore:
            self._refresh_text()

    def start_listening(self) -> None:
        if self._listening:
            return
        parent = self.parent()
        if parent is not None and hasattr(parent, "_stop_other_hotkey_captures"):
            parent._stop_other_hotkey_captures(self)
        self._listening = True
        set_hotkey_capture_active(True)
        self.setProperty("listening", True)
        self.style().unpolish(self)
        self.style().polish(self)
        self.setText("按下快捷键…")
        self.setToolTip("按下要绑定的按键。Esc 关闭监听（该键不能作为快捷键）。")
        self.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.grabKeyboard()

    def _on_clicked(self) -> None:
        if self._listening:
            return
        self.start_listening()

    def _refresh_text(self) -> None:
        self.setText(display_hotkey(self._value) if self._value else "点击设置")
        self.setToolTip(
            f"当前：{display_hotkey(self._value)}\n"
            "点击后按下任意键或组合键绑定。Esc 关闭监听，该键除外。"
        )

    def _commit(self, spec: str) -> None:
        spec = normalize_hotkey(spec)
        if not spec:
            return
        if is_cancel_hotkey(spec) or spec == self._except_hotkey:
            self.stop_listening(restore=True)
            return
        self._value = spec
        self.stop_listening(restore=False)
        self._refresh_text()
        self.changed.emit(self._value)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._listening:
            super().keyPressEvent(event)
            return
        spec = spec_from_qt_key(event)
        if spec:
            self._commit(spec)
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._listening:
            spec = spec_from_qt_mouse(event)
            if spec:
                self._commit(spec)
            elif event.button() == Qt.MouseButton.RightButton:
                self.stop_listening(restore=True)
            event.accept()
            return
        super().mousePressEvent(event)

    def focusOutEvent(self, event) -> None:
        if self._listening:
            self.stop_listening(restore=True)
        super().focusOutEvent(event)

    def hideEvent(self, event) -> None:
        self.stop_listening(restore=True)
        super().hideEvent(event)
