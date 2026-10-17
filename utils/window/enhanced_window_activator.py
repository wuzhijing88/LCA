"""按 Win32 消息契约执行和解除后台假激活，不调用系统激活或焦点 API。"""

import logging

import win32con
import win32gui
import win32process

logger = logging.getLogger(__name__)


class EnhancedWindowActivator:
    @staticmethod
    def _send(hwnd, message, wparam, lparam, use_post_message):
        if use_post_message:
            win32gui.PostMessage(hwnd, message, wparam, lparam)
        else:
            win32gui.SendMessageTimeout(
                hwnd, message, wparam, lparam, win32con.SMTO_ABORTIFHUNG, 200,
            )

    @staticmethod
    def _foreground_peer(parent_hwnd):
        peer = int(win32gui.GetForegroundWindow() or 0)
        if not peer or peer == parent_hwnd:
            return peer, 0
        thread_id, _ = win32process.GetWindowThreadProcessId(peer)
        if not thread_id:
            raise RuntimeError("无法确定当前前台窗口线程")
        return peer, thread_id

    def _activate(self, parent_hwnd, child_hwnd, state, use_post_message):
        try:
            if not win32gui.IsWindow(parent_hwnd) or not win32gui.IsWindow(child_hwnd):
                raise RuntimeError("后台假激活窗口已失效")
            peer, thread_id = self._foreground_peer(parent_hwnd)
            if peer == parent_hwnd:
                return True
            minimized = int(bool(win32gui.IsIconic(parent_hwnd))) << 16
            for hwnd, message, wparam, lparam in (
                (parent_hwnd, win32con.WM_ACTIVATEAPP, 1, thread_id),
                (parent_hwnd, win32con.WM_NCACTIVATE, 1, 0),
                (parent_hwnd, win32con.WM_ACTIVATE, state | minimized, peer),
                (child_hwnd, win32con.WM_SETFOCUS, 0, 0),
            ):
                self._send(hwnd, message, wparam, lparam, use_post_message)
            return True
        except Exception:
            logger.error("后台假激活失败", exc_info=True)
            return False

    def activate_for_click(self, parent_hwnd, child_hwnd, *, use_post_message=False):
        return self._activate(parent_hwnd, child_hwnd, win32con.WA_CLICKACTIVE, use_post_message)

    def activate_for_keyboard(self, parent_hwnd, child_hwnd, *, use_post_message=False):
        return self._activate(parent_hwnd, child_hwnd, win32con.WA_ACTIVE, use_post_message)

    def deactivate(self, parent_hwnd, child_hwnd, *, use_post_message=False):
        """释放本次假激活；主窗口已真实成为前台时保留真实激活状态。"""
        try:
            peer, thread_id = self._foreground_peer(parent_hwnd)
            if peer == parent_hwnd:
                return True
        except Exception:
            logger.error("无法确定后台假激活释放目标", exc_info=True)
            return False
        success = True
        minimized = int(bool(win32gui.IsIconic(parent_hwnd))) << 16 if win32gui.IsWindow(parent_hwnd) else 0
        for hwnd, message, wparam, lparam in (
            (child_hwnd, win32con.WM_KILLFOCUS, 0, 0),
            (parent_hwnd, win32con.WM_ACTIVATE, win32con.WA_INACTIVE | minimized, peer),
            (parent_hwnd, win32con.WM_ACTIVATEAPP, 0, thread_id),
            (parent_hwnd, win32con.WM_NCACTIVATE, 0, 0),
        ):
            try:
                if win32gui.IsWindow(hwnd):
                    self._send(hwnd, message, wparam, lparam, use_post_message)
            except Exception:
                logger.error("解除后台假激活失败：%s", hwnd, exc_info=True)
                success = False
        return success


_global_activator = None


def get_window_activator() -> EnhancedWindowActivator:
    global _global_activator
    if _global_activator is None:
        _global_activator = EnhancedWindowActivator()
    return _global_activator
