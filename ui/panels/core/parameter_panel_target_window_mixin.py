from ..parameter_panel_support import *
from utils.window.window_binding_utils import (
    resolve_live_target_hwnd,
)

class ParameterPanelTargetWindowMixin:

    def _binding_host(self):
        return getattr(self, "main_window", None) or getattr(self, "parent_window", None)

    def _get_target_window_hwnd(self):
        """每次采集读取当前绑定；解绑或读取失败时立即清除旧句柄。"""
        logger.info("获取目标窗口句柄...")
        standalone_hwnd = getattr(self, "target_window_hwnd", None)
        self.target_window_hwnd = None
        hwnd = resolve_live_target_hwnd(self._binding_host(), standalone_hwnd)
        self.target_window_hwnd = hwnd
        if hwnd is not None:
            logger.info(f"当前目标窗口句柄: {hwnd}")
        else:
            logger.warning("未找到可用的绑定窗口句柄")
        return hwnd

    def _get_first_window_for_selection(self):
        hwnd = self._get_target_window_hwnd()
        if hwnd is None:
            return None
        import win32gui
        return win32gui.GetWindowText(hwnd)
