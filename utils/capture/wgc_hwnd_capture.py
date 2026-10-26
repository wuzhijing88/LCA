#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import math
import numpy as np
import time
import threading
import os
from typing import Optional, Tuple
from dataclasses import dataclass

from utils.capture.wgc_capture_policy import (
    resolve_wgc_capture_hwnd,
    should_crop_wgc_as_child,
    should_force_static_window_rebuild,
)
from utils.window.hwnd_utils import as_hwnd

logger = logging.getLogger(__name__)

# WGC完整销毁重建闸门：clear=重建中，set=可执行截图任务
_wgc_rebuild_gate = threading.Event()
_wgc_rebuild_gate.set()
_wgc_rebuild_state_lock = threading.Lock()
_wgc_rebuild_depth = 0


def _enter_wgc_rebuild() -> None:
    """进入WGC重建状态。支持嵌套调用，最后一个退出者负责放行闸门。"""
    global _wgc_rebuild_depth
    with _wgc_rebuild_state_lock:
        _wgc_rebuild_depth += 1
        _wgc_rebuild_gate.clear()


def _leave_wgc_rebuild() -> None:
    """退出WGC重建状态。"""
    global _wgc_rebuild_depth
    with _wgc_rebuild_state_lock:
        if _wgc_rebuild_depth > 0:
            _wgc_rebuild_depth -= 1
        if _wgc_rebuild_depth == 0:
            _wgc_rebuild_gate.set()


def is_wgc_rebuilding() -> bool:
    """当前是否处于WGC完整销毁重建中。"""
    return not _wgc_rebuild_gate.is_set()


def wait_wgc_rebuild_complete(timeout: Optional[float] = None) -> bool:
    """等待WGC重建完成。timeout=None表示无限等待。"""
    return _wgc_rebuild_gate.wait(timeout=timeout)


def _read_env_int(name: str, default: int, min_value: int, max_value: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(str(raw_value).strip())
    except ValueError as exc:
        raise ValueError(f"截图配置{name}必须是整数") from exc
    if not min_value <= value <= max_value:
        raise ValueError(f"截图配置{name}必须在{min_value}到{max_value}之间")
    return value


_WGC_REQUEST_FRAME_TIMEOUT_MS = _read_env_int(
    "SCREENSHOT_WGC_REQUEST_FRAME_TIMEOUT_MS",
    default=1500,
    min_value=300,
    max_value=8000,
)

_WGC_REQUEST_ACTIVE_POLL_MS = _read_env_int(
    "SCREENSHOT_WGC_REQUEST_ACTIVE_POLL_MS",
    default=0,
    min_value=0,
    max_value=8000,
)

_WGC_STATIC_REBUILD_RETRY_COUNT = _read_env_int(
    "SCREENSHOT_WGC_STATIC_REBUILD_RETRY_COUNT",
    default=8,
    min_value=1,
    max_value=40,
)

_WGC_STATIC_REBUILD_RETRY_INTERVAL_MS = _read_env_int(
    "SCREENSHOT_WGC_STATIC_REBUILD_RETRY_INTERVAL_MS",
    default=8,
    min_value=4,
    max_value=500,
)

_WGC_STATIC_REBUILD_COOLDOWN_MS = _read_env_int(
    "SCREENSHOT_WGC_STATIC_REBUILD_COOLDOWN_MS",
    default=250,
    min_value=0,
    max_value=2000,
)

_WGC_REQUEST_TIMEOUT_BUFFER_MS = _read_env_int(
    "SCREENSHOT_WGC_REQUEST_TIMEOUT_BUFFER_MS",
    default=40,
    min_value=10,
    max_value=2000,
)

_WGC_MIN_REQUEST_TIMEOUT_MS = (
    _WGC_REQUEST_ACTIVE_POLL_MS
    + (_WGC_STATIC_REBUILD_RETRY_COUNT * _WGC_STATIC_REBUILD_RETRY_INTERVAL_MS)
    + _WGC_REQUEST_TIMEOUT_BUFFER_MS
)

_WGC_REBUILD_GATE_WAIT_RATIO_PERCENT = _read_env_int(
    "SCREENSHOT_WGC_REBUILD_GATE_WAIT_RATIO_PERCENT",
    default=35,
    min_value=10,
    max_value=90,
)

_WGC_REBUILD_GATE_WAIT_MIN_MS = _read_env_int(
    "SCREENSHOT_WGC_REBUILD_GATE_WAIT_MIN_MS",
    default=200,
    min_value=50,
    max_value=5000,
)

_WGC_REBUILD_GATE_WAIT_MAX_MS = _read_env_int(
    "SCREENSHOT_WGC_REBUILD_GATE_WAIT_MAX_MS",
    default=5000,
    min_value=100,
    max_value=30000,
)

_WGC_REBUILD_RETRY_GUARD_MS = _read_env_int(
    "SCREENSHOT_WGC_REBUILD_RETRY_GUARD_MS",
    default=80,
    min_value=20,
    max_value=1000,
)

_WGC_STALE_FRAME_MAX_AGE_MS = _read_env_int(
    "SCREENSHOT_WGC_STALE_FRAME_MAX_AGE_MS",
    default=2000,
    min_value=100,
    max_value=30000,
)

_WGC_FRAME_POOL_BUFFERS = _read_env_int(
    "SCREENSHOT_WGC_FRAME_POOL_BUFFERS",
    default=2,
    min_value=1,
    max_value=4,
)

_WGC_RECREATE_EVERY_N_FRAMES = _read_env_int(
    "SCREENSHOT_WGC_RECREATE_EVERY_N_FRAMES",
    default=0,
    min_value=0,
    max_value=10000,
)

# 尝试导入WGC相关库
try:
    from winrt.windows.graphics.capture.interop import create_for_window
    from winrt.windows.graphics.capture import (
        Direct3D11CaptureFramePool,
    )
    from winrt.windows.graphics.directx import DirectXPixelFormat
    from winrt.windows.graphics.directx.direct3d11 import IDirect3DDevice
    from utils.capture.wgc_d3d_readback import create_staging_readback as _create_staging_readback
    WGC_AVAILABLE = True
    logger.info("[OK] WGC库已加载 (winrt)")
except ImportError as e:
    WGC_AVAILABLE = False
    IDirect3DDevice = None  # 类型占位符
    _create_staging_readback = None
    logger.warning(f"[ERROR] WGC库未安装: {e}")
    logger.warning("  安装: pip install winrt-Windows.Graphics winrt-Windows.Graphics.Capture winrt-Windows.Graphics.DirectX winrt-Windows.Foundation winrt-Windows.AI.MachineLearning")

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("[ERROR] OpenCV未安装: pip install opencv-python")

try:
    import win32gui
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    logger.warning("[ERROR] pywin32未安装: pip install pywin32")


def _get_win32_root_hwnd(hwnd: int) -> int:
    if not WIN32_AVAILABLE:
        raise RuntimeError("缺少pywin32，无法解析WGC捕获窗口")
    return as_hwnd(win32gui.GetAncestor(hwnd, 2))


def _resolve_relative_axis_bounds(
    start: int,
    end: int,
    base: int,
    *,
    dpi_scale: float = 1.0,
    apply_scale: bool = False,
) -> Tuple[int, int]:
    """把同一坐标系下的起止端点转换成相对起点和长度，避免位置与尺寸分开换算造成 1px 漂移。"""
    start_value = int(start) - int(base)
    end_value = int(end) - int(base)
    if end_value < start_value:
        raise ValueError("截图坐标端点顺序无效")

    if apply_scale:
        scale = float(dpi_scale)
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("截图DPI比例无效")
        start_value = int(start_value * scale)
        end_value = int(end_value * scale)

    return start_value, max(0, end_value - start_value)


def resolve_wgc_client_crop_box(
    surface_width: int,
    surface_height: int,
    *,
    client_origin: Tuple[int, int],
    client_size: Tuple[int, int],
    dwm_rect: Tuple[int, int, int, int],
    window_rect: Tuple[int, int, int, int],
    surface_tolerance: int = 8,
) -> Optional[Tuple[int, int, int, int]]:
    """
    从 WGC 整窗 surface 精确裁出客户区 box。

    对齐 OP WgcCapture::getClientBox：多候选（已是客户区 / DWM 外框 / WindowRect），
    若会裁掉像素则返回 None，禁止静默缩小宽度。
    """
    try:
        surface_w = int(surface_width)
        surface_h = int(surface_height)
        expected_w = int(client_size[0])
        expected_h = int(client_size[1])
        origin_x = int(client_origin[0])
        origin_y = int(client_origin[1])
        tol = max(0, int(surface_tolerance))
    except Exception:
        return None
    if surface_w <= 0 or surface_h <= 0 or expected_w <= 0 or expected_h <= 0:
        return None

    candidates: list[Tuple[int, int, int, int, int, int]] = []
    # (x, y, w, h, clipped_pixels, frame_mismatch)

    extra_w = surface_w - expected_w
    extra_h = surface_h - expected_h
    if 0 <= extra_w <= tol and 0 <= extra_h <= tol:
        candidates.append((0, 0, expected_w, expected_h, 0, extra_w + extra_h))

    for base_rect in (dwm_rect, window_rect):
        try:
            base_left, base_top, base_right, base_bottom = [int(v) for v in base_rect]
        except Exception:
            continue
        left = max(0, origin_x - base_left)
        top = max(0, origin_y - base_top)
        if left >= surface_w or top >= surface_h:
            continue
        width = min(expected_w, surface_w - left)
        height = min(expected_h, surface_h - top)
        if width <= 0 or height <= 0:
            continue
        clipped = (expected_w - width) + (expected_h - height)
        mismatch = abs((base_right - base_left) - surface_w) + abs((base_bottom - base_top) - surface_h)
        candidates.append((left, top, width, height, clipped, mismatch))

    best = None
    for item in candidates:
        if best is None:
            best = item
            continue
        if item[4] < best[4]:
            best = item
        elif item[4] == best[4] and item[5] < best[5]:
            best = item
        elif item[4] == best[4] and item[5] == best[5] and item[0] < best[0]:
            best = item

    if best is None or best[4] > 0:
        return None
    return best[0], best[1], best[2], best[3]


@dataclass
class CaptureStats:
    """捕获统计"""
    total_captures: int = 0
    wgc_captures: int = 0
    cache_hits: int = 0
    total_time_ms: float = 0.0

    @property
    def avg_time_ms(self) -> float:
        return self.total_time_ms / self.total_captures if self.total_captures > 0 else 0.0

    @property
    def wgc_usage_rate(self) -> float:
        return (self.wgc_captures / self.total_captures * 100) if self.total_captures > 0 else 0.0


class FrameCache:
    """LRU帧缓存 - 使用手动管理确保内存释放"""

    def __init__(self, max_size: int = 2, ttl_ms: float = 30.0):
        """
        初始化帧缓存

        """
        self.max_size = max_size
        self.ttl_ms = ttl_ms
        # 【修复】使用普通列表，手动管理大小和删除
        self._cache_list = []  # [(key, frame, timestamp), ...]
        self.lock = threading.Lock()

    def get(self, key: str) -> Optional[np.ndarray]:
        """获取缓存帧"""
        with self.lock:
            if not self._cache_list:
                return None

            # 从最新到最旧查找匹配的key
            for i in range(len(self._cache_list) - 1, -1, -1):
                cached_key, frame, timestamp = self._cache_list[i]
                if cached_key == key:
                    # 检查是否过期
                    if (time.time() * 1000 - timestamp) > self.ttl_ms:
                        # 过期了，删除并返回None
                        self._cache_list.pop(i)
                        del frame  # 【关键】显式释放numpy数组
                        return None

                    # 未过期，返回副本
                    return frame.copy()

            # 未找到
            return None

    def set(self, key: str, frame: np.ndarray):
        """设置缓存帧"""
        with self.lock:
            # 检查是否已存在相同key，如果存在则更新
            for i in range(len(self._cache_list)):
                cached_key, old_frame, _ = self._cache_list[i]
                if cached_key == key:
                    # 【关键】先删除旧帧再更新
                    self._cache_list.pop(i)
                    del old_frame
                    break

            # 【关键】如果超过最大数量，删除最老的
            while len(self._cache_list) >= self.max_size:
                _, old_frame, _ = self._cache_list.pop(0)
                del old_frame  # 【关键】显式释放numpy数组
                logger.debug("[FrameCache] 缓存已满，删除最老的帧")

            # 添加新帧
            self._cache_list.append((key, frame.copy(), time.time() * 1000))

    def clear(self):
        """清空缓存"""
        with self.lock:
            # 【内存泄漏修复】显式删除所有帧数据
            cache_size = len(self._cache_list)
            while self._cache_list:
                try:
                    _, frame, _ = self._cache_list.pop()
                    del frame  # 显式删除numpy数组
                except Exception:
                    pass



class D3D11DeviceManager:
    """D3D11设备管理器（单例）"""
    _instance = None
    _lock = threading.RLock()
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
                    cls._instance._users = 0
                    cls._instance.device = None
                    cls._instance._learning_model_device = None
                    cls._instance._native_readback = None
        return cls._instance
    def __init__(self):
        with self._lock:
            if not self._initialized:
                self._init_device()
                self._initialized = True
    def _init_device(self):
        """初始化D3D11设备"""
        model_device = None
        native = None
        try:
            from winrt.windows.ai.machinelearning import LearningModelDevice, LearningModelDeviceKind
            model_device = LearningModelDevice(LearningModelDeviceKind.DIRECTX_HIGH_PERFORMANCE)
            device = model_device.direct3d11_device
            if device is None:
                raise RuntimeError("LearningModelDevice 未返回 direct3d11_device")
            if not callable(_create_staging_readback):
                raise RuntimeError("WGC staging 读回模块不可用")
            native = _create_staging_readback(device)
            # 整条设备链完成后才发布，初始化失败不会留下半成品。
            self._learning_model_device = model_device
            self.device = device
            self._native_readback = native
            logger.info("[成功] D3D11设备和 staging 读回已创建")
        except Exception as e:
            if native is not None:
                native.close()
            self._native_readback = None
            self.device = None
            self._learning_model_device = None
            del model_device
            logger.error(f"D3D11设备创建失败: {e}")
            raise RuntimeError(f"无法创建D3D11设备: {e}")

    def get_native_readback(self):
        with self._lock:
            return self._native_readback

    def acquire_device(self):
        """捕获器取得设备使用权，必须在原生资源关闭后归还。"""
        with self._lock:
            if self.device is None:
                self._init_device()
            self._users += 1
            return self.device

    def release_device(self):
        with self._lock:
            if self._users <= 0:
                raise RuntimeError("WGC设备使用计数不平衡")
            self._users -= 1

    def cleanup(self):
        """清理D3D设备资源"""
        with self._lock:
            if self._users:
                raise RuntimeError(f"仍有{self._users}个WGC捕获器占用D3D设备，清理未完成")
            if self._native_readback is not None:
                self._native_readback.close()
                self._native_readback = None
            # 这些 WinRT 接口不实现 IClosable；释放 Python 引用以归还 COM 引用。
            self.device = None
            self._learning_model_device = None


class WGCCleanupIncomplete(RuntimeError):
    """启动失败时向管理器转交尚未关闭的捕获器。"""
    def __init__(self, capturer, reason):
        super().__init__(reason)
        self.capturer = capturer


class WGC_HWND_Capturer:
    """WGC HWND捕获器"""

    # 【资源平衡监控】全局资源计数器
    _resource_stats = {
        'capturers_created': 0,
        'capturers_destroyed': 0,
        'frame_pools_created': 0,
        'frame_pools_closed': 0,
        'sessions_created': 0,
        'sessions_closed': 0,
    }
    _resource_lock = threading.Lock()

    @classmethod
    def get_resource_stats(cls) -> dict:
        """获取资源统计信息"""
        with cls._resource_lock:
            stats = cls._resource_stats.copy()
            stats['capturers_active'] = stats['capturers_created'] - stats['capturers_destroyed']
            stats['frame_pools_active'] = stats['frame_pools_created'] - stats['frame_pools_closed']
            stats['sessions_active'] = stats['sessions_created'] - stats['sessions_closed']
            return stats

    @classmethod
    def _inc_stat(cls, key: str):
        """增加计数器"""
        with cls._resource_lock:
            cls._resource_stats[key] = cls._resource_stats.get(key, 0) + 1

    def __init__(self, hwnd: int):
        """
        初始化捕获器

        Args:
            hwnd: 窗口句柄（可以是子窗口，会自动转换为顶层窗口）
        """
        if not WGC_AVAILABLE:
            raise ImportError("WGC库未安装，请安装: pip install winrt-Windows.Graphics winrt-Windows.Graphics.Capture winrt-Windows.Graphics.DirectX winrt-Windows.Foundation winrt-Windows.AI.MachineLearning")

        hwnd = as_hwnd(hwnd)
        # 【关键修复】检查是否为子窗口，WGC只能捕获顶层窗口
        self.target_hwnd = hwnd  # 保存原始目标窗口（可能是子窗口）
        self.capture_hwnd = self._get_top_level_window(hwnd)  # WGC实际捕获的窗口（必须是顶层）

        if self.target_hwnd != self.capture_hwnd:
            logger.info(f"[INFO] 检测到子窗口 {self.target_hwnd}，WGC将捕获其父窗口 {self.capture_hwnd}")

        self.hwnd = self.capture_hwnd
        self.item = None
        self.frame_pool = None
        self.session = None
        self.latest_frame = None  # 存储BGR格式的帧（已转换）
        self.frame_arrived_token = None  # 【内存泄漏修复】保存事件token用于移除
        self._frame_arrived_handler = None
        self.lock = threading.Lock()
        self.frame_ready = threading.Event()  # 新帧就绪事件
        self._frame_request = threading.Event()  # 【新增】请求新帧信号
        self._native_frame_arrived = threading.Event()
        self._loop_started = threading.Event()
        self._stop_event = threading.Event()
        self._frame_seq = 0  # 【功能修复】帧序号，用于区分新旧帧
        self._frame_time = 0.0  # 【WGC静态窗口修复】帧捕获时间戳
        self._frame_is_new = False  # 【帧标签】True=新帧（未使用），False=旧帧（已使用）
        self.is_running = False
        self.capture_thread = None
        self._destroy_lock = threading.Lock()
        self._destroyed_recorded = False
        self._cleanup_error = ""
        self._pending_closures = []
        self._device_manager = None
        self._frame_skip_count = 0  # 【修复闪退】帧跳过计数器，用于监控
        self._last_static_rebuild_ts = 0.0
        self._static_rebuild_cooldown_sec = _WGC_STATIC_REBUILD_COOLDOWN_MS / 1000.0
        self._last_failure_reason = ""
        self._last_failure_lock = threading.Lock()

        # 获取D3D设备
        self.device = None
        WGC_HWND_Capturer._inc_stat('capturers_created')
        try:
            manager = D3D11DeviceManager()
            self.device = manager.acquire_device()
            self._device_manager = manager
            self._create_capture_item()
            self._start_background_capture()
        except Exception:
            try:
                self.stop()
            except Exception as exc:
                raise WGCCleanupIncomplete(self, f"WGC启动失败且清理未完成：{exc}") from exc
            raise
        logger.debug(f"[资源监控] 捕获器已创建 (HWND: {hwnd}), 统计: {WGC_HWND_Capturer.get_resource_stats()}")

    def _wait_for_pool_frame(self, frame_pool, attempts: int, interval_ms: int):
        """等 FrameArrived 取帧。事件一到立刻返回，超时只是上限，不是固定 sleep。"""
        if frame_pool is None:
            return None
        deadline = time.time() + (
            max(1, int(attempts)) * max(0.001, float(interval_ms) / 1000.0)
        )
        while self.is_running and time.time() < deadline:
            frame = self._take_latest_pool_frame(frame_pool)
            if frame is not None:
                return frame
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            self._native_frame_arrived.wait(timeout=remaining)
            self._native_frame_arrived.clear()
        return None

    def _take_latest_pool_frame(self, frame_pool):
        frame = frame_pool.try_get_next_frame()
        if frame is None:
            return None
        try:
            for _ in range(int(_WGC_FRAME_POOL_BUFFERS) - 1):
                newer_frame = frame_pool.try_get_next_frame()
                if newer_frame is None:
                    return frame
                old_frame = frame
                frame = newer_frame
                self._close_frame_resource(old_frame)
            return frame
        except Exception:
            try:
                self._close_frame_resource(frame)
            finally:
                raise

    def _discard_pooled_frames(self, frame_pool) -> int:
        """丢掉请求前积压的缓冲帧，避免把旧画面标成新帧。"""
        if frame_pool is None:
            return 0
        discarded = 0
        for _ in range(int(_WGC_FRAME_POOL_BUFFERS)):
            frame = frame_pool.try_get_next_frame()
            if frame is None:
                break
            self._close_frame_resource(frame)
            discarded += 1
        return discarded

    def _close_frame_resource(self, resource):
        try:
            resource.close()
        except Exception:
            self._pending_closures.append(resource)
            raise

    def _close_capture_session(self, session) -> None:
        if session is None:
            return
        session.close()
        WGC_HWND_Capturer._inc_stat("sessions_closed")
        if self.session is session:
            self.session = None

    def _close_frame_pool(self, frame_pool) -> None:
        if frame_pool is None:
            return
        try:
            self._detach_frame_arrived_handler(frame_pool=frame_pool)
        finally:
            frame_pool.close()
            WGC_HWND_Capturer._inc_stat("frame_pools_closed")
            if self.frame_pool is frame_pool:
                self.frame_pool = None
            # Close 会撤销池上的事件，即使显式移除事件曾失败。
            self.frame_arrived_token = None
            self._frame_arrived_handler = None

    def _open_pool_and_session(self):
        size = self.item.size
        self.frame_pool = Direct3D11CaptureFramePool.create_free_threaded(
            self.device,
            DirectXPixelFormat.B8_G8_R8_A8_UINT_NORMALIZED,
            int(_WGC_FRAME_POOL_BUFFERS),
            size,
        )
        WGC_HWND_Capturer._inc_stat("frame_pools_created")
        self._attach_frame_arrived_handler(self.frame_pool)
        self.session = self.frame_pool.create_capture_session(self.item)
        WGC_HWND_Capturer._inc_stat("sessions_created")
        self.session.is_border_required = False
        self.session.is_cursor_capture_enabled = False
        self.session.start_capture()
        return self.frame_pool, self.session

    def _force_static_window_frame(self, frame_pool, session):
        """静态窗口通过一次新会话请求新帧，失败由工作线程结束并清理。"""
        self._close_capture_session(session)
        session = None
        self._close_frame_pool(frame_pool)
        frame_pool = None
        frame_pool, session = self._open_pool_and_session()
        frame = self._wait_for_pool_frame(
            frame_pool,
            _WGC_STATIC_REBUILD_RETRY_COUNT,
            _WGC_STATIC_REBUILD_RETRY_INTERVAL_MS,
        )
        if frame is None:
            logger.debug("[后台捕获] 静态窗口重建后仍无新帧")
        return frame, frame_pool, session

    def _get_top_level_window(self, hwnd: int) -> int:
        return resolve_wgc_capture_hwnd(hwnd, get_root_hwnd=_get_win32_root_hwnd)

    def _create_capture_item(self):
        """通过HWND创建GraphicsCaptureItem"""
        try:
            # 关键：使用create_for_window通过HWND创建捕获项
            self.item = create_for_window(self.hwnd)
            self._set_last_failure_reason("")
            logger.debug(f"[OK] GraphicsCaptureItem创建成功 (HWND: {self.hwnd})")
        except Exception as e:
            self._set_last_failure_reason(f"capture_item_create_failed:{type(e).__name__}")
            logger.error(f"[ERROR] 捕获项创建失败 (HWND: {self.hwnd}): {e}")
            raise

    def _set_last_failure_reason(self, reason: str) -> None:
        try:
            normalized = str(reason or "").strip().lower()
        except Exception:
            normalized = ""
        if len(normalized) > 160:
            normalized = normalized[:160]
        with self._last_failure_lock:
            self._last_failure_reason = normalized

    def get_last_failure_reason(self) -> str:
        with self._last_failure_lock:
            return self._last_failure_reason

    def _detach_frame_arrived_handler(self, frame_pool=None) -> None:
        target_pool = frame_pool
        if target_pool is None:
            target_pool = self.frame_pool
        token = self.frame_arrived_token
        if target_pool is not None and token is not None:
            target_pool.remove_frame_arrived(token)
        self.frame_arrived_token = None
        self._frame_arrived_handler = None
        self._native_frame_arrived.clear()

    def _attach_frame_arrived_handler(self, frame_pool) -> None:
        if self.frame_arrived_token is not None:
            raise RuntimeError("WGC上一帧池事件尚未注销")
        if frame_pool is None:
            raise RuntimeError("WGC帧池为空")

        def _on_frame_arrived(_sender, _args):
            try:
                self._native_frame_arrived.set()
            except Exception:
                pass

        token = frame_pool.add_frame_arrived(_on_frame_arrived)
        self._frame_arrived_handler = _on_frame_arrived
        self.frame_arrived_token = token
        try:
            self._native_frame_arrived.clear()
        except Exception:
            pass

    def _frame_to_numpy(self, frame) -> Optional[np.ndarray]:
        """将 D3D11 捕获帧转为 BGR numpy（仅 staging 读回）。"""
        native = self._device_manager.get_native_readback()
        if native is None:
            self._set_last_failure_reason("staging_readback_unavailable")
            logger.error("[WGC] staging 读回未初始化")
            raise RuntimeError("WGC staging 读回未初始化")
        surface = None
        try:
            surface = frame.surface
            return native.surface_to_bgr(surface)
        except Exception as e:
            self._set_last_failure_reason(f"staging_readback_failed:{type(e).__name__}")
            logger.error(f"[WGC] staging 读回失败: {e}", exc_info=True)
            raise
        finally:
            if surface is not None:
                self._close_frame_resource(surface)

    def request_new_frame(self, timeout_ms: float = 2000) -> Optional[np.ndarray]:
        """
        主动请求捕获新帧。

        只返回本次请求之后新读回的帧（seq 必须前进）。不复用超时前的旧帧。
        """
        if not self.is_running:
            self._set_last_failure_reason("capturer_not_running")
            logger.error("[请求新帧] 后台捕获未运行")
            return None

        if not WIN32_AVAILABLE:
            raise RuntimeError("缺少pywin32，无法验证WGC捕获窗口")
        if not win32gui.IsWindow(self.hwnd):
            self._set_last_failure_reason("invalid_hwnd")
            return None

        try:
            logger.debug("[请求新帧] 等待新帧...")
            with self.lock:
                wait_seq = int(self._frame_seq)
                self.frame_ready.clear()
            self._frame_request.set()

            effective_timeout_ms = max(float(timeout_ms), float(_WGC_MIN_REQUEST_TIMEOUT_MS))
            deadline = time.time() + (effective_timeout_ms / 1000.0)

            while not self._stop_event.is_set():
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                if not self.frame_ready.wait(timeout=remaining):
                    break
                with self.lock:
                    if (
                        self._frame_is_new
                        and self.latest_frame is not None
                        and int(self._frame_seq) > wait_seq
                    ):
                        frame_copy = self.latest_frame.copy()
                        self._frame_is_new = False
                        self._set_last_failure_reason("")
                        logger.debug(f"[请求新帧] 获取新帧成功: seq={self._frame_seq}")
                        return frame_copy
                self.frame_ready.clear()

            nested_reason = self.get_last_failure_reason()
            if nested_reason:
                self._set_last_failure_reason(f"request_timeout:{nested_reason}")
            else:
                self._set_last_failure_reason("request_timeout")
            logger.warning(
                f"[请求新帧] 等待超时 (requested={int(timeout_ms)}ms, effective={int(effective_timeout_ms)}ms)"
            )
            try:
                self._frame_request.clear()
            except Exception:
                pass
            return None

        except Exception as e:
            self._set_last_failure_reason(f"request_exception:{type(e).__name__}")
            logger.error(f"[请求新帧] 获取帧失败: {e}", exc_info=True)
            return None

    def get_frame(self, timeout_ms: float = 300, wait_for_new: bool = False) -> Optional[np.ndarray]:
        """
        获取最新帧（从后台线程获取）

        【帧标签系统】
        - `wait_for_new=False` 时优先返回当前最近帧（含已消费帧）
        - 返回后将帧标签设为"旧帧"，保留最近帧供短时复用

        Args:
            timeout_ms: 超时时间（毫秒）
            wait_for_new: 是否等待新帧（True时跳过已有帧检查，直接等待新帧）

        Returns:
            BGR格式的numpy数组
        """
        if not self.is_running:
            self._set_last_failure_reason("capturer_not_running")
            logger.error("后台捕获未运行")
            return None

        # 【修复闪退】在获取帧前检查窗口是否仍然有效
        if not WIN32_AVAILABLE:
            self._set_last_failure_reason("window_validation_unavailable")
            raise RuntimeError("缺少pywin32，无法验证WGC捕获窗口")
        try:
            valid_window = win32gui.IsWindow(self.hwnd)
        except Exception as e:
            self._set_last_failure_reason("window_validation_failed")
            raise RuntimeError(f"检查WGC捕获窗口有效性失败：{e}") from e
        if not valid_window:
            self._set_last_failure_reason("invalid_hwnd")
            logger.error(f"[获取帧] 窗口已失效 (HWND: {self.hwnd})")
            return None

        # 等待新帧
        timeout_seconds = timeout_ms / 1000.0

        # 【帧标签】检查是否有未使用的新帧
        if not wait_for_new:
            with self.lock:
                if self.latest_frame is not None:
                    # 返回最近帧（优先新帧，其次旧帧）
                    frame_copy = self.latest_frame.copy()
                    # 【帧标签】标记为"旧帧"
                    self._frame_is_new = False
                    self._set_last_failure_reason("")
                    logger.debug(f"[获取帧] 返回最近帧，标记为旧帧 (seq={self._frame_seq})")
                    return frame_copy

        # 等待新帧就绪（使用Event，无需轮询）
        if self.frame_ready.wait(timeout=timeout_seconds):
            with self.lock:
                if self.latest_frame is not None:
                    # 返回最新可用帧
                    frame_copy = self.latest_frame.copy()
                    # 【帧标签】标记为"旧帧"
                    self._frame_is_new = False
                    self._set_last_failure_reason("")
                    logger.debug(f"[获取帧] 返回等待到的最新帧，标记为旧帧 (seq={self._frame_seq})")
                    return frame_copy

        self._set_last_failure_reason("get_frame_timeout")
        logger.warning(f"获取帧超时 (HWND: {self.hwnd})")
        return None

    def _start_background_capture(self):
        """原生资源只由捕获线程创建、使用和关闭。"""
        def capture_loop():
            frame = None
            try:
                frame_pool, session = self._open_pool_and_session()
                with self.lock:
                    self.is_running = not self._stop_event.is_set()
                self._loop_started.set()
                frame_count = 0
                while not self._stop_event.is_set():
                    with self.lock:
                        need_bootstrap = self.latest_frame is None
                    if not self._frame_request.is_set() and not need_bootstrap:
                        self._frame_request.wait(timeout=0.25)
                        continue
                    self._discard_pooled_frames(frame_pool)
                    self._native_frame_arrived.clear()
                    poll_seconds = _WGC_REQUEST_ACTIVE_POLL_MS / 1000.0
                    if poll_seconds > 0:
                        frame = self._wait_for_pool_frame(
                            frame_pool, 1, _WGC_REQUEST_ACTIVE_POLL_MS
                        )
                    else:
                        frame = self._take_latest_pool_frame(frame_pool)
                    if frame is None and not self._stop_event.is_set():
                        now = time.time()
                        if should_force_static_window_rebuild(
                            now_ts=now,
                            last_rebuild_ts=self._last_static_rebuild_ts,
                            cooldown_sec=self._static_rebuild_cooldown_sec,
                        ):
                            self._last_static_rebuild_ts = now
                            frame, frame_pool, session = self._force_static_window_frame(
                                frame_pool, session
                            )
                        else:
                            remaining = self._static_rebuild_cooldown_sec - (
                                now - self._last_static_rebuild_ts
                            )
                            self._native_frame_arrived.wait(timeout=max(0, remaining))
                            self._native_frame_arrived.clear()
                            frame = self._take_latest_pool_frame(frame_pool)
                    if frame is None:
                        continue
                    try:
                        if self._stop_event.is_set():
                            break
                        image = self._frame_to_numpy(frame)
                        if image is None:
                            raise RuntimeError("WGC读回未返回图像")
                        with self.lock:
                            self.latest_frame = image
                            self._frame_seq += 1
                            self._frame_time = time.time()
                            self._frame_is_new = True
                            self._frame_request.clear()
                            self.frame_ready.set()
                    finally:
                        owned_frame, frame = frame, None
                        self._close_frame_resource(owned_frame)
                    frame_count += 1
                    if _WGC_RECREATE_EVERY_N_FRAMES > 0 and frame_count >= _WGC_RECREATE_EVERY_N_FRAMES:
                        frame_pool.recreate(
                            self.device,
                            DirectXPixelFormat.B8_G8_R8_A8_UINT_NORMALIZED,
                            int(_WGC_FRAME_POOL_BUFFERS),
                            self.item.size,
                        )
                        frame_count = 0
            except Exception as exc:
                self._set_last_failure_reason(f"background_failed:{type(exc).__name__}")
                logger.error("WGC后台捕获失败: %s", exc, exc_info=True)
            finally:
                self.is_running = False
                self._stop_event.set()
                if frame is not None:
                    try:
                        self._close_frame_resource(frame)
                    except Exception as exc:
                        self._cleanup_error = f"WGC帧关闭失败：{exc}"
                try:
                    self._release_owned_resources()
                except Exception as exc:
                    self._cleanup_error = str(exc)
                    logger.error("WGC资源清理未完成: %s", exc)
                self.frame_ready.set()
                self._loop_started.set()

        self.capture_thread = threading.Thread(
            target=capture_loop, daemon=True, name=f"WGC-{self.hwnd}"
        )
        self.capture_thread.start()
        if not self._loop_started.wait(timeout=1.0) or not self.is_running:
            self._stop_event.set()
            raise RuntimeError("WGC后台捕获启动失败或超时")

    def _mark_destroyed_once(self) -> bool:
        """仅记录一次销毁统计，避免重复计数。"""
        with self._destroy_lock:
            if self._destroyed_recorded:
                return False
            self._destroyed_recorded = True
        WGC_HWND_Capturer._inc_stat('capturers_destroyed')
        return True

    def _release_owned_resources(self):
        """原生调用结束后关闭资源；失败对象保留到下一次显式清理。"""
        errors = []
        pending, self._pending_closures = self._pending_closures, []
        for resource in pending:
            try:
                self._close_frame_resource(resource)
            except Exception as exc:
                errors.append(str(exc))
        for close, resource in (
            (self._close_capture_session, self.session),
            (self._close_frame_pool, self.frame_pool),
        ):
            try:
                close(resource)
            except Exception as exc:
                errors.append(str(exc))
        with self.lock:
            self.latest_frame = None
            self._frame_is_new = False
        if self.session is None and self.frame_pool is None and not self._pending_closures:
            self.item = None
            self.device = None
            if self._device_manager is not None:
                try:
                    self._device_manager.release_device()
                    self._device_manager = None
                except Exception as exc:
                    errors.append(str(exc))
            if self._device_manager is None:
                self._mark_destroyed_once()
        self._cleanup_error = "；".join(errors)
        if errors:
            raise RuntimeError(f"WGC资源关闭失败：{self._cleanup_error}")

    def stop(self):
        """停止超时明确失败；仍在原生调用的线程继续持有设备及资源。"""
        self._stop_event.set()
        self.is_running = False
        self._frame_request.set()
        self._native_frame_arrived.set()
        thread = self.capture_thread
        if thread is not None:
            if thread is threading.current_thread():
                raise RuntimeError("WGC捕获线程不能等待自身停止")
            if thread.ident is not None:
                thread.join(timeout=3.0)
            if thread.is_alive():
                raise RuntimeError(f"WGC捕获线程停止超时，资源清理未完成（窗口{self.hwnd}）")
        if not self._destroyed_recorded:
            self._release_owned_resources()
        else:
            self._cleanup_error = ""
        self.capture_thread = None


class OptimizedWGCCapture:
    """优化的WGC捕获管理器"""

    def __init__(self, cache_size: int = 2, cache_ttl_ms: float = 30.0, max_capturers: int = 5):
        """
        初始化

        Args:
            cache_size: 缓存大小（默认2个，高频OCR优化：减少内存占用）
            cache_ttl_ms: 缓存有效期（毫秒，默认30ms，高频OCR优化：更快过期）
            max_capturers: 最大捕获器数量（默认5个，减少资源占用）

        【高频OCR优化】
        - cache_size从5降到2
        - cache_ttl_ms从50降到30
        - max_capturers从10降到5
        """
        self.capturers = {}  # hwnd -> WGC_HWND_Capturer
        self.capturer_last_used = {}  # hwnd -> 最后使用时间戳
        self.max_capturers = max_capturers
        self.cache = FrameCache(max_size=cache_size, ttl_ms=cache_ttl_ms)
        self.stats = CaptureStats()
        self.lock = threading.Lock()
        self._operation_lock = threading.RLock()
        self._request_condition = threading.Condition(self.lock)
        self._active_capture_requests = 0
        self._last_capture_request_ts = 0.0
        self._closing = False
        self._closed = False

        # 【内存泄漏修复】启动定期清理线程
        self._cleanup_stop_event = threading.Event()
        self._cleanup_thread = threading.Thread(target=self._periodic_cleanup, daemon=True, name="WGC-Cleanup")
        self._cleanup_thread.start()
        logger.debug("[WGC] 定期清理线程已启动")
        self._last_capture_failure_reason = ""
        self._last_capture_failure_lock = threading.Lock()

    def _capturer_key(self, hwnd: int) -> int:
        return resolve_wgc_capture_hwnd(hwnd, get_root_hwnd=_get_win32_root_hwnd)

    def _pop_capturer(self, key: int):
        capturer = self.capturers.pop(key, None)
        self.capturer_last_used.pop(key, None)
        return capturer

    def _set_last_capture_failure_reason(self, reason: str) -> None:
        try:
            normalized = str(reason or "").strip().lower()
        except Exception:
            normalized = ""
        if len(normalized) > 160:
            normalized = normalized[:160]
        with self._last_capture_failure_lock:
            self._last_capture_failure_reason = normalized

    def get_last_capture_failure_reason(self) -> str:
        with self._last_capture_failure_lock:
            return self._last_capture_failure_reason

    @staticmethod
    def _extract_capturer_failure_reason(capturer: Optional[WGC_HWND_Capturer], default_reason: str) -> str:
        if capturer is None:
            return default_reason
        try:
            reason = str(capturer.get_last_failure_reason() or "").strip().lower()
        except Exception:
            reason = ""
        return reason or default_reason

    def _begin_capture_request(self) -> bool:
        with self._request_condition:
            if self._closing or self._closed:
                return False
            self._active_capture_requests += 1
            self._last_capture_request_ts = time.time()
            return True

    def _end_capture_request(self) -> None:
        with self._request_condition:
            if self._active_capture_requests > 0:
                self._active_capture_requests -= 1
            self._request_condition.notify_all()

    def _check_capturer_health(self, capturer: Optional[WGC_HWND_Capturer]) -> Tuple[bool, str]:
        """统一的捕获器健康检查，避免多处判定不一致。"""
        if capturer is None:
            return False, "捕获器为空"

        if not getattr(capturer, "is_running", False):
            return False, "is_running=False"

        capture_thread = getattr(capturer, "capture_thread", None)
        if capture_thread is None or (not capture_thread.is_alive()):
            return False, "捕获线程未运行"

        if getattr(capturer, "item", None) is None:
            return False, "capture_item为空"
        if getattr(capturer, "frame_pool", None) is None:
            return False, "frame_pool为空"
        if getattr(capturer, "session", None) is None:
            return False, "session为空"

        return True, "ok"

    def _stop_capturer(self, key):
        capturer = self.capturers.get(key)
        if capturer is not None:
            capturer.stop()
            self._pop_capturer(key)

    def _periodic_cleanup(self):
        while not self._cleanup_stop_event.wait(1.0):
            if not self._operation_lock.acquire(blocking=False):
                continue
            try:
                if self._closing or self._closed:
                    continue
                now = time.time()
                for key, capturer in list(self.capturers.items()):
                    healthy, _ = self._check_capturer_health(capturer)
                    if not healthy or now - self.capturer_last_used[key] > 30:
                        try:
                            self._stop_capturer(key)
                        except Exception:
                            logger.error("WGC捕获器清理未完成：窗口%s", key, exc_info=True)
            finally:
                self._operation_lock.release()

    def capture_window(
        self,
        hwnd: int,
        use_cache: bool = False,
        client_area_only: bool = True,
        request_timeout_ms: Optional[int] = None,
    ) -> Optional[np.ndarray]:
        with self._operation_lock:
            if not self._begin_capture_request():
                self._set_last_capture_failure_reason("capture_manager_closing")
                return None
            start_time = time.monotonic()
            capture_key = None
            capturer = None
            cleanup_attempted = False
            try:
                self._set_last_capture_failure_reason("")
                hwnd = as_hwnd(hwnd)
                if not WIN32_AVAILABLE or not win32gui.IsWindow(hwnd):
                    raise RuntimeError("无法验证截图窗口或窗口已失效")
                capture_key = self._capturer_key(hwnd)
                timeout_ms = _WGC_REQUEST_FRAME_TIMEOUT_MS if request_timeout_ms is None else int(request_timeout_ms)
                if timeout_ms <= 0 or timeout_ms > 30000:
                    raise ValueError("WGC截图超时必须大于0且不超过30000毫秒")
                cache_key = f"wgc_{hwnd}_{client_area_only}"
                if use_cache:
                    cached = self.cache.get(cache_key)
                    if cached is not None:
                        self.stats.cache_hits += 1
                        return cached
                capturer = self.capturers.get(capture_key)
                if capturer is not None:
                    healthy, reason = self._check_capturer_health(capturer)
                    if not healthy:
                        cleanup_attempted = True
                        self._stop_capturer(capture_key)
                        raise RuntimeError(f"WGC捕获器已失效：{reason}")
                if capturer is None:
                    if len(self.capturers) >= self.max_capturers:
                        lru_key = min(self.capturer_last_used, key=self.capturer_last_used.get)
                        self._stop_capturer(lru_key)
                    try:
                        capturer = WGC_HWND_Capturer(hwnd)
                    except WGCCleanupIncomplete as exc:
                        self.capturers[capture_key] = exc.capturer
                        self.capturer_last_used[capture_key] = time.time()
                        raise
                    self.capturers[capture_key] = capturer
                self.capturer_last_used[capture_key] = time.time()
                if use_cache:
                    frame = capturer.get_frame(timeout_ms=timeout_ms, wait_for_new=False)
                else:
                    frame = capturer.request_new_frame(timeout_ms=timeout_ms)
                if frame is None:
                    self._set_last_capture_failure_reason(
                        self._extract_capturer_failure_reason(capturer, "capture_failed")
                    )
                    cleanup_attempted = True
                    self._stop_capturer(capture_key)
                    return None
                if client_area_only:
                    frame = self._crop_to_client_area(hwnd, frame, capturer)
                    if frame is None:
                        self._set_last_capture_failure_reason("crop_failed")
                        cleanup_attempted = True
                        self._stop_capturer(capture_key)
                        return None
                if use_cache:
                    self.cache.set(cache_key, frame)
                self.stats.total_captures += 1
                self.stats.wgc_captures += 1
                self.stats.total_time_ms += (time.monotonic() - start_time) * 1000
                return frame
            except Exception as exc:
                self._set_last_capture_failure_reason(f"capture_failed:{type(exc).__name__}:{exc}")
                logger.error("WGC截图失败：%s", exc, exc_info=True)
                if capture_key is not None and capturer is not None and not cleanup_attempted:
                    try:
                        self._stop_capturer(capture_key)
                    except Exception:
                        logger.error("WGC异常后的资源清理未完成", exc_info=True)
                return None
            finally:
                self._end_capture_request()

    def _crop_to_client_area(self, hwnd: int, frame: np.ndarray, capturer: WGC_HWND_Capturer = None) -> Optional[np.ndarray]:
        """
        裁剪到客户区 - 使用DWM API获取精确的窗口frame边框

        【重要】如果捕获器捕获的是父窗口（因为WGC不支持子窗口），
        则hwnd可能是子窗口，需要特殊处理坐标转换
        """
        try:
            capture_hwnd = getattr(capturer, "capture_hwnd", 0) if capturer is not None else 0
            if should_crop_wgc_as_child(hwnd, capture_hwnd):
                logger.debug(f"【子窗口裁剪模式】请求窗口: {hwnd}, 捕获窗口: {capture_hwnd}")
                return self._crop_child_window(hwnd, frame, capture_hwnd)

            # 正常情况：裁剪到指定窗口的客户区
            return self._crop_normal_window(hwnd, frame)

        except Exception as e:
            logger.warning(f"裁剪客户区失败: {e}")
            logger.exception(e)
            return None

    def _crop_child_window(self, child_hwnd: int, frame: np.ndarray, capture_hwnd: int) -> Optional[np.ndarray]:
        """
        裁剪子窗口：从父窗口的捕获中提取子窗口的区域

        Args:
            child_hwnd: 子窗口句柄（目标窗口）
            frame: WGC捕获的帧
            capture_hwnd: 实际被WGC捕获的父窗口句柄
        """
        try:
            import ctypes
            from ctypes import wintypes

            logger.debug("【子窗口裁剪开始】")
            logger.debug(f"  子窗口HWND: {child_hwnd}")
            logger.debug(f"  父窗口HWND: {capture_hwnd}")

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetThreadDpiAwarenessContext.restype = wintypes.HANDLE
            user32.GetAwarenessFromDpiAwarenessContext.argtypes = [wintypes.HANDLE]
            context = user32.GetThreadDpiAwarenessContext()
            awareness = user32.GetAwarenessFromDpiAwarenessContext(context)
            dpi = user32.GetDpiForWindow(wintypes.HWND(capture_hwnd))
            if awareness < 0 or dpi <= 0:
                raise RuntimeError("无法确定WGC窗口DPI坐标系")
            is_dpi_aware = awareness >= 2
            dpi_scale = dpi / 96.0

            # 获取子窗口的窗口矩形和客户区
            child_window_rect = win32gui.GetWindowRect(child_hwnd)
            child_client_rect = win32gui.GetClientRect(child_hwnd)
            child_w = child_client_rect[2]
            child_h = child_client_rect[3]

            # 如果进程是Per-Monitor DPI感知，GetClientRect返回的已经是物理像素
            if is_dpi_aware:
                child_w_physical = child_w
                child_h_physical = child_h
            else:
                child_w_physical = int(child_w * dpi_scale)
                child_h_physical = int(child_h * dpi_scale)

            # 获取子窗口客户区在屏幕上的位置与右下角端点
            child_screen_pos = win32gui.ClientToScreen(child_hwnd, (0, 0))
            child_screen_end = win32gui.ClientToScreen(child_hwnd, (child_client_rect[2], child_client_rect[3]))
            child_w_screen = max(0, int(child_screen_end[0]) - int(child_screen_pos[0]))
            child_h_screen = max(0, int(child_screen_end[1]) - int(child_screen_pos[1]))

            logger.debug(f"  子窗口窗口矩形(屏幕): {child_window_rect}")
            logger.debug(
                f"  子窗口客户区(逻辑): {child_client_rect}, 屏幕跨度: {child_w_screen}x{child_h_screen}, "
                f"物理估算: {child_w_physical}x{child_h_physical}"
            )
            logger.debug(f"  子窗口客户区屏幕坐标: {child_screen_pos}")

            # 获取父窗口（捕获窗口）的DWM边界
            logger.debug("  【获取父窗口信息】")
            capture_window_rect = win32gui.GetWindowRect(capture_hwnd)
            capture_client_rect = win32gui.GetClientRect(capture_hwnd)
            capture_client_pos = win32gui.ClientToScreen(capture_hwnd, (0, 0))
            capture_client_end = win32gui.ClientToScreen(
                capture_hwnd,
                (capture_client_rect[2], capture_client_rect[3]),
            )
            capture_client_w_screen = max(0, int(capture_client_end[0]) - int(capture_client_pos[0]))
            capture_client_h_screen = max(0, int(capture_client_end[1]) - int(capture_client_pos[1]))

            logger.debug(f"  父窗口窗口矩形(屏幕): {capture_window_rect}")
            logger.debug(f"  父窗口客户区(本地): {capture_client_rect}")
            logger.debug(f"  父窗口客户区屏幕坐标: {capture_client_pos}")

            try:
                dwmapi = ctypes.windll.dwmapi
                DWMWA_EXTENDED_FRAME_BOUNDS = 9
                rect = wintypes.RECT()
                result = dwmapi.DwmGetWindowAttribute(
                    wintypes.HWND(capture_hwnd),
                    wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
                    ctypes.byref(rect),
                    ctypes.sizeof(rect)
                )

                if result == 0:
                    capture_dwm_rect = (rect.left, rect.top, rect.right, rect.bottom)
                    logger.debug(f"  父窗口DWM边界(屏幕): {capture_dwm_rect}")
                    logger.debug(f"  父窗口DWM尺寸: {rect.right-rect.left}x{rect.bottom-rect.top}")

                    # 【关键】计算WGC捕获的基准点
                    # WGC可能捕获的是DWM边界，也可能是窗口矩形
                    logger.debug("  【计算WGC捕获基准点】")
                    frame_h, frame_w = frame.shape[:2]
                    logger.debug(f"  WGC捕获帧尺寸: {frame_w}x{frame_h}")

                    # 判断WGC捕获的是什么（需要用物理像素比较）
                    dwm_w = rect.right - rect.left
                    dwm_h = rect.bottom - rect.top
                    window_w = capture_window_rect[2] - capture_window_rect[0]
                    window_h = capture_window_rect[3] - capture_window_rect[1]
                    client_w = capture_client_w_screen
                    client_h = capture_client_h_screen

                    # WGC返回帧可能是逻辑像素或物理像素，需要同时比较两者
                    # 在非DPI感知进程中，WGC可能返回接近逻辑尺寸的帧
                    wgc_is_logical = True  # 默认假设是逻辑像素

                    # 先尝试与逻辑尺寸比较
                    if abs(frame_w - dwm_w) <= 4 and abs(frame_h - dwm_h) <= 4:
                        # WGC返回逻辑像素的DWM边界
                        screenshot_base_pos = (rect.left, rect.top)
                        wgc_is_logical = True
                        logger.debug(f"  [OK] WGC捕获的是DWM边界(逻辑像素)，基准点: {screenshot_base_pos}")
                    elif abs(frame_w - client_w) <= 4 and abs(frame_h - client_h) <= 4:
                        # WGC返回逻辑像素的客户区
                        screenshot_base_pos = capture_client_pos
                        wgc_is_logical = True
                        logger.debug(f"  [OK] WGC捕获的是客户区(逻辑像素)，基准点: {screenshot_base_pos}")
                    else:
                        # 尝试物理像素比较
                        if is_dpi_aware:
                            dwm_w_physical = dwm_w
                            dwm_h_physical = dwm_h
                            client_w_physical_cmp = client_w
                            client_h_physical_cmp = client_h
                        else:
                            dwm_w_physical = int(dwm_w * dpi_scale)
                            dwm_h_physical = int(dwm_h * dpi_scale)
                            client_w_physical_cmp = int(client_w * dpi_scale)
                            client_h_physical_cmp = int(client_h * dpi_scale)

                        if abs(frame_w - dwm_w_physical) <= 4 and abs(frame_h - dwm_h_physical) <= 4:
                            # WGC返回物理像素的DWM边界
                            screenshot_base_pos = (rect.left, rect.top)
                            wgc_is_logical = False
                            logger.debug(f"  [OK] WGC捕获的是DWM边界(物理像素)，基准点: {screenshot_base_pos}")
                        elif abs(frame_w - client_w_physical_cmp) <= 4 and abs(frame_h - client_h_physical_cmp) <= 4:
                            # WGC返回物理像素的客户区
                            screenshot_base_pos = capture_client_pos
                            wgc_is_logical = False
                            logger.debug(f"  [OK] WGC捕获的是客户区(物理像素)，基准点: {screenshot_base_pos}")
                        else:
                            raise RuntimeError(
                                f"无法识别WGC帧坐标系: frame={frame_w}x{frame_h}, "
                                f"DWM={dwm_w}x{dwm_h}, client={client_w}x{client_h}"
                            )

                    # 子窗口客户区相对于WGC捕获基准点的偏移与尺寸，统一按端点换算避免 1px 漂移
                    offset_x = int(child_screen_pos[0]) - int(screenshot_base_pos[0])
                    offset_y = int(child_screen_pos[1]) - int(screenshot_base_pos[1])
                    convert_to_physical = (not wgc_is_logical) and (not is_dpi_aware)
                    offset_x_physical, target_w = _resolve_relative_axis_bounds(
                        child_screen_pos[0],
                        child_screen_end[0],
                        screenshot_base_pos[0],
                        dpi_scale=dpi_scale,
                        apply_scale=convert_to_physical,
                    )
                    offset_y_physical, target_h = _resolve_relative_axis_bounds(
                        child_screen_pos[1],
                        child_screen_end[1],
                        screenshot_base_pos[1],
                        dpi_scale=dpi_scale,
                        apply_scale=convert_to_physical,
                    )
                    if wgc_is_logical:
                        logger.debug("  WGC使用逻辑像素坐标系，按屏幕端点计算裁剪范围")
                    elif is_dpi_aware:
                        logger.debug("  WGC使用物理像素坐标系，按屏幕端点计算裁剪范围")
                    else:
                        logger.debug("  WGC使用物理像素坐标系，按屏幕端点和DPI缩放计算裁剪范围")
                else:
                    raise Exception(f"DwmGetWindowAttribute 调用失败：{result}")

            except Exception as e:
                logger.error(f"DWM API 调用失败: {e}")
                raise

            logger.debug(f"  父窗口WindowRect: {capture_window_rect}, wgc_is_logical: {wgc_is_logical}")

            logger.debug("  【开始裁剪子窗口区域】")
            logger.debug(f"  子窗口偏移(逻辑): ({offset_x}, {offset_y}), 最终偏移: ({offset_x_physical}, {offset_y_physical})")
            logger.debug(f"  子窗口尺寸(逻辑): {child_w}x{child_h}, 物理: {child_w_physical}x{child_h_physical}")
            logger.debug(f"  WGC捕获帧尺寸: {frame.shape[1]}x{frame.shape[0]}")

            # 【修复】边界检查：确保不会超出父窗口捕获的帧尺寸
            frame_h, frame_w = frame.shape[:2]

            if wgc_is_logical:
                logger.debug(f"  WGC使用逻辑像素，目标裁剪尺寸: {target_w}x{target_h}")
            else:
                logger.debug(f"  WGC使用物理像素，目标裁剪尺寸: {target_w}x{target_h}")

            # 禁止静默缩小：算不出完整子窗口客户区则失败
            crop_x = int(offset_x_physical)
            crop_y = int(offset_y_physical)
            crop_w = int(target_w)
            crop_h = int(target_h)
            if (
                crop_x < 0
                or crop_y < 0
                or crop_w <= 0
                or crop_h <= 0
                or crop_x + crop_w > frame_w
                or crop_y + crop_h > frame_h
            ):
                logger.error(
                    "子窗口裁剪会丢失像素，拒绝缩小输出: offset=(%s,%s) target=%sx%s frame=%sx%s",
                    crop_x,
                    crop_y,
                    crop_w,
                    crop_h,
                    frame_w,
                    frame_h,
                )
                return None

            logger.debug(f"  实际裁剪区域: 起点=({crop_x}, {crop_y}), 尺寸={crop_w}x{crop_h}")
            return frame[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w].copy()

        except Exception as e:
            logger.error(f"子窗口裁剪失败: {e}", exc_info=True)
            return None

    def _crop_normal_window(self, hwnd: int, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        正常窗口裁剪：裁剪到窗口的客户区。

        禁止静默缩小：算不出完整客户区时返回 None（由上层记 crop_failed）。
        """
        try:
            import ctypes
            from ctypes import wintypes

            client_rect = win32gui.GetClientRect(hwnd)
            client_screen_pos = win32gui.ClientToScreen(hwnd, (0, 0))
            client_screen_end = win32gui.ClientToScreen(hwnd, (client_rect[2], client_rect[3]))
            client_w_screen = max(0, int(client_screen_end[0]) - int(client_screen_pos[0]))
            client_h_screen = max(0, int(client_screen_end[1]) - int(client_screen_pos[1]))
            if client_w_screen <= 0 or client_h_screen <= 0:
                raise RuntimeError("WGC客户区屏幕尺寸无效")

            window_rect = win32gui.GetWindowRect(hwnd)
            dwmapi = ctypes.windll.dwmapi
            rect = wintypes.RECT()
            result = dwmapi.DwmGetWindowAttribute(
                wintypes.HWND(hwnd),
                wintypes.DWORD(9),
                ctypes.byref(rect),
                ctypes.sizeof(rect),
            )
            if result != 0:
                raise RuntimeError(f"DwmGetWindowAttribute 失败：{result}")
            dwm_rect = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))

            frame_h, frame_w = frame.shape[:2]
            box = resolve_wgc_client_crop_box(
                frame_w,
                frame_h,
                client_origin=(int(client_screen_pos[0]), int(client_screen_pos[1])),
                client_size=(client_w_screen, client_h_screen),
                dwm_rect=dwm_rect,
                window_rect=(
                    int(window_rect[0]),
                    int(window_rect[1]),
                    int(window_rect[2]),
                    int(window_rect[3]),
                ),
            )
            if box is None:
                logger.error(
                    "WGC 客户区裁剪会丢失像素，拒绝缩小输出: hwnd=%s frame=%sx%s client=%sx%s",
                    hwnd,
                    frame_w,
                    frame_h,
                    client_w_screen,
                    client_h_screen,
                )
                return None

            crop_x, crop_y, crop_w, crop_h = box
            logger.debug(
                "WGC 客户区裁剪: hwnd=%s frame=%sx%s crop=(%s,%s) %sx%s",
                hwnd,
                frame_w,
                frame_h,
                crop_x,
                crop_y,
                crop_w,
                crop_h,
            )
            if crop_x == 0 and crop_y == 0 and crop_w == frame_w and crop_h == frame_h:
                return frame
            return frame[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w].copy()

        except Exception as e:
            logger.error(f"正常窗口裁剪失败: {e}", exc_info=True)
            return None

    def cleanup(self, hwnd: int = None):
        errors = []
        if hwnd is None:
            with self.lock:
                self._closing = True
            self._cleanup_stop_event.set()
        if not self._operation_lock.acquire(timeout=35.0):
            raise RuntimeError("WGC截图请求尚未退出，清理未完成")
        try:
            keys = list(self.capturers) if hwnd is None else [self._capturer_key(hwnd)]
            for key in keys:
                try:
                    self._stop_capturer(key)
                except Exception as exc:
                    errors.append(f"窗口{key}：{exc}")
            self.clear_cache(hwnd)
            if hwnd is None and not errors:
                self._closed = True
        finally:
            self._operation_lock.release()
        if hwnd is None:
            thread = self._cleanup_thread
            if thread is not None:
                thread.join(timeout=4.0)
                if thread.is_alive():
                    errors.append("WGC定期清理线程停止超时")
                else:
                    self._cleanup_thread = None
        if errors:
            raise RuntimeError("WGC清理未完成：" + "；".join(errors))

    def clear_cache(self, hwnd: int = None):
        """
        清除帧缓存，不销毁捕获器

        Args:
            hwnd: 指定窗口句柄只清除该窗口的缓存，None则清除所有缓存
        """
        if hwnd is not None:
            # 清除指定窗口的缓存
            # FrameCache使用key格式: f"wgc_{hwnd}_{client_area_only}"
            with self.cache.lock:
                # 反向遍历删除，避免索引错位
                hwnd_prefix = f"wgc_{hwnd}_"
                removed_count = 0
                i = len(self.cache._cache_list) - 1
                while i >= 0:
                    cached_key, frame, _ = self.cache._cache_list[i]
                    if cached_key.startswith(hwnd_prefix):
                        self.cache._cache_list.pop(i)
                        del frame
                        removed_count += 1
                    i -= 1

                if removed_count > 0:
                    logger.debug(f"[清除缓存] 已清除窗口{hwnd}的{removed_count}个缓存帧")
        else:
            # 清除所有缓存
            self.cache.clear()
            logger.debug("[清除缓存] 已清除所有帧缓存")

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            'total_captures': self.stats.total_captures,
            'wgc_captures': self.stats.wgc_captures,
            'cache_hits': self.stats.cache_hits,
            'avg_time_ms': self.stats.avg_time_ms,
            'wgc_usage_rate': f"{self.stats.wgc_usage_rate:.1f}%"
        }


# 全局实例
_global_capture = None
_global_lock = threading.Lock()


def get_global_capture() -> OptimizedWGCCapture:
    """获取全局捕获器实例"""
    global _global_capture
    with _global_lock:
        if _global_capture is None:
            _global_capture = OptimizedWGCCapture()
        return _global_capture


def get_existing_global_capture() -> Optional[OptimizedWGCCapture]:
    with _global_lock:
        return _global_capture


def get_last_wgc_capture_failure_reason() -> str:
    capture = get_existing_global_capture()
    if capture is None:
        return ""
    return str(capture.get_last_capture_failure_reason() or "")


def capture_window_wgc_optimized(
    hwnd: int,
    client_area_only: bool = True,
    use_cache: bool = False,
    request_timeout_ms: Optional[int] = None,
) -> Optional[np.ndarray]:
    """通过全局 WGC 管理器捕获窗口。"""
    capture = get_global_capture()
    return capture.capture_window(
        hwnd=hwnd,
        use_cache=use_cache,
        client_area_only=client_area_only,
        request_timeout_ms=request_timeout_ms,
    )


def cleanup_wgc(hwnd: int = None, cleanup_d3d: bool = False):
    """清理 WGC 资源；失败时保留全局管理器并抛出异常。"""
    global _global_capture
    with _global_lock:
        capture = _global_capture
        if capture is not None:
            capture.cleanup(hwnd=hwnd)
            if hwnd is None:
                _global_capture = None
        if hwnd is None and cleanup_d3d:
            manager = D3D11DeviceManager._instance
            if manager is not None:
                manager.cleanup()


# 自动清理（程序退出时清理D3D设备）
import atexit
atexit.register(lambda: cleanup_wgc(cleanup_d3d=True))


def clear_wgc_cache(hwnd: int = None):
    """清理 WGC 帧缓存。"""
    capture = get_existing_global_capture()
    if capture is not None:
        capture.clear_cache(hwnd)
