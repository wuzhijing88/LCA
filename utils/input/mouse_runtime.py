from __future__ import annotations

import ctypes
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ScreenBounds:
    left: int
    top: int
    width: int
    height: int

    @classmethod
    def from_tuple(cls, values) -> "_ScreenBounds":
        left, top, width, height = (int(value) for value in values)
        if width <= 0 or height <= 0:
            raise ValueError(f"虚拟屏幕尺寸必须大于零: {(left, top, width, height)!r}")
        return cls(left=left, top=top, width=width, height=height)

    def clamp(self, x: int, y: int) -> tuple[int, int]:
        right = self.left + self.width - 1
        bottom = self.top + self.height - 1
        return (
            max(self.left, min(int(x), right)),
            max(self.top, min(int(y), bottom)),
        )


class MouseMoveFixer:
    """Convert client coordinates and move the foreground cursor through the active driver."""

    def __init__(self, user32=None):
        self._user32 = user32 if user32 is not None else ctypes.windll.user32
        self._monitor_manager = None

    def _resolve_monitor_manager(self):
        if self._monitor_manager is None:
            from utils.window.multi_monitor_manager import get_multi_monitor_manager

            manager = get_multi_monitor_manager()
            if manager is None:
                raise RuntimeError("多显示器管理器未初始化")
            self._monitor_manager = manager
        return self._monitor_manager

    def _get_virtual_screen_bounds(self) -> _ScreenBounds:
        return _ScreenBounds.from_tuple(self._resolve_monitor_manager().get_virtual_screen_bounds())

    def client_to_clamped_screen(self, hwnd, client_x, client_y) -> tuple[int, int]:
        from ctypes import wintypes

        if not hwnd or not self._user32.IsWindow(hwnd):
            raise ValueError(f"无效的目标窗口句柄: {hwnd!r}")

        point = wintypes.POINT(int(client_x), int(client_y))
        if not self._user32.ClientToScreen(hwnd, ctypes.byref(point)):
            raise OSError("ClientToScreen 转换失败")
        return self._get_virtual_screen_bounds().clamp(point.x, point.y)

    def move_to_client_coord(self, hwnd, client_x, client_y) -> None:
        screen_x, screen_y = self.client_to_clamped_screen(hwnd, client_x, client_y)
        from utils.input.foreground_input_manager import get_foreground_input_manager

        moved = get_foreground_input_manager().move_mouse(screen_x, screen_y, absolute=True)
        if not moved:
            raise RuntimeError(f"前台鼠标移动失败: ({screen_x}, {screen_y})")
        logger.debug("前台鼠标已移动到屏幕坐标 (%s, %s)", screen_x, screen_y)


mouse_move_fixer = MouseMoveFixer()
