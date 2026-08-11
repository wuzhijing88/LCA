#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import asyncio
import numpy as np
import time
import threading
import gc
import os
from typing import Optional, Tuple
from dataclasses import dataclass

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
    except Exception:
        value = default
    return max(min_value, min(max_value, value))


_WGC_REQUEST_FRAME_TIMEOUT_MS = _read_env_int(
    "SCREENSHOT_WGC_REQUEST_FRAME_TIMEOUT_MS",
    default=1500,
    min_value=300,
    max_value=8000,
)

_WGC_REQUEST_ACTIVE_POLL_MS = _read_env_int(
    "SCREENSHOT_WGC_REQUEST_ACTIVE_POLL_MS",
    default=200,
    min_value=100,
    max_value=8000,
)

_WGC_STATIC_REBUILD_RETRY_COUNT = _read_env_int(
    "SCREENSHOT_WGC_STATIC_REBUILD_RETRY_COUNT",
    default=6,
    min_value=1,
    max_value=40,
)

_WGC_STATIC_REBUILD_RETRY_INTERVAL_MS = _read_env_int(
    "SCREENSHOT_WGC_STATIC_REBUILD_RETRY_INTERVAL_MS",
    default=50,
    min_value=5,
    max_value=500,
)

_WGC_REQUEST_TIMEOUT_BUFFER_MS = _read_env_int(
    "SCREENSHOT_WGC_REQUEST_TIMEOUT_BUFFER_MS",
    default=350,
    min_value=50,
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

_WGC_MAIN_MEMORY_CHECK_INTERVAL_SEC = _read_env_int(
    "SCREENSHOT_WGC_MEMORY_CHECK_INTERVAL_SEC",
    default=1,
    min_value=1,
    max_value=30,
)

_WGC_MAIN_MEMORY_THRESHOLD_MB = _read_env_int(
    "SCREENSHOT_WGC_MAIN_MEMORY_THRESHOLD_MB",
    default=500,
    min_value=200,
    max_value=8192,
)

_WGC_NO_RESOURCE_RECLAIM_COOLDOWN_SEC = _read_env_int(
    "SCREENSHOT_WGC_NO_RESOURCE_RECLAIM_COOLDOWN_SEC",
    default=45,
    min_value=5,
    max_value=1800,
)

_WGC_NO_RESOURCE_HIGH_MEM_LOG_INTERVAL_SEC = _read_env_int(
    "SCREENSHOT_WGC_NO_RESOURCE_HIGH_MEM_LOG_INTERVAL_SEC",
    default=30,
    min_value=5,
    max_value=600,
)

# 尝试导入WGC相关库
try:
    from winrt.windows.graphics.capture.interop import create_for_window
    from winrt.windows.graphics.capture import (
        Direct3D11CaptureFramePool,
        GraphicsCaptureSession,
    )
    from winrt.windows.graphics.directx import DirectXPixelFormat
    from winrt.windows.graphics.directx.direct3d11 import IDirect3DDevice
    from winrt.windows.graphics.imaging import (
        SoftwareBitmap,
        BitmapBufferAccessMode,
    )
    WGC_AVAILABLE = True
    logger.info("[OK] WGC库已加载 (winrt)")
except ImportError as e:
    WGC_AVAILABLE = False
    IDirect3DDevice = None  # 类型占位符
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
    import win32ui
    import win32con
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    logger.warning("[ERROR] pywin32未安装: pip install pywin32")


def _resolve_relative_axis_bounds(
    start: int,
    end: int,
    base: int,
    *,
    dpi_scale: float = 1.0,
    apply_scale: bool = False,
) -> Tuple[int, int]:
    """把同一坐标系下的起止端点转换成相对起点和长度，避免位置与尺寸分开换算造成 1px 漂移。"""
    try:
        start_value = int(start) - int(base)
        end_value = int(end) - int(base)
    except Exception:
        return 0, 0

    if end_value < start_value:
        end_value = start_value

    if apply_scale:
        scale = max(0.01, float(dpi_scale or 1.0))
        start_value = int(start_value * scale)
        end_value = int(end_value * scale)

    return start_value, max(0, end_value - start_value)


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
                logger.debug(f"[FrameCache] 缓存已满，删除最老的帧")

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
                except:
                    pass



class D3D11DeviceManager:
    """D3D11设备管理器（单例）"""
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
        self.device = None
        self._learning_model_device = None
        self._initialized = True
        self._init_device()
    def _init_device(self):
        """初始化D3D11设备"""
        try:
            # 先释放旧设备链，避免重建时残留native对象
            self.cleanup()
            from winrt.windows.ai.machinelearning import LearningModelDevice, LearningModelDeviceKind
            kind = (
                getattr(LearningModelDeviceKind, "DIRECTX_HIGH_PERFORMANCE", None)
                or getattr(LearningModelDeviceKind, "DIRECT_X_HIGH_PERFORMANCE", None)
                or getattr(LearningModelDeviceKind, "DIRECTX", None)
                or getattr(LearningModelDeviceKind, "DEFAULT", None)
            )
            if kind is None:
                raise RuntimeError("LearningModelDeviceKind 无可用设备类型")
            model_device = LearningModelDevice(kind)
            direct3d_device = (
                getattr(model_device, "direct3d11_device", None)
                or getattr(model_device, "direct3_d11_device", None)
            )
            if direct3d_device:
                self._learning_model_device = model_device
                self.device = direct3d_device
                logger.info("[成功] D3D11设备创建成功")
                return
            try:
                model_device.close()
            except Exception:
                pass
            raise RuntimeError("LearningModelDevice 未返回 direct3d11_device")
        except Exception as e:
            logger.error(f"D3D11设备创建失败: {e}")
            raise RuntimeError(f"无法创建D3D11设备: {e}")
    def get_device(self):
        """获取D3D设备（设备不可用时尝试重建）"""
        if self.device is None:
            with self._lock:
                if self.device is None:
                    logger.warning("[D3D11] 设备不可用，尝试重新初始化...")
                    try:
                        self._init_device()
                        if self.device:
                            logger.info("[D3D11] 设备重新初始化成功")
                    except Exception as e:
                        logger.error(f"[D3D11] 设备重新初始化失败: {e}")
        return self.device
    def cleanup(self):
        """清理D3D设备资源"""
        try:
            if self.device:
                try:
                    self.device.close()
                except Exception:
                    pass
                self.device = None
            if self._learning_model_device:
                try:
                    self._learning_model_device.close()
                except Exception:
                    pass
                self._learning_model_device = None
        except Exception as e:
            logger.debug(f"清理D3D11设备失败: {e}")
class COMResourceTracker:
    """
    【完善的COM资源清理】追踪和清理WinRT/COM对象

    """

    _instance = None
    _lock = threading.Lock()

    # 【内存泄漏修复】限制待清理列表最大大小
    MAX_PENDING_CLEANUP = 50

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

        import weakref
        self._pending_cleanup = []  # 待清理的对象列表 [(weak_ref, close_callback, name)]
        self._cleanup_lock = threading.Lock()
        self._cleanup_count = 0
        self._last_cleanup_time = 0
        self._initialized = True
        logger.debug("[COMResourceTracker] 初始化完成")

    def track(self, obj, name: str = "unknown"):
        """
        追踪一个COM对象，当它变得不可达时会被清理

        Args:
            obj: WinRT/COM对象（必须有close()方法）
            name: 对象名称（用于日志）
        """
        if obj is None:
            return

        import weakref

        def cleanup_callback(weak_ref):
            """弱引用回调 - 当对象被GC时调用"""
            logger.debug(f"[COMResourceTracker] 对象已被GC回收: {name}")

        try:
            # 创建弱引用，当对象被GC时会调用cleanup_callback
            weak_ref = weakref.ref(obj, cleanup_callback)

            with self._cleanup_lock:
                self._pending_cleanup.append((weak_ref, name, time.time()))

            logger.debug(f"[COMResourceTracker] 追踪对象: {name}")
        except TypeError:
            # 某些COM对象不支持弱引用，直接忽略
            logger.debug(f"[COMResourceTracker] 对象不支持弱引用: {name}")

    def schedule_cleanup(self, obj, name: str = "unknown"):
        """
        Args:
            obj: WinRT/COM对象
            name: 对象名称
        """
        if obj is None:
            return

        import weakref

        # 【关键修复】先立即关闭对象，释放底层COM资源
        try:
            if hasattr(obj, 'close'):
                obj.close()
                logger.debug(f"[COMResourceTracker] 立即关闭: {name}")
        except Exception as e:
            logger.debug(f"[COMResourceTracker] 关闭失败: {name}: {e}")

        # 【内存泄漏修复】使用弱引用而非强引用，不阻止GC
        try:
            weak_ref = weakref.ref(obj)
            with self._cleanup_lock:
                # 限制待清理列表大小，超过时强制清理最老的
                if len(self._pending_cleanup) >= self.MAX_PENDING_CLEANUP:
                    # 强制清理前一半
                    half = len(self._pending_cleanup) // 2
                    self._pending_cleanup = self._pending_cleanup[half:]
                    logger.debug(f"[COMResourceTracker] 待清理列表过大，清理了{half}个旧条目")

                self._pending_cleanup.append((weak_ref, name, time.time()))
                self._cleanup_count += 1
        except TypeError:
            # 对象不支持弱引用，直接忽略（已经关闭了）
            pass

        logger.debug(f"[COMResourceTracker] 安排延迟清理: {name}")

    def do_cleanup(self, max_age_seconds: float = 0.5, force: bool = False):
        """
        Args:
            max_age_seconds: 只清理超过这个年龄的对象（秒）
            force: 强制清理所有对象，忽略年龄

        Returns:
            int: 清理的对象数量
        """
        import weakref
        current_time = time.time()
        cleaned_count = 0
        still_pending = []

        with self._cleanup_lock:
            for item in self._pending_cleanup:
                obj_or_ref, name, create_time = item
                age = current_time - create_time

                # 检查年龄
                if not force and age < max_age_seconds:
                    still_pending.append(item)
                    continue

                # 现在存储的都是弱引用（schedule_cleanup改进后）
                if isinstance(obj_or_ref, weakref.ref):
                    # 弱引用：检查对象是否还存在
                    obj = obj_or_ref()
                    if obj is None:
                        # 对象已被GC，清理成功
                        cleaned_count += 1
                        continue
                    else:
                        # 对象仍存在（可能还有其他引用），再次尝试关闭
                        try:
                            if hasattr(obj, 'close'):
                                obj.close()
                        except:
                            pass
                        cleaned_count += 1
                else:
                    # 兼容旧的强引用模式（不应该再出现）
                    obj = obj_or_ref
                    try:
                        if hasattr(obj, 'close'):
                            obj.close()
                            logger.debug(f"[COMResourceTracker] 已关闭: {name} (年龄: {age:.2f}s)")
                    except Exception as e:
                        logger.debug(f"[COMResourceTracker] 关闭失败: {name}: {e}")
                    cleaned_count += 1

            self._pending_cleanup = still_pending
            self._last_cleanup_time = current_time

        # 清理完成
        if cleaned_count > 0:
            logger.debug(f"[COMResourceTracker] 清理完成: {cleaned_count}个条目, 剩余: {len(still_pending)}个")

        return cleaned_count

    def get_pending_count(self) -> int:
        """获取待清理对象数量"""
        with self._cleanup_lock:
            return len(self._pending_cleanup)


def get_com_tracker() -> COMResourceTracker:
    """获取全局COM资源追踪器"""
    return COMResourceTracker()


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

    # 【内存泄漏修复】全局复用的numpy缓冲区
    # 避免每帧都分配新的numpy数组
    _reusable_buffer = None
    _reusable_buffer_shape = None
    _reusable_buffer_lock = threading.Lock()

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

    def _flush_gpu(self) -> bool:
        """
        Returns:
            bool: 是否成功执行Flush
        """
        if not self.device:
            return False

        try:
            if hasattr(self.device, 'device') and self.device.device:
                context = self.device.device.GetImmediateContext()
                if context:
                    # 【业界最佳实践】ClearState()确保所有GPU状态清空
                    context.ClearState()
                    # 【显存优化】Flush强制执行待命令
                    context.Flush()
                    # 交由 Python/COM 包装层自动释放，避免手动 Release 触发双重释放导致闪退
                    context = None
                    return True
        except Exception as e:
            logger.debug(f"[显存优化] GPU Flush失败(可忽略): {e}")

        return False

    def __init__(self, hwnd: int):
        """
        初始化捕获器

        Args:
            hwnd: 窗口句柄（可以是子窗口，会自动转换为顶层窗口）
        """
        if not WGC_AVAILABLE:
            raise ImportError("WGC库未安装，请安装: pip install winrt-Windows.Graphics winrt-Windows.Graphics.Capture winrt-Windows.Graphics.DirectX winrt-Windows.Foundation winrt-Windows.AI.MachineLearning")

        # 【关键修复】检查是否为子窗口，WGC只能捕获顶层窗口
        self.target_hwnd = hwnd  # 保存原始目标窗口（可能是子窗口）
        self.capture_hwnd = self._get_top_level_window(hwnd)  # WGC实际捕获的窗口（必须是顶层）

        if self.target_hwnd != self.capture_hwnd:
            logger.info(f"[INFO] 检测到子窗口 {self.target_hwnd}，WGC将捕获其父窗口 {self.capture_hwnd}")

        self.hwnd = self.capture_hwnd  # 兼容性：保持hwnd属性指向捕获窗口
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
        self._frame_seq = 0  # 【功能修复】帧序号，用于区分新旧帧
        self._frame_time = 0.0  # 【WGC静态窗口修复】帧捕获时间戳
        self._frame_is_new = False  # 【帧标签】True=新帧（未使用），False=旧帧（已使用）
        self.is_running = False
        self.capture_thread = None
        self._event_loop = None  # 后台线程的事件循环
        self._destroy_lock = threading.Lock()
        self._destroyed_recorded = False
        self._finalizer_thread = None
        self._frame_skip_count = 0  # 【修复闪退】帧跳过计数器，用于监控
        self._last_static_rebuild_ts = 0.0
        self._static_rebuild_cooldown_sec = 0.35
        self._last_failure_reason = ""
        self._last_failure_lock = threading.Lock()

        # 获取D3D设备
        self.device = D3D11DeviceManager().get_device()
        if self.device is None:
            raise RuntimeError("D3D11设备不可用")

        # 创建捕获项
        self._create_capture_item()

        # 【关键修复】立即启动后台捕获线程
        self._start_background_capture()

        # 【资源平衡监控】记录创建
        WGC_HWND_Capturer._inc_stat('capturers_created')
        logger.debug(f"[资源监控] 捕获器已创建 (HWND: {hwnd}), 统计: {WGC_HWND_Capturer.get_resource_stats()}")

    def _get_top_level_window(self, hwnd: int) -> int:
        """
        获取顶层窗口句柄
        如果hwnd是子窗口，返回其根窗口；否则返回hwnd本身
        """
        try:
            if not WIN32_AVAILABLE:
                return hwnd
            import win32gui
            # 使用GetAncestor获取根窗口（顶层窗口）
            # GA_ROOT = 2: 获取根窗口（向上遍历父窗口链直到顶层）
            root_hwnd = win32gui.GetAncestor(hwnd, 2)  # GA_ROOT = 2
            if root_hwnd and root_hwnd != hwnd:
                return root_hwnd
            return hwnd
        except Exception as e:
            logger.warning(f"获取顶层窗口失败: {e}，使用原始句柄")
            return hwnd

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
            try:
                target_pool.remove_frame_arrived(token)
            except Exception:
                pass
        self.frame_arrived_token = None
        self._frame_arrived_handler = None
        try:
            self._native_frame_arrived.clear()
        except Exception:
            pass

    def _attach_frame_arrived_handler(self, frame_pool) -> None:
        self._detach_frame_arrived_handler(frame_pool=frame_pool)
        if frame_pool is None:
            return

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


    async def _frame_to_numpy_async(self, frame) -> Optional[np.ndarray]:
        """
        将D3D11帧转换为numpy数组（异步）

        【内存泄漏修复 v3】
        强制关闭中间 COM 对象，避免底层资源泄漏。
        """
        software_bitmap = None
        bitmap_buffer = None
        reference = None
        surface = None
        mv = None

        def force_release_com(obj, name):
            """强制释放 COM 对象"""
            if obj is None:
                return
            try:
                if hasattr(obj, 'close'):
                    obj.close()
            except:
                pass
            try:
                if hasattr(obj, '__release__'):
                    obj.__release__()
            except:
                pass

        try:
            surface = frame.surface

            software_bitmap = await SoftwareBitmap.create_copy_from_surface_async(surface)

            if software_bitmap is None:
                return None

            height = software_bitmap.pixel_height
            width = software_bitmap.pixel_width

            if height <= 0 or width <= 0:
                logger.error(f"无效的帧尺寸: {width}x{height}")
                return None

            if width > 65535 or height > 65535:
                logger.error(f"帧尺寸超出合理范围: {width}x{height}")
                return None

            expected_size = height * width * 4

            bitmap_buffer = software_bitmap.lock_buffer(BitmapBufferAccessMode.READ)
            reference = bitmap_buffer.create_reference()

            try:
                mv = memoryview(reference)
                # 【优化】零拷贝：直接从memoryview创建numpy视图，再reshape
                # 只在最后做一次copy()，避免中间np.empty + 赋值的二次拷贝
                result = np.frombuffer(mv, dtype=np.uint8, count=expected_size).reshape((height, width, 4)).copy()
                mv.release()
                mv = None
                return result
            except (TypeError, BufferError):
                data_bytes = bytes(reference)
                if len(data_bytes) != expected_size:
                    logger.error(f"帧数据长度不匹配: 期望{expected_size}, 实际{len(data_bytes)}")
                    del data_bytes
                    return None
                result = np.frombuffer(data_bytes, dtype=np.uint8).reshape((height, width, 4)).copy()
                del data_bytes
                return result

        except Exception as e:
            logger.debug(f"异步帧转换失败: {e}", exc_info=True)
            return None
        finally:
            if mv is not None:
                try:
                    mv.release()
                except:
                    pass

            force_release_com(reference, "reference")
            reference = None

            force_release_com(bitmap_buffer, "bitmap_buffer")
            bitmap_buffer = None

            force_release_com(software_bitmap, "software_bitmap")
            software_bitmap = None

            force_release_com(surface, "surface")
            surface = None

    def request_new_frame(self, timeout_ms: float = 2000) -> Optional[np.ndarray]:
        """
        主动请求捕获新帧

        【帧标签系统】
        - 优先返回带有"新帧"标签的帧
        - 若超时且存在最近帧，则在年龄阈值内复用最近帧，避免并发窗口请求被“全量新帧”约束拖死

        Args:
            timeout_ms: 超时时间（毫秒）

        Returns:
            BGR格式的numpy数组，失败返回None
        """
        if not self.is_running:
            self._set_last_failure_reason("capturer_not_running")
            logger.error("[请求新帧] 后台捕获未运行")
            return None

        # 检查窗口是否仍然有效
        if WIN32_AVAILABLE:
            try:
                if not win32gui.IsWindow(self.hwnd):
                    self._set_last_failure_reason("invalid_hwnd")
                    logger.error(f"[请求新帧] 窗口已失效 (HWND: {self.hwnd})")
                    return None
            except Exception as e:
                logger.warning(f"[请求新帧] 检查窗口有效性失败: {e}")

        try:
            logger.debug(f"[请求新帧] 等待新帧...")

            # 记录可复用的最近帧快照（仅在本次新帧请求超时时兜底使用）
            fallback_frame = None
            fallback_seq = 0
            fallback_age_ms = -1.0
            with self.lock:
                if self.latest_frame is not None:
                    fallback_seq = int(self._frame_seq)
                    if self._frame_time > 0:
                        fallback_age_ms = max(0.0, (time.time() - float(self._frame_time)) * 1000.0)
                    if fallback_age_ms < 0.0 or fallback_age_ms <= float(_WGC_STALE_FRAME_MAX_AGE_MS):
                        try:
                            fallback_frame = self.latest_frame.copy()
                        except Exception:
                            fallback_frame = None
                self.frame_ready.clear()

            # 发送请求信号，通知后台线程
            self._frame_request.set()

            # 以内部轮询预算为下限，避免请求端先超时导致“明明在重建但调用已失败”
            effective_timeout_ms = max(float(timeout_ms), float(_WGC_MIN_REQUEST_TIMEOUT_MS))
            timeout_seconds = effective_timeout_ms / 1000.0

            # 直接等待帧就绪事件，减少轮询开销
            if self.frame_ready.wait(timeout=timeout_seconds):
                with self.lock:
                    # 【帧标签】只返回"新帧"
                    if self._frame_is_new and self.latest_frame is not None:
                        # 返回帧的副本
                        frame_copy = self.latest_frame.copy()
                        # 【帧标签】标记为"旧帧"
                        self._frame_is_new = False
                        self._set_last_failure_reason("")
                        logger.debug(f"[请求新帧] 获取新帧成功: seq={self._frame_seq}")
                        return frame_copy

            # 超时但存在可复用最近帧：返回最近帧，避免多窗口同批请求被“新帧”硬约束放大为失败。
            if fallback_frame is not None:
                self._set_last_failure_reason("")
                logger.warning(
                    f"[请求新帧] 等待超时，复用最近帧 (seq={fallback_seq}, age={int(max(0.0, fallback_age_ms))}ms, "
                    f"requested={int(timeout_ms)}ms)"
                )
                try:
                    self._frame_request.clear()
                except Exception:
                    pass
                return fallback_frame

            # 超时
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
        if WIN32_AVAILABLE:
            try:
                if not win32gui.IsWindow(self.hwnd):
                    self._set_last_failure_reason("invalid_hwnd")
                    logger.error(f"[获取帧] 窗口已失效 (HWND: {self.hwnd})")
                    return None
            except Exception as e:
                logger.warning(f"[获取帧] 检查窗口有效性失败: {e}")

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
        """在后台线程中启动持续捕获"""
        def capture_loop():
            """后台捕获循环"""
            # 初始化所有需要在finally中清理的资源
            frame_pool = None
            session = None
            loop = None

            try:
                # 在独立线程中创建事件循环
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._event_loop = loop  # 保存事件循环引用

                # 获取窗口尺寸
                size = self.item.size

                # 创建帧池（单缓冲低延迟）
                frame_pool = Direct3D11CaptureFramePool.create_free_threaded(
                    self.device,
                    DirectXPixelFormat.B8_G8_R8_A8_UINT_NORMALIZED,
                    1,
                    size,
                )
                WGC_HWND_Capturer._inc_stat('frame_pools_created')
                self._attach_frame_arrived_handler(frame_pool)

                # 创建并启动会话
                session = frame_pool.create_capture_session(self.item)
                WGC_HWND_Capturer._inc_stat('sessions_created')
                session.is_border_required = False
                session.is_cursor_capture_enabled = False
                session.start_capture()

                # 保存到实例
                with self.lock:
                    self.frame_pool = frame_pool
                    self.session = session
                    self.is_running = True

                logger.debug(f"[WGC] 后台捕获已启动 (HWND: {self.hwnd})")

                # 响应请求信号；无请求时仅在尚未建立最近帧快照时做首帧引导
                _last_frame_process_time = 0.0
                _frames_dropped_count = 0
                _frame_count_since_recreate = 0
                _recreate_every_n_frames = 100

                while self.is_running:
                    try:
                        with self.lock:
                            need_bootstrap_frame = self.latest_frame is None
                        has_request = self._frame_request.is_set() or need_bootstrap_frame

                        if not has_request:
                            loop.run_until_complete(asyncio.sleep(0.005))
                            continue

                        frame = frame_pool.try_get_next_frame()
                        if frame is None:
                            request_deadline = time.time() + (_WGC_REQUEST_ACTIVE_POLL_MS / 1000.0)
                            while self.is_running and frame is None and time.time() < request_deadline:
                                self._native_frame_arrived.wait(timeout=0.01)
                                self._native_frame_arrived.clear()
                                frame = frame_pool.try_get_next_frame()

                        # 积压时只保留最新帧
                        if frame is not None:
                            while True:
                                newer_frame = frame_pool.try_get_next_frame()
                                if newer_frame is None:
                                    break
                                frame.close()
                                frame = newer_frame

                        if frame is not None:
                            try:
                                np_frame = loop.run_until_complete(self._frame_to_numpy_async(frame))
                                if np_frame is not None:
                                    if len(np_frame.shape) == 3 and np_frame.shape[2] == 4:
                                        bgr_frame = cv2.cvtColor(np_frame, cv2.COLOR_BGRA2BGR)
                                        del np_frame
                                        np_frame = None
                                    else:
                                        bgr_frame = np_frame
                                        np_frame = None

                                    with self.lock:
                                        if self.latest_frame is not None:
                                            del self.latest_frame
                                            self.latest_frame = None
                                        self.latest_frame = bgr_frame
                                        self._frame_seq += 1
                                        self._frame_time = time.time()
                                        self._frame_is_new = True
                                        self.frame_ready.set()
                                        # 请求完成后清除请求标记，避免重复处理同一请求
                                        self._frame_request.clear()
                                        _last_frame_process_time = time.time()
                                        logger.debug(f"[后台捕获] 帧已更新: {bgr_frame.shape}, seq={self._frame_seq}, is_new=True")

                                # 定期recreate重置frame_pool缓冲区
                                _frame_count_since_recreate += 1
                                if _frame_count_since_recreate >= _recreate_every_n_frames:
                                    try:
                                        self._flush_gpu()
                                        size = self.item.size
                                        frame_pool.recreate(
                                            self.device,
                                            DirectXPixelFormat.B8_G8_R8_A8_UINT_NORMALIZED,
                                            1,
                                            size,
                                        )
                                        _frame_count_since_recreate = 0
                                        logger.debug(f"[显存优化] frame_pool.recreate() 完成，帧序号={self._frame_seq}")
                                    except Exception as recreate_err:
                                        logger.debug(f"[显存优化] recreate 失败: {recreate_err}")

                                if _frames_dropped_count > 0:
                                    logger.debug(f"[后台捕获] 帧率控制: 丢弃了 {_frames_dropped_count} 帧")
                                    _frames_dropped_count = 0
                            finally:
                                try:
                                    frame.close()
                                    del frame
                                    frame = None
                                except:
                                    pass
                        elif has_request:
                            # 静态窗口：请求时无新帧，重建 frame_pool/session 强制获取
                            now_ts = time.time()
                            if (now_ts - self._last_static_rebuild_ts) < self._static_rebuild_cooldown_sec:
                                loop.run_until_complete(asyncio.sleep(0.01))
                                continue
                            self._last_static_rebuild_ts = now_ts
                            logger.debug("[后台捕获] 静态窗口，重建frame_pool和session获取新帧")
                            try:
                                self._rebuild_count = getattr(self, "_rebuild_count", 0) + 1

                                if session is not None:
                                    try:
                                        session.close()
                                        WGC_HWND_Capturer._inc_stat('sessions_closed')
                                    except:
                                        pass
                                    del session
                                    session = None

                                if frame_pool is not None:
                                    try:
                                        self._detach_frame_arrived_handler(frame_pool=frame_pool)
                                        frame_pool.close()
                                        WGC_HWND_Capturer._inc_stat('frame_pools_closed')
                                    except:
                                        pass
                                    del frame_pool
                                    frame_pool = None

                                self._flush_gpu()

                                size = self.item.size
                                frame_pool = Direct3D11CaptureFramePool.create_free_threaded(
                                    self.device,
                                    DirectXPixelFormat.B8_G8_R8_A8_UINT_NORMALIZED,
                                    1,
                                    size,
                                )
                                WGC_HWND_Capturer._inc_stat('frame_pools_created')
                                self._attach_frame_arrived_handler(frame_pool)

                                session = frame_pool.create_capture_session(self.item)
                                WGC_HWND_Capturer._inc_stat('sessions_created')
                                session.is_border_required = False
                                session.is_cursor_capture_enabled = False
                                session.start_capture()

                                with self.lock:
                                    self.frame_pool = frame_pool
                                    self.session = session

                                frame = None
                                for _retry in range(_WGC_STATIC_REBUILD_RETRY_COUNT):
                                    loop.run_until_complete(
                                        asyncio.sleep(_WGC_STATIC_REBUILD_RETRY_INTERVAL_MS / 1000.0)
                                    )
                                    frame = frame_pool.try_get_next_frame()
                                    if frame is not None:
                                        break

                                if frame is not None:
                                    try:
                                        np_frame = loop.run_until_complete(self._frame_to_numpy_async(frame))
                                        if np_frame is not None:
                                            if len(np_frame.shape) == 3 and np_frame.shape[2] == 4:
                                                bgr_frame = cv2.cvtColor(np_frame, cv2.COLOR_BGRA2BGR)
                                                del np_frame
                                            else:
                                                bgr_frame = np_frame
                                            with self.lock:
                                                if self.latest_frame is not None:
                                                    del self.latest_frame
                                                    self.latest_frame = None
                                                self.latest_frame = bgr_frame
                                                self._frame_seq += 1
                                                self._frame_time = time.time()
                                                self._frame_is_new = True
                                                self.frame_ready.set()
                                                # 请求完成后清除请求标记，避免重复处理同一请求
                                                self._frame_request.clear()
                                                _last_frame_process_time = time.time()
                                                logger.debug(
                                                    f"[后台捕获] 静态窗口重建后获取新帧: {bgr_frame.shape}, seq={self._frame_seq}, is_new=True"
                                                )
                                    finally:
                                        try:
                                            frame.close()
                                        except:
                                            pass
                                else:
                                    logger.debug("[后台捕获] 静态窗口重建后仍无新帧")
                            except Exception as e:
                                logger.warning(f"[后台捕获] 重建frame_pool失败: {e}")
                                try:
                                    self._flush_gpu()
                                    size = self.item.size
                                    frame_pool = Direct3D11CaptureFramePool.create_free_threaded(
                                        self.device,
                                        DirectXPixelFormat.B8_G8_R8_A8_UINT_NORMALIZED,
                                        1,
                                        size,
                                    )
                                    WGC_HWND_Capturer._inc_stat('frame_pools_created')
                                    session = frame_pool.create_capture_session(self.item)
                                    WGC_HWND_Capturer._inc_stat('sessions_created')
                                    session.is_border_required = False
                                    session.is_cursor_capture_enabled = False
                                    session.start_capture()
                                    with self.lock:
                                        self.frame_pool = frame_pool
                                        self.session = session
                                    logger.info("[后台捕获] 重建失败后恢复捕获")
                                except Exception as recover_e:
                                    self._set_last_failure_reason(
                                        f"background_recover_failed:{type(recover_e).__name__}"
                                    )
                                    logger.error(f"[后台捕获] 恢复捕获失败: {recover_e}")
                                    self.is_running = False
                                    try:
                                        if 'frame_pool' in locals() and frame_pool is not None:
                                            try:
                                                frame_pool.close()
                                                WGC_HWND_Capturer._inc_stat('frame_pools_closed')
                                            except:
                                                pass
                                        if 'session' in locals() and session is not None:
                                            try:
                                                session.close()
                                                WGC_HWND_Capturer._inc_stat('sessions_closed')
                                            except:
                                                pass
                                    except:
                                        pass
                                    break

                        # 短暂休眠（有请求时更快响应）
                        sleep_time = 0.005 if has_request else 0.016
                        loop.run_until_complete(asyncio.sleep(sleep_time))

                    except Exception as e:
                        logger.debug(f"[后台捕获] 获取帧失败: {e}")
                        loop.run_until_complete(asyncio.sleep(0.1))

            except Exception as e:
                self._set_last_failure_reason(f"background_start_failed:{type(e).__name__}")
                logger.error(f"后台捕获失败: {e}")
                import traceback
                logger.error(traceback.format_exc())
            finally:
                logger.debug(f"[WGC-Finally] 开始清理后台线程资源 (HWND: {self.hwnd})")

                self.is_running = False

                with self.lock:
                    # 清理 session
                    if session is not None and self.session is session:
                        self.session = None
                        try:
                            session.close()
                            WGC_HWND_Capturer._inc_stat('sessions_closed')
                            logger.debug("[WGC-Finally] session已关闭")
                        except Exception as e:
                            logger.debug(f"[WGC-Finally] session关闭失败: {e}")

                    # 清理 frame_pool
                    if frame_pool is not None and self.frame_pool is frame_pool:
                        self.frame_pool = None
                        try:
                            self._detach_frame_arrived_handler(frame_pool=frame_pool)
                            frame_pool.close()
                            WGC_HWND_Capturer._inc_stat('frame_pools_closed')
                            logger.debug("[WGC-Finally] frame_pool已关闭")
                        except Exception as e:
                            logger.debug(f"[WGC-Finally] frame_pool关闭失败: {e}")

                    self._flush_gpu()

                # 清理事件循环
                if loop:
                    try:
                        if loop.is_running():
                            loop.call_soon_threadsafe(loop.stop)
                        loop.close()
                        logger.debug("[WGC-Finally] 事件循环已关闭")
                    except:
                        pass
                    finally:
                        self._event_loop = None

                logger.debug(f"[WGC-Finally] 后台线程资源清理完成 (HWND: {self.hwnd})")

        self.capture_thread = threading.Thread(target=capture_loop, daemon=True, name=f"WGC-{self.hwnd}")
        self.capture_thread.start()

        max_wait = 1.0
        wait_start = time.time()
        while not self.is_running and (time.time() - wait_start) < max_wait:
            time.sleep(0.01)

        if not self.is_running:
            raise RuntimeError("WGC 后台捕获启动失败")

    def _mark_destroyed_once(self) -> bool:
        """仅记录一次销毁统计，避免重复计数。"""
        with self._destroy_lock:
            if self._destroyed_recorded:
                return False
            self._destroyed_recorded = True
        WGC_HWND_Capturer._inc_stat('capturers_destroyed')
        return True

    def _start_async_finalize(self, capture_thread: threading.Thread):
        """后台等待捕获线程退出后做最终收尾，避免状态悬挂。"""
        with self._destroy_lock:
            existing = self._finalizer_thread
            if existing is not None and existing.is_alive():
                return

            def _finalize():
                try:
                    capture_thread.join(timeout=8.0)
                    if capture_thread.is_alive():
                        logger.error(f"[WGC-Stop] 捕获线程长时间未退出 (HWND: {self.hwnd})")
                        return
                    self.capture_thread = None
                    if self._mark_destroyed_once():
                        logger.debug(f"[WGC-Stop] 捕获器延迟销毁完成 (HWND: {self.hwnd})")
                except Exception as finalize_err:
                    logger.debug(f"[WGC-Stop] 延迟销毁失败: {finalize_err}")

            self._finalizer_thread = threading.Thread(
                target=_finalize,
                daemon=True,
                name=f"WGC-Finalize-{self.hwnd}",
            )
            self._finalizer_thread.start()

    def stop(self):
        """
        停止捕获并释放所有资源

        【资源清理策略 - 单一责任原则】
        - stop() 负责：触发线程退出 + 等待线程结束 + 清理非后台线程创建的资源
        - finally 负责：清理后台线程创建的 session/frame_pool/event_loop
        - 这样避免了重复清理和资源计数不准的问题
        """
        logger.debug(f"[WGC-Stop] 开始停止捕获器 (HWND: {self.hwnd})")

        # 1. 设置标志，触发后台线程退出
        self.is_running = False

        # 2. 等待后台线程结束（线程会在finally中清理session/frame_pool）
        # 线程join()添加timeout保护，防止无限等待hang
        thread_still_alive = False
        if self.capture_thread and self.capture_thread.is_alive():
            try:
                # 唤醒后台循环，避免线程在无请求分支长时间停留
                self._frame_request.set()
            except Exception:
                pass
            try:
                self.capture_thread.join(timeout=3.0)  # 给更充足时间让finally执行完成
                thread_still_alive = self.capture_thread.is_alive()
                if thread_still_alive:
                    logger.error(f"[WGC-Stop] 捕获线程未能在3秒内停止 (HWND: {self.hwnd})，继续执行兜底清理")
                    # 再次尝试停止事件循环并唤醒线程，然后短暂等待一次
                    try:
                        loop = getattr(self, "_event_loop", None)
                        if loop is not None and (not loop.is_closed()):
                            loop.call_soon_threadsafe(loop.stop)
                    except Exception:
                        pass
                    try:
                        self._frame_request.set()
                    except Exception:
                        pass
                    self.capture_thread.join(timeout=0.8)
                    thread_still_alive = self.capture_thread.is_alive()
            except Exception as e:
                logger.debug(f"[WGC-Stop] 线程join失败: {e}")

        # 3. 线程已结束或超时，现在清理残留资源（以防finally未执行或执行失败）
        try:
            lock_timeout = 0.5 if thread_still_alive else 2.0
            if self.lock.acquire(timeout=lock_timeout):
                try:
                    # 【安全检查】如果session/frame_pool仍存在，说明finally未成功清理，这里补救
                    # 注意：正常情况下这些应该已被finally清理，这只是保险措施
                    if self.session is not None:
                        logger.warning(f"[WGC-Stop] session未被finally清理，补救清理")
                        try:
                            self.session.close()
                            WGC_HWND_Capturer._inc_stat('sessions_closed')
                        except:
                            pass
                        self.session = None

                    if self.frame_pool is not None:
                        logger.warning(f"[WGC-Stop] frame_pool未被finally清理，补救清理")
                        try:
                            self._detach_frame_arrived_handler(frame_pool=self.frame_pool)
                            self.frame_pool.close()
                            WGC_HWND_Capturer._inc_stat('frame_pools_closed')
                        except:
                            pass
                        self.frame_pool = None

                    # 【显存优化】强制GPU完成所有操作并释放显存
                    if self._flush_gpu():
                        logger.debug(f"[WGC-Stop] GPU已Flush")

                    # 清理GraphicsCaptureItem（这个是在构造函数创建的，由stop负责清理）
                    if self.item:
                        try:
                            self.item.close()
                        except:
                            pass
                        self.item = None

                    # 清理帧引用
                    if self.latest_frame is not None:
                        del self.latest_frame
                        self.latest_frame = None

                finally:
                    self.lock.release()
            else:
                logger.warning(f"[WGC-Stop] 获取锁超时，跳过同步兜底清理 (HWND: {self.hwnd})")

        except Exception as e:
            logger.error(f"[WGC-Stop] 清理资源异常: {e}")

        # 4. 清理线程引用和销毁统计
        if thread_still_alive:
            logger.warning(f"[WGC-Stop] 捕获线程仍在退出中，已安排延迟回收 (HWND: {self.hwnd})")
            if self.capture_thread is not None:
                self._start_async_finalize(self.capture_thread)
        else:
            self.capture_thread = None
            if self._mark_destroyed_once():
                logger.debug(f"[WGC-Stop] 捕获器已销毁 (HWND: {self.hwnd}), 统计: {WGC_HWND_Capturer.get_resource_stats()}")


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
        self._active_capture_requests = 0
        self._last_capture_request_ts = 0.0

        # 【内存泄漏修复】启动定期清理线程
        self._cleanup_stop_event = threading.Event()
        self._cleanup_thread = threading.Thread(target=self._periodic_cleanup, daemon=True, name="WGC-Cleanup")
        self._cleanup_thread.start()
        logger.debug("[WGC] 定期清理线程已启动")
        self._high_mem_no_resource_hits = 0
        self._high_mem_persistent_hits_to_reclaim = 2
        self._full_reclaim_lock = threading.Lock()
        self._no_resource_last_reclaim_ts = 0.0
        self._no_resource_high_mem_last_log_ts = 0.0
        self._no_resource_reclaim_cooldown_sec = float(_WGC_NO_RESOURCE_RECLAIM_COOLDOWN_SEC)
        self._no_resource_high_mem_log_interval_sec = float(_WGC_NO_RESOURCE_HIGH_MEM_LOG_INTERVAL_SEC)
        self._last_capture_failure_reason = ""
        self._last_capture_failure_lock = threading.Lock()

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

    def _begin_capture_request(self) -> None:
        with self.lock:
            self._active_capture_requests += 1
            self._last_capture_request_ts = time.time()

    def _end_capture_request(self) -> None:
        with self.lock:
            if self._active_capture_requests > 0:
                self._active_capture_requests -= 1

    def _get_capture_activity_snapshot(self) -> Tuple[int, float]:
        with self.lock:
            return self._active_capture_requests, self._last_capture_request_ts

    def _run_process_trim(self):
        """执行进程级内存回收（GC + 堆修剪 + 工作集修剪）。"""
        try:
            gc.collect()
        except Exception:
            pass

        if os.name != 'nt':
            return

        try:
            import ctypes
            msvcrt = ctypes.CDLL('msvcrt')
            if hasattr(msvcrt, '_heapmin'):
                msvcrt._heapmin()
        except Exception:
            pass

        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            psapi = ctypes.windll.psapi
            current_process = kernel32.GetCurrentProcess()
            psapi.EmptyWorkingSet(current_process)
        except Exception:
            pass

    def _hard_reclaim_no_active_resources(self):
        """无活跃捕获资源但内存持续偏高时执行硬回收。"""
        try:
            self.cache.clear()
        except Exception:
            pass

        try:
            get_com_tracker().do_cleanup(max_age_seconds=0.0, force=True)
        except Exception:
            pass

        try:
            D3D11DeviceManager().cleanup()
        except Exception:
            pass

        self._run_process_trim()

    def _get_main_and_children_rss_mb(self) -> Tuple[float, float]:
        """获取主进程RSS和子进程RSS（MB）。"""
        try:
            import psutil
            process = psutil.Process()
            main_rss_mb = float(process.memory_info().rss) / 1024 / 1024
            children_rss_mb = 0.0
            try:
                for child in process.children(recursive=True):
                    try:
                        children_rss_mb += float(child.memory_info().rss) / 1024 / 1024
                    except Exception:
                        continue
            except Exception:
                pass
            return main_rss_mb, children_rss_mb
        except Exception:
            return 0.0, 0.0

    def _full_reclaim_on_high_memory(
        self,
        memory_before_mb: float,
        force_reclaim: bool = False,
        recreate_device: bool = True
    ) -> Tuple[float, float, int]:
        """
        高内存时执行完整回收闭环：
        1. 停止并移除所有捕获器
        2. 清理帧缓存
        3. 强制清理COM延迟队列
        4. 释放D3D设备
        5. 执行进程级trim
        """
        _enter_wgc_rebuild()
        try:
            active_requests, _ = self._get_capture_activity_snapshot()
            if active_requests > 0:
                if not force_reclaim:
                    # 正在执行截图请求时禁止做“完整回收”，避免关闭中的对象被并发访问
                    self._run_process_trim()
                    return memory_before_mb, 0.0, 0

                # 强制回收路径：不使用硬编码超时，等待在途请求全部完成后再执行销毁重建
                while active_requests > 0:
                    if self._cleanup_stop_event.is_set():
                        break
                    time.sleep(0.01)
                    active_requests, _ = self._get_capture_activity_snapshot()
                if active_requests > 0:
                    self._run_process_trim()
                    return memory_before_mb, 0.0, 0

            snapshot = []
            if self.lock.acquire(timeout=2.0):
                try:
                    snapshot = list(self.capturers.items())
                    self.capturers.clear()
                    self.capturer_last_used.clear()
                finally:
                    self.lock.release()

            stopped = 0
            for _, capturer in snapshot:
                try:
                    capturer.stop()
                    stopped += 1
                except Exception:
                    pass

            try:
                self.cache.clear()
            except Exception:
                pass

            try:
                get_com_tracker().do_cleanup(max_age_seconds=0.0, force=True)
            except Exception:
                pass

            try:
                D3D11DeviceManager().cleanup()
            except Exception:
                pass
            if recreate_device:
                try:
                    # 立即重建设备链，确保“完整销毁重建”闭环在本次清理内完成
                    D3D11DeviceManager().get_device()
                except Exception:
                    pass

            self._run_process_trim()
            time.sleep(0.05)
            self._run_process_trim()

            memory_after_mb, _ = self._get_main_and_children_rss_mb()
            if memory_after_mb <= 0:
                memory_after_mb = memory_before_mb

            freed_mb = memory_before_mb - memory_after_mb
            return memory_after_mb, freed_mb, stopped
        finally:
            _leave_wgc_rebuild()

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

        event_loop = getattr(capturer, "_event_loop", None)
        if event_loop is None:
            return False, "事件循环为空"
        try:
            if event_loop.is_closed():
                return False, "事件循环已关闭"
        except Exception as loop_err:
            return False, f"事件循环状态异常: {loop_err}"

        return True, "ok"

    def _periodic_cleanup(self):
        """定期清理闲置和失效的捕获器"""
        import time
        # 【高频OCR优化】调整清理参数，更积极地检测和清理内存
        IDLE_TIMEOUT = 30  # 【优化】从60秒降到30秒，更快释放闲置捕获器
        CHECK_INTERVAL = 1  # 每秒检查，保证高内存即时触发
        HEALTH_CHECK_INTERVAL = 3  # 【优化】健康检查间隔从5秒改为3秒
        FORCE_GC_INTERVAL = 30  # 【优化】从60秒改为30秒，更频繁GC
        MEMORY_CHECK_INTERVAL = int(_WGC_MAIN_MEMORY_CHECK_INTERVAL_SEC)
        MEMORY_THRESHOLD_MB = int(_WGC_MAIN_MEMORY_THRESHOLD_MB)
        last_health_check = 0
        last_force_gc = time.time()
        last_memory_check = 0

        while not self._cleanup_stop_event.is_set():
            try:
                if self._cleanup_stop_event.wait(CHECK_INTERVAL):
                    break

                current_time = time.time()
                to_cleanup = []
                unhealthy_capturers = []

                with self.lock:
                    # 1. 检查闲置的捕获器
                    for hwnd, last_used in list(self.capturer_last_used.items()):
                        if current_time - last_used > IDLE_TIMEOUT:
                            to_cleanup.append((hwnd, "闲置超时"))

                    # 2. 检查不健康的捕获器
                    if current_time - last_health_check > HEALTH_CHECK_INTERVAL:
                        last_health_check = current_time
                        for hwnd, capturer in list(self.capturers.items()):
                            is_healthy, unhealthy_reason = self._check_capturer_health(capturer)
                            if not is_healthy:
                                unhealthy_capturers.append((hwnd, unhealthy_reason))
                                continue

                        # 【资源平衡监控】仅在有问题时输出
                        resource_stats = WGC_HWND_Capturer.get_resource_stats()
                        if resource_stats['capturers_active'] != len(self.capturers):
                            logger.warning(f"[资源不平衡警告] 计数器显示{resource_stats['capturers_active']}个活跃捕获器，实际{len(self.capturers)}个，统计: {resource_stats}")
                        elif len(self.capturers) > 0 or any(resource_stats.values()):
                            logger.debug(f"[资源平衡检查] 活跃捕获器: {len(self.capturers)}, 统计: {resource_stats}")

                # 在锁外清理闲置的捕获器
                for hwnd, reason in to_cleanup:
                    try:
                        with self.lock:
                            if hwnd in self.capturers:
                                self.capturers[hwnd].stop()
                                del self.capturers[hwnd]
                            if hwnd in self.capturer_last_used:
                                del self.capturer_last_used[hwnd]
                        logger.info(f"[WGC自动清理] 清理捕获器 HWND={hwnd} ({reason})")
                    except Exception as e:
                        logger.debug(f"[WGC自动清理] 清理失败: {e}")

                # 清理不健康的捕获器（让下次capture_window时重新创建）
                for hwnd, reason in unhealthy_capturers:
                    try:
                        with self.lock:
                            if hwnd in self.capturers:
                                try:
                                    self.capturers[hwnd].stop()
                                except:
                                    pass
                                del self.capturers[hwnd]
                            if hwnd in self.capturer_last_used:
                                del self.capturer_last_used[hwnd]
                        logger.warning(f"[WGC健康检查] 清理不健康捕获器 HWND={hwnd} ({reason})")
                    except Exception as e:
                        logger.debug(f"[WGC健康检查] 清理失败: {e}")

                # 3. 清理完成

                # 【完善的清理】定期执行COM资源追踪器的延迟清理
                try:
                    com_tracker = get_com_tracker()
                    pending_count = com_tracker.get_pending_count()
                    if pending_count > 0:
                        cleaned = com_tracker.do_cleanup(max_age_seconds=1.0)
                        if cleaned > 0:
                            logger.debug(f"[WGC定期清理] COM资源追踪器清理了{cleaned}个对象，剩余{com_tracker.get_pending_count()}个")
                except Exception as e:
                    logger.debug(f"[WGC定期清理] COM资源清理异常: {e}")

                # 更新GC时间记录
                if current_time - last_force_gc > FORCE_GC_INTERVAL:
                    last_force_gc = current_time
                    self._run_process_trim()

                # 【长期运行优化】内存监控和自动清理
                if current_time - last_memory_check > MEMORY_CHECK_INTERVAL:
                    try:
                        import psutil
                        main_rss_mb, children_rss_mb = self._get_main_and_children_rss_mb()

                        if main_rss_mb > MEMORY_THRESHOLD_MB:
                            active_capturers = 0
                            if self.lock.acquire(timeout=0.5):
                                try:
                                    active_capturers = len(self.capturers)
                                finally:
                                    self.lock.release()
                            stats = WGC_HWND_Capturer.get_resource_stats()
                            active_requests, _ = self._get_capture_activity_snapshot()
                            has_active_wgc_resources = bool(
                                active_requests > 0
                                or active_capturers > 0
                                or int(stats.get('frame_pools_active', 0) or 0) > 0
                                or int(stats.get('sessions_active', 0) or 0) > 0
                            )

                            # 无活跃WGC资源时，不执行完整销毁重建；仅做低频轻量回收，避免误触发循环重建。
                            if not has_active_wgc_resources:
                                self._high_mem_no_resource_hits += 1
                            else:
                                self._high_mem_no_resource_hits = 0

                            if not has_active_wgc_resources:
                                now_ts = current_time
                                reached_hits = self._high_mem_no_resource_hits >= self._high_mem_persistent_hits_to_reclaim
                                cooldown_elapsed = (
                                    (now_ts - self._no_resource_last_reclaim_ts)
                                    >= self._no_resource_reclaim_cooldown_sec
                                )
                                if reached_hits and cooldown_elapsed:
                                    self._hard_reclaim_no_active_resources()
                                    self._high_mem_no_resource_hits = 0
                                    self._no_resource_last_reclaim_ts = now_ts
                                    try:
                                        main_rss_mb, children_rss_mb = self._get_main_and_children_rss_mb()
                                    except Exception:
                                        pass

                                if (
                                    (now_ts - self._no_resource_high_mem_last_log_ts)
                                    >= self._no_resource_high_mem_log_interval_sec
                                ):
                                    self._no_resource_high_mem_last_log_ts = now_ts
                                    logger.info(
                                        f"[WGC内存告警] 主进程内存{main_rss_mb:.1f}MB超过阈值{MEMORY_THRESHOLD_MB}MB，"
                                        f"但当前无WGC活跃资源，跳过完整销毁重建 | 子进程RSS={children_rss_mb:.1f}MB(不计入阈值), "
                                        f"active_requests={active_requests}, capturers={active_capturers}, "
                                        f"frame_pools_active={stats.get('frame_pools_active', 0)}, "
                                        f"sessions_active={stats.get('sessions_active', 0)}"
                                    )
                                continue

                            logger.warning(
                                f"[WGC内存告警] 主进程内存{main_rss_mb:.1f}MB超过阈值{MEMORY_THRESHOLD_MB}MB，"
                                f"立即触发完整销毁重建 | 子进程RSS={children_rss_mb:.1f}MB(不计入阈值), "
                                f"active_requests={active_requests}, capturers={active_capturers}, "
                                f"frame_pools_active={stats.get('frame_pools_active', 0)}, "
                                f"sessions_active={stats.get('sessions_active', 0)}"
                            )
                            if self._full_reclaim_lock.acquire(blocking=False):
                                try:
                                    memory_after_mb, freed_mb, stopped = self._full_reclaim_on_high_memory(
                                        main_rss_mb,
                                        force_reclaim=True,
                                        recreate_device=True,
                                    )
                                    active_capturers_after = 0
                                    if self.lock.acquire(timeout=0.5):
                                        try:
                                            active_capturers_after = len(self.capturers)
                                        finally:
                                            self.lock.release()
                                    stats_after = WGC_HWND_Capturer.get_resource_stats()
                                    logger.info(
                                        f"[WGC内存告警] 完整清理完成，释放{freed_mb:.1f}MB，当前{memory_after_mb:.1f}MB，"
                                        f"回收捕获器={stopped}，"
                                        f"capturers={active_capturers_after}，frame_pools_active={stats_after.get('frame_pools_active', 0)}，"
                                        f"sessions_active={stats_after.get('sessions_active', 0)}"
                                    )
                                except Exception as cleanup_err:
                                    logger.error(f"[WGC内存告警] 完整清理失败: {cleanup_err}")
                                finally:
                                    self._full_reclaim_lock.release()
                            else:
                                logger.debug("[WGC内存告警] 完整清理正在进行，跳过本次触发")

                        else:
                            pass
                    except ImportError:
                        pass  # psutil未安装，跳过内存监控
                    except Exception as e:
                        logger.debug(f"内存监控失败: {e}")

                    last_memory_check = current_time

            except Exception as e:
                logger.error(f"[WGC自动清理] 异常: {e}")
                if self._cleanup_stop_event.wait(60):
                    break

        logger.debug("[WGC自动清理] 定期清理循环已退出")

    def capture_window(
        self,
        hwnd: int,
        use_cache: bool = False,
        client_area_only: bool = True,
        request_timeout_ms: Optional[int] = None,
    ) -> Optional[np.ndarray]:
        """
        捕获窗口（支持遮挡窗口）

        Args:
            hwnd: 窗口句柄
            use_cache: 是否使用缓存（默认False，获取最新帧）
            client_area_only: 是否只捕获客户区

        Returns:
            BGRA格式的numpy数组，失败返回None
        """
        start_time = time.time()
        capturer = None  # 用于finally块清理
        self._set_last_capture_failure_reason("")

        default_total_budget_ms = int(_WGC_REQUEST_FRAME_TIMEOUT_MS) * 2
        if request_timeout_ms is not None:
            try:
                total_budget_ms = int(request_timeout_ms)
            except Exception:
                total_budget_ms = default_total_budget_ms
        else:
            total_budget_ms = default_total_budget_ms
        total_budget_ms = max(600, min(30000, total_budget_ms))

        gate_wait_timeout_ms = int(
            max(
                int(_WGC_REBUILD_GATE_WAIT_MIN_MS),
                min(
                    int(_WGC_REBUILD_GATE_WAIT_MAX_MS),
                    (total_budget_ms * int(_WGC_REBUILD_GATE_WAIT_RATIO_PERCENT)) // 100,
                ),
            )
        )
        # 若正在执行完整销毁重建，仅等待当前请求预算内的闸门时间，避免无限阻塞。
        gate_wait_ok = wait_wgc_rebuild_complete(timeout=(float(gate_wait_timeout_ms) / 1000.0))
        if not gate_wait_ok:
            self._set_last_capture_failure_reason("rebuild_gate_wait_timeout")
            logger.warning(
                f"[WGC] 等待重建闸门超时，跳过本次抓帧 (HWND: {hwnd}, wait={gate_wait_timeout_ms}ms)"
            )
            return None
        self._begin_capture_request()

        try:
            # 验证窗口
            if not WIN32_AVAILABLE or not win32gui.IsWindow(hwnd):
                self._set_last_capture_failure_reason("invalid_hwnd")
                logger.error(f"无效的窗口句柄: {hwnd}")
                # 【修复闪退】如果窗口已失效，清理对应的捕获器
                with self.lock:
                    if hwnd in self.capturers:
                        try:
                            self.capturers[hwnd].stop()
                        except:
                            pass
                        del self.capturers[hwnd]
                    if hwnd in self.capturer_last_used:
                        del self.capturer_last_used[hwnd]
                return None

            # 缓存key
            cache_key = f"wgc_{hwnd}_{client_area_only}"

            # 检查缓存
            if use_cache:
                cached_frame = self.cache.get(cache_key)
                if cached_frame is not None:
                    self.stats.cache_hits += 1
                    self._set_last_capture_failure_reason("")
                    return cached_frame

            # 【关键修复】复用捕获器，不要每次都销毁重建
            # 只有在捕获器不存在或已失效时才创建新的
            with self.lock:
                capturer = None
                if hwnd in self.capturers:
                    # 检查已有捕获器是否仍在运行
                    existing_capturer = self.capturers[hwnd]
                    is_healthy, unhealthy_reason = self._check_capturer_health(existing_capturer)
                    if is_healthy:
                        # 复用已有的捕获器
                        capturer = existing_capturer
                        logger.debug(f"[WGC] 复用现有捕获器 (HWND: {hwnd})")
                    else:
                        # 捕获器已失效，清理并重建
                        logger.warning(f"[WGC] 捕获器已失效({unhealthy_reason})，重新创建 (HWND: {hwnd})")
                        try:
                            existing_capturer.stop()  # 确保清理资源
                        except:
                            pass
                        del self.capturers[hwnd]
                        if hwnd in self.capturer_last_used:
                            del self.capturer_last_used[hwnd]

                # 如果没有可用的捕获器，创建新的
                if capturer is None:
                    # 【内存管理】检查捕获器数量，如果超过最大限制则清理最久未使用的
                    if len(self.capturers) >= self.max_capturers:
                        self._cleanup_least_recently_used()

                    if not WGC_AVAILABLE:
                        self._set_last_capture_failure_reason("wgc_unavailable")
                        raise RuntimeError("WGC库未安装，请安装: pip install winrt-Windows.Graphics winrt-Windows.Graphics.Capture winrt-Windows.Graphics.DirectX winrt-Windows.Foundation winrt-Windows.AI.MachineLearning")

                    logger.debug(f"[WGC] 创建新捕获器 (HWND: {hwnd})")
                    try:
                        capturer = WGC_HWND_Capturer(hwnd)
                    except Exception as create_error:
                        self._set_last_capture_failure_reason(
                            f"capturer_create_failed:{type(create_error).__name__}"
                        )
                        raise
                    self.capturers[hwnd] = capturer

                # 【并发一致性】在同一把锁内更新使用时间戳
                self.capturer_last_used[hwnd] = time.time()

            # 根据use_cache决定是请求新帧还是使用已有帧
            first_request_timeout_ms = int(_WGC_REQUEST_FRAME_TIMEOUT_MS)
            rebuild_request_timeout_ms = int(_WGC_REQUEST_FRAME_TIMEOUT_MS)
            allow_rebuild_retry = True
            if request_timeout_ms is not None:
                elapsed_ms = int(max(0.0, (time.time() - start_time) * 1000.0))
                remaining_budget_ms = max(300, total_budget_ms - elapsed_ms)
                min_retry_budget_ms = int((_WGC_MIN_REQUEST_TIMEOUT_MS * 2) + int(_WGC_REBUILD_RETRY_GUARD_MS))
                if remaining_budget_ms >= min_retry_budget_ms:
                    first_request_timeout_ms = max(
                        int(_WGC_MIN_REQUEST_TIMEOUT_MS),
                        int(remaining_budget_ms * 0.58),
                    )
                    first_request_timeout_ms = min(
                        first_request_timeout_ms,
                        int(
                            remaining_budget_ms
                            - int(_WGC_MIN_REQUEST_TIMEOUT_MS)
                            - int(_WGC_REBUILD_RETRY_GUARD_MS)
                        ),
                    )
                    rebuild_request_timeout_ms = max(
                        int(_WGC_MIN_REQUEST_TIMEOUT_MS),
                        int(
                            remaining_budget_ms
                            - first_request_timeout_ms
                            - int(_WGC_REBUILD_RETRY_GUARD_MS)
                        ),
                    )
                    allow_rebuild_retry = True
                else:
                    first_request_timeout_ms = max(
                        int(_WGC_MIN_REQUEST_TIMEOUT_MS),
                        int(remaining_budget_ms - int(_WGC_REBUILD_RETRY_GUARD_MS)),
                    )
                    rebuild_request_timeout_ms = 0
                    allow_rebuild_retry = False

            if not use_cache:
                logger.debug(f"[WGC] 禁用缓存，主动请求新帧 (HWND: {hwnd})")
                frame = capturer.request_new_frame(timeout_ms=float(first_request_timeout_ms))
            else:
                logger.debug(f"[WGC] 启用缓存，使用已有帧 (HWND: {hwnd})")
                frame = capturer.get_frame(timeout_ms=200, wait_for_new=False)

            if frame is None:
                first_failure_reason = self._extract_capturer_failure_reason(
                    capturer,
                    "request_new_frame_failed" if not use_cache else "get_frame_failed",
                )
                self._set_last_capture_failure_reason(first_failure_reason)
                if not allow_rebuild_retry:
                    logger.warning(
                        f"[WGC] 捕获失败，当前预算不足以执行二次重建重试 (HWND: {hwnd})"
                    )
                    return None
                logger.warning(f"[WGC] 捕获失败，尝试重建捕获器 (HWND: {hwnd})")
                try:
                    with self.lock:
                        if hwnd in self.capturers:
                            try:
                                self.capturers[hwnd].stop()
                            except:
                                pass
                            del self.capturers[hwnd]
                        if hwnd in self.capturer_last_used:
                            del self.capturer_last_used[hwnd]

                        # 重新创建捕获器
                        logger.info(f"[WGC] 重建捕获器 (HWND: {hwnd})")
                        capturer = WGC_HWND_Capturer(hwnd)
                        self.capturers[hwnd] = capturer
                        self.capturer_last_used[hwnd] = time.time()

                    # 重试捕获
                    time.sleep(0.03)  # 30ms等待捕获器就绪
                    if not use_cache:
                        frame = capturer.request_new_frame(timeout_ms=float(rebuild_request_timeout_ms))
                    else:
                        frame = capturer.get_frame(timeout_ms=200, wait_for_new=False)

                    if frame is not None:
                        self._set_last_capture_failure_reason("")
                        logger.info(f"[WGC] 重建后捕获成功 (HWND: {hwnd})")
                    else:
                        second_failure_reason = self._extract_capturer_failure_reason(
                            capturer,
                            "request_new_frame_failed_after_rebuild" if not use_cache else "get_frame_failed_after_rebuild",
                        )
                        self._set_last_capture_failure_reason(f"after_rebuild:{second_failure_reason}")
                        logger.error(f"[WGC] 重建后仍然捕获失败 (HWND: {hwnd})")
                        return None
                except Exception as retry_error:
                    self._set_last_capture_failure_reason(
                        f"capturer_rebuild_failed:{type(retry_error).__name__}"
                    )
                    logger.error(f"[WGC] 重建捕获器失败: {retry_error}")
                    return None

            # 裁剪客户区
            if client_area_only and WIN32_AVAILABLE:
                # 【修复】传递capturer以获取target_hwnd和capture_hwnd信息
                frame = self._crop_to_client_area(hwnd, frame, capturer)
                if frame is None:
                    self._set_last_capture_failure_reason("crop_failed")
                    logger.error(f"裁剪客户区失败 (HWND: {hwnd})")
                    # 【关键修复】裁剪失败也不清理捕获器，可能只是临时问题
                    return None

            # 更新缓存
            if use_cache and frame is not None:
                self.cache.set(cache_key, frame)

            # 更新统计
            elapsed_ms = (time.time() - start_time) * 1000
            self.stats.total_captures += 1
            self.stats.wgc_captures += 1
            self.stats.total_time_ms += elapsed_ms

            logger.debug(f"WGC捕获成功: {frame.shape if frame is not None else None}, {elapsed_ms:.1f}ms")

            # 【关键修复】不要清理捕获器！让捕获器保持运行，持续产生新帧
            # 捕获器会在以下情况被清理：
            # 1. 捕获失败时（超时、异常）
            # 2. 窗口关闭时（通过cleanup_wgc()）
            # 3. 程序退出时

            self._set_last_capture_failure_reason("")
            return frame

        except Exception as e:
            self._set_last_capture_failure_reason(f"capture_exception:{type(e).__name__}")
            logger.error(f"捕获异常: {e}", exc_info=True)
            # 【修复】异常时也不立即清理，异常可能是临时的
            return None
        finally:
            self._end_capture_request()

    def _cleanup_capturer(self, hwnd: int):
        """
        清理指定窗口的捕获器

        Args:
            hwnd: 窗口句柄
        """
        try:
            with self.lock:
                if hwnd in self.capturers:
                    cleanup_capturer = self.capturers[hwnd]
                    # 调用stop方法完整清理所有资源
                    cleanup_capturer.stop()
                    del self.capturers[hwnd]
                    # 同时清理使用时间戳
                    if hwnd in self.capturer_last_used:
                        del self.capturer_last_used[hwnd]
                    logger.debug(f"[WGC清理] 已完全销毁捕获器并释放所有资源 (HWND: {hwnd})")
        except Exception as e:
            logger.debug(f"清理捕获器失败: {e}")

    def _cleanup_least_recently_used(self):
        """
        清理最久未使用的捕获器（LRU策略）
        当捕获器数量超过最大限制时调用
        """
        if not self.capturer_last_used:
            return

        # 找出最久未使用的hwnd
        lru_hwnd = min(self.capturer_last_used, key=self.capturer_last_used.get)
        lru_time = self.capturer_last_used[lru_hwnd]
        idle_time = time.time() - lru_time

        logger.info(f"[内存管理-LRU] 清理最久未使用的捕获器 (HWND: {lru_hwnd}, 闲置时间: {idle_time:.1f}秒)")

        # 清理该捕获器
        try:
            if lru_hwnd in self.capturers:
                self.capturers[lru_hwnd].stop()
                del self.capturers[lru_hwnd]
            del self.capturer_last_used[lru_hwnd]
        except Exception as e:
            logger.debug(f"LRU清理失败: {e}")

    def _crop_to_client_area(self, hwnd: int, frame: np.ndarray, capturer: WGC_HWND_Capturer = None) -> Optional[np.ndarray]:
        """
        裁剪到客户区 - 使用DWM API获取精确的窗口frame边框

        【重要】如果捕获器捕获的是父窗口（因为WGC不支持子窗口），
        则hwnd可能是子窗口，需要特殊处理坐标转换
        """
        try:
            import ctypes
            from ctypes import wintypes

            # 【关键修复】从capturer获取target_hwnd和capture_hwnd
            # 如果hwnd是原始目标窗口（可能是子窗口），则需要特殊处理
            if capturer is not None and hasattr(capturer, 'target_hwnd') and hasattr(capturer, 'capture_hwnd'):
                target_hwnd = capturer.target_hwnd
                capture_hwnd = capturer.capture_hwnd
                if target_hwnd != capture_hwnd:
                    # 子窗口情况：需要将子窗口的客户区映射到父窗口捕获的坐标系
                    logger.info(f"【子窗口裁剪模式】目标窗口: {target_hwnd}, 捕获窗口: {capture_hwnd}")
                    return self._crop_child_window(hwnd, frame, capture_hwnd)

            # 正常情况：裁剪到指定窗口的客户区
            return self._crop_normal_window(hwnd, frame)

        except Exception as e:
            logger.warning(f"裁剪客户区失败: {e}")
            logger.exception(e)
            return frame

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

            logger.info(f"【子窗口裁剪开始】")
            logger.info(f"  子窗口HWND: {child_hwnd}")
            logger.info(f"  父窗口HWND: {capture_hwnd}")

            # 获取DPI缩放因子和进程DPI感知状态
            dpi_scale = 1.0
            is_dpi_aware = False
            try:
                user32 = ctypes.windll.user32
                # 检查进程DPI感知状态
                if hasattr(user32, 'GetAwarenessFromDpiAwarenessContext') and hasattr(user32, 'GetThreadDpiAwarenessContext'):
                    try:
                        context = user32.GetThreadDpiAwarenessContext()
                        awareness = user32.GetAwarenessFromDpiAwarenessContext(context)
                        is_dpi_aware = awareness >= 2
                    except Exception:
                        pass

                if hasattr(user32, 'GetDpiForWindow'):
                    dpi = user32.GetDpiForWindow(capture_hwnd)
                    if dpi > 0:
                        dpi_scale = dpi / 96.0
                        logger.info(f"  DPI: {dpi}, 缩放因子: {dpi_scale:.2f}, DPI感知: {is_dpi_aware}")
            except Exception:
                pass

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

            logger.info(f"  子窗口窗口矩形(屏幕): {child_window_rect}")
            logger.info(
                f"  子窗口客户区(逻辑): {child_client_rect}, 屏幕跨度: {child_w_screen}x{child_h_screen}, "
                f"物理估算: {child_w_physical}x{child_h_physical}"
            )
            logger.info(f"  子窗口客户区屏幕坐标: {child_screen_pos}")

            # 获取父窗口（捕获窗口）的DWM边界
            logger.info(f"  【获取父窗口信息】")
            capture_window_rect = win32gui.GetWindowRect(capture_hwnd)
            capture_client_rect = win32gui.GetClientRect(capture_hwnd)
            capture_client_pos = win32gui.ClientToScreen(capture_hwnd, (0, 0))
            capture_client_end = win32gui.ClientToScreen(
                capture_hwnd,
                (capture_client_rect[2], capture_client_rect[3]),
            )
            capture_client_w_screen = max(0, int(capture_client_end[0]) - int(capture_client_pos[0]))
            capture_client_h_screen = max(0, int(capture_client_end[1]) - int(capture_client_pos[1]))

            logger.info(f"  父窗口窗口矩形(屏幕): {capture_window_rect}")
            logger.info(f"  父窗口客户区(本地): {capture_client_rect}")
            logger.info(f"  父窗口客户区屏幕坐标: {capture_client_pos}")

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
                    logger.info(f"  父窗口DWM边界(屏幕): {capture_dwm_rect}")
                    logger.info(f"  父窗口DWM尺寸: {rect.right-rect.left}x{rect.bottom-rect.top}")

                    # 【关键】计算WGC捕获的基准点
                    # WGC可能捕获的是DWM边界，也可能是窗口矩形
                    logger.info(f"  【计算WGC捕获基准点】")
                    frame_h, frame_w = frame.shape[:2]
                    logger.info(f"  WGC捕获帧尺寸: {frame_w}x{frame_h}")

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
                        logger.info(f"  [OK] WGC捕获的是DWM边界(逻辑像素)，基准点: {screenshot_base_pos}")
                    elif abs(frame_w - client_w) <= 4 and abs(frame_h - client_h) <= 4:
                        # WGC返回逻辑像素的客户区
                        screenshot_base_pos = capture_client_pos
                        wgc_is_logical = True
                        logger.info(f"  [OK] WGC捕获的是客户区(逻辑像素)，基准点: {screenshot_base_pos}")
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
                            logger.info(f"  [OK] WGC捕获的是DWM边界(物理像素)，基准点: {screenshot_base_pos}")
                        elif abs(frame_w - client_w_physical_cmp) <= 4 and abs(frame_h - client_h_physical_cmp) <= 4:
                            # WGC返回物理像素的客户区
                            screenshot_base_pos = capture_client_pos
                            wgc_is_logical = False
                            logger.info(f"  [OK] WGC捕获的是客户区(物理像素)，基准点: {screenshot_base_pos}")
                        else:
                            # 未知，默认使用DWM边界，假设逻辑像素
                            screenshot_base_pos = (rect.left, rect.top)
                            wgc_is_logical = True
                            logger.warning(f"  [WARNING] WGC捕获尺寸不匹配任何已知边界")
                            logger.warning(f"    DWM(逻辑): {dwm_w}x{dwm_h}, 物理: {dwm_w_physical}x{dwm_h_physical}")
                            logger.warning(f"    客户区(逻辑): {client_w}x{client_h}, 物理: {client_w_physical_cmp}x{client_h_physical_cmp}")
                            logger.warning(f"    WGC: {frame_w}x{frame_h}")
                            logger.warning(f"    默认使用DWM边界(逻辑像素)作为基准点: {screenshot_base_pos}")

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
                        logger.info("  WGC使用逻辑像素坐标系，按屏幕端点计算裁剪范围")
                    elif is_dpi_aware:
                        logger.info("  WGC使用物理像素坐标系，按屏幕端点计算裁剪范围")
                    else:
                        logger.info("  WGC使用物理像素坐标系，按屏幕端点和DPI缩放计算裁剪范围")
                else:
                    raise Exception(f"DwmGetWindowAttribute 调用失败：{result}")

            except Exception as e:
                logger.error(f"DWM API 调用失败: {e}")
                raise

            logger.info(f"  父窗口WindowRect: {capture_window_rect}, wgc_is_logical: {wgc_is_logical}")

            logger.info(f"  【开始裁剪子窗口区域】")
            logger.info(f"  子窗口偏移(逻辑): ({offset_x}, {offset_y}), 最终偏移: ({offset_x_physical}, {offset_y_physical})")
            logger.info(f"  子窗口尺寸(逻辑): {child_w}x{child_h}, 物理: {child_w_physical}x{child_h_physical}")
            logger.info(f"  WGC捕获帧尺寸: {frame.shape[1]}x{frame.shape[0]}")

            # 【修复】边界检查：确保不会超出父窗口捕获的帧尺寸
            frame_h, frame_w = frame.shape[:2]

            if wgc_is_logical:
                logger.info(f"  WGC使用逻辑像素，目标裁剪尺寸: {target_w}x{target_h}")
            else:
                logger.info(f"  WGC使用物理像素，目标裁剪尺寸: {target_w}x{target_h}")

            # 确保裁剪边界不超出帧尺寸
            crop_x = max(0, min(offset_x_physical, frame_w - 1))
            crop_y = max(0, min(offset_y_physical, frame_h - 1))
            crop_w = min(target_w, frame_w - crop_x)
            crop_h = min(target_h, frame_h - crop_y)

            logger.info(f"  实际裁剪区域: 起点=({crop_x}, {crop_y}), 尺寸={crop_w}x{crop_h}")
            logger.info(f"  裁剪范围: frame[{crop_y}:{crop_y + crop_h}, {crop_x}:{crop_x + crop_w}]")

            if crop_x != offset_x_physical or crop_y != offset_y_physical or crop_w != target_w or crop_h != target_h:
                logger.warning(f"  [WARNING] 子窗口边界修正发生:")
                logger.warning(f"    期望裁剪区域: ({offset_x_physical}, {offset_y_physical}) {target_w}x{target_h}")
                logger.warning(f"    实际裁剪区域: ({crop_x}, {crop_y}) {crop_w}x{crop_h}")
                logger.warning(f"    丢失: 左={offset_x_physical - crop_x}px, 上={offset_y_physical - crop_y}px, 右={(offset_x_physical + target_w) - (crop_x + crop_w)}px, 下={(offset_y_physical + target_h) - (crop_y + crop_h)}px")
                if (offset_y_physical + target_h) > frame_h:
                    logger.error(f"    [ERROR] 底部被截断！期望高度={offset_y_physical + target_h}, 但帧高度只有{frame_h}, 少了{(offset_y_physical + target_h) - frame_h}像素")

            # 裁剪子窗口区域
            # 必须复制切片，避免返回视图导致整帧内存被上层长期引用
            cropped = frame[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w].copy()
            logger.info(f"  [OK] 裁剪完成，输出尺寸: {cropped.shape[1]}x{cropped.shape[0]}")

            return cropped

        except Exception as e:
            logger.error(f"子窗口裁剪失败: {e}", exc_info=True)
            return frame

    def _crop_normal_window(self, hwnd: int, frame: np.ndarray) -> Optional[np.ndarray]:
        """
        正常窗口裁剪：裁剪到窗口的客户区
        """
        try:
            import ctypes
            from ctypes import wintypes

            # 获取窗口DPI和进程DPI感知状态
            dpi_scale = 1.0
            is_dpi_aware = False
            try:
                user32 = ctypes.windll.user32
                # 检查进程DPI感知状态
                if hasattr(user32, 'GetAwarenessFromDpiAwarenessContext') and hasattr(user32, 'GetThreadDpiAwarenessContext'):
                    try:
                        context = user32.GetThreadDpiAwarenessContext()
                        awareness = user32.GetAwarenessFromDpiAwarenessContext(context)
                        # 0=Unaware, 1=System, 2=PerMonitor
                        is_dpi_aware = awareness >= 2
                    except Exception:
                        pass

                if hasattr(user32, 'GetDpiForWindow'):
                    dpi = user32.GetDpiForWindow(hwnd)
                    if dpi > 0:
                        dpi_scale = dpi / 96.0
            except Exception:
                pass

            # 获取客户区矩形
            client_rect = win32gui.GetClientRect(hwnd)
            client_w = client_rect[2]
            client_h = client_rect[3]

            # 如果进程是Per-Monitor DPI感知，GetClientRect返回的已经是物理像素
            # 否则需要转换
            if is_dpi_aware:
                client_w_physical = client_w
                client_h_physical = client_h
            else:
                client_w_physical = int(client_w * dpi_scale)
                client_h_physical = int(client_h * dpi_scale)

            # 获取客户区在屏幕上的位置与右下角端点
            client_screen_pos = win32gui.ClientToScreen(hwnd, (0, 0))
            client_screen_end = win32gui.ClientToScreen(hwnd, (client_rect[2], client_rect[3]))
            client_w_screen = max(0, int(client_screen_end[0]) - int(client_screen_pos[0]))
            client_h_screen = max(0, int(client_screen_end[1]) - int(client_screen_pos[1]))

            # 尝试使用DwmGetWindowAttribute获取扩展frame边界
            try:
                dwmapi = ctypes.windll.dwmapi
                DWMWA_EXTENDED_FRAME_BOUNDS = 9

                rect = wintypes.RECT()
                result = dwmapi.DwmGetWindowAttribute(
                    wintypes.HWND(hwnd),
                    wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
                    ctypes.byref(rect),
                    ctypes.sizeof(rect)
                )

                if result == 0:
                    # DWM返回窗口的实际可见边界（不含Windows 10的不可见阴影边框）
                    # 在Per-Monitor DPI感知模式下，DWM返回的坐标已经是物理像素
                    # 在非DPI感知模式下，返回的是逻辑像素
                    dwm_rect = (rect.left, rect.top, rect.right, rect.bottom)

                    # 客户区相对于DWM frame的偏移
                    # 两者都是相同的坐标空间（都是物理或都是逻辑）
                    border_left = client_screen_pos[0] - dwm_rect[0]
                    border_top = client_screen_pos[1] - dwm_rect[1]

                    logger.info(f"【WGC客户区裁剪 - 使用DWM】")
                    logger.info(f"  DWM扩展frame边界: {dwm_rect}")
                    logger.info(f"  ClientToScreen: {client_screen_pos}")
                    logger.info(f"  边框偏移: left={border_left}, top={border_top}")
                else:
                    raise Exception(f"DwmGetWindowAttribute 调用失败，错误码：{result}")

            except Exception as e:
                logger.error(f"DWM API 调用失败: {e}")
                raise

            # 【修复】边界检查：确保不会超出WGC捕获的帧尺寸
            frame_h, frame_w = frame.shape[:2]

            logger.info(f"  WGC捕获尺寸: {frame_w}x{frame_h}")
            logger.info(f"  GetClientRect: {client_w}x{client_h}, 屏幕跨度: {client_w_screen}x{client_h_screen}, DPI缩放: {dpi_scale:.2f}, DPI感知: {is_dpi_aware}")
            logger.info(f"  客户区物理尺寸: {client_w_physical}x{client_h_physical}")
            logger.info(f"  边框偏移(逻辑): left={border_left}, top={border_top}")

            # 判断WGC返回的坐标空间（逻辑像素 vs 物理像素）
            # 先与逻辑尺寸比较
            wgc_is_logical = True  # 默认假设逻辑像素
            if abs(frame_w - client_w_screen) <= 4 and abs(frame_h - client_h_screen) <= 4:
                wgc_is_logical = True
                logger.info(f"  [OK] WGC捕获尺寸≈客户区逻辑尺寸({client_w_screen}x{client_h_screen})，WGC使用逻辑像素")
            elif abs(frame_w - client_w_physical) <= 4 and abs(frame_h - client_h_physical) <= 4:
                wgc_is_logical = False
                logger.info(f"  [OK] WGC捕获尺寸≈客户区物理尺寸({client_w_physical}x{client_h_physical})，WGC使用物理像素")
            else:
                # 尝试比较DWM边界
                try:
                    dwm_w = dwm_rect[2] - dwm_rect[0]
                    dwm_h = dwm_rect[3] - dwm_rect[1]
                    dwm_w_physical = int(dwm_w * dpi_scale) if not is_dpi_aware else dwm_w
                    dwm_h_physical = int(dwm_h * dpi_scale) if not is_dpi_aware else dwm_h
                    if abs(frame_w - dwm_w) <= 4 and abs(frame_h - dwm_h) <= 4:
                        wgc_is_logical = True
                        logger.info(f"  [OK] WGC捕获尺寸≈DWM逻辑尺寸({dwm_w}x{dwm_h})，WGC使用逻辑像素")
                    elif abs(frame_w - dwm_w_physical) <= 4 and abs(frame_h - dwm_h_physical) <= 4:
                        wgc_is_logical = False
                        logger.info(f"  [OK] WGC捕获尺寸≈DWM物理尺寸({dwm_w_physical}x{dwm_h_physical})，WGC使用物理像素")
                    else:
                        wgc_is_logical = True
                        logger.warning(f"  [WARNING] WGC尺寸不匹配，默认使用逻辑像素坐标系")
                except:
                    wgc_is_logical = True
                    logger.warning(f"  [WARNING] 无法确定WGC坐标系，默认使用逻辑像素")

            convert_to_physical = (not wgc_is_logical) and (not is_dpi_aware)
            border_left_final, target_w = _resolve_relative_axis_bounds(
                client_screen_pos[0],
                client_screen_end[0],
                dwm_rect[0],
                dpi_scale=dpi_scale,
                apply_scale=convert_to_physical,
            )
            border_top_final, target_h = _resolve_relative_axis_bounds(
                client_screen_pos[1],
                client_screen_end[1],
                dwm_rect[1],
                dpi_scale=dpi_scale,
                apply_scale=convert_to_physical,
            )
            if wgc_is_logical:
                logger.info(f"  WGC逻辑模式: 边框=({border_left_final}, {border_top_final}), 目标={target_w}x{target_h}")
            else:
                logger.info(f"  WGC物理模式: 边框=({border_left_final}, {border_top_final}), 目标={target_w}x{target_h}")

            # 如果WGC已经返回了客户区内容（无边框），直接返回
            if abs(frame_w - target_w) <= 4 and abs(frame_h - target_h) <= 4:
                logger.info(f"  [OK] WGC捕获尺寸≈目标尺寸，WGC已返回客户区，直接返回")
                return frame

            # 如果WGC捕获尺寸<=客户区且无边框，说明WGC已返回正确内容
            if (frame_w <= target_w and frame_h <= target_h and
                border_left_final <= 0 and border_top_final <= 0):
                logger.info(f"  [OK] WGC捕获尺寸≤目标尺寸且无边框，直接返回")
                return frame

            # WGC捕获了整个窗口（包含边框），需要裁剪到客户区
            crop_x = max(0, min(border_left_final, frame_w - 1))
            crop_y = max(0, min(border_top_final, frame_h - 1))
            crop_w = min(target_w, frame_w - crop_x)
            crop_h = min(target_h, frame_h - crop_y)

            # 验证裁剪区域是否合理
            can_crop_safely = (crop_x + crop_w <= frame_w and crop_y + crop_h <= frame_h and
                             crop_w > 0 and crop_h > 0)

            if not can_crop_safely:
                logger.warning(f"  [WARNING] 无法安全裁剪：")
                logger.warning(f"    WGC捕获尺寸: {frame_w}x{frame_h}")
                logger.warning(f"    计算的裁剪区域: ({crop_x}, {crop_y}) {crop_w}x{crop_h}")
                logger.warning(f"    边框偏移: left={border_left_final}, top={border_top_final}")
                logger.warning(f"    返回完整帧由上层处理")
                return frame

            logger.info(f"  需要裁剪边框: 起点=({crop_x}, {crop_y}), 尺寸={crop_w}x{crop_h}")

            if crop_x != border_left_final or crop_y != border_top_final or crop_w != target_w or crop_h != target_h:
                logger.warning(f"  [WARNING] 边界修正发生:")
                logger.warning(f"    期望裁剪区域: ({border_left_final}, {border_top_final}) {target_w}x{target_h}")
                logger.warning(f"    实际裁剪区域: ({crop_x}, {crop_y}) {crop_w}x{crop_h}")
                if (crop_y + crop_h) < (border_top_final + target_h):
                    logger.error(f"    [ERROR] 底部被截断！")

            # 裁剪（从WGC捕获中提取客户区）
            # 必须复制切片，避免返回视图导致整帧内存被上层长期引用
            cropped = frame[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w].copy()

            logger.info(f"  [OK] 裁剪完成，输出尺寸: {cropped.shape[1]}x{cropped.shape[0]}")

            return cropped

        except Exception as e:
            logger.error(f"正常窗口裁剪失败: {e}", exc_info=True)
            return frame

    def cleanup(self, hwnd: int = None):
        """
        清理资源

        Args:
            hwnd: 指定窗口句柄只清理该窗口的capturer，None则清理所有
        """
        if hwnd is not None:
            # 只清理指定窗口
            with self.lock:
                if hwnd in self.capturers:
                    try:
                        self.capturers[hwnd].stop()
                        del self.capturers[hwnd]
                        # 【内存泄漏修复】同时清理使用时间戳
                        if hwnd in self.capturer_last_used:
                            del self.capturer_last_used[hwnd]
                        logger.debug(f"[清理] 已清理窗口{hwnd}的WGC捕获器")
                    except Exception as e:
                        logger.debug(f"清理窗口{hwnd}的捕获器失败: {e}")
        else:
            # 【内存泄漏修复】先停止定期清理线程
            if hasattr(self, "_cleanup_stop_event"):
                self._cleanup_stop_event.set()
            cleanup_thread = getattr(self, "_cleanup_thread", None)
            if cleanup_thread and cleanup_thread.is_alive():
                try:
                    # 等待一个完整检查周期，确保清理线程有机会自然退出
                    cleanup_thread.join(timeout=4.0)
                    if cleanup_thread.is_alive():
                        logger.warning("[清理] 定期清理线程未能在4秒内停止，继续执行主清理链路")
                    else:
                        logger.debug("[清理] 定期清理线程已停止")
                except Exception as e:
                    logger.debug(f"[清理] 清理线程join失败: {e}")
            self._cleanup_thread = None

            # 清理所有
            with self.lock:
                for hwnd_key, capturer in list(self.capturers.items()):
                    try:
                        capturer.stop()
                    except:
                        pass
                self.capturers.clear()
                # 【内存泄漏修复】清理所有使用时间戳
                self.capturer_last_used.clear()

            self.cache.clear()
            try:
                D3D11DeviceManager().cleanup()
            except Exception:
                pass
            self._run_process_trim()

            logger.info("[OK] WGC资源已完全清理")

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
    if _global_capture is None:
        with _global_lock:
            if _global_capture is None:
                _global_capture = OptimizedWGCCapture()
    return _global_capture


def get_existing_global_capture() -> Optional[OptimizedWGCCapture]:
    return _global_capture


def get_last_wgc_capture_failure_reason() -> str:
    capture = get_existing_global_capture()
    if capture is None:
        return ""
    try:
        return str(capture.get_last_capture_failure_reason() or "")
    except Exception:
        return ""


def capture_window_wgc_optimized(
    hwnd: int,
    client_area_only: bool = True,
    use_cache: bool = False,
    request_timeout_ms: Optional[int] = None,
) -> Optional[np.ndarray]:
    """
    优化的WGC窗口捕获（全局接口）

    Args:
        hwnd: 窗口句柄
        client_area_only: 是否只捕获客户区
        use_cache: 是否使用缓存（默认False，获取最新帧）

    Returns:
        BGR格式的numpy数组
    """
    capture = get_global_capture()
    return capture.capture_window(
        hwnd=hwnd,
        use_cache=use_cache,
        client_area_only=client_area_only,
        request_timeout_ms=request_timeout_ms,
    )


def cleanup_wgc(hwnd: int = None, cleanup_d3d: bool = False):
    """清理WGC资源

    Args:
        hwnd: 指定窗口句柄，None表示清理全部
        cleanup_d3d: 是否同时清理D3D设备（默认False，D3D单例可复用）
    """
    global _global_capture
    if _global_capture:
        if hwnd is not None:
            _global_capture.cleanup(hwnd=hwnd)
        else:
            _global_capture.cleanup()
            _global_capture = None

    # 指定窗口清理时，不处理全局D3D
    if hwnd is not None:
        return

    # 只在明确要求时才清理D3D设备（程序退出时）
    if cleanup_d3d:
        try:
            # 避免“仅为清理而创建”D3D设备：如果从未初始化，则跳过
            if getattr(D3D11DeviceManager, "_instance", None) is not None:
                D3D11DeviceManager().cleanup()
        except:
            pass


# 自动清理（程序退出时清理D3D设备）
import atexit
atexit.register(lambda: cleanup_wgc(cleanup_d3d=True))


if __name__ == "__main__":
    # 测试代码
    import win32gui

    logging.basicConfig(level=logging.DEBUG)

    logger.info("=" * 60)
    logger.info("优化WGC HWND捕获测试")
    logger.info("=" * 60)

    # 查找窗口
    hwnd = win32gui.FindWindow(None, "二重螺旋")
    if not hwnd:
        logger.info("[ERROR] 未找到二重螺旋窗口")
        exit(1)

    logger.info(f"\n目标窗口: HWND={hwnd}")

    # 测试捕获
    logger.info("\n开始捕获测试...")
    start = time.time()

    frame = capture_window_wgc_optimized(hwnd, client_area_only=True)

    elapsed = (time.time() - start) * 1000
    logger.info(f"[OK] 捕获耗时: {elapsed:.1f}ms")

    if frame is not None:
        logger.info(f"[OK] 帧尺寸: {frame.shape}")
        if CV2_AVAILABLE:
            cv2.imwrite("wgc_optimized_test.png", frame)
            logger.info("[OK] 已保存: wgc_optimized_test.png")
    else:
        logger.info("[ERROR] 捕获失败")

    # 统计信息
    capture = get_global_capture()
    stats = capture.get_stats()
    logger.info("\n统计信息:")
    for key, value in stats.items():
        logger.info(f"  {key}: {value}")

    cleanup_wgc()
    logger.info("\n" + "=" * 60)


# ==================== 兼容性接口 ====================

def capture_window_wgc(
    hwnd: int,
    client_area_only: bool = True,
    use_cache: bool = False,
    request_timeout_ms: Optional[int] = None,
) -> Optional[np.ndarray]:
    """兼容旧代码的捕获接口"""
    return capture_window_wgc_optimized(
        hwnd=hwnd,
        client_area_only=client_area_only,
        use_cache=use_cache,
        request_timeout_ms=request_timeout_ms,
    )


def clear_wgc_cache(hwnd: int = None):
    """兼容旧代码的缓存清理接口"""
    capture = get_existing_global_capture()
    if capture:
        capture.clear_cache(hwnd)


def shutdown_wgc():
    """兼容旧代码的关闭接口"""
    cleanup_wgc(cleanup_d3d=False)

