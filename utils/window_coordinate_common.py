#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""UI 坐标与 DPI 公共方法。"""

import ctypes
from ctypes import wintypes
from typing import Any, Callable, Dict, List, Optional, Tuple

from utils.dpi_awareness import get_process_dpi_awareness

_MONITORINFOF_PRIMARY = 0x00000001
_MONITOR_DEFAULTTONEAREST = 0x00000002


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


def _rect_struct_to_tuple(rect: _RECT) -> Tuple[int, int, int, int]:
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def _get_monitor_info_from_handle(monitor_handle) -> Optional[Dict[str, Any]]:
    if not monitor_handle or getattr(ctypes, "windll", None) is None:
        return None

    try:
        user32 = ctypes.windll.user32
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MONITORINFOEXW)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL

        monitor_info = _MONITORINFOEXW()
        monitor_info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if not user32.GetMonitorInfoW(monitor_handle, ctypes.byref(monitor_info)):
            return None

        return {
            "Device": str(monitor_info.szDevice),
            "Monitor": _rect_struct_to_tuple(monitor_info.rcMonitor),
            "Work": _rect_struct_to_tuple(monitor_info.rcWork),
            "Flags": int(monitor_info.dwFlags),
            "Primary": bool(int(monitor_info.dwFlags) & _MONITORINFOF_PRIMARY),
        }
    except Exception:
        return None


def _safe_positive_int(value: Any, default: int = 96) -> int:
    try:
        num = int(value)
        return num if num > 0 else default
    except Exception:
        return default


def _get_qt_application():
    try:
        from PySide6.QtWidgets import QApplication
        return QApplication.instance()
    except Exception:
        return None


def _normalize_iterable(items: Any) -> List[Any]:
    if items is None:
        return []

    try:
        return [item for item in list(items) if item is not None]
    except Exception:
        return []


def _get_qt_screens() -> List[Any]:
    app = _get_qt_application()
    if app is None:
        return []

    try:
        screens = _normalize_iterable(app.screens())
        if screens:
            return screens
    except Exception:
        pass

    try:
        from PySide6.QtGui import QGuiApplication

        screens = _normalize_iterable(QGuiApplication.screens())
        if screens:
            return screens
    except Exception:
        pass

    try:
        primary = app.primaryScreen()
        return [primary] if primary is not None else []
    except Exception:
        return []


def _enum_monitor_infos():
    if getattr(ctypes, "windll", None) is None:
        return []

    try:
        user32 = ctypes.windll.user32
        callback_handles: List[Any] = []
        monitor_enum_proc = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            wintypes.HANDLE,
            wintypes.HDC,
            ctypes.POINTER(_RECT),
            wintypes.LPARAM,
        )

        @monitor_enum_proc
        def _enum_proc(hmonitor, hdc, lprect, lparam):
            callback_handles.append(hmonitor)
            return 1

        user32.EnumDisplayMonitors.argtypes = [
            wintypes.HDC,
            ctypes.POINTER(_RECT),
            monitor_enum_proc,
            wintypes.LPARAM,
        ]
        user32.EnumDisplayMonitors.restype = wintypes.BOOL

        if not user32.EnumDisplayMonitors(None, None, _enum_proc, 0):
            return []

        monitor_infos = []
        for monitor_handle in callback_handles:
            info = _get_monitor_info_from_handle(monitor_handle)
            if info:
                monitor_infos.append(info)
        return monitor_infos
    except Exception:
        return []


def _get_monitor_rect(info: Optional[Dict[str, Any]]) -> Optional[Tuple[int, int, int, int]]:
    if not info or not isinstance(info, dict):
        return None

    try:
        monitor_rect = info.get("Monitor")
        if not monitor_rect or len(monitor_rect) != 4:
            return None
        left, top, right, bottom = [int(v) for v in monitor_rect]
        if right <= left or bottom <= top:
            return None
        return left, top, right, bottom
    except Exception:
        return None


def _get_qt_rect(screen) -> Optional[Tuple[int, int, int, int]]:
    if screen is None:
        return None

    try:
        geometry = screen.geometry()
        left = int(geometry.x())
        top = int(geometry.y())
        right = left + int(geometry.width())
        bottom = top + int(geometry.height())
        if right <= left or bottom <= top:
            return None
        return left, top, right, bottom
    except Exception:
        return None


def _get_rect_size(rect: Tuple[int, int, int, int]) -> Tuple[float, float]:
    left, top, right, bottom = rect
    return max(1.0, float(right - left)), max(1.0, float(bottom - top))


def _get_rect_center(rect: Tuple[int, int, int, int]) -> Tuple[float, float]:
    left, top, right, bottom = rect
    return ((left + right) / 2.0, (top + bottom) / 2.0)


def _get_virtual_bounds(rects: List[Tuple[int, int, int, int]]) -> Optional[Tuple[int, int, int, int]]:
    if not rects:
        return None

    left = min(rect[0] for rect in rects)
    top = min(rect[1] for rect in rects)
    right = max(rect[2] for rect in rects)
    bottom = max(rect[3] for rect in rects)
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _get_normalized_center(
    rect: Tuple[int, int, int, int],
    virtual_bounds: Optional[Tuple[int, int, int, int]],
) -> Tuple[float, float]:
    if not virtual_bounds:
        return 0.5, 0.5

    v_left, v_top, v_right, v_bottom = virtual_bounds
    v_width = max(1.0, float(v_right - v_left))
    v_height = max(1.0, float(v_bottom - v_top))
    center_x, center_y = _get_rect_center(rect)
    return ((center_x - v_left) / v_width, (center_y - v_top) / v_height)


def _get_normalized_size(
    rect: Tuple[int, int, int, int],
    virtual_bounds: Optional[Tuple[int, int, int, int]],
) -> Tuple[float, float, float]:
    width, height = _get_rect_size(rect)
    aspect_ratio = width / max(1.0, height)
    if not virtual_bounds:
        return width, height, aspect_ratio

    v_left, v_top, v_right, v_bottom = virtual_bounds
    v_width = max(1.0, float(v_right - v_left))
    v_height = max(1.0, float(v_bottom - v_top))
    return width / v_width, height / v_height, aspect_ratio


def _get_screen_name(screen) -> str:
    if screen is None:
        return ""

    try:
        return str(screen.name()).strip().lower()
    except Exception:
        return ""


def _get_screen_signature(screen) -> Tuple[str, Optional[Tuple[int, int, int, int]]]:
    return _get_screen_name(screen), _get_qt_rect(screen)


def _screen_matches(screen_a, screen_b) -> bool:
    if screen_a is None or screen_b is None:
        return False

    if screen_a is screen_b:
        return True

    name_a, rect_a = _get_screen_signature(screen_a)
    name_b, rect_b = _get_screen_signature(screen_b)
    if name_a and name_b and name_a == name_b:
        return True
    return rect_a is not None and rect_a == rect_b


def _build_monitor_screen_pairs():
    screens = _normalize_iterable(_get_qt_screens())
    monitor_infos = [
        info for info in _normalize_iterable(_enum_monitor_infos())
        if isinstance(info, dict)
    ]
    if not screens or not monitor_infos:
        return []

    pairs = []
    used_screen_ids = set()
    used_monitor_keys = set()

    def _screen_id(screen) -> int:
        return id(screen)

    def _monitor_key(info: Dict[str, Any]):
        rect = _get_monitor_rect(info)
        device_name = str(info.get("Device", "")).strip().lower()
        return (device_name, rect)

    for screen in screens:
        screen_name = _get_screen_name(screen)
        if not screen_name:
            continue

        for info in monitor_infos:
            device_name = str(info.get("Device", "")).strip().lower()
            if device_name and device_name == screen_name:
                pairs.append((screen, info))
                used_screen_ids.add(_screen_id(screen))
                used_monitor_keys.add(_monitor_key(info))
                break

    remaining_screens = [screen for screen in screens if _screen_id(screen) not in used_screen_ids]
    remaining_monitors = [info for info in monitor_infos if _monitor_key(info) not in used_monitor_keys]
    if not remaining_screens or not remaining_monitors:
        return pairs

    qt_rects = []
    for screen in remaining_screens:
        rect = _get_qt_rect(screen)
        if rect:
            qt_rects.append(rect)
    native_rects = []
    for info in remaining_monitors:
        rect = _get_monitor_rect(info)
        if rect:
            native_rects.append(rect)

    qt_virtual_bounds = _get_virtual_bounds(qt_rects)
    native_virtual_bounds = _get_virtual_bounds(native_rects)

    while remaining_screens and remaining_monitors:
        best_pair = None
        best_cost = None

        for screen in remaining_screens:
            qt_rect = _get_qt_rect(screen)
            if not qt_rect:
                continue
            qt_center = _get_normalized_center(qt_rect, qt_virtual_bounds)
            qt_width_ratio, qt_height_ratio, qt_aspect = _get_normalized_size(
                qt_rect,
                qt_virtual_bounds,
            )

            for info in remaining_monitors:
                native_rect = _get_monitor_rect(info)
                if not native_rect:
                    continue
                native_center = _get_normalized_center(native_rect, native_virtual_bounds)
                native_width_ratio, native_height_ratio, native_aspect = _get_normalized_size(
                    native_rect,
                    native_virtual_bounds,
                )
                center_cost = abs(qt_center[0] - native_center[0]) + abs(qt_center[1] - native_center[1])
                size_cost = abs(qt_width_ratio - native_width_ratio) + abs(qt_height_ratio - native_height_ratio)
                aspect_cost = abs(qt_aspect - native_aspect)
                total_cost = (center_cost * 4.0) + (size_cost * 2.5) + (aspect_cost * 0.5)
                if best_cost is None or total_cost < best_cost:
                    best_cost = total_cost
                    best_pair = (screen, info)

        if best_pair is None:
            break

        screen, info = best_pair
        pairs.append((screen, info))
        remaining_screens = [item for item in remaining_screens if item is not screen]
        target_key = _monitor_key(info)
        remaining_monitors = [item for item in remaining_monitors if _monitor_key(item) != target_key]

    return pairs


def _get_monitor_info_from_native_point(x: int, y: int):
    if getattr(ctypes, "windll", None) is None:
        return None

    try:
        user32 = ctypes.windll.user32
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.MonitorFromPoint.restype = wintypes.HANDLE

        monitor_handle = user32.MonitorFromPoint(
            wintypes.POINT(int(x), int(y)),
            _MONITOR_DEFAULTTONEAREST,
        )
        return _get_monitor_info_from_handle(monitor_handle)
    except Exception:
        return None


def _get_monitor_info_from_hwnd(hwnd: int):
    if getattr(ctypes, "windll", None) is None:
        return None

    try:
        hwnd_int = int(hwnd)
        if hwnd_int == 0:
            return None

        user32 = ctypes.windll.user32
        user32.MonitorFromWindow.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HANDLE

        monitor_handle = user32.MonitorFromWindow(
            wintypes.HANDLE(hwnd_int),
            _MONITOR_DEFAULTTONEAREST,
        )
        return _get_monitor_info_from_handle(monitor_handle)
    except Exception:
        return None


def _resolve_qt_screen_for_widget_native_window(widget):
    if widget is None:
        return None

    candidates = []
    try:
        top_level = widget.window() if hasattr(widget, "window") else None
        if top_level is not None:
            candidates.append(top_level)
    except Exception:
        pass
    candidates.append(widget)

    seen_ids = set()
    for candidate in candidates:
        if candidate is None:
            continue
        marker = id(candidate)
        if marker in seen_ids:
            continue
        seen_ids.add(marker)

        try:
            hwnd = int(candidate.winId())
        except Exception:
            hwnd = 0
        if hwnd == 0:
            continue

        monitor_info = _get_monitor_info_from_hwnd(hwnd)
        screen = _resolve_qt_screen_for_monitor(monitor_info)
        if screen is not None:
            return screen

    return None


def _get_monitor_info_for_qt_screen(qt_screen):
    if qt_screen is None:
        return None

    try:
        qt_name = str(qt_screen.name()).strip().lower()
    except Exception:
        qt_name = ""

    monitor_infos = [
        info for info in _normalize_iterable(_enum_monitor_infos())
        if isinstance(info, dict)
    ]
    if qt_name:
        for info in monitor_infos:
            device_name = str(info.get("Device", "")).strip().lower()
            if device_name == qt_name:
                return info

    for screen, info in _build_monitor_screen_pairs():
        if _screen_matches(screen, qt_screen):
            return info

    return monitor_infos[0] if monitor_infos else None


def _resolve_qt_screen_for_monitor(monitor_info):
    app = _get_qt_application()
    if app is None:
        return None

    screens = _normalize_iterable(_get_qt_screens())
    if not screens:
        return None

    if monitor_info and isinstance(monitor_info, dict):
        device_name = str(monitor_info.get("Device", "")).strip().lower()
        if device_name:
            for screen in screens:
                try:
                    if str(screen.name()).strip().lower() == device_name:
                        return screen
                except Exception:
                    continue

        monitor_rect = _get_monitor_rect(monitor_info)
        for screen, info in _build_monitor_screen_pairs():
            if info is monitor_info:
                return screen
            if monitor_rect and _get_monitor_rect(info) == monitor_rect:
                return screen

    primary = app.primaryScreen()
    if primary is not None:
        return primary
    return screens[0] if screens else None


def get_qt_virtual_desktop_rect():
    """返回覆盖全部 Qt 屏幕的虚拟桌面逻辑矩形。"""
    try:
        from PySide6.QtCore import QRect
    except Exception:
        return None

    app = _get_qt_application()
    if app is None:
        return QRect(0, 0, 0, 0)

    screens = _normalize_iterable(_get_qt_screens())
    rects = []
    for screen in screens:
        rect = _get_qt_rect(screen)
        if rect:
            rects.append(rect)

    virtual_bounds = _get_virtual_bounds(rects)
    if virtual_bounds:
        left, top, right, bottom = virtual_bounds
        return QRect(left, top, max(0, right - left), max(0, bottom - top))

    try:
        primary = app.primaryScreen()
        if primary is not None:
            return QRect(primary.virtualGeometry())
    except Exception:
        pass
    return QRect(0, 0, 0, 0)


def resolve_qt_screen(widget=None, global_pos=None):
    """尽量解析与当前交互上下文一致的 Qt 屏幕。"""
    app = _get_qt_application()
    if app is None:
        return None

    try:
        widget_visible = bool(widget is not None and hasattr(widget, "isVisible") and widget.isVisible())
    except Exception:
        widget_visible = False

    if global_pos is not None and not widget_visible:
        try:
            screen = app.screenAt(global_pos)
            if screen is not None:
                return screen
        except Exception:
            pass

    try:
        if widget is not None:
            try:
                native_screen = _resolve_qt_screen_for_widget_native_window(widget)
                if native_screen is not None:
                    return native_screen
            except Exception:
                pass

            try:
                window_handle = widget.windowHandle()
                if window_handle is not None:
                    screen = window_handle.screen()
                    if screen is not None:
                        return screen
            except Exception:
                pass

            try:
                frame_rect = widget.frameGeometry()
                if frame_rect is not None and not frame_rect.isEmpty():
                    screen = app.screenAt(frame_rect.center())
                    if screen is not None:
                        return screen
            except Exception:
                pass

            try:
                geometry = widget.geometry()
                if geometry is not None and not geometry.isEmpty() and hasattr(widget, "mapToGlobal"):
                    screen = app.screenAt(widget.mapToGlobal(geometry.center()))
                    if screen is not None:
                        return screen
            except Exception:
                pass
    except Exception:
        pass

    if global_pos is not None:
        try:
            screen = app.screenAt(global_pos)
            if screen is not None:
                return screen
        except Exception:
            pass

    try:
        active = app.activeWindow()
        if active is not None and active is not widget:
            screen = resolve_qt_screen(active)
            if screen is not None:
                return screen
    except Exception:
        pass

    try:
        from PySide6.QtGui import QCursor, QGuiApplication

        cursor_screen = QGuiApplication.screenAt(QCursor.pos())
        if cursor_screen is not None:
            return cursor_screen
    except Exception:
        pass

    try:
        primary = app.primaryScreen()
        if primary is not None:
            return primary
    except Exception:
        pass

    screens = _normalize_iterable(_get_qt_screens())
    return screens[0] if screens else None


def get_available_geometry_for_widget(widget=None, global_pos=None):
    """获取与当前窗口或坐标最匹配屏幕的可用区域。"""
    try:
        from PySide6.QtCore import QRect
    except Exception:
        return None

    screen = resolve_qt_screen(widget=widget, global_pos=global_pos)
    if screen is None:
        return QRect(0, 0, 0, 0)

    try:
        return QRect(screen.availableGeometry())
    except Exception:
        return QRect(0, 0, 0, 0)


def _resolve_reference_window(widget):
    if widget is None:
        return None

    try:
        window = widget.window() if hasattr(widget, "window") else None
        if window is not None:
            return window
    except Exception:
        pass

    return widget


def _get_widget_global_center(widget):
    if widget is None:
        return None

    try:
        frame_rect = widget.frameGeometry()
        if frame_rect is not None and not frame_rect.isEmpty():
            return frame_rect.center()
    except Exception:
        pass

    try:
        geometry = widget.geometry()
        if geometry is not None and not geometry.isEmpty() and hasattr(widget, "mapToGlobal"):
            return widget.mapToGlobal(geometry.center())
    except Exception:
        pass

    return None


def clamp_preferred_window_size(
    width: int,
    height: int,
    available_geometry,
    padding: int = 48,
) -> Tuple[int, int]:
    """将窗口首选尺寸限制到当前屏幕可用区域内。"""
    safe_width = max(320, int(width))
    safe_height = max(240, int(height))

    try:
        if available_geometry is None or available_geometry.isEmpty():
            return safe_width, safe_height

        max_width = max(320, int(available_geometry.width()) - max(0, int(padding)))
        max_height = max(240, int(available_geometry.height()) - max(0, int(padding)))
        return min(safe_width, max_width), min(safe_height, max_height)
    except Exception:
        return safe_width, safe_height


def center_window_on_widget_screen(window, reference_widget=None, global_pos=None) -> bool:
    """将窗口居中到参考窗口中心点，并限制在对应屏幕可用区域内。"""
    if window is None:
        return False

    ref_widget = reference_widget
    if ref_widget is None:
        try:
            ref_widget = window.parentWidget()
        except Exception:
            ref_widget = None

    ref_window = _resolve_reference_window(ref_widget)
    screen = resolve_qt_screen(widget=ref_window, global_pos=global_pos)
    available_geometry = get_available_geometry_for_widget(widget=ref_window, global_pos=global_pos)
    if available_geometry is None or available_geometry.isEmpty():
        return False

    try:
        width = max(0, int(window.width()))
        height = max(0, int(window.height()))
    except Exception:
        width, height = 0, 0

    if width <= 0 or height <= 0:
        try:
            size_hint = window.sizeHint()
            width = max(width, int(size_hint.width()))
            height = max(height, int(size_hint.height()))
        except Exception:
            pass

    if width <= 0 or height <= 0:
        return False

    reference_center = _get_widget_global_center(ref_window)
    if reference_center is None:
        try:
            reference_center = available_geometry.center()
        except Exception:
            reference_center = None

    if reference_center is None:
        return False

    try:
        window_handle = window.windowHandle() if hasattr(window, "windowHandle") else None
        if window_handle is not None and screen is not None:
            window_handle.setScreen(screen)
    except Exception:
        pass

    target_x = int(reference_center.x()) - (width // 2)
    target_y = int(reference_center.y()) - (height // 2)

    try:
        min_x = int(available_geometry.left())
        max_x = int(available_geometry.right()) - width + 1
        if max_x < min_x:
            max_x = min_x
        target_x = max(min_x, min(target_x, max_x))

        min_y = int(available_geometry.top())
        max_y = int(available_geometry.bottom()) - height + 1
        if max_y < min_y:
            max_y = min_y
        target_y = max(min_y, min(target_y, max_y))
    except Exception:
        pass

    try:
        window.move(int(target_x), int(target_y))
    except Exception:
        return False

    try:
        is_visible = bool(window.isVisible())
    except Exception:
        is_visible = True

    if not is_visible:
        try:
            retry_pending = bool(window.property("_lca_center_retry_pending"))
        except Exception:
            retry_pending = False

        if not retry_pending:
            try:
                from PySide6.QtCore import QTimer

                window.setProperty("_lca_center_retry_pending", True)

                def _retry_center():
                    try:
                        window.setProperty("_lca_center_retry_pending", False)
                    except Exception:
                        pass
                    try:
                        center_window_on_widget_screen(window, reference_widget, global_pos)
                    except Exception:
                        pass

                QTimer.singleShot(0, _retry_center)
            except Exception:
                pass

    return True


def native_point_to_qt_global(native_x: int, native_y: int) -> Tuple[int, int]:
    """Win32 物理坐标 -> Qt 全局逻辑坐标。"""
    x = int(native_x)
    y = int(native_y)

    try:
        monitor_info = _get_monitor_info_from_native_point(x, y)
        qt_screen = _resolve_qt_screen_for_monitor(monitor_info)
        if not monitor_info or qt_screen is None:
            return x, y

        monitor_rect = monitor_info.get("Monitor")
        if not monitor_rect or len(monitor_rect) != 4:
            return x, y

        left, top, right, bottom = [int(v) for v in monitor_rect]
        monitor_width = max(1, right - left)
        monitor_height = max(1, bottom - top)

        qt_geometry = qt_screen.geometry()
        qt_width = max(1, int(qt_geometry.width()))
        qt_height = max(1, int(qt_geometry.height()))

        # 始终按显示器物理尺寸与 Qt 逻辑尺寸的比例换算，避免开发态/打包态走成两条坐标链路。
        scale_x = monitor_width / float(qt_width)
        scale_y = monitor_height / float(qt_height)

        qt_x = int(qt_geometry.x() + round((x - left) / scale_x))
        qt_y = int(qt_geometry.y() + round((y - top) / scale_y))
        return qt_x, qt_y
    except Exception:
        return x, y


def qt_global_to_native_point(qt_x: int, qt_y: int) -> Tuple[int, int]:
    """Qt 全局逻辑坐标 -> Win32 物理坐标。"""
    x = int(qt_x)
    y = int(qt_y)

    app = _get_qt_application()
    if app is None:
        return x, y

    try:
        from PySide6.QtCore import QPoint

        qt_point = QPoint(x, y)
        qt_screen = app.screenAt(qt_point)
        if qt_screen is None:
            qt_screen = app.primaryScreen()
        if qt_screen is None:
            screens = _normalize_iterable(_get_qt_screens())
            qt_screen = screens[0] if screens else None
        if qt_screen is None:
            return x, y

        monitor_info = _get_monitor_info_for_qt_screen(qt_screen)
        if not monitor_info:
            return x, y

        monitor_rect = monitor_info.get("Monitor")
        if not monitor_rect or len(monitor_rect) != 4:
            return x, y

        left, top, right, bottom = [int(v) for v in monitor_rect]
        monitor_width = max(1, right - left)
        monitor_height = max(1, bottom - top)

        qt_geometry = qt_screen.geometry()
        qt_width = max(1, int(qt_geometry.width()))
        qt_height = max(1, int(qt_geometry.height()))

        scale_x = monitor_width / float(qt_width)
        scale_y = monitor_height / float(qt_height)

        native_x = int(left + round((x - qt_geometry.x()) * scale_x))
        native_y = int(top + round((y - qt_geometry.y()) * scale_y))
        return native_x, native_y
    except Exception:
        return x, y


def native_rect_to_qt_global_rect(rect: Tuple[int, int, int, int]):
    """Win32 物理矩形 -> Qt 全局逻辑矩形。"""
    try:
        from PySide6.QtCore import QRect

        if not rect or len(rect) != 4:
            return QRect()

        left, top, right, bottom = [int(v) for v in rect]
        qt_left, qt_top = native_point_to_qt_global(left, top)
        qt_right, qt_bottom = native_point_to_qt_global(right, bottom)

        x = min(qt_left, qt_right)
        y = min(qt_top, qt_bottom)
        width = max(0, abs(qt_right - qt_left))
        height = max(0, abs(qt_bottom - qt_top))
        return QRect(x, y, width, height)
    except Exception:
        return None


def _size_relative_error(
    actual_width: int,
    actual_height: int,
    expected_width: int,
    expected_height: int,
) -> float:
    if actual_width <= 0 or actual_height <= 0 or expected_width <= 0 or expected_height <= 0:
        return float("inf")
    width_error = abs(int(actual_width) - int(expected_width)) / float(max(1, int(expected_width)))
    height_error = abs(int(actual_height) - int(expected_height)) / float(max(1, int(expected_height)))
    return width_error + height_error


def _get_rect_width_height(rect: Any) -> Tuple[int, int]:
    try:
        left, top, right, bottom = [int(v) for v in rect]
        return max(0, right - left), max(0, bottom - top)
    except Exception:
        return 0, 0


def _tuple_xywh_to_qrect(rect: Optional[Tuple[int, int, int, int]]):
    try:
        from PySide6.QtCore import QRect
    except Exception:
        return None

    if not rect or len(rect) != 4:
        return QRect()

    try:
        x, y, width, height = [int(v) for v in rect]
        return QRect(x, y, max(0, width), max(0, height))
    except Exception:
        return QRect()


def _infer_window_screen_coord_space(
    hwnd: int,
    window_rect: Tuple[int, int, int, int],
    scale_factor: float,
) -> str:
    scale = max(1.0, float(scale_factor or 1.0))
    if scale <= 1.01:
        return "qt_logical"

    raw_width, raw_height = _get_rect_width_height(window_rect)
    if raw_width <= 0 or raw_height <= 0:
        return "qt_logical"

    try:
        from utils.hwnd_capture_utils import get_window_rect_with_dwm
    except Exception:
        get_window_rect_with_dwm = None

    if get_window_rect_with_dwm is not None:
        try:
            dwm_rect = get_window_rect_with_dwm(int(hwnd))
        except Exception:
            dwm_rect = None
        if dwm_rect:
            dwm_width, dwm_height = _get_rect_width_height(dwm_rect)
            raw_error = _size_relative_error(raw_width, raw_height, dwm_width, dwm_height)
            scaled_error = _size_relative_error(
                int(round(raw_width * scale)),
                int(round(raw_height * scale)),
                dwm_width,
                dwm_height,
            )
            return "native_physical" if raw_error <= scaled_error else "qt_logical"

    return "qt_logical"


def _infer_client_size_coord_space(
    window_rect: Tuple[int, int, int, int],
    client_width: int,
    client_height: int,
    scale_factor: float,
    screen_coord_space: str,
) -> str:
    raw_width, raw_height = _get_rect_width_height(window_rect)
    if raw_width <= 0 or raw_height <= 0 or client_width <= 0 or client_height <= 0:
        return "qt_logical"

    scale = max(1.0, float(scale_factor or 1.0))
    if scale <= 1.01:
        return "qt_logical"

    if screen_coord_space == "native_physical":
        logical_width = int(round(client_width * scale))
        logical_height = int(round(client_height * scale))
        physical_width = int(client_width)
        physical_height = int(client_height)
    else:
        logical_width = int(client_width)
        logical_height = int(client_height)
        physical_width = max(1, int(round(client_width / scale)))
        physical_height = max(1, int(round(client_height / scale)))

    logical_error = _size_relative_error(raw_width, raw_height, logical_width, logical_height)
    physical_error = _size_relative_error(raw_width, raw_height, physical_width, physical_height)
    return "qt_logical" if logical_error <= physical_error else "native_physical"


def _build_client_rects(
    client_screen_pos: Tuple[int, int],
    client_width: int,
    client_height: int,
    screen_coord_space: str,
    client_size_space: str,
) -> Tuple[Optional[Tuple[int, int, int, int]], Optional[Tuple[int, int, int, int]]]:
    try:
        raw_left = int(client_screen_pos[0])
        raw_top = int(client_screen_pos[1])
        width = int(client_width)
        height = int(client_height)
    except Exception:
        return None, None

    if width <= 0 or height <= 0:
        return None, None

    if screen_coord_space == "native_physical":
        native_left, native_top = raw_left, raw_top
        qt_left, qt_top = native_point_to_qt_global(native_left, native_top)
    else:
        qt_left, qt_top = raw_left, raw_top
        native_left, native_top = qt_global_to_native_point(qt_left, qt_top)

    if client_size_space == "native_physical":
        native_right = native_left + width
        native_bottom = native_top + height
        qt_right, qt_bottom = native_point_to_qt_global(native_right, native_bottom)
    else:
        qt_right = qt_left + width
        qt_bottom = qt_top + height
        native_right, native_bottom = qt_global_to_native_point(qt_right, qt_bottom)

    native_right = max(native_left + 1, int(native_right))
    native_bottom = max(native_top + 1, int(native_bottom))
    qt_right = max(qt_left + 1, int(qt_right))
    qt_bottom = max(qt_top + 1, int(qt_bottom))

    client_native_rect = (
        int(native_left),
        int(native_top),
        int(native_right),
        int(native_bottom),
    )
    client_qt_rect = (
        int(qt_left),
        int(qt_top),
        int(qt_right - qt_left),
        int(qt_bottom - qt_top),
    )
    return client_native_rect, client_qt_rect


def get_window_client_native_rect(
    window_info: Dict[str, Any],
) -> Optional[Tuple[int, int, int, int]]:
    """Extract the client rect in native screen coordinates."""
    if not window_info:
        return None

    client_native_rect = window_info.get("client_native_rect")
    if client_native_rect and len(client_native_rect) == 4:
        try:
            return tuple(int(v) for v in client_native_rect)
        except Exception:
            return None

    try:
        client_screen_pos = window_info.get("client_screen_pos", (0, 0))
        client_width = int(window_info.get("client_width", 0) or 0)
        client_height = int(window_info.get("client_height", 0) or 0)
        if client_width <= 0 or client_height <= 0:
            return None

        left = int(client_screen_pos[0])
        top = int(client_screen_pos[1])
        return (
            left,
            top,
            left + client_width,
            top + client_height,
        )
    except Exception:
        return None


def get_window_client_qt_global_rect(window_info: Dict[str, Any]):
    """Compute the client rect in Qt global logical coordinates."""
    if not window_info:
        return None

    native_rect = get_window_client_native_rect(window_info)
    if native_rect:
        qt_rect = native_rect_to_qt_global_rect(native_rect)
        if qt_rect is not None and not qt_rect.isEmpty():
            return qt_rect

    client_qt_rect = window_info.get("client_qt_rect")
    if client_qt_rect and len(client_qt_rect) == 4:
        return _tuple_xywh_to_qrect(client_qt_rect)

    return None


def get_window_client_logical_size(
    window_info: Optional[Dict[str, Any]],
) -> Tuple[int, int]:
    """Return client size in Qt logical pixels."""
    if not window_info:
        return 1, 1

    qt_rect = get_window_client_qt_global_rect(window_info)
    if qt_rect is not None and not qt_rect.isEmpty():
        return max(1, int(qt_rect.width())), max(1, int(qt_rect.height()))

    try:
        logical_width = int(window_info.get("client_logical_width", 0) or 0)
        logical_height = int(window_info.get("client_logical_height", 0) or 0)
        if logical_width > 0 and logical_height > 0:
            return logical_width, logical_height
    except Exception:
        pass

    try:
        raw_width = int(window_info.get("client_width", 0) or 0)
        raw_height = int(window_info.get("client_height", 0) or 0)
        if raw_width > 0 and raw_height > 0:
            return raw_width, raw_height
    except Exception:
        pass

    return 1, 1


def get_window_client_physical_size(
    window_info: Optional[Dict[str, Any]],
) -> Tuple[int, int]:
    """Return client size in native physical pixels."""
    if not window_info:
        return 1, 1

    try:
        physical_width = int(window_info.get("client_physical_width", 0) or 0)
        physical_height = int(window_info.get("client_physical_height", 0) or 0)
        if physical_width > 0 and physical_height > 0:
            return physical_width, physical_height
    except Exception:
        pass

    native_rect = get_window_client_native_rect(window_info)
    if native_rect:
        try:
            left, top, right, bottom = [int(v) for v in native_rect]
            return max(1, right - left), max(1, bottom - top)
        except Exception:
            pass

    logical_width, logical_height = get_window_client_logical_size(window_info)
    try:
        scale = float(
            window_info.get("window_scale_factor")
            or window_info.get("qt_device_pixel_ratio")
            or 1.0
        )
    except Exception:
        scale = 1.0
    scale = max(1.0, scale)
    return max(1, int(round(logical_width * scale))), max(1, int(round(logical_height * scale)))


def _resolve_client_base_size(
    window_info: Optional[Dict[str, Any]],
    coord_space: str = "physical",
) -> Tuple[int, int]:
    """Resolve the client-space size used by a coordinate conversion."""
    normalized_space = str(coord_space or "physical").strip().lower()
    if normalized_space == "logical":
        return get_window_client_logical_size(window_info)
    return get_window_client_physical_size(window_info)


def _rect_to_xywh(rect: Any) -> Optional[Tuple[int, int, int, int]]:
    if rect is None:
        return None

    try:
        x = int(rect.x())
        y = int(rect.y())
        width = int(rect.width())
        height = int(rect.height())
        return x, y, width, height
    except Exception:
        return None


def overlay_local_point_to_client_relative(
    window_info: Dict[str, Any],
    target_rect: Any,
    overlay_point: Any,
    *,
    coord_space: str = "physical",
) -> Tuple[int, int]:
    """覆盖层本地点 -> 窗口客户区相对逻辑坐标。"""
    client_width, client_height = _resolve_client_base_size(window_info, coord_space=coord_space)

    target_metrics = _rect_to_xywh(target_rect)
    if not target_metrics:
        try:
            return int(overlay_point.x()), int(overlay_point.y())
        except Exception:
            return 0, 0

    try:
        point_x = int(overlay_point.x())
        point_y = int(overlay_point.y())
    except Exception:
        return 0, 0

    target_x, target_y, target_width, target_height = target_metrics
    target_width = max(1, int(target_width))
    target_height = max(1, int(target_height))

    relative_qt_x = max(0, min(point_x - target_x, target_width - 1))
    relative_qt_y = max(0, min(point_y - target_y, target_height - 1))

    scale_x = client_width / float(target_width)
    scale_y = client_height / float(target_height)
    client_x = int(round(relative_qt_x * scale_x))
    client_y = int(round(relative_qt_y * scale_y))
    client_x = max(0, min(client_x, client_width - 1))
    client_y = max(0, min(client_y, client_height - 1))
    return client_x, client_y


def overlay_local_rect_to_client_relative(
    window_info: Dict[str, Any],
    target_rect: Any,
    overlay_rect: Any,
    *,
    coord_space: str = "physical",
) -> Optional[Tuple[int, int, int, int]]:
    """覆盖层本地矩形 -> 窗口客户区相对逻辑矩形。"""
    client_width, client_height = _resolve_client_base_size(window_info, coord_space=coord_space)

    target_metrics = _rect_to_xywh(target_rect)
    overlay_metrics = _rect_to_xywh(overlay_rect)
    if not target_metrics or not overlay_metrics:
        return None

    target_x, target_y, target_width, target_height = target_metrics
    rect_x, rect_y, rect_width, rect_height = overlay_metrics
    if target_width <= 0 or target_height <= 0 or rect_width <= 0 or rect_height <= 0:
        return None

    clip_left = max(rect_x, target_x)
    clip_top = max(rect_y, target_y)
    clip_right = min(rect_x + rect_width, target_x + target_width)
    clip_bottom = min(rect_y + rect_height, target_y + target_height)
    if clip_right <= clip_left or clip_bottom <= clip_top:
        return None

    scale_x = client_width / float(target_width)
    scale_y = client_height / float(target_height)

    rel_left_qt = clip_left - target_x
    rel_top_qt = clip_top - target_y
    rel_right_qt = clip_right - target_x
    rel_bottom_qt = clip_bottom - target_y

    left = int(round(rel_left_qt * scale_x))
    top = int(round(rel_top_qt * scale_y))
    right = int(round(rel_right_qt * scale_x))
    bottom = int(round(rel_bottom_qt * scale_y))

    client_x = max(0, min(left, client_width - 1))
    client_y = max(0, min(top, client_height - 1))
    right = max(client_x + 1, min(right, client_width))
    bottom = max(client_y + 1, min(bottom, client_height))
    return client_x, client_y, right - client_x, bottom - client_y


def client_relative_to_qt_global(
    window_info: Dict[str, Any],
    client_x: int,
    client_y: int,
    *,
    coord_space: str = "physical",
) -> Tuple[int, int]:
    """Map client-relative coordinates to Qt global logical coordinates."""
    qt_rect = get_window_client_qt_global_rect(window_info)
    if qt_rect is None or qt_rect.isEmpty() or not window_info:
        return int(client_x), int(client_y)

    try:
        base_width, base_height = _resolve_client_base_size(window_info, coord_space=coord_space)
        scale_x = qt_rect.width() / float(max(1, base_width))
        scale_y = qt_rect.height() / float(max(1, base_height))
        qt_x = int(qt_rect.x() + round(int(client_x) * scale_x))
        qt_y = int(qt_rect.y() + round(int(client_y) * scale_y))
        return qt_x, qt_y
    except Exception:
        return int(client_x), int(client_y)
def normalize_window_hwnd(
    hwnd: int,
    *,
    title_hint: str = "",
    min_width: int = 200,
    min_height: int = 200,
) -> Tuple[int, str]:
    """
    规范化窗口句柄：
    1) 校验句柄有效性
    2) 小窗口优先提升到父窗口
    3) 仍不满足尺寸时，按标题选择最大可见窗口

    返回: (规范化后的句柄, 标题)
    """
    try:
        import win32gui
    except Exception:
        return int(hwnd or 0), str(title_hint or "")

    try:
        target_hwnd = int(hwnd or 0)
    except Exception:
        return 0, str(title_hint or "")

    if target_hwnd == 0 or not win32gui.IsWindow(target_hwnd):
        return 0, str(title_hint or "")

    try:
        target_title = str(win32gui.GetWindowText(target_hwnd) or "").strip()
    except Exception:
        target_title = ""
    resolved_title = target_title or str(title_hint or "").strip()

    def _window_size(candidate_hwnd: int) -> Tuple[int, int]:
        try:
            left, top, right, bottom = win32gui.GetWindowRect(int(candidate_hwnd))
            return max(0, int(right - left)), max(0, int(bottom - top))
        except Exception:
            return 0, 0

    width, height = _window_size(target_hwnd)
    if width >= min_width and height >= min_height:
        return target_hwnd, resolved_title

    try:
        parent_hwnd = int(win32gui.GetParent(target_hwnd) or 0)
    except Exception:
        parent_hwnd = 0

    if parent_hwnd and win32gui.IsWindow(parent_hwnd):
        parent_width, parent_height = _window_size(parent_hwnd)
        if parent_width >= min_width and parent_height >= min_height:
            try:
                parent_title = str(win32gui.GetWindowText(parent_hwnd) or "").strip()
            except Exception:
                parent_title = ""
            return parent_hwnd, parent_title or resolved_title

    search_title = (resolved_title or str(title_hint or "").strip()).lower()
    if not search_title:
        return target_hwnd, resolved_title

    best_hwnd = 0
    best_area = -1
    best_title = ""

    def _enum_callback(enum_hwnd, _):
        nonlocal best_hwnd, best_area, best_title
        try:
            if not win32gui.IsWindowVisible(enum_hwnd):
                return True

            enum_title = str(win32gui.GetWindowText(enum_hwnd) or "").strip()
            if not enum_title or search_title not in enum_title.lower():
                return True

            enum_width, enum_height = _window_size(enum_hwnd)
            if enum_width < min_width or enum_height < min_height:
                return True

            enum_area = enum_width * enum_height
            if enum_area > best_area:
                best_hwnd = int(enum_hwnd)
                best_area = enum_area
                best_title = enum_title
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(_enum_callback, None)
    except Exception:
        return target_hwnd, resolved_title

    if best_hwnd and best_hwnd != target_hwnd:
        return best_hwnd, best_title or resolved_title
    return target_hwnd, resolved_title


def _get_hwnd_client_metrics(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    try:
        import win32gui
    except Exception:
        return None

    try:
        hwnd_int = int(hwnd or 0)
    except Exception:
        return None

    if hwnd_int <= 0 or not win32gui.IsWindow(hwnd_int):
        return None

    try:
        client_rect = win32gui.GetClientRect(hwnd_int)
        client_origin = win32gui.ClientToScreen(hwnd_int, (0, 0))
    except Exception:
        return None

    width = max(0, int(client_rect[2] - client_rect[0]))
    height = max(0, int(client_rect[3] - client_rect[1]))
    return int(client_origin[0]), int(client_origin[1]), width, height


def _client_metrics_match(
    lhs: Optional[Tuple[int, int, int, int]],
    rhs: Optional[Tuple[int, int, int, int]],
    *,
    tolerance: int = 2,
) -> bool:
    if lhs is None or rhs is None:
        return False

    try:
        tolerance_int = max(0, int(tolerance))
    except Exception:
        tolerance_int = 0

    return all(
        abs(int(lhs[index]) - int(rhs[index])) <= tolerance_int
        for index in range(4)
    )


def _promote_region_binding_parent_hwnd(
    hwnd: int,
    *,
    tolerance: int = 2,
) -> int:
    try:
        import win32gui
    except Exception:
        return int(hwnd or 0)

    try:
        current_hwnd = int(hwnd or 0)
    except Exception:
        return 0

    if current_hwnd <= 0 or not win32gui.IsWindow(current_hwnd):
        return 0

    current_metrics = _get_hwnd_client_metrics(current_hwnd)
    if current_metrics is None:
        return current_hwnd

    visited = set()
    while current_hwnd not in visited:
        visited.add(current_hwnd)
        try:
            parent_hwnd = int(win32gui.GetParent(current_hwnd) or 0)
        except Exception:
            break

        if parent_hwnd <= 0 or not win32gui.IsWindow(parent_hwnd):
            break

        parent_metrics = _get_hwnd_client_metrics(parent_hwnd)
        if not _client_metrics_match(current_metrics, parent_metrics, tolerance=tolerance):
            break

        current_hwnd = parent_hwnd
        current_metrics = parent_metrics

    return current_hwnd


def _hwnd_matches_region_binding_metadata(
    hwnd: int,
    *,
    title_hint: str = "",
    class_hint: str = "",
    client_width: int = 0,
    client_height: int = 0,
    client_size_tolerance: int = 2,
) -> bool:
    try:
        import win32gui
    except Exception:
        return False

    try:
        hwnd_int = int(hwnd or 0)
    except Exception:
        return False

    if hwnd_int <= 0 or not win32gui.IsWindow(hwnd_int):
        return False

    title_text = str(title_hint or "").strip()
    class_text = str(class_hint or "").strip()

    try:
        width_hint = max(0, int(client_width or 0))
    except Exception:
        width_hint = 0
    try:
        height_hint = max(0, int(client_height or 0))
    except Exception:
        height_hint = 0

    if not any((title_text, class_text, width_hint > 0, height_hint > 0)):
        return False

    if title_text:
        try:
            current_title = str(win32gui.GetWindowText(hwnd_int) or "").strip()
        except Exception:
            return False
        if current_title != title_text:
            return False

    if class_text:
        try:
            current_class = str(win32gui.GetClassName(hwnd_int) or "").strip()
        except Exception:
            return False
        if current_class != class_text:
            return False

    metrics = _get_hwnd_client_metrics(hwnd_int)
    if metrics is None:
        return False

    try:
        tolerance_int = max(0, int(client_size_tolerance))
    except Exception:
        tolerance_int = 0

    if width_hint > 0 and abs(int(metrics[2]) - width_hint) > tolerance_int:
        return False
    if height_hint > 0 and abs(int(metrics[3]) - height_hint) > tolerance_int:
        return False

    return True


def normalize_region_binding_hwnd(
    hwnd: int,
    *,
    title_hint: str = "",
    class_hint: str = "",
    client_width: int = 0,
    client_height: int = 0,
    client_size_tolerance: int = 2,
) -> Tuple[int, str, str, int, int]:
    title_text = str(title_hint or "").strip()
    class_text = str(class_hint or "").strip()

    try:
        width_hint = max(0, int(client_width or 0))
    except Exception:
        width_hint = 0
    try:
        height_hint = max(0, int(client_height or 0))
    except Exception:
        height_hint = 0

    try:
        import win32gui
    except Exception:
        return int(hwnd or 0), title_text, class_text, width_hint, height_hint

    try:
        hwnd_int = int(hwnd or 0)
    except Exception:
        hwnd_int = 0

    if hwnd_int <= 0 or not win32gui.IsWindow(hwnd_int):
        return 0, title_text, class_text, width_hint, height_hint

    normalized_hwnd = _promote_region_binding_parent_hwnd(
        hwnd_int,
        tolerance=client_size_tolerance,
    )
    if normalized_hwnd <= 0 or not win32gui.IsWindow(normalized_hwnd):
        normalized_hwnd = hwnd_int

    try:
        normalized_title = str(win32gui.GetWindowText(normalized_hwnd) or "").strip()
    except Exception:
        normalized_title = ""
    try:
        normalized_class = str(win32gui.GetClassName(normalized_hwnd) or "").strip()
    except Exception:
        normalized_class = ""

    metrics = _get_hwnd_client_metrics(normalized_hwnd)
    normalized_width = width_hint
    normalized_height = height_hint
    if metrics is not None:
        normalized_width = max(0, int(metrics[2]))
        normalized_height = max(0, int(metrics[3]))

    return (
        normalized_hwnd,
        normalized_title or title_text,
        normalized_class or class_text,
        normalized_width,
        normalized_height,
    )


def find_region_binding_equivalent_descendant(
    root_hwnd: int,
    *,
    title_hint: str = "",
    class_hint: str = "",
    client_width: int = 0,
    client_height: int = 0,
    client_size_tolerance: int = 2,
) -> int:
    title_text = str(title_hint or "").strip()
    class_text = str(class_hint or "").strip()

    try:
        width_hint = max(0, int(client_width or 0))
    except Exception:
        width_hint = 0
    try:
        height_hint = max(0, int(client_height or 0))
    except Exception:
        height_hint = 0

    if not any((title_text, class_text, width_hint > 0, height_hint > 0)):
        return 0

    try:
        import win32gui
    except Exception:
        return 0

    try:
        root_hwnd_int = int(root_hwnd or 0)
    except Exception:
        return 0

    if root_hwnd_int <= 0 or not win32gui.IsWindow(root_hwnd_int):
        return 0

    normalized_root_hwnd, _, _, _, _ = normalize_region_binding_hwnd(
        root_hwnd_int,
        client_size_tolerance=client_size_tolerance,
    )
    if normalized_root_hwnd <= 0:
        normalized_root_hwnd = root_hwnd_int

    matched_hwnd = 0

    def _enum_child(candidate_hwnd, _):
        nonlocal matched_hwnd
        if matched_hwnd:
            return False

        try:
            candidate_int = int(candidate_hwnd or 0)
        except Exception:
            return True

        if candidate_int <= 0:
            return True

        if not _hwnd_matches_region_binding_metadata(
            candidate_int,
            title_hint=title_text,
            class_hint=class_text,
            client_width=width_hint,
            client_height=height_hint,
            client_size_tolerance=client_size_tolerance,
        ):
            return True

        normalized_candidate_hwnd, _, _, _, _ = normalize_region_binding_hwnd(
            candidate_int,
            client_size_tolerance=client_size_tolerance,
        )
        if normalized_candidate_hwnd == normalized_root_hwnd:
            matched_hwnd = candidate_int
            return False

        return True

    try:
        win32gui.EnumChildWindows(normalized_root_hwnd, _enum_child, None)
    except Exception:
        return 0

    return matched_hwnd


def get_window_dpi(hwnd: int) -> int:
    """获取窗口 DPI，失败返回 96。"""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        if hasattr(user32, "GetDpiForWindow"):
            return _safe_positive_int(user32.GetDpiForWindow(int(hwnd)), 96)
    except Exception:
        pass
    return 96


def get_system_dpi() -> int:
    """获取系统 DPI，失败返回 96。"""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

        user32.GetDC.argtypes = [ctypes.c_void_p]
        user32.GetDC.restype = ctypes.c_void_p
        user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.ReleaseDC.restype = ctypes.c_int
        gdi32.GetDeviceCaps.argtypes = [ctypes.c_void_p, ctypes.c_int]
        gdi32.GetDeviceCaps.restype = ctypes.c_int

        hdc = user32.GetDC(0)
        if not hdc:
            return 96

        try:
            return _safe_positive_int(gdi32.GetDeviceCaps(hdc, 88), 96)  # LOGPIXELSX
        finally:
            user32.ReleaseDC(0, hdc)
    except Exception:
        return 96


def build_window_info(
    hwnd: int,
    *,
    use_window_rect_as_client: bool = False,
    include_system_metrics: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Build a normalized window-info structure.

    Fields:
    hwnd/window_rect/client_rect/client_screen_pos/client_width/client_height/window_dpi/qt_device_pixel_ratio
    client_native_rect/client_qt_rect/client_physical_width/client_physical_height/client_logical_width/client_logical_height

    When include_system_metrics=True, also include:
    system_dpi/window_scale_factor/system_scale_factor/qt_dpi
    """
    try:
        import win32gui
    except Exception:
        return None

    try:
        hwnd_int = int(hwnd)
        if hwnd_int == 0 or not win32gui.IsWindow(hwnd_int):
            return None

        window_rect = win32gui.GetWindowRect(hwnd_int)
        client_rect = win32gui.GetClientRect(hwnd_int)
        client_screen_pos = win32gui.ClientToScreen(hwnd_int, (0, 0))

        if use_window_rect_as_client:
            client_screen_pos = (int(window_rect[0]), int(window_rect[1]))
            client_width = int(window_rect[2] - window_rect[0])
            client_height = int(window_rect[3] - window_rect[1])
        else:
            client_width = int(client_rect[2] - client_rect[0])
            client_height = int(client_rect[3] - client_rect[1])

        window_dpi = get_window_dpi(hwnd_int)
        qt_device_pixel_ratio = max(1.0, float(window_dpi) / 96.0)
        process_dpi_awareness = get_process_dpi_awareness()
        if process_dpi_awareness is not None and process_dpi_awareness >= 1:
            screen_coord_space = "native_physical"
            client_size_space = "native_physical"
        else:
            screen_coord_space = _infer_window_screen_coord_space(
                hwnd_int,
                window_rect,
                qt_device_pixel_ratio,
            )
            client_size_space = _infer_client_size_coord_space(
                window_rect,
                client_width,
                client_height,
                qt_device_pixel_ratio,
                screen_coord_space,
            )
        client_native_rect, client_qt_rect = _build_client_rects(
            (int(client_screen_pos[0]), int(client_screen_pos[1])),
            client_width,
            client_height,
            screen_coord_space,
            client_size_space,
        )

        client_screen_rect = (
            int(client_screen_pos[0]),
            int(client_screen_pos[1]),
            int(client_screen_pos[0]) + int(client_width),
            int(client_screen_pos[1]) + int(client_height),
        )
        client_native_width = 0
        client_native_height = 0
        if client_native_rect:
            client_native_width = max(0, int(client_native_rect[2]) - int(client_native_rect[0]))
            client_native_height = max(0, int(client_native_rect[3]) - int(client_native_rect[1]))

        client_logical_width = 0
        client_logical_height = 0
        client_native_screen_pos = (0, 0)
        client_qt_screen_pos = (0, 0)
        if client_qt_rect and len(client_qt_rect) == 4:
            client_logical_width = max(0, int(client_qt_rect[2]))
            client_logical_height = max(0, int(client_qt_rect[3]))
            client_qt_screen_pos = (int(client_qt_rect[0]), int(client_qt_rect[1]))
        if client_native_rect and len(client_native_rect) == 4:
            client_native_screen_pos = (int(client_native_rect[0]), int(client_native_rect[1]))

        info: Dict[str, Any] = {
            "hwnd": hwnd_int,
            "window_rect": window_rect,
            "client_rect": client_rect,
            "client_screen_pos": (int(client_screen_pos[0]), int(client_screen_pos[1])),
            "client_screen_rect": client_screen_rect,
            "client_width": client_width,
            "client_height": client_height,
            "window_dpi": window_dpi,
            "qt_device_pixel_ratio": qt_device_pixel_ratio,
            "process_dpi_awareness": process_dpi_awareness,
            "screen_coord_space": screen_coord_space,
            "client_size_space": client_size_space,
            "client_native_rect": client_native_rect,
            "client_qt_rect": client_qt_rect,
            "client_native_screen_pos": client_native_screen_pos,
            "client_qt_screen_pos": client_qt_screen_pos,
            "client_physical_width": client_native_width,
            "client_physical_height": client_native_height,
            "client_logical_width": client_logical_width,
            "client_logical_height": client_logical_height,
        }

        if include_system_metrics:
            system_dpi = get_system_dpi()
            info["system_dpi"] = system_dpi
            info["window_scale_factor"] = float(window_dpi) / 96.0
            info["system_scale_factor"] = float(system_dpi) / 96.0
            info["qt_dpi"] = 96.0 * qt_device_pixel_ratio

        return info
    except Exception:
        return None
