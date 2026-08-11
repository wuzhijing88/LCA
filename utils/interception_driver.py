#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Interception DLL驱动模块
"""

import os
import time
import ctypes
import logging
import platform
import subprocess
import atexit
try:
    import winreg
except ImportError:
    winreg = None
from threading import RLock
from ctypes import wintypes, Structure, c_int, c_void_p, c_ushort, c_uint
from typing import Optional, Tuple
from utils.dpi_awareness import get_process_dpi_awareness
from utils.input_timing import DEFAULT_CLICK_HOLD_SECONDS, DEFAULT_KEY_HOLD_SECONDS
from utils.precise_sleep import precise_sleep as _shared_precise_sleep

logger = logging.getLogger(__name__)

# 获取DLL路径 - 根据系统架构选择
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 检测系统架构
def get_system_architecture() -> str:
    """检测系统架构，返回'x64'或'x86'"""
    machine = platform.machine().lower()
    if machine in ['amd64', 'x86_64']:
        return 'x64'
    elif machine in ['i386', 'i686', 'x86']:
        return 'x86'
    else:
        # 默认使用64位，因为现代Windows大多是64位
        logger.warning(f"未知系统架构: {machine}，默认使用x64")
        return 'x64'

# 根据架构选择DLL路径
SYSTEM_ARCH = get_system_architecture()
DLL_PATH = os.path.join(PROJECT_ROOT, "Interception", "library", SYSTEM_ARCH, "interception.dll")
INSTALLER_PATH = os.path.join(PROJECT_ROOT, "Interception", "command line installer", "install-interception.exe")

_KEYBOARD_CLASS_GUID = r"{4d36e96b-e325-11ce-bfc1-08002be10318}"
_MOUSE_CLASS_GUID = r"{4d36e96f-e325-11ce-bfc1-08002be10318}"
_KEYBOARD_FILTER_NAME = "keyboard"
_MOUSE_FILTER_NAME = "mouse"

logger.info(f"系统架构: {SYSTEM_ARCH}")
logger.info(f"驱动DLL路径: {DLL_PATH}")

# Interception常量
INTERCEPTION_MAX_KEYBOARD = 10
INTERCEPTION_MAX_MOUSE = 10
INTERCEPTION_MIN_KEYBOARD = 1
INTERCEPTION_MIN_MOUSE = INTERCEPTION_MAX_KEYBOARD + 1
INTERCEPTION_MAX_DEVICE = INTERCEPTION_MAX_KEYBOARD + INTERCEPTION_MAX_MOUSE
INTERCEPTION_HARDWARE_ID_BUFFER_SIZE = 1024

# 过滤器常量
INTERCEPTION_FILTER_NONE = 0x0000
INTERCEPTION_FILTER_KEY_ALL = 0xFFFF
INTERCEPTION_FILTER_MOUSE_ALL = 0xFFFF

INTERCEPTION_PREDICATE = ctypes.CFUNCTYPE(c_int, c_int)

# 键盘状态
INTERCEPTION_KEY_DOWN = 0x00
INTERCEPTION_KEY_UP = 0x01
INTERCEPTION_KEY_E0 = 0x02
INTERCEPTION_KEY_E1 = 0x04

# 鼠标状态（state字段）
INTERCEPTION_MOUSE_LEFT_BUTTON_DOWN = 0x001
INTERCEPTION_MOUSE_LEFT_BUTTON_UP = 0x002
INTERCEPTION_MOUSE_RIGHT_BUTTON_DOWN = 0x004
INTERCEPTION_MOUSE_RIGHT_BUTTON_UP = 0x008
INTERCEPTION_MOUSE_MIDDLE_BUTTON_DOWN = 0x010
INTERCEPTION_MOUSE_MIDDLE_BUTTON_UP = 0x020
INTERCEPTION_MOUSE_WHEEL = 0x400

# 鼠标状态（state字段）
INTERCEPTION_MOUSE_MOVE = 0x000

# 鼠标移动标志（flags字段）
INTERCEPTION_MOUSE_MOVE_RELATIVE = 0x000
INTERCEPTION_MOUSE_MOVE_ABSOLUTE = 0x001
INTERCEPTION_MOUSE_VIRTUAL_DESKTOP = 0x002  # 用于多显示器支持

_DEFAULT_KEY_HOLD_SECONDS = DEFAULT_KEY_HOLD_SECONDS
_DEFAULT_HOTKEY_HOLD_SECONDS = DEFAULT_KEY_HOLD_SECONDS
_DEFAULT_CLICK_HOLD_SECONDS = DEFAULT_CLICK_HOLD_SECONDS
_DEFAULT_PRE_BUTTON_SETTLE_SECONDS = 0.012
_DEFAULT_TARGET_PRIME_SETTLE_SECONDS = 0.0
_BUTTON_PRE_CLICK_RELEASE_SETTLE_SECONDS = 0.002


def _default_hotkey_hold_seconds() -> float:
    """默认组合键按住时长。"""
    return _DEFAULT_HOTKEY_HOLD_SECONDS


def _default_click_hold_seconds() -> float:
    """默认完整点击按住时长。"""
    return _DEFAULT_CLICK_HOLD_SECONDS


def _default_pre_button_settle_seconds() -> float:
    """默认点击前稳定等待。"""
    return _DEFAULT_PRE_BUTTON_SETTLE_SECONDS


def _default_target_prime_settle_seconds() -> float:
    """默认目标点预热后等待。"""
    return _DEFAULT_TARGET_PRIME_SETTLE_SECONDS


def _precise_sleep(duration: float) -> None:
    _shared_precise_sleep(duration)

# 结构体定义
class InterceptionKeyStroke(Structure):
    _fields_ = [
        ("code", wintypes.WORD),
        ("state", wintypes.WORD),
        ("information", wintypes.DWORD)
    ]

class InterceptionMouseStroke(Structure):
    _fields_ = [
        ("state", wintypes.WORD),      # unsigned short state
        ("flags", wintypes.WORD),      # unsigned short flags
        ("rolling", wintypes.SHORT),   # short rolling
        ("x", c_int),                  # int x
        ("y", c_int),                  # int y
        ("information", wintypes.DWORD) # unsigned int information
    ]

class InterceptionDriver:
    """Interception DLL驱动类"""
    _global_mouse_event_lock = RLock()
    _global_send_lock = RLock()
    _global_atomic_sequence_lock = RLock()
    
    # 按键扫描码映射
    KEY_CODES = {
        'a': 30, 'b': 48, 'c': 46, 'd': 32, 'e': 18, 'f': 33, 'g': 34, 'h': 35,
        'i': 23, 'j': 36, 'k': 37, 'l': 38, 'm': 50, 'n': 49, 'o': 24, 'p': 25,
        'q': 16, 'r': 19, 's': 31, 't': 20, 'u': 22, 'v': 47, 'w': 17, 'x': 45,
        'y': 21, 'z': 44,
        '1': 2, '2': 3, '3': 4, '4': 5, '5': 6, '6': 7, '7': 8, '8': 9, '9': 10, '0': 11,
        'enter': 28, 'space': 57, 'tab': 15, 'shift': 42, 'ctrl': 29, 'alt': 56,
        'esc': 1, 'escape': 1, 'backspace': 14, 'delete': 83,
        'up': 72, 'down': 80, 'left': 75, 'right': 77,
        'f1': 59, 'f2': 60, 'f3': 61, 'f4': 62, 'f5': 63, 'f6': 64,
        'f7': 65, 'f8': 66, 'f9': 67, 'f10': 68, 'f11': 87, 'f12': 88,
        'home': 71, 'end': 79, 'pageup': 73, 'pagedown': 81, 'insert': 82,
        'capslock': 58, 'numlock': 69, 'scrolllock': 70,
        'pause': 69, 'printscreen': 55,
        'lshift': 42, 'rshift': 54, 'lctrl': 29, 'rctrl': 29, 'lalt': 56, 'ralt': 56,
        'win': 91, 'lwin': 91, 'rwin': 92,
        'numpad0': 82, 'numpad1': 79, 'numpad2': 80, 'numpad3': 81, 'numpad4': 75,
        'numpad5': 76, 'numpad6': 77, 'numpad7': 71, 'numpad8': 72, 'numpad9': 73,
        'numpad+': 78, 'numpad-': 74, 'numpad*': 55, 'numpad/': 53, 'numpad.': 83,
        'numpadadd': 78, 'numpadsub': 74, 'numpadmult': 55, 'numpaddiv': 53, 'numpaddot': 83,
        # 特殊字符
        '!': 2, '@': 3, '#': 4, '$': 5, '%': 6, '^': 7, '&': 8, '*': 9, '(': 10, ')': 11,
        '-': 12, '=': 13, '[': 26, ']': 27, '\\': 43, ';': 39, "'": 40, '`': 41,
        ',': 51, '.': 52, '/': 53
    }
    KEY_ALIASES = {
        'return': 'enter',
        'spacebar': 'space',
        'control': 'ctrl',
        'page_up': 'pageup',
        'page_down': 'pagedown',
        'pgup': 'pageup',
        'pgdn': 'pagedown',
        'ins': 'insert',
        'del': 'delete',
        'caps': 'capslock',
        'scroll': 'scrolllock',
        'windows': 'win',
        'left_shift': 'lshift',
        'right_shift': 'rshift',
        'left_ctrl': 'lctrl',
        'right_ctrl': 'rctrl',
        'left_alt': 'lalt',
        'right_alt': 'ralt',
        'left_win': 'lwin',
        'right_win': 'rwin',
    }
    EXTENDED_KEYS_E0 = {
        'up', 'down', 'left', 'right',
        'home', 'end', 'pageup', 'pagedown', 'insert', 'delete',
        'rctrl', 'ralt', 'lwin', 'rwin', 'win', 'printscreen', 'numpad/'
    }
    EXTENDED_KEYS_E1 = {'pause'}
    
    def __init__(self):
        """初始化驱动"""
        self.dll = None
        self.context = None
        self.keyboard_device = INTERCEPTION_MIN_KEYBOARD
        self.mouse_device = INTERCEPTION_MIN_MOUSE
        self.initialized = False
        self.driver_just_installed = False  # 标记驱动是否刚刚安装
        self.driver_restart_required = False
        self.relative_move_scale = 1.0  # 与前台二保持一致：不做DPI补偿
        self._mouse_lock = RLock()
        self._key_lock = RLock()
        self._auto_install_attempted = False
        self._keyboard_predicate = None
        self._mouse_predicate = None
        self._all_devices_predicate = None
        # 保留成员以兼容旧代码路径；当前按住链路使用原子发送窗口，不再依赖预留时窗。
        self._key_release_reserve_window = 0.0
        # 追踪按下未释放的按键，停止/退出时强制回收，避免残留按键状态。
        self._pressed_keys = set()

    def initialize(self) -> bool:
        """初始化DLL驱动"""
        if self.initialized and self.context and self.dll:
            self._clear_event_filters()
            return True

        self.driver_just_installed = False
        self.driver_restart_required = False
        try:
            if not os.path.exists(DLL_PATH):
                logger.error(f"驱动文件不存在: {DLL_PATH}")
                logger.error("请确保驱动已正确安装在项目目录中")
                return False

            self.dll = ctypes.CDLL(DLL_PATH)
            self._configure_api_prototypes()
            self.context = self.dll.interception_create_context()

            if not self.context:
                logger.error("无法创建驱动上下文")
                if self._is_driver_registered():
                    self.driver_restart_required = True
                    logger.warning("检测到驱动已注册，但当前未生效")
                else:
                    install_result = self._try_auto_install_driver()
                    if install_result == "installed":
                        self.driver_just_installed = True
                        self.driver_restart_required = True
                        logger.warning("驱动安装完成，需要重启计算机使驱动生效")
                    elif install_result == "already_installed":
                        self.driver_restart_required = True
                        logger.warning("驱动已安装，但当前仍未生效")
                    elif install_result == "no_change":
                        logger.error("驱动安装程序执行成功，但未检测到驱动注册状态变化")
                self._keyboard_predicate = None
                self._mouse_predicate = None
                self.dll = None
                return False

            if not self._clear_event_filters():
                logger.error("驱动安全过滤器初始化失败")
                self.close()
                return False

            if not self._resolve_devices():
                logger.error("驱动设备检测失败")
                self.close()
                return False

            self.initialized = True
            logger.info("驱动初始化成功")

            self._detect_dpi_scale()
            return True

        except FileNotFoundError as e:
            logger.error(f"找不到驱动文件或依赖库: {e}")
            logger.error("请确保所有文件都在正确的位置")
            self.close()
            return False
        except OSError as e:
            logger.error(f"加载驱动时发生系统错误: {e}")
            logger.error("可能是文件损坏或版本不匹配")
            self.close()
            return False
        except Exception as e:
            logger.error(f"驱动初始化失败: {e}")
            self.close()
            return False

    def _configure_api_prototypes(self) -> None:
        """配置 Interception API 函数签名。"""
        self.dll.interception_create_context.restype = c_void_p
        self.dll.interception_destroy_context.argtypes = [c_void_p]
        self.dll.interception_set_filter.argtypes = [c_void_p, INTERCEPTION_PREDICATE, c_ushort]
        self.dll.interception_wait_with_timeout.argtypes = [c_void_p, c_uint]
        self.dll.interception_wait_with_timeout.restype = c_int
        self.dll.interception_receive.argtypes = [c_void_p, c_int, ctypes.c_void_p, c_uint]
        self.dll.interception_receive.restype = c_int
        self.dll.interception_send.argtypes = [c_void_p, c_int, ctypes.c_void_p, c_uint]
        self.dll.interception_send.restype = c_int
        self.dll.interception_get_hardware_id.argtypes = [c_void_p, c_int, ctypes.c_void_p, c_uint]
        self.dll.interception_get_hardware_id.restype = c_uint
        self.dll.interception_is_keyboard.argtypes = [c_int]
        self.dll.interception_is_keyboard.restype = c_int
        self.dll.interception_is_mouse.argtypes = [c_int]
        self.dll.interception_is_mouse.restype = c_int

    @staticmethod
    def _is_admin() -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    @staticmethod
    def _read_upper_filters(class_guid: str) -> Tuple[str, ...]:
        if winreg is None:
            return tuple()

        key_path = fr"SYSTEM\CurrentControlSet\Control\Class\{class_guid}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "UpperFilters")
        except FileNotFoundError:
            return tuple()
        except OSError as e:
            logger.warning(f"读取驱动注册表失败: {e}")
            return tuple()

        if isinstance(value, str):
            filters = [value]
        elif isinstance(value, (list, tuple)):
            filters = list(value)
        else:
            return tuple()

        return tuple(str(item).strip().lower() for item in filters if str(item).strip())

    @classmethod
    def _is_driver_registered(cls) -> bool:
        keyboard_filters = cls._read_upper_filters(_KEYBOARD_CLASS_GUID)
        mouse_filters = cls._read_upper_filters(_MOUSE_CLASS_GUID)
        return _KEYBOARD_FILTER_NAME in keyboard_filters and _MOUSE_FILTER_NAME in mouse_filters

    def get_restart_prompt_config(self) -> Optional[Tuple[str, str, str]]:
        if self.driver_just_installed:
            return (
                "需要重启计算机",
                "Interception 驱动已成功安装！",
                "驱动需要重启计算机后才能生效。\n\n"
                "请保存您的工作，然后重启计算机。\n"
                "重启后，前台模式功能将可以正常使用。",
            )

        if self.driver_restart_required:
            return (
                "驱动尚未生效",
                "Interception 驱动当前未生效。",
                "已检测到驱动注册信息，但当前仍无法创建驱动上下文。\n\n"
                "如果你已经重启过，说明这不是重复安装，而是驱动没有成功加载。\n"
                "请确认使用管理员权限运行，并检查系统安全拦截后再处理。",
            )

        return None

    def _is_keyboard_device(self, device: int) -> bool:
        try:
            return bool(self.dll and int(self.dll.interception_is_keyboard(int(device))) > 0)
        except Exception:
            return False

    def _is_mouse_device(self, device: int) -> bool:
        try:
            return bool(self.dll and int(self.dll.interception_is_mouse(int(device))) > 0)
        except Exception:
            return False

    def _clear_event_filters(self) -> bool:
        """
        清空上下文过滤器，避免任何拦截态导致系统键鼠不可用。
        """
        if not self.dll or not self.context:
            return True

        try:
            if self._all_devices_predicate is None:
                self._all_devices_predicate = INTERCEPTION_PREDICATE(lambda _device: 1)
            self.dll.interception_set_filter(
                self.context,
                self._all_devices_predicate,
                INTERCEPTION_FILTER_NONE,
            )
            return True
        except Exception as e:
            logger.error(f"清理事件过滤器失败: {e}")
            return False

    def _read_device_hardware_id(self, device: int) -> str:
        if not self.dll or not self.context:
            return ""

        try:
            buffer = ctypes.create_string_buffer(INTERCEPTION_HARDWARE_ID_BUFFER_SIZE)
            length = int(
                self.dll.interception_get_hardware_id(
                    self.context,
                    int(device),
                    buffer,
                    INTERCEPTION_HARDWARE_ID_BUFFER_SIZE,
                )
            )
            if length <= 0:
                return ""

            raw = bytes(buffer)[: min(length, INTERCEPTION_HARDWARE_ID_BUFFER_SIZE)]
            if b"\x00" in raw:
                raw = raw.split(b"\x00", 1)[0]
            if not raw:
                return ""
            return raw.decode("utf-8", errors="ignore").strip()
        except Exception:
            return ""

    def _resolve_device_by_hardware_id(self, device_begin: int, device_end: int, device_kind: str) -> Optional[int]:
        first_candidate: Optional[int] = None
        for device in range(int(device_begin), int(device_end) + 1):
            if device_kind == "keyboard":
                if not self._is_keyboard_device(device):
                    continue
            elif device_kind == "mouse":
                if not self._is_mouse_device(device):
                    continue
            else:
                continue

            if first_candidate is None:
                first_candidate = int(device)

            hardware_id = self._read_device_hardware_id(device)
            if hardware_id:
                return int(device)
        return first_candidate

    def _resolve_devices(self) -> bool:
        keyboard_device = self._resolve_device_by_hardware_id(
            INTERCEPTION_MIN_KEYBOARD,
            INTERCEPTION_MAX_KEYBOARD,
            "keyboard",
        )
        mouse_device = self._resolve_device_by_hardware_id(
            INTERCEPTION_MIN_MOUSE,
            INTERCEPTION_MAX_DEVICE,
            "mouse",
        )

        if keyboard_device is None or mouse_device is None:
            logger.error(f"未检测到可用输入设备: keyboard={keyboard_device}, mouse={mouse_device}")
            return False

        self.keyboard_device = int(keyboard_device)
        self.mouse_device = int(mouse_device)
        logger.info(f"驱动设备绑定完成: keyboard={self.keyboard_device}, mouse={self.mouse_device}")
        return True

    def _try_auto_install_driver(self) -> str:
        """尝试自动安装 Interception 驱动（仅在当前进程执行一次）。"""
        if self._auto_install_attempted:
            return "skipped"
        self._auto_install_attempted = True

        if not os.path.exists(INSTALLER_PATH):
            logger.warning(f"驱动安装程序不存在: {INSTALLER_PATH}")
            return "failed"

        if not self._is_admin():
            logger.error("自动安装驱动需要管理员权限")
            return "failed"

        installed_before = self._is_driver_registered()

        try:
            result = subprocess.run(
                [INSTALLER_PATH, "/install"],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if int(result.returncode) != 0:
                logger.error(f"驱动安装失败，返回码: {result.returncode}")
                return "failed"

            installed_after = self._is_driver_registered()
            if installed_after and not installed_before:
                return "installed"
            if installed_after and installed_before:
                return "already_installed"

            return "no_change"
        except subprocess.TimeoutExpired:
            logger.error("驱动安装超时")
            return "failed"
        except Exception as e:
            logger.error(f"自动安装驱动失败: {e}")
            return "failed"

    def _detect_dpi_scale(self):
        """自动检测DPI缩放因子
        仅使用后台API查询，不做前台位移采样。
        """
        try:
            awareness = self._get_process_dpi_awareness()
            monitor_dpi = self._get_monitor_effective_dpi()
            system_dpi = self._get_system_dpi()

            scale = 1.0
            awareness_desc = "unknown"

            # PROCESS_DPI_UNAWARE = 0, PROCESS_SYSTEM_DPI_AWARE = 1, PROCESS_PER_MONITOR_DPI_AWARE = 2
            if awareness == 2:
                awareness_desc = "per_monitor_aware"
            elif awareness == 1:
                awareness_desc = "system_aware"
            elif awareness == 0:
                awareness_desc = "dpi_unaware"
            else:
                awareness_desc = "unknown"

            # 以前台二为基准：Interception 不做DPI缩放补偿，统一按传入坐标执行。
            self.relative_move_scale = 1.0
            logger.info(
                f"DPI缩放因子检测(后台API): awareness={awareness_desc}({awareness}), "
                f"monitor_dpi={monitor_dpi}, system_dpi={system_dpi}, "
                f"relative补偿={self.relative_move_scale:.4f}"
            )

        except Exception as e:
            logger.warning(f"DPI缩放因子检测失败: {e}，使用默认值1.0")
            self.relative_move_scale = 1.0

    def _get_process_dpi_awareness(self) -> Optional[int]:
        """获取当前进程DPI感知级别。"""
        try:
            return get_process_dpi_awareness()
        except Exception:
            return None

    def _get_system_dpi(self) -> Optional[int]:
        """获取系统DPI。"""
        try:
            user32 = ctypes.windll.user32
            if hasattr(user32, "GetDpiForSystem"):
                dpi = int(user32.GetDpiForSystem())
                if dpi > 0:
                    return dpi
        except Exception:
            pass

        # 兼容旧系统
        try:
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            LOGPIXELSX = 88
            hdc = user32.GetDC(0)
            if hdc:
                dpi = int(gdi32.GetDeviceCaps(hdc, LOGPIXELSX))
                user32.ReleaseDC(0, hdc)
                if dpi > 0:
                    return dpi
        except Exception:
            pass
        return None

    def _get_monitor_effective_dpi(self) -> Optional[int]:
        """获取光标所在显示器的有效DPI。"""
        try:
            user32 = ctypes.windll.user32
            shcore = ctypes.windll.shcore
            point = wintypes.POINT()
            if not user32.GetCursorPos(ctypes.byref(point)):
                return None

            MONITOR_DEFAULTTONEAREST = 2
            MDT_EFFECTIVE_DPI = 0
            hmonitor = user32.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
            if not hmonitor:
                return None

            dpi_x = c_uint(0)
            dpi_y = c_uint(0)
            hr = shcore.GetDpiForMonitor(hmonitor, MDT_EFFECTIVE_DPI, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
            if hr == 0 and dpi_x.value > 0:
                return int(dpi_x.value)
        except Exception:
            pass
        return None

    def _get_current_mouse_pos(self) -> Tuple[int, int]:
        """获取当前鼠标位置（像素坐标）"""
        try:
            point = wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
            return point.x, point.y
        except:
            return 0, 0

    def _wait_mouse_reach_target(
        self,
        target_x: int,
        target_y: int,
        timeout: float = 0.08,
        tolerance: int = 2,
        poll_interval: float = 0.002,
        stable_samples: int = 1,
    ) -> bool:
        deadline = time.perf_counter() + max(0.0, timeout)
        required_samples = max(1, int(stable_samples))
        stable_count = 0
        while time.perf_counter() <= deadline:
            current_x, current_y = self._get_current_mouse_pos()
            if abs(current_x - target_x) <= tolerance and abs(current_y - target_y) <= tolerance:
                stable_count += 1
                if stable_count >= required_samples:
                    return True
            else:
                stable_count = 0
            _precise_sleep(max(0.001, poll_interval))
        return self._is_mouse_at_target(target_x, target_y, tolerance=tolerance)

    def _is_mouse_at_target(self, target_x: int, target_y: int, tolerance: int = 2) -> bool:
        """检查鼠标是否在目标坐标附近。"""
        current_x, current_y = self._get_current_mouse_pos()
        return abs(current_x - int(target_x)) <= tolerance and abs(current_y - int(target_y)) <= tolerance

    def _clip_cursor_to_point(self, target_x: int, target_y: int) -> bool:
        """将系统光标临时限制在目标点，防止发键瞬间漂移。"""
        tx = int(target_x)
        ty = int(target_y)
        rect = wintypes.RECT(tx, ty, tx + 1, ty + 1)
        try:
            return bool(ctypes.windll.user32.ClipCursor(ctypes.byref(rect)))
        except Exception:
            return False

    def _release_cursor_clip(self) -> None:
        """释放系统光标限制。"""
        try:
            ctypes.windll.user32.ClipCursor(None)
        except Exception:
            pass

    @staticmethod
    def _is_mouse_down_state(button_state: int) -> bool:
        return int(button_state) in (
            INTERCEPTION_MOUSE_LEFT_BUTTON_DOWN,
            INTERCEPTION_MOUSE_RIGHT_BUTTON_DOWN,
            INTERCEPTION_MOUSE_MIDDLE_BUTTON_DOWN,
        )

    @staticmethod
    def _mouse_button_name_from_state(button_state: int) -> str:
        state = int(button_state)
        if state in (INTERCEPTION_MOUSE_LEFT_BUTTON_DOWN, INTERCEPTION_MOUSE_LEFT_BUTTON_UP):
            return "left"
        if state in (INTERCEPTION_MOUSE_RIGHT_BUTTON_DOWN, INTERCEPTION_MOUSE_RIGHT_BUTTON_UP):
            return "right"
        if state in (INTERCEPTION_MOUSE_MIDDLE_BUTTON_DOWN, INTERCEPTION_MOUSE_MIDDLE_BUTTON_UP):
            return "middle"
        return f"state_{state}"

    @staticmethod
    def _mouse_button_vk_from_state(button_state: int) -> Optional[int]:
        state = int(button_state)
        if state in (INTERCEPTION_MOUSE_LEFT_BUTTON_DOWN, INTERCEPTION_MOUSE_LEFT_BUTTON_UP):
            return 0x01  # VK_LBUTTON
        if state in (INTERCEPTION_MOUSE_RIGHT_BUTTON_DOWN, INTERCEPTION_MOUSE_RIGHT_BUTTON_UP):
            return 0x02  # VK_RBUTTON
        if state in (INTERCEPTION_MOUSE_MIDDLE_BUTTON_DOWN, INTERCEPTION_MOUSE_MIDDLE_BUTTON_UP):
            return 0x04  # VK_MBUTTON
        return None

    def _is_mouse_button_pressed(self, button_state: int) -> bool:
        vk_code = self._mouse_button_vk_from_state(button_state)
        if vk_code is None:
            return False
        try:
            return bool(ctypes.windll.user32.GetAsyncKeyState(vk_code) & 0x8000)
        except Exception:
            return False

    def _prepare_button_release_for_click(
        self,
        down_state: int,
        up_state: int,
        target_x: int,
        target_y: int,
    ) -> None:
        """
        完整点击前做一次按钮状态归一化。
        这里仅做“尽力释放”，不以系统按键状态作为失败判据，避免在游戏前台中误判。
        """
        tx = int(target_x)
        ty = int(target_y)
        if self._is_mouse_button_pressed(down_state):
            try:
                self._send_mouse_button_event_at_target_once(
                    up_state,
                    tx,
                    ty,
                    source="click_prepare_release",
                    enforce_target=False,
                )
                _precise_sleep(0.002)
                if self._is_mouse_button_pressed(down_state):
                    self._send_mouse_button_event_at_target_once(
                        up_state,
                        tx,
                        ty,
                        source="click_prepare_release_retry",
                        enforce_target=False,
                    )
            except Exception:
                pass
        _precise_sleep(_BUTTON_PRE_CLICK_RELEASE_SETTLE_SECONDS)

    @staticmethod
    def _is_vk_pressed(vk_code: Optional[int]) -> bool:
        if vk_code is None:
            return False
        try:
            return bool(ctypes.windll.user32.GetAsyncKeyState(int(vk_code)) & 0x8000)
        except Exception:
            return False

    @staticmethod
    def _scan_code_to_vk(scan_code: int, use_e0: bool = False, use_e1: bool = False) -> Optional[int]:
        try:
            source_code = int(scan_code) & 0xFF
            if use_e0:
                source_code |= 0xE000
            elif use_e1:
                source_code |= 0xE100
            MAPVK_VSC_TO_VK_EX = 3
            vk_code = int(ctypes.windll.user32.MapVirtualKeyW(source_code, MAPVK_VSC_TO_VK_EX))
            if vk_code <= 0:
                return None
            return vk_code & 0xFF
        except Exception:
            return None

    @staticmethod
    def _high_precision_hold_sleep(duration_seconds: float) -> None:
        """高精度保持时长：粗睡眠+收口轮询，保持阶段临时提高计时精度和线程优先级。"""
        try:
            target_seconds = max(0.0, float(duration_seconds))
        except Exception:
            target_seconds = 0.0
        if target_seconds <= 0:
            return

        timer_raised = False
        thread_handle = None
        has_original_priority = False
        original_priority = 0
        THREAD_PRIORITY_HIGHEST = 2
        THREAD_PRIORITY_ERROR_RETURN = 2147483647

        try:
            try:
                begin_result = ctypes.windll.winmm.timeBeginPeriod(1)
                if int(begin_result) == 0:
                    timer_raised = True
            except Exception:
                timer_raised = False

            try:
                thread_handle = ctypes.windll.kernel32.GetCurrentThread()
                if thread_handle:
                    current_priority = int(ctypes.windll.kernel32.GetThreadPriority(thread_handle))
                    if current_priority != THREAD_PRIORITY_ERROR_RETURN:
                        original_priority = current_priority
                        has_original_priority = True
                        if current_priority < THREAD_PRIORITY_HIGHEST:
                            ctypes.windll.kernel32.SetThreadPriority(thread_handle, THREAD_PRIORITY_HIGHEST)
            except Exception:
                has_original_priority = False

            end_ts = time.perf_counter() + target_seconds
            while True:
                remaining = end_ts - time.perf_counter()
                if remaining <= 0:
                    break

                if remaining > 0.018:
                    sleep_seconds = max(0.0, remaining - 0.012)
                    sleep_ms = int(sleep_seconds * 1000.0)
                    if sleep_ms > 0:
                        try:
                            ctypes.windll.kernel32.Sleep(sleep_ms)
                        except Exception:
                            _precise_sleep(sleep_seconds)
                    else:
                        try:
                            ctypes.windll.kernel32.Sleep(0)
                        except Exception:
                            _precise_sleep(0.0)
                elif remaining > 0.002:
                    try:
                        ctypes.windll.kernel32.Sleep(0)
                    except Exception:
                        _precise_sleep(0.0)
        finally:
            if has_original_priority and thread_handle:
                try:
                    ctypes.windll.kernel32.SetThreadPriority(thread_handle, int(original_priority))
                except Exception:
                    pass
            if timer_raised:
                try:
                    ctypes.windll.winmm.timeEndPeriod(1)
                except Exception:
                    pass

    def _log_mouse_down_snapshot(
        self,
        button_state: int,
        target_x: Optional[int] = None,
        target_y: Optional[int] = None,
        source: str = "unknown",
    ) -> None:
        """记录鼠标按下瞬间系统光标坐标。"""
        if not self._is_mouse_down_state(button_state):
            return
        try:
            current_x, current_y = self._get_current_mouse_pos()
            button_name = self._mouse_button_name_from_state(button_state)
            if target_x is None or target_y is None:
                logger.info(
                    f"[按下快照] 来源={source}, 按键={button_name}, 当前坐标=({current_x}, {current_y})"
                )
                return

            tx = int(target_x)
            ty = int(target_y)
            delta_x = int(current_x) - tx
            delta_y = int(current_y) - ty
            logger.info(
                f"[按下快照] 来源={source}, 按键={button_name}, 当前坐标=({current_x}, {current_y}), "
                f"目标坐标=({tx}, {ty}), 偏差=({delta_x}, {delta_y})"
            )
        except Exception:
            pass

    def _ensure_cursor_at_target(
        self,
        target_x: int,
        target_y: int,
        timeout: float = 0.35,
        tolerance: int = 0,
        stable_samples: int = 1,
    ) -> bool:
        """统一到位复核：驱动移动 + 系统定位兜底，直到到位或超时。"""
        tx = int(target_x)
        ty = int(target_y)
        tol = max(0, int(tolerance))
        required_stable_samples = max(1, int(stable_samples))
        deadline = time.perf_counter() + max(0.01, float(timeout))

        while time.perf_counter() <= deadline:
            if self._wait_mouse_reach_target(
                tx,
                ty,
                timeout=0.008,
                tolerance=tol,
                poll_interval=0.001,
                stable_samples=required_stable_samples,
            ):
                return True

            try:
                self._move_mouse_internal(tx, ty, absolute=True)
            except Exception:
                pass
            if self._wait_mouse_reach_target(
                tx,
                ty,
                timeout=0.02,
                tolerance=tol,
                poll_interval=0.001,
                stable_samples=required_stable_samples,
            ):
                return True

            try:
                ctypes.windll.user32.SetCursorPos(tx, ty)
            except Exception:
                pass
            if self._wait_mouse_reach_target(
                tx,
                ty,
                timeout=0.02,
                tolerance=tol,
                poll_interval=0.001,
                stable_samples=required_stable_samples,
            ):
                return True

            _precise_sleep(0.001)

        return self._is_mouse_at_target(tx, ty, tolerance=tol)

    def _prime_mouse_target_for_click(self, target_x: int, target_y: int) -> bool:
        """
        在按键前向目标点注入一次绝对移动事件，降低前台目标“位置已显示但命中未同步”的漏点概率。
        """
        tx = int(target_x)
        ty = int(target_y)
        try:
            interception_x, interception_y = self._pixel_to_interception(tx, ty)
        except Exception:
            return False

        flags = INTERCEPTION_MOUSE_MOVE_ABSOLUTE | INTERCEPTION_MOUSE_VIRTUAL_DESKTOP
        moved = self._send_mouse_event(interception_x, interception_y, flags, INTERCEPTION_MOUSE_MOVE, 0)
        if moved:
            _precise_sleep(_default_target_prime_settle_seconds())
        return bool(moved)

    def _send_mouse_button_event_at_target_once(
        self,
        button_state: int,
        target_x: int,
        target_y: int,
        source: str = "button_at_target",
        enforce_target: bool = True,
    ) -> bool:
        """
        在目标坐标发送单次鼠标按键事件。
        先确保光标到位，再发送“携带目标绝对坐标的按键事件”。
        严禁回退到无坐标按键事件，避免误点到当前鼠标位置。
        """
        tx = int(target_x)
        ty = int(target_y)
        self._log_mouse_down_snapshot(button_state, tx, ty, source=source)
        if not self._is_mouse_at_target(tx, ty, tolerance=1):
            if enforce_target:
                if not self._ensure_cursor_at_target(
                    tx,
                    ty,
                    timeout=0.08,
                    tolerance=1,
                    stable_samples=2,
                ):
                    return False
            else:
                if not self._move_mouse_internal(tx, ty, absolute=True):
                    return False
                if not self._is_mouse_at_target(tx, ty, tolerance=2):
                    return False
        # 关键：按钮事件必须携带目标绝对坐标，避免按“旧位置”消费点击。
        # 不再回退纯按钮事件，以免点击落在原位置。
        try:
            interception_x, interception_y = self._pixel_to_interception(tx, ty)
            coord_flags = INTERCEPTION_MOUSE_MOVE_ABSOLUTE | INTERCEPTION_MOUSE_VIRTUAL_DESKTOP
            for _ in range(2):
                if self._send_mouse_event(interception_x, interception_y, coord_flags, button_state, 0):
                    return True
                if not self._ensure_cursor_at_target(
                    tx,
                    ty,
                    timeout=0.03,
                    tolerance=1,
                    stable_samples=1,
                ):
                    break
        except Exception:
            pass
        return False

    def _send_mouse_button_event_strict(
        self,
        button_state: int,
        target_x: Optional[int] = None,
        target_y: Optional[int] = None,
    ) -> bool:
        """统一鼠标按键入口：坐标模式严格复核，非坐标模式直接发键。"""
        if (target_x is None) != (target_y is None):
            logger.error("invalid mouse button coordinates: x and y must both be provided")
            return False

        # 非坐标按键
        if target_x is None or target_y is None:
            logger.error("foreground strict mode requires coordinates for mouse button events")
            return False

        tx = int(target_x)
        ty = int(target_y)
        is_down_event = self._is_mouse_down_state(button_state)

        # 坐标模式：严格落位成功后才允许发键，避免误点。
        with InterceptionDriver._global_mouse_event_lock:
            if is_down_event:
                if not self._ensure_cursor_at_target(
                    tx,
                    ty,
                    timeout=0.26,
                    tolerance=1,
                    stable_samples=2,
                ):
                    return False

            cursor_clipped = False
            if is_down_event:
                try:
                    cursor_clipped = self._clip_cursor_to_point(tx, ty)
                except Exception:
                    cursor_clipped = False

            try:
                if is_down_event:
                    self._prime_mouse_target_for_click(tx, ty)
                    _precise_sleep(_default_pre_button_settle_seconds())
                else:
                    _precise_sleep(0.001)

                result = self._send_mouse_button_event_at_target_once(
                    button_state,
                    tx,
                    ty,
                    source="button_verified",
                    enforce_target=is_down_event,
                )
                if not result:
                    _precise_sleep(0.003)
                    result = self._send_mouse_button_event_at_target_once(
                        button_state,
                        tx,
                        ty,
                        source="button_retry",
                        enforce_target=is_down_event,
                    )
                if result:
                    _precise_sleep(0.001)
                return result
            finally:
                if cursor_clipped:
                    self._release_cursor_clip()

    def _send_mouse_click_event_strict(
        self,
        down_state: int,
        up_state: int,
        target_x: int,
        target_y: int,
        hold_duration: Optional[float] = None,
    ) -> bool:
        """
        完整点击原子链路：同一轮落位/夹取内连续发送 down+up。
        仅“仅按下/仅松开”场景才调用分离事件接口。
        """
        tx = int(target_x)
        ty = int(target_y)

        with InterceptionDriver._global_mouse_event_lock:
            if not self._ensure_cursor_at_target(
                tx,
                ty,
                timeout=0.26,
                tolerance=1,
                stable_samples=2,
            ):
                return False

            cursor_clipped = False
            button_down_sent = False
            try:
                cursor_clipped = self._clip_cursor_to_point(tx, ty)
            except Exception:
                cursor_clipped = False

            try:
                self._prime_mouse_target_for_click(tx, ty)
                _precise_sleep(_default_pre_button_settle_seconds())
                if not self._ensure_cursor_at_target(
                    tx,
                    ty,
                    timeout=0.08,
                    tolerance=1,
                    stable_samples=2,
                ):
                    return False
                # 完整点击在同一发送窗口完成，避免并发事件插队导致漏点/点偏。
                with InterceptionDriver._global_send_lock:
                    self._prepare_button_release_for_click(
                        down_state,
                        up_state,
                        tx,
                        ty,
                    )

                    down_ok = self._send_mouse_button_event_at_target_once(
                        down_state,
                        tx,
                        ty,
                        source="click_down",
                        enforce_target=True,
                    )
                    if not down_ok:
                        _precise_sleep(0.002)
                        down_ok = self._send_mouse_button_event_at_target_once(
                            down_state,
                            tx,
                            ty,
                            source="click_down_retry",
                            enforce_target=True,
                        )
                    if not down_ok:
                        return False
                    button_down_sent = True

                    if hold_duration is None:
                        hold_seconds = _default_click_hold_seconds()
                    else:
                        try:
                            hold_seconds = max(0.0, float(hold_duration))
                        except Exception:
                            hold_seconds = 0.0
                    if hold_seconds > 0:
                        # 对齐前台二(PyAutoGUI)点击按住时序，统一使用共享精确睡眠。
                        _precise_sleep(hold_seconds)

                    up_ok = self._send_mouse_button_event_at_target_once(
                        up_state,
                        tx,
                        ty,
                        source="click_up",
                        enforce_target=True,
                    )
                    if not up_ok:
                        _precise_sleep(0.002)
                        up_ok = self._send_mouse_button_event_at_target_once(
                            up_state,
                            tx,
                            ty,
                            source="click_up_retry",
                            enforce_target=True,
                        )
                    if not up_ok:
                        return False

                button_down_sent = False
                return True
            finally:
                if button_down_sent:
                    try:
                        self._send_mouse_button_event_at_target_once(
                            up_state,
                            tx,
                            ty,
                            source="click_up_finalize",
                            enforce_target=False,
                        )
                    except Exception:
                        pass
                if cursor_clipped:
                    self._release_cursor_clip()

    def _pixel_to_interception(self, x: int, y: int) -> Tuple[int, int]:
        """将像素坐标转换为内部坐标格式（支持多显示器）"""
        try:
            # 使用虚拟屏幕尺寸支持多显示器
            SM_XVIRTUALSCREEN = 76
            SM_YVIRTUALSCREEN = 77
            SM_CXVIRTUALSCREEN = 78
            SM_CYVIRTUALSCREEN = 79

            v_left = ctypes.windll.user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            v_top = ctypes.windll.user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            v_width = ctypes.windll.user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            v_height = ctypes.windll.user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

            logger.info(f"[坐标转换] 输入像素: ({x}, {y}), 虚拟屏幕: left={v_left}, top={v_top}, width={v_width}, height={v_height}")

            # 转换为内部坐标系统（相对于虚拟屏幕）
            # 使用 width-1/height-1 并四舍五入，减少系统性左上偏移
            width_span = max(1, int(v_width) - 1)
            height_span = max(1, int(v_height) - 1)
            interception_x = int(round(((int(x) - int(v_left)) * 65535) / width_span))
            interception_y = int(round(((int(y) - int(v_top)) * 65535) / height_span))

            logger.info(f"[坐标转换] 输出interception: ({interception_x}, {interception_y})")

            # 确保坐标在有效范围内
            interception_x = max(0, min(65535, interception_x))
            interception_y = max(0, min(65535, interception_y))

            return interception_x, interception_y
        except Exception as e:
            logger.error(f"坐标转换失败: {e}")
            return x, y  # 失败时返回原坐标

    def _interception_to_pixel(self, x: int, y: int) -> Tuple[int, int]:
        """将内部坐标格式转换为像素坐标（支持多显示器）"""
        try:
            # 使用虚拟屏幕尺寸支持多显示器
            SM_XVIRTUALSCREEN = 76
            SM_YVIRTUALSCREEN = 77
            SM_CXVIRTUALSCREEN = 78
            SM_CYVIRTUALSCREEN = 79

            v_left = ctypes.windll.user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            v_top = ctypes.windll.user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            v_width = ctypes.windll.user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            v_height = ctypes.windll.user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

            # 从内部坐标系统转换为像素（相对于虚拟屏幕）
            width_span = max(1, int(v_width) - 1)
            height_span = max(1, int(v_height) - 1)
            pixel_x = int(round((int(x) * width_span) / 65535.0)) + int(v_left)
            pixel_y = int(round((int(y) * height_span) / 65535.0)) + int(v_top)

            return pixel_x, pixel_y
        except Exception as e:
            logger.error(f"坐标转换失败: {e}")
            return x, y  # 失败时返回原坐标

    def _normalize_key_name(self, key: str) -> str:
        text = str(key or "").strip().lower()
        if not text:
            return ""
        return self.KEY_ALIASES.get(text, text)

    def _resolve_scan_code(self, key: str) -> Tuple[Optional[int], bool, bool]:
        normalized_key = self._normalize_key_name(key)
        if not normalized_key:
            return None, False, False
        scan_code = self.KEY_CODES.get(normalized_key)
        if scan_code is None:
            return None, False, False
        use_e1 = normalized_key in self.EXTENDED_KEYS_E1
        use_e0 = (normalized_key in self.EXTENDED_KEYS_E0) and not use_e1
        return scan_code, use_e0, use_e1

    def _send_key_event(self, scan_code: int, key_down: bool, use_e0: bool = False, use_e1: bool = False) -> bool:
        """发送键盘事件"""
        if not self.initialized:
            if not self.initialize():
                return False
        
        try:
            stroke = InterceptionKeyStroke()
            stroke.code = scan_code
            state = INTERCEPTION_KEY_DOWN if key_down else INTERCEPTION_KEY_UP
            if use_e0:
                state |= INTERCEPTION_KEY_E0
            if use_e1:
                state |= INTERCEPTION_KEY_E1
            stroke.state = state
            stroke.information = 0
            
            with InterceptionDriver._global_send_lock:
                result = self.dll.interception_send(
                    self.context,
                    self.keyboard_device,
                    ctypes.byref(stroke),
                    1
                )
            
            return result > 0
            
        except Exception as e:
            logger.error(f"发送键盘事件失败: {e}")
            return False

    def _send_mouse_event(self, x: int = 0, y: int = 0, flags: int = 0, state: int = 0, rolling: int = 0) -> bool:
        """发送鼠标事件"""
        if not self.initialized:
            if not self.initialize():
                return False

        logger.debug(f"_send_mouse_event: x={x}, y={y}, flags={flags}")

        try:
            stroke = InterceptionMouseStroke()
            stroke.x = x
            stroke.y = y
            stroke.flags = flags
            stroke.state = state
            stroke.rolling = rolling
            stroke.information = 0

            with InterceptionDriver._global_mouse_event_lock:
                with InterceptionDriver._global_send_lock:
                    result = self.dll.interception_send(
                        self.context,
                        self.mouse_device,
                        ctypes.byref(stroke),
                        1
                    )

            return result > 0

        except Exception as e:
            logger.error(f"发送鼠标事件失败: {e}")
            return False
    
    def press_key(self, key: str, duration: float = _DEFAULT_KEY_HOLD_SECONDS) -> bool:
        """按下并释放按键"""
        scan_code, use_e0, use_e1 = self._resolve_scan_code(key)
        if scan_code is None:
            logger.warning(f"未知按键: {key}")
            return False
        key_signature = (int(scan_code), bool(use_e0), bool(use_e1))

        try:
            hold_duration = float(duration)
        except Exception:
            hold_duration = _DEFAULT_KEY_HOLD_SECONDS
        if hold_duration < 0:
            hold_duration = 0.0

        down_sent = False
        with InterceptionDriver._global_atomic_sequence_lock:
            with self._key_lock:
                # 单键按住在同一发送窗口内执行，避免并发发送插队导致固定时长漂移。
                with InterceptionDriver._global_send_lock:
                    try:
                        if not self._send_key_event(scan_code, True, use_e0=use_e0, use_e1=use_e1):
                            return False
                        down_sent = True
                        self._pressed_keys.add(key_signature)

                        if hold_duration > 0:
                            self._high_precision_hold_sleep(hold_duration)

                        result_up = self._send_key_event(scan_code, False, use_e0=use_e0, use_e1=use_e1)
                        if result_up:
                            down_sent = False
                            self._pressed_keys.discard(key_signature)
                            return True

                        _precise_sleep(0.001)
                        result_up_retry = self._send_key_event(scan_code, False, use_e0=use_e0, use_e1=use_e1)
                        if result_up_retry:
                            self._pressed_keys.discard(key_signature)
                        down_sent = not result_up_retry
                        return result_up_retry
                    finally:
                        if down_sent:
                            try:
                                self._send_key_event(scan_code, False, use_e0=use_e0, use_e1=use_e1)
                            except Exception:
                                pass
                            finally:
                                self._pressed_keys.discard(key_signature)

    def key_down(self, key: str) -> bool:
        """按下按键（不释放）"""
        scan_code, use_e0, use_e1 = self._resolve_scan_code(key)
        if scan_code is None:
            logger.warning(f"未知按键: {key}")
            return False
        key_signature = (int(scan_code), bool(use_e0), bool(use_e1))

        with InterceptionDriver._global_atomic_sequence_lock:
            with self._key_lock:
                result = self._send_key_event(scan_code, True, use_e0=use_e0, use_e1=use_e1)
                if result:
                    self._pressed_keys.add(key_signature)
                return result

    def key_up(self, key: str) -> bool:
        """释放按键"""
        scan_code, use_e0, use_e1 = self._resolve_scan_code(key)
        if scan_code is None:
            logger.warning(f"未知按键: {key}")
            return False
        key_signature = (int(scan_code), bool(use_e0), bool(use_e1))

        with InterceptionDriver._global_atomic_sequence_lock:
            with self._key_lock:
                result = self._send_key_event(scan_code, False, use_e0=use_e0, use_e1=use_e1)
                if result:
                    self._pressed_keys.discard(key_signature)
                return result

    def release_all_keys(self) -> bool:
        """释放当前驱动记录的所有按下按键。"""
        if not self._pressed_keys:
            return True

        if not (self.context and self.dll and self.initialized):
            self._pressed_keys.clear()
            return True

        release_ok = True
        with InterceptionDriver._global_atomic_sequence_lock:
            with self._key_lock:
                for scan_code, use_e0, use_e1 in list(reversed(tuple(self._pressed_keys))):
                    try:
                        if not self._send_key_event(
                            int(scan_code),
                            False,
                            use_e0=bool(use_e0),
                            use_e1=bool(use_e1),
                        ):
                            release_ok = False
                        else:
                            self._pressed_keys.discard((int(scan_code), bool(use_e0), bool(use_e1)))
                    except Exception:
                        release_ok = False
                        self._pressed_keys.discard((int(scan_code), bool(use_e0), bool(use_e1)))

        if self._pressed_keys:
            release_ok = False
            self._pressed_keys.clear()
        return release_ok
    
    def type_text(self, text: str, delay: float = 0.05, use_clipboard: bool = True) -> bool:
        """输入文本

        支持英文、中文、特殊符号等所有 Unicode 字符
        优先使用剪贴板粘贴（支持所有字符），回退到按键模拟（仅支持英文字符）
        """
        # 方法1：优先使用剪贴板粘贴（支持所有字符包括中文）
        if use_clipboard:
            try:
                import pyperclip

                original_clipboard = None
                try:
                    original_clipboard = pyperclip.paste()
                except:
                    pass

                try:
                    # 复制文本到剪贴板
                    pyperclip.copy(text)
                    _precise_sleep(0.1)

                    # 发送粘贴快捷键 (Ctrl+V)
                    if self.hotkey('ctrl', 'v'):
                        _precise_sleep(0.2)

                        # 恢复剪贴板
                        if original_clipboard:
                            try:
                                pyperclip.copy(original_clipboard)
                            except:
                                pass

                        logger.debug(f"使用剪贴板粘贴输入文本: '{text[:50]}'...")
                        return True
                except Exception as clipboard_error:
                    logger.debug(f"剪贴板粘贴失败: {clipboard_error}，回退到按键模拟")

                    # 恢复剪贴板
                    if original_clipboard:
                        try:
                            pyperclip.copy(original_clipboard)
                        except:
                            pass
            except ImportError:
                logger.debug("pyperclip不可用，使用按键模拟")

        # 方法2：回退到按键模拟（仅支持 KEY_CODES 中定义的字符）
        logger.debug(f"使用按键模拟输入文本，仅支持英文字符: '{text[:50]}'...")

        for char in text:
            if char == ' ':
                key = 'space'
            elif char == '\n':
                key = 'enter'
            elif char == '\t':
                key = 'tab'
            elif char.lower() in self.KEY_CODES:
                key = char.lower()
            else:
                logger.debug(f"无法输入字符（跳过）: {char}")
                continue

            if not self.press_key(key, delay):
                return False
            _precise_sleep(delay)

        return True
    
    def hotkey(self, *keys) -> bool:
        """组合键"""
        key_strokes = []
        
        for key in keys:
            scan_code, use_e0, use_e1 = self._resolve_scan_code(key)
            if scan_code is None:
                logger.warning(f"未知按键: {key}")
                return False
            key_strokes.append((scan_code, use_e0, use_e1))
        
        with InterceptionDriver._global_atomic_sequence_lock:
            with self._key_lock:
                # 按下所有键
                for scan_code, use_e0, use_e1 in key_strokes:
                    self._send_key_event(scan_code, True, use_e0=use_e0, use_e1=use_e1)
                    _precise_sleep(0.01)

                self._high_precision_hold_sleep(_default_hotkey_hold_seconds())

                # 释放所有键（逆序）
                for scan_code, use_e0, use_e1 in reversed(key_strokes):
                    self._send_key_event(scan_code, False, use_e0=use_e0, use_e1=use_e1)
                    _precise_sleep(0.01)

                return True
    
    def _move_mouse_internal(self, x: int, y: int, absolute: bool = True) -> bool:
        if absolute:
            interception_x, interception_y = self._pixel_to_interception(x, y)
            flags = INTERCEPTION_MOUSE_MOVE_ABSOLUTE | INTERCEPTION_MOUSE_VIRTUAL_DESKTOP
            return self._send_mouse_event(interception_x, interception_y, flags, INTERCEPTION_MOUSE_MOVE, 0)

        flags = INTERCEPTION_MOUSE_MOVE_RELATIVE
        return self._send_mouse_event(int(x), int(y), flags, INTERCEPTION_MOUSE_MOVE, 0)

    def move_mouse(self, x: int, y: int, absolute: bool = True) -> bool:
        with self._mouse_lock:
            return self._move_mouse_internal(x, y, absolute)

    def click_mouse(self, x: Optional[int] = None, y: Optional[int] = None,
                   button: str = 'left', clicks: int = 1, interval: float = 0.0,
                   duration: float = 0.0) -> bool:
        with InterceptionDriver._global_atomic_sequence_lock:
            with self._mouse_lock:
                if x is None or y is None:
                    logger.error("invalid click coordinates: x and y are required")
                    return False

                target_x = int(x)
                target_y = int(y)

                if button.lower() == 'left':
                    down_state = INTERCEPTION_MOUSE_LEFT_BUTTON_DOWN
                    up_state = INTERCEPTION_MOUSE_LEFT_BUTTON_UP
                elif button.lower() == 'right':
                    down_state = INTERCEPTION_MOUSE_RIGHT_BUTTON_DOWN
                    up_state = INTERCEPTION_MOUSE_RIGHT_BUTTON_UP
                elif button.lower() == 'middle':
                    down_state = INTERCEPTION_MOUSE_MIDDLE_BUTTON_DOWN
                    up_state = INTERCEPTION_MOUSE_MIDDLE_BUTTON_UP
                else:
                    logger.warning(f"未知鼠标按键: {button}")
                    return False

                try:
                    safe_clicks = max(1, int(clicks))
                except Exception:
                    safe_clicks = 1
                try:
                    safe_interval = max(0.0, float(interval))
                except Exception:
                    safe_interval = 0.0
                try:
                    safe_duration = max(0.0, float(duration))
                except Exception:
                    safe_duration = 0.0

                for i in range(safe_clicks):
                    if i > 0 and safe_interval > 0:
                        _precise_sleep(safe_interval)
                    if not self._send_mouse_click_event_strict(
                        down_state,
                        up_state,
                        target_x,
                        target_y,
                        hold_duration=safe_duration if safe_duration > 0 else None,
                    ):
                        logger.error("鼠标完整点击事件发送失败")
                        return False

                return True

    def drag_mouse(self, start_x: int, start_y: int, end_x: int, end_y: int,
                  button: str = 'left', duration: float = 1.0) -> bool:
        """鼠标拖拽（输入像素坐标）"""
        # 移动到起始位置
        if not self.move_mouse(start_x, start_y):
            logger.error(f"移动到起始位置({start_x}, {start_y})失败")
            return False
        _precise_sleep(0.1)

        # 确定按键状态
        use_button = button.lower() != 'none'

        if use_button:
            if button.lower() == 'left':
                down_state = INTERCEPTION_MOUSE_LEFT_BUTTON_DOWN
                up_state = INTERCEPTION_MOUSE_LEFT_BUTTON_UP
            elif button.lower() == 'right':
                down_state = INTERCEPTION_MOUSE_RIGHT_BUTTON_DOWN
                up_state = INTERCEPTION_MOUSE_RIGHT_BUTTON_UP
            elif button.lower() == 'middle':
                down_state = INTERCEPTION_MOUSE_MIDDLE_BUTTON_DOWN
                up_state = INTERCEPTION_MOUSE_MIDDLE_BUTTON_UP
            else:
                logger.warning(f"未知鼠标按键: {button}")
                return False

        # 按下鼠标(如果使用按键)
        if use_button:
            if not self._send_mouse_event(0, 0, 0, down_state, 0):
                return False
            _precise_sleep(0.1)

        # 拖拽到目标位置
        if duration > 0:
            steps = max(10, int(duration * 100))
            for i in range(steps + 1):
                progress = i / steps
                current_pixel_x = int(start_x + (end_x - start_x) * progress)
                current_pixel_y = int(start_y + (end_y - start_y) * progress)
                self.move_mouse(current_pixel_x, current_pixel_y)
                _precise_sleep(duration / steps)
        else:
            self.move_mouse(end_x, end_y)

        # 释放鼠标(如果使用按键)
        if use_button:
            return self._send_mouse_event(0, 0, 0, up_state, 0)
        else:
            return True  # 不使用按键时直接返回成功

    def drag_path(self, path_points: list, duration: float = 1.0, button: str = 'left', timestamps: list = None) -> bool:
        """多点路径拖拽（输入像素坐标）

        Args:
            path_points: 路径点列表 [(x1, y1), (x2, y2), ...]
            duration: 总持续时间（秒）
            button: 鼠标按钮 ('left', 'right', 'middle')
            timestamps: 时间戳列表（秒），用于精确回放；如果为None则均匀分配时间

        Returns:
            bool: 是否执行成功
        """
        if not path_points or len(path_points) < 2:
            logger.error("路径点数量不足，至少需要2个点")
            return False

        try:
            start_x, start_y = path_points[0]
            end_x, end_y = path_points[-1]

            # 移动到起始位置
            if not self.move_mouse(start_x, start_y):
                logger.error(f"移动到起始位置({start_x}, {start_y})失败")
                return False
            _precise_sleep(0.05)

            # 确定按键状态
            button_lower = button.lower()
            if button_lower == 'left':
                down_state = INTERCEPTION_MOUSE_LEFT_BUTTON_DOWN
                up_state = INTERCEPTION_MOUSE_LEFT_BUTTON_UP
            elif button_lower == 'right':
                down_state = INTERCEPTION_MOUSE_RIGHT_BUTTON_DOWN
                up_state = INTERCEPTION_MOUSE_RIGHT_BUTTON_UP
            elif button_lower == 'middle':
                down_state = INTERCEPTION_MOUSE_MIDDLE_BUTTON_DOWN
                up_state = INTERCEPTION_MOUSE_MIDDLE_BUTTON_UP
            else:
                logger.warning(f"未知鼠标按键: {button}")
                return False

            # 按下鼠标
            if not self._send_mouse_event(0, 0, 0, down_state, 0):
                return False
            _precise_sleep(0.05)

            # 执行路径拖拽
            if timestamps and len(timestamps) == len(path_points):
                # 使用时间戳精确回放
                logger.debug(f"使用时间戳进行精确路径回放，{len(path_points)}个点")

                total_duration = duration
                # 总步数统一使用30fps
                total_steps = max(20, int(total_duration * 30))

                for step in range(1, total_steps + 1):
                    # 计算总进度
                    total_progress = step / total_steps
                    current_time = total_progress * total_duration

                    # 根据时间找到当前应该在哪两个点之间
                    segment_idx = 0
                    for j in range(len(timestamps) - 1):
                        if current_time >= timestamps[j]:
                            segment_idx = j
                        else:
                            break

                    if segment_idx >= len(path_points) - 1:
                        segment_idx = len(path_points) - 2

                    segment_start = path_points[segment_idx]
                    segment_end = path_points[segment_idx + 1]
                    segment_start_time = timestamps[segment_idx]
                    segment_end_time = timestamps[segment_idx + 1]
                    segment_progress = (current_time - segment_start_time) / (segment_end_time - segment_start_time)
                    segment_progress = max(0, min(1, segment_progress))

                    current_x = int(segment_start[0] + (segment_end[0] - segment_start[0]) * segment_progress)
                    current_y = int(segment_start[1] + (segment_end[1] - segment_start[1]) * segment_progress)
                    self.move_mouse(current_x, current_y)
                    _precise_sleep(total_duration / total_steps)
            else:
                # 均匀分配时间
                logger.debug(f"均匀分配时间进行路径拖拽，{len(path_points)}个点")

                # 统一使用30fps
                total_steps = max(20, int(duration * 30))

                for step in range(1, total_steps + 1):
                    # 计算总进度
                    total_progress = step / total_steps

                    # 找到当前进度对应的两个路径点
                    point_idx = int(total_progress * (len(path_points) - 1))
                    if point_idx >= len(path_points) - 1:
                        point_idx = len(path_points) - 2

                    # 段内进度
                    segment_progress = (total_progress * (len(path_points) - 1)) - point_idx

                    p1 = path_points[point_idx]
                    p2 = path_points[point_idx + 1]

                    current_x = int(p1[0] + (p2[0] - p1[0]) * segment_progress)
                    current_y = int(p1[1] + (p2[1] - p1[1]) * segment_progress)

                    self.move_mouse(current_x, current_y)
                    _precise_sleep(duration / total_steps)

            # 确保最后一次移动到终点
            self.move_mouse(end_x, end_y)
            _precise_sleep(0.02)

            # 释放鼠标
            return self._send_mouse_event(0, 0, 0, up_state, 0)

        except Exception as e:
            logger.error(f"多点路径拖拽失败: {e}", exc_info=True)
            # 紧急释放鼠标
            try:
                button_lower = button.lower()
                if button_lower == 'left':
                    up_state = INTERCEPTION_MOUSE_LEFT_BUTTON_UP
                elif button_lower == 'right':
                    up_state = INTERCEPTION_MOUSE_RIGHT_BUTTON_UP
                else:
                    up_state = INTERCEPTION_MOUSE_MIDDLE_BUTTON_UP
                self._send_mouse_event(0, 0, 0, up_state, 0)
            except:
                pass
            return False

    def mouse_down(self, x: Optional[int] = None, y: Optional[int] = None, button: str = 'left') -> bool:
        with InterceptionDriver._global_atomic_sequence_lock:
            with self._mouse_lock:
                if x is None or y is None:
                    logger.error("invalid mouse_down coordinates: x and y are required")
                    return False
                target_x = int(x)
                target_y = int(y)

                button_lower = button.lower()
                if button_lower == 'left':
                    down_state = INTERCEPTION_MOUSE_LEFT_BUTTON_DOWN
                elif button_lower == 'right':
                    down_state = INTERCEPTION_MOUSE_RIGHT_BUTTON_DOWN
                elif button_lower == 'middle':
                    down_state = INTERCEPTION_MOUSE_MIDDLE_BUTTON_DOWN
                else:
                    logger.warning(f"未知鼠标按键: {button}")
                    return False
                return self._send_mouse_button_event_strict(down_state, target_x, target_y)

    def mouse_up(self, x: Optional[int] = None, y: Optional[int] = None, button: str = 'left') -> bool:
        with InterceptionDriver._global_atomic_sequence_lock:
            with self._mouse_lock:
                if x is None or y is None:
                    logger.error("invalid mouse_up coordinates: x and y are required")
                    return False
                target_x = int(x)
                target_y = int(y)

                button_lower = button.lower()
                if button_lower == 'left':
                    up_state = INTERCEPTION_MOUSE_LEFT_BUTTON_UP
                elif button_lower == 'right':
                    up_state = INTERCEPTION_MOUSE_RIGHT_BUTTON_UP
                elif button_lower == 'middle':
                    up_state = INTERCEPTION_MOUSE_MIDDLE_BUTTON_UP
                else:
                    logger.warning(f"未知鼠标按键: {button}")
                    return False
                return self._send_mouse_button_event_strict(up_state, target_x, target_y)

    def scroll_mouse(self, direction: str, clicks: int = 1, x: Optional[int] = None, y: Optional[int] = None) -> bool:
        """鼠标滚轮（输入像素坐标）"""
        if x is not None and y is not None:
            if not self.move_mouse(x, y):
                logger.error(f"移动鼠标到({x}, {y})失败")
                return False

        if direction.lower() == 'up':
            rolling = 120 * clicks
        elif direction.lower() == 'down':
            rolling = -120 * clicks
        else:
            logger.warning(f"未知滚动方向: {direction}")
            return False

        return self._send_mouse_event(0, 0, 0, INTERCEPTION_MOUSE_WHEEL, rolling)
    
    def get_screen_size(self) -> Tuple[int, int]:
        """获取屏幕尺寸"""
        try:
            from utils.multi_monitor_manager import get_primary_screen_size
            return get_primary_screen_size()
        except Exception:
            return (0, 0)
    
    def get_mouse_position(self) -> Tuple[int, int]:
        """获取鼠标位置"""
        return self._get_current_mouse_pos()
    
    def close(self) -> None:
        """清理资源"""
        if self.context and self.dll:
            try:
                self.release_all_keys()
            except Exception:
                pass
            try:
                self._clear_event_filters()
            except Exception:
                pass
            try:
                self.dll.interception_destroy_context(self.context)
            except Exception:
                pass
        self.context = None
        self._keyboard_predicate = None
        self._mouse_predicate = None
        self._all_devices_predicate = None
        self.dll = None
        self.keyboard_device = INTERCEPTION_MIN_KEYBOARD
        self.mouse_device = INTERCEPTION_MIN_MOUSE
        self.initialized = False
        self.driver_just_installed = False
        self.driver_restart_required = False
        self._pressed_keys.clear()
        logger.info("驱动已关闭")

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


# 全局驱动实例
_driver_instance = None

def get_driver() -> InterceptionDriver:
    """获取全局驱动实例"""
    global _driver_instance
    if _driver_instance is None:
        _driver_instance = InterceptionDriver()
    return _driver_instance


def _close_global_driver_on_exit() -> None:
    global _driver_instance
    if _driver_instance is not None:
        try:
            _driver_instance.close()
        except Exception:
            pass


atexit.register(_close_global_driver_on_exit)




