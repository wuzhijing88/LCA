#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前台输入驱动管理器
"""

import logging
import os
import time
import ctypes
import atexit
from threading import RLock
from typing import Optional, Tuple
from utils.input_timing import DEFAULT_CLICK_HOLD_SECONDS, DEFAULT_KEY_HOLD_SECONDS
from utils.precise_sleep import precise_sleep as _shared_precise_sleep
from utils.input_simulation.mode_utils import (
    get_foreground_driver_backends,
    get_ibinputsimulator_config,
    is_foreground_mode,
    normalize_ib_driver_name,
)

logger = logging.getLogger(__name__)

def _precise_sleep(duration: float) -> None:
    _shared_precise_sleep(duration)


_DEFAULT_ATOMIC_CLICK_HOLD_SECONDS = DEFAULT_CLICK_HOLD_SECONDS


def _default_atomic_click_hold_seconds() -> float:
    return _DEFAULT_ATOMIC_CLICK_HOLD_SECONDS


def _get_default_screen_size() -> Tuple[int, int]:
    try:
        from utils.multi_monitor_manager import get_primary_screen_size
        return get_primary_screen_size()
    except Exception:
        return (0, 0)


class _SplitForegroundDriverProxy:
    """将鼠标和键盘操作分发到不同驱动。"""

    def __init__(self, mouse_driver, keyboard_driver):
        self._mouse_driver = mouse_driver
        self._keyboard_driver = keyboard_driver

    @staticmethod
    def _safe_call(driver, method_name: str, *args, **kwargs):
        if not driver:
            return False
        method = getattr(driver, method_name, None)
        if not callable(method):
            return False
        return method(*args, **kwargs)

    def move_mouse(self, x, y, absolute=True):
        return self._safe_call(self._mouse_driver, "move_mouse", x, y, absolute=absolute)

    def click_mouse(self, x=None, y=None, button='left', clicks=1, interval=0.0, duration=0.0, **kwargs):
        return self._safe_call(
            self._mouse_driver,
            "click_mouse",
            x,
            y,
            button=button,
            clicks=clicks,
            interval=interval,
            duration=duration,
            **kwargs,
        )

    def mouse_down(self, x, y, button='left'):
        return self._safe_call(self._mouse_driver, "mouse_down", x, y, button=button)

    def mouse_up(self, x, y, button='left'):
        return self._safe_call(self._mouse_driver, "mouse_up", x, y, button=button)

    def drag_mouse(self, start_x, start_y, end_x, end_y, button='left', duration=1.0):
        return self._safe_call(
            self._mouse_driver,
            "drag_mouse",
            start_x,
            start_y,
            end_x,
            end_y,
            button=button,
            duration=duration,
        )

    def drag_path(self, points, duration=1.0, button='left', timestamps=None):
        return self._safe_call(
            self._mouse_driver,
            "drag_path",
            points,
            duration=duration,
            button=button,
            timestamps=timestamps,
        )

    def scroll_mouse(self, direction, clicks=1, x=None, y=None):
        return self._safe_call(
            self._mouse_driver,
            "scroll_mouse",
            direction,
            clicks=clicks,
            x=x,
            y=y,
        )

    def hotkey(self, *keys):
        return self._safe_call(self._keyboard_driver, "hotkey", *keys)

    def press_key(self, key, duration=DEFAULT_KEY_HOLD_SECONDS):
        return self._safe_call(self._keyboard_driver, "press_key", key, duration)

    def key_down(self, key):
        return self._safe_call(self._keyboard_driver, "key_down", key)

    def key_up(self, key):
        return self._safe_call(self._keyboard_driver, "key_up", key)

    def release_all_keys(self) -> bool:
        release_method = getattr(self._keyboard_driver, "release_all_keys", None)
        if callable(release_method):
            try:
                return bool(release_method())
            except Exception:
                return False
        release_method = getattr(self._keyboard_driver, "release_all_inputs", None)
        if callable(release_method):
            try:
                return bool(release_method())
            except Exception:
                return False
        return True

    def release_all_inputs(self) -> bool:
        release_ok = True
        mouse_release = getattr(self._mouse_driver, "release_all_inputs", None)
        if callable(mouse_release):
            try:
                release_ok = bool(mouse_release()) and release_ok
            except Exception:
                release_ok = False

        keyboard_release = self.release_all_keys()
        return release_ok and keyboard_release

    def type_text(self, text, **kwargs):
        return self._safe_call(self._keyboard_driver, "type_text", text, **kwargs)

    def get_screen_size(self):
        if self._mouse_driver and hasattr(self._mouse_driver, "get_screen_size"):
            return self._mouse_driver.get_screen_size()
        return _get_default_screen_size()

    def get_mouse_position(self):
        if self._mouse_driver and hasattr(self._mouse_driver, "get_mouse_position"):
            return self._mouse_driver.get_mouse_position()
        return (0, 0)

    def close(self):
        try:
            self.release_all_inputs()
        except Exception:
            pass
        closed = set()
        for driver in (self._mouse_driver, self._keyboard_driver):
            if not driver:
                continue
            driver_id = id(driver)
            if driver_id in closed:
                continue
            closed.add(driver_id)
            close_fn = getattr(driver, "close", None)
            if callable(close_fn):
                try:
                    close_fn()
                except Exception:
                    pass

    def __getattr__(self, name: str):
        if self._mouse_driver and hasattr(self._mouse_driver, name):
            return getattr(self._mouse_driver, name)
        if self._keyboard_driver and hasattr(self._keyboard_driver, name):
            return getattr(self._keyboard_driver, name)
        raise AttributeError(name)


class ForegroundInputManager:
    """前台输入驱动管理器"""

    def __init__(self):
        """初始化"""
        self._state_lock = RLock()
        self._interception_driver = None
        self._pyautogui_driver = None
        self._ibinputsimulator_driver = None
        self._active_driver = None
        self._driver_type = None
        self._initialization_attempted = False
        self._forced_mode = None
        self._mouse_forced_mode = None
        self._keyboard_forced_mode = None
        self._ib_driver = "Logitech"
        self._ib_driver_arg = ""
        self._ib_ahk_path = ""
        self._ib_ahk_dir = ""
        self._allow_fallback = False  # 严格隔离，不自动降级
        self._last_failure_time = 0.0
        self._retry_cooldown_seconds = 0.0
        self._ib_missing_prompt_signatures = set()

    def set_execution_mode(self, execution_mode: str) -> None:
        """根据执行模式选择驱动类型（严格隔离，不降级）"""
        if not (execution_mode and is_foreground_mode(execution_mode)):
            return

        normalized_mode = str(execution_mode or "").strip().lower()
        native_modes = {"interception", "ibinputsimulator"}
        current_mouse_mode = str(self._mouse_forced_mode or "").strip().lower()
        current_keyboard_mode = str(self._keyboard_forced_mode or "").strip().lower()

        # 前台一模式下，若运行时已存在分离后的鼠标/键盘驱动设置，则沿用当前设置。
        # 这样可避免被旧配置文件回写覆盖导致“键盘驱动回退到鼠标驱动”。
        if normalized_mode in ("foreground_driver", "foreground"):
            if current_mouse_mode in native_modes and current_keyboard_mode in native_modes:
                logger.debug(
                    f"前台驱动模式沿用当前运行时设置: mouse={current_mouse_mode}, keyboard={current_keyboard_mode}"
                )
                return

        mouse_mode, keyboard_mode = get_foreground_driver_backends(execution_mode)
        self.set_forced_modes(mouse_mode, keyboard_mode)
        if 'ibinputsimulator' in (mouse_mode, keyboard_mode):
            ib_driver, ib_driver_arg, ib_ahk_path, ib_ahk_dir = get_ibinputsimulator_config()
            self.set_ibinputsimulator_driver(ib_driver, ib_driver_arg, ib_ahk_path, ib_ahk_dir)

    def set_ibinputsimulator_driver(
        self,
        driver: str,
        driver_arg: str = "",
        ahk_path: str = "",
        ahk_dir: str = "",
    ) -> None:
        """设置 IbInputSimulator 驱动类型。"""
        normalized_driver = normalize_ib_driver_name(driver)
        normalized_arg = str(driver_arg or "").strip()
        normalized_ahk_path = str(ahk_path or "").strip()
        normalized_ahk_dir = str(ahk_dir or "").strip()

        if (
            self._ib_driver == normalized_driver
            and self._ib_driver_arg == normalized_arg
            and self._ib_ahk_path == normalized_ahk_path
            and self._ib_ahk_dir == normalized_ahk_dir
        ):
            return

        self._ib_driver = normalized_driver
        self._ib_driver_arg = normalized_arg
        self._ib_ahk_path = normalized_ahk_path
        self._ib_ahk_dir = normalized_ahk_dir
        if self._driver_type and 'ibinputsimulator' in str(self._driver_type):
            self._release_runtime_drivers()

    @staticmethod
    def _normalize_forced_mode(mode: str) -> str:
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode not in ('interception', 'pyautogui', 'ibinputsimulator'):
            logger.warning(f"不支持的驱动模式: {mode}，将使用 interception")
            return 'interception'
        return normalized_mode

    @staticmethod
    def _release_stuck_inputs_for_driver(driver) -> bool:
        if not driver:
            return True
        release_fn = getattr(driver, "release_all_inputs", None)
        if callable(release_fn):
            try:
                return bool(release_fn())
            except Exception:
                return False
        release_keys_fn = getattr(driver, "release_all_keys", None)
        if callable(release_keys_fn):
            try:
                return bool(release_keys_fn())
            except Exception:
                return False
        return True

    def release_all_inputs(self, include_cached_drivers: bool = False) -> bool:
        release_ok = True
        released = set()
        drivers_to_release = [self._active_driver]
        if include_cached_drivers:
            drivers_to_release.extend(
                [
                    self._interception_driver,
                    self._pyautogui_driver,
                    self._ibinputsimulator_driver,
                ]
            )
        for driver in drivers_to_release:
            if not driver:
                continue
            driver_id = id(driver)
            if driver_id in released:
                continue
            released.add(driver_id)
            if not self._release_stuck_inputs_for_driver(driver):
                release_ok = False
        return release_ok

    def _release_runtime_drivers(self) -> None:
        if isinstance(self._active_driver, _SplitForegroundDriverProxy):
            try:
                self._release_stuck_inputs_for_driver(self._active_driver)
            except Exception:
                pass
            try:
                self._active_driver.close()
            except Exception:
                pass
        else:
            closed = set()
            for driver in (
                self._active_driver,
                self._interception_driver,
                self._pyautogui_driver,
                self._ibinputsimulator_driver,
            ):
                if not driver:
                    continue
                driver_id = id(driver)
                if driver_id in closed:
                    continue
                closed.add(driver_id)
                try:
                    self._release_stuck_inputs_for_driver(driver)
                except Exception:
                    pass
                close_fn = getattr(driver, 'close', None)
                if callable(close_fn):
                    try:
                        close_fn()
                    except Exception:
                        pass

        self._active_driver = None
        self._driver_type = None
        self._interception_driver = None
        self._pyautogui_driver = None
        self._ibinputsimulator_driver = None
        self._initialization_attempted = False
        self._last_failure_time = 0.0

    def set_forced_modes(self, mouse_mode: str, keyboard_mode: str) -> None:
        normalized_mouse_mode = self._normalize_forced_mode(mouse_mode)
        normalized_keyboard_mode = self._normalize_forced_mode(keyboard_mode)
        unified_mode = (
            normalized_mouse_mode
            if normalized_mouse_mode == normalized_keyboard_mode
            else 'mixed'
        )

        if (
            self._mouse_forced_mode == normalized_mouse_mode
            and self._keyboard_forced_mode == normalized_keyboard_mode
            and self._forced_mode == unified_mode
            and self._initialization_attempted
        ):
            return

        self._mouse_forced_mode = normalized_mouse_mode
        self._keyboard_forced_mode = normalized_keyboard_mode
        self._forced_mode = unified_mode
        self._allow_fallback = False
        self._release_runtime_drivers()

    def set_forced_mode(self, mode: str) -> None:
        """
        设置强制使用的驱动模式
        Args:
            mode: 'interception' 或 'pyautogui'
        """
        normalized_mode = self._normalize_forced_mode(mode)
        self.set_forced_modes(normalized_mode, normalized_mode)

    def initialize(self) -> bool:
        """
        初始化驱动

        Returns:
            是否成功初始化驱动
        """
        if self._initialization_attempted and self._active_driver is not None:
            logger.debug(f"驱动已初始化（类型: {self._driver_type}），跳过重复初始化")
            return True

        if self._initialization_attempted and self._active_driver is None:
            now = time.monotonic()
            if self._retry_cooldown_seconds > 0 and now - self._last_failure_time < self._retry_cooldown_seconds:
                logger.debug("前台驱动初始化未到重试间隔，稍后再试")
                return False
            self._initialization_attempted = False

        self._initialization_attempted = True
        success = False

        mouse_mode = self._mouse_forced_mode
        keyboard_mode = self._keyboard_forced_mode

        if not mouse_mode and not keyboard_mode:
            base_mode = self._normalize_forced_mode(self._forced_mode or 'interception')
            mouse_mode = base_mode
            keyboard_mode = base_mode

        if not mouse_mode:
            mouse_mode = self._normalize_forced_mode(self._forced_mode or keyboard_mode or 'interception')
        if not keyboard_mode:
            keyboard_mode = self._normalize_forced_mode(self._forced_mode or mouse_mode or 'interception')

        mouse_mode = self._normalize_forced_mode(mouse_mode)
        keyboard_mode = self._normalize_forced_mode(keyboard_mode)

        if mouse_mode == keyboard_mode:
            success = self._initialize_driver_for_mode(mouse_mode, set_active=True) is not None
        else:
            mouse_driver = self._initialize_driver_for_mode(mouse_mode, set_active=False)
            keyboard_driver = self._initialize_driver_for_mode(keyboard_mode, set_active=False)
            if mouse_driver is not None and keyboard_driver is not None:
                self._active_driver = _SplitForegroundDriverProxy(mouse_driver, keyboard_driver)
                self._driver_type = f"{mouse_mode}+{keyboard_mode}"
                success = True

        if success:
            self._last_failure_time = 0.0
            return True

        self._active_driver = None
        self._driver_type = None
        self._last_failure_time = time.monotonic()
        return False

    def _initialize_driver_for_mode(self, mode: str, set_active: bool = False):
        normalized_mode = self._normalize_forced_mode(mode)
        if normalized_mode == 'pyautogui':
            if self._initialize_pyautogui(set_active=set_active):
                return self._pyautogui_driver
            return None
        if normalized_mode == 'ibinputsimulator':
            if self._initialize_ibinputsimulator(set_active=set_active):
                return self._ibinputsimulator_driver
            return None

        if self._initialize_interception(set_active=set_active):
            return self._interception_driver
        if self._allow_fallback and normalized_mode == 'interception':
            logger.info("Interception驱动初始化失败，自动降级到PyAutoGUI")
            if self._initialize_pyautogui(set_active=set_active):
                return self._pyautogui_driver
        return None
    def _initialize_interception(self, set_active: bool = True) -> bool:
        """尝试初始化Interception驱动"""
        logger.info("正在初始化Interception驱动...")

        try:
            from utils.interception_driver import get_driver
            if self._interception_driver is None:
                self._interception_driver = get_driver()

            if self._interception_driver.initialize():
                if set_active:
                    self._active_driver = self._interception_driver
                    self._driver_type = 'interception'
                logger.info("Interception驱动初始化成功")
                return True
            else:
                prompt_config = self._interception_driver.get_restart_prompt_config()
                if prompt_config:
                    logger.info("检测到驱动需要提示用户处理")
                    self._show_restart_prompt(prompt_config)

                logger.warning("Interception驱动初始化失败")
                return False

        except Exception as e:
            logger.warning(f"Interception驱动初始化失败: {e}")
            return False

    def _initialize_ibinputsimulator(self, set_active: bool = True) -> bool:
        """初始化 IbInputSimulator 驱动。"""
        logger.info("正在初始化 IbInputSimulator 驱动...")

        try:
            from utils.ibinputsimulator_driver import IbInputSimulatorDriver

            if self._ib_ahk_path:
                os.environ['IBINPUTSIMULATOR_AHK'] = self._ib_ahk_path
            else:
                os.environ.pop('IBINPUTSIMULATOR_AHK', None)

            if self._ib_ahk_dir:
                os.environ['IBINPUTSIMULATOR_DIR'] = self._ib_ahk_dir
            else:
                os.environ.pop('IBINPUTSIMULATOR_DIR', None)

            if self._ibinputsimulator_driver is None:
                self._ibinputsimulator_driver = IbInputSimulatorDriver(
                    driver=self._ib_driver,
                    driver_arg=self._ib_driver_arg,
                )
            if self._ibinputsimulator_driver.initialize():
                if set_active:
                    self._active_driver = self._ibinputsimulator_driver
                    self._driver_type = 'ibinputsimulator'
                logger.info("IbInputSimulator 驱动初始化成功")
                return True

            error_detail = ""
            try:
                error_detail = self._ibinputsimulator_driver.get_last_error()
            except Exception:
                error_detail = ""

            if error_detail:
                logger.warning(f"IbInputSimulator 驱动初始化失败: {error_detail}")
            else:
                logger.warning("IbInputSimulator 驱动初始化失败")
            self._show_ib_driver_missing_prompt(error_detail)
            self._ibinputsimulator_driver = None
            return False
        except Exception as e:
            logger.warning(f"IbInputSimulator 驱动初始化失败: {e}")
            self._show_ib_driver_missing_prompt(str(e))
            self._ibinputsimulator_driver = None
            return False

    def _is_ib_driver_missing_error(self, error_detail: str) -> bool:
        text = str(error_detail or "").strip().lower().replace(" ", "")
        if not text:
            return False
        keywords = (
            "devicenotfound",
            "deviceopenfailed",
            "devicecreatefailed",
            "ibsendinitfailedcode:4",
            "ibsendinitfailedcode:5",
            "ibsendinitfailedcode:6",
        )
        return any(key in text for key in keywords)

    def _show_ib_driver_missing_prompt(self, error_detail: str) -> None:
        if not self._is_ib_driver_missing_error(error_detail):
            return

        driver_key = str(self._ib_driver or "").strip().lower() or "logitech"
        signature = f"{driver_key}:driver_missing"
        if signature in self._ib_missing_prompt_signatures:
            return
        self._ib_missing_prompt_signatures.add(signature)

        if driver_key == "logitech":
            display_name = "罗技"
        elif driver_key == "razer":
            display_name = "雷蛇"
        else:
            display_name = self._ib_driver

        try:
            from PySide6.QtWidgets import QMessageBox, QApplication
            from PySide6.QtCore import QTimer

            app = QApplication.instance()
            if app is None:
                logger.warning(f"{display_name}驱动未就绪，前台输入不可用")
                return

            def show_message():
                try:
                    msg_box = QMessageBox()
                    msg_box.setIcon(QMessageBox.Icon.Warning)
                    msg_box.setWindowTitle("前台驱动不可用")
                    msg_box.setText(f"{display_name}驱动未就绪，前台输入无法执行。")
                    msg_box.setInformativeText(
                        "请先安装并启用对应驱动后重试。\n"
                        "安装完成后请重启软件。\n"
                        "必要时请以管理员身份运行软件。"
                    )
                    msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
                    msg_box.exec()
                except Exception as e:
                    logger.error(f"显示前台驱动提示失败: {e}")

            QTimer.singleShot(200, show_message)
        except Exception as e:
            logger.error(f"准备前台驱动提示失败: {e}")

    def _initialize_pyautogui(self, set_active: bool = True) -> bool:
        """降级到PyAutoGUI"""
        logger.info("正在初始化PyAutoGUI...")

        try:
            import pyautogui
            # PyAutoGUI不需要特殊初始化，直接标记为可用
            class PyAutoGUIDriver:
                MOUSEEVENTF_MOVE = 0x0001
                MOUSEEVENTF_LEFTDOWN = 0x0002
                MOUSEEVENTF_LEFTUP = 0x0004
                MOUSEEVENTF_RIGHTDOWN = 0x0008
                MOUSEEVENTF_RIGHTUP = 0x0010
                MOUSEEVENTF_MIDDLEDOWN = 0x0020
                MOUSEEVENTF_MIDDLEUP = 0x0040
                MOUSEEVENTF_VIRTUALDESK = 0x4000
                MOUSEEVENTF_ABSOLUTE = 0x8000

                def __init__(self):
                    pyautogui.FAILSAFE = False
                    pyautogui.PAUSE = 0
                    self._user32 = ctypes.windll.user32
                    self._send_lock = RLock()
                    self._key_release_reserve_window = 0.003
                    self._pressed_keys = set()
                    self._pressed_buttons = set()
                    self._cursor_align_tolerance = 1
                    self._cursor_align_timeout = 0.26
                    self._cursor_align_precheck_timeout = 0.05
                    self._cursor_align_attempts = 2
                    self._cursor_align_poll_interval = 0.002

                def _normalize_button(self, button: str) -> str:
                    key = str(button or "left").strip().lower()
                    if key == "right":
                        return "right"
                    if key == "middle":
                        return "middle"
                    return "left"

                def _button_flags(self, button: str):
                    key = self._normalize_button(button)
                    if key == "right":
                        return self.MOUSEEVENTF_RIGHTDOWN, self.MOUSEEVENTF_RIGHTUP
                    if key == "middle":
                        return self.MOUSEEVENTF_MIDDLEDOWN, self.MOUSEEVENTF_MIDDLEUP
                    return self.MOUSEEVENTF_LEFTDOWN, self.MOUSEEVENTF_LEFTUP

                @staticmethod
                def _normalize_key_name(key) -> str:
                    return str(key or "").strip().lower()

                def _mouse_event_at(self, x: int, y: int, event_flag: int) -> None:
                    if not self._ensure_cursor_pos(int(x), int(y)):
                        raise RuntimeError("cursor not at target")
                    self._user32.mouse_event(int(event_flag), 0, 0, 0, 0)

                def _wait_cursor_pos(self, x: int, y: int, timeout: float = 0.08, tolerance: Optional[int] = None) -> bool:
                    tx = int(x)
                    ty = int(y)
                    tol = self._cursor_align_tolerance if tolerance is None else max(0, int(tolerance))
                    deadline = time.perf_counter() + max(0.0, float(timeout))
                    point = ctypes.wintypes.POINT()
                    while time.perf_counter() <= deadline:
                        try:
                            if self._user32.GetCursorPos(ctypes.byref(point)):
                                if abs(int(point.x) - tx) <= tol and abs(int(point.y) - ty) <= tol:
                                    return True
                        except Exception:
                            return False
                        _precise_sleep(self._cursor_align_poll_interval)
                    return False

                def _ensure_cursor_pos(self, x: int, y: int, timeout: Optional[float] = None, tolerance: Optional[int] = None) -> bool:
                    tx = int(x)
                    ty = int(y)
                    total_timeout = self._cursor_align_timeout if timeout is None else max(0.05, float(timeout))
                    tol = self._cursor_align_tolerance if tolerance is None else max(0, int(tolerance))
                    precheck_timeout = min(self._cursor_align_precheck_timeout, total_timeout)

                    if self._wait_cursor_pos(tx, ty, timeout=precheck_timeout, tolerance=tol):
                        return True

                    remain_timeout = max(0.01, total_timeout - precheck_timeout)
                    attempt_count = max(1, int(self._cursor_align_attempts))
                    per_attempt_timeout = max(0.01, remain_timeout / attempt_count)

                    for _ in range(attempt_count):
                        try:
                            self._user32.SetCursorPos(tx, ty)
                        except Exception:
                            return False
                        if self._wait_cursor_pos(tx, ty, timeout=per_attempt_timeout, tolerance=tol):
                            return True

                    return self._wait_cursor_pos(tx, ty, timeout=0.01, tolerance=tol)

                def _clip_cursor_to_point(self, x: int, y: int) -> bool:
                    try:
                        tx = int(x)
                        ty = int(y)
                        rect = ctypes.wintypes.RECT(tx, ty, tx + 1, ty + 1)
                        return bool(self._user32.ClipCursor(ctypes.byref(rect)))
                    except Exception:
                        return False

                def _release_cursor_clip(self) -> None:
                    try:
                        self._user32.ClipCursor(None)
                    except Exception:
                        pass

                def get_screen_size(self):
                    size = pyautogui.size()
                    return (size.width, size.height)

                def get_mouse_position(self):
                    pos = pyautogui.position()
                    return (pos.x, pos.y)

                def move_mouse(self, x, y, absolute=True):
                    try:
                        if absolute:
                            return bool(self._user32.SetCursorPos(int(x), int(y)))
                        dx = int(x)
                        dy = int(y)
                        if dx == 0 and dy == 0:
                            return True
                        # 前台二相对移动走系统相对注入，避免 pyautogui 在锁鼠场景下失效。
                        self._user32.mouse_event(int(self.MOUSEEVENTF_MOVE), dx, dy, 0, 0)
                        return True
                    except Exception:
                        return False

                def click_mouse(self, x=None, y=None, button='left', clicks=1, interval=0.0, duration=0.0, **kwargs):
                    if x is None or y is None:
                        return False
                    tx = int(x)
                    ty = int(y)
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

                    down_flag, up_flag = self._button_flags(button)
                    for i in range(safe_clicks):
                        if i > 0 and safe_interval > 0:
                            _precise_sleep(safe_interval)
                        with self._send_lock:
                            if not self._ensure_cursor_pos(tx, ty):
                                return False
                            hold_seconds = safe_duration if safe_duration > 0 else _default_atomic_click_hold_seconds()
                            cursor_clipped = False
                            button_down = False
                            try:
                                cursor_clipped = self._clip_cursor_to_point(tx, ty)
                                _precise_sleep(0.006)
                                self._mouse_event_at(tx, ty, down_flag)
                                button_down = True
                                if hold_seconds > 0:
                                    _precise_sleep(hold_seconds)
                                self._mouse_event_at(tx, ty, up_flag)
                                button_down = False
                            finally:
                                if button_down:
                                    try:
                                        self._mouse_event_at(tx, ty, up_flag)
                                    except Exception:
                                        pass
                                if cursor_clipped:
                                    self._release_cursor_clip()

                    return True

                def mouse_down(self, x, y, button='left'):
                    if x is None or y is None:
                        return False
                    tx = int(x)
                    ty = int(y)
                    down_flag, _ = self._button_flags(button)
                    normalized_button = self._normalize_button(button)
                    try:
                        with self._send_lock:
                            if not self._ensure_cursor_pos(tx, ty):
                                return False
                            cursor_clipped = False
                            try:
                                cursor_clipped = self._clip_cursor_to_point(tx, ty)
                                _precise_sleep(0.012)
                                self._mouse_event_at(tx, ty, down_flag)
                            finally:
                                if cursor_clipped:
                                    self._release_cursor_clip()
                            self._pressed_buttons.add(normalized_button)
                            return True
                    except Exception:
                        return False

                def mouse_up(self, x, y, button='left'):
                    if x is None or y is None:
                        return False
                    tx = int(x)
                    ty = int(y)
                    _, up_flag = self._button_flags(button)
                    normalized_button = self._normalize_button(button)
                    try:
                        with self._send_lock:
                            if not self._ensure_cursor_pos(tx, ty):
                                return False
                            cursor_clipped = False
                            try:
                                cursor_clipped = self._clip_cursor_to_point(tx, ty)
                                _precise_sleep(0.012)
                                self._mouse_event_at(tx, ty, up_flag)
                            finally:
                                if cursor_clipped:
                                    self._release_cursor_clip()
                            self._pressed_buttons.discard(normalized_button)
                            return True
                    except Exception:
                        return False

                def drag_mouse(self, start_x, start_y, end_x, end_y, button='left', duration=1.0):
                    pyautogui.moveTo(start_x, start_y)
                    pyautogui.dragTo(end_x, end_y, duration=duration, button=button)
                    return True

                def drag_path(self, points, duration=1.0, button='left', timestamps=None):
                    if not points or len(points) < 2:
                        return False
                    pyautogui.moveTo(points[0][0], points[0][1])
                    pyautogui.mouseDown(button=button)
                    try:
                        if timestamps and len(timestamps) == len(points):
                            prev_time = timestamps[0]
                            for (x, y), ts in zip(points[1:], timestamps[1:]):
                                step = max(0.0, ts - prev_time)
                                pyautogui.moveTo(x, y, duration=step)
                                prev_time = ts
                        else:
                            step_duration = duration / max(1, len(points) - 1)
                            for x, y in points[1:]:
                                pyautogui.moveTo(x, y, duration=step_duration)
                    finally:
                        pyautogui.mouseUp(button=button)
                    return True

                def scroll_mouse(self, direction, clicks, x=None, y=None):
                    if x is not None and y is not None:
                        pyautogui.moveTo(x, y)
                    amount = clicks if direction == 'up' else -clicks
                    pyautogui.scroll(amount)
                    return True

                def hotkey(self, *keys):
                    with self._send_lock:
                        pyautogui.hotkey(*keys)
                        return True

                def press_key(self, key, duration=DEFAULT_KEY_HOLD_SECONDS):
                    hold = max(0.0, float(duration or 0.0))
                    normalized_key = self._normalize_key_name(key)
                    if not normalized_key:
                        return False
                    with self._send_lock:
                        pyautogui.keyDown(normalized_key)
                        key_is_down = True
                        self._pressed_keys.add(normalized_key)
                        try:
                            release_deadline = time.perf_counter() + hold
                            reserve_window = min(
                                max(0.0, float(self._key_release_reserve_window)),
                                hold,
                            )
                            pre_hold = hold - reserve_window
                            if pre_hold > 0:
                                _precise_sleep(pre_hold)
                            remaining = release_deadline - time.perf_counter()
                            if remaining > 0:
                                _precise_sleep(remaining)
                            pyautogui.keyUp(normalized_key)
                            key_is_down = False
                            self._pressed_keys.discard(normalized_key)
                            return True
                        finally:
                            if key_is_down:
                                try:
                                    pyautogui.keyUp(normalized_key)
                                except Exception:
                                    pass
                                finally:
                                    self._pressed_keys.discard(normalized_key)

                def key_down(self, key):
                    normalized_key = self._normalize_key_name(key)
                    if not normalized_key:
                        return False
                    with self._send_lock:
                        pyautogui.keyDown(normalized_key)
                        self._pressed_keys.add(normalized_key)
                        return True

                def key_up(self, key):
                    normalized_key = self._normalize_key_name(key)
                    if not normalized_key:
                        return False
                    with self._send_lock:
                        pyautogui.keyUp(normalized_key)
                        self._pressed_keys.discard(normalized_key)
                        return True

                def type_text(self, text, **_kwargs):
                    pyautogui.typewrite(text)
                    return True

                def release_all_keys(self):
                    with self._send_lock:
                        pending_keys = list(self._pressed_keys)
                        self._pressed_keys.clear()
                        for key_name in reversed(pending_keys):
                            try:
                                pyautogui.keyUp(key_name)
                            except Exception:
                                pass
                    return True

                def release_all_inputs(self):
                    with self._send_lock:
                        pending_buttons = list(self._pressed_buttons)
                        self._pressed_buttons.clear()
                        for button_name in pending_buttons:
                            try:
                                _, up_flag = self._button_flags(button_name)
                                self._user32.mouse_event(int(up_flag), 0, 0, 0, 0)
                            except Exception:
                                pass
                    return self.release_all_keys()

                def close(self):
                    try:
                        self.release_all_inputs()
                    except Exception:
                        pass
                    return True

            if self._pyautogui_driver is None:
                self._pyautogui_driver = PyAutoGUIDriver()
            if set_active:
                self._active_driver = self._pyautogui_driver
                self._driver_type = 'pyautogui'
            logger.info("PyAutoGUI初始化成功")
            return True
        except ImportError:
            logger.error("PyAutoGUI不可用，无法初始化")
            return False
        except Exception as e:
            logger.error(f"PyAutoGUI初始化失败: {e}")
            return False

    def _show_restart_prompt(self, prompt_config: Optional[Tuple[str, str, str]] = None):
        """显示重启提示弹窗（延迟非阻塞方式）"""
        try:
            from PySide6.QtWidgets import QMessageBox, QApplication
            from PySide6.QtCore import QTimer
            import sys

            # 确保有QApplication实例
            app = QApplication.instance()
            if app is None:
                logger.warning("无法显示重启提示：QApplication未初始化")
                return

            if prompt_config is None:
                prompt_config = (
                    "需要重启计算机",
                    "Interception驱动已成功安装！",
                    "驱动需要重启计算机后才能生效。\n\n"
                    "请保存您的工作，然后重启计算机。\n"
                    "重启后，前台模式功能将可以正常使用。"
                )

            def show_message():
                """延迟显示消息框,在主线程事件循环中执行exec()"""
                try:
                    msg_box = QMessageBox()
                    msg_box.setIcon(QMessageBox.Icon.Information)
                    title, message, informative_text = prompt_config
                    msg_box.setWindowTitle(title)
                    msg_box.setText(message)
                    msg_box.setInformativeText(informative_text)
                    msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
                    # 在主线程中使用exec()是安全的，因为此时主窗口已经初始化完成
                    logger.info("显示重启提示弹窗（延迟后在主线程中执行）")
                    msg_box.exec()
                    logger.info("用户已确认重启提示")
                except Exception as e:
                    logger.error(f"显示重启提示时出错: {e}")

            # 使用QTimer延迟显示,确保在主窗口完全初始化后才显示
            # 这样既避免了初始化阶段阻塞,又能正常显示模态对话框
            QTimer.singleShot(2000, show_message)  # 延迟2秒后显示,确保主窗口已完成初始化
            logger.info("已安排显示重启提示（延迟2秒,等待主窗口初始化完成）")
        except Exception as e:
            logger.error(f"显示重启提示失败: {e}")

    def move_mouse(self, x: int, y: int, absolute: bool = True) -> bool:
        """移动鼠标"""
        if not self._active_driver:
            if not self.initialize():
                return False

        try:
            return self._active_driver.move_mouse(x, y, absolute)
        except Exception as e:
            logger.error(f"鼠标移动失败: {e}")
            return False

    def click_mouse(self, x: Optional[int] = None, y: Optional[int] = None,
                   button: str = 'left', clicks: int = 1, interval: float = 0.0,
                   duration: float = 0.0) -> bool:
        """鼠标点击"""
        if not self._active_driver:
            if not self.initialize():
                return False

        if x is None or y is None:
            logger.error("鼠标点击失败: 缺少坐标")
            return False

        try:
            safe_x = int(x)
            safe_y = int(y)
        except Exception:
            logger.error(f"鼠标点击失败: 坐标无效 ({x}, {y})")
            return False

        try:
            logger.info(f"执行点击: ({safe_x}, {safe_y}), 按钮={button}, 次数={clicks}")
            return self._active_driver.click_mouse(safe_x, safe_y, button, clicks, interval, duration)
        except Exception as e:
            logger.error(f"鼠标点击失败: {e}")
            return False

    def drag_mouse(self, start_x: int, start_y: int, end_x: int, end_y: int,
                  button: str = 'left', duration: float = 1.0) -> bool:
        """鼠标拖拽"""
        if not self._active_driver:
            if not self.initialize():
                return False

        try:
            return self._active_driver.drag_mouse(start_x, start_y, end_x, end_y, button, duration)
        except Exception as e:
            logger.error(f"鼠标拖拽失败: {e}")
            return False

    def scroll_mouse(self, direction: str, clicks: int = 1, x: Optional[int] = None, y: Optional[int] = None) -> bool:
        """鼠标滚轮"""
        if not self._active_driver:
            if not self.initialize():
                return False

        try:
            return self._active_driver.scroll_mouse(direction, clicks, x, y)
        except Exception as e:
            logger.error(f"鼠标滚轮失败: {e}")
            return False

    def mouse_down(self, x: int, y: int, button: str = 'left') -> bool:
        """仅按下鼠标按钮"""
        if not self._active_driver:
            if not self.initialize():
                return False

        if x is None or y is None:
            logger.error("鼠标按下失败: 缺少坐标")
            return False

        try:
            safe_x = int(x)
            safe_y = int(y)
        except Exception:
            logger.error(f"鼠标按下失败: 坐标无效 ({x}, {y})")
            return False

        try:
            return self._active_driver.mouse_down(safe_x, safe_y, button)
        except Exception as e:
            logger.error(f"鼠标按下失败: {e}")
            return False

    def mouse_up(self, x: int, y: int, button: str = 'left') -> bool:
        """仅松开鼠标按钮"""
        if not self._active_driver:
            if not self.initialize():
                return False

        if x is None or y is None:
            logger.error("鼠标松开失败: 缺少坐标")
            return False

        try:
            safe_x = int(x)
            safe_y = int(y)
        except Exception:
            logger.error(f"鼠标松开失败: 坐标无效 ({x}, {y})")
            return False

        try:
            return self._active_driver.mouse_up(safe_x, safe_y, button)
        except Exception as e:
            logger.error(f"鼠标松开失败: {e}")
            return False

    def get_screen_size(self) -> Tuple[int, int]:
        """获取屏幕尺寸"""
        if not self._active_driver:
            if not self.initialize():
                return _get_default_screen_size()

        try:
            return self._active_driver.get_screen_size()
        except Exception:
            return _get_default_screen_size()

    def get_mouse_position(self) -> Tuple[int, int]:
        """获取鼠标位置"""
        if not self._active_driver:
            if not self.initialize():
                return (0, 0)

        try:
            return self._active_driver.get_mouse_position()
        except:
            return (0, 0)

    def get_driver_type(self) -> Optional[str]:
        """
        获取当前使用的驱动类型

        Returns:
            'interception', 'pyautogui' 或 None（未初始化）
        """
        return self._driver_type

    def get_active_driver(self):
        """获取当前活动驱动实例"""
        return self._active_driver

    def is_interception_available(self) -> bool:
        """检查 Interception 驱动是否可用"""
        return bool(self._driver_type and 'interception' in str(self._driver_type))

    def set_target_window(self, hwnd: int) -> None:
        """
        设置目标窗口（用于PyAutoGUI激活窗口）

        Args:
            hwnd: 窗口句柄
        """
        if self._driver_type == 'pyautogui' and hasattr(self, '_pyautogui_fallback') and self._pyautogui_fallback:
            self._pyautogui_fallback.set_target_window(hwnd)

    def close(self) -> None:
        """清理资源"""
        try:
            self.release_all_inputs(include_cached_drivers=True)
        except Exception:
            pass
        self._release_runtime_drivers()
        logger.info("前台输入驱动管理器已关闭")


def _guard_manager_state(method):
    def wrapper(self, *args, **kwargs):
        with self._state_lock:
            return method(self, *args, **kwargs)
    return wrapper


for _method_name in (
    "set_execution_mode",
    "set_ibinputsimulator_driver",
    "release_all_inputs",
    "_release_runtime_drivers",
    "set_forced_modes",
    "set_forced_mode",
    "initialize",
    "get_driver_type",
    "get_active_driver",
    "is_interception_available",
    "set_target_window",
    "close",
):
    _original_method = getattr(ForegroundInputManager, _method_name, None)
    if callable(_original_method):
        setattr(ForegroundInputManager, _method_name, _guard_manager_state(_original_method))


# Global manager instance
_manager_instance = None
_manager_instance_lock = RLock()

def get_foreground_input_manager() -> ForegroundInputManager:
    """Get global foreground input manager."""
    global _manager_instance
    with _manager_instance_lock:
        if _manager_instance is None:
            _manager_instance = ForegroundInputManager()
        return _manager_instance


def _close_global_foreground_manager_on_exit() -> None:
    global _manager_instance
    with _manager_instance_lock:
        if _manager_instance is not None:
            try:
                _manager_instance.close()
            except Exception:
                pass


atexit.register(_close_global_foreground_manager_on_exit)





