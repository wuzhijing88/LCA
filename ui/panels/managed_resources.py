"""参数界面临时窗口、全局钩子和可停止线程的所有权。"""
import logging
from functools import partial
from threading import RLock
import weakref

from PySide6.QtCore import QCoreApplication, QEvent
from shiboken6 import isValid

logger = logging.getLogger(__name__)
_threads = set()
_background_threads = {}
_lock = RLock()


def _release_thread(state_ref, thread):
    state = state_ref()
    if state is not None:
        state.threads.discard(thread)
    with _lock:
        _threads.discard(thread)
    thread.deleteLater()


def _drain_threads():
    with _lock:
        threads = list(_threads)
        background_threads = list(_background_threads.items())
    for thread, cancelled in background_threads:
        cancelled.set()
    for thread in threads:
        if isValid(thread) and thread.isRunning():
            thread.stop()
    for thread in threads:
        if isValid(thread):
            thread.wait()
            thread.deleteLater()
    for thread, cancelled in background_threads:
        thread.join()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def own_background_thread(thread, cancelled):
    app = QCoreApplication.instance()
    if not app.property('_lca_parameter_thread_shutdown'):
        app.aboutToQuit.connect(_drain_threads)
        app.setProperty('_lca_parameter_thread_shutdown', True)
    with _lock:
        _background_threads[thread] = cancelled


def release_background_thread(thread):
    with _lock:
        _background_threads.pop(thread, None)


class PanelResources:
    def __init__(self):
        self.cleanups = {}
        self.widgets = {}
        self.widget_cleanups = {}
        self.threads = set()

    def bind_cleanup(self, key, callback):
        if key in self.cleanups:
            raise RuntimeError(f"界面资源重复注册：{key}")
        self.cleanups[key] = callback

    def forget_cleanup(self, key):
        self.cleanups.pop(key, None)

    def own_widget(self, widget, cleanup=None):
        key = id(widget)
        self.widgets[key] = widget
        if cleanup is not None:
            self.widget_cleanups[key] = cleanup
            widget.destroyed.connect(partial(self.widget_cleanups.pop, key, None))
        widget.destroyed.connect(partial(self.widgets.pop, key, None))
        return widget

    def own_thread(self, thread):
        app = QCoreApplication.instance()
        if not app.property('_lca_parameter_thread_shutdown'):
            app.aboutToQuit.connect(_drain_threads)
            app.setProperty('_lca_parameter_thread_shutdown', True)
        thread.setParent(app)
        self.threads.add(thread)
        with _lock:
            _threads.add(thread)
        thread.finished.connect(partial(_release_thread, weakref.ref(self), thread))
        return thread

    def close(self):
        errors = []
        for key, callback in list(self.cleanups.items()):
            try:
                callback()
            except Exception as exc:
                errors.append(exc)
                logger.error("卸载界面资源 %s 失败：%s", key, exc)
            else:
                self.cleanups.pop(key, None)
        for thread in list(self.threads):
            if isValid(thread) and thread.isRunning():
                try:
                    thread.stop()
                except Exception as exc:
                    errors.append(exc)
                    logger.error("停止参数面板线程失败：%s", exc)
        errors.extend(self.close_tools())
        return errors

    def close_tools(self):
        errors = []
        for key, widget in list(self.widgets.items()):
            if isValid(widget):
                widget.setProperty("parameterDisposed", True)
                widget.blockSignals(True)
                cleanup = self.widget_cleanups.pop(key, None)
                if cleanup is not None:
                    try:
                        cleanup()
                    except Exception as exc:
                        errors.append(exc)
                        logger.error("释放参数工具资源失败：%s", exc)
                try:
                    widget.close()
                except Exception as exc:
                    errors.append(exc)
                    logger.error("关闭参数工具失败：%s", exc)
                finally:
                    widget.deleteLater()
            self.widgets.pop(key, None)
        return errors



def dispose_partial_widget(owner, parent):
    from PySide6.QtWidgets import QWidget

    for value in vars(owner).values():
        if isinstance(value, QWidget) and value is not owner and value is not parent and isValid(value) and value.parentWidget() is None:
            value.setParent(owner, value.windowFlags())
    owner.deleteLater()
