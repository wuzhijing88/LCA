"""全局设置的窗口调整任务：单线程执行，按句柄合并待处理请求。"""

import logging
import threading

from utils.window.universal_window_manager import get_universal_window_manager

logger = logging.getLogger(__name__)


class WindowResizeJobs:
    """只持有窗口数据，不持有或访问 Qt 控件。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending = {}
        self._thread = None
        self._closed = False

    @property
    def thread(self):
        with self._lock:
            return self._thread

    def submit(self, windows, width, height):
        with self._lock:
            if self._closed:
                raise RuntimeError("设置窗口已关闭，不能再调整分辨率")
            for hwnd, title in windows:
                self._pending[hwnd] = (title, width, height)
            if not self._pending or self._thread is not None:
                return
            worker = threading.Thread(target=self._run, name="settings-window-resize", daemon=True)
            self._thread = worker
            try:
                worker.start()
            except BaseException:
                self._thread = None
                self._pending.clear()
                raise

    def cancel(self, *_args):
        """取消尚未开始的操作；已进入系统调用的单个窗口调整自然收尾。"""
        with self._lock:
            self._closed = True
            self._pending.clear()

    def resume(self):
        with self._lock:
            self._closed = False

    def _run(self):
        try:
            manager = get_universal_window_manager()
            while True:
                with self._lock:
                    if self._closed or not self._pending:
                        self._thread = None
                        return
                    hwnd = next(iter(self._pending))
                    title, width, height = self._pending.pop(hwnd)
                try:
                    result = manager.adjust_single_window(hwnd, width, height)
                    if result.success:
                        logger.info("窗口分辨率调整成功: %s (%s -> %s)", title, result.before_size, result.after_size)
                    else:
                        logger.warning("窗口分辨率调整失败: %s - %s", title, result.message)
                except Exception:
                    logger.exception("窗口分辨率调整失败: %s", title)
        except Exception:
            logger.exception("启动窗口分辨率调整失败")
        finally:
            with self._lock:
                if self._thread is threading.current_thread():
                    self._pending.clear()
                    self._thread = None
