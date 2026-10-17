"""应用对话框的生命周期入口；主题与具体业务仍由各自模块负责。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
from weakref import WeakSet

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QThread, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from shiboken6 import isValid

from themes import apply_rounded_popup


@dataclass
class _WindowEntry:
    window: QWidget
    connections: list = field(default_factory=list)
    close_requested: bool = False


def _worker_running(worker):
    return isValid(worker) and worker.isRunning() if isinstance(worker, QThread) else worker.is_alive()


class _DialogCoordinator(QObject):
    """应用退出前先关闭所有托管窗口，再等待已取消的后台工作收尾。"""

    def __init__(self, app):
        super().__init__(app)
        self.managers = WeakSet()
        self._retired = []
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._collect)
        app.aboutToQuit.connect(self.shutdown)

    def retire(self, dialog, workers):
        workers = tuple(worker for worker in workers if worker is not None)
        if not any(_worker_running(worker) for worker in workers):
            dialog.deleteLater()
            return
        # 父窗口销毁时后台任务仍可能回传信号，保留整个接收对象直到线程退出。
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        dialog.hide()
        dialog.setParent(None, dialog.windowFlags())
        self._retired.append((dialog, workers))
        self._timer.start()

    def _collect(self):
        pending = []
        for dialog, workers in self._retired:
            if any(_worker_running(worker) for worker in workers):
                pending.append((dialog, workers))
            else:
                dialog.deleteLater()
        self._retired = pending
        if not pending:
            self._timer.stop()

    def shutdown(self):
        for manager in tuple(self.managers):
            if isValid(manager):
                manager.close_all()
        self._timer.stop()
        for _dialog, workers in self._retired:
            for worker in workers:
                if isinstance(worker, QThread):
                    if isValid(worker):
                        worker.wait()
                else:
                    worker.join()
        self._collect()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _coordinator():
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("创建对话框管理器前必须创建应用程序")
    coordinator = getattr(app, "_lca_dialog_coordinator", None)
    if coordinator is None:
        coordinator = _DialogCoordinator(app)
        app._lca_dialog_coordinator = coordinator
    return coordinator


def retire_dialog(dialog: QDialog, workers=()):
    """调用方先取消工作并断开 UI 信号；管理器等线程退出后销毁接收对象。"""
    _coordinator().retire(dialog, workers)


class DialogManager(QObject):
    """每个所属窗口一个管理器，统一临时对话框与可复用窗口的释放。"""

    def __init__(self, owner: QObject):
        super().__init__(owner)
        self._windows: dict[str, _WindowEntry] = {}
        self._modal_dialogs: set[QDialog] = set()
        owner.installEventFilter(self)
        owner.destroyed.connect(self._owner_destroyed)
        _coordinator().managers.add(self)

    def _owner_destroyed(self, *_args):
        for entry in tuple(self._windows.values()):
            for connection in entry.connections:
                QObject.disconnect(connection)
            entry.connections.clear()
        self._windows.clear()
        self._modal_dialogs.clear()

    def eventFilter(self, watched, event):
        if watched is self.parent() and event.type() == QEvent.Type.DeferredDelete:
            self.close_all()
        elif event.type() == QEvent.Type.Close:
            for entry in tuple(self._windows.values()):
                if entry.window is watched and not isinstance(watched, QDialog):
                    entry.close_requested = True
                    QTimer.singleShot(0, self, lambda entry=entry: setattr(entry, "close_requested", False))
                    break
        return False

    def exec(self, dialog: QDialog, *, read_result: Callable | None = None):
        """读取结果后再释放；异常路径同样释放，禁止自动关闭时提前销毁。"""
        if dialog.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose):
            raise ValueError("临时对话框不能启用关闭时自动销毁，请交给对话框管理器释放")
        self._modal_dialogs.add(dialog)
        try:
            apply_rounded_popup(dialog, frameless=False)
            result = dialog.exec()
            return read_result(result) if read_result is not None else result
        finally:
            self._modal_dialogs.discard(dialog)
            if isValid(dialog):
                dialog.close()
                dialog.deleteLater()

    def find(self, key: str) -> QWidget | None:
        entry = self._windows.get(key)
        if entry is not None and entry.close_requested and not entry.window.isVisible():
            # close 已接受、DeferredDelete 尚未处理时不能把待销毁窗口重新展示。
            self._remove(key, entry)
            return None
        return entry.window if entry is not None else None

    def _remove(self, key: str, entry: _WindowEntry):
        if self._windows.get(key) is not entry:
            return
        del self._windows[key]
        if isValid(entry.window):
            entry.window.removeEventFilter(self)
        for connection in entry.connections:
            QObject.disconnect(connection)
        entry.connections.clear()

    def show(
        self,
        key: str,
        factory: Callable[[], QWidget],
        *,
        present: Callable[[QWidget], None] | None = None,
        on_finished: Callable[[QDialog, int], None] | None = None,
        dispose: Callable[[QDialog], None] | None = None,
    ) -> QWidget:
        """同一所属窗口、同一键只创建一次；关闭被拒绝时仍保留原窗口。"""
        window = self.find(key)
        if window is None:
            window = factory()
            expected_parent = self.parent() if isinstance(self.parent(), QWidget) else None
            if window.parent() is not expected_parent:
                window.deleteLater()
                raise ValueError("托管窗口必须以管理器所属窗口为父对象")
            # 对话框先读取业务结果再销毁；普通窗口由 Qt 在接受 close 后销毁。
            window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, not isinstance(window, QDialog))
            entry = _WindowEntry(window)
            self._windows[key] = entry
            window.installEventFilter(self)
            entry.connections.append(window.destroyed.connect(lambda: self._remove(key, entry)))
            if isinstance(window, QDialog):
                def finished(result):
                    self._remove(key, entry)
                    try:
                        if on_finished is not None:
                            on_finished(window, result)
                    finally:
                        if isValid(window):
                            if dispose is None:
                                window.deleteLater()
                            else:
                                dispose(window)

                entry.connections.append(window.finished.connect(finished))
        try:
            apply_rounded_popup(window, frameless=False)
            if present is None:
                window.show()
                window.raise_()
                window.activateWindow()
            else:
                present(window)
        except Exception:
            entry = self._windows.get(key)
            if entry is not None:
                self._remove(key, entry)
            window.close()
            if isValid(window):
                if dispose is None:
                    window.deleteLater()
                else:
                    dispose(window)
            raise
        return window

    def close_all(self) -> bool:
        """走窗口自己的关闭流程；拒绝关闭的窗口保持托管。"""
        accepted = True
        windows = [entry.window for entry in self._windows.values()]
        windows.extend(self._modal_dialogs)
        for window in windows:
            if isValid(window) and not window.close():
                accepted = False
        return accepted


def get_dialog_manager(owner: QObject | None = None) -> DialogManager:
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("创建对话框管理器前必须创建应用程序")
    if owner is None:
        owner = app
    manager = getattr(owner, "_lca_dialog_manager", None)
    if manager is None:
        manager = DialogManager(owner)
        owner._lca_dialog_manager = manager
    return manager


def exec_dialog(dialog: QDialog, *, read_result: Callable | None = None):
    return get_dialog_manager(dialog.parent()).exec(dialog, read_result=read_result)
