"""
统一的回放引擎模块
使用 Windows API 实现高可靠性的鼠标键盘回放
解决 pynput 方式导致的按键丢失问题
"""
import time
import ctypes
from ctypes import wintypes
import logging
from typing import Callable, Optional, Tuple
from utils.relative_mouse_move import perform_timed_relative_move

try:
    import win32api
    import win32con
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    logging.warning("win32api 不可用，回放功能可能受限")

logger = logging.getLogger(__name__)


def get_vk_code_from_char(char):
    """将单字符映射到虚拟键码，仅返回VK，不注入修饰键信息。"""
    if not isinstance(char, str) or len(char) != 1:
        return None

    # 优先使用当前键盘布局的系统映射
    try:
        layout = ctypes.windll.user32.GetKeyboardLayout(0)
        vk_with_modifiers = ctypes.windll.user32.VkKeyScanExW(ord(char), layout)
    except Exception:
        vk_with_modifiers = -1

    if vk_with_modifiers != -1:
        vk_code = vk_with_modifiers & 0xFF
        if vk_code != 0xFF:
            return vk_code

    # 系统映射失败时，回退到稳定的基础映射，防止整批按键失效
    if 'a' <= char <= 'z' or 'A' <= char <= 'Z':
        return ord(char.upper())

    if '0' <= char <= '9':
        return ord(char)

    shifted_digits = {
        '!': '1',
        '@': '2',
        '#': '3',
        '$': '4',
        '%': '5',
        '^': '6',
        '&': '7',
        '*': '8',
        '(': '9',
        ')': '0',
    }
    if char in shifted_digits:
        return ord(shifted_digits[char])

    punctuation_vk_map = {
        ';': win32con.VK_OEM_1,
        ':': win32con.VK_OEM_1,
        '=': win32con.VK_OEM_PLUS,
        '+': win32con.VK_OEM_PLUS,
        ',': win32con.VK_OEM_COMMA,
        '<': win32con.VK_OEM_COMMA,
        '-': win32con.VK_OEM_MINUS,
        '_': win32con.VK_OEM_MINUS,
        '.': win32con.VK_OEM_PERIOD,
        '>': win32con.VK_OEM_PERIOD,
        '/': win32con.VK_OEM_2,
        '?': win32con.VK_OEM_2,
        '`': win32con.VK_OEM_3,
        '~': win32con.VK_OEM_3,
        '[': win32con.VK_OEM_4,
        '{': win32con.VK_OEM_4,
        '\\': win32con.VK_OEM_5,
        '|': win32con.VK_OEM_5,
        ']': win32con.VK_OEM_6,
        '}': win32con.VK_OEM_6,
        "'": win32con.VK_OEM_7,
        '"': win32con.VK_OEM_7,
    }
    return punctuation_vk_map.get(char)


class ReplayEngine:
    """
    统一的回放引擎
    使用 Windows API (SendInput + 扫描码) 确保按键不丢失
    """

    def __init__(self):
        self._original_mouse_params = None
        self._stop_requested = False
        self._INPUT_KEYBOARD_defined = False

    def disable_mouse_acceleration(self):
        """禁用鼠标加速以实现精确回放"""
        try:
            # 保存原始设置
            mouse_params = (ctypes.c_int * 3)()
            ctypes.windll.user32.SystemParametersInfoW(
                0x0003,  # SPI_GETMOUSE
                0,
                ctypes.byref(mouse_params),
                0
            )
            self._original_mouse_params = tuple(mouse_params)
            logger.info(f"[回放引擎] 原始鼠标参数: {self._original_mouse_params}")

            # 禁用鼠标加速：设置阈值为 0, 0，加速为 0
            new_params = (ctypes.c_int * 3)(0, 0, 0)
            result = ctypes.windll.user32.SystemParametersInfoW(
                0x0004,  # SPI_SETMOUSE
                0,
                ctypes.byref(new_params),
                0  # 不保存到用户配置文件
            )
            if result:
                logger.info("[回放引擎] 已临时禁用鼠标加速")
            else:
                logger.warning("[回放引擎] 禁用鼠标加速失败")
        except Exception as e:
            logger.error(f"[回放引擎] 禁用鼠标加速异常: {e}")

    def restore_mouse_acceleration(self):
        """恢复原始鼠标加速设置"""
        try:
            if self._original_mouse_params:
                params = (ctypes.c_int * 3)(*self._original_mouse_params)
                result = ctypes.windll.user32.SystemParametersInfoW(
                    0x0004,  # SPI_SETMOUSE
                    0,
                    ctypes.byref(params),
                    0
                )
                if result:
                    logger.info(f"[回放引擎] 已恢复鼠标参数: {self._original_mouse_params}")
                else:
                    logger.warning("[回放引擎] 恢复鼠标参数失败")
        except Exception as e:
            logger.error(f"[回放引擎] 恢复鼠标加速异常: {e}")
    def stop(self):
        """请求停止回放"""
        self._stop_requested = True
        logger.info("[回放引擎] 收到停止请求")

    def _get_cursor_pos(self) -> Tuple[int, int]:
        """获取当前鼠标坐标。"""
        try:
            point = wintypes.POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
                return int(point.x), int(point.y)
        except Exception:
            pass

        if WIN32_AVAILABLE:
            try:
                x, y = win32api.GetCursorPos()
                return int(x), int(y)
            except Exception:
                pass
        return 0, 0

    def _set_cursor_pos_with_retry(
        self,
        x: int,
        y: int,
        max_attempts: int = 3,
        timeout: float = 0.08,
        tolerance: int = 2,
    ) -> bool:
        """设置鼠标坐标并等待到位，避免后续点击落在旧位置。"""
        target_x, target_y = int(x), int(y)
        attempts = max(1, int(max_attempts))
        wait_timeout = max(0.01, float(timeout))
        tol = max(0, int(tolerance))

        for _ in range(attempts):
            try:
                win32api.SetCursorPos((target_x, target_y))
            except Exception as e:
                logger.warning(f"[回放引擎] 设置鼠标位置失败: {e}")
                return False

            deadline = time.perf_counter() + wait_timeout
            while time.perf_counter() <= deadline:
                current_x, current_y = self._get_cursor_pos()
                if abs(current_x - target_x) <= tol and abs(current_y - target_y) <= tol:
                    return True
                time.sleep(0.002)

        return False

    def _get_scan_code(self, vk_code):
        """将虚拟键码转换为扫描码（硬件扫描码）"""
        # 使用MapVirtualKey获取扫描码
        return ctypes.windll.user32.MapVirtualKeyW(vk_code, 0)

    def _send_key_with_sendinput(self, vk_code, key_up=False):
        """使用SendInput发送按键（更可靠，支持扫描码）"""
        if not WIN32_AVAILABLE:
            logger.error("[回放引擎] win32api 不可用，无法发送按键")
            return

        # 定义INPUT结构（如果还没有定义）
        if not self._INPUT_KEYBOARD_defined:
            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [
                    ("wVk", wintypes.WORD),
                    ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))
                ]

            class MOUSEINPUT(ctypes.Structure):
                _fields_ = [
                    ("dx", wintypes.LONG),
                    ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))
                ]

            class HARDWAREINPUT(ctypes.Structure):
                _fields_ = [
                    ("uMsg", wintypes.DWORD),
                    ("wParamL", wintypes.WORD),
                    ("wParamH", wintypes.WORD)
                ]

            class INPUT_UNION(ctypes.Union):
                _fields_ = [
                    ("mi", MOUSEINPUT),
                    ("ki", KEYBDINPUT),
                    ("hi", HARDWAREINPUT)
                ]

            class INPUT(ctypes.Structure):
                _fields_ = [
                    ("type", wintypes.DWORD),
                    ("union", INPUT_UNION)
                ]
                _anonymous_ = ("union",)

            self._INPUT = INPUT
            self._KEYBDINPUT = KEYBDINPUT
            self._INPUT_KEYBOARD_defined = True

        # 获取扫描码
        scan_code = self._get_scan_code(vk_code)

        # 创建INPUT结构
        extra = wintypes.ULONG(0)
        ii = self._INPUT()
        ii.type = 1  # INPUT_KEYBOARD
        ii.ki.wVk = vk_code
        ii.ki.wScan = scan_code
        ii.ki.dwFlags = 0x0002 if key_up else 0  # KEYEVENTF_KEYUP = 0x0002
        ii.ki.time = 0
        ii.ki.dwExtraInfo = ctypes.pointer(extra)

        # 发送输入
        ctypes.windll.user32.SendInput(1, ctypes.byref(ii), ctypes.sizeof(ii))

    def _get_vk_code(self, key_name):
        """将按键名称转换为虚拟键码"""
        if not WIN32_AVAILABLE:
            return None
        if key_name is None:
            return None

        if not isinstance(key_name, str):
            key_name = str(key_name)
        if not key_name:
            return None

        normalized_key = key_name.lower()

        # 特殊键映射
        special_keys = {
            ' ': win32con.VK_SPACE,
            'space': win32con.VK_SPACE,
            'enter': win32con.VK_RETURN,
            'esc': win32con.VK_ESCAPE,
            'escape': win32con.VK_ESCAPE,
            'tab': win32con.VK_TAB,
            'backspace': win32con.VK_BACK,
            'delete': win32con.VK_DELETE,
            'shift': win32con.VK_SHIFT,
            'ctrl': win32con.VK_CONTROL,
            'alt': win32con.VK_MENU,
            'lshift': win32con.VK_LSHIFT,
            'rshift': win32con.VK_RSHIFT,
            'lctrl': win32con.VK_LCONTROL,
            'rctrl': win32con.VK_RCONTROL,
            'lalt': win32con.VK_LMENU,
            'ralt': win32con.VK_RMENU,
            'left': win32con.VK_LEFT,
            'right': win32con.VK_RIGHT,
            'up': win32con.VK_UP,
            'down': win32con.VK_DOWN,
            'home': win32con.VK_HOME,
            'end': win32con.VK_END,
            'pageup': win32con.VK_PRIOR,
            'pagedown': win32con.VK_NEXT,
            'insert': win32con.VK_INSERT,
            'caps_lock': win32con.VK_CAPITAL,
            'num_lock': win32con.VK_NUMLOCK,
            'scroll_lock': win32con.VK_SCROLL,
            # 数字小键盘
            'numpad_0': win32con.VK_NUMPAD0,
            'numpad_1': win32con.VK_NUMPAD1,
            'numpad_2': win32con.VK_NUMPAD2,
            'numpad_3': win32con.VK_NUMPAD3,
            'numpad_4': win32con.VK_NUMPAD4,
            'numpad_5': win32con.VK_NUMPAD5,
            'numpad_6': win32con.VK_NUMPAD6,
            'numpad_7': win32con.VK_NUMPAD7,
            'numpad_8': win32con.VK_NUMPAD8,
            'numpad_9': win32con.VK_NUMPAD9,
            'numpad_multiply': win32con.VK_MULTIPLY,
            'numpad_add': win32con.VK_ADD,
            'numpad_subtract': win32con.VK_SUBTRACT,
            'numpad_decimal': win32con.VK_DECIMAL,
            'numpad_divide': win32con.VK_DIVIDE,
        }

        # F功能键
        if normalized_key.startswith('f') and len(normalized_key) > 1:
            try:
                f_num = int(normalized_key[1:])
                if 1 <= f_num <= 24:
                    return win32con.VK_F1 + (f_num - 1)
            except:
                pass

        # 检查特殊键
        if normalized_key in special_keys:
            return special_keys[normalized_key]

        # 单字符按当前输入法/键盘布局映射到VK
        if len(key_name) == 1:
            return get_vk_code_from_char(key_name)

        return None

    def execute_action(self, action, recording_area='全屏录制', window_offset_x=0, window_offset_y=0,
                       recording_mode='绝对坐标', stop_checker=None):
        """
        执行单个动作

        Args:
            action: 动作字典 {'type': 'xxx', ...}
            recording_area: 录制区域（'全屏录制' 或 '窗口录制'）
            window_offset_x: 窗口X偏移
            window_offset_y: 窗口Y偏移
            recording_mode: 录制模式（'绝对坐标' 或 '相对位移'）
        """
        if not WIN32_AVAILABLE:
            logger.error("[回放引擎] win32api 不可用")
            return False

        action_type = action.get('type')

        try:
            if action_type == 'mouse_move':
                # 绝对移动 - 使用 win32api.SetCursorPos
                x, y = action['x'], action['y']
                if recording_area == '窗口录制':
                    x += window_offset_x
                    y += window_offset_y
                if not self._set_cursor_pos_with_retry(int(x), int(y)):
                    logger.warning(f"[回放引擎] 鼠标移动未到位: ({x}, {y})")
                    return False

            elif action_type == 'mouse_move_relative':
                dx, dy = action.get('dx', 0), action.get('dy', 0)
                try:
                    duration = max(0.0, float(action.get('duration', 0.0) or 0.0))
                except (TypeError, ValueError):
                    duration = 0.0

                def _send_relative_step(step_x: int, step_y: int) -> bool:
                    win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, int(step_x), int(step_y), 0, 0)
                    return True

                if duration > 0:
                    if not perform_timed_relative_move(
                        dx,
                        dy,
                        duration,
                        _send_relative_step,
                        stop_checker=stop_checker,
                    ):
                        return False
                elif not _send_relative_step(dx, dy):
                    return False
            elif action_type == 'mouse_click':
                x, y = action['x'], action['y']
                # 窗口录制模式：转换相对坐标为绝对坐标
                if recording_area == '窗口录制':
                    x += window_offset_x
                    y += window_offset_y

                button_name = action.get('button', 'left')
                pressed = action.get('pressed', True)

                # 移动到位置并确认到位
                if not self._set_cursor_pos_with_retry(int(x), int(y)):
                    logger.warning(f"[回放引擎] 点击前移动未到位: ({x}, {y})")
                    return False

                # 鼠标按钮操作
                if pressed:
                    if button_name == 'left':
                        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                    elif button_name == 'right':
                        win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
                    elif button_name == 'middle':
                        win32api.mouse_event(win32con.MOUSEEVENTF_MIDDLEDOWN, 0, 0, 0, 0)
                else:
                    if button_name == 'left':
                        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                    elif button_name == 'right':
                        win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
                    elif button_name == 'middle':
                        win32api.mouse_event(win32con.MOUSEEVENTF_MIDDLEUP, 0, 0, 0, 0)

            elif action_type == 'mouse_scroll':
                dx, dy = action.get('dx', 0), action.get('dy', 0)
                if dy != 0:
                    # 垂直滚轮: 正值向上，负值向下
                    win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, int(dy * 120), 0)
                if dx != 0:
                    # 水平滚轮: 正值向右，负值向左
                    win32api.mouse_event(win32con.MOUSEEVENTF_HWHEEL, 0, 0, int(dx * 120), 0)

            elif action_type == 'key_press':
                key = action.get('key', '')
                if key:
                    # 按键按下 - 使用 SendInput（支持扫描码，更可靠）
                    vk_code = self._get_vk_code(key)
                    if vk_code:
                        self._send_key_with_sendinput(vk_code, key_up=False)
                        # 如果是修饰键，添加短延迟确保被目标应用识别
                        if key.lower() in ['shift', 'lshift', 'rshift', 'ctrl', 'lctrl', 'rctrl', 'alt', 'lalt', 'ralt']:
                            time.sleep(0.02)  # 20ms延迟，确保修饰键生效
                    else:
                        logger.warning(f"[回放引擎] 无法获取按键虚拟码: {key}")

            elif action_type == 'key_release':
                key = action.get('key', '')
                if key:
                    # 按键释放 - 使用 SendInput
                    vk_code = self._get_vk_code(key)
                    if vk_code:
                        self._send_key_with_sendinput(vk_code, key_up=True)
                    else:
                        logger.warning(f"[回放引擎] 无法获取按键虚拟码: {key}")

            return True

        except Exception as e:
            logger.warning(f"[回放引擎] 执行动作失败 {action_type}: {e}")
            return False

    def replay(
        self,
        actions,
        speed=1.0,
        loop_count=1,
        recording_area='全屏录制',
        window_offset_x=0,
        window_offset_y=0,
        precise_timer=None,
        recording_mode='绝对坐标',
        step_callback: Optional[Callable[[int], None]] = None,
    ):
        """
        执行回放

        Args:
            actions: 动作列表
            speed: 回放速度倍率
            loop_count: 循环次数
            recording_area: 录制区域
            window_offset_x: 窗口X偏移
            window_offset_y: 窗口Y偏移
            precise_timer: 精确定时器对象（可选）
            recording_mode: 录制模式（'绝对坐标' 或 '相对位移'）

        Returns:
            bool: 是否成功完成
        """
        if not WIN32_AVAILABLE:
            logger.error("[回放引擎] win32api 不可用，无法回放")
            return False

        try:
            self._stop_requested = False
            logger.info(f"[回放引擎] 开始回放 - 动作数: {len(actions)}, 速度: {speed}x, 循环: {loop_count}")

            # 禁用鼠标加速以实现精确回放
            self.disable_mouse_acceleration()

            # 统计动作
            action_types = {}
            for action in actions:
                action_type = action.get('type')
                action_types[action_type] = action_types.get(action_type, 0) + 1
            logger.info(f"[回放引擎] 动作统计: {action_types}")

            stopped = False

            for loop in range(loop_count):
                if self._stop_requested:
                    stopped = True
                    break

                replay_start_time = time.time()

                for action_index, action in enumerate(actions):
                    if self._stop_requested:
                        stopped = True
                        break

                    if step_callback:
                        try:
                            step_callback(action_index)
                        except Exception as callback_error:
                            logger.warning(f"[回放引擎] 步骤回调失败: {callback_error}")

                    action_type = action.get('type')
                    action_time = action.get('time', 0)

                    # 时间同步
                    target_time = replay_start_time + (action_time / speed)
                    delay = target_time - time.time()
                    if delay > 0:
                        if precise_timer:
                            precise_timer.precise_sleep(delay)
                        else:
                            time.sleep(delay)

                    # 执行动作
                    action_success = self.execute_action(
                        action,
                        recording_area,
                        window_offset_x,
                        window_offset_y,
                        recording_mode,
                        stop_checker=lambda: self._stop_requested,
                    )
                    if not action_success and self._stop_requested:
                        stopped = True
                        break

                if stopped:
                    break

                if loop < loop_count - 1:
                    if self._stop_requested:
                        stopped = True
                        break
                    # 循环间隔
                    if precise_timer:
                        precise_timer.precise_sleep(0.5)
                    else:
                        time.sleep(0.5)

            if stopped:
                logger.info("[回放引擎] 回放已停止")
                return False

            logger.info("[回放引擎] 回放完成")
            return True

        except Exception as e:
            logger.error(f"[回放引擎] 回放异常: {e}", exc_info=True)
            return False

        finally:
            # 恢复鼠标加速设置
            self.restore_mouse_acceleration()

