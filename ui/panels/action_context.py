"""后台识别按钮的不可变上下文与可取消窗口恢复入口。"""
import copy
import weakref
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot
from shiboken6 import isValid


class ActionWindowContext(QObject):
    cancelled = Signal()

    def __init__(self, window, directories, card_id, parent):
        super().__init__(parent)
        self._window = weakref.ref(window) if window is not None else lambda: None
        self._directories = copy.deepcopy(directories)
        self._cancelled = Event()
        self.current_card_id = card_id
        for key, value in directories.items():
            setattr(self, key, value)
        self.destroyed.connect(self._cancelled.set)

    def _current_task_resource_dirs(self):
        return dict(self._directories)

    def cancel(self):
        if not self._cancelled.is_set():
            self._cancelled.set()
            self.cancelled.emit()

    @Slot()
    def show(self):
        window = self._window()
        if not self._cancelled.is_set() and window is not None and isValid(window):
            window.show()

    @Slot()
    def raise_(self):
        window = self._window()
        if not self._cancelled.is_set() and window is not None and isValid(window):
            window.raise_()

    @Slot()
    def activateWindow(self):
        window = self._window()
        if not self._cancelled.is_set() and window is not None and isValid(window):
            window.activateWindow()
