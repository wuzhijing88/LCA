#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PrintWindow 截图引擎

特性:
- 基于 Win32 PrintWindow API
- 支持后台窗口截图
- DPI 感知和多显示器兼容
- 完整的资源管理和清理

依赖:
    pip install pywin32 numpy opencv-python
"""

import logging
import numpy as np
import threading
import ctypes
from typing import Optional, Tuple
from dataclasses import dataclass

from utils.hwnd_capture_utils import CaptureStats, crop_frame_by_hwnd, get_window_rect_with_dwm, resolve_capture_target

logger = logging.getLogger(__name__)

import cv2
import win32gui
import win32ui


class PrintWindowCapture:
    """PrintWindow 截图管理器"""

    def __init__(self):
        """初始化"""
        self.stats = CaptureStats()
        self.lock = threading.Lock()
        # PrintWindow 在多线程并发下可能出现跨窗口错帧，统一串行化抓图链路。
        self._capture_lock = threading.Lock()
        self.auto_fix_black_borders = True
        self._black_border_threshold = 8
        self._black_border_min_ratio = 0.02
        self._black_border_min_area_ratio = 0.40

    def _auto_fix_black_borders(self, img_bgr: np.ndarray, target_size: Tuple[int, int]) -> np.ndarray:
        """Auto-crop black borders and resize to target size."""
        try:
            if img_bgr is None:
                return img_bgr
            h, w = img_bgr.shape[:2]
            if h <= 0 or w <= 0:
                return img_bgr
            if len(img_bgr.shape) == 3 and img_bgr.shape[2] == 4:
                gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGRA2GRAY)
            elif len(img_bgr.shape) == 3:
                gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            else:
                gray = img_bgr
            _, mask = cv2.threshold(gray, self._black_border_threshold, 255, cv2.THRESH_BINARY)
            coords = cv2.findNonZero(mask)
            if coords is None:
                return img_bgr
            x, y, bw, bh = cv2.boundingRect(coords)
            left = x
            top = y
            right = w - (x + bw)
            bottom = h - (y + bh)
            min_border = max(1, int(self._black_border_min_ratio * min(w, h)))
            if max(left, right, top, bottom) < min_border:
                return img_bgr
            if (bw * bh) < (self._black_border_min_area_ratio * w * h):
                return img_bgr
            cropped = img_bgr[y:y + bh, x:x + bw]
            target_w, target_h = target_size
            if target_w > 0 and target_h > 0 and (bw != target_w or bh != target_h):
                cropped = cv2.resize(cropped, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
            return cropped
        except Exception as e:
            logger.debug(f"黑边修复失败：{e}")
            return img_bgr

    def capture_window(
        self,
        hwnd: int,
        client_area_only: bool = True
    ) -> Optional[np.ndarray]:
        """
        使用 PrintWindow 捕获窗口

        Args:
            hwnd: 窗口句柄
            client_area_only: 是否只捕获客户区

        Returns:
            BGR 格式的 numpy 数组，失败返回 None
        """
        import time
        start_time = time.time()

        dc_window = None
        dc_mem = None
        dc_compatible = None
        bitmap = None
        capture_lock_acquired = False
        target_info = resolve_capture_target(hwnd)
        target_hwnd = target_info.target_hwnd
        capture_hwnd = target_info.capture_hwnd

        try:
            self._capture_lock.acquire()
            capture_lock_acquired = True

            # 检查窗口有效性
            if not win32gui.IsWindow(target_hwnd):
                logger.error(f"无效的窗口句柄: {target_hwnd}")
                return None

            rect = win32gui.GetWindowRect(capture_hwnd)
            window_rect: Optional[Tuple[int, int, int, int]] = (
                int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
            )
            dwm_rect: Optional[Tuple[int, int, int, int]] = get_window_rect_with_dwm(capture_hwnd)
            width = int(window_rect[2] - window_rect[0])
            height = int(window_rect[3] - window_rect[1])

            if width <= 0 or height <= 0:
                logger.error(f"无效的窗口尺寸: {width}x{height}")
                return None

            # 进程启动阶段已经声明 Per-Monitor DPI awareness。
            # 这里再手动乘 DPI 会把 PrintWindow 抓到的窗口放大，导致开发/打包行为分叉。
            capture_width = width
            capture_height = height

            # 创建设备上下文
            dc_window = win32gui.GetWindowDC(capture_hwnd)
            dc_mem = win32ui.CreateDCFromHandle(dc_window)
            dc_compatible = dc_mem.CreateCompatibleDC()

            # 创建位图
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(dc_mem, capture_width, capture_height)
            dc_compatible.SelectObject(bitmap)

            # 使用 PrintWindow 捕获 (通过 ctypes 调用)
            # PW_CLIENTONLY = 0x1, PW_RENDERFULLCONTENT = 0x2
            flags = 0x00000002  # PW_RENDERFULLCONTENT

            # ctypes 调用 PrintWindow
            user32 = ctypes.windll.user32
            result = user32.PrintWindow(capture_hwnd, dc_compatible.GetSafeHdc(), flags)

            if result == 0:
                logger.error(f"PrintWindow 调用失败: hwnd={capture_hwnd}")
                return None

            # 转换为 numpy 数组
            bmp_bits = bitmap.GetBitmapBits(True)

            img = np.frombuffer(bmp_bits, dtype=np.uint8)
            img.shape = (capture_height, capture_width, 4)

            # BGRA -> BGR
            img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

            img_bgr = crop_frame_by_hwnd(
                frame=img_bgr,
                target_hwnd=target_hwnd,
                capture_hwnd=capture_hwnd,
                client_area_only=client_area_only,
                capture_window_rect=window_rect,
                capture_dwm_rect=dwm_rect,
            )
            if img_bgr is None:
                logger.error(
                    f"PrintWindow 句柄裁剪失败: target={target_hwnd}, capture={capture_hwnd}, client={client_area_only}"
                )
                return None

            height, width = img_bgr.shape[:2]



            if self.auto_fix_black_borders:
                img_bgr = self._auto_fix_black_borders(img_bgr, (width, height))

            # 更新统计
            elapsed_ms = (time.time() - start_time) * 1000
            with self.lock:
                self.stats.total_captures += 1
                self.stats.success_captures += 1
                self.stats.total_time_ms += elapsed_ms

            logger.debug(f"PrintWindow 截图成功: {img_bgr.shape}, {elapsed_ms:.1f}ms")
            return img_bgr

        except Exception as e:
            logger.error(f"PrintWindow 截图失败: {e}")
            with self.lock:
                self.stats.total_captures += 1
                self.stats.failed_captures += 1
            return None

        finally:
            # 清理资源
            try:
                if bitmap:
                    win32gui.DeleteObject(bitmap.GetHandle())
            except Exception:
                pass

            try:
                if dc_compatible:
                    dc_compatible.DeleteDC()
            except Exception:
                pass

            try:
                if dc_mem:
                    dc_mem.DeleteDC()
            except Exception:
                pass

            try:
                if dc_window:
                    win32gui.ReleaseDC(capture_hwnd, dc_window)
            except Exception:
                pass
            if capture_lock_acquired:
                try:
                    self._capture_lock.release()
                except Exception:
                    pass

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
        logger.debug(f"PrintWindow 资源已清理: hwnd={hwnd}")

    def get_stats(self) -> dict:
        """获取统计信息"""
        with self.lock:
            return {
                'total_captures': self.stats.total_captures,
                'success_captures': self.stats.success_captures,
                'failed_captures': self.stats.failed_captures,
                'avg_time_ms': self.stats.avg_time_ms,
                'success_rate': f"{self.stats.success_rate:.1f}%"
            }


# 全局实例
_global_capture = None
_global_lock = threading.Lock()


def get_global_capture() -> PrintWindowCapture:
    """获取全局截图器实例"""
    global _global_capture
    if _global_capture is None:
        with _global_lock:
            if _global_capture is None:
                _global_capture = PrintWindowCapture()
    return _global_capture


def capture_window_printwindow(
    hwnd: int,
    client_area_only: bool = True
) -> Optional[np.ndarray]:
    """
    PrintWindow 窗口截图（全局接口）

    Args:
        hwnd: 窗口句柄
        client_area_only: 是否只捕获客户区

    Returns:
        BGR 格式的 numpy 数组
    """
    capture = get_global_capture()
    return capture.capture_window(hwnd, client_area_only)


def get_pixel_color_printwindow(
    hwnd: int,
    x: int,
    y: int,
    client_coords: bool = True
) -> Optional[Tuple[int, int, int]]:
    """获取像素颜色（全局接口）"""
    capture = get_global_capture()
    return capture.get_pixel_color(hwnd, x, y, client_coords)


def cleanup_printwindow(hwnd: int = None):
    """清理资源（全局接口）"""
    global _global_capture
    with _global_lock:
        capture = _global_capture
        if hwnd is None:
            _global_capture = None

    if capture:
        capture.cleanup(hwnd)


def clear_printwindow_runtime_cache(hwnd: int = None):
    """软清理PrintWindow运行时缓存（不销毁全局实例）。"""
    with _global_lock:
        capture = _global_capture
    if capture:
        capture.cleanup(hwnd)


def is_printwindow_available() -> bool:
    """检查 PrintWindow 是否可用"""
    return True
