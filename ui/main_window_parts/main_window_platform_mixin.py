import ctypes
import logging
import threading

from PySide6.QtCore import QTimer

logger = logging.getLogger(__name__)


class MainWindowPlatformMixin:
    def _has_initial_window_resize_context(self) -> bool:

        """Return True only when startup workflow context exists for initial resize."""

        try:

            task_manager = getattr(self, 'task_manager', None)

            if task_manager is not None and task_manager.get_all_tasks():

                return True

        except Exception as e:

            logging.warning(f"检查启动任务上下文失败: {e}")

        try:

            checked_favorites = self._load_checked_favorite_workflow_paths()

            if checked_favorites:

                return True

        except Exception as e:

            logging.warning(f"检查启动收藏上下文失败: {e}")

        return False

    def _schedule_initial_window_resize(self):

        """Delay initial window resize until after the main window is shown."""

        if not self._has_initial_window_resize_context():

            logging.info("跳过初始窗口尺寸调整：没有需要恢复的工作流上下文。")

            return

        if getattr(self, '_initial_window_resize_started', False):

            return

        self._initial_window_resize_started = True

        def _launch_resize_task():

            try:

                resize_thread = getattr(self, '_initial_window_resize_thread', None)

                if resize_thread and resize_thread.is_alive():

                    return

                self._initial_window_resize_thread = threading.Thread(

                    target=self._apply_initial_window_resize,

                    name='initial-window-resize',

                    daemon=True,

                )

                self._initial_window_resize_thread.start()

                logging.info("Initial window resize thread started.")

            except Exception as e:

                self._initial_window_resize_started = False

                logging.error(f"启动初始窗口缩放线程失败：{e}")

        QTimer.singleShot(100, _launch_resize_task)

    def _apply_initial_window_resize(self):

        """Attempts to resize the target window's client area based on global settings on startup."""

        title = self.current_target_window_title

        target_client_width = self.custom_width

        target_client_height = self.custom_height

        # Read target resolution and bound window info from config.

        has_custom_resolution = target_client_width > 0 and target_client_height > 0

        # Only resize on startup when target windows or custom resolution exist.

        if self.window_binding_mode == 'multiple':

            if has_custom_resolution and self.bound_windows:

                logging.info(f"Multi-window mode: resize bound windows to {target_client_width}x{target_client_height} on startup...")

                self._apply_multi_window_resize()

            else:

                if not has_custom_resolution:

                    logging.info("Multi-window mode: no custom resolution configured; skip startup resize.")

                else:

                    logging.info("Multi-window mode: bound windows exist but resize conditions are not met; skip startup resize.")

        elif has_custom_resolution:

            target_hwnd = 0

            enabled_windows = [w for w in self.bound_windows if w.get('enabled', True)] if getattr(self, 'bound_windows', None) else []

            if enabled_windows:

                try:

                    target_hwnd = int(enabled_windows[0].get('hwnd') or 0)

                except Exception:

                    target_hwnd = 0

            if not target_hwnd and title:

                try:

                    target_hwnd, _is_child_window, _parent_hwnd = self._find_window_with_parent_info(title)

                except Exception:

                    target_hwnd = 0

            target_desc = str(title or target_hwnd or "target window")

            logging.info(f"Single-window mode: resize '{target_desc}' to {target_client_width}x{target_client_height} on startup...")

            try:

                from utils.universal_window_manager import get_universal_window_manager

                if target_hwnd:

                    logging.info(f"Single-window mode: resolved target HWND: {target_hwnd}")

                    window_manager = get_universal_window_manager()

                    result = window_manager.adjust_single_window(

                        target_hwnd, target_client_width, target_client_height, async_mode=False

                    )

                    if result.success:

                        logging.info(f"Single-window mode: resize succeeded: {result.message}")

                    else:

                        logging.warning(f"Single-window mode: resize failed: {result.message}")

                else:

                    logging.warning("Single-window mode: target window handle not found; skip startup resize.")

            except Exception as e:

                logging.error(f"Single-window mode: unexpected error while resizing window: {e}")

        else:

            logging.info("Skip initial window resize: target title or custom resolution is not configured.")

    def nativeEvent(self, eventType, message):

        """

        Handle Windows native events for frameless drag/resize support.

        WM_ENTERSIZEMOVE (0x0231): Start moving or resizing

        WM_EXITSIZEMOVE (0x0232): Finish moving or resizing
        WM_NCHITTEST (0x0084): Hit test for edge resizing

        """


        from .main_window_support import _safe_get_win_msg
        retval, result = super().nativeEvent(eventType, message)

        # Only process native messages on Windows

        if eventType == b"windows_generic_MSG" or eventType == "windows_generic_MSG":

            try:

                # 鐟欙絾鐎絎indows濞戝牊浼?
                msg = _safe_get_win_msg(message)

                if msg is None:

                    return retval, result

                # WM_NCHITTEST = 0x0084 - Allow resizing by window edges
                if msg.message == 0x0084:
                    if self.isMaximized() or self.isFullScreen():

                        return retval, result

                    # 获取鼠标全局坐标（原生物理像素），直接与原生窗口矩形比较。
                    # Avoid Qt/Win32 coordinate conversion errors on high-DPI or multi-screen setups.
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value

                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value

                    hwnd = int(self.winId())

                    rect = ctypes.wintypes.RECT()

                    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):

                        return retval, result

                    border_width = 5

                    left = int(rect.left)
                    top = int(rect.top)
                    right = int(rect.right)
                    bottom = int(rect.bottom)

                    on_left = left <= x < left + border_width

                    on_right = right - border_width <= x < right

                    on_top = top <= y < top + border_width

                    on_bottom = bottom - border_width <= y < bottom

                    # 角落优先（允许对角线调整大小）
                    if on_top and on_left:

                        return True, 13  # HTTOPLEFT

                    elif on_top and on_right:

                        return True, 14  # HTTOPRIGHT

                    elif on_bottom and on_left:

                        return True, 16  # HTBOTTOMLEFT

                    elif on_bottom and on_right:

                        return True, 17  # HTBOTTOMRIGHT

                    # 杈圭紭

                    elif on_left:

                        return True, 10  # HTLEFT

                    elif on_right:

                        return True, 11  # HTRIGHT

                    elif on_top:

                        return True, 12  # HTTOP

                    elif on_bottom:

                        return True, 15  # HTBOTTOM

                # WM_ENTERSIZEMOVE = 0x0231 - Start moving or resizing
                if msg.message == 0x0231:

                    logger.debug("Window move/resize started")

                # WM_EXITSIZEMOVE = 0x0232 - Finish moving or resizing
                elif msg.message == 0x0232:

                    logger.debug("Window move/resize finished")

            except Exception as e:

                # Ignore message parsing errors to avoid affecting normal event handling
                pass

        return retval, result
