#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多进程OCR工作进程 - 独立进程运行OCR引擎
每个进程维护自己的OCR引擎实例，避免GIL限制

【内存优化】此模块设计为独立运行，不依赖main.py，避免加载GUI库
【Nuitka修复】PySide6 的阻止已在 main.py 开头通过环境变量检测处理
"""

import sys
import os

# 确保独立入口下能稳定导入项目包（services.*, utils.*）
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_CURRENT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 【内存优化】设置ONNX Runtime环境变量，减少内存占用
# 必须在导入任何可能加载ONNX Runtime的模块之前设置
# 【关键】禁用ONNX Runtime的内存arena（内存池），强制每次分配后释放
os.environ['ORT_DISABLE_MEMORY_ARENA'] = '1'
# 【内存优化】禁用ONNX Runtime的内存高效注意力机制（减少内存缓存）
os.environ['ORT_DISABLE_MEMORY_EFFICIENT_ATTENTION'] = '1'
# 【内存优化】禁用ONNX Runtime的融合注意力（减少临时内存）
os.environ['ORT_DISABLE_FUSED_ATTENTION'] = '1'
# 【内存优化】设置malloc的环境变量，让系统更积极地释放内存给OS
os.environ['MALLOC_TRIM_THRESHOLD_'] = '65536'  # 64KB阈值时trim
os.environ['MALLOC_MMAP_THRESHOLD_'] = '65536'  # 64KB以上使用mmap
os.environ['MALLOC_MMAP_MAX_'] = '65536'  # 允许大量mmap分配

# 检查 PySide6 是否已加载（用于诊断）
pyside6_already_loaded = 'PySide6.QtWidgets' in sys.modules

import logging
import multiprocessing as mp
import time
import numpy as np
from typing import Dict, List, Optional, Tuple
import traceback
import gc


def _setup_ocr_worker_logging(process_id: str = None):
    """Disable OCR worker file logging to avoid generating per-process log files."""
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(logging.NullHandler())
    root_logger.setLevel(logging.CRITICAL)
    root_logger.propagate = False
    return logging.getLogger(__name__)


logger = logging.getLogger(__name__)


def _read_int_env(name: str, default: int, min_value: int) -> int:
    """安全读取整型环境变量"""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    return value if value >= min_value else min_value


def _format_exception_detail(exc: Exception) -> str:
    """统一格式化异常，便于写日志和跨进程传递。"""
    if exc is None:
        return ""
    exc_type = type(exc).__name__
    message = str(exc).strip()
    return f"{exc_type}: {message}" if message else exc_type


def _extract_ocr_engine_init_detail(ocr_engine) -> str:
    """尽量从 OCR 引擎实例中提取初始化失败详情。"""
    if ocr_engine is None:
        return ""

    try:
        if hasattr(ocr_engine, "get_service_info"):
            service_info = ocr_engine.get_service_info()
            if isinstance(service_info, dict):
                detail = str(service_info.get("init_error") or "").strip()
                if detail:
                    return detail
    except Exception:
        pass

    try:
        detail = str(getattr(ocr_engine, "_init_error", "") or "").strip()
        if detail:
            return detail
    except Exception:
        pass

    return ""


class OCRWorkerProcess:
    """OCR工作进程 - 在独立进程中运行"""

    def __init__(self, process_id: str, request_queue: mp.Queue, response_queue: mp.Queue):
        """
        初始化OCR工作进程

        Args:
            process_id: 进程ID
            request_queue: 请求队列（接收OCR任务）
            response_queue: 响应队列（返回OCR结果）
        """
        self.process_id = process_id
        self.request_queue = request_queue
        self.response_queue = response_queue
        self.ocr_engine = None
        self.is_running = False
        self._last_request_timestamp = 0  # 【画面变动修复】记录最后请求的时间戳
        self._init_error_detail = ""

    def initialize_ocr_engine(self) -> bool:
        """初始化OCR引擎（在子进程中执行）"""
        self._init_error_detail = ""
        try:
            from services.fastdeploy_ocr_service import get_fastdeploy_ocr_service

            # 每个进程创建自己的OCR引擎实例
            self.ocr_engine = get_fastdeploy_ocr_service()

            if not self.ocr_engine.initialize():
                self._init_error_detail = _extract_ocr_engine_init_detail(self.ocr_engine) or "未返回具体错误"
                logger.error(f"[{self.process_id}] OCR引擎初始化失败: {self._init_error_detail}")
                return False

            self._init_error_detail = ""
            logger.warning(f"[{self.process_id}] OCR引擎初始化成功")
            return True

        except Exception as e:
            engine_detail = _extract_ocr_engine_init_detail(self.ocr_engine)
            detail = _format_exception_detail(e)
            if engine_detail and engine_detail not in detail:
                detail = f"{detail} | 引擎详情: {engine_detail}"
            self._init_error_detail = detail
            logger.error(f"[{self.process_id}] OCR引擎初始化异常: {detail}")
            return False

    def process_ocr_request(self, request: Dict) -> Dict:
        """
        处理OCR请求

        Args:
            request: OCR请求 {'request_id', 'window_hwnd', 'window_title', 'image'/'shm_name', 'confidence', 'timestamp'}

        Returns:
            Dict: OCR响应 {'request_id', 'window_hwnd', 'window_title', 'results', 'success', 'processing_time', 'error'}
        """
        request_id = request.get('request_id', 'unknown')
        window_hwnd = request.get('window_hwnd', 0)
        window_title = request.get('window_title', 'unknown')
        start_time = time.time()

        image = None  # 【内存泄漏修复】确保在finally中可以删除
        image_bytes = None
        image_shm = None

        try:
            # 【优化】支持共享内存接收大图像
            use_shared_memory = request.get('use_shared_memory', False)

            if use_shared_memory:
                # 【修复OCR识别失败】从共享内存读取图像需要异常处理
                try:
                    import multiprocessing.shared_memory as shm
                    shm_name = request.get('shm_name')
                    image_shape = request.get('image_shape')
                    image_dtype = request.get('image_dtype')

                    # 打开共享内存
                    image_shm = shm.SharedMemory(name=shm_name)
                    # 创建numpy数组视图
                    shm_view = np.ndarray(image_shape, dtype=image_dtype, buffer=image_shm.buf)
                    # 【关键】socket请求是同步串行，主进程在收到响应前不会unlink，直接零拷贝使用共享内存
                    image = shm_view
                except Exception as shm_err:
                    error_msg = f"读取共享内存失败: {shm_err}"
                    logger.error(f"[{self.process_id}] {error_msg}")
                    return {
                        'request_id': request_id,
                        'process_id': self.process_id,
                        'window_hwnd': window_hwnd,
                        'window_title': window_title,
                        'results': [],
                        'success': False,
                        'processing_time': time.time() - start_time,
                        'error': error_msg
                    }
            else:
                # 【修复OCR识别失败】提取图像数据需要异常处理
                try:
                    # 【关键修复】使用pop而不是get，从request中移除image引用
                    image_bytes = request.pop('image', None)
                    image_shape = request.get('image_shape')
                    image_dtype = request.get('image_dtype')

                    if image_bytes is None:
                        error_msg = "缺少图像数据"
                        logger.error(f"[{self.process_id}] {error_msg}")
                        return {
                            'request_id': request_id,
                            'process_id': self.process_id,
                            'window_hwnd': window_hwnd,
                            'window_title': window_title,
                            'results': [],
                            'success': False,
                            'processing_time': time.time() - start_time,
                            'error': error_msg
                        }

                    # 反序列化numpy数组
                    # 【内存泄漏修复】np.frombuffer返回的是视图，需要copy才能释放原始bytes
                    image_view = np.frombuffer(image_bytes, dtype=image_dtype).reshape(image_shape)
                    image = np.copy(image_view)
                    del image_view

                    # 【内存泄漏修复】立即删除字节数据，只保留numpy数组
                    del image_bytes
                    image_bytes = None

                    # 【内存泄漏修复】从request中移除其他大数据字段
                    request.pop('image_shape', None)
                    request.pop('image_dtype', None)
                except Exception as deserialize_err:
                    error_msg = f"反序列化图像数据失败: {deserialize_err}"
                    logger.error(f"[{self.process_id}] {error_msg}")
                    return {
                        'request_id': request_id,
                        'process_id': self.process_id,
                        'window_hwnd': window_hwnd,
                        'window_title': window_title,
                        'results': [],
                        'success': False,
                        'processing_time': time.time() - start_time,
                        'error': error_msg
                    }

            confidence = request.get('confidence', 0.5)

            # 执行OCR识别
            results = self.ocr_engine.recognize_text(image, confidence)

            # 【内存泄漏修复】OCR完成后立即释放输入图像
            del image
            image = None

            processing_time = time.time() - start_time

            return {
                'request_id': request_id,
                'process_id': self.process_id,
                'window_hwnd': window_hwnd,  # 【关键】返回窗口句柄
                'window_title': window_title,  # 【辅助】返回窗口标题
                'results': results,
                'success': True,
                'processing_time': processing_time,
                'error': None
            }

        except Exception as e:
            processing_time = time.time() - start_time
            error_msg = f"OCR识别异常: {e}"
            logger.error(f"[{self.process_id}] {error_msg}")

            return {
                'request_id': request_id,
                'process_id': self.process_id,
                'window_hwnd': window_hwnd,
                'window_title': window_title,
                'results': [],
                'success': False,
                'processing_time': processing_time,
                'error': error_msg
            }

        finally:
            # 【内存泄漏修复】显式删除图像数据（使用'in locals()'检查变量是否存在）
            if 'image' in locals() and image is not None:
                del image
            if 'image_bytes' in locals() and image_bytes is not None:
                del image_bytes

            # 清理共享内存（必须在删除图像视图后执行）
            if image_shm is not None:
                try:
                    image_shm.close()
                except Exception:
                    pass

    def run(self):
        """运行工作进程主循环"""
        try:
            # 初始化OCR引擎
            if not self.initialize_ocr_engine():
                if self._init_error_detail:
                    logger.error(f"[{self.process_id}] OCR引擎初始化失败，进程退出: {self._init_error_detail}")
                else:
                    logger.error(f"[{self.process_id}] OCR引擎初始化失败，进程退出")
                return

            self.is_running = True
            request_count = 0

            # 主循环：处理OCR请求
            while self.is_running:
                try:
                    # 从请求队列获取任务（超时1秒）
                    try:
                        request = self.request_queue.get(timeout=1.0)
                    except (BrokenPipeError, EOFError, OSError, ConnectionResetError):
                        self.is_running = False
                        break

                    # 检查是否为停止信号
                    if request is None or request.get('command') == 'STOP':
                        self.is_running = False
                        break

                    # 处理PING心跳命令
                    if request.get('command') == 'PING':
                        continue

                    # 检查请求是否过期
                    request_timestamp = request.get('timestamp', 0)
                    request_id = request.get('request_id', 'unknown')
                    current_time = time.time()

                    request_age_ms = (current_time - request_timestamp) * 1000 if request_timestamp > 0 else 0
                    is_stale_order = request_timestamp > 0 and request_timestamp < self._last_request_timestamp
                    is_too_old = request_age_ms > 500

                    if is_stale_order or is_too_old:
                        # 发送错误响应
                        error_response = {
                            'request_id': request_id,
                            'process_id': self.process_id,
                            'window_hwnd': request.get('window_hwnd', 0),
                            'window_title': request.get('window_title', 'unknown'),
                            'results': [],
                            'success': False,
                            'processing_time': 0,
                            'error': '请求已过期（画面变动），已丢弃'
                        }
                        try:
                            self.response_queue.put(error_response, timeout=1)
                        except:
                            pass
                        # 清理请求中的图像数据
                        if 'image' in request:
                            del request['image']
                        request.clear()
                        del request
                        request = None
                        continue

                    # 更新最后请求时间戳
                    self._last_request_timestamp = request_timestamp

                    # 处理OCR请求
                    response = self.process_ocr_request(request)
                    request_count += 1

                    # 每500个请求执行内存trim（减少日志频率）
                    if request_count % 500 == 0:
                        try:
                            import ctypes
                            msvcrt = ctypes.CDLL('msvcrt')
                            if hasattr(msvcrt, '_heapmin'):
                                msvcrt._heapmin()
                        except Exception:
                            pass

                    # 【内存泄漏修复】彻底清理request对象
                    request.clear()
                    del request
                    request = None

                    # 将结果放入响应队列
                    try:
                        self.response_queue.put(response, timeout=5)
                    except (BrokenPipeError, EOFError, OSError, ConnectionResetError):
                        self.is_running = False
                    except Exception:
                        pass

                    # 【内存泄漏修复】彻底清理response对象，包括results列表
                    if 'results' in response and isinstance(response.get('results'), list):
                        for item in response['results']:
                            if isinstance(item, dict):
                                try:
                                    item.clear()
                                except:
                                    pass
                        response['results'].clear()
                    response.clear()
                    del response
                    response = None

                except mp.queues.Empty:
                    # 队列为空，继续等待
                    continue

                except Exception as e:
                    logger.error(f"[{self.process_id}] 处理请求异常: {e}")
                    # 发送错误响应
                    try:
                        error_response = {
                            'request_id': request.get('request_id', 'unknown') if 'request' in locals() and request else 'unknown',
                            'process_id': self.process_id,
                            'window_hwnd': request.get('window_hwnd', 0) if 'request' in locals() and request else 0,
                            'window_title': request.get('window_title', 'unknown') if 'request' in locals() and request else 'unknown',
                            'results': [],
                            'success': False,
                            'processing_time': 0,
                            'error': str(e)
                        }
                        self.response_queue.put(error_response, timeout=2)
                    except Exception:
                        pass

        except KeyboardInterrupt:
            pass

        finally:
            # 清理OCR引擎资源
            try:
                if self.ocr_engine:
                    if hasattr(self.ocr_engine, 'cleanup'):
                        self.ocr_engine.cleanup()
                    elif hasattr(self.ocr_engine, 'shutdown'):
                        self.ocr_engine.shutdown(deep_cleanup=True)
                    self.ocr_engine = None
            except Exception:
                pass
            self.is_running = False


def ocr_worker_main(process_id: str, request_queue: mp.Queue, response_queue: mp.Queue):
    """
    OCR工作进程入口函数（兼容旧版 multiprocessing 方式）

    Args:
        process_id: 进程ID
        request_queue: 请求队列
        response_queue: 响应队列
    """
    worker = OCRWorkerProcess(process_id, request_queue, response_queue)
    worker.run()


# ============================================================
# 【Nuitka修复】独立运行模式 - 使用 socket 通信
# ============================================================

import socket
from services.ocr_socket_message_utils import (
    recv_message as recv_ocr_socket_message,
    send_message as send_ocr_socket_message,
)


def _send_message(sock: socket.socket, data: dict) -> bool:
    """通过 socket 发送消息（带长度前缀）"""
    return send_ocr_socket_message(sock=sock, data=data, logger=logger)


def _recv_message(sock: socket.socket, timeout: float = 10.0) -> Optional[dict]:
    """通过 socket 接收消息（带长度前缀）

    【画面变动优化】接收完大消息后立即执行轻量级GC，防止多个大图像同时驻留内存
    """
    return recv_ocr_socket_message(sock=sock, timeout=timeout, logger=logger)



class OCRWorkerStandalone:
    """独立运行的 OCR Worker - 使用 socket 通信"""

    def __init__(self, process_id: str, port: int):
        self.process_id = process_id
        self.port = port
        self.socket = None
        self.ocr_engine = None
        self.is_running = False
        self._request_count = 0  # 【内存泄漏修复】请求计数器，用于定期GC
        self._last_request_timestamp = 0  # 【画面变动修复】记录最后请求的时间戳，用于丢弃过期请求
        self._pending_request_id = None  # 【画面变动修复】当前正在处理的请求ID
        self._max_rss_mb_before_recycle = _read_int_env('OCR_WORKER_MAX_RSS_MB', 1200, 256)
        self._rss_growth_soft_limit_mb = _read_int_env('OCR_WORKER_RSS_GROWTH_SOFT_MB', 320, 64)
        self._large_frame_pixels = _read_int_env('OCR_WORKER_LARGE_FRAME_PIXELS', 1920 * 1080, 10000)
        self._soft_cleanup_cooldown_sec = _read_int_env('OCR_WORKER_SOFT_CLEANUP_COOLDOWN_MS', 1500, 100) / 1000.0
        self._engine_refresh_cooldown_sec = float(_read_int_env('OCR_WORKER_ENGINE_REFRESH_COOLDOWN_SEC', 3, 0))
        self._hard_limit_required_hits = _read_int_env('OCR_WORKER_HARD_LIMIT_REQUIRED_HITS', 2, 1)
        self._hard_limit_large_frame_allowance_cap_mb = _read_int_env('OCR_WORKER_HARD_LIMIT_ALLOWANCE_CAP_MB', 192, 0)
        self._hard_limit_consecutive_hits = 0
        self._rss_baseline_mb = 0.0
        self._high_pressure_count = 0
        self._last_soft_cleanup_ts = 0.0
        self._last_engine_refresh_ts = 0.0
        self._init_error_detail = ""
        self._psutil_process = None
        try:
            import psutil
            self._psutil_process = psutil.Process(os.getpid())
        except Exception:
            self._psutil_process = None

    def _estimate_request_pixels(self, request: Dict) -> int:
        """根据请求估算帧大小（像素）"""
        try:
            shape = request.get('image_shape')
            if not isinstance(shape, (list, tuple)) or len(shape) < 2:
                return 0
            height = int(shape[0])
            width = int(shape[1])
            if height <= 0 or width <= 0:
                return 0
            return height * width
        except Exception:
            return 0

    def _get_rss_mb(self) -> float:
        """获取当前进程RSS（MB）"""
        if self._psutil_process is not None:
            try:
                return float(self._psutil_process.memory_info().rss) / (1024 * 1024)
            except Exception:
                pass

        if os.name != 'nt':
            return 0.0

        try:
            import ctypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ('cb', ctypes.c_ulong),
                    ('PageFaultCount', ctypes.c_ulong),
                    ('PeakWorkingSetSize', ctypes.c_size_t),
                    ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t),
                    ('PeakPagefileUsage', ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            current_process = ctypes.windll.kernel32.GetCurrentProcess()
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                current_process,
                ctypes.byref(counters),
                counters.cb
            )
            if not ok:
                return 0.0
            return float(counters.WorkingSetSize) / (1024 * 1024)
        except Exception:
            return 0.0

    def _run_soft_memory_cleanup(self) -> None:
        """执行轻量内存清理"""
        try:
            gc.collect()
        except Exception:
            pass

        try:
            import ctypes
            msvcrt = ctypes.CDLL('msvcrt')
            if hasattr(msvcrt, '_heapmin'):
                msvcrt._heapmin()
        except Exception:
            pass

    def _try_refresh_ocr_engine(self, force: bool = False) -> bool:
        """在高压场景下尝试仅重置OCR引擎，不重启子进程"""
        now = time.time()
        if (not force) and (now - self._last_engine_refresh_ts < self._engine_refresh_cooldown_sec):
            return False
        self._last_engine_refresh_ts = now

        try:
            if self.ocr_engine and hasattr(self.ocr_engine, 'shutdown'):
                self.ocr_engine.shutdown(deep_cleanup=True)
        except Exception:
            pass
        self.ocr_engine = None

        self._run_soft_memory_cleanup()
        refresh_ok = self.initialize_ocr_engine()
        if refresh_ok:
            self._hard_limit_consecutive_hits = 0
            rss_mb = self._get_rss_mb()
            if rss_mb > 0:
                self._rss_baseline_mb = rss_mb
        return refresh_ok

    def _adaptive_memory_maintenance(self, request_pixels: int) -> Tuple[bool, float]:
        """动态内存治理：优先软清理，必要时热重置引擎"""
        rss_mb = self._get_rss_mb()
        if rss_mb <= 0:
            return False, rss_mb

        if self._rss_baseline_mb <= 0:
            self._rss_baseline_mb = rss_mb
        elif rss_mb < self._rss_baseline_mb:
            self._rss_baseline_mb = rss_mb

        rss_growth_mb = max(0.0, rss_mb - self._rss_baseline_mb)
        near_hard_limit = self._max_rss_mb_before_recycle > 0 and rss_mb >= self._max_rss_mb_before_recycle * 0.85
        large_frame = request_pixels >= self._large_frame_pixels
        growth_pressure = rss_growth_mb >= self._rss_growth_soft_limit_mb

        if not (near_hard_limit or large_frame or growth_pressure):
            if self._high_pressure_count > 0:
                self._high_pressure_count -= 1
            return False, rss_mb

        self._high_pressure_count += 1
        now = time.time()
        if now - self._last_soft_cleanup_ts >= self._soft_cleanup_cooldown_sec:
            self._last_soft_cleanup_ts = now
            self._run_soft_memory_cleanup()
            rss_mb = self._get_rss_mb()
            if rss_mb > 0 and rss_mb < self._rss_baseline_mb:
                self._rss_baseline_mb = rss_mb

        # 高压持续时，优先热重置引擎，不直接回收整个子进程
        if near_hard_limit and self._high_pressure_count >= 2:
            if self._try_refresh_ocr_engine():
                rss_mb = self._get_rss_mb()
                if rss_mb > 0 and rss_mb < self._rss_baseline_mb:
                    self._rss_baseline_mb = rss_mb
                self._high_pressure_count = 0
                return True, rss_mb

        return True, rss_mb

    def _should_recycle_worker(self, request_pixels: int = 0, rss_hint_mb: float = 0.0) -> Tuple[bool, str, float]:
        """根据RSS判断是否需要重建worker（连续超阈值才回收）"""
        rss_mb = rss_hint_mb if rss_hint_mb > 0 else self._get_rss_mb()
        hard_limit_mb = float(self._max_rss_mb_before_recycle)

        if hard_limit_mb <= 0 or rss_mb <= 0:
            self._hard_limit_consecutive_hits = 0
            return False, '', rss_mb

        frame_allowance_mb = 0.0
        if request_pixels > 0 and request_pixels >= self._large_frame_pixels:
            frame_mb = (float(request_pixels) * 3.0) / (1024.0 * 1024.0)
            frame_allowance_mb = min(
                float(self._hard_limit_large_frame_allowance_cap_mb),
                max(16.0, frame_mb * 0.8)
            )

        effective_hard_limit_mb = hard_limit_mb + frame_allowance_mb
        if rss_mb < effective_hard_limit_mb:
            if self._hard_limit_consecutive_hits > 0:
                self._hard_limit_consecutive_hits -= 1
            return False, '', rss_mb

        # 超阈值后先做一次轻量清理，防止大窗口单次峰值导致误回收
        self._run_soft_memory_cleanup()
        rss_after_cleanup_mb = self._get_rss_mb()
        if rss_after_cleanup_mb > 0:
            rss_mb = rss_after_cleanup_mb

        if rss_mb < effective_hard_limit_mb:
            if self._hard_limit_consecutive_hits > 0:
                self._hard_limit_consecutive_hits -= 1
            return False, '', rss_mb

        self._hard_limit_consecutive_hits += 1
        if self._hard_limit_consecutive_hits < self._hard_limit_required_hits:
            return False, '', rss_mb

        self._hard_limit_consecutive_hits = 0
        return True, 'max_rss_sustained', rss_mb

    def initialize_ocr_engine(self) -> bool:
        """初始化OCR引擎"""
        self._init_error_detail = ""
        try:
            from services.fastdeploy_ocr_service import get_fastdeploy_ocr_service
            self.ocr_engine = get_fastdeploy_ocr_service()

            if not self.ocr_engine.initialize():
                self._init_error_detail = _extract_ocr_engine_init_detail(self.ocr_engine) or "未返回具体错误"
                logger.error(f"[{self.process_id}] OCR引擎初始化失败: {self._init_error_detail}")
                return False

            self._init_error_detail = ""
            logger.warning(f"[{self.process_id}] OCR引擎初始化成功")
            return True

        except Exception as e:
            engine_detail = _extract_ocr_engine_init_detail(self.ocr_engine)
            detail = _format_exception_detail(e)
            if engine_detail and engine_detail not in detail:
                detail = f"{detail} | 引擎详情: {engine_detail}"
            self._init_error_detail = detail
            logger.error(f"[{self.process_id}] OCR引擎初始化异常: {detail}")
            return False

    def connect_to_parent(self) -> bool:
        """连接到父进程"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10.0)
            self.socket.connect(('127.0.0.1', self.port))
            return True
        except Exception as e:
            logger.error(f"[{self.process_id}] 连接父进程失败: {e}")
            return False

    def process_ocr_request(self, request: Dict) -> Dict:
        """处理OCR请求"""
        request_id = request.get('request_id', 'unknown')
        window_hwnd = request.get('window_hwnd', 0)
        window_title = request.get('window_title', 'unknown')
        start_time = time.time()

        # 【内存泄漏修复】所有临时变量预声明为None，确保finally可清理
        image = None
        image_bytes = None
        image_view = None
        shm = None
        results = None
        response = None  # 【新增】响应也要跟踪

        try:
            # 获取图像数据
            if 'image' in request:
                # 直接传输的图像数据
                # 【关键修复】从request中pop出来，同时删除request中的引用
                image_bytes = request.pop('image')
                image_shape = request.get('image_shape')
                image_dtype = request.get('image_dtype', 'uint8')

                if image_shape:
                    # 【内存泄漏修复】frombuffer返回视图，需要copy才能释放原始bytes
                    image_view = np.frombuffer(image_bytes, dtype=np.dtype(image_dtype)).reshape(image_shape)
                    image = np.copy(image_view)
                    del image_view
                    image_view = None
                    # 【内存泄漏修复】立即删除字节数据
                    del image_bytes
                    image_bytes = None
                else:
                    logger.error(f"[{self.process_id}] 缺少图像形状信息")
                    # 【修复】错误返回前也要清理image_bytes
                    del image_bytes
                    image_bytes = None
                    return self._error_response(request_id, window_hwnd, window_title, start_time, "缺少图像形状信息")

            elif 'shm_name' in request:
                # 共享内存方式
                try:
                    from multiprocessing import shared_memory
                    shm_name = request.get('shm_name')
                    shm_size = request.get('shm_size')
                    image_shape = request.get('image_shape')
                    image_dtype = request.get('image_dtype', 'uint8')

                    shm = shared_memory.SharedMemory(name=shm_name)
                    image_view = np.ndarray(image_shape, dtype=np.dtype(image_dtype), buffer=shm.buf[:shm_size])
                    # 【关键】同步处理路径下直接使用共享内存视图，避免整帧复制导致内存抖动
                    image = image_view
                except Exception as e:
                    logger.error(f"[{self.process_id}] 读取共享内存失败: {e}")
                    return self._error_response(request_id, window_hwnd, window_title, start_time, f"读取共享内存失败: {e}")
            else:
                return self._error_response(request_id, window_hwnd, window_title, start_time, "缺少图像数据")

            confidence = request.get('confidence', 0.5)

            # 【关键修复】清理request中的其他大数据字段
            request.pop('image_shape', None)
            request.pop('image_dtype', None)
            request.pop('shm_name', None)
            request.pop('shm_size', None)

            # 执行OCR识别
            results = self.ocr_engine.recognize_text(image, confidence)

            # 【内存泄漏修复】OCR完成后立即释放输入图像
            del image
            image = None

            processing_time = time.time() - start_time

            # 构建响应
            response = {
                'request_id': request_id,
                'process_id': self.process_id,
                'window_hwnd': window_hwnd,
                'window_title': window_title,
                'results': results,
                'success': True,
                'processing_time': processing_time,
                'error': None
            }

            # 【内存泄漏修复】解除本地引用，让response持有唯一引用
            results = None

            return response

        except Exception as e:
            logger.error(f"[{self.process_id}] OCR识别异常: {e}")
            return self._error_response(request_id, window_hwnd, window_title, start_time, str(e))

        finally:
            # 【内存泄漏修复】确保所有临时对象被清理
            if image is not None:
                del image
            if image_bytes is not None:
                del image_bytes
            if image_view is not None:
                del image_view
            if results is not None:
                # 【关键修复】如果results还存在（异常时），清理它
                if isinstance(results, list):
                    results.clear()
                del results
            if shm is not None:
                try:
                    shm.close()
                except:
                    pass

    def _error_response(self, request_id, window_hwnd, window_title, start_time, error_msg):
        """生成错误响应"""
        return {
            'request_id': request_id,
            'process_id': self.process_id,
            'window_hwnd': window_hwnd,
            'window_title': window_title,
            'results': [],
            'success': False,
            'processing_time': time.time() - start_time,
            'error': error_msg
        }

    def run(self):
        """运行主循环"""
        # 配置日志（已禁用OCR日志文件输出）
        global logger
        logger = _setup_ocr_worker_logging(self.process_id)

        try:
            # 连接到父进程
            if not self.connect_to_parent():
                logger.error(f"[{self.process_id}] 连接父进程失败")
                return

            # 初始化OCR引擎
            if not self.initialize_ocr_engine():
                error_detail = self._init_error_detail or "未返回具体错误"
                try:
                    _send_message(
                        self.socket,
                        {
                            'type': 'error',
                            'message': f'OCR引擎初始化失败: {error_detail}',
                            'detail': error_detail,
                            'process_id': self.process_id,
                        },
                    )
                except Exception:
                    pass
                return

            # 发送就绪消息
            try:
                _send_message(self.socket, {
                    'type': 'ready',
                    'process_id': self.process_id,
                    'pid': os.getpid()
                })
            except Exception as e:
                logger.error(f"[{self.process_id}] 发送就绪消息失败: {e}")
                return

            self.is_running = True

            # 主循环
            request = None  # 【内存泄漏修复】在循环外声明，确保finally可以清理
            response = None
            while self.is_running:
                try:
                    recycle_after_response = False
                    request_pixels = 0
                    # 接收请求（长超时）
                    # 【内存泄漏修复】主进程已实现流控(is_busy)，一次只发送一个请求
                    # 所以这里不会有请求堆积，简化处理逻辑
                    request = _recv_message(self.socket, timeout=60.0)

                    if request is None:
                        # 超时，继续等待
                        continue

                    # 检查是否是停止命令
                    if request.get('command') == 'STOP':
                        del request
                        request = None
                        break

                    # 检查是否是 PING
                    if request.get('command') == 'PING':
                        _send_message(self.socket, {'type': 'pong', 'process_id': self.process_id})
                        del request
                        request = None
                        continue

                    if request.get('command') == 'RESET_ENGINE':
                        reset_success = False
                        try:
                            reset_success = bool(self._try_refresh_ocr_engine(force=bool(request.get('force', False))))
                        except Exception:
                            reset_success = False
                        _send_message(
                            self.socket,
                            {
                                'type': 'reset_engine',
                                'process_id': self.process_id,
                                'success': reset_success,
                            },
                        )
                        del request
                        request = None
                        continue

                    # 获取请求信息
                    request_id = request.get('request_id', 'unknown')
                    request_pixels = self._estimate_request_pixels(request)

                    # 处理OCR请求
                    response = self.process_ocr_request(request)
                    self._request_count += 1

                    # 动态内存治理：先软清理/热重置，再决定是否回收子进程
                    _, current_rss_mb = self._adaptive_memory_maintenance(request_pixels)

                    # 满足生命周期阈值后，在本次响应后重建子进程
                    should_recycle, recycle_reason, rss_mb = self._should_recycle_worker(
                        request_pixels=request_pixels,
                        rss_hint_mb=current_rss_mb
                    )
                    if should_recycle:
                        response['worker_should_recycle'] = True
                        response['worker_recycle_reason'] = recycle_reason
                        response['worker_rss_mb'] = rss_mb
                        recycle_after_response = True
                    else:
                        response['worker_should_recycle'] = False
                        response['worker_rss_mb'] = current_rss_mb

                    # 【内存泄漏修复】彻底清理request（包含大量图像数据）
                    # process_ocr_request已经pop了'image'，但字典本身可能还有引用
                    request.clear()  # 清空字典所有键值对
                    del request
                    request = None

                    # 发送响应
                    _send_message(self.socket, response)

                    # 【内存泄漏修复】彻底清理response，包括内部的results列表
                    if 'results' in response and isinstance(response['results'], list):
                        # 清理results中的每个字典
                        for item in response['results']:
                            if isinstance(item, dict):
                                item.clear()
                        response['results'].clear()
                    response.clear()
                    del response
                    response = None

                    if recycle_after_response:
                        self.is_running = False
                        break

                    # 每500个请求执行内存trim
                    if self._request_count % 500 == 0:
                        try:
                            import ctypes
                            msvcrt = ctypes.CDLL('msvcrt')
                            if hasattr(msvcrt, '_heapmin'):
                                msvcrt._heapmin()
                        except Exception:
                            pass

                except Exception as e:
                    logger.error(f"[{self.process_id}] 主循环异常: {e}")
                    # 清理
                    if request is not None:
                        try:
                            request.clear()
                        except Exception:
                            pass
                        request = None
                    if response is not None:
                        try:
                            if 'results' in response and isinstance(response.get('results'), list):
                                response['results'].clear()
                            response.clear()
                        except Exception:
                            pass
                        response = None

        except Exception as e:
            logger.error(f"[{self.process_id}] Worker 运行异常: {e}")

        finally:
            # 清理资源
            if self.ocr_engine:
                try:
                    if hasattr(self.ocr_engine, 'shutdown'):
                        self.ocr_engine.shutdown(deep_cleanup=True)
                except Exception:
                    pass
                self.ocr_engine = None

            try:
                gc.collect()
            except Exception:
                pass

            try:
                import ctypes
                msvcrt = ctypes.CDLL('msvcrt')
                if hasattr(msvcrt, '_heapmin'):
                    msvcrt._heapmin()
            except Exception:
                pass

            if self.socket:
                try:
                    self.socket.close()
                except Exception:
                    pass
                self.socket = None


def run_ocr_worker_standalone(process_id: str, port: int):
    """独立运行 OCR Worker（从 main.py 调用）"""
    worker = OCRWorkerStandalone(process_id, port)
    worker.run()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="OCR Worker Standalone Entry")
    parser.add_argument('--ocr-worker-standalone', action='store_true', help='Run standalone OCR worker')
    parser.add_argument('--process-id', type=str, default='unknown', help='OCR process id')
    parser.add_argument('--port', type=int, default=0, help='Socket port')
    args = parser.parse_args()

    if args.ocr_worker_standalone:
        if args.port <= 0:
            sys.exit(2)
        run_ocr_worker_standalone(args.process_id, args.port)
        sys.exit(0)

    sys.exit(0)
