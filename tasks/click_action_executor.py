# -*- coding: utf-8 -*-
"""
统一点击动作执行器
"""

from __future__ import annotations

import inspect
import math
import threading
import time
import ctypes
from typing import Any, Callable, Optional

from .task_utils import interruptible_sleep, precise_sleep
from utils.window.hwnd_utils import as_hwnd
from utils.input.input_guard import (
    acquire_input_guard,
    get_current_input_guard_resource,
    get_input_lock_wait_warn_ms,
    resolve_input_lock_resource,
)
from utils.input.input_timing import (
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


def _safe_int(value: Any, minimum: Optional[int] = None) -> int:
    result = int(value)
    if minimum is not None and result < minimum:
        raise ValueError(f"整数参数不能小于 {minimum}")
    return result


def _safe_float(value: Any, minimum: Optional[float] = None) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("时间参数必须是有限数值")
    if minimum is not None and result < minimum:
        raise ValueError(f"时间参数不能小于 {minimum}")
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
        return True


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
    precise_sleep(safe_duration)
    return True


def _is_foreground_click_context(simulator: Any, execution_mode: Any) -> bool:
    """判断当前点击是否处于前台上下文。"""
    if execution_mode is not None:
        return normalize_execution_mode(execution_mode) == "foreground"
    return bool(getattr(simulator, "use_foreground", False))


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
        _FOREGROUND_CLICK_LAST_TS.pop(key, None)
        if len(_FOREGROUND_CLICK_LAST_TS) >= 256:
            del _FOREGROUND_CLICK_LAST_TS[next(iter(_FOREGROUND_CLICK_LAST_TS))]
        _FOREGROUND_CLICK_LAST_TS[key] = time.monotonic()


def _get_cursor_position() -> Optional[tuple[int, int]]:
    try:
        point = _CursorPoint()
        if bool(ctypes.windll.user32.GetCursorPos(ctypes.byref(point))):
            return int(point.x), int(point.y)
    except Exception:
        return None
    return None


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
            return False
        if not pressed:
            return True

        if time.monotonic() >= deadline:
            break

        if not _sleep_with_stop(wait_slice, stop_checker):
            return False

    # 能读取状态但超时仍为按下，视为点击未完整结束。
    return False


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

    deadline = time.monotonic() + max(0.0, float(timeout or 0.0))
    wait_slice = max(0.001, float(poll_interval or 0.0))
    safe_tolerance = max(0, int(tolerance))

    while True:
        if _is_stop_requested(stop_checker):
            return False

        pos = _get_cursor_position()
        if pos is not None:
            if (
                abs(int(pos[0]) - target_x) <= safe_tolerance
                and abs(int(pos[1]) - target_y) <= safe_tolerance
            ):
                return True

        if time.monotonic() >= deadline:
            break

        if not _sleep_with_stop(wait_slice, stop_checker):
            return False

    return False


def _is_target_window_foreground(target_hwnd: Any) -> bool:
    """普通窗口须在前台才允许完整点击；桌面层不检查前台。"""
    try:
        hwnd = as_hwnd(target_hwnd)
    except Exception:
        return False
    if hwnd == 0:
        return False

    try:
        from utils.window.window_identity import is_desktop_window

        if is_desktop_window(hwnd):
            return True
    except Exception:
        pass

    try:
        import win32con
        import win32gui
    except Exception:
        return False

    try:
        fg_hwnd = as_hwnd(win32gui.GetForegroundWindow())
        if fg_hwnd == 0:
            return False
        if fg_hwnd == hwnd:
            return True
        fg_root = as_hwnd(win32gui.GetAncestor(fg_hwnd, win32con.GA_ROOT))
        target_root = as_hwnd(win32gui.GetAncestor(hwnd, win32con.GA_ROOT))
        return fg_root != 0 and target_root != 0 and fg_root == target_root
    except Exception:
        return False


def _ensure_target_window_foreground_for_click(
    target_hwnd: Any,
    *,
    mode_label: str,
    log_obj: Any,
) -> bool:
    """完整点击前确保目标在前台；丢焦时尝试恢复一次（罗技连线场景常见）。"""
    safe_hwnd = _safe_int(target_hwnd, minimum=0)
    if safe_hwnd <= 0:
        return True
    if _is_target_window_foreground(safe_hwnd):
        return True

    front = _front_window_name()
    if front:
        _log(
            log_obj,
            "warning",
            f"[{mode_label}] 要点的窗口不在最前面（现在最前面是「{front}」），尝试重新激活",
        )
    else:
        _log(log_obj, "warning", f"[{mode_label}] 要点的窗口不在最前面，尝试重新激活")

    try:
        from utils.window.window_activation_utils import activate_window

        activate_window(safe_hwnd, log_prefix=str(mode_label or "前台点击"))
    except Exception as err:
        _log(log_obj, "warning", f"[{mode_label}] 重新激活目标窗口失败: {err}")

    if _is_target_window_foreground(safe_hwnd):
        _log(log_obj, "info", f"[{mode_label}] 已重新激活目标窗口，继续点击")
        return True

    front_after = _front_window_name()
    if front_after:
        _log(
            log_obj,
            "warning",
            f"[{mode_label}] 要点的窗口不在最前面（现在最前面是「{front_after}」），已取消点击",
        )
    else:
        _log(log_obj, "warning", f"[{mode_label}] 要点的窗口不在最前面，已取消点击")
    return False


def _front_window_name() -> str:
    try:
        import win32gui

        hwnd = as_hwnd(win32gui.GetForegroundWindow())
        if hwnd <= 0:
            return ""
        title = (win32gui.GetWindowText(hwnd) or "").strip()
        if title:
            return title
        return (win32gui.GetClassName(hwnd) or "").strip()
    except Exception:
        return ""


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
        _log(log_obj, "error", f"[{mode_label}] 模拟器不支持移动鼠标")
        return False
    if _is_stop_requested(stop_checker):
        return False
    try:
        moved = bool(move_fn(int(x), int(y)))
    except Exception as err:
        _log(log_obj, "error", f"[{mode_label}] 移动鼠标失败：{err}")
        return False
    if not moved or not _wait_cursor_reach_target(int(x), int(y), stop_checker=stop_checker):
        _log(log_obj, "error", f"[{mode_label}] 鼠标未到达点击位置 ({x}, {y})")
        return False
    return True


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


def _invoke_native_double_click(
    simulator: Any,
    x: int,
    y: int,
    button_type: str,
    interval: float,
    hold_duration: float,
    mode_label: str,
    log_obj: Any,
) -> bool:
    double_fn = getattr(simulator, "double_click", None)
    if not callable(double_fn):
        _log(log_obj, "error", f"[{mode_label}] 模拟器不支持双击接口")
        return False
    try:
        return bool(double_fn(int(x), int(y), button_type,
                              interval=float(interval), hold_duration=float(hold_duration)))
    except Exception as err:
        _log(log_obj, "error", f"[{mode_label}] 双击执行失败：{err}")
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
    except Exception as err:
        _log(log_obj, "error", f"[{mode_label}] 原子按住执行失败: {err}")
        return False


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

    try:
        safe_clicks = _safe_int(clicks, minimum=1)
        safe_interval = _safe_float(interval, minimum=0.0)
        safe_hold_duration = _safe_float(hold_duration, minimum=0.0)
    except (TypeError, ValueError, OverflowError) as err:
        _log(logger_obj, "error", f"[{mode_label}] 点击参数无效：{err}")
        return False
    complete_click_hold_duration = (
        safe_hold_duration if safe_hold_duration > 0 else DEFAULT_CLICK_HOLD_SECONDS
    )

    def _run_click_action_locked(active_lock_resource: Optional[str] = None) -> bool:
        if _is_stop_requested(stop_checker):
            _log(logger_obj, "warning", f"[{mode_label}] 收到停止请求，取消点击")
            return False
        foreground_context = _is_foreground_click_context(simulator, execution_mode)
        complete_action = click_action in {"完整点击", "双击"} or (click_action == "仅按下" and auto_release)

        # 先检查按钮，再进行任何移动。按住或状态未知时禁止开始完整点击。
        if foreground_context and complete_action:
            for checked_button in _MOUSE_BUTTON_VK_MAP:
                if _is_mouse_button_pressed(checked_button) is not False:
                    button_label = {"left": "左键", "right": "右键", "middle": "中键"}[checked_button]
                    _log(logger_obj, "error", f"[{mode_label}] 鼠标{button_label}未确认松开，取消点击")
                    return False
            try:
                safe_target_hwnd = _safe_int(0 if target_hwnd is None else target_hwnd, minimum=0)
            except (TypeError, ValueError, OverflowError) as err:
                _log(logger_obj, "error", f"[{mode_label}] 目标窗口无效：{err}")
                return False
            if safe_target_hwnd > 0 and not _ensure_target_window_foreground_for_click(
                safe_target_hwnd, mode_label=mode_label, log_obj=logger_obj,
            ):
                return False

        if complete_action and click_action != "双击" and not _supports_atomic_click_hold(simulator):
            _log(logger_obj, "error", f"[{mode_label}] 模拟器不支持完整的点击按住接口")
            return False
        if foreground_context:
            cadence_ok, _ = _wait_foreground_click_gap(active_lock_resource, stop_checker)
            if not cadence_ok or not _sleep_with_stop(_FOREGROUND_PRE_CLICK_SETTLE_SECONDS, stop_checker):
                return False
            if complete_action and not _ensure_foreground_cursor_ready(
                simulator, int(x), int(y), mode_label, logger_obj, stop_checker,
            ):
                return False
        elif move_before_click and click_action != "仅松开":
            move_fn = getattr(simulator, "move_mouse", None)
            if not callable(move_fn):
                _log(logger_obj, "error", f"[{mode_label}] 模拟器不支持移动鼠标")
                return False
            try:
                if not bool(move_fn(int(x), int(y))):
                    return False
            except Exception as err:
                _log(logger_obj, "error", f"[{mode_label}] 点击前移动失败：{err}")
                return False

        success = False
        try:
            if click_action == "完整点击":
                for click_index in range(safe_clicks):
                    if _is_stop_requested(stop_checker):
                        return False
                    if click_index and not _sleep_with_stop(safe_interval, stop_checker):
                        return False
                    if not bool(simulator.click(int(x), int(y), button=button_type, clicks=1,
                                                interval=0.0, duration=complete_click_hold_duration)):
                        return False
                success = True
            elif click_action == "双击":
                success = _invoke_native_double_click(
                    simulator, int(x), int(y), button_type,
                    safe_interval if safe_interval > 0 else DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
                    complete_click_hold_duration, mode_label, logger_obj,
                )
            elif click_action == "仅按下":
                if auto_release:
                    success = bool(_invoke_atomic_click_hold(
                        simulator, int(x), int(y), button_type, complete_click_hold_duration,
                        mode_label, logger_obj,
                    ))
                else:
                    success = bool(simulator.mouse_down(int(x), int(y), button_type))
            elif click_action == "仅松开":
                # 松开必须直接发送；禁止先移动、校准或等待停止状态。
                success = bool(simulator.mouse_up(int(x), int(y), button_type))
            else:
                _log(logger_obj, "error", f"[{mode_label}] 不支持的点击动作：{click_action}")
                return False
        except Exception as err:
            _log(logger_obj, "error", f"[{mode_label}] 点击动作执行失败：{err}")
            return False
        finally:
            if foreground_context:
                _mark_foreground_click_completion(active_lock_resource)

        if foreground_context and success:
            if (complete_action or click_action == "仅松开") and not _wait_mouse_button_release(
                button_type, stop_checker=stop_checker,
            ):
                _log(logger_obj, "error", f"[{mode_label}] 鼠标弹起未确认，点击失败")
                return False
            if not _sleep_with_stop(_FOREGROUND_POST_CLICK_SETTLE_SECONDS, stop_checker):
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
