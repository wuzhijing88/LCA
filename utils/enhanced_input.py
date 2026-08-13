"""录制回放用的 pynput 输入控制器。"""

import logging
import time
import ctypes
from ctypes import wintypes
from threading import RLock
from typing import Tuple

from pynput.mouse import Controller as PynputMouse
from pynput.keyboard import Controller as PynputKeyboard

logger = logging.getLogger(__name__)


class EnhancedMouseController:
    """鼠标控制器，使用 pynput，移动带到位确认。"""

    def __init__(self):
        self._mouse_lock = RLock()
        self.pynput_mouse = PynputMouse()

    def _get_cursor_pos(self) -> Tuple[int, int]:
        try:
            point = wintypes.POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
                return int(point.x), int(point.y)
        except Exception:
            pass
        try:
            x, y = self.pynput_mouse.position
            return int(x), int(y)
        except Exception:
            return 0, 0

    def _move_to_target(self, x: int, y: int) -> None:
        self.pynput_mouse.position = (int(x), int(y))

    def _move_to_target_with_retry(
        self,
        x: int,
        y: int,
        max_attempts: int = 3,
        timeout: float = 0.08,
        tolerance: int = 2,
    ) -> bool:
        target_x, target_y = int(x), int(y)
        attempts = max(1, int(max_attempts))
        wait_timeout = max(0.01, float(timeout))
        tol = max(0, int(tolerance))

        for _ in range(attempts):
            try:
                self._move_to_target(target_x, target_y)
            except Exception:
                return False

            deadline = time.perf_counter() + wait_timeout
            while time.perf_counter() <= deadline:
                current_x, current_y = self._get_cursor_pos()
                if abs(current_x - target_x) <= tol and abs(current_y - target_y) <= tol:
                    return True
                time.sleep(0.002)

        return False

    @property
    def position(self) -> Tuple[int, int]:
        return self.pynput_mouse.position

    @position.setter
    def position(self, pos: Tuple[int, int]):
        x, y = int(pos[0]), int(pos[1])
        with self._mouse_lock:
            if not self._move_to_target_with_retry(x, y):
                logger.warning(f"鼠标移动未到位: ({x}, {y})")

    def press(self, button):
        with self._mouse_lock:
            self.pynput_mouse.press(button)

    def release(self, button):
        with self._mouse_lock:
            self.pynput_mouse.release(button)

    def click(self, button, count: int = 1):
        with self._mouse_lock:
            self.pynput_mouse.click(button, count)

    def scroll(self, dx: int, dy: int):
        with self._mouse_lock:
            self.pynput_mouse.scroll(dx, dy)


class EnhancedKeyboardController:
    """键盘控制器，使用 pynput。"""

    def __init__(self):
        self.pynput_keyboard = PynputKeyboard()

    def press(self, key):
        self.pynput_keyboard.press(key)

    def release(self, key):
        self.pynput_keyboard.release(key)

    def tap(self, key, count: int = 1):
        for _ in range(count):
            self.press(key)
            self.release(key)


def create_mouse_controller() -> EnhancedMouseController:
    return EnhancedMouseController()


def create_keyboard_controller() -> EnhancedKeyboardController:
    return EnhancedKeyboardController()
