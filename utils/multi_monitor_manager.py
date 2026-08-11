#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多显示器管理模块

功能:
- 枚举所有显示器信息
- 获取虚拟屏幕边界（支持负坐标）
- 坐标转换（屏幕坐标 <-> 显示器相对坐标）
- DPI感知处理
- 显示器变化监听

参考实现:
- Windows EnumDisplayMonitors API
- python-mss 多显示器处理
- pyautogui 多显示器修复方案
"""

import logging
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import List, Optional, Tuple
import threading
import time

from .dpi_awareness import enable_process_dpi_awareness

logger = logging.getLogger(__name__)

# Windows API 常量
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
SM_CMONITORS = 80  # 显示器数量

MONITOR_DEFAULTTONEAREST = 2
MONITOR_DEFAULTTONULL = 0
MONITOR_DEFAULTTOPRIMARY = 1


@dataclass
class MonitorInfo:
    """显示器信息"""
    handle: int                    # 显示器句柄
    device_name: str               # 设备名称 (如 \\.\DISPLAY1)
    left: int                      # 左边界 (可能为负数)
    top: int                       # 上边界 (可能为负数)
    right: int                     # 右边界
    bottom: int                    # 下边界
    work_left: int                 # 工作区左边界
    work_top: int                  # 工作区上边界
    work_right: int                # 工作区右边界
    work_bottom: int               # 工作区下边界
    is_primary: bool               # 是否为主显示器
    dpi_x: int = 96                # 水平DPI
    dpi_y: int = 96                # 垂直DPI
    scale_factor: float = 1.0      # 缩放比例

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def work_width(self) -> int:
        return self.work_right - self.work_left

    @property
    def work_height(self) -> int:
        return self.work_bottom - self.work_top

    @property
    def center(self) -> Tuple[int, int]:
        """显示器中心点"""
        return (self.left + self.width // 2, self.top + self.height // 2)

    def contains_point(self, x: int, y: int) -> bool:
        """检查点是否在此显示器内"""
        return self.left <= x < self.right and self.top <= y < self.bottom

    def to_local_coords(self, screen_x: int, screen_y: int) -> Tuple[int, int]:
        """屏幕坐标转换为显示器本地坐标"""
        return (screen_x - self.left, screen_y - self.top)

    def to_screen_coords(self, local_x: int, local_y: int) -> Tuple[int, int]:
        """显示器本地坐标转换为屏幕坐标"""
        return (local_x + self.left, local_y + self.top)


class MultiMonitorManager:
    """多显示器管理器（单例模式）"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._monitors: List[MonitorInfo] = []
        self._virtual_screen = (0, 0, 0, 0)  # (left, top, width, height)
        self._primary_monitor: Optional[MonitorInfo] = None
        self._cache_lock = threading.Lock()
        self._last_refresh_time = 0
        self._cache_ttl_ms = 5000  # 缓存5秒

        # Windows API
        self._user32 = ctypes.windll.user32
        self._shcore = None
        try:
            self._shcore = ctypes.windll.shcore
        except OSError:
            logger.debug("shcore.dll 不可用，DPI感知功能受限")

        # 设置DPI感知
        self._set_dpi_awareness()

        # 初始化刷新
        self.refresh()

        self._initialized = True
        logger.info(f"[MultiMonitorManager] 初始化完成，检测到 {len(self._monitors)} 个显示器")

    def _set_dpi_awareness(self):
        """确保进程 DPI 感知已通过统一入口完成设置。"""
        try:
            awareness = enable_process_dpi_awareness()
            logger.debug(f"统一 DPI 感知入口完成，当前 awareness={awareness}")
        except Exception as e:
            logger.debug(f"DPI感知设置跳过: {e}")

    def refresh(self) -> None:
        """刷新显示器信息"""
        with self._cache_lock:
            self._monitors.clear()
            self._primary_monitor = None

            # 获取虚拟屏幕边界
            v_left = self._user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            v_top = self._user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            v_width = self._user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            v_height = self._user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
            self._virtual_screen = (v_left, v_top, v_width, v_height)

            # 枚举所有显示器
            monitors_data = []

            # 定义 MONITORINFOEXW 结构
            class MONITORINFOEXW(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD),
                    ("szDevice", wintypes.WCHAR * 32),
                ]

            # 回调函数
            MONITORENUMPROC = ctypes.WINFUNCTYPE(
                wintypes.BOOL,
                wintypes.HMONITOR,
                wintypes.HDC,
                ctypes.POINTER(wintypes.RECT),
                wintypes.LPARAM
            )

            def enum_callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
                monitors_data.append(hMonitor)
                return True

            callback = MONITORENUMPROC(enum_callback)
            # 显式绑定当前调用的回调类型，避免其它模块设置了不同的 WINFUNCTYPE 后产生
            # “argument 3: expected WinFunctionType instance ...” 的类型不匹配异常。
            self._user32.EnumDisplayMonitors.argtypes = [
                wintypes.HDC,
                ctypes.POINTER(wintypes.RECT),
                MONITORENUMPROC,
                wintypes.LPARAM,
            ]
            self._user32.EnumDisplayMonitors.restype = wintypes.BOOL
            self._user32.EnumDisplayMonitors(None, None, callback, 0)
            # 同样显式绑定 GetMonitorInfoW 的结构体指针类型，避免被其它模块设置成不同结构体类型后
            # 出现 “argument 2: expected LP_xxx instance” 的参数类型冲突。
            self._user32.GetMonitorInfoW.argtypes = [
                wintypes.HMONITOR,
                ctypes.POINTER(MONITORINFOEXW),
            ]
            self._user32.GetMonitorInfoW.restype = wintypes.BOOL

            # 获取每个显示器的详细信息
            for hMonitor in monitors_data:
                info = MONITORINFOEXW()
                info.cbSize = ctypes.sizeof(MONITORINFOEXW)

                if self._user32.GetMonitorInfoW(hMonitor, ctypes.pointer(info)):
                    is_primary = bool(info.dwFlags & 1)  # MONITORINFOF_PRIMARY = 1

                    # 获取DPI（需要正确设置函数签名）
                    dpi_x, dpi_y = 96, 96
                    scale_factor = 1.0
                    dpi_source = "default"

                    # 方法1：优先使用GetDpiForMonitor（Per-Monitor DPI Aware模式下最准确）
                    if self._shcore:
                        try:
                            # 设置正确的函数签名
                            self._shcore.GetDpiForMonitor.argtypes = [
                                wintypes.HMONITOR, ctypes.c_int,
                                ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)
                            ]
                            self._shcore.GetDpiForMonitor.restype = ctypes.c_long

                            dpi_x_val = ctypes.c_uint()
                            dpi_y_val = ctypes.c_uint()
                            # MDT_EFFECTIVE_DPI = 0
                            hr = self._shcore.GetDpiForMonitor(
                                hMonitor, 0,
                                ctypes.byref(dpi_x_val),
                                ctypes.byref(dpi_y_val)
                            )
                            if hr == 0:  # S_OK
                                dpi_x = dpi_x_val.value
                                dpi_y = dpi_y_val.value
                                if dpi_x > 0 and dpi_y > 0:
                                    scale_factor = dpi_x / 96.0
                                    dpi_source = "GetDpiForMonitor"
                        except Exception as e:
                            logger.debug(f"GetDpiForMonitor失败: {e}")

                    # 方法2：如果GetDpiForMonitor未能获取到有效DPI，尝试通过分辨率推算
                    # 这种情况可能发生在：进程未设置DPI感知 或 GetDpiForMonitor失败
                    if dpi_x == 96 and scale_factor == 1.0:
                        try:
                            # 使用 EnumDisplaySettings 获取物理分辨率
                            class DEVMODE(ctypes.Structure):
                                _fields_ = [
                                    ("dmDeviceName", wintypes.WCHAR * 32),
                                    ("dmSpecVersion", wintypes.WORD),
                                    ("dmDriverVersion", wintypes.WORD),
                                    ("dmSize", wintypes.WORD),
                                    ("dmDriverExtra", wintypes.WORD),
                                    ("dmFields", wintypes.DWORD),
                                    ("dmPositionX", wintypes.LONG),
                                    ("dmPositionY", wintypes.LONG),
                                    ("dmDisplayOrientation", wintypes.DWORD),
                                    ("dmDisplayFixedOutput", wintypes.DWORD),
                                    ("dmColor", wintypes.SHORT),
                                    ("dmDuplex", wintypes.SHORT),
                                    ("dmYResolution", wintypes.SHORT),
                                    ("dmTTOption", wintypes.SHORT),
                                    ("dmCollate", wintypes.SHORT),
                                    ("dmFormName", wintypes.WCHAR * 32),
                                    ("dmLogPixels", wintypes.WORD),
                                    ("dmBitsPerPel", wintypes.DWORD),
                                    ("dmPelsWidth", wintypes.DWORD),
                                    ("dmPelsHeight", wintypes.DWORD),
                                    ("dmDisplayFlags", wintypes.DWORD),
                                    ("dmDisplayFrequency", wintypes.DWORD),
                                ]

                            devmode = DEVMODE()
                            devmode.dmSize = ctypes.sizeof(DEVMODE)
                            # ENUM_CURRENT_SETTINGS = -1
                            if self._user32.EnumDisplaySettingsW(
                                info.szDevice, -1, ctypes.byref(devmode)
                            ):
                                physical_width = devmode.dmPelsWidth
                                physical_height = devmode.dmPelsHeight
                                logical_width = info.rcMonitor.right - info.rcMonitor.left
                                logical_height = info.rcMonitor.bottom - info.rcMonitor.top

                                if logical_width > 0 and logical_height > 0:
                                    scale_x = physical_width / logical_width
                                    scale_y = physical_height / logical_height
                                    # 只有当缩放比例明显不为1时才使用
                                    if abs(scale_x - 1.0) > 0.01 or abs(scale_y - 1.0) > 0.01:
                                        scale_factor = (scale_x + scale_y) / 2
                                        dpi_x = int(96 * scale_factor)
                                        dpi_y = dpi_x
                                        dpi_source = "EnumDisplaySettings"
                        except Exception as e:
                            logger.debug(f"EnumDisplaySettings推算DPI失败: {e}")

                    monitor_info = MonitorInfo(
                        handle=hMonitor,
                        device_name=info.szDevice,
                        left=info.rcMonitor.left,
                        top=info.rcMonitor.top,
                        right=info.rcMonitor.right,
                        bottom=info.rcMonitor.bottom,
                        work_left=info.rcWork.left,
                        work_top=info.rcWork.top,
                        work_right=info.rcWork.right,
                        work_bottom=info.rcWork.bottom,
                        is_primary=is_primary,
                        dpi_x=dpi_x,
                        dpi_y=dpi_y,
                        scale_factor=scale_factor
                    )

                    self._monitors.append(monitor_info)
                    if is_primary:
                        self._primary_monitor = monitor_info

            # 按位置排序（左到右，上到下）
            self._monitors.sort(key=lambda m: (m.top, m.left))

            self._last_refresh_time = int(time.time() * 1000)

            logger.info(f"显示器刷新完成: {len(self._monitors)} 个显示器")
            for i, m in enumerate(self._monitors):
                logger.info(
                    f"  [{i}] {m.device_name}: "
                    f"位置=({m.left},{m.top})-({m.right},{m.bottom}) "
                    f"尺寸={m.width}x{m.height} "
                    f"DPI={m.dpi_x} (缩放={m.scale_factor:.1%}) "
                    f"{'[主显示器]' if m.is_primary else ''}"
                )

    def _ensure_fresh(self, force: bool = False) -> None:
        """按需刷新显示器缓存，避免显示器拓扑变化后使用旧数据。"""
        try:
            if force:
                self.refresh()
                return

            now_ms = int(time.time() * 1000)
            with self._cache_lock:
                last_refresh = int(self._last_refresh_time)
                ttl_ms = int(self._cache_ttl_ms)

            if last_refresh <= 0 or now_ms - last_refresh >= ttl_ms:
                self.refresh()
        except Exception as e:
            logger.debug(f"显示器缓存刷新检查失败: {e}")

    def get_monitors(self) -> List[MonitorInfo]:
        """获取所有显示器信息"""
        self._ensure_fresh()
        return self._monitors.copy()

    def get_primary_monitor(self) -> Optional[MonitorInfo]:
        """获取主显示器"""
        self._ensure_fresh()
        return self._primary_monitor

    def get_monitor_count(self) -> int:
        """获取显示器数量"""
        self._ensure_fresh()
        return len(self._monitors)

    def get_virtual_screen_bounds(self) -> Tuple[int, int, int, int]:
        """
        获取虚拟屏幕边界

        Returns:
            (left, top, width, height) - left/top 可能为负数
        """
        self._ensure_fresh()
        return self._virtual_screen

    def get_virtual_screen_rect(self) -> Tuple[int, int, int, int]:
        """
        获取虚拟屏幕矩形

        Returns:
            (left, top, right, bottom)
        """
        self._ensure_fresh()
        left, top, width, height = self._virtual_screen
        return (left, top, left + width, top + height)

    def get_min_coords(self) -> Tuple[int, int]:
        """
        获取所有显示器的最小坐标（用于修复负坐标问题）

        Returns:
            (min_x, min_y) - 通常为负数或0
        """
        self._ensure_fresh()
        if not self._monitors:
            return (0, 0)

        min_x = min(m.left for m in self._monitors)
        min_y = min(m.top for m in self._monitors)
        return (min_x, min_y)

    def get_monitor_at_point(self, x: int, y: int) -> Optional[MonitorInfo]:
        """
        获取包含指定点的显示器

        Args:
            x: 屏幕X坐标（虚拟屏幕坐标系）
            y: 屏幕Y坐标

        Returns:
            MonitorInfo 或 None
        """
        self._ensure_fresh()
        for monitor in self._monitors:
            if monitor.contains_point(x, y):
                return monitor
        return None

    def get_monitor_for_window(self, hwnd: int) -> Optional[MonitorInfo]:
        """
        获取窗口所在的显示器

        Args:
            hwnd: 窗口句柄

        Returns:
            MonitorInfo 或 None
        """
        try:
            self._ensure_fresh()
            hMonitor = self._user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
            if hMonitor:
                for monitor in self._monitors:
                    if monitor.handle == hMonitor:
                        return monitor
        except Exception as e:
            logger.error(f"获取窗口显示器失败: {e}")

        return None

    def get_monitor_for_rect(self, left: int, top: int, right: int, bottom: int) -> Optional[MonitorInfo]:
        """
        获取与矩形交集最大的显示器

        Args:
            left, top, right, bottom: 矩形边界

        Returns:
            MonitorInfo 或 None
        """
        try:
            self._ensure_fresh()
            rect = wintypes.RECT(left, top, right, bottom)
            hMonitor = self._user32.MonitorFromRect(ctypes.byref(rect), MONITOR_DEFAULTTONEAREST)
            if hMonitor:
                for monitor in self._monitors:
                    if monitor.handle == hMonitor:
                        return monitor
        except Exception as e:
            logger.error(f"获取矩形显示器失败: {e}")

        return None

    def clamp_to_virtual_screen(self, x: int, y: int) -> Tuple[int, int]:
        """
        将坐标限制在虚拟屏幕范围内

        Args:
            x, y: 原始坐标

        Returns:
            (clamped_x, clamped_y)
        """
        self._ensure_fresh()
        left, top, width, height = self._virtual_screen
        right = left + width - 1
        bottom = top + height - 1

        clamped_x = max(left, min(x, right))
        clamped_y = max(top, min(y, bottom))
        return (clamped_x, clamped_y)

    def screen_to_monitor_coords(self, screen_x: int, screen_y: int) -> Tuple[Optional[MonitorInfo], int, int]:
        """
        屏幕坐标转换为显示器本地坐标

        Args:
            screen_x, screen_y: 屏幕坐标

        Returns:
            (MonitorInfo, local_x, local_y) 或 (None, screen_x, screen_y)
        """
        monitor = self.get_monitor_at_point(screen_x, screen_y)
        if monitor:
            local_x, local_y = monitor.to_local_coords(screen_x, screen_y)
            return (monitor, local_x, local_y)
        return (None, screen_x, screen_y)

    def monitor_to_screen_coords(self, monitor_index: int, local_x: int, local_y: int) -> Tuple[int, int]:
        """
        显示器本地坐标转换为屏幕坐标

        Args:
            monitor_index: 显示器索引
            local_x, local_y: 本地坐标

        Returns:
            (screen_x, screen_y)
        """
        self._ensure_fresh()
        if 0 <= monitor_index < len(self._monitors):
            monitor = self._monitors[monitor_index]
            return monitor.to_screen_coords(local_x, local_y)
        return (local_x, local_y)

    def fix_pyautogui_coords(self, box_left: int, box_top: int) -> Tuple[int, int]:
        """
        修复 pyautogui locateOnScreen 返回的坐标（多显示器偏移）

        Args:
            box_left, box_top: pyautogui 返回的原始坐标

        Returns:
            (fixed_left, fixed_top) - 修正后的坐标
        """
        min_x, min_y = self.get_min_coords()
        return (box_left + min_x, box_top + min_y)

    def get_mss_monitors_config(self) -> List[dict]:
        """
        获取适用于 mss 库的显示器配置

        Returns:
            [{"left": x, "top": y, "width": w, "height": h}, ...]
        """
        self._ensure_fresh()
        configs = []
        for monitor in self._monitors:
            configs.append({
                "left": monitor.left,
                "top": monitor.top,
                "width": monitor.width,
                "height": monitor.height
            })
        return configs

    def get_all_screens_config(self) -> dict:
        """
        获取全屏幕（所有显示器）的配置

        Returns:
            {"left": x, "top": y, "width": w, "height": h}
        """
        self._ensure_fresh()
        left, top, width, height = self._virtual_screen
        return {
            "left": left,
            "top": top,
            "width": width,
            "height": height
        }

    def is_multi_monitor(self) -> bool:
        """是否为多显示器配置"""
        self._ensure_fresh()
        return len(self._monitors) > 1

    def has_negative_coords(self) -> bool:
        """是否存在负坐标的显示器"""
        self._ensure_fresh()
        for monitor in self._monitors:
            if monitor.left < 0 or monitor.top < 0:
                return True
        return False


# 全局单例
_manager_instance: Optional[MultiMonitorManager] = None
_manager_lock = threading.Lock()


def get_multi_monitor_manager() -> MultiMonitorManager:
    """获取多显示器管理器单例"""
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = MultiMonitorManager()
    return _manager_instance


def get_virtual_screen_bounds() -> Tuple[int, int, int, int]:
    """快捷方法: 获取虚拟屏幕边界"""
    return get_multi_monitor_manager().get_virtual_screen_bounds()


def get_primary_screen_size() -> Tuple[int, int]:
    """快捷方法: 获取主显示器分辨率 (width, height)"""
    manager = get_multi_monitor_manager()
    monitor = manager.get_primary_monitor()
    if monitor is None:
        return (0, 0)
    return (monitor.width, monitor.height)


def get_monitor_at_point(x: int, y: int) -> Optional[MonitorInfo]:
    """快捷方法: 获取指定点所在的显示器"""
    return get_multi_monitor_manager().get_monitor_at_point(x, y)


def clamp_to_virtual_screen(x: int, y: int) -> Tuple[int, int]:
    """快捷方法: 将坐标限制在虚拟屏幕范围内"""
    return get_multi_monitor_manager().clamp_to_virtual_screen(x, y)


def fix_pyautogui_coords(box_left: int, box_top: int) -> Tuple[int, int]:
    """快捷方法: 修复pyautogui多显示器坐标"""
    return get_multi_monitor_manager().fix_pyautogui_coords(box_left, box_top)


# 测试代码
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    logger.info("=" * 80)
    logger.info("多显示器管理器测试")
    logger.info("=" * 80)

    manager = get_multi_monitor_manager()

    logger.info(f"\n显示器数量: {manager.get_monitor_count()}")
    logger.info(f"多显示器: {manager.is_multi_monitor()}")
    logger.info(f"存在负坐标: {manager.has_negative_coords()}")

    logger.info("\n虚拟屏幕边界:")
    left, top, width, height = manager.get_virtual_screen_bounds()
    logger.info(f"  位置: ({left}, {top})")
    logger.info(f"  尺寸: {width} x {height}")

    logger.info("\n各显示器信息:")
    for i, monitor in enumerate(manager.get_monitors()):
        logger.info(f"\n  [{i}] {monitor.device_name}")
        logger.info(f"      位置: ({monitor.left}, {monitor.top})")
        logger.info(f"      尺寸: {monitor.width} x {monitor.height}")
        logger.info(f"      DPI: {monitor.dpi_x}")
        logger.info(f"      缩放: {monitor.scale_factor:.1%}")
        logger.info(f"      主显示器: {monitor.is_primary}")

    logger.info("\n" + "=" * 80)
    logger.info("MSS 配置:")
    for i, cfg in enumerate(manager.get_mss_monitors_config()):
        logger.info(f"  [{i}] {cfg}")

    logger.info("\n全屏配置:")
    logger.info(f"  {manager.get_all_screens_config()}")

    logger.info("\n" + "=" * 80)
