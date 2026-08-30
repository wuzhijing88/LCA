# -*- coding: utf-8 -*-
"""加载官方 OP C API / COM，提供绑定窗口和取帧。"""

from __future__ import annotations

import ctypes
import logging
import os
import struct
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from utils.app_paths import get_app_root
from utils.capture.engine_ids import iter_op_capture_display_candidates

logger = logging.getLogger(__name__)

# C intptr_t / HWND：Python 未提供 ctypes.c_intptr
_C_INTPTR = ctypes.c_ssize_t

_CAPI_DLL_NAMES = (
    "op_c_api.dll",
    "op_c_api_x64.dll",
    "op_c_api_x86.dll",
    "op_capi.dll",
    "op_c_api_amd64.dll",
)
_RUNTIME_LOCK = threading.RLock()
_CACHED_AVAILABLE: Optional[bool] = None
_CACHED_DIR: Optional[Path] = None


def decode_op_bmp(data: bytes) -> Optional[np.ndarray]:
    raw = bytes(data or b"")
    if len(raw) < 14:
        return None
    try:
        import cv2

        frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        return None
    if frame is None or frame.size == 0:
        return None
    return np.ascontiguousarray(frame)


def decode_op_bgra(data: bytes, width: int, height: int) -> Optional[np.ndarray]:
    try:
        w = int(width)
        h = int(height)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    raw = bytes(data or b"")
    for channels in (4, 3):
        expected = w * h * channels
        if len(raw) < expected:
            continue
        try:
            image = np.frombuffer(raw, dtype=np.uint8, count=expected).reshape((h, w, channels))
        except ValueError:
            continue
        bgr = image[:, :, :3]
        return np.ascontiguousarray(bgr)
    return None


def _candidate_runtime_dirs() -> list[Path]:
    dirs: list[Path] = []
    env_dir = str(os.environ.get("LCA_OP_DIR") or "").strip()
    if env_dir:
        dirs.append(Path(env_dir))
    try:
        app_root = Path(get_app_root())
    except Exception:
        app_root = Path(__file__).resolve().parents[2]
    dirs.extend(
        (
            app_root / "tools" / "op",
            app_root / "vendor" / "op",
            Path(__file__).resolve().parents[2] / "tools" / "op",
            Path(__file__).resolve().parents[2] / "vendor" / "op",
        )
    )
    unique: list[Path] = []
    seen = set()
    for item in dirs:
        try:
            resolved = item.resolve()
        except OSError:
            continue
        key = os.path.normcase(str(resolved))
        if key in seen:
            continue
        seen.add(key)
        unique.append(resolved)
    return unique


def find_op_runtime_dir() -> Optional[Path]:
    global _CACHED_DIR
    with _RUNTIME_LOCK:
        if _CACHED_DIR is not None and _CACHED_DIR.is_dir():
            return _CACHED_DIR
        for directory in _candidate_runtime_dirs():
            if not directory.is_dir():
                continue
            for name in _CAPI_DLL_NAMES:
                if (directory / name).is_file():
                    _CACHED_DIR = directory
                    return directory
            if any(path.is_file() and path.suffix.lower() == ".dll" for path in directory.iterdir()):
                _CACHED_DIR = directory
                return directory
        return None


def find_op_capi_dll() -> Optional[Path]:
    runtime_dir = find_op_runtime_dir()
    if runtime_dir is None:
        return None
    for name in _CAPI_DLL_NAMES:
        candidate = runtime_dir / name
        if candidate.is_file():
            return candidate
    return None


def is_op_runtime_available() -> bool:
    global _CACHED_AVAILABLE
    with _RUNTIME_LOCK:
        if find_op_capi_dll() is not None:
            _CACHED_AVAILABLE = True
            return True
        if _CACHED_AVAILABLE is not None:
            return _CACHED_AVAILABLE
        try:
            import win32com.client

            win32com.client.Dispatch("op.opsoft")
            _CACHED_AVAILABLE = True
            return True
        except Exception:
            _CACHED_AVAILABLE = False
            return False


def reset_op_runtime_cache() -> None:
    global _CACHED_AVAILABLE, _CACHED_DIR
    with _RUNTIME_LOCK:
        _CACHED_AVAILABLE = None
        _CACHED_DIR = None


class OpClient:
    """官方 OP 客户端。优先 C API，其次已注册 COM。"""

    def __init__(self, backend=None):
        self._backend = backend
        self._owns_backend = backend is None
        self._lock = threading.RLock()
        self._bound_hwnd = 0
        self._bound_display = ""
        self._bound_mouse = ""
        self._bound_keypad = ""

    def _ensure_backend(self):
        if self._backend is not None:
            return self._backend
        capi_path = find_op_capi_dll()
        if capi_path is not None:
            self._backend = _CApiBackend(capi_path)
            return self._backend
        self._backend = _ComBackend()
        return self._backend

    @property
    def available(self) -> bool:
        try:
            self._ensure_backend()
            return True
        except Exception:
            return False

    @property
    def astar_available(self) -> bool:
        try:
            return bool(self._ensure_backend().has_astar)
        except Exception:
            return False

    def astar_find_path(
        self,
        map_width: int,
        map_height: int,
        cells,
        start: tuple[int, int],
        goal: tuple[int, int],
    ) -> Optional[list[tuple[int, int]]]:
        try:
            with self._lock:
                backend = self._ensure_backend()
                find_path = getattr(backend, "astar_find_path", None)
                if not callable(find_path):
                    return None
                path = find_path(
                    int(map_width),
                    int(map_height),
                    cells,
                    (int(start[0]), int(start[1])),
                    (int(goal[0]), int(goal[1])),
                )
                if not path:
                    return None
                return [(int(point[0]), int(point[1])) for point in path]
        except Exception:
            return None

    def bind(self, hwnd: int, display: str, mouse: Optional[str] = None, keypad: Optional[str] = None, mode: int = 0) -> bool:
        target = int(hwnd or 0)
        display_mode = str(display or "").strip()
        if target <= 0 or not display_mode:
            return False
        with self._lock:
            backend = self._ensure_backend()
            wanted_mouse = str(mouse or self._bound_mouse or "normal").strip() or "normal"
            wanted_keypad = str(keypad or self._bound_keypad or "normal").strip() or "normal"
            same_session = (
                self._bound_hwnd == target
                and self._bound_display == display_mode
                and self._bound_mouse == wanted_mouse
                and self._bound_keypad == wanted_keypad
                and backend.is_bind()
            )
            if same_session:
                return True
            if backend.is_bind():
                backend.unbind()
            if not backend.bind(target, display_mode, wanted_mouse, wanted_keypad, mode):
                self._bound_hwnd = 0
                self._bound_display = ""
                self._bound_mouse = ""
                self._bound_keypad = ""
                return False
            self._bound_hwnd = target
            self._bound_display = display_mode
            self._bound_mouse = wanted_mouse
            self._bound_keypad = wanted_keypad
            return True

    def unbind(self) -> None:
        with self._lock:
            backend = self._backend
            if backend is None:
                self._clear_bind_state()
                return
            try:
                backend.unbind()
            finally:
                self._clear_bind_state()

    def _clear_bind_state(self) -> None:
        self._bound_hwnd = 0
        self._bound_display = ""
        self._bound_mouse = ""
        self._bound_keypad = ""

    def ensure_input_bind(self, hwnd: int, display: str, mouse: str = "dx", keypad: str = "dx", mode: int = 0) -> bool:
        """绑定 DX 键鼠。优先官方推荐的 display=normal + mouse/keypad=dx，再回退其它 display。"""
        wanted_mouse = str(mouse or "dx").strip() or "dx"
        wanted_keypad = str(keypad or "dx").strip() or "dx"
        preferred = str(display or "").strip() or "normal"
        # wiki 示例：BindWindow(hwnd, "normal", "dx", "dx", 0)
        # 截图引擎的 dx.d3d* 常与 mouse=dx 组合失败（ERROR_INVALID_PARAMETER=87）
        candidates: list[str] = []
        for item in (
            "normal",
            preferred,
            "gdi",
            "normal.wgc",
            "gdi2",
            "dx",
            "dx2",
            "dx.d3d11",
        ):
            key = str(item or "").strip()
            if key and key not in candidates:
                candidates.append(key)
        modes: list[int] = []
        for bind_mode in (int(mode or 0), 0, 1):
            if bind_mode not in modes:
                modes.append(bind_mode)
        for display_mode in candidates:
            for bind_mode in modes:
                if self.bind(
                    hwnd,
                    display_mode,
                    mouse=wanted_mouse,
                    keypad=wanted_keypad,
                    mode=bind_mode,
                ):
                    if display_mode != preferred or bind_mode != int(mode or 0):
                        logger.info(
                            "OP DX 输入绑定成功（回退）: hwnd=%s display=%s mode=%s",
                            hwnd,
                            display_mode,
                            bind_mode,
                        )
                    return True
        logger.error(
            "OP BindWindow(mouse=%s, keypad=%s) 全部 display 均失败: hwnd=%s preferred=%s",
            wanted_mouse,
            wanted_keypad,
            hwnd,
            preferred,
        )
        return False

    def move_to(self, x: int, y: int) -> bool:
        with self._lock:
            return bool(self._ensure_backend().move_to(int(x), int(y)))

    def mouse_click(self, button: str = "left") -> bool:
        with self._lock:
            return bool(self._ensure_backend().mouse_click(str(button or "left")))

    def mouse_double_click(self, button: str = "left") -> bool:
        with self._lock:
            return bool(self._ensure_backend().mouse_double_click(str(button or "left")))

    def mouse_down(self, button: str = "left") -> bool:
        with self._lock:
            return bool(self._ensure_backend().mouse_down(str(button or "left")))

    def mouse_up(self, button: str = "left") -> bool:
        with self._lock:
            return bool(self._ensure_backend().mouse_up(str(button or "left")))

    def wheel(self, delta: int) -> bool:
        with self._lock:
            return bool(self._ensure_backend().wheel(int(delta)))

    def key_down(self, vk_code: int) -> bool:
        with self._lock:
            return bool(self._ensure_backend().key_down(int(vk_code)))

    def key_up(self, vk_code: int) -> bool:
        with self._lock:
            return bool(self._ensure_backend().key_up(int(vk_code)))

    def key_press(self, vk_code: int) -> bool:
        with self._lock:
            return bool(self._ensure_backend().key_press(int(vk_code)))

    def key_press_str(self, text: str, delay: int = 30) -> bool:
        with self._lock:
            return bool(self._ensure_backend().key_press_str(str(text or ""), int(delay)))

    def last_error(self) -> int:
        try:
            return int(self._ensure_backend().last_error())
        except Exception:
            return 0

    def has_display_bind(self, hwnd: int, display: str) -> bool:
        target = int(hwnd or 0)
        preferred = str(display or "").strip()
        if target <= 0 or not preferred:
            return False
        try:
            backend = self._ensure_backend()
        except Exception:
            return False
        return (
            self._bound_hwnd == target
            and self._bound_display == preferred
            and bool(backend.is_bind())
        )

    def client_size(self, hwnd: int) -> tuple[int, int]:
        with self._lock:
            return self._ensure_backend().client_size(int(hwnd or 0))

    def set_yolo_engine(self, path: str, dll_name: str = "", argv: str = "") -> bool:
        with self._lock:
            return bool(self._ensure_backend().set_yolo_engine(str(path or ""), str(dll_name or ""), str(argv or "")))

    def yolo_detect(self, x1: int, y1: int, x2: int, y2: int, conf: float, iou: float):
        with self._lock:
            from utils.op.yolo import parse_yolo_detect_payload

            raw = self._ensure_backend().yolo_detect(int(x1), int(y1), int(x2), int(y2), float(conf), float(iou))
            return parse_yolo_detect_payload(raw)

    def grab_bound_bgr(self, hwnd: int):
        with self._lock:
            backend = self._ensure_backend()
            target = int(hwnd or 0)
            if target <= 0 or not backend.is_bind():
                return None
            width, height = backend.client_size(target)
            if width <= 0 or height <= 0:
                return None
            bmp = backend.screen_data_bmp(0, 0, width, height)
            frame = decode_op_bmp(bmp) if bmp else None
            if frame is not None:
                return frame
            raw = backend.screen_data(0, 0, width, height)
            return decode_op_bgra(raw, width, height) if raw else None

    def capture_bgr(self, hwnd: int, display: str, client_area_only: bool = True) -> Optional[np.ndarray]:
        _ = client_area_only
        with self._lock:
            target = int(hwnd or 0)
            preferred = str(display or "").strip()
            if target <= 0 or not preferred:
                return None
            backend = self._ensure_backend()

            def _grab() -> Optional[np.ndarray]:
                width, height = backend.client_size(target)
                if width <= 0 or height <= 0:
                    return None
                bmp = backend.screen_data_bmp(0, 0, width, height)
                frame = decode_op_bmp(bmp) if bmp else None
                if frame is not None:
                    return frame
                raw = backend.screen_data(0, 0, width, height)
                return decode_op_bgra(raw, width, height) if raw else None

            # 已是同 hwnd+display 的绑定（可含 mouse=dx）则直接取帧，避免打断 DX 键鼠。
            if (
                self._bound_hwnd == target
                and self._bound_display == preferred
                and backend.is_bind()
            ):
                frame = _grab()
                if frame is not None:
                    return frame

            candidates = iter_op_capture_display_candidates(preferred) or (preferred,)
            for display_mode in candidates:
                for bind_mode in (0, 1):
                    # 截图重绑必须显式 normal 键鼠，禁止沿用上一轮 sticky mouse=dx。
                    if not self.bind(
                        target,
                        display_mode,
                        mouse="normal",
                        keypad="normal",
                        mode=bind_mode,
                    ):
                        continue
                    frame = _grab()
                    if frame is not None:
                        if display_mode != preferred or bind_mode != 0:
                            logger.info(
                                "OP 截图绑定成功（兼容重试）: hwnd=%s display=%s mode=%s preferred=%s",
                                target,
                                display_mode,
                                bind_mode,
                                preferred,
                            )
                        return frame
            logger.error(
                "OP 截图 BindWindow/取帧失败: hwnd=%s preferred=%s last_error=%s tried=%s",
                target,
                preferred,
                self.last_error(),
                ",".join(candidates),
            )
            return None

    def close(self) -> None:
        with self._lock:
            try:
                self.unbind()
            except Exception:
                pass
            backend = self._backend
            self._backend = None
            if self._owns_backend and backend is not None:
                close_fn = getattr(backend, "close", None)
                if callable(close_fn):
                    try:
                        close_fn()
                    except Exception:
                        pass


class _CApiBackend:
    def __init__(self, dll_path: Path):
        self._dll_path = Path(dll_path)
        runtime_dir = self._dll_path.parent
        try:
            os.add_dll_directory(str(runtime_dir))
        except Exception:
            pass
        # 确保能解析同目录 tools.dll / op_x64.dll
        os.environ["PATH"] = str(runtime_dir) + os.pathsep + str(os.environ.get("PATH") or "")
        self._dll = ctypes.WinDLL(str(self._dll_path))
        self._handle = None
        self._bind_api()
        self._handle = self._dll.OpCreate()
        if not self._handle:
            raise RuntimeError(f"OpCreate 失败: {self._dll_path}")
        try:
            self._dll.OpSetPath(self._handle, str(runtime_dir))
        except Exception:
            logger.debug("OpSetPath 失败", exc_info=True)
        # 0=关闭弹窗，避免 BindWindow 失败时 MessageBox 卡住 Qt 主线程
        try:
            self.set_show_error_msg(0)
        except Exception:
            logger.debug("OpSetShowErrorMsg(0) 失败", exc_info=True)

    def _bind_api(self) -> None:
        dll = self._dll
        dll.OpCreate.restype = ctypes.c_void_p
        dll.OpCreate.argtypes = []
        dll.OpDestroy.restype = None
        dll.OpDestroy.argtypes = [ctypes.c_void_p]
        dll.OpSetPath.restype = ctypes.c_int
        dll.OpSetPath.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        dll.OpSetShowErrorMsg.restype = ctypes.c_int
        dll.OpSetShowErrorMsg.argtypes = [ctypes.c_void_p, ctypes.c_int]
        dll.OpGetLastError.restype = ctypes.c_int
        dll.OpGetLastError.argtypes = [ctypes.c_void_p]
        dll.OpBindWindow.restype = ctypes.c_int
        dll.OpBindWindow.argtypes = [
            ctypes.c_void_p,
            _C_INTPTR,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_int,
        ]
        dll.OpUnBindWindow.restype = ctypes.c_int
        dll.OpUnBindWindow.argtypes = [ctypes.c_void_p]
        dll.OpIsBind.restype = ctypes.c_int
        dll.OpIsBind.argtypes = [ctypes.c_void_p]
        dll.OpGetClientSize.restype = ctypes.c_int
        dll.OpGetClientSize.argtypes = [
            ctypes.c_void_p,
            _C_INTPTR,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
        dll.OpGetScreenDataBmp.restype = ctypes.c_uint64
        dll.OpGetScreenDataBmp.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
        dll.OpGetScreenData.restype = ctypes.c_uint64
        dll.OpGetScreenData.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        dll.OpMoveTo.restype = ctypes.c_int
        dll.OpMoveTo.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        for name in (
            "OpLeftClick",
            "OpLeftDoubleClick",
            "OpLeftDown",
            "OpLeftUp",
            "OpRightClick",
            "OpRightDoubleClick",
            "OpRightDown",
            "OpRightUp",
            "OpMiddleClick",
            "OpMiddleDoubleClick",
            "OpMiddleDown",
            "OpMiddleUp",
        ):
            fn = getattr(dll, name)
            fn.restype = ctypes.c_int
            fn.argtypes = [ctypes.c_void_p]
        for name in ("OpWheel", "OpKeyDown", "OpKeyUp", "OpKeyPress"):
            fn = getattr(dll, name)
            fn.restype = ctypes.c_int
            fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
        dll.OpKeyPressStr.restype = ctypes.c_int
        dll.OpKeyPressStr.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        self._has_astar = hasattr(dll, "OpAStarFindPath")
        # 该仓库没有可核实的 C 签名；只探测符号，禁止猜测 argtypes 后调用。
        self._has_yolo = hasattr(dll, "OpSetYoloEngine") and hasattr(dll, "OpYoloDetect")
        if self._has_yolo:
            dll.OpSetYoloEngine.restype = ctypes.c_int
            dll.OpSetYoloEngine.argtypes = [
                ctypes.c_void_p,
                ctypes.c_wchar_p,
                ctypes.c_wchar_p,
                ctypes.c_wchar_p,
            ]
            dll.OpYoloDetect.restype = ctypes.c_wchar_p
            dll.OpYoloDetect.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_double,
                ctypes.c_double,
            ]

    @property
    def has_astar(self) -> bool:
        return bool(getattr(self, "_has_astar", False))

    def astar_find_path(self, map_width: int, map_height: int, cells, start, goal):
        _ = map_width, map_height, cells, start, goal
        # 未找到本仓库可验证的 ABI 文档，不调用未知 ctypes 签名。
        return None

    def set_show_error_msg(self, show_type: int) -> bool:
        return int(self._dll.OpSetShowErrorMsg(self._handle, int(show_type))) == 1

    def last_error(self) -> int:
        try:
            return int(self._dll.OpGetLastError(self._handle))
        except Exception:
            return 0

    def bind(self, hwnd: int, display: str, mouse: str, keypad: str, mode: int) -> bool:
        ok = int(self._dll.OpBindWindow(self._handle, int(hwnd), display, mouse, keypad, int(mode))) == 1
        if not ok:
            logger.warning(
                "OP BindWindow 失败: hwnd=%s display=%s mouse=%s keypad=%s mode=%s last_error=%s",
                hwnd,
                display,
                mouse,
                keypad,
                mode,
                self.last_error(),
            )
        return ok

    def unbind(self) -> None:
        if self._handle:
            self._dll.OpUnBindWindow(self._handle)

    def is_bind(self) -> bool:
        if not self._handle:
            return False
        return int(self._dll.OpIsBind(self._handle)) == 1

    def client_size(self, hwnd: int) -> tuple[int, int]:
        width = ctypes.c_int(0)
        height = ctypes.c_int(0)
        ok = int(self._dll.OpGetClientSize(self._handle, int(hwnd), ctypes.byref(width), ctypes.byref(height)))
        if ok != 1:
            return 0, 0
        return int(width.value), int(height.value)

    def screen_data_bmp(self, x1: int, y1: int, x2: int, y2: int) -> bytes:
        size = ctypes.c_int(0)
        ret = ctypes.c_int(0)
        ptr = int(
            self._dll.OpGetScreenDataBmp(
                self._handle,
                int(x1),
                int(y1),
                int(x2),
                int(y2),
                ctypes.byref(size),
                ctypes.byref(ret),
            )
        )
        if ret.value != 1 or ptr == 0 or size.value <= 0:
            return b""
        return ctypes.string_at(ptr, int(size.value))

    def screen_data(self, x1: int, y1: int, x2: int, y2: int) -> bytes:
        ret = ctypes.c_int(0)
        ptr = int(
            self._dll.OpGetScreenData(
                self._handle,
                int(x1),
                int(y1),
                int(x2),
                int(y2),
                ctypes.byref(ret),
            )
        )
        if ret.value != 1 or ptr == 0:
            return b""
        width = max(0, int(x2) - int(x1))
        height = max(0, int(y2) - int(y1))
        nbytes = width * height * 4
        if nbytes <= 0:
            return b""
        return ctypes.string_at(ptr, nbytes)

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle:
            try:
                self._dll.OpDestroy(handle)
            except Exception:
                pass

    def move_to(self, x: int, y: int) -> bool:
        return int(self._dll.OpMoveTo(self._handle, int(x), int(y))) == 1

    def mouse_click(self, button: str) -> bool:
        return self._call0(_button_func(button, "click"))

    def mouse_double_click(self, button: str) -> bool:
        return self._call0(_button_func(button, "double"))

    def mouse_down(self, button: str) -> bool:
        return self._call0(_button_func(button, "down"))

    def mouse_up(self, button: str) -> bool:
        return self._call0(_button_func(button, "up"))

    def wheel(self, delta: int) -> bool:
        return int(self._dll.OpWheel(self._handle, int(delta))) == 1

    def key_down(self, vk_code: int) -> bool:
        return int(self._dll.OpKeyDown(self._handle, int(vk_code))) == 1

    def key_up(self, vk_code: int) -> bool:
        return int(self._dll.OpKeyUp(self._handle, int(vk_code))) == 1

    def key_press(self, vk_code: int) -> bool:
        return int(self._dll.OpKeyPress(self._handle, int(vk_code))) == 1

    def key_press_str(self, text: str, delay: int) -> bool:
        return int(self._dll.OpKeyPressStr(self._handle, str(text or ""), int(delay))) == 1

    def set_yolo_engine(self, path: str, dll_name: str, argv: str) -> bool:
        if not getattr(self, "_has_yolo", False):
            raise RuntimeError("当前 OP 运行库没有 YOLO 接口")
        return int(self._dll.OpSetYoloEngine(self._handle, str(path or ""), str(dll_name or ""), str(argv or ""))) == 1

    def yolo_detect(self, x1: int, y1: int, x2: int, y2: int, conf: float, iou: float):
        if not getattr(self, "_has_yolo", False):
            raise RuntimeError("当前 OP 运行库没有 YOLO 接口")
        text = self._dll.OpYoloDetect(
            self._handle,
            int(x1),
            int(y1),
            int(x2),
            int(y2),
            float(conf),
            float(iou),
        )
        return text or ""

    def _call0(self, name: str) -> bool:
        return int(getattr(self._dll, name)(self._handle)) == 1


class _ComBackend:
    def __init__(self):
        import win32com.client

        self._op = win32com.client.Dispatch("op.opsoft")
        runtime_dir = find_op_runtime_dir()
        if runtime_dir is not None:
            try:
                self._op.SetPath(str(runtime_dir))
            except Exception:
                logger.debug("COM SetPath 失败", exc_info=True)
        try:
            self.set_show_error_msg(0)
        except Exception:
            logger.debug("COM SetShowErrorMsg(0) 失败", exc_info=True)

    def set_show_error_msg(self, show_type: int) -> bool:
        return int(self._op.SetShowErrorMsg(int(show_type))) == 1

    def last_error(self) -> int:
        try:
            return int(self._op.GetLastError())
        except Exception:
            return 0

    def bind(self, hwnd: int, display: str, mouse: str, keypad: str, mode: int) -> bool:
        ok = int(self._op.BindWindow(int(hwnd), display, mouse, keypad, int(mode))) == 1
        if not ok:
            logger.warning(
                "OP COM BindWindow 失败: hwnd=%s display=%s mouse=%s keypad=%s mode=%s last_error=%s",
                hwnd,
                display,
                mouse,
                keypad,
                mode,
                self.last_error(),
            )
        return ok

    def unbind(self) -> None:
        self._op.UnBindWindow()

    def is_bind(self) -> bool:
        return int(self._op.IsBind()) == 1

    def client_size(self, hwnd: int) -> tuple[int, int]:
        result = self._op.GetClientSize(int(hwnd))
        width, height = _unpack_size(result)
        return width, height

    def screen_data_bmp(self, x1: int, y1: int, x2: int, y2: int) -> bytes:
        result = self._op.GetScreenDataBmp(int(x1), int(y1), int(x2), int(y2))
        return _unpack_bytes(result)

    def screen_data(self, x1: int, y1: int, x2: int, y2: int) -> bytes:
        result = self._op.GetScreenData(int(x1), int(y1), int(x2), int(y2))
        return _unpack_bytes(result)

    def close(self) -> None:
        try:
            self.unbind()
        except Exception:
            pass
        self._op = None

    def move_to(self, x: int, y: int) -> bool:
        return int(self._op.MoveTo(int(x), int(y))) == 1

    def mouse_click(self, button: str) -> bool:
        return self._call0(_com_button_func(button, "click"))

    def mouse_double_click(self, button: str) -> bool:
        return self._call0(_com_button_func(button, "double"))

    def mouse_down(self, button: str) -> bool:
        return self._call0(_com_button_func(button, "down"))

    def mouse_up(self, button: str) -> bool:
        return self._call0(_com_button_func(button, "up"))

    def wheel(self, delta: int) -> bool:
        return int(self._op.Wheel(int(delta))) == 1

    def key_down(self, vk_code: int) -> bool:
        return int(self._op.KeyDown(int(vk_code))) == 1

    def key_up(self, vk_code: int) -> bool:
        return int(self._op.KeyUp(int(vk_code))) == 1

    def key_press(self, vk_code: int) -> bool:
        return int(self._op.KeyPress(int(vk_code))) == 1

    def key_press_str(self, text: str, delay: int) -> bool:
        return int(self._op.KeyPressStr(str(text or ""), int(delay))) == 1

    def set_yolo_engine(self, path: str, dll_name: str, argv: str) -> bool:
        fn = getattr(self._op, "SetYoloEngine", None)
        if not callable(fn):
            raise RuntimeError("当前 OP 运行库没有 YOLO 接口")
        return int(fn(str(path or ""), str(dll_name or ""), str(argv or ""))) == 1

    def yolo_detect(self, x1: int, y1: int, x2: int, y2: int, conf: float, iou: float):
        fn = getattr(self._op, "YoloDetect", None)
        if not callable(fn):
            raise RuntimeError("当前 OP 运行库没有 YOLO 接口")
        return fn(int(x1), int(y1), int(x2), int(y2), float(conf), float(iou))

    def _call0(self, name: str) -> bool:
        return int(getattr(self._op, name)()) == 1


_BUTTON_FUNCS = {
    ("left", "click"): "OpLeftClick",
    ("left", "double"): "OpLeftDoubleClick",
    ("left", "down"): "OpLeftDown",
    ("left", "up"): "OpLeftUp",
    ("right", "click"): "OpRightClick",
    ("right", "double"): "OpRightDoubleClick",
    ("right", "down"): "OpRightDown",
    ("right", "up"): "OpRightUp",
    ("middle", "click"): "OpMiddleClick",
    ("middle", "double"): "OpMiddleDoubleClick",
    ("middle", "down"): "OpMiddleDown",
    ("middle", "up"): "OpMiddleUp",
}
_COM_BUTTON_FUNCS = {
    (button, action): name[2:]
    for (button, action), name in _BUTTON_FUNCS.items()
}


def _normalize_button(button: str) -> str:
    name = str(button or "left").strip().lower()
    if name in {"left", "right", "middle"}:
        return name
    return "left"


def _button_func(button: str, action: str) -> str:
    return _BUTTON_FUNCS[(_normalize_button(button), action)]


def _com_button_func(button: str, action: str) -> str:
    return _COM_BUTTON_FUNCS[(_normalize_button(button), action)]


def _unpack_size(result) -> tuple[int, int]:
    if isinstance(result, (tuple, list)):
        if len(result) >= 3:
            return int(result[-2] or 0), int(result[-1] or 0)
        if len(result) == 2:
            return int(result[0] or 0), int(result[1] or 0)
    return 0, 0


def _unpack_bytes(result) -> bytes:
    if result is None:
        return b""
    if isinstance(result, (bytes, bytearray, memoryview)):
        return bytes(result)
    if isinstance(result, (tuple, list)):
        for item in reversed(result):
            packed = _unpack_bytes(item)
            if packed:
                return packed
        return b""
    if isinstance(result, str):
        try:
            return result.encode("latin1")
        except Exception:
            return b""
    if isinstance(result, int) and result > 0:
        try:
            return struct.pack("P", result)
        except Exception:
            return b""
    return b""
