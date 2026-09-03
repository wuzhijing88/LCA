#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PrintWindow 截图引擎

借鉴 OP gdi/gdi2：UpdateWindow 后重试、flags=0 兼容、GetDIBits 读图。
仍优先 PW_RENDERFULLCONTENT；失败不回退 BitBlt / 其他引擎。
"""

import ctypes
import logging
import threading
from ctypes import wintypes
from typing import Optional, Tuple

import cv2
import numpy as np
import win32gui
import win32ui

from utils.capture.hwnd_capture_utils import CaptureStats, crop_frame_by_hwnd, get_window_rect_with_dwm, resolve_capture_target

logger = logging.getLogger(__name__)

PW_RENDERFULLCONTENT = 0x00000002
BI_RGB = 0
DIB_RGB_COLORS = 0
BLACKNESS = 0x00000042

_last_failure_reason = ""
_last_failure_lock = threading.Lock()


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


def _set_last_failure_reason(reason: str) -> None:
    global _last_failure_reason
    with _last_failure_lock:
        _last_failure_reason = str(reason or "").strip()


def get_last_printwindow_capture_failure_reason() -> str:
    with _last_failure_lock:
        return str(_last_failure_reason or "")


def _user32():
    lib = ctypes.WinDLL("user32", use_last_error=True)
    lib.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    lib.PrintWindow.restype = wintypes.BOOL
    lib.UpdateWindow.argtypes = [wintypes.HWND]
    lib.UpdateWindow.restype = wintypes.BOOL
    return lib


def _gdi32():
    lib = ctypes.WinDLL("gdi32", use_last_error=True)
    lib.GetDIBits.argtypes = [
        wintypes.HDC,
        wintypes.HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.POINTER(BITMAPINFO),
        wintypes.UINT,
    ]
    lib.GetDIBits.restype = ctypes.c_int
    lib.GetBitmapBits.argtypes = [wintypes.HBITMAP, ctypes.c_long, ctypes.c_void_p]
    lib.GetBitmapBits.restype = ctypes.c_long
    lib.PatBlt.argtypes = [
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.DWORD,
    ]
    lib.PatBlt.restype = wintypes.BOOL
    return lib


def print_window_with_op_retry(hwnd: int, hdc: int, user32=None) -> bool:
    """先 RENDERFULLCONTENT，失败则 UpdateWindow 再试，最后 flags=0。不走 BitBlt。"""
    lib = user32 if user32 is not None else _user32()
    target = int(hwnd)
    target_dc = int(hdc)

    if lib.PrintWindow(target, target_dc, PW_RENDERFULLCONTENT):
        return True

    try:
        lib.UpdateWindow(target)
    except Exception:
        logger.debug("UpdateWindow 失败，继续 PrintWindow 重试", exc_info=True)

    if lib.PrintWindow(target, target_dc, PW_RENDERFULLCONTENT):
        logger.debug("PrintWindow 在 UpdateWindow 后成功: hwnd=%s", target)
        return True

    if lib.PrintWindow(target, target_dc, 0):
        logger.debug("PrintWindow 以 flags=0 成功: hwnd=%s", target)
        return True
    return False


def _new_bitmap_info(width: int, height: int, top_down: bool) -> BITMAPINFO:
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = int(width)
    bmi.bmiHeader.biHeight = -int(height) if top_down else int(height)
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB
    bmi.bmiHeader.biSizeImage = int(width) * int(height) * 4
    return bmi


def read_printwindow_bitmap_bgra(
    hdc: int,
    hbitmap: int,
    width: int,
    height: int,
    gdi32=None,
) -> Optional[np.ndarray]:
    """优先 GetDIBits；仅当读同一张 HBITMAP 失败时才用 GetBitmapBits。"""
    if width <= 0 or height <= 0:
        return None

    lib = gdi32 if gdi32 is not None else _gdi32()
    nbytes = int(width) * int(height) * 4
    buf = (ctypes.c_ubyte * nbytes)()
    buf_ptr = ctypes.cast(buf, ctypes.c_void_p)

    def _getdibits(top_down: bool) -> bool:
        bmi = _new_bitmap_info(width, height, top_down)
        lines = lib.GetDIBits(
            int(hdc),
            int(hbitmap),
            0,
            int(height),
            buf_ptr,
            ctypes.byref(bmi),
            DIB_RGB_COLORS,
        )
        return int(lines or 0) == int(height)

    if _getdibits(True):
        return np.frombuffer(buf, dtype=np.uint8).reshape((height, width, 4)).copy()

    if _getdibits(False):
        img = np.frombuffer(buf, dtype=np.uint8).reshape((height, width, 4)).copy()
        return np.ascontiguousarray(np.flipud(img))

    bits = lib.GetBitmapBits(int(hbitmap), nbytes, buf_ptr)
    if int(bits or 0) != nbytes:
        return None
    return np.frombuffer(buf, dtype=np.uint8).reshape((height, width, 4)).copy()


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

    def _auto_fix_black_borders(self, img_bgr: np.ndarray, target_size: Tuple[int, int] = None) -> np.ndarray:
        """裁掉黑边，保持像素比例；不再强制 resize 回原尺寸。"""
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
            # 只裁剪黑边，禁止再拉回原尺寸，否则上下/左右去边后会被非等比拉伸。
            return img_bgr[y:y + bh, x:x + bw].copy()
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
        old_bitmap = None
        capture_lock_acquired = False
        target_info = resolve_capture_target(hwnd)
        target_hwnd = target_info.target_hwnd
        capture_hwnd = target_info.capture_hwnd

        try:
            self._capture_lock.acquire()
            capture_lock_acquired = True

            if not win32gui.IsWindow(target_hwnd) or not win32gui.IsWindow(capture_hwnd):
                _set_last_failure_reason("无效的窗口句柄")
                logger.error(f"无效的窗口句柄: {target_hwnd}")
                return None

            if win32gui.IsIconic(capture_hwnd) or win32gui.IsIconic(target_hwnd):
                _set_last_failure_reason("窗口已最小化，PrintWindow 无法抓取最小化窗口")
                logger.error(f"窗口已最小化: target={target_hwnd}, capture={capture_hwnd}")
                return None

            rect = win32gui.GetWindowRect(capture_hwnd)
            window_rect: Optional[Tuple[int, int, int, int]] = (
                int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
            )
            dwm_rect: Optional[Tuple[int, int, int, int]] = get_window_rect_with_dwm(capture_hwnd)
            width = int(window_rect[2] - window_rect[0])
            height = int(window_rect[3] - window_rect[1])

            if width <= 0 or height <= 0:
                _set_last_failure_reason(f"无效的窗口尺寸: {width}x{height}")
                logger.error(f"无效的窗口尺寸: {width}x{height}")
                return None

            # 进程启动阶段已经声明 Per-Monitor DPI awareness。
            # 这里再手动乘 DPI 会把 PrintWindow 抓到的窗口放大，导致开发/打包行为分叉。
            capture_width = width
            capture_height = height

            dc_window = win32gui.GetWindowDC(capture_hwnd)
            dc_mem = win32ui.CreateDCFromHandle(dc_window)
            dc_compatible = dc_mem.CreateCompatibleDC()

            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(dc_mem, capture_width, capture_height)
            old_bitmap = dc_compatible.SelectObject(bitmap)
            mem_hdc = dc_compatible.GetSafeHdc()

            try:
                _gdi32().PatBlt(int(mem_hdc), 0, 0, capture_width, capture_height, BLACKNESS)
            except Exception:
                logger.debug("PrintWindow 清空位图失败，继续抓图", exc_info=True)

            if not print_window_with_op_retry(capture_hwnd, mem_hdc):
                _set_last_failure_reason(
                    f"PrintWindow 调用失败: hwnd={capture_hwnd}（已重试 UpdateWindow 与 flags=0，未回退 BitBlt）"
                )
                logger.error(f"PrintWindow 调用失败: hwnd={capture_hwnd}")
                return None

            if old_bitmap is not None:
                try:
                    dc_compatible.SelectObject(old_bitmap)
                except Exception:
                    logger.debug("PrintWindow 还原位图失败", exc_info=True)

            img = read_printwindow_bitmap_bgra(
                hdc=int(mem_hdc),
                hbitmap=int(bitmap.GetHandle()),
                width=capture_width,
                height=capture_height,
            )
            if img is None:
                _set_last_failure_reason("无法读取 PrintWindow 位图像素")
                logger.error(f"PrintWindow 读位图失败: hwnd={capture_hwnd}")
                return None

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
                _set_last_failure_reason(
                    f"PrintWindow 句柄裁剪失败: target={target_hwnd}, capture={capture_hwnd}, client={client_area_only}"
                )
                logger.error(
                    f"PrintWindow 句柄裁剪失败: target={target_hwnd}, capture={capture_hwnd}, client={client_area_only}"
                )
                return None

            if self.auto_fix_black_borders:
                img_bgr = self._auto_fix_black_borders(img_bgr)

            elapsed_ms = (time.time() - start_time) * 1000
            with self.lock:
                self.stats.total_captures += 1
                self.stats.success_captures += 1
                self.stats.total_time_ms += elapsed_ms

            _set_last_failure_reason("")
            logger.debug(f"PrintWindow 截图成功: {img_bgr.shape}, {elapsed_ms:.1f}ms")
            return img_bgr

        except Exception as e:
            _set_last_failure_reason(f"{type(e).__name__}: {e}")
            logger.error(f"PrintWindow 截图失败: {e}")
            with self.lock:
                self.stats.total_captures += 1
                self.stats.failed_captures += 1
            return None

        finally:
            try:
                if dc_compatible is not None and old_bitmap is not None:
                    dc_compatible.SelectObject(old_bitmap)
            except Exception:
                pass

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
