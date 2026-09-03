# -*- coding: utf-8 -*-
"""原生 Win32 分层覆盖窗口：在目标窗口上方绘制检测框，不依赖 Qt。

由 YOLO 检测任务在“原生叠加层”模式下使用；本模块只负责窗口与 GDI+ 绘制，不感知任务逻辑。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _get_native_overlay_metrics(hwnd: int) -> Optional[Dict[str, Any]]:
    try:
        import win32gui

        hwnd_int = int(hwnd)
        if hwnd_int <= 0 or not win32gui.IsWindow(hwnd_int):
            return None

        client_rect = win32gui.GetClientRect(hwnd_int)
        if not client_rect or len(client_rect) != 4:
            return None

        client_width = max(0, int(client_rect[2]) - int(client_rect[0]))
        client_height = max(0, int(client_rect[3]) - int(client_rect[1]))
        if client_width <= 0 or client_height <= 0:
            return None

        left_top = win32gui.ClientToScreen(hwnd_int, (0, 0))
        right_bottom = win32gui.ClientToScreen(hwnd_int, (client_width, client_height))
        left = int(left_top[0])
        top = int(left_top[1])
        right = max(left + 1, int(right_bottom[0]))
        bottom = max(top + 1, int(right_bottom[1]))

        return {
            "native_rect": (left, top, right, bottom),
            "physical_size": (
                max(1, right - left),
                max(1, bottom - top),
            ),
        }
    except Exception:
        return None


class Win32OverlayWindow:
    """Persistent Win32 layered overlay with reusable buffers."""

    _instance = None
    _class_registered = False
    _wnd_proc = None

    def __init__(self):
        self._hwnd_overlay = None
        self._gdiplus_token = None
        self._winapi = None
        self._screen_dc = None
        self._mem_dc = None
        self._bitmap = None
        self._old_bitmap = None
        self._bits = None
        self._width = 0
        self._height = 0
        self._stride = 0
        self._buffer_size = 0
        self._buffer_valid = False
        self._last_present_rect = None
        self._last_frame_shape = None
        self._fallback_last_boxes = []
        self._pen_cache = {}
        self._brush_cache = {}
        self._color_cache = {}
        self._font_family = None
        self._font = None
        self._init_gdiplus()
        self._init_winapi_prototypes()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _init_gdiplus(self):
        try:
            import ctypes

            class GdiplusStartupInput(ctypes.Structure):
                _fields_ = [
                    ("GdiplusVersion", ctypes.c_uint32),
                    ("DebugEventCallback", ctypes.c_void_p),
                    ("SuppressBackgroundThread", ctypes.c_int),
                    ("SuppressExternalCodecs", ctypes.c_int),
                ]

            gdiplus = ctypes.windll.gdiplus
            startup_input = GdiplusStartupInput()
            startup_input.GdiplusVersion = 1
            token = ctypes.c_ulong()
            gdiplus.GdiplusStartup(ctypes.byref(token), ctypes.byref(startup_input), None)
            self._gdiplus_token = token.value
        except Exception as e:
            logger.debug(f"GDI+ 初始化失败：{e}")

    def _init_winapi_prototypes(self):
        try:
            import ctypes
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
            gdiplus = ctypes.WinDLL("gdiplus", use_last_error=True)

            user32.GetDC.argtypes = [ctypes.c_void_p]
            user32.GetDC.restype = ctypes.c_void_p
            user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            user32.ReleaseDC.restype = ctypes.c_int

            user32.UpdateLayeredWindow.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                ctypes.c_uint32,
            ]
            user32.UpdateLayeredWindow.restype = ctypes.c_int

            gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
            gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
            gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
            gdi32.DeleteDC.restype = ctypes.c_int
            gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            gdi32.SelectObject.restype = ctypes.c_void_p
            gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
            gdi32.DeleteObject.restype = ctypes.c_int
            gdi32.CreateDIBSection.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                ctypes.c_void_p, ctypes.c_uint32,
            ]
            gdi32.CreateDIBSection.restype = ctypes.c_void_p

            self._winapi = {"user32": user32, "gdi32": gdi32, "gdiplus": gdiplus}
        except Exception as e:
            logger.debug(f"WinAPI 初始化失败：{e}")
            self._winapi = None

    def _ensure_window_class(self):
        if Win32OverlayWindow._class_registered:
            return True
        try:
            import win32gui
            import win32api
            import win32con

            def wnd_proc(hwnd, msg, wparam, lparam):
                if msg == win32con.WM_DESTROY:
                    return 0
                return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

            Win32OverlayWindow._wnd_proc = wnd_proc
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = Win32OverlayWindow._wnd_proc
            wc.lpszClassName = "YOLOOverlayClass"
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
            wc.hbrBackground = 0

            try:
                win32gui.RegisterClass(wc)
            except Exception:
                pass

            Win32OverlayWindow._class_registered = True
            return True
        except Exception as e:
            logger.debug(f"悬浮窗类注册失败：{e}")
            return False

    def _release_dib(self):
        try:
            if not self._winapi:
                return
            gdi32 = self._winapi["gdi32"]
            user32 = self._winapi["user32"]

            if self._mem_dc and self._old_bitmap:
                gdi32.SelectObject(self._mem_dc, self._old_bitmap)
                self._old_bitmap = None
            if self._bitmap:
                gdi32.DeleteObject(self._bitmap)
                self._bitmap = None
            if self._mem_dc:
                gdi32.DeleteDC(self._mem_dc)
                self._mem_dc = None
            if self._screen_dc:
                user32.ReleaseDC(0, self._screen_dc)
                self._screen_dc = None
        finally:
            self._bits = None
            self._width = 0
            self._height = 0
            self._stride = 0
            self._buffer_size = 0
            self._buffer_valid = False

    def _ensure_dib(self, width: int, height: int) -> bool:
        if width <= 0 or height <= 0:
            return False
        if self._mem_dc and self._width == width and self._height == height:
            return True
        if not self._winapi:
            return False

        import ctypes

        self._release_dib()
        user32 = self._winapi["user32"]
        gdi32 = self._winapi["gdi32"]

        self._screen_dc = user32.GetDC(0)
        self._mem_dc = gdi32.CreateCompatibleDC(self._screen_dc)
        if not self._mem_dc:
            if self._screen_dc:
                user32.ReleaseDC(0, self._screen_dc)
                self._screen_dc = None
            return False

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", ctypes.c_uint32),
                ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16),
                ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32),
                ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32),
                ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32),
            ]

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = width
        bmi.biHeight = -height
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0

        bits = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(
            self._mem_dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0
        )
        if not bitmap:
            self._release_dib()
            return False

        self._old_bitmap = gdi32.SelectObject(self._mem_dc, bitmap)
        self._bitmap = bitmap
        self._bits = bits
        self._width = width
        self._height = height
        self._stride = width * 4
        self._buffer_size = self._stride * height
        self._buffer_valid = False
        return True

    def _ensure_font(self):
        if self._font is not None or not self._winapi:
            return

        import ctypes
        gdiplus = self._winapi["gdiplus"]

        font_family = ctypes.c_void_p()
        gdiplus.GdipCreateFontFamilyFromName(
            ctypes.c_wchar_p("Arial"), None, ctypes.byref(font_family)
        )
        if not font_family:
            return

        font = ctypes.c_void_p()
        gdiplus.GdipCreateFont(font_family, ctypes.c_float(12.0), 0, 2, ctypes.byref(font))
        if font:
            self._font_family = font_family
            self._font = font
        else:
            gdiplus.GdipDeleteFontFamily(font_family)

    def _get_color(self, class_name: str) -> int:
        if class_name in self._color_cache:
            return self._color_cache[class_name]
        palette = [0xFF00FF00, 0xFFFF0000, 0xFF0000FF, 0xFFFFFF00, 0xFFFF00FF, 0xFF00FFFF]
        color = palette[len(self._color_cache) % len(palette)]
        self._color_cache[class_name] = color
        return color

    def _get_pen(self, color: int):
        if color in self._pen_cache:
            return self._pen_cache[color]
        if not self._winapi:
            return None
        import ctypes
        gdiplus = self._winapi["gdiplus"]
        pen = ctypes.c_void_p()
        gdiplus.GdipCreatePen1(ctypes.c_uint32(color), ctypes.c_float(2.0), 2, ctypes.byref(pen))
        if pen:
            self._pen_cache[color] = pen
        return pen

    def _get_brush(self, color: int):
        if color in self._brush_cache:
            return self._brush_cache[color]
        if not self._winapi:
            return None
        import ctypes
        gdiplus = self._winapi["gdiplus"]
        brush = ctypes.c_void_p()
        gdiplus.GdipCreateSolidFill(ctypes.c_uint32(color), ctypes.byref(brush))
        if brush:
            self._brush_cache[color] = brush
        return brush

    def _draw(self, detections: List, scale_x: float, scale_y: float):
        if not self._winapi or not self._mem_dc or not self._bits:
            return

        import ctypes
        gdiplus = self._winapi["gdiplus"]

        ctypes.memset(self._bits, 0, self._buffer_size)

        graphics = ctypes.c_void_p()
        gdiplus.GdipCreateFromHDC(self._mem_dc, ctypes.byref(graphics))
        gdiplus.GdipSetSmoothingMode(graphics, 4)

        self._ensure_font()

        class RectF(ctypes.Structure):
            _fields_ = [
                ("X", ctypes.c_float),
                ("Y", ctypes.c_float),
                ("Width", ctypes.c_float),
                ("Height", ctypes.c_float),
            ]

        for det in detections:
            class_name = str(det.get("class_name", ""))
            confidence = float(det.get("confidence", 0.0) or 0.0)
            color = self._get_color(class_name)
            pen = self._get_pen(color)
            brush = self._get_brush(color)
            if not pen:
                continue

            x1 = max(0, min(int(float(det.get("x1", 0)) * scale_x), self._width - 1))
            y1 = max(0, min(int(float(det.get("y1", 0)) * scale_y), self._height - 1))
            x2 = max(0, min(int(float(det.get("x2", 0)) * scale_x), self._width - 1))
            y2 = max(0, min(int(float(det.get("y2", 0)) * scale_y), self._height - 1))
            w = max(1, x2 - x1)
            h = max(1, y2 - y1)

            gdiplus.GdipDrawRectangleI(graphics, pen, x1, y1, w, h)

            if self._font and brush:
                label = f"{class_name} {confidence:.2f}"
                rect = RectF(float(x1), float(max(0, y1 - 16)), 220.0, 20.0)
                gdiplus.GdipDrawString(
                    graphics, ctypes.c_wchar_p(label), -1, self._font, ctypes.byref(rect), None, brush
                )

        gdiplus.GdipDeleteGraphics(graphics)
        self._buffer_valid = True

    def _present(self, left: int, top: int, width: int, height: int) -> bool:
        if not self._winapi or not self._mem_dc or not self._hwnd_overlay:
            return False
        import ctypes
        user32 = self._winapi["user32"]

        class BLENDFUNCTION(ctypes.Structure):
            _fields_ = [
                ("BlendOp", ctypes.c_byte),
                ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte),
                ("AlphaFormat", ctypes.c_byte),
            ]

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class SIZE(ctypes.Structure):
            _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

        blend = BLENDFUNCTION()
        blend.BlendOp = 0
        blend.BlendFlags = 0
        blend.SourceConstantAlpha = 255
        blend.AlphaFormat = 1

        pt_src = POINT(0, 0)
        pt_dst = POINT(left, top)
        size = SIZE(width, height)

        result = user32.UpdateLayeredWindow(
            self._hwnd_overlay, self._screen_dc,
            ctypes.byref(pt_dst), ctypes.byref(size),
            self._mem_dc, ctypes.byref(pt_src),
            0, ctypes.byref(blend), 2
        )
        return result != 0

    def _draw_fallback_gdi(self, hwnd: int, detections: List, scale_x: float, scale_y: float):
        try:
            import win32gui
            import win32con

            hdc = win32gui.GetDC(hwnd)
            if not hdc:
                return

            pen = win32gui.CreatePen(win32con.PS_SOLID, 2, 0x00FF00)
            old_pen = win32gui.SelectObject(hdc, pen)
            old_rop2 = win32gui.SetROP2(hdc, win32con.R2_NOTXORPEN)

            # Erase previous boxes (XOR) then draw new ones.
            for box in self._fallback_last_boxes:
                win32gui.Rectangle(hdc, box[0], box[1], box[2], box[3])

            new_boxes = []
            for det in detections:
                x1 = int(float(det.get("x1", 0)) * scale_x)
                y1 = int(float(det.get("y1", 0)) * scale_y)
                x2 = int(float(det.get("x2", 0)) * scale_x)
                y2 = int(float(det.get("y2", 0)) * scale_y)
                win32gui.Rectangle(hdc, x1, y1, x2, y2)
                new_boxes.append((x1, y1, x2, y2))
            self._fallback_last_boxes = new_boxes

            win32gui.SelectObject(hdc, old_pen)
            win32gui.SetROP2(hdc, old_rop2)
            win32gui.DeleteObject(pen)
            win32gui.ReleaseDC(hwnd, hdc)
        except Exception as e:
            logger.debug(f"GDI 回退绘制失败：{e}")

    def _promote_overlay_window(self, left: int, top: int, width: int, height: int) -> None:
        if not self._hwnd_overlay:
            return
        try:
            import win32gui
            import win32con

            win32gui.SetWindowPos(
                self._hwnd_overlay,
                win32con.HWND_TOPMOST,
                int(left),
                int(top),
                max(1, int(width)),
                max(1, int(height)),
                win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW,
            )
        except Exception:
            pass

    def render(self, hwnd: int, detections: List, frame_shape: Tuple, force_redraw: bool = False):
        try:
            import win32gui
            import win32con
            import win32api

            metrics = _get_native_overlay_metrics(hwnd)
            if not metrics:
                self.hide()
                return

            native_rect = metrics.get("native_rect")
            if not native_rect or len(native_rect) != 4:
                self.hide()
                return

            client_left, client_top, client_right, client_bottom = [int(v) for v in native_rect]
            client_w = max(0, client_right - client_left)
            client_h = max(0, client_bottom - client_top)

            if client_w <= 0 or client_h <= 0:
                self.hide()
                return

            scale_x, scale_y = 1.0, 1.0
            if frame_shape and len(frame_shape) >= 2:
                src_h, src_w = frame_shape[:2]
                if src_w and src_h:
                    scale_x = client_w / float(src_w)
                    scale_y = client_h / float(src_h)

            if not self._ensure_dib(client_w, client_h):
                self._draw_fallback_gdi(hwnd, detections, scale_x, scale_y)
                return

            if self._hwnd_overlay is None or not win32gui.IsWindow(self._hwnd_overlay):
                if not self._ensure_window_class():
                    self._draw_fallback_gdi(hwnd, detections, scale_x, scale_y)
                    return
                self._hwnd_overlay = win32gui.CreateWindowEx(
                    win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT |
                    win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE,
                    "YOLOOverlayClass", "",
                    win32con.WS_POPUP,
                    client_left, client_top, client_w, client_h,
                    0, 0, win32api.GetModuleHandle(None), None,
                )
                if not self._hwnd_overlay:
                    self._draw_fallback_gdi(hwnd, detections, scale_x, scale_y)
                    return
                self._promote_overlay_window(client_left, client_top, client_w, client_h)

            shape_changed = frame_shape != self._last_frame_shape
            if shape_changed:
                self._last_frame_shape = frame_shape

            if force_redraw or shape_changed or not self._buffer_valid:
                self._draw(detections, scale_x, scale_y)

            present_rect = (client_left, client_top, client_w, client_h)
            if force_redraw or self._last_present_rect != present_rect:
                if self._present(client_left, client_top, client_w, client_h):
                    self._promote_overlay_window(client_left, client_top, client_w, client_h)
                    win32gui.ShowWindow(self._hwnd_overlay, win32con.SW_SHOWNOACTIVATE)
                    self._last_present_rect = present_rect
                    self._fallback_last_boxes = []
                else:
                    self._draw_fallback_gdi(hwnd, detections, scale_x, scale_y)
        except Exception as e:
            logger.debug(f"悬浮层渲染失败：{e}")

    def hide(self):
        if self._hwnd_overlay:
            try:
                import win32gui
                import win32con
                win32gui.ShowWindow(self._hwnd_overlay, win32con.SW_HIDE)
            except Exception:
                pass
        self._last_present_rect = None
        self._buffer_valid = False

    def shutdown(self):
        self.hide()
        try:
            import win32gui
            if self._hwnd_overlay and win32gui.IsWindow(self._hwnd_overlay):
                win32gui.DestroyWindow(self._hwnd_overlay)
        except Exception:
            pass
        self._hwnd_overlay = None

        if self._winapi:
            gdiplus = self._winapi["gdiplus"]
            for pen in self._pen_cache.values():
                gdiplus.GdipDeletePen(pen)
            for brush in self._brush_cache.values():
                gdiplus.GdipDeleteBrush(brush)
            if self._font:
                gdiplus.GdipDeleteFont(self._font)
            if self._font_family:
                gdiplus.GdipDeleteFontFamily(self._font_family)
        self._pen_cache.clear()
        self._brush_cache.clear()
        self._color_cache.clear()
        self._font = None
        self._font_family = None
        self._release_dib()
        try:
            self.__class__._instance = None
        except Exception:
            pass

    def __del__(self):
        self.shutdown()
        if self._gdiplus_token:
            try:
                import ctypes
                if self._winapi:
                    self._winapi["gdiplus"].GdiplusShutdown(self._gdiplus_token)
                else:
                    ctypes.windll.gdiplus.GdiplusShutdown(self._gdiplus_token)
            except Exception:
                pass
