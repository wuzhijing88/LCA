#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DXGI 截图引擎 (Desktop Duplication API)

特性:
- 基于 DXGI Desktop Duplication API
- GPU 硬件加速
- 高性能屏幕捕获
- 仅支持前台模式
- DPI 感知和多显示器兼容
- 完整的资源管理和清理

依赖:
    pip install numpy opencv-python dxcam
"""

import logging
import ctypes
import numpy as np
import threading
import time
from typing import Optional, Tuple, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_last_failure_reason = ""
_last_failure_lock = threading.Lock()


def _set_last_failure_reason(reason: str) -> None:
    global _last_failure_reason
    try:
        normalized = str(reason or "").strip().lower()
    except Exception:
        normalized = ""
    with _last_failure_lock:
        _last_failure_reason = normalized


def get_last_dxgi_capture_failure_reason() -> str:
    with _last_failure_lock:
        return str(_last_failure_reason or "")

# DXGI 库（Desktop Duplication API）
DXGI_AVAILABLE = False
DXCAM_AVAILABLE = False
dxcam = None

try:
    import dxcam as dxcam_module
    dxcam = dxcam_module
    DXCAM_AVAILABLE = True
    DXGI_AVAILABLE = True
    logger.info("[OK] dxcam 已加载")
except Exception as e:
    DXGI_AVAILABLE = False
    DXCAM_AVAILABLE = False
    logger.warning("[ERROR] DXGI 不可用: %s", e)

import cv2
import win32api
import win32gui

from utils.capture.hwnd_capture_utils import CaptureStats


@dataclass
class MonitorInfo:
    """显示器信息"""
    index: int
    left: int
    top: int
    width: int
    height: int
    is_primary: bool = False


class DXGICapture:
    """DXGI 截图管理器"""

    def __init__(self):
        """初始化"""
        if not DXGI_AVAILABLE:
            raise ImportError("DXGI 不可用，请安装: pip install dxcam")

        self.stats = CaptureStats()
        self.lock = threading.Lock()
        self._monitors = []
        self._camera = None
        self._camera_output_idx = None
        self._camera_lock = threading.RLock()
        self._initialized = False
        self._last_hwnd = None
        self._last_frame = None
        self._last_frame_key = None
        self._last_frame_ts = 0.0
        self._last_none_log_ts = 0.0
        self._closed = False

        self._init_capture()

    def _init_capture(self):
        """先完成显示器校验，再取得相机所有权。"""
        with self._camera_lock:
            if not DXCAM_AVAILABLE:
                raise RuntimeError("dxcam 不可用")
            monitors = self._get_monitors_dxcam()
            camera = dxcam.create(output_idx=0, output_color="BGR")
            if camera is None:
                raise RuntimeError("DXGI未返回相机对象")
            self._camera = camera
            self._camera_output_idx = 0
            self._monitors = monitors
            self._initialized = True
            _set_last_failure_reason("")

    def _get_win32_error(self) -> Optional[Tuple[int, str]]:
        try:
            err_code = ctypes.windll.kernel32.GetLastError()
            if err_code == 0:
                return None
            buf = ctypes.create_unicode_buffer(512)
            ctypes.windll.kernel32.FormatMessageW(
                0x00001000,
                None,
                err_code,
                0,
                buf,
                len(buf),
                None,
            )
            return err_code, buf.value.strip()
        except Exception:
            return None

    def _log_failure_context(self, reason: str, monitor_index: int = None, region: Tuple[int, int, int, int] = None):
        parts = [reason]
        hwnd = self._last_hwnd
        if hwnd:
            try:
                parts.append(f"hwnd={hwnd}")
                parts.append(f"is_window={win32gui.IsWindow(hwnd)}")
                parts.append(f"visible={win32gui.IsWindowVisible(hwnd)}")
                parts.append(f"iconic={win32gui.IsIconic(hwnd)}")
                fg = win32gui.GetForegroundWindow()
                parts.append(f"foreground={fg}")
                if win32gui.IsWindow(hwnd):
                    rect = win32gui.GetWindowRect(hwnd)
                    parts.append(f"rect={rect}")
            except Exception:
                pass
        if monitor_index is not None:
            parts.append(f"monitor_index={monitor_index}")
        if region is not None:
            parts.append(f"region={region}")
        if self._camera is not None:
            cam_w = int(getattr(self._camera, "width", 0) or 0)
            cam_h = int(getattr(self._camera, "height", 0) or 0)
            parts.append(f"output_idx={self._camera_output_idx}")
            parts.append(f"output_size={cam_w}x{cam_h}")
        err = self._get_win32_error()
        if err:
            parts.append(f"win32_error={err[0]} {err[1]}")
        logger.error("DXGI failure context: " + ", ".join(parts))

    def _ensure_camera(self, monitor_index: int):
        with self._camera_lock:
            if self._closed or not self._initialized:
                raise RuntimeError("DXGI相机已关闭或尚未初始化")
            if self._camera is not None and self._camera_output_idx == monitor_index:
                return
            if self._camera is not None:
                self._camera.release()
                self._camera = None
                self._camera_output_idx = None
            camera = dxcam.create(output_idx=int(monitor_index), output_color="BGR")
            if camera is None:
                raise RuntimeError("DXGI未返回相机对象")
            self._camera = camera
            self._camera_output_idx = int(monitor_index)

    def _get_monitors_dxcam(self) -> List[MonitorInfo]:
        monitors = []
        for i, (hmon, _hdc, _rect) in enumerate(win32api.EnumDisplayMonitors()):
            info = win32api.GetMonitorInfo(hmon)
            left, top, right, bottom = info["Monitor"]
            if right <= left or bottom <= top:
                raise RuntimeError("DXGI显示器尺寸无效")
            monitors.append(MonitorInfo(i, int(left), int(top), int(right-left), int(bottom-top), bool(info["Flags"] & 1)))
        if not monitors:
            raise RuntimeError("DXGI无法枚举显示器")
        return monitors

    def get_monitors(self) -> List[MonitorInfo]:
        """获取显示器列表"""
        return self._monitors.copy()

    def _get_monitor_for_window(self, hwnd: int) -> Optional[MonitorInfo]:
        self._monitors = self._get_monitors_dxcam()
        rect = win32gui.GetWindowRect(hwnd)
        x, y = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        for monitor in self._monitors:
            if monitor.left <= x < monitor.left + monitor.width and monitor.top <= y < monitor.top + monitor.height:
                return monitor
        return None

    def capture_screen(
        self,
        monitor_index: int = 0,
        region: Tuple[int, int, int, int] = None,
        frame_key=None,
    ) -> Optional[np.ndarray]:
        """
        捕获屏幕

        Args:
            monitor_index: 显示器索引（dxcam 的 output_idx）
            region: (left, top, width, height) 区域，坐标相对于该显示器左上角；None 表示全屏

        Returns:
            BGR 格式的 numpy 数组，失败返回 None
        """
        start_time = time.time()

        try:
            if not self._initialized or self._closed:
                _set_last_failure_reason("not_initialized")
                return None

            # 校验并切换到正确的输出
            if self._monitors and (monitor_index < 0 or monitor_index >= len(self._monitors)):
                _set_last_failure_reason("invalid_monitor_index")
                raise ValueError(f"无效的显示器索引: {monitor_index} (0..{len(self._monitors)-1})")

            with self._camera_lock:
                self._ensure_camera(monitor_index)

                # dxcam 的 region 需要在当前输出的尺寸范围内
                if region is not None:
                    left, top, width, height = region
                    if width <= 0 or height <= 0:
                        _set_last_failure_reason("invalid_region_size")
                        raise ValueError(f"截图区域的宽高必须大于0：{region}")

                    cam_w = int(getattr(self._camera, "width", 0) or 0)
                    cam_h = int(getattr(self._camera, "height", 0) or 0)
                    if cam_w <= 0 or cam_h <= 0:
                        _set_last_failure_reason("invalid_output_size")
                        raise RuntimeError(f"无法获取 dxcam 输出尺寸: {cam_w}x{cam_h}")

                    right = left + width
                    bottom = top + height
                    if left < 0 or top < 0 or right > cam_w or bottom > cam_h:
                        _set_last_failure_reason("region_out_of_bounds")
                        raise ValueError(
                            f"截图区域{region}超出显示器{monitor_index}的范围（{cam_w}x{cam_h}）"
                        )

                if DXCAM_AVAILABLE and self._camera:
                    if frame_key is None:
                        frame_key = (
                            "screen",
                            int(monitor_index),
                            None if region is None else tuple(int(v) for v in region),
                        )
                    return self._capture_dxcam(monitor_index, region, start_time, frame_key=frame_key)
                else:
                    logger.error("DXGI 未正确初始化")
                    _set_last_failure_reason("camera_not_ready")
                    return None

        except Exception as e:
            logger.error(f"DXGI 截图失败: {e}")
            if not get_last_dxgi_capture_failure_reason():
                _set_last_failure_reason(f"capture_screen_exception:{type(e).__name__}".lower())
            self._log_failure_context("capture_screen exception", monitor_index, region)
            with self.lock:
                self.stats.total_captures += 1
                self.stats.failed_captures += 1
            return None

    def _capture_dxcam(
        self,
        monitor_index: int,
        region: Tuple[int, int, int, int],
        start_time: float,
        frame_key=None,
    ) -> Optional[np.ndarray]:
        """使用 dxcam 截图"""
        try:
            if self._camera_output_idx != monitor_index:
                raise RuntimeError("DXGI相机输出与请求不一致")
            if region is None:
                frame = self._camera.grab()
            else:
                left, top, width, height = region
                frame = self._camera.grab(region=(left, top, left + width, top + height))
            if frame is None:
                _set_last_failure_reason("dxcam_returned_none")
                with self.lock:
                    self.stats.total_captures += 1
                    self.stats.failed_captures += 1
                return None

            # dxcam 返回 BGR 格式，无需转换
            img_bgr = frame
            self._last_frame = img_bgr
            self._last_frame_key = frame_key
            self._last_frame_ts = time.time()

            # 更新统计
            elapsed_ms = (time.time() - start_time) * 1000
            with self.lock:
                self.stats.total_captures += 1
                self.stats.success_captures += 1
                self.stats.total_time_ms += elapsed_ms

            logger.debug(f"DXGI (dxcam) 截图成功: {img_bgr.shape}, {elapsed_ms:.1f}ms")
            _set_last_failure_reason("")
            return img_bgr

        except Exception as e:
            if region is not None and self._camera is not None:
                cam_w = int(getattr(self._camera, "width", 0) or 0)
                cam_h = int(getattr(self._camera, "height", 0) or 0)
                logger.error(f"dxcam 截图失败: {e} (output={self._camera_output_idx}, size={cam_w}x{cam_h}, region={region})")
            else:
                logger.error(f"dxcam 截图失败: {e}")
            _set_last_failure_reason(f"dxcam_exception:{type(e).__name__}".lower())
            self._log_failure_context("dxcam exception", monitor_index, region)
            return None

    def capture_window(
        self,
        hwnd: int,
        client_area_only: bool = True
    ) -> Optional[np.ndarray]:
        """
        捕获窗口（DXGI 通过截取窗口所在屏幕区域实现）

        注意: DXGI 只能捕获前台可见窗口

        Args:
            hwnd: 窗口句柄
            client_area_only: 是否只捕获客户区

        Returns:
            BGR 格式的 numpy 数组，失败返回 None
        """
        try:
            # 检查窗口有效性
            if not win32gui.IsWindow(hwnd):
                logger.error(f"无效的窗口句柄: {hwnd}")
                _set_last_failure_reason("invalid_hwnd")
                return None

            # 检查窗口是否可见
            if not win32gui.IsWindowVisible(hwnd):
                logger.warning(f"窗口不可见: {hwnd}")
                _set_last_failure_reason("window_not_visible")
                return None

            # 获取窗口位置
            if client_area_only:
                rect = win32gui.GetClientRect(hwnd)
                client_pos = win32gui.ClientToScreen(hwnd, (0, 0))
                left = client_pos[0]
                top = client_pos[1]
                width = rect[2]
                height = rect[3]
            else:
                rect = win32gui.GetWindowRect(hwnd)
                left = rect[0]
                top = rect[1]
                width = rect[2] - rect[0]
                height = rect[3] - rect[1]

            if width <= 0 or height <= 0:
                logger.error(f"无效的窗口尺寸: {width}x{height}")
                _set_last_failure_reason("invalid_window_size")
                return None

            # 获取窗口所在显示器
            monitor = self._get_monitor_for_window(hwnd)
            if monitor is None:
                _set_last_failure_reason("monitor_not_found")
                raise RuntimeError("无法确定窗口所在显示器")
            monitor_index = monitor.index
            self._last_hwnd = hwnd

            # DXGI/dxcam 的 region 坐标相对于显示器左上角
            rel_left = int(left - monitor.left)
            rel_top = int(top - monitor.top)

            # 严格校验：窗口区域必须在单个显示器内，否则 dxcam 会报 Invalid Region
            if rel_left < 0 or rel_top < 0 or rel_left + width > monitor.width or rel_top + height > monitor.height:
                _set_last_failure_reason("window_out_of_monitor_bounds")
                raise ValueError(
                    "窗口区域跨屏/越界，DXGI 无法裁剪: "
                    f"abs=({left},{top},{width},{height}), "
                    f"rel=({rel_left},{rel_top},{width},{height}), "
                    f"monitor={monitor.index}@({monitor.left},{monitor.top}) {monitor.width}x{monitor.height}"
                )

            # 截取窗口所在区域（相对坐标）
            frame_key = (
                "hwnd",
                int(hwnd),
                int(monitor_index),
                int(rel_left),
                int(rel_top),
                int(width),
                int(height),
            )
            frame = self.capture_screen(
                monitor_index,
                region=(rel_left, rel_top, width, height),
                frame_key=frame_key,
            )

            return frame

        except Exception as e:
            logger.error(f"DXGI 窗口截图失败: {e}")
            if not get_last_dxgi_capture_failure_reason():
                _set_last_failure_reason(f"capture_window_exception:{type(e).__name__}".lower())
            return None

    def get_pixel_color(
        self,
        hwnd: int,
        x: int,
        y: int,
        client_coords: bool = True
    ) -> Optional[Tuple[int, int, int]]:
        """
        获取像素颜色

        Args:
            hwnd: 窗口句柄
            x: X 坐标
            y: Y 坐标
            client_coords: 是否为客户区坐标

        Returns:
            (R, G, B) 颜色值，失败返回 None
        """
        try:
            frame = self.capture_window(hwnd, client_area_only=client_coords)
            if frame is None:
                return None

            if y < 0 or y >= frame.shape[0] or x < 0 or x >= frame.shape[1]:
                return None

            b, g, r = frame[y, x]
            return (int(r), int(g), int(b))

        except Exception as e:
            logger.error(f"获取像素颜色失败: {e}")
            return None

    def cleanup(self, hwnd: int = None):
        with self._camera_lock:
            if hwnd is None and self._camera is not None:
                # 释放失败时保留对象，不发布一个仍占用原生资源的新相机。
                self._camera.release()
                self._camera = None
                self._camera_output_idx = None
            with self.lock:
                if hwnd is None or self._last_hwnd == hwnd:
                    self._last_hwnd = None
                    self._last_frame = None
                    self._last_frame_key = None
                    self._last_frame_ts = 0.0
                if hwnd is None:
                    self._monitors.clear()
                    self._initialized = False
                    self._closed = True

    def clear_runtime_cache(self, hwnd: int = None):
        """软清理运行时缓存（不释放camera，避免下次重建）。"""
        try:
            with self._camera_lock:
                with self.lock:
                    if hwnd is not None:
                        if self._last_hwnd == hwnd:
                            self._last_hwnd = None
                            self._last_frame = None
                            self._last_frame_key = None
                            self._last_frame_ts = 0.0
                    else:
                        self._last_hwnd = None
                        self._last_frame = None
                        self._last_frame_key = None
                        self._last_frame_ts = 0.0
                    self._last_none_log_ts = 0.0
        except Exception as e:
            logger.error(f"DXGI 运行时缓存清理失败: {e}")

    def get_stats(self) -> dict:
        """获取统计信息"""
        with self.lock:
            return {
                'total_captures': self.stats.total_captures,
                'success_captures': self.stats.success_captures,
                'failed_captures': self.stats.failed_captures,
                'avg_time_ms': self.stats.avg_time_ms,
                'success_rate': f"{self.stats.success_rate:.1f}%",
                'backend': 'dxcam'
            }


# 全局实例
_global_capture = None
_global_lock = threading.Lock()


def get_global_capture() -> DXGICapture:
    """获取全局截图器实例"""
    global _global_capture
    with _global_lock:
        if _global_capture is None:
            _global_capture = DXGICapture()
        return _global_capture


def get_existing_global_capture() -> Optional[DXGICapture]:
    """读取已存在的截图器，不为统计查询创建相机。"""
    with _global_lock:
        return _global_capture


def capture_window_dxgi(
    hwnd: int,
    client_area_only: bool = True
) -> Optional[np.ndarray]:
    """
    DXGI 窗口截图（全局接口）

    注意: DXGI 只能捕获前台可见窗口

    Args:
        hwnd: 窗口句柄
        client_area_only: 是否只捕获客户区

    Returns:
        BGR 格式的 numpy 数组
    """
    capture = get_global_capture()
    return capture.capture_window(hwnd, client_area_only)


def capture_screen_dxgi(
    monitor_index: int = 0,
    region: Tuple[int, int, int, int] = None
) -> Optional[np.ndarray]:
    """
    DXGI 屏幕截图（全局接口）

    Args:
        monitor_index: 显示器索引
        region: (left, top, width, height) 区域

    Returns:
        BGR 格式的 numpy 数组
    """
    capture = get_global_capture()
    return capture.capture_screen(monitor_index, region)


def get_pixel_color_dxgi(
    hwnd: int,
    x: int,
    y: int,
    client_coords: bool = True
) -> Optional[Tuple[int, int, int]]:
    """获取像素颜色（全局接口）"""
    capture = get_global_capture()
    return capture.get_pixel_color(hwnd, x, y, client_coords)


def cleanup_dxgi(hwnd: int = None):
    """清理资源（全局接口）"""
    global _global_capture
    with _global_lock:
        capture = _global_capture
        if capture is not None:
            capture.cleanup(hwnd)
            if hwnd is None:
                _global_capture = None


def clear_dxgi_runtime_cache(hwnd: int = None):
    """软清理DXGI运行时缓存（不销毁全局实例）。"""
    with _global_lock:
        capture = _global_capture
    if capture:
        capture.clear_runtime_cache(hwnd)


def is_dxgi_available() -> bool:
    """检查 DXGI 是否可用"""
    return bool(DXGI_AVAILABLE and DXCAM_AVAILABLE)


def get_dxgi_monitors() -> List[MonitorInfo]:
    """获取显示器列表"""
    if not is_dxgi_available():
        return []
    capture = get_global_capture()
    return capture.get_monitors()
