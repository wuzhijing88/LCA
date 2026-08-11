"""
增强型输入控制器
集成PyDirectInput以获得更低的输入延迟和更好的兼容性
"""

import logging
import time
import ctypes
from ctypes import wintypes
from threading import RLock
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

# 尝试导入PyDirectInput
try:
    import pydirectinput as pdi
    PYDIRECTINPUT_AVAILABLE = True
    logger.info("PyDirectInput已加载 - 将使用低延迟输入模式")
except ImportError:
    PYDIRECTINPUT_AVAILABLE = False
    logger.info("PyDirectInput未安装 - 使用标准pynput模式")

# 导入pynput作为后备
from pynput.mouse import Button as PynputButton, Controller as PynputMouse
from pynput.keyboard import Controller as PynputKeyboard, Key as PynputKey


class EnhancedMouseController:
    """增强型鼠标控制器，优先使用PyDirectInput"""

    def __init__(self, prefer_pydirectinput: bool = True):
        """
        初始化鼠标控制器

        Args:
            prefer_pydirectinput: 是否优先使用PyDirectInput（默认True）
        """
        self.use_pydirectinput = PYDIRECTINPUT_AVAILABLE and prefer_pydirectinput
        self._mouse_lock = RLock()

        if self.use_pydirectinput:
            logger.info("鼠标控制器: 使用PyDirectInput (低延迟模式)")
            # PyDirectInput配置
            pdi.PAUSE = 0  # 禁用操作间延迟
            pdi.FAILSAFE = False  # 禁用失败安全（提高性能）
        else:
            logger.info("鼠标控制器: 使用pynput (标准模式)")
            self.pynput_mouse = PynputMouse()

    def _get_cursor_pos(self) -> Tuple[int, int]:
        try:
            point = wintypes.POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
                return int(point.x), int(point.y)
        except Exception:
            pass
        try:
            if self.use_pydirectinput:
                x, y = pdi.position()
                return int(x), int(y)
            x, y = self.pynput_mouse.position
            return int(x), int(y)
        except Exception:
            return 0, 0

    def _move_to_target(self, x: int, y: int) -> None:
        if self.use_pydirectinput:
            pdi.moveTo(int(x), int(y), duration=0)
        else:
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
        """获取鼠标位置"""
        if self.use_pydirectinput:
            return pdi.position()
        else:
            return self.pynput_mouse.position
    @position.setter
    def position(self, pos: Tuple[int, int]):
        """设置鼠标位置（带到位确认）。"""
        x, y = int(pos[0]), int(pos[1])
        with self._mouse_lock:
            if not self._move_to_target_with_retry(x, y):
                logger.warning(f"鼠标移动未到位: ({x}, {y})")

    def press(self, button):
        """按下鼠标按钮"""
        with self._mouse_lock:
            if self.use_pydirectinput:
                # 转换pynput按钮到PyDirectInput格式
                if button == PynputButton.left or str(button) == 'Button.left':
                    pdi.mouseDown(button='left')
                elif button == PynputButton.right or str(button) == 'Button.right':
                    pdi.mouseDown(button='right')
                elif button == PynputButton.middle or str(button) == 'Button.middle':
                    pdi.mouseDown(button='middle')
            else:
                self.pynput_mouse.press(button)

    def release(self, button):
        """释放鼠标按钮"""
        with self._mouse_lock:
            if self.use_pydirectinput:
                if button == PynputButton.left or str(button) == 'Button.left':
                    pdi.mouseUp(button='left')
                elif button == PynputButton.right or str(button) == 'Button.right':
                    pdi.mouseUp(button='right')
                elif button == PynputButton.middle or str(button) == 'Button.middle':
                    pdi.mouseUp(button='middle')
            else:
                self.pynput_mouse.release(button)

    def click(self, button, count: int = 1):
        """点击鼠标按钮"""
        with self._mouse_lock:
            if self.use_pydirectinput:
                button_name = 'left'
                if button == PynputButton.right or str(button) == 'Button.right':
                    button_name = 'right'
                elif button == PynputButton.middle or str(button) == 'Button.middle':
                    button_name = 'middle'

                for _ in range(count):
                    pdi.click(button=button_name)
            else:
                self.pynput_mouse.click(button, count)

    def scroll(self, dx: int, dy: int):
        """滚动鼠标滚轮"""
        with self._mouse_lock:
            if self.use_pydirectinput:
                # PyDirectInput使用click参数表示滚动量
                if dy != 0:
                    pdi.scroll(int(dy))
                # 注意：PyDirectInput不支持水平滚动
            else:
                self.pynput_mouse.scroll(dx, dy)


class EnhancedKeyboardController:
    """增强型键盘控制器，优先使用PyDirectInput"""

    def __init__(self, prefer_pydirectinput: bool = True):
        """
        初始化键盘控制器

        Args:
            prefer_pydirectinput: 是否优先使用PyDirectInput（默认True）
        """
        self.use_pydirectinput = PYDIRECTINPUT_AVAILABLE and prefer_pydirectinput

        if self.use_pydirectinput:
            logger.info("键盘控制器: 使用PyDirectInput (低延迟模式)")
            pdi.PAUSE = 0
        else:
            logger.info("键盘控制器: 使用pynput (标准模式)")
            self.pynput_keyboard = PynputKeyboard()

        # 特殊键映射表（pynput -> PyDirectInput）
        self.key_mapping = {
            'Key.enter': 'enter',
            'Key.esc': 'esc',
            'Key.space': 'space',
            'Key.tab': 'tab',
            'Key.backspace': 'backspace',
            'Key.delete': 'delete',
            'Key.home': 'home',
            'Key.end': 'end',
            'Key.page_up': 'pageup',
            'Key.page_down': 'pagedown',
            'Key.up': 'up',
            'Key.down': 'down',
            'Key.left': 'left',
            'Key.right': 'right',
            'Key.shift': 'shift',
            'Key.shift_l': 'shiftleft',
            'Key.shift_r': 'shiftright',
            'Key.ctrl': 'ctrl',
            'Key.ctrl_l': 'ctrlleft',
            'Key.ctrl_r': 'ctrlright',
            'Key.alt': 'alt',
            'Key.alt_l': 'altleft',
            'Key.alt_r': 'altright',
            'Key.caps_lock': 'capslock',
            'Key.f1': 'f1', 'Key.f2': 'f2', 'Key.f3': 'f3', 'Key.f4': 'f4',
            'Key.f5': 'f5', 'Key.f6': 'f6', 'Key.f7': 'f7', 'Key.f8': 'f8',
            'Key.f9': 'f9', 'Key.f10': 'f10', 'Key.f11': 'f11', 'Key.f12': 'f12',
        }

    def _convert_key(self, key) -> Optional[str]:
        """转换按键格式"""
        # 如果是字符串格式的特殊键
        if isinstance(key, str):
            if key.startswith('Key.'):
                return self.key_mapping.get(key.lower(), None)
            # 普通字符
            elif len(key) == 1:
                return key
            return None

        # 如果是pynput的Key对象
        if hasattr(key, 'name'):
            key_str = f'Key.{key.name}'
            return self.key_mapping.get(key_str.lower(), None)

        # 普通字符
        if hasattr(key, 'char') and key.char:
            return key.char

        return None

    def press(self, key):
        """按下按键"""
        if self.use_pydirectinput:
            key_str = self._convert_key(key)
            if key_str:
                try:
                    pdi.keyDown(key_str)
                except Exception as e:
                    logger.warning(f"PyDirectInput按键失败，降级到pynput: {e}")
                    if not hasattr(self, 'pynput_keyboard'):
                        self.pynput_keyboard = PynputKeyboard()
                    self.pynput_keyboard.press(key)
            else:
                logger.warning(f"无法转换按键: {key}")
        else:
            self.pynput_keyboard.press(key)

    def release(self, key):
        """释放按键"""
        if self.use_pydirectinput:
            key_str = self._convert_key(key)
            if key_str:
                try:
                    pdi.keyUp(key_str)
                except Exception as e:
                    logger.warning(f"PyDirectInput按键释放失败，降级到pynput: {e}")
                    if not hasattr(self, 'pynput_keyboard'):
                        self.pynput_keyboard = PynputKeyboard()
                    self.pynput_keyboard.release(key)
        else:
            self.pynput_keyboard.release(key)

    def tap(self, key, count: int = 1):
        """敲击按键（按下并释放）"""
        for _ in range(count):
            self.press(key)
            self.release(key)


def create_mouse_controller(prefer_pydirectinput: bool = True) -> EnhancedMouseController:
    """
    创建鼠标控制器

    Args:
        prefer_pydirectinput: 是否优先使用PyDirectInput

    Returns:
        EnhancedMouseController实例
    """
    return EnhancedMouseController(prefer_pydirectinput=prefer_pydirectinput)


def create_keyboard_controller(prefer_pydirectinput: bool = True) -> EnhancedKeyboardController:
    """
    创建键盘控制器

    Args:
        prefer_pydirectinput: 是否优先使用PyDirectInput

    Returns:
        EnhancedKeyboardController实例
    """
    return EnhancedKeyboardController(prefer_pydirectinput=prefer_pydirectinput)


def is_pydirectinput_available() -> bool:
    """检查PyDirectInput是否可用"""
    return PYDIRECTINPUT_AVAILABLE

