#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GDI 截图引擎

特性:
- 基于 Win32 GDI BitBlt
- 支持前台和后台窗口
- DPI 感知和多显示器兼容
- 完整的资源管理和清理

依赖:
    pip install pywin32 numpy opencv-python
"""

import logging
import numpy as np
import threading
from typing import Optional, Tuple
from dataclasses import dataclass

from utils.hwnd_capture_utils import crop_frame_by_hwnd, get_window_rect_with_dwm, resolve_capture_target
from utils.multi_monitor_manager import get_virtual_screen_bounds

logger = logging.getLogger(__name__)

# Win32 API
try:
    import win32gui
    import win32ui
    import win32con
    WIN32_AVAILABLE = True
    logger.info("[OK] Win32 API 已加载")
except ImportError as e:
    WIN32_AVAILABLE = False
    logger.error(f"[ERROR] Win32 API 不可用: {e}")

# OpenCV
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.error("[ERROR] OpenCV 不可用")


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


class GDICapture:
    """GDI 截图管理器"""

    def __init__(self):
        """初始化"""
        if not WIN32_AVAILABLE:
            raise ImportError("Win32 API 不可用，请安装 pywin32")

        self.stats = CaptureStats()
        self.lock = threading.Lock()
        self._capture_lock = threading.Lock()

    def capture_window(
        self,
        hwnd: int,
        client_area_only: bool = True
    ) -> Optional[np.ndarray]:
        """
        使用 GDI BitBlt 捕获窗口

        前台窗口: 使用屏幕 DC
        后台窗口: 使用窗口 DC

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

            dc_window = win32gui.GetWindowDC(capture_hwnd)
            dc_mem = win32ui.CreateDCFromHandle(dc_window)
            logger.debug(
                f"GDI 严格句柄模式: target={target_hwnd}, capture={capture_hwnd}, client={client_area_only}"
            )

            dc_compatible = dc_mem.CreateCompatibleDC()

            # 创建位图
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(dc_mem, width, height)
            dc_compatible.SelectObject(bitmap)

            # 使用 BitBlt 复制
            result = dc_compatible.BitBlt(
                (0, 0),
                (width, height),
                dc_mem,
                (0, 0),
                win32con.SRCCOPY
            )

            if result == 0:
                logger.error(f"BitBlt 调用失败: hwnd={capture_hwnd}")
                return None

            # 转换为 numpy 数组
            bmp_bits = bitmap.GetBitmapBits(True)

            img = np.frombuffer(bmp_bits, dtype=np.uint8)
            img.shape = (height, width, 4)

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
                    f"GDI 句柄裁剪失败: target={target_hwnd}, capture={capture_hwnd}, client={client_area_only}"
                )
                return None

            # 更新统计
            elapsed_ms = (time.time() - start_time) * 1000
            with self.lock:
                self.stats.total_captures += 1
                self.stats.success_captures += 1
                self.stats.total_time_ms += elapsed_ms

            logger.debug(f"GDI 截图成功: {img_bgr.shape}, {elapsed_ms:.1f}ms")
            return img_bgr

        except Exception as e:
            logger.error(f"GDI 截图失败: {e}")
            with self.lock:
                self.stats.total_captures += 1
                self.stats.failed_captures += 1
            return None

        finally:
            # 清理资源
            try:
                if bitmap:
                    win32gui.DeleteObject(bitmap.GetHandle())
            except:
                pass

            try:
                if dc_compatible:
                    dc_compatible.DeleteDC()
            except:
                pass

            try:
                if dc_mem:
                    dc_mem.DeleteDC()
            except:
                pass

            try:
                if dc_window:
                    win32gui.ReleaseDC(capture_hwnd, dc_window)
            except:
                pass
            if capture_lock_acquired:
                try:
                    self._capture_lock.release()
                except Exception:
                    pass

    def capture_screen(
        self,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[np.ndarray]:
        """使用 GDI BitBlt 捕获屏幕绝对区域。"""
        import time

        start_time = time.time()
        dc_screen = None
        dc_mem = None
        dc_compatible = None
        bitmap = None
        capture_lock_acquired = False

        try:
            self._capture_lock.acquire()
            capture_lock_acquired = True

            virtual_left, virtual_top, virtual_width, virtual_height = get_virtual_screen_bounds()
            if virtual_width <= 0 or virtual_height <= 0:
                logger.error("虚拟屏幕尺寸无效")
                return None

            if region is None:
                left = int(virtual_left)
                top = int(virtual_top)
                width = int(virtual_width)
                height = int(virtual_height)
            else:
                left, top, width, height = [int(value) for value in region]

            if width <= 0 or height <= 0:
                logger.error(f"无效的屏幕区域尺寸: {width}x{height}")
                return None

            virtual_right = int(virtual_left + virtual_width)
            virtual_bottom = int(virtual_top + virtual_height)
            if (
                left < virtual_left
                or top < virtual_top
                or left + width > virtual_right
                or top + height > virtual_bottom
            ):
                logger.error(
                    "屏幕区域超出虚拟屏幕范围: "
                    f"region=({left},{top},{width},{height}), "
                    f"virtual=({virtual_left},{virtual_top},{virtual_width},{virtual_height})"
                )
                return None

            dc_screen = win32gui.GetDC(0)
            dc_mem = win32ui.CreateDCFromHandle(dc_screen)
            dc_compatible = dc_mem.CreateCompatibleDC()

            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(dc_mem, width, height)
            dc_compatible.SelectObject(bitmap)

            result = dc_compatible.BitBlt(
                (0, 0),
                (width, height),
                dc_mem,
                (left, top),
                win32con.SRCCOPY,
            )
            if result == 0:
                logger.error(f"GDI 屏幕截图 BitBlt 失败: region=({left},{top},{width},{height})")
                return None

            bmp_bits = bitmap.GetBitmapBits(True)
            img = np.frombuffer(bmp_bits, dtype=np.uint8)
            img.shape = (height, width, 4)
            img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

            elapsed_ms = (time.time() - start_time) * 1000
            with self.lock:
                self.stats.total_captures += 1
                self.stats.success_captures += 1
                self.stats.total_time_ms += elapsed_ms

            logger.debug(f"GDI 屏幕截图成功: {img_bgr.shape}, {elapsed_ms:.1f}ms")
            return img_bgr
        except Exception as e:
            logger.error(f"GDI 屏幕截图失败: {e}")
            with self.lock:
                self.stats.total_captures += 1
                self.stats.failed_captures += 1
            return None
        finally:
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
                if dc_screen:
                    win32gui.ReleaseDC(0, dc_screen)
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
        logger.debug(f"GDI 资源已清理: hwnd={hwnd}")

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


def get_global_capture() -> GDICapture:
    """获取全局截图器实例"""
    global _global_capture
    if _global_capture is None:
        with _global_lock:
            if _global_capture is None:
                _global_capture = GDICapture()
    return _global_capture


def capture_window_gdi(
    hwnd: int,
    client_area_only: bool = True
) -> Optional[np.ndarray]:
    """
    GDI 窗口截图（全局接口）

    Args:
        hwnd: 窗口句柄
        client_area_only: 是否只捕获客户区

    Returns:
        BGR 格式的 numpy 数组
    """
    capture = get_global_capture()
    return capture.capture_window(hwnd, client_area_only)


def capture_screen_gdi(
    region: Optional[Tuple[int, int, int, int]] = None,
) -> Optional[np.ndarray]:
    """GDI 屏幕截图（全局接口）。"""
    capture = get_global_capture()
    return capture.capture_screen(region)


def get_pixel_color_gdi(
    hwnd: int,
    x: int,
    y: int,
    client_coords: bool = True
) -> Optional[Tuple[int, int, int]]:
    """获取像素颜色（全局接口）"""
    capture = get_global_capture()
    return capture.get_pixel_color(hwnd, x, y, client_coords)


def cleanup_gdi(hwnd: int = None):
    """清理资源（全局接口）"""
    global _global_capture
    with _global_lock:
        capture = _global_capture
        if hwnd is None:
            _global_capture = None

    if capture:
        capture.cleanup(hwnd)


def clear_gdi_runtime_cache(hwnd: int = None):
    """软清理GDI运行时缓存（不销毁全局实例）。"""
    with _global_lock:
        capture = _global_capture
    if capture:
        capture.cleanup(hwnd)


def is_gdi_available() -> bool:
    """检查 GDI 是否可用"""
    return WIN32_AVAILABLE and CV2_AVAILABLE


if __name__ == "__main__":
    import time

    logging.basicConfig(level=logging.DEBUG)

    logger.info("=" * 60)
    logger.info("GDI 截图引擎测试")
    logger.info("=" * 60)

    if not is_gdi_available():
        logger.info("[ERROR] GDI 不可用")
        exit(1)

    # 查找窗口
    hwnd = win32gui.FindWindow(None, "二重螺旋")
    if not hwnd:
        logger.info("[ERROR] 未找到测试窗口")
        exit(1)

    logger.info(f"\n目标窗口: HWND={hwnd}")

    # 测试截图
    logger.info("\n开始截图测试...")
    start = time.time()

    frame = capture_window_gdi(hwnd, client_area_only=True)

    elapsed = (time.time() - start) * 1000
    logger.info(f"截图耗时: {elapsed:.1f}ms")

    if frame is not None:
        logger.info(f"帧尺寸: {frame.shape}")
        if CV2_AVAILABLE:
            cv2.imwrite("gdi_test.png", frame)
            logger.info("已保存: gdi_test.png")
    else:
        logger.info("[ERROR] 截图失败")

    # 统计信息
    capture = get_global_capture()
    stats = capture.get_stats()
    logger.info("\n统计信息:")
    for key, value in stats.items():
        logger.info(f"  {key}: {value}")

    cleanup_gdi()
    logger.info("\n测试完成")
