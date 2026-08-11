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

# Win32 API
try:
    import win32gui
    import win32api
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    logger.error("[ERROR] Win32 API 不可用")

# OpenCV
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.error("[ERROR] OpenCV 不可用")


@dataclass
class MonitorInfo:
    """显示器信息"""
    index: int
    left: int
    top: int
    width: int
    height: int
    is_primary: bool = False


@dataclass
class CaptureStats:
    """截图统计信息"""
    total_captures: int = 0
    success_captures: int = 0
    failed_captures: int = 0
    total_time_ms: float = 0.0

    @property
    def avg_time_ms(self) -> float:
        return self.total_time_ms / self.total_captures if self.total_captures > 0 else 0.0

    @property
    def success_rate(self) -> float:
        return (self.success_captures / self.total_captures * 100) if self.total_captures > 0 else 0.0


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
        self._reuse_frame_timeout = 0.25
        self._none_frame_retry_count = 2
        self._none_frame_retry_interval_sec = 0.01
        self._last_reinit_attempt_ts = 0.0
        self._reinit_cooldown_sec = 0.1

        self._init_capture()

    def _init_capture(self):
        """初始化截图引擎"""
        try:
            with self._camera_lock:
                if self._camera is not None:
                    try:
                        if hasattr(self._camera, "release"):
                            self._camera.release()
                    except Exception:
                        pass
                self._camera = None
                self._camera_output_idx = None
                self._monitors = []
                self._initialized = False

                if DXCAM_AVAILABLE:
                    self._camera = dxcam.create(output_idx=0, output_color="BGR")
                    self._camera_output_idx = 0
                    self._monitors = self._get_monitors_dxcam()
                    self._initialized = True
                    _set_last_failure_reason("")
                    logger.info("[OK] DXGI Desktop Duplication 已初始化")
                else:
                    _set_last_failure_reason("dxcam_unavailable")
                    raise ImportError("dxcam 不可用")

        except Exception as e:
            logger.error(f"DXGI 初始化失败: {e}")
            _set_last_failure_reason(f"init_failed:{type(e).__name__}".lower())
            self._initialized = False

    def _try_reinitialize(self, force: bool = False) -> bool:
        try:
            now = time.perf_counter()
        except Exception:
            now = time.time()
        with self._camera_lock:
            if self._initialized and self._camera is not None:
                return True
            if (not force) and ((now - float(self._last_reinit_attempt_ts)) < float(self._reinit_cooldown_sec)):
                return False
            self._last_reinit_attempt_ts = now

        self._init_capture()
        with self._camera_lock:
            return bool(self._initialized and self._camera is not None)

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
        """确保 camera 与 monitor_index 对应（dxcam 的 output_idx）"""
        if not DXCAM_AVAILABLE:
            raise RuntimeError("dxcam 不可用")

        if monitor_index is None:
            monitor_index = 0

        with self._camera_lock:
            if self._camera is not None and self._camera_output_idx == monitor_index:
                return

            try:
                # 释放旧 camera
                if self._camera is not None:
                    try:
                        if hasattr(self._camera, "release"):
                            self._camera.release()
                    except Exception:
                        pass
                    self._camera = None

                self._camera = dxcam.create(output_idx=int(monitor_index), output_color="BGR")
                self._camera_output_idx = int(monitor_index)
                logger.info(f"[DXGI] dxcam camera 已切换到输出: {self._camera_output_idx} ({self._camera.width}x{self._camera.height})")
            except Exception as e:
                raise RuntimeError(f"创建 dxcam camera 失败: output_idx={monitor_index}, err={e}") from e

    def _recreate_camera_for_output_locked(self, monitor_index: int) -> bool:
        """在已持有 _camera_lock 时强制重建当前输出对应的 camera。"""
        if not DXCAM_AVAILABLE:
            return False
        try:
            if self._camera is not None:
                try:
                    if hasattr(self._camera, "release"):
                        self._camera.release()
                except Exception:
                    pass
            self._camera = None
            self._camera_output_idx = None
            self._ensure_camera(monitor_index)
            return bool(self._camera is not None and self._camera_output_idx == int(monitor_index))
        except Exception as exc:
            logger.warning("[DXGI] 重建 dxcam camera 失败: output=%s, error=%s", monitor_index, exc)
            return False

    def _get_monitors_dxcam(self) -> List[MonitorInfo]:
        """使用 dxcam 获取显示器列表"""
        monitors: List[MonitorInfo] = []
        try:
            # 优先使用 pywin32 获取显示器信息（可靠、无需手动解析结构体）
            if WIN32_AVAILABLE:
                try:
                    for i, (hmon, _hdc, _rect) in enumerate(win32api.EnumDisplayMonitors()):
                        info = win32api.GetMonitorInfo(hmon) or {}
                        mon_rect = info.get("Monitor")
                        if not mon_rect or len(mon_rect) != 4:
                            continue
                        left, top, right, bottom = mon_rect
                        width = int(right - left)
                        height = int(bottom - top)
                        flags = int(info.get("Flags", 0) or 0)
                        monitors.append(MonitorInfo(
                            index=i,
                            left=int(left),
                            top=int(top),
                            width=width,
                            height=height,
                            is_primary=bool(flags & 1),
                        ))
                except Exception as e:
                    logger.error(f"使用 win32api 获取显示器列表失败: {e}")

            # 兜底：如果枚举失败，至少用 camera 的输出尺寸构造一个主显示器
            if not monitors and self._camera is not None:
                cam_w = int(getattr(self._camera, "width", 0) or 0)
                cam_h = int(getattr(self._camera, "height", 0) or 0)
                if cam_w > 0 and cam_h > 0:
                    monitors = [MonitorInfo(index=0, left=0, top=0, width=cam_w, height=cam_h, is_primary=True)]

            if monitors:
                logger.info("DXGI 显示器列表: " + ", ".join(
                    [f"{m.index}:{m.width}x{m.height}@({m.left},{m.top}){'*' if m.is_primary else ''}" for m in monitors]
                ))
        except Exception as e:
            logger.error(f"获取显示器列表失败: {e}")

        return monitors

    def _refresh_monitors(self) -> None:
        try:
            refreshed = self._get_monitors_dxcam()
            if refreshed:
                self._monitors = refreshed
        except Exception:
            pass

    def get_monitors(self) -> List[MonitorInfo]:
        """获取显示器列表"""
        return self._monitors.copy()

    def _get_monitor_for_window(self, hwnd: int) -> Optional[MonitorInfo]:
        """获取窗口所在的显示器"""
        if not self._monitors:
            self._refresh_monitors()

        if not WIN32_AVAILABLE:
            return self._monitors[0] if self._monitors else None

        try:
            rect = win32gui.GetWindowRect(hwnd)
            window_center_x = (rect[0] + rect[2]) // 2
            window_center_y = (rect[1] + rect[3]) // 2

            for monitor in self._monitors:
                if (monitor.left <= window_center_x < monitor.left + monitor.width and
                    monitor.top <= window_center_y < monitor.top + monitor.height):
                    return monitor

            # 显示器拓扑可能动态变化，刷新后再尝试一次
            self._refresh_monitors()
            for monitor in self._monitors:
                if (monitor.left <= window_center_x < monitor.left + monitor.width and
                    monitor.top <= window_center_y < monitor.top + monitor.height):
                    return monitor

            # 默认返回主显示器
            for monitor in self._monitors:
                if monitor.is_primary:
                    return monitor

            return self._monitors[0] if self._monitors else None

        except Exception as e:
            logger.error(f"获取窗口所在显示器失败: {e}")
            return self._monitors[0] if self._monitors else None

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
            if (not self._initialized) or (self._camera is None):
                if not self._try_reinitialize(force=True):
                    logger.error("DXGI 未初始化")
                    _set_last_failure_reason("not_initialized")
                    return None
            if not self._initialized:
                logger.error("DXGI 未初始化")
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
                        raise ValueError(f"Invalid Region: width/height must be > 0, got {region}")

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
                            f"Invalid Region: {region} out of bounds for output {monitor_index} ({cam_w}x{cam_h})"
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
                # 理论上 capture_screen 会确保一致，这里再兜底提示
                logger.warning(f"[DXGI] camera 输出不一致: camera={self._camera_output_idx}, requested={monitor_index}")

            def _grab_once() -> Optional[np.ndarray]:
                if region:
                    left, top, width, height = region
                    return self._camera.grab(region=(left, top, left + width, top + height))
                return self._camera.grab()

            frame = _grab_once()

            if frame is None:
                now = time.time()
                if (
                    self._last_frame is not None
                    and self._last_frame_key == frame_key
                    and now - self._last_frame_ts <= self._reuse_frame_timeout
                ):
                    elapsed_ms = (time.time() - start_time) * 1000
                    with self.lock:
                        self.stats.total_captures += 1
                        self.stats.success_captures += 1
                        self.stats.total_time_ms += elapsed_ms
                    _set_last_failure_reason("")
                    return self._last_frame

                for _ in range(max(0, int(self._none_frame_retry_count))):
                    retry_interval = max(0.0, float(self._none_frame_retry_interval_sec))
                    if retry_interval > 0:
                        time.sleep(retry_interval)
                    frame = _grab_once()
                    if frame is not None:
                        break

                if frame is None and self._recreate_camera_for_output_locked(monitor_index):
                    frame = _grab_once()

            if frame is None:
                if now - self._last_none_log_ts > 1.0:
                    logger.error("dxcam 截图返回 None")
                    self._log_failure_context("dxcam returned None", monitor_index, region)
                    self._last_none_log_ts = now
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
        if not WIN32_AVAILABLE:
            logger.error("Win32 API 不可用")
            return None

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
            if monitor is None and WIN32_AVAILABLE:
                try:
                    hmon = win32api.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
                    info = win32api.GetMonitorInfo(hmon) or {}
                    mon_rect = info.get("Monitor")
                    if mon_rect and len(mon_rect) == 4:
                        m_left, m_top, m_right, m_bottom = [int(v) for v in mon_rect]
                        m_width = int(m_right - m_left)
                        m_height = int(m_bottom - m_top)
                        if m_width > 0 and m_height > 0:
                            fallback_index = (
                                int(self._camera_output_idx)
                                if self._camera_output_idx is not None
                                else 0
                            )
                            monitor = MonitorInfo(
                                index=fallback_index,
                                left=m_left,
                                top=m_top,
                                width=m_width,
                                height=m_height,
                                is_primary=bool(int(info.get("Flags", 0) or 0) & 1),
                            )
                except Exception:
                    monitor = None
            monitor_index = monitor.index if monitor else 0
            self._last_hwnd = hwnd

            # DXGI/dxcam 的 region 坐标相对于显示器左上角
            if monitor is None:
                _set_last_failure_reason("monitor_not_found")
                raise RuntimeError("无法确定窗口所在显示器")

            rel_left = int(left - monitor.left)
            rel_top = int(top - monitor.top)

            # 严格校验：窗口区域必须在单个显示器内，否则 dxcam 会报 Invalid Region
            if rel_left < 0 or rel_top < 0 or rel_left + width > monitor.width or rel_top + height > monitor.height:
                _set_last_failure_reason("window_out_of_monitor_bounds")
                raise ValueError(
                    f"窗口区域跨屏/越界，DXGI 无法裁剪: "
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
        """清理资源"""
        try:
            with self._camera_lock:
                if hwnd is not None:
                    with self.lock:
                        if self._last_hwnd == hwnd:
                            self._last_hwnd = None
                            self._last_frame = None
                            self._last_frame_key = None
                            self._last_frame_ts = 0.0
                else:
                    with self.lock:
                        self._last_hwnd = None
                        self._last_frame = None
                        self._last_frame_key = None
                        self._last_frame_ts = 0.0
                        self._last_none_log_ts = 0.0
                        self._monitors.clear()
                        self._initialized = False

                    if self._camera:
                        try:
                            if hasattr(self._camera, 'release'):
                                self._camera.release()
                        except:
                            pass
                        self._camera = None
                    self._camera_output_idx = None

            logger.debug(f"DXGI 资源已清理: hwnd={hwnd}")

        except Exception as e:
            logger.error(f"DXGI 清理失败: {e}")

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
    if _global_capture is None:
        with _global_lock:
            if _global_capture is None:
                _global_capture = DXGICapture()
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
        if hwnd is None:
            _global_capture = None

    if capture:
        capture.cleanup(hwnd)


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


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    logger.info("=" * 60)
    logger.info("DXGI 截图引擎测试")
    logger.info("=" * 60)

    if not is_dxgi_available():
        logger.info("[ERROR] DXGI 不可用")
        logger.info("请安装: pip install dxcam")
        exit(1)

    # 显示显示器信息
    monitors = get_dxgi_monitors()
    logger.info(f"\n检测到 {len(monitors)} 个显示器:")
    for mon in monitors:
        logger.info(f"  显示器 {mon.index}: {mon.width}x{mon.height} @ ({mon.left}, {mon.top})")

    # 查找窗口
    if WIN32_AVAILABLE:
        hwnd = win32gui.FindWindow(None, "二重螺旋")
        if hwnd:
            logger.info(f"\n目标窗口: HWND={hwnd}")

            # 测试窗口截图
            logger.info("\n开始窗口截图测试...")
            start = time.time()

            frame = capture_window_dxgi(hwnd, client_area_only=True)

            elapsed = (time.time() - start) * 1000
            logger.info(f"截图耗时: {elapsed:.1f}ms")

            if frame is not None:
                logger.info(f"帧尺寸: {frame.shape}")
                if CV2_AVAILABLE:
                    cv2.imwrite("dxgi_window_test.png", frame)
                    logger.info("已保存: dxgi_window_test.png")
            else:
                logger.info("[ERROR] 窗口截图失败")
        else:
            logger.info("\n未找到测试窗口")

    # 测试全屏截图
    logger.info("\n开始全屏截图测试...")
    start = time.time()

    frame = capture_screen_dxgi(0)

    elapsed = (time.time() - start) * 1000
    logger.info(f"截图耗时: {elapsed:.1f}ms")

    if frame is not None:
        logger.info(f"帧尺寸: {frame.shape}")
        if CV2_AVAILABLE:
            cv2.imwrite("dxgi_screen_test.png", frame)
            logger.info("已保存: dxgi_screen_test.png")
    else:
        logger.info("[ERROR] 全屏截图失败")

    # 统计信息
    capture = get_global_capture()
    stats = capture.get_stats()
    logger.info("\n统计信息:")
    for key, value in stats.items():
        logger.info(f"  {key}: {value}")

    cleanup_dxgi()
    logger.info("\n测试完成")
