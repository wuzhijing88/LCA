# -*- coding: utf-8 -*-
"""
统一点击动作执行器
"""

from __future__ import annotations

import inspect
import threading
import time
import ctypes
from typing import Any, Callable, Optional

from .task_utils import interruptible_sleep, precise_sleep
from utils.input_guard import (
    acquire_input_guard,
    get_current_input_guard_resource,
    get_input_lock_wait_warn_ms,
    resolve_input_lock_resource,
)
from utils.input_timing import (
    DEFAULT_CLICK_HOLD_SECONDS,
    DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
)
from utils.input_simulation.mode_utils import normalize_execution_mode


_BUTTON_MAP = {
    "左键": "left",
    "右键": "right",
    "中键": "middle",
    "left": "left",
    "right": "right",
    "middle": "middle",
}

_FOREGROUND_PRE_CLICK_SETTLE_SECONDS = 0.020
_FOREGROUND_POST_CLICK_SETTLE_SECONDS = 0.080
_FOREGROUND_CLICK_MIN_GAP_SECONDS = 0.120
_FOREGROUND_BUTTON_RELEASE_TIMEOUT_SECONDS = 0.250
_FOREGROUND_BUTTON_RELEASE_POLL_SECONDS = 0.002
_FOREGROUND_CLICK_CADENCE_LOCK = threading.RLock()
_FOREGROUND_CLICK_LAST_TS: dict[str, float] = {}
_FOREGROUND_CURSOR_VERIFY_TIMEOUT_SECONDS = 0.200
_FOREGROUND_CURSOR_VERIFY_POLL_SECONDS = 0.002
_FOREGROUND_CURSOR_VERIFY_TOLERANCE = 2
_MOUSE_BUTTON_VK_MAP = {
    "left": 0x01,   # VK_LBUTTON
    "right": 0x02,  # VK_RBUTTON
    "middle": 0x04, # VK_MBUTTON
}


class _CursorPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def _normalize_button(button: Any) -> Optional[str]:
    text = str(button or "").strip().lower()
    if not text:
        return None
    return _BUTTON_MAP.get(text)


def _safe_int(value: Any, default: int = 0, minimum: Optional[int] = None) -> int:
    try:
        result = int(value)
    except Exception:
        result = int(default)
    if minimum is not None and result < minimum:
        result = minimum
    return result


def _safe_float(value: Any, default: float = 0.0, minimum: Optional[float] = None) -> float:
    try:
        result = float(value)
    except Exception:
        result = float(default)
    if minimum is not None and result < minimum:
        result = minimum
    return result


def _log(log_obj, level: str, message: str) -> None:
    if not log_obj:
        return
    fn = getattr(log_obj, level, None)
    if callable(fn):
        fn(message)


def _is_stop_requested(stop_checker: Optional[Callable[[], bool]]) -> bool:
    if not callable(stop_checker):
        return False
    try:
        return bool(stop_checker())
    except Exception:
        return False


def _sleep_with_stop(duration: float, stop_checker: Optional[Callable[[], bool]]) -> bool:
    safe_duration = max(0.0, float(duration or 0.0))
    if safe_duration <= 0:
        return True
    if _is_stop_requested(stop_checker):
        return False
    if callable(stop_checker):
        try:
            interruptible_sleep(safe_duration, stop_checker)
            return not _is_stop_requested(stop_checker)
        except InterruptedError:
            return False
        except Exception:
            # 防御性回退
            precise_sleep(safe_duration)
            return not _is_stop_requested(stop_checker)
    precise_sleep(safe_duration)
    return True


def _is_foreground_click_context(simulator: Any, execution_mode: Any) -> bool:
    """判断当前点击是否处于前台上下文。"""
    try:
        if normalize_execution_mode(str(execution_mode or "")) == "foreground":
            return True
    except Exception:
        pass

    try:
        if bool(getattr(simulator, "use_foreground", False)):
            return True
    except Exception:
        pass

    try:
        is_fg = getattr(simulator, "_is_foreground_mode", None)
        if callable(is_fg):
            return bool(is_fg())
    except Exception:
        pass

    return False


def _wait_foreground_click_gap(
    lock_resource: Optional[str],
    stop_checker: Optional[Callable[[], bool]],
) -> tuple[bool, float]:
    """
    为前台点击提供统一步间隔，降低连续点击被吞的概率。
    间隔按输入资源维度串行，不影响其他资源。
    """
    min_gap = max(0.0, float(_FOREGROUND_CLICK_MIN_GAP_SECONDS))
    if min_gap <= 0:
        return True, 0.0

    key = str(lock_resource or "").strip() or "__default_foreground_resource__"
    waited = 0.0

    while True:
        if _is_stop_requested(stop_checker):
            return False, waited

        with _FOREGROUND_CLICK_CADENCE_LOCK:
            now = time.monotonic()
            last_ts = float(_FOREGROUND_CLICK_LAST_TS.get(key, 0.0) or 0.0)
            remain = min_gap - (now - last_ts)
            if remain <= 0:
                return True, waited

        slice_wait = min(0.01, max(0.0, remain))
        if slice_wait <= 0:
            continue
        if not _sleep_with_stop(slice_wait, stop_checker):
            return False, waited
        waited += slice_wait


def _mark_foreground_click_completion(lock_resource: Optional[str]) -> None:
    key = str(lock_resource or "").strip() or "__default_foreground_resource__"
    with _FOREGROUND_CLICK_CADENCE_LOCK:
        _FOREGROUND_CLICK_LAST_TS[key] = time.monotonic()


def _get_cursor_position() -> Optional[tuple[int, int]]:
    try:
        point = _CursorPoint()
        if bool(ctypes.windll.user32.GetCursorPos(ctypes.byref(point))):
            return int(point.x), int(point.y)
    except Exception:
        return None
    return None


def _set_cursor_position(x: int, y: int) -> bool:
    try:
        return bool(ctypes.windll.user32.SetCursorPos(int(x), int(y)))
    except Exception:
        return False



def _is_mouse_button_pressed(button_type: str) -> Optional[bool]:
    vk_code = _MOUSE_BUTTON_VK_MAP.get(str(button_type or "").strip().lower())
    if vk_code is None:
        return None
    try:
        state = int(ctypes.windll.user32.GetAsyncKeyState(int(vk_code)))
        return bool(state & 0x8000)
    except Exception:
        return None


def _wait_mouse_button_release(
    button_type: str,
    stop_checker: Optional[Callable[[], bool]] = None,
    timeout: float = _FOREGROUND_BUTTON_RELEASE_TIMEOUT_SECONDS,
    poll_interval: float = _FOREGROUND_BUTTON_RELEASE_POLL_SECONDS,
) -> bool:
    """
    前台点击完成屏障：确认目标按钮已处于松开状态后再继续下一步骤。
    """
    deadline = time.monotonic() + max(0.0, float(timeout or 0.0))
    wait_slice = max(0.001, float(poll_interval or 0.0))

    while True:
        if _is_stop_requested(stop_checker):
            return False

        pressed = _is_mouse_button_pressed(button_type)
        if pressed is None:
            # 系统无法读取按键状态时不做硬失败，保持兼容性。
            return True
        if not pressed:
            return True

        if time.monotonic() >= deadline:
            break

        if not _sleep_with_stop(wait_slice, stop_checker):
            return False

    # 能读取状态但超时仍为按下，视为点击未完整结束。
    return False


def _force_release_mouse_button(
    simulator: Any,
    x: int,
    y: int,
    button_type: str,
    mode_label: str,
    log_obj: Any,
    stop_checker: Optional[Callable[[], bool]] = None,
) -> bool:
    """
    前台点击恢复：当检测到按键未弹起时，主动补发 mouse_up 进行修复。
    """
    mouse_up_fn = getattr(simulator, "mouse_up", None)
    if not callable(mouse_up_fn):
        return False

    points = []
    try:
        points.append((int(x), int(y)))
    except Exception:
        pass

    current_pos = _get_cursor_position()
    if current_pos is not None:
        points.append((int(current_pos[0]), int(current_pos[1])))

    if not points:
        return False

    for release_x, release_y in points:
        for _ in range(2):
            if _is_stop_requested(stop_checker):
                return False
            try:
                mouse_up_fn(int(release_x), int(release_y), button_type)
            except Exception:
                pass
            if _sleep_with_stop(0.01, stop_checker):
                pressed = _is_mouse_button_pressed(button_type)
                if pressed is False:
                    _log(log_obj, "warning", f"[{mode_label}] 已自动补发mouse_up并恢复弹起")
                    return True

    return _is_mouse_button_pressed(button_type) is False

def _wait_cursor_reach_target(
    x: int,
    y: int,
    stop_checker: Optional[Callable[[], bool]] = None,
    timeout: float = _FOREGROUND_CURSOR_VERIFY_TIMEOUT_SECONDS,
    poll_interval: float = _FOREGROUND_CURSOR_VERIFY_POLL_SECONDS,
    tolerance: int = _FOREGROUND_CURSOR_VERIFY_TOLERANCE,
) -> bool:
    try:
        target_x = int(x)
        target_y = int(y)
    except Exception:
        return False

    sampled = False
    deadline = time.monotonic() + max(0.0, float(timeout or 0.0))
    wait_slice = max(0.001, float(poll_interval or 0.0))
    safe_tolerance = max(0, int(tolerance))

    while True:
        if _is_stop_requested(stop_checker):
            return False

        pos = _get_cursor_position()
        if pos is not None:
            sampled = True
            if (
                abs(int(pos[0]) - target_x) <= safe_tolerance
                and abs(int(pos[1]) - target_y) <= safe_tolerance
            ):
                return True

        if time.monotonic() >= deadline:
            break

        if not _sleep_with_stop(wait_slice, stop_checker):
            return False

    # 无法读取系统光标时不做硬失败，避免兼容性问题导致全量点击失败。
    return not sampled


def _is_target_window_foreground(target_hwnd: Any) -> bool:
    """校验目标窗口是否在前台（支持根窗口一致）。"""
    try:
        hwnd = int(target_hwnd or 0)
    except Exception:
        return False
    if hwnd <= 0:
        return False

    try:
        import win32con
        import win32gui
    except Exception:
        return False

    try:
        fg_hwnd = int(win32gui.GetForegroundWindow() or 0)
        if fg_hwnd <= 0:
            return False
        if fg_hwnd == hwnd:
            return True
        fg_root = int(win32gui.GetAncestor(fg_hwnd, win32con.GA_ROOT) or 0)
        target_root = int(win32gui.GetAncestor(hwnd, win32con.GA_ROOT) or 0)
        return fg_root > 0 and target_root > 0 and fg_root == target_root
    except Exception:
        return False

def _ensure_foreground_cursor_ready(
    simulator: Any,
    x: int,
    y: int,
    mode_label: str,
    log_obj: Any,
    stop_checker: Optional[Callable[[], bool]] = None,
) -> bool:
    move_fn = getattr(simulator, "move_mouse", None)
    if not callable(move_fn):
        _log(log_obj, "error", f"[{mode_label}] 前台模式缺少move_mouse接口")
        return False

    max_attempts = 3
    target_x = int(x)
    target_y = int(y)
    for attempt in range(max_attempts):
        if _is_stop_requested(stop_checker):
            return False

        try:
            moved = bool(move_fn(target_x, target_y))
        except Exception as err:
            _log(log_obj, "warning", f"[{mode_label}] 前台落位异常: {err}")
            moved = False

        if moved and _wait_cursor_reach_target(
            target_x,
            target_y,
            stop_checker=stop_checker,
        ):
            return True

        if _set_cursor_position(target_x, target_y) and _wait_cursor_reach_target(
            target_x,
            target_y,
            stop_checker=stop_checker,
        ):
            return True

        if attempt < (max_attempts - 1):
            _sleep_with_stop(0.01, stop_checker)

    _log(log_obj, "error", f"[{mode_label}] 前台落位失败，坐标=({target_x}, {target_y})")
    return False


def _supports_atomic_click_hold(simulator: Any) -> bool:
    marker = getattr(simulator, "supports_atomic_click_hold", None)
    if isinstance(marker, bool):
        return marker

    click_fn = getattr(simulator, "click", None)
    if not callable(click_fn):
        return False

    try:
        sig = inspect.signature(click_fn)
    except Exception:
        return False

    if "duration" in sig.parameters:
        return True

    for param in sig.parameters.values():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True
    return False


def _prefer_atomic_foreground_click(simulator: Any) -> bool:
    """
    在特定前台驱动下优先走原子click链路，避免down/up分离引入时序偏差。
    """
    try:
        backend_getter = getattr(simulator, "_get_foreground_mouse_backend", None)
        if callable(backend_getter):
            backend_name = str(backend_getter() or "").strip().lower()
            if backend_name in {"ibinputsimulator", "pyautogui"}:
                return True
    except Exception:
        pass

    try:
        driver_obj = getattr(simulator, "driver", None)
        if driver_obj is not None:
            driver_name = type(driver_obj).__name__.lower()
            if "ibinput" in driver_name:
                return True
            if "pyautogui" in driver_name:
                return True
            mouse_driver = getattr(driver_obj, "_mouse_driver", None)
            if mouse_driver is not None:
                mouse_driver_name = type(mouse_driver).__name__.lower()
                if "ibinput" in mouse_driver_name or "pyautogui" in mouse_driver_name:
                    return True
    except Exception:
        pass

    return False


def _invoke_atomic_click_hold(
    simulator: Any,
    x: int,
    y: int,
    button_type: str,
    hold_duration: float,
    mode_label: str,
    log_obj: Any,
) -> Optional[bool]:
    click_fn = getattr(simulator, "click", None)
    if not callable(click_fn):
        return None

    try:
        return bool(
            click_fn(
                int(x),
                int(y),
                button=button_type,
                clicks=1,
                interval=0.0,
                duration=float(hold_duration),
            )
        )
    except TypeError:
        return None
    except Exception as err:
        _log(log_obj, "error", f"[{mode_label}] 原子按住执行失败: {err}")
        return False


def _single_click_with_retry(
    simulator: Any,
    x: int,
    y: int,
    button_type: str,
    interval: float,
    mode_label: str,
    log_obj: Any,
    hold_duration: Optional[float] = None,
    stop_checker: Optional[Callable[[], bool]] = None,
) -> bool:
    try:
        if hold_duration is not None:
            first_ok = bool(
                simulator.click(
                    x,
                    y,
                    button=button_type,
                    clicks=1,
                    interval=interval,
                    duration=float(hold_duration),
                )
            )
        else:
            first_ok = bool(
                simulator.click(
                    x,
                    y,
                    button=button_type,
                    clicks=1,
                    interval=interval,
                )
            )
    except Exception as err:
        _log(log_obj, "warning", f"[{mode_label}] 单击执行异常: {err}")
        first_ok = False

    if first_ok:
        return True

    retry_wait = min(0.1, interval) if interval > 0 else 0.03
    if retry_wait > 0:
        if not _sleep_with_stop(retry_wait, stop_checker):
            _log(log_obj, "warning", f"[{mode_label}] 单击补发前收到停止请求")
            return False

    _log(log_obj, "warning", f"[{mode_label}] 单击未成功，执行补发")
    try:
        if hold_duration is not None:
            second_ok = bool(
                simulator.click(
                    x,
                    y,
                    button=button_type,
                    clicks=1,
                    interval=interval,
                    duration=float(hold_duration),
                )
            )
        else:
            second_ok = bool(
                simulator.click(
                    x,
                    y,
                    button=button_type,
                    clicks=1,
                    interval=interval,
                )
            )
    except Exception as err:
        _log(log_obj, "warning", f"[{mode_label}] 补发执行异常: {err}")
        second_ok = False

    return second_ok


def _foreground_single_click_via_down_up(
    simulator: Any,
    x: int,
    y: int,
    button_type: str,
    hold_duration: float,
    mode_label: str,
    log_obj: Any,
    stop_checker: Optional[Callable[[], bool]] = None,
) -> bool:
    mouse_down_fn = getattr(simulator, "mouse_down", None)
    mouse_up_fn = getattr(simulator, "mouse_up", None)
    if not callable(mouse_down_fn) or not callable(mouse_up_fn):
        return False

    safe_hold = max(0.0, float(hold_duration or 0.0))
    down_sent = False
    hold_completed = True
    try:
        if not bool(mouse_down_fn(int(x), int(y), button_type)):
            return False
        down_sent = True
        if safe_hold > 0:
            hold_completed = _sleep_with_stop(safe_hold, stop_checker)
        if not bool(mouse_up_fn(int(x), int(y), button_type)):
            return False
        down_sent = False
        return bool(hold_completed)
    except Exception as err:
        _log(log_obj, "warning", f"[{mode_label}] 前台down/up点击异常: {err}")
        return False
    finally:
        if down_sent:
            try:
                mouse_up_fn(int(x), int(y), button_type)
            except Exception:
                pass


def _foreground_single_click_with_retry(
    simulator: Any,
    x: int,
    y: int,
    button_type: str,
    hold_duration: float,
    interval: float,
    mode_label: str,
    log_obj: Any,
    stop_checker: Optional[Callable[[], bool]] = None,
    align_before_click: Optional[Callable[[], bool]] = None,
) -> bool:
    if callable(align_before_click):
        try:
            if not bool(align_before_click()):
                _log(log_obj, "warning", f"[{mode_label}] 前台点击前落位失败")
                return False
        except Exception as err:
            _log(log_obj, "warning", f"[{mode_label}] 前台点击前落位异常: {err}")
            return False

    first_ok = _foreground_single_click_via_down_up(
        simulator=simulator,
        x=int(x),
        y=int(y),
        button_type=button_type,
        hold_duration=float(hold_duration),
        mode_label=mode_label,
        log_obj=log_obj,
        stop_checker=stop_checker,
    )
    if first_ok:
        return True

    retry_wait = min(0.1, float(interval or 0.0)) if interval > 0 else 0.03
    if retry_wait > 0:
        if not _sleep_with_stop(retry_wait, stop_checker):
            _log(log_obj, "warning", f"[{mode_label}] 前台补发前收到停止请求")
            return False

    if callable(align_before_click):
        try:
            if not bool(align_before_click()):
                _log(log_obj, "warning", f"[{mode_label}] 前台补发前落位失败")
                return False
        except Exception as err:
            _log(log_obj, "warning", f"[{mode_label}] 前台补发前落位异常: {err}")
            return False

    _log(log_obj, "warning", f"[{mode_label}] 前台单击未成功，执行补发")
    return _foreground_single_click_via_down_up(
        simulator=simulator,
        x=int(x),
        y=int(y),
        button_type=button_type,
        hold_duration=float(hold_duration),
        mode_label=mode_label,
        log_obj=log_obj,
        stop_checker=stop_checker,
    )


def execute_simulator_click_action(
    simulator: Any,
    x: int,
    y: int,
    button: Any = "left",
    click_action: str = "完整点击",
    clicks: int = 1,
    interval: float = DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
    hold_duration: float = DEFAULT_CLICK_HOLD_SECONDS,
    auto_release: bool = True,
    mode_label: str = "点击",
    logger_obj: Any = None,
    call_lock: Any = None,
    single_click_retry: bool = False,
    require_atomic_hold: bool = False,
    move_before_click: bool = False,
    stop_checker: Optional[Callable[[], bool]] = None,
    execution_mode: Any = None,
    target_hwnd: Any = None,
    lock_resource: Optional[str] = None,
    task_type: str = "模拟鼠标操作",
) -> bool:
    """
    统一执行点击动作（完整点击/双击/仅按下/仅松开）。
    """
    if simulator is None:
        _log(logger_obj, "error", f"[{mode_label}] 输入模拟器为空")
        return False

    button_type = _normalize_button(button)
    if button_type is None:
        _log(logger_obj, "error", f"[{mode_label}] 不支持的按钮类型: {button}")
        return False

    safe_clicks = _safe_int(clicks, default=1, minimum=1)
    safe_interval = _safe_float(interval, default=0.0, minimum=0.0)
    safe_hold_duration = _safe_float(hold_duration, default=0.0, minimum=0.0)
    complete_click_hold_duration = (
        safe_hold_duration if safe_hold_duration > 0 else DEFAULT_CLICK_HOLD_SECONDS
    )

    def _run_click_action_locked(active_lock_resource: Optional[str] = None) -> bool:
        if _is_stop_requested(stop_checker):
            _log(logger_obj, "warning", f"[{mode_label}] 收到停止请求，取消点击")
            return False
        foreground_context = _is_foreground_click_context(
            simulator,
            execution_mode,
        )
        is_complete_click = (click_action == "完整点击")
        # 根因修复：前台驱动在高负载下可能消费到旧坐标，执行层需在每次点击前做强制落位校验。
        def _align_foreground_cursor() -> bool:
            return _ensure_foreground_cursor_ready(
                simulator=simulator,
                x=int(x),
                y=int(y),
                mode_label=mode_label,
                log_obj=logger_obj,
                stop_checker=stop_checker,
            )

        # 后台消息点击没有“先移动再点”的语义，移动前置只允许前台上下文使用。
        effective_move_before_click = bool(move_before_click) and foreground_context
        if effective_move_before_click:
            move_fn = getattr(simulator, "move_mouse", None)
            if callable(move_fn):
                try:
                    moved = bool(move_fn(int(x), int(y)))
                except Exception as err:
                    _log(logger_obj, "error", f"[{mode_label}] 点击前移动失败: {err}")
                    return False
                if not moved:
                    _log(logger_obj, "error", f"[{mode_label}] 点击前移动失败")
                    return False
            else:
                _log(logger_obj, "warning", f"[{mode_label}] 模拟器不支持move_mouse，跳过点击前移动")
        if foreground_context:
            cadence_ok, waited_gap = _wait_foreground_click_gap(
                active_lock_resource,
                stop_checker,
            )
            if not cadence_ok:
                _log(logger_obj, "warning", f"[{mode_label}] 前台点击步间隔等待被中断")
                return False
            if waited_gap > 0.001:
                _log(logger_obj, "debug", f"[{mode_label}] 前台点击步间隔等待 {waited_gap * 1000.0:.1f}ms")
            if not _sleep_with_stop(_FOREGROUND_PRE_CLICK_SETTLE_SECONDS, stop_checker):
                _log(logger_obj, "warning", f"[{mode_label}] 点击前稳定等待被中断")
                return False

        # 仅“完整点击”执行点击前验证；验证失败前禁止发送任何点击。
        if foreground_context and is_complete_click:
            pressed_before_click = _is_mouse_button_pressed(button_type)
            if pressed_before_click is True:
                _log(logger_obj, "warning", f"[{mode_label}] 点击前检测到鼠标按键残留按下，尝试自动释放")
                if not _force_release_mouse_button(
                    simulator=simulator,
                    x=int(x),
                    y=int(y),
                    button_type=button_type,
                    mode_label=mode_label,
                    log_obj=logger_obj,
                    stop_checker=stop_checker,
                ):
                    _log(logger_obj, "warning", f"[{mode_label}] 点击前按键残留未恢复，已阻止点击")
                    return False
            safe_target_hwnd = _safe_int(target_hwnd, default=0, minimum=0)
            if safe_target_hwnd > 0 and not _is_target_window_foreground(safe_target_hwnd):
                _log(logger_obj, "warning", f"[{mode_label}] 完整点击前验证失败，目标窗口不在前台，已阻止点击")
                return False
            if not _align_foreground_cursor():
                _log(logger_obj, "warning", f"[{mode_label}] 完整点击前验证失败，已阻止点击")
                return False
        click_attempted = False
        success = False
        try:
            click_attempted = True
            if click_action == "完整点击":
                use_foreground_down_up = (
                    foreground_context
                    and hasattr(simulator, "mouse_down")
                    and hasattr(simulator, "mouse_up")
                    and (not _prefer_atomic_foreground_click(simulator))
                )
                if use_foreground_down_up:
                    if safe_clicks == 1 and single_click_retry:
                        success = _foreground_single_click_with_retry(
                            simulator=simulator,
                            x=int(x),
                            y=int(y),
                            button_type=button_type,
                            hold_duration=complete_click_hold_duration,
                            interval=safe_interval,
                            mode_label=mode_label,
                            log_obj=logger_obj,
                            stop_checker=stop_checker,
                            align_before_click=None,
                        )
                    else:
                        success = True
                        for click_index in range(safe_clicks):
                            if _is_stop_requested(stop_checker):
                                _log(logger_obj, "warning", f"[{mode_label}] 连续点击过程中收到停止请求")
                                return False
                            if click_index > 0 and safe_interval > 0:
                                if not _sleep_with_stop(safe_interval, stop_checker):
                                    _log(logger_obj, "warning", f"[{mode_label}] 连续点击间隔被中断")
                                    return False
                            click_ok = _foreground_single_click_via_down_up(
                                simulator=simulator,
                                x=int(x),
                                y=int(y),
                                button_type=button_type,
                                hold_duration=complete_click_hold_duration,
                                mode_label=mode_label,
                                log_obj=logger_obj,
                                stop_checker=stop_checker,
                            )
                            if not click_ok:
                                success = False
                                break
                else:
                    if not hasattr(simulator, "click"):
                        _log(logger_obj, "error", f"[{mode_label}] 模拟器不支持click接口")
                        return False
                    atomic_click_hold_supported = _supports_atomic_click_hold(simulator)
                    if safe_clicks == 1 and single_click_retry:
                        retry_hold_duration = (
                            complete_click_hold_duration if atomic_click_hold_supported else None
                        )
                        success = _single_click_with_retry(
                            simulator,
                            int(x),
                            int(y),
                            button_type,
                            safe_interval,
                            mode_label,
                            logger_obj,
                            hold_duration=retry_hold_duration,
                            stop_checker=stop_checker,
                        )
                    else:
                        success = True
                        for click_index in range(safe_clicks):
                            if _is_stop_requested(stop_checker):
                                _log(logger_obj, "warning", f"[{mode_label}] 连续点击过程中收到停止请求")
                                return False
                            if click_index > 0 and safe_interval > 0:
                                if not _sleep_with_stop(safe_interval, stop_checker):
                                    _log(logger_obj, "warning", f"[{mode_label}] 连续点击间隔被中断")
                                    return False
                            if atomic_click_hold_supported:
                                click_ok = bool(
                                    simulator.click(
                                        int(x),
                                        int(y),
                                        button=button_type,
                                        clicks=1,
                                        interval=0.0,
                                        duration=complete_click_hold_duration,
                                    )
                                )
                            else:
                                click_ok = bool(
                                    simulator.click(
                                        int(x),
                                        int(y),
                                        button=button_type,
                                        clicks=1,
                                        interval=0.0,
                                    )
                                )
                            if not click_ok:
                                success = False
                                break
            elif click_action == "双击":
                if not hasattr(simulator, "click"):
                    _log(logger_obj, "error", f"[{mode_label}] 模拟器不支持click接口")
                    return False
                atomic_click_hold_supported = _supports_atomic_click_hold(simulator)
                dbl_interval = safe_interval if safe_interval > 0 else DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS
                if atomic_click_hold_supported:
                    first_ok = bool(
                        simulator.click(
                            int(x),
                            int(y),
                            button=button_type,
                            clicks=1,
                            interval=0.0,
                            duration=complete_click_hold_duration,
                        )
                    )
                else:
                    first_ok = bool(
                        simulator.click(
                            int(x),
                            int(y),
                            button=button_type,
                            clicks=1,
                            interval=0.0,
                        )
                    )
                if not first_ok:
                    success = False
                else:
                    if dbl_interval > 0:
                        if not _sleep_with_stop(dbl_interval, stop_checker):
                            _log(logger_obj, "warning", f"[{mode_label}] 双击间隔被中断")
                            return False
                    if atomic_click_hold_supported:
                        success = bool(
                            simulator.click(
                                int(x),
                                int(y),
                                button=button_type,
                                clicks=1,
                                interval=0.0,
                                duration=complete_click_hold_duration,
                            )
                        )
                    else:
                        success = bool(
                            simulator.click(
                                int(x),
                                int(y),
                                button=button_type,
                                clicks=1,
                                interval=0.0,
                            )
                        )
            elif click_action == "仅按下":
                effective_hold_duration = (
                    safe_hold_duration if safe_hold_duration > 0 else DEFAULT_CLICK_HOLD_SECONDS
                )
                if auto_release:
                    atomic_supported = _supports_atomic_click_hold(simulator)
                    if atomic_supported:
                        atomic_success = _invoke_atomic_click_hold(
                            simulator,
                            int(x),
                            int(y),
                            button_type,
                            effective_hold_duration,
                            mode_label,
                            logger_obj,
                        )
                        if atomic_success is None:
                            _log(logger_obj, "error", f"[{mode_label}] 原子按住调用签名不支持duration参数")
                            return False
                        return bool(atomic_success)
                    if require_atomic_hold:
                        _log(logger_obj, "error", f"[{mode_label}] 当前模拟器不支持原子按住")
                        return False

                if not hasattr(simulator, "mouse_down"):
                    _log(logger_obj, "error", f"[{mode_label}] 模拟器不支持mouse_down接口")
                    return False
                success = bool(simulator.mouse_down(int(x), int(y), button_type))
                if success and auto_release:
                    if not hasattr(simulator, "mouse_up"):
                        _log(logger_obj, "error", f"[{mode_label}] 模拟器不支持mouse_up接口")
                        return False
                    hold_completed = _sleep_with_stop(effective_hold_duration, stop_checker)
                    if not hold_completed:
                        _log(logger_obj, "warning", f"[{mode_label}] 按住期间收到停止请求，提前释放")
                    released = bool(simulator.mouse_up(int(x), int(y), button_type))
                    if not released:
                        return False
                    if not hold_completed:
                        return False
                    success = released
            elif click_action == "仅松开":
                if not hasattr(simulator, "mouse_up"):
                    _log(logger_obj, "error", f"[{mode_label}] 模拟器不支持mouse_up接口")
                    return False
                success = bool(simulator.mouse_up(int(x), int(y), button_type))
            else:
                _log(logger_obj, "error", f"[{mode_label}] 不支持的点击动作: {click_action}")
                return False
        except Exception as err:
            _log(logger_obj, "error", f"[{mode_label}] 点击动作执行失败: {err}")
            return False
        finally:
            if foreground_context and click_attempted:
                _mark_foreground_click_completion(active_lock_resource)

        if foreground_context and success:
            if click_action in {"完整点击", "双击", "仅松开"}:
                if not _wait_mouse_button_release(button_type, stop_checker=stop_checker):
                    _log(logger_obj, "warning", f"[{mode_label}] 前台点击完成后检测到鼠标按键仍未松开，尝试自动恢复")
                    recovered = _force_release_mouse_button(
                        simulator=simulator,
                        x=int(x),
                        y=int(y),
                        button_type=button_type,
                        mode_label=mode_label,
                        log_obj=logger_obj,
                        stop_checker=stop_checker,
                    )
                    if not recovered:
                        _log(logger_obj, "warning", f"[{mode_label}] 前台点击后按键恢复失败")
                        return False
                    if not _wait_mouse_button_release(button_type, stop_checker=stop_checker, timeout=0.12):
                        _log(logger_obj, "warning", f"[{mode_label}] 前台点击恢复后按键仍未松开")
                        return False
            if not _sleep_with_stop(_FOREGROUND_POST_CLICK_SETTLE_SECONDS, stop_checker):
                _log(logger_obj, "warning", f"[{mode_label}] 点击后稳定等待被中断")
                return False

        return bool(success)
    if call_lock is not None:
        call_lock_resource = str(lock_resource or "").strip()
        if not call_lock_resource:
            call_lock_resource = str(get_current_input_guard_resource() or "").strip()
        if not call_lock_resource:
            call_lock_resource = resolve_input_lock_resource(
                execution_mode=execution_mode,
                target_hwnd=target_hwnd,
                task_type=task_type or "模拟鼠标操作",
            )
        with call_lock as lock_state:
            if (
                isinstance(lock_state, tuple)
                and len(lock_state) >= 1
                and lock_state[0] is False
            ):
                _log(logger_obj, "error", f"[{mode_label}] 获取输入锁失败")
                return False
            return _run_click_action_locked(call_lock_resource)

    resolved_lock_resource = str(lock_resource or "").strip()
    if not resolved_lock_resource:
        resolved_lock_resource = str(get_current_input_guard_resource() or "").strip()
    if not resolved_lock_resource:
        resolved_lock_resource = resolve_input_lock_resource(
            execution_mode=execution_mode,
            target_hwnd=target_hwnd,
            task_type=task_type or "模拟鼠标操作",
        )

    lock_owner = (
        f"click:{mode_label}, thread={threading.get_ident()}, resource={resolved_lock_resource}"
    )
    wait_slice = 0.2
    total_wait_ms = 0.0
    wait_warn_ms = get_input_lock_wait_warn_ms()
    while True:
        if _is_stop_requested(stop_checker):
            _log(logger_obj, "warning", f"[{mode_label}] 等待输入锁期间收到停止请求")
            return False
        with acquire_input_guard(
            owner=lock_owner,
            timeout=wait_slice,
            resource=resolved_lock_resource,
        ) as (acquired, wait_ms):
            total_wait_ms += max(0.0, float(wait_ms))
            if not acquired:
                continue
            if total_wait_ms >= wait_warn_ms:
                _log(
                    logger_obj,
                    "warning",
                    f"[{mode_label}] 等待输入锁 {total_wait_ms:.1f}ms "
                    f"(阈值 {wait_warn_ms:.1f}ms)",
                )
            elif total_wait_ms > 20.0:
                _log(logger_obj, "debug", f"[{mode_label}] 等待输入锁 {total_wait_ms:.1f}ms")
            return _run_click_action_locked(resolved_lock_resource)




