#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多进程OCR池管理器 - 管理多个OCR工作进程
使用进程池替代线程池，每个进程独立运行OCR引擎，避免GIL限制

【Nuitka修复】使用 subprocess + socket 替代 multiprocessing.Process + Queue
这样可以通过命令行参数在 main.py 最开头检测 OCR 子进程，阻止 PySide6 加载
"""

import logging
import multiprocessing as mp
import subprocess
import socket
import threading
import time
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
import queue
import os

from services.worker_process_cleanup import cleanup_worker_processes
from services.ocr_socket_message_utils import (
    recv_message as recv_ocr_socket_message,
    send_message as send_ocr_socket_message,
)
from utils.app_paths import get_logs_dir
from utils.worker_entry import build_worker_launch_command, build_worker_process_env

logger = logging.getLogger(__name__)


# ============================================================
# Socket 通信辅助函数
# ============================================================

def _send_message(sock: socket.socket, data: dict) -> bool:
    """通过 socket 发送消息（带长度前缀）"""
    return send_ocr_socket_message(sock=sock, data=data, logger=logger)


def _recv_message(sock: socket.socket, timeout: float = 10.0) -> Optional[dict]:
    """通过 socket 接收消息（带长度前缀）"""
    return recv_ocr_socket_message(sock=sock, timeout=timeout, logger=logger)


def _is_process_alive(process: Optional[subprocess.Popen]) -> bool:
    """检查 subprocess.Popen 进程是否仍在运行

    对于 subprocess.Popen:
    - poll() 返回 None 表示进程仍在运行
    - poll() 返回退出码表示进程已结束
    """
    if process is None:
        return False
    try:
        return process.poll() is None
    except Exception:
        return False


def _read_int_env(name: str, default: int, min_value: int, max_value: Optional[int] = None) -> int:
    """安全读取整型环境变量并做边界校验"""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    if value < min_value:
        value = min_value
    if max_value is not None and value > max_value:
        value = max_value
    return value


def _read_float_env(name: str, default: float, min_value: float, max_value: Optional[float] = None) -> float:
    """安全读取浮点型环境变量并做边界校验"""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return default
    if value < min_value:
        value = min_value
    if max_value is not None and value > max_value:
        value = max_value
    return value


def _read_bool_env(name: str, default: bool = False) -> bool:
    """安全读取布尔环境变量"""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    value = raw_value.strip().lower()
    if value in ('1', 'true', 'yes', 'on'):
        return True
    if value in ('0', 'false', 'no', 'off'):
        return False
    return default


@dataclass
class OCRProcessInfo:
    """OCR进程信息"""
    process_id: str
    process: Optional[subprocess.Popen]  # 改为 subprocess.Popen
    request_queue: Optional[mp.Queue]  # 保留用于兼容，但可能为 None
    response_queue: Optional[mp.Queue]  # 保留用于兼容，但可能为 None
    socket_conn: Optional[socket.socket] = None  # 新增：socket 连接
    socket_port: int = 0  # 新增：监听端口
    is_active: bool = True
    last_used: float = 0.0
    total_requests: int = 0
    total_processing_time: float = 0.0
    assigned_windows: Dict[int, str] = field(default_factory=dict)  # hwnd -> window_title
    max_windows: int = 3  # 每个进程最多支持3个窗口
    is_creating: bool = False  # 【修复竞态条件】标记占位符正在创建真实进程
    is_busy: bool = False  # 【内存泄漏修复】标记进程是否正在处理请求，防止请求堆积
    is_retiring: bool = False  # 生命周期回收中，不再接收新窗口

    def can_accept_window(self) -> bool:
        """检查是否可以接受新窗口"""
        # 【修复】允许正在创建的占位符接受新窗口(但需要额外检查窗口数)
        # 这样可以让多个窗口共享同一个正在创建的进程,避免创建过多进程
        if self.is_retiring:
            return False
        return len(self.assigned_windows) < self.max_windows

    def add_window(self, window_hwnd: int, window_title: str) -> bool:
        """添加窗口到进程"""
        if self.can_accept_window():
            self.assigned_windows[window_hwnd] = window_title
            return True
        return False

    def remove_window(self, window_hwnd: int) -> bool:
        """从进程中移除窗口"""
        if window_hwnd in self.assigned_windows:
            del self.assigned_windows[window_hwnd]
            return True
        return False

    def get_window_count(self) -> int:
        """获取当前窗口数量"""
        return len(self.assigned_windows)

    def is_empty(self) -> bool:
        """检查进程是否为空（无窗口）"""
        return len(self.assigned_windows) == 0


@dataclass
class OCRSharedMemorySlot:
    """可复用共享内存槽（每个进程一个槽）"""
    shm: Any
    capacity: int


class MultiProcessOCRPool:
    """多进程OCR池管理器"""

    def __init__(self, max_processes: int = 10, max_windows_per_process: int = 3):
        """
        初始化多进程OCR池

        Args:
            max_processes: 最大进程数量（建议不超过CPU核心数）
            max_windows_per_process: 每个进程最多支持的窗口数
        """
        # 限制最大进程数不超过CPU核心数
        cpu_count = mp.cpu_count()
        configured_max_processes = _read_int_env('OCR_POOL_MAX_PROCESSES', max_processes, 1, 10)
        configured_max_windows = _read_int_env('OCR_POOL_MAX_WINDOWS_PER_PROCESS', max_windows_per_process, 1, 20)
        self.max_processes = min(configured_max_processes, cpu_count, 10)
        self.max_windows_per_process = configured_max_windows
        self._adaptive_scale_enabled = _read_bool_env('OCR_POOL_ADAPTIVE_SCALE', True)
        self._adaptive_min_processes = _read_int_env('OCR_POOL_MIN_PROCESSES', 1, 1, self.max_processes)
        # 并发请求扩容粒度：每 N 个并发请求对应 1 个OCR子进程
        self._threads_per_process = _read_int_env('OCR_POOL_THREADS_PER_PROCESS', 3, 1, 64)
        # 预注册仅做窗口登记，默认不提前拉起子进程；如需预热可显式开启
        self._preregister_allocate_enabled = _read_bool_env('OCR_POOL_PREREGISTER_ALLOCATE', False)
        self._effective_max_processes = self.max_processes

        # 进程管理
        self.processes: Dict[str, OCRProcessInfo] = {}
        self.window_process_mapping: Dict[int, str] = {}  # hwnd -> process_id
        self._shm_slots: Dict[str, OCRSharedMemorySlot] = {}
        self._resource_process_mapping: Dict[str, str] = {}  # resource_key -> process_id
        self._resource_last_used: Dict[str, float] = {}  # resource_key -> timestamp
        self._route_by_thread_start = _read_bool_env('LCA_ROUTE_POOL_BY_THREAD_START', True)
        self._resource_mapping_ttl_sec = _read_float_env(
            'OCR_POOL_RESOURCE_MAPPING_TTL_SEC', 90.0, 5.0, 3600.0
        )

        # 线程安全
        self._pool_lock = threading.RLock()
        self._request_counter = 0
        self._counter_lock = threading.Lock()

        # 性能监控
        self._performance_stats = {
            "total_processes": 0,
            "active_processes": 0,
            "total_requests": 0,
            "average_processing_time": 0.0,
            "effective_max_processes": self._effective_max_processes,
            "shared_memory_slots": 0,
            "shared_memory_total_mb": 0.0,
            "resource_routes": 0
        }

        # 清理线程
        self._cleanup_thread = None
        self._cleanup_interval = _read_float_env('OCR_POOL_CLEANUP_INTERVAL_SEC', 2.0, 1.0, 60.0)
        self._process_timeout = _read_float_env('OCR_POOL_PROCESS_IDLE_TIMEOUT_SEC', 10.0, 5.0, 3600.0)
        self._process_ready_timeout = _read_float_env('OCR_POOL_PROCESS_READY_TIMEOUT_SEC', 10.0, 1.0, 60.0)
        self._busy_wait_timeout = _read_float_env('OCR_POOL_BUSY_WAIT_TIMEOUT_SEC', 10.0, 1.0, 120.0)
        self._worker_connect_timeout = _read_float_env('OCR_POOL_WORKER_CONNECT_TIMEOUT_SEC', 10.0, 1.0, 60.0)
        self._worker_ready_timeout = _read_float_env('OCR_POOL_WORKER_READY_TIMEOUT_SEC', 30.0, 1.0, 120.0)
        self._shared_memory_threshold_kb = _read_int_env('OCR_POOL_SHM_THRESHOLD_KB', 100, 32, 4096)
        # 强制策略：主进程不保留常驻共享内存槽
        self._shared_memory_reuse_enabled = False
        self._shared_memory_reuse_max_mb = _read_int_env('OCR_POOL_SHM_REUSE_MAX_MB', 96, 16, 4096)
        self._shared_memory_idle_release_sec = _read_float_env('OCR_POOL_SHM_IDLE_RELEASE_SEC', 8.0, 1.0, 600.0)
        self._idle_rebuild_threshold_mb = _read_int_env('OCR_POOL_IDLE_REBUILD_MB', 500, 128, 8192)
        self._running = True
        self._is_shutdown = False  # 【修复闪退】标记是否正在关闭

        # 兼容层：仅在显式开启时使用旧Queue响应收集逻辑
        self._enable_legacy_queue_mode = os.getenv('OCR_POOL_ENABLE_LEGACY_QUEUE_MODE', '0').strip() == '1'

        # 响应收集线程（仅Queue模式需要）
        self._response_collector_thread = None
        self._pending_responses: Dict[str, queue.Queue] = {}  # request_id -> Queue

        # 【画面变动修复】记录每个窗口的最后请求时间戳，用于防止请求堆积
        self._window_last_request_time: Dict[int, float] = {}  # hwnd -> timestamp
        self._request_throttle_interval = _read_float_env('OCR_POOL_REQUEST_THROTTLE_SEC', 0.0, 0.0, 5.0)
        self._window_request_entry_ttl_sec = _read_float_env(
            'OCR_POOL_WINDOW_REQUEST_TTL_SEC', 900.0, 30.0, 86400.0
        )
        self._window_request_entry_limit = _read_int_env(
            'OCR_POOL_WINDOW_REQUEST_ENTRY_LIMIT', 1024, 64, 32768
        )
        self._window_request_prune_interval_sec = _read_float_env(
            'OCR_POOL_WINDOW_REQUEST_PRUNE_INTERVAL_SEC', 15.0, 1.0, 300.0
        )
        self._last_window_request_prune_ts = 0.0
        self._last_ocr_activity_ts = 0.0  # 最近一次OCR活动时间（用于空闲热重置判定）
        self._active_ocr_requests = 0  # 全局在途OCR请求数（用于禁止执行中重建）
        self._idle_rebuild_suspend_until = 0.0
        self._idle_rebuild_suspend_reason = ""
        self._idle_rebuild_suspend_default_sec = _read_float_env(
            'OCR_POOL_IDLE_REBUILD_SUSPEND_SEC', 3.0, 0.2, 30.0
        )
        self._idle_rebuild_require_idle_sec = _read_float_env(
            'OCR_POOL_IDLE_REBUILD_REQUIRE_IDLE_SEC',
            max(1.5, self._cleanup_interval * 2.0),
            0.2,
            30.0
        )

        self._start_cleanup_thread()
        if self._enable_legacy_queue_mode:
            self._start_response_collector()

    def _start_cleanup_thread(self):
        """启动清理线程"""
        def cleanup_worker():
            last_log_cleanup_time = time.time()
            while self._running:
                try:
                    time.sleep(self._cleanup_interval)
                    if self._running:
                        with self._pool_lock:
                            self._prune_window_request_times_unlocked()
                            self._prune_resource_mappings_locked()
                        self._cleanup_inactive_processes()
                        self._rebuild_over_limit_idle_processes()
                        self._update_performance_stats()

                        current_time = time.time()

                        # 【日志优化】每30分钟清理一次过期日志文件
                        if self._is_ocr_log_size_exceeded() or current_time - last_log_cleanup_time > 30 * 60:
                            self._cleanup_old_log_files()
                            last_log_cleanup_time = current_time

                except Exception as e:
                    logger.error(f"清理线程异常: {e}")
                    time.sleep(60)

        self._cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True, name="OCRPool-Cleaner")
        self._cleanup_thread.start()

    def _start_response_collector(self):
        """启动响应收集线程 - 从所有进程的响应队列中收集结果"""
        def response_collector():
            while self._running:
                try:
                    # 【内存优化】检查是否有进程，无进程时延长休眠
                    with self._pool_lock:
                        if not self.processes:
                            time.sleep(0.2)  # 无进程时休眠200ms
                            continue

                        # 【修复OCR识别失败】使用字典快照避免迭代时字典被修改
                        processes_snapshot = list(self.processes.values())

                    # 【关键修复】在锁外迭代快照，避免死锁和RuntimeError
                    for process_info in processes_snapshot:
                        try:
                            # 【修复】跳过占位符进程（response_queue为None）
                            if process_info.response_queue is None:
                                continue

                            # 非阻塞获取响应
                            response = process_info.response_queue.get_nowait()

                            # 【修复OCR识别失败】将响应分发到对应的等待队列（需要锁保护字典访问）
                            request_id = response.get('request_id')
                            with self._pool_lock:
                                if request_id in self._pending_responses:
                                    self._pending_responses[request_id].put(response)
                                else:
                                    del response

                        except queue.Empty:
                            # 该进程没有响应，继续检查下一个
                            continue
                        except (RuntimeError, AttributeError):
                            continue
                        except (BrokenPipeError, EOFError, OSError, ConnectionResetError):
                            continue

                    # 【性能优化】降低频率，从10ms改为50ms（每秒20次）
                    time.sleep(0.05)

                except Exception:
                    time.sleep(1)

        self._response_collector_thread = threading.Thread(
            target=response_collector,
            daemon=True,
            name="OCRPool-ResponseCollector"
        )
        self._response_collector_thread.start()

    def _generate_process_id(self) -> str:
        """生成进程ID"""
        return f"ocr_process_{len(self.processes)}_{int(time.time())}"

    def _generate_request_id(self) -> str:
        """生成请求ID"""
        with self._counter_lock:
            self._request_counter += 1
            return f"ocr_req_{self._request_counter}_{int(time.time() * 1000)}"

    def _prune_window_request_times_unlocked(self, now: Optional[float] = None, force: bool = False) -> int:
        """清理窗口请求时间表，避免长期运行后字典无限增长。"""
        if not self._window_last_request_time:
            return 0

        current = float(now) if isinstance(now, (int, float)) and now > 0 else time.time()
        if (
            not force
            and (current - self._last_window_request_prune_ts) < self._window_request_prune_interval_sec
            and len(self._window_last_request_time) <= self._window_request_entry_limit
        ):
            return 0

        self._last_window_request_prune_ts = current
        removed = 0

        ttl = max(1.0, float(self._window_request_entry_ttl_sec))
        stale_hwnds = [
            hwnd for hwnd, ts in self._window_last_request_time.items()
            if (current - float(ts)) > ttl
        ]
        for hwnd in stale_hwnds:
            if hwnd in self._window_last_request_time:
                del self._window_last_request_time[hwnd]
                removed += 1

        overflow = len(self._window_last_request_time) - int(self._window_request_entry_limit)
        if overflow > 0:
            oldest = sorted(self._window_last_request_time.items(), key=lambda item: item[1])
            for hwnd, _ in oldest[:overflow]:
                if hwnd in self._window_last_request_time:
                    del self._window_last_request_time[hwnd]
                    removed += 1

        return removed

    @staticmethod
    def _normalize_resource_key(resource_key: Optional[str]) -> Optional[str]:
        if resource_key is None:
            return None
        try:
            normalized = str(resource_key).strip()
        except Exception:
            return None
        return normalized or None

    def _resolve_resource_key(self, window_hwnd: Optional[int], resource_key: Optional[str] = None) -> Optional[str]:
        explicit_key = self._normalize_resource_key(resource_key)
        if explicit_key:
            return explicit_key
        if not self._route_by_thread_start:
            return None
        try:
            from task_workflow.workflow_context import get_current_resource_lane_key
        except Exception:
            return None
        try:
            lane_key = self._normalize_resource_key(get_current_resource_lane_key(window_hwnd=window_hwnd))
            return lane_key
        except Exception:
            return None

    def _touch_resource_mapping_locked(self, resource_key: Optional[str], process_id: Optional[str], now: Optional[float] = None) -> None:
        normalized_key = self._normalize_resource_key(resource_key)
        if not normalized_key or not process_id:
            return
        current = float(now) if isinstance(now, (int, float)) and now > 0 else time.time()
        self._resource_process_mapping[normalized_key] = process_id
        self._resource_last_used[normalized_key] = current

    def _purge_resource_mappings_for_process_locked(self, process_id: Optional[str]) -> int:
        if not process_id:
            return 0
        removed = 0
        for key, mapped_pid in list(self._resource_process_mapping.items()):
            if mapped_pid == process_id:
                self._resource_process_mapping.pop(key, None)
                self._resource_last_used.pop(key, None)
                removed += 1
        return removed

    def _prune_resource_mappings_locked(self, now: Optional[float] = None, force: bool = False) -> int:
        if not self._resource_process_mapping:
            return 0
        current = float(now) if isinstance(now, (int, float)) and now > 0 else time.time()
        ttl = max(1.0, float(self._resource_mapping_ttl_sec))
        removed = 0
        for key, process_id in list(self._resource_process_mapping.items()):
            last_used = float(self._resource_last_used.get(key, 0.0) or 0.0)
            process_alive = process_id in self.processes
            if (not process_alive) or (force or (current - last_used) > ttl):
                self._resource_process_mapping.pop(key, None)
                self._resource_last_used.pop(key, None)
                removed += 1
        return removed

    @staticmethod
    def _get_process_rss_mb(process: Optional[subprocess.Popen]) -> float:
        """获取子进程RSS内存（MB）。"""
        if process is None:
            return 0.0
        try:
            if process.poll() is not None:
                return 0.0
        except Exception:
            return 0.0

        try:
            import psutil
            proc = psutil.Process(process.pid)
            total_rss = float(proc.memory_info().rss)
            try:
                for child in proc.children(recursive=True):
                    try:
                        total_rss += float(child.memory_info().rss)
                    except Exception:
                        continue
            except Exception:
                pass
            return total_rss / (1024 * 1024)
        except Exception:
            return 0.0

    def _start_async_create_for_process(self, process_id: str) -> None:
        """异步创建占位进程对应的真实OCR子进程。"""
        def _async_create():
            new_process_info = self._create_ocr_process(process_id)
            with self._pool_lock:
                if new_process_info and process_id in self.processes:
                    placeholder = self.processes[process_id]
                    for hwnd, title in placeholder.assigned_windows.items():
                        new_process_info.add_window(hwnd, title)
                    new_process_info.is_creating = False
                    self.processes[process_id] = new_process_info
                else:
                    if process_id in self.processes and self.processes[process_id].is_creating:
                        self.processes[process_id].is_creating = False
                        del self.processes[process_id]
                        self._purge_resource_mappings_for_process_locked(process_id)
                        windows_to_remove = [hwnd for hwnd, pid in self.window_process_mapping.items() if pid == process_id]
                        for hwnd in windows_to_remove:
                            del self.window_process_mapping[hwnd]
                        logger.error(f"进程创建失败，清理占位符: {process_id}")

        thread = threading.Thread(target=_async_create, daemon=True, name=f"OCRCreate-{process_id}")
        thread.start()

    def _schedule_process_rebuild(self, retiring_process_id: str) -> bool:
        """为高内存进程安排替换重建，不让OCR请求直接失败。"""
        new_process_id = None
        with self._pool_lock:
            if self._is_shutdown or (not self._running):
                return False
            if retiring_process_id not in self.processes:
                return False

            old_info = self.processes[retiring_process_id]
            if old_info.process is None:
                return False

            windows_to_move = [
                (hwnd, title)
                for hwnd, title in old_info.assigned_windows.items()
                if self.window_process_mapping.get(hwnd) == retiring_process_id
            ]
            if not windows_to_move:
                return False

            old_info.is_retiring = True

            new_process_id = self._generate_process_id()
            placeholder_info = OCRProcessInfo(
                process_id=new_process_id,
                process=None,
                request_queue=None,
                response_queue=None,
                is_active=False,
                last_used=time.time(),
                max_windows=self.max_windows_per_process,
                is_creating=True
            )

            for hwnd, title in windows_to_move:
                placeholder_info.add_window(hwnd, title)
                self.window_process_mapping[hwnd] = new_process_id
                old_info.remove_window(hwnd)

            self.processes[new_process_id] = placeholder_info
            for key, mapped_pid in list(self._resource_process_mapping.items()):
                if mapped_pid == retiring_process_id:
                    self._resource_process_mapping[key] = new_process_id
                    self._resource_last_used[key] = time.time()
            old_info.last_used = time.time()

        if new_process_id:
            self._start_async_create_for_process(new_process_id)
            logger.warning(f"[OCR重建] 高内存进程已进入替换重建: old={retiring_process_id}, new={new_process_id}")
            return True
        return False

    def suspend_idle_rebuild(self, duration_sec: Optional[float] = None, reason: str = "") -> float:
        """临时抑制空闲高内存重建，避免OCR连续卡片切换时误触发。"""
        hold_sec = self._idle_rebuild_suspend_default_sec
        if duration_sec is not None:
            try:
                hold_sec = float(duration_sec)
            except (TypeError, ValueError):
                hold_sec = self._idle_rebuild_suspend_default_sec
        if hold_sec <= 0:
            hold_sec = self._idle_rebuild_suspend_default_sec

        now = time.time()
        with self._pool_lock:
            if self._is_shutdown or (not self._running):
                return 0.0
            suspend_until = now + hold_sec
            if suspend_until > self._idle_rebuild_suspend_until:
                self._idle_rebuild_suspend_until = suspend_until
            reason_text = str(reason or "").strip()
            if reason_text:
                self._idle_rebuild_suspend_reason = reason_text
            return self._idle_rebuild_suspend_until

    def _rebuild_over_limit_idle_processes(self) -> int:
        """
        无OCR任务执行时：
        - 若子进程内存超过阈值，则直接重建该子进程
        - OCR请求在重建期间会等待占位进程就绪，不视为失败
        """
        threshold_mb = float(self._idle_rebuild_threshold_mb)
        if threshold_mb <= 0:
            return 0

        with self._pool_lock:
            if self._is_shutdown or (not self._running) or (not self.processes):
                return 0

            # 有在途OCR请求时，绝对禁止空闲重建
            if self._active_ocr_requests > 0:
                return 0

            # 当前存在OCR任务执行时，跳过该轮重建检查
            has_busy_worker = any(
                process_info.is_busy
                for process_info in self.processes.values()
            )
            if has_busy_worker:
                return 0

            now = time.time()
            # 最近仍有OCR活动时，不允许执行空闲重建（避免状态切换竞态）
            if self._last_ocr_activity_ts > 0:
                idle_elapsed = now - self._last_ocr_activity_ts
                if idle_elapsed < self._idle_rebuild_require_idle_sec:
                    return 0
            if now < self._idle_rebuild_suspend_until:
                remain_sec = self._idle_rebuild_suspend_until - now
                reason_text = self._idle_rebuild_suspend_reason or "未指定"
                logger.debug(
                    f"[OCR重建抑制] 抑制中(剩余{remain_sec:.2f}s, reason={reason_text})，跳过空闲重建检查"
                )
                return 0
            if self._idle_rebuild_suspend_until > 0:
                self._idle_rebuild_suspend_until = 0.0
                self._idle_rebuild_suspend_reason = ""

            process_snapshot = [
                (process_id, process_info.process, process_info.get_window_count())
                for process_id, process_info in self.processes.items()
                if process_info.process is not None and process_info.is_active and not process_info.is_retiring
            ]

        rebuild_candidates: List[Tuple[str, float, int]] = []
        for process_id, process, window_count in process_snapshot:
            rss_mb = self._get_process_rss_mb(process)
            if rss_mb >= threshold_mb:
                rebuild_candidates.append((process_id, rss_mb, window_count))

        rebuild_count = 0
        terminate_count = 0
        for process_id, rss_mb, window_count in rebuild_candidates:
            # 没有窗口绑定的高内存进程直接清理，不做替换重建
            if window_count <= 0:
                with self._pool_lock:
                    if process_id in self.processes:
                        self.processes[process_id].is_active = False
                        self.processes[process_id].last_used = 0
                terminate_count += 1
                logger.warning(
                    f"[OCR重建] 无OCR任务执行且内存超限({rss_mb:.1f}MB >= {threshold_mb:.0f}MB)，无窗口绑定，标记立即清理: {process_id}"
                )
                continue

            if self._schedule_process_rebuild(process_id):
                rebuild_count += 1
                logger.warning(
                    f"[OCR重建] 无OCR任务执行且内存超限({rss_mb:.1f}MB >= {threshold_mb:.0f}MB)，已发起重建: {process_id}"
                )

        if (rebuild_count + terminate_count) > 0:
            self._cleanup_inactive_processes(force_immediate=True)
        return rebuild_count + terminate_count

    def _mark_ocr_activity_locked(self, timestamp: Optional[float] = None) -> None:
        """在持锁上下文记录OCR活动时间"""
        ts = float(timestamp) if isinstance(timestamp, (int, float)) and timestamp > 0 else time.time()
        if ts > self._last_ocr_activity_ts:
            self._last_ocr_activity_ts = ts

    def _begin_ocr_request_locked(self, timestamp: Optional[float] = None) -> None:
        """在持锁上下文登记OCR请求开始。"""
        self._active_ocr_requests += 1
        self._mark_ocr_activity_locked(timestamp)

    def _end_ocr_request_locked(self, timestamp: Optional[float] = None) -> None:
        """在持锁上下文登记OCR请求结束。"""
        if self._active_ocr_requests > 0:
            self._active_ocr_requests -= 1
        self._mark_ocr_activity_locked(timestamp)

    def get_hot_reset_remaining_idle_sec(self, idle_seconds: float = 3.0) -> float:
        """返回触发热重置还需等待的空闲秒数（0 表示可立即热重置）"""
        try:
            target_idle = float(idle_seconds)
        except (TypeError, ValueError):
            target_idle = 3.0
        if target_idle < 0:
            target_idle = 0.0

        now = time.time()
        with self._pool_lock:
            if self._is_shutdown or (not self._running):
                return target_idle

            if self._active_ocr_requests > 0:
                return target_idle

            has_busy_worker = any(
                process_info.is_busy
                for process_info in self.processes.values()
            )
            if has_busy_worker:
                return target_idle

            last_activity = self._last_ocr_activity_ts

        if last_activity <= 0:
            return 0.0

        idle_elapsed = now - last_activity
        if idle_elapsed >= target_idle:
            return 0.0
        return max(0.0, target_idle - idle_elapsed)

    def _get_effective_max_processes_locked(self) -> int:
        """在锁内计算当前有效的进程上限"""
        if not self._adaptive_scale_enabled:
            return self.max_processes

        mapped_windows = len(self.window_process_mapping)
        windows_target = (
            (mapped_windows + self.max_windows_per_process - 1) // self.max_windows_per_process
            if mapped_windows > 0 else 1
        )

        active_requests = max(0, int(self._active_ocr_requests))
        request_threads_per_process = max(1, int(self._threads_per_process))
        request_target = (
            (active_requests + request_threads_per_process - 1) // request_threads_per_process
            if active_requests > 0 else 1
        )

        # 规则：
        # - 无在途请求（预注册/空闲）阶段：沿用窗口驱动，确保预创建能按窗口规模完成。
        # - 有在途请求（并发执行）阶段：改为并发请求驱动，避免按历史窗口数持续扩容。
        if active_requests > 0:
            base_target = request_target
        else:
            base_target = windows_target

        base_target = max(self._adaptive_min_processes, base_target)
        self._effective_max_processes = min(self.max_processes, base_target)
        return self._effective_max_processes

    def _release_shared_memory_slot(self, process_id: str) -> None:
        """释放指定进程的共享内存槽"""
        slot = None
        with self._pool_lock:
            slot = self._shm_slots.pop(process_id, None)

        if slot is None:
            return

        try:
            slot.shm.close()
        except Exception:
            pass

        try:
            slot.shm.unlink()
        except Exception:
            pass

    def _release_all_shared_memory_slots(self) -> None:
        """释放所有共享内存槽"""
        with self._pool_lock:
            process_ids = list(self._shm_slots.keys())
        for process_id in process_ids:
            self._release_shared_memory_slot(process_id)

    def _acquire_shared_memory_slot(self, process_id: str, required_size: int):
        """获取可复用共享内存槽，必要时扩容重建"""
        if not self._shared_memory_reuse_enabled:
            return None

        if required_size <= 0:
            return None

        reuse_max_bytes = int(self._shared_memory_reuse_max_mb * 1024 * 1024)
        if required_size > reuse_max_bytes:
            # 超大帧不复用，避免主进程长期持有巨型共享内存槽
            self._release_shared_memory_slot(process_id)
            return None

        release_oversized_slot = False

        with self._pool_lock:
            slot = self._shm_slots.get(process_id)
            if slot is not None and slot.capacity > reuse_max_bytes:
                release_oversized_slot = True
            elif slot is not None and slot.capacity >= required_size:
                return slot.shm

        if release_oversized_slot:
            self._release_shared_memory_slot(process_id)

        # 容量不足时，先释放旧槽再重建
        self._release_shared_memory_slot(process_id)

        try:
            import multiprocessing.shared_memory as shm
            new_shm = shm.SharedMemory(create=True, size=required_size)
        except Exception:
            return None

        with self._pool_lock:
            self._shm_slots[process_id] = OCRSharedMemorySlot(shm=new_shm, capacity=required_size)
        return new_shm

    def _create_ocr_process(self, process_id: str) -> Optional[OCRProcessInfo]:
        """创建新的OCR工作进程"""
        try:
            process: Optional[subprocess.Popen] = None
            client_socket: Optional[socket.socket] = None

            # 防御：禁止在主线程同步创建OCR子进程
            if threading.current_thread() is threading.main_thread():
                logger.error(f"[OCR进程创建] 禁止在主线程创建OCR进程: {process_id}")
                return None

            # 【Nuitka修复】使用 subprocess 启动子进程
            # 通过命令行参数 --ocr-worker 让 main.py 在最开头检测并直接执行 worker
            # 这样可以完全避免 PySide6 加载

            # 创建 socket 服务器监听端口
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(('127.0.0.1', 0))  # 绑定到随机可用端口
            server_socket.listen(1)
            port = server_socket.getsockname()[1]

            project_root = os.path.dirname(os.path.dirname(__file__))

            try:
                cmd = build_worker_launch_command(
                    worker_flag="--ocr-worker",
                    module_name="services.multiprocess_ocr_worker",
                    standalone_flag="--ocr-worker-standalone",
                    extra_args=["--process-id", process_id, "--port", str(port)],
                    require_python_executable=True,
                    project_root=project_root,
                )
            except FileNotFoundError:
                logger.error("[OCR进程创建] 未找到可用的 Python 解释器")
                server_socket.close()
                return None

            child_env = build_worker_process_env(project_root=project_root)

            # 启动子进程
            # 使用 CREATE_NO_WINDOW 标志避免创建控制台窗口
            creation_flags = 0
            if os.name == 'nt':
                creation_flags = subprocess.CREATE_NO_WINDOW

            # 子进程日志由子进程内部的logging模块管理，主进程不重定向stdout/stderr
            # 这样可以让子进程使用RotatingFileHandler实现真正的日志轮转
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=project_root,
                env=child_env,
                creationflags=creation_flags
            )

            # 等待子进程连接（可配置超时）
            server_socket.settimeout(self._worker_connect_timeout)
            try:
                client_socket, _addr = server_socket.accept()
            except socket.timeout:
                logger.error(f"[进程创建] 等待子进程连接超时")
                self._terminate_process_tree(process, wait_timeout=1.0)
                return None
            finally:
                server_socket.close()

            # 等待子进程发送就绪消息（可配置超时）
            ready_msg = _recv_message(client_socket, timeout=self._worker_ready_timeout)
            if not ready_msg or ready_msg.get('type') != 'ready':
                logger.error(f"[进程创建] 未收到子进程就绪消息: {ready_msg}")
                try:
                    client_socket.close()
                except Exception:
                    pass
                self._terminate_process_tree(process, wait_timeout=1.0)
                return None

            # 创建进程信息
            process_info = OCRProcessInfo(
                process_id=process_id,
                process=process,
                request_queue=None,  # 不再使用 multiprocessing.Queue
                response_queue=None,
                socket_conn=client_socket,
                socket_port=port,
                is_active=True,
                last_used=time.time(),
                max_windows=self.max_windows_per_process
            )

            return process_info

        except Exception as e:
            if client_socket is not None:
                try:
                    client_socket.close()
                except Exception:
                    pass
            self._terminate_process_tree(process, wait_timeout=1.0)
            logger.error(f"创建OCR工作进程失败: {process_id}, 错误: {e}")
            return None

    def _find_best_process_for_window(
        self,
        window_hwnd: int,
        window_title: str,
        resource_key: Optional[str] = None,
        _retry_count: int = 0
    ) -> Optional[str]:
        """找到最适合分配给窗口的进程

        Args:
            window_hwnd: 窗口句柄
            window_title: 窗口标题
            _retry_count: 内部重试计数（防止无限循环）
        """
        # 【修复闪退】使用迭代替代递归，防止栈溢出
        MAX_RETRIES = 3
        current_retry = _retry_count
        normalized_resource_key = self._normalize_resource_key(resource_key)

        while current_retry <= MAX_RETRIES:
            new_process_id = None
            need_retry = False  # 【修复死锁】标记是否需要重试

            with self._pool_lock:
                now_ts = time.time()
                self._prune_resource_mappings_locked(now=now_ts)
                # 1. 检查窗口是否已经分配给某个进程
                if window_hwnd in self.window_process_mapping:
                    process_id = self.window_process_mapping[window_hwnd]
                    if process_id in self.processes:
                        process_info = self.processes[process_id]
                        is_dead = process_info.process is not None and not _is_process_alive(process_info.process)
                        is_invalid_placeholder = process_info.process is None and not process_info.is_creating
                        is_retiring = process_info.is_retiring

                        if is_retiring:
                            process_info.remove_window(window_hwnd)
                            if self.window_process_mapping.get(window_hwnd) == process_id:
                                del self.window_process_mapping[window_hwnd]
                            need_retry = True
                        elif is_dead or is_invalid_placeholder:
                            if process_id in self.processes:
                                del self.processes[process_id]
                                self._purge_resource_mappings_for_process_locked(process_id)
                                self._release_shared_memory_slot(process_id)
                            if self.window_process_mapping.get(window_hwnd) == process_id:
                                del self.window_process_mapping[window_hwnd]
                            need_retry = True
                        else:
                            if not process_info.is_active and process_info.process is not None:
                                process_info.is_active = True
                                process_info.last_used = now_ts
                            if normalized_resource_key:
                                self._touch_resource_mapping_locked(
                                    normalized_resource_key,
                                    process_id,
                                    now=now_ts
                                )
                            return process_id
                    else:
                        del self.window_process_mapping[window_hwnd]
                        need_retry = True

                # 【修复死锁】如果需要重试，跳过后续处理，直接退出锁块
                if not need_retry and normalized_resource_key:
                    routed_process_id = self._resource_process_mapping.get(normalized_resource_key)
                    if routed_process_id:
                        routed_info = self.processes.get(routed_process_id)
                        if routed_info is None:
                            self._resource_process_mapping.pop(normalized_resource_key, None)
                            self._resource_last_used.pop(normalized_resource_key, None)
                        else:
                            routed_dead = routed_info.process is not None and not _is_process_alive(routed_info.process)
                            routed_invalid_placeholder = routed_info.process is None and not routed_info.is_creating
                            if routed_info.is_retiring or routed_dead or routed_invalid_placeholder:
                                if routed_process_id in self.processes and (routed_dead or routed_invalid_placeholder):
                                    del self.processes[routed_process_id]
                                    self._release_shared_memory_slot(routed_process_id)
                                    windows_to_remove = [
                                        hwnd for hwnd, pid in self.window_process_mapping.items()
                                        if pid == routed_process_id
                                    ]
                                    for hwnd in windows_to_remove:
                                        del self.window_process_mapping[hwnd]
                                self._purge_resource_mappings_for_process_locked(routed_process_id)
                            else:
                                if routed_info.process is not None and not routed_info.is_active:
                                    routed_info.is_active = True
                                    routed_info.last_used = now_ts

                                already_assigned = window_hwnd in routed_info.assigned_windows
                                if already_assigned or routed_info.can_accept_window():
                                    if already_assigned or routed_info.add_window(window_hwnd, window_title):
                                        self.window_process_mapping[window_hwnd] = routed_process_id
                                        self._touch_resource_mapping_locked(
                                            normalized_resource_key,
                                            routed_process_id,
                                            now=now_ts
                                        )
                                        return routed_process_id

                if not need_retry:
                    # 2. 寻找负载最轻的可用进程（优先选择已有活跃进程，避免创建过多进程）
                    # 按进程ID排序后遍历，确保稳定的选择顺序
                    best_process_id = None
                    min_window_count = float('inf')
                    for process_id in sorted(self.processes.keys()):
                        process_info = self.processes[process_id]

                        # 跳过已死亡的进程
                        if process_info.process is not None and not _is_process_alive(process_info.process):
                            continue

                        # 检查进程是否可以接受新窗口
                        if not process_info.can_accept_window():
                            continue

                        # 重新激活非活跃进程
                        if process_info.process is not None and not process_info.is_active:
                            process_info.is_active = True
                            process_info.last_used = now_ts

                        # 选择窗口数最少的进程
                        window_count = process_info.get_window_count()
                        if window_count < min_window_count or (window_count == min_window_count and (best_process_id is None or process_id < best_process_id)):
                            min_window_count = window_count
                            best_process_id = process_id

                    # 3. 如果找到合适的进程，分配窗口
                    if best_process_id:
                        process_info = self.processes[best_process_id]
                        if not process_info.can_accept_window():
                            best_process_id = None
                        elif process_info.add_window(window_hwnd, window_title):
                            self.window_process_mapping[window_hwnd] = best_process_id
                            if normalized_resource_key:
                                self._touch_resource_mapping_locked(
                                    normalized_resource_key,
                                    best_process_id,
                                    now=now_ts
                                )
                            return best_process_id
                        else:
                            best_process_id = None

                    # 4. 如果没有可用进程且未达到进程上限，创建占位符
                    # 【关键修复】退役中的进程不应占用新建配额，否则会出现：
                    # 第一次识别成功后标记退役，第二次识别因“进程池已满”无法拉起替换进程
                    effective_limit = self._get_effective_max_processes_locked()
                    # 关键边界：当前窗口即将分配到“新进程”分支时，
                    # 需要把“本次待分配窗口”纳入容量评估，避免在 3/6/9 ... 边界卡住无法扩容
                    pending_windows_target = (
                        (len(self.window_process_mapping) + 1 + self.max_windows_per_process - 1)
                        // self.max_windows_per_process
                    )
                    if pending_windows_target > effective_limit:
                        effective_limit = min(self.max_processes, pending_windows_target)
                    effective_process_count = 0
                    for existing_info in self.processes.values():
                        # 退役进程即将被清理，不计入可用容量
                        if existing_info.is_retiring:
                            continue
                        # 已死亡进程不计入（后续清理线程会回收）
                        if existing_info.process is not None and not _is_process_alive(existing_info.process):
                            continue
                        # 创建失败的占位符不计入
                        if existing_info.process is None and not existing_info.is_creating:
                            continue
                        effective_process_count += 1

                    if best_process_id is None and effective_process_count < effective_limit:
                        new_process_id = self._generate_process_id()

                        placeholder_info = OCRProcessInfo(
                            process_id=new_process_id,
                            process=None,
                            request_queue=None,
                            response_queue=None,
                            is_active=False,
                            last_used=now_ts,
                            max_windows=self.max_windows_per_process,
                            is_creating=True
                        )
                        placeholder_info.add_window(window_hwnd, window_title)
                        self.processes[new_process_id] = placeholder_info
                        self.window_process_mapping[window_hwnd] = new_process_id
                        if normalized_resource_key:
                            self._touch_resource_mapping_locked(
                                normalized_resource_key,
                                new_process_id,
                                now=now_ts
                            )

            # 如果需要重试，增加计数器并继续循环
            if need_retry:
                current_retry += 1
                continue

            # 在锁外创建进程，避免阻塞其他请求
            if new_process_id:
                self._start_async_create_for_process(new_process_id)
                return new_process_id

            # 进程池已满
            return None

        logger.error(f"重试次数过多，放弃分配: {window_hwnd}")
        return None

    def recognize_text(self, window_title: str, window_hwnd: int, image: np.ndarray,
                      confidence: float = 0.5, timeout: float = 30.0,
                      resource_key: Optional[str] = None) -> List[Dict]:
        """
        执行OCR识别

        Args:
            window_title: 窗口标题
            window_hwnd: 窗口句柄
            image: 图像数据（numpy数组）
            confidence: 置信度阈值
            timeout: 超时时间（秒）

        Returns:
            List[Dict]: OCR结果
        """
        start_time = time.time()
        resolved_resource_key = self._resolve_resource_key(window_hwnd=window_hwnd, resource_key=resource_key)
        request_id = None  # 【内存泄漏修复】确保在所有路径都能清理
        image_shm = None  # 【修复OCR识别失败】跟踪共享内存对象，确保所有路径清理
        process_id = None  # 【内存泄漏修复】确保 finally 中可以正确清理 is_busy
        is_busy_set = False  # 【内存泄漏修复】跟踪是否设置了 is_busy，用于 finally 清理
        use_pending_response = False  # socket模式下不使用_pending_responses
        request_tracked = False  # 全局在途请求计数是否已登记
        force_recycle_process = False  # 请求链路异常后，强制退役当前进程
        request_sent_to_worker = False  # 请求是否已发给worker（用于判定是否需要强制退役）
        response_received = False  # 是否已收到worker响应

        try:
            with self._pool_lock:
                if self._is_shutdown or (not self._running):
                    return []
                self._begin_ocr_request_locked(start_time)
                request_tracked = True

            # 【画面变动修复】请求节流 - 改为排队等待，避免直接丢弃请求
            while True:
                current_time = time.time()
                with self._pool_lock:
                    last_request_time = self._window_last_request_time.get(window_hwnd, 0)
                    time_since_last = current_time - last_request_time
                    if time_since_last >= self._request_throttle_interval:
                        self._window_last_request_time[window_hwnd] = current_time
                        self._prune_window_request_times_unlocked(now=current_time)
                        break
                    wait_time = self._request_throttle_interval - time_since_last
                if wait_time > 0:
                    time.sleep(min(wait_time, 0.05))

            # 获取或创建OCR进程
            process_id = self._find_best_process_for_window(
                window_hwnd,
                window_title,
                resource_key=resolved_resource_key
            )
            if not process_id:
                logger.error(f"无法获取OCR进程: {window_title}")
                return []

            # 获取进程信息（带等待机制，作为第二道保险）
            max_wait_for_process = self._process_ready_timeout
            try:
                max_wait_for_process = max(max_wait_for_process, float(timeout))
            except (TypeError, ValueError):
                pass
            wait_start = time.time()
            dead_process_retry_count = 0

            while True:
                need_rebuild_process = False
                with self._pool_lock:
                    if process_id not in self.processes:
                        logger.error(f"OCR进程不存在: {process_id}")
                        return []

                    process_info = self.processes[process_id]

                    # 【修复OCR识别失败】检查占位符是否创建失败（is_creating=False且process仍为None说明创建失败）
                    if process_info.process is None and not process_info.is_creating:
                        logger.error(f"OCR进程创建失败，占位符已被标记为失败: {process_id}")
                        return []

                    # 检查进程是否就绪
                    if process_info.process is not None and process_info.is_active and _is_process_alive(process_info.process):
                        # 进程已就绪，退出等待循环
                        break
                    elif process_info.process is not None and not _is_process_alive(process_info.process):
                        stale_process_id = process_id
                        if stale_process_id in self.processes:
                            del self.processes[stale_process_id]
                            self._purge_resource_mappings_for_process_locked(stale_process_id)
                            self._release_shared_memory_slot(stale_process_id)
                        if self.window_process_mapping.get(window_hwnd) == stale_process_id:
                            del self.window_process_mapping[window_hwnd]

                        if dead_process_retry_count >= 1:
                            logger.error(f"OCR进程已终止且重建失败: {stale_process_id}")
                            return []

                        dead_process_retry_count += 1
                        need_rebuild_process = True

                if need_rebuild_process:
                    process_id = self._find_best_process_for_window(
                        window_hwnd,
                        window_title,
                        resource_key=resolved_resource_key
                    )
                    if not process_id:
                        logger.error(f"OCR进程重建失败: {window_title}")
                        return []
                    wait_start = time.time()
                    continue

                # 检查超时
                elapsed = time.time() - wait_start
                if elapsed >= max_wait_for_process:
                    with self._pool_lock:
                        # 【修复闪退】正确检查进程是否在字典中
                        proc_state = "占位符" if process_id in self.processes and self.processes[process_id].process is None else "未知"
                    logger.error(f"等待OCR进程就绪超时({elapsed:.1f}s，状态:{proc_state}): {process_id}")
                    return []

                # 继续等待
                time.sleep(0.1)

            # 【多窗口并发修复】等待进程空闲后处理，而不是丢弃请求
            # 这样多个窗口的OCR请求可以排队处理，避免因流控导致识别失败
            max_busy_wait = self._busy_wait_timeout
            busy_wait_start = time.time()
            while True:
                with self._pool_lock:
                    if not process_info.is_busy:
                        # 进程空闲，标记为忙并退出等待
                        process_info.is_busy = True
                        self._mark_ocr_activity_locked()
                        is_busy_set = True
                        break

                # 检查等待超时
                busy_elapsed = time.time() - busy_wait_start
                if busy_elapsed >= max_busy_wait:
                    return []

                time.sleep(0.1)

            # 生成请求ID
            request_id = self._generate_request_id()

            # 仅 multiprocessing.Queue 模式需要 pending 队列；socket 模式直接阻塞收包
            response_queue = None
            if process_info.request_queue is not None and process_info.socket_conn is None:
                use_pending_response = True
                response_queue = queue.Queue()
                with self._pool_lock:
                    self._pending_responses[request_id] = response_queue

            # 【优化】使用共享内存传递大图像，避免pickle序列化大数据导致"Ran out of input"错误
            # 对于大图像（>100KB），使用共享内存；小图像直接序列化
            image_size_kb = image.nbytes / 1024
            use_shared_memory = image_size_kb > self._shared_memory_threshold_kb

            if use_shared_memory:
                try:
                    import multiprocessing.shared_memory as shm
                    # 强制临时共享内存：请求结束即释放，不在主进程常驻
                    image_shm = shm.SharedMemory(create=True, size=image.nbytes)

                    # 复制图像数据到共享内存
                    shared_array = np.ndarray(image.shape, dtype=image.dtype, buffer=image_shm.buf)
                    np.copyto(shared_array, image)
                    # 【内存泄漏修复】立即删除共享内存视图引用，允许GC回收
                    del shared_array

                    # 构建请求（使用共享内存名称）
                    request = {
                        'request_id': request_id,
                        'window_hwnd': window_hwnd,
                        'window_title': window_title,
                        'use_shared_memory': True,
                        'shm_name': image_shm.name,
                        'shm_size': image.nbytes,  # 共享内存大小
                        'image_shape': image.shape,
                        'image_dtype': str(image.dtype),
                        'confidence': confidence,
                        'timestamp': time.time()
                    }

                except ImportError:
                    use_shared_memory = False
                    image_shm = None
                except Exception:
                    use_shared_memory = False
                    image_shm = None

            if not use_shared_memory:
                # 序列化图像数据（小图像或共享内存不可用时）
                image_bytes = image.tobytes()
                image_shape = image.shape
                image_dtype = str(image.dtype)

                # 构建请求（添加窗口标识，用于区分多窗口）
                request = {
                    'request_id': request_id,
                    'window_hwnd': window_hwnd,
                    'window_title': window_title,
                    'use_shared_memory': False,
                    'image': image_bytes,
                    'image_shape': image_shape,
                    'image_dtype': image_dtype,
                    'confidence': confidence,
                    'timestamp': time.time()
                }

            # 发送请求到进程
            if process_info.socket_conn is not None:
                # 使用 socket 通信
                try:
                    if not _send_message(process_info.socket_conn, request):
                        force_recycle_process = True
                        logger.error(f"发送OCR请求失败: {process_id}")
                        return []
                    request_sent_to_worker = True
                except Exception:
                    with self._pool_lock:
                        process_info.is_active = False
                    force_recycle_process = True
                    return []

                if not use_shared_memory and 'image_bytes' in locals():
                    del image_bytes
                del request

                # 等待响应
                try:
                    response = _recv_message(process_info.socket_conn, timeout=timeout)
                    if response is None:
                        force_recycle_process = request_sent_to_worker
                        logger.error(f"OCR响应超时: {process_id}")
                        return []
                    response_received = True
                except Exception:
                    force_recycle_process = request_sent_to_worker
                    return []

            elif process_info.request_queue is not None:
                # 使用 multiprocessing.Queue 通信
                try:
                    process_info.request_queue.put(request, timeout=5)
                    request_sent_to_worker = True
                except Exception:
                    with self._pool_lock:
                        process_info.is_active = False
                    force_recycle_process = True
                    return []

                if not use_shared_memory and 'image_bytes' in locals():
                    del image_bytes
                del request

                try:
                    if response_queue is None:
                        force_recycle_process = request_sent_to_worker
                        return []
                    response = response_queue.get(timeout=timeout)
                    response_received = True
                except Exception:
                    force_recycle_process = request_sent_to_worker
                    return []
            else:
                force_recycle_process = request_sent_to_worker
                return []

            # 验证响应窗口句柄
            response_hwnd = response.get('window_hwnd', 0)
            if response_hwnd != window_hwnd:
                force_recycle_process = True
                logger.error(f"OCR响应窗口不匹配: 请求={window_hwnd}, 响应={response_hwnd}")
                return []

            # 处理响应
            worker_should_recycle = bool(response.get('worker_should_recycle', False))
            if response.get('success'):
                results = response.get('results', [])
                processing_time = response.get('processing_time', 0)

                with self._pool_lock:
                    if process_id in self.processes:
                        process_info = self.processes[process_id]
                        now_ts = time.time()
                        process_info.last_used = now_ts
                        self._mark_ocr_activity_locked(now_ts)
                        process_info.total_requests += 1
                        process_info.total_processing_time += processing_time
                        if worker_should_recycle:
                            process_info.is_retiring = True

                del response
                return results
            else:
                if worker_should_recycle:
                    with self._pool_lock:
                        if process_id in self.processes:
                            self.processes[process_id].is_retiring = True
                del response
                return []

        except queue.Empty:
            force_recycle_process = request_sent_to_worker and (not response_received)
            with self._pool_lock:
                if process_id in self.processes:
                    process_info = self.processes[process_id]
                    if process_info.process and not _is_process_alive(process_info.process):
                        process_info.is_active = False
                    elif process_info.request_queue is not None:
                        try:
                            process_info.request_queue.put({'command': 'PING'}, block=False)
                        except Exception:
                            process_info.is_active = False
            return []

        except Exception as e:
            logger.error(f"OCR识别异常: {e}")
            return []
        finally:
            # 清理共享内存
            if image_shm is not None:
                try:
                    image_shm.close()
                    image_shm.unlink()
                except Exception:
                    pass

            # 清理响应队列
            if request_id and use_pending_response:
                with self._pool_lock:
                    if request_id in self._pending_responses:
                        try:
                            q = self._pending_responses[request_id]
                            while not q.empty():
                                try:
                                    q.get_nowait()
                                except Exception:
                                    break
                            del self._pending_responses[request_id]
                        except Exception:
                            pass

            # 清除is_busy标志
            need_force_cleanup = False
            with self._pool_lock:
                if is_busy_set and process_id and process_id in self.processes:
                    self.processes[process_id].is_busy = False
                    self._mark_ocr_activity_locked()

                # 请求链路异常且请求已发给worker，但未拿到有效响应：强制退役该进程
                if force_recycle_process and process_id and process_id in self.processes:
                    proc_info = self.processes[process_id]
                    proc_info.is_retiring = True
                    proc_info.is_active = False
                    proc_info.last_used = 0.0
                    proc_info.assigned_windows.clear()
                    for hwnd, mapped_pid in list(self.window_process_mapping.items()):
                        if mapped_pid == process_id:
                            del self.window_process_mapping[hwnd]
                    need_force_cleanup = True

                if request_tracked:
                    self._end_ocr_request_locked()

            if need_force_cleanup:
                self._cleanup_inactive_processes(force_immediate=True)

    def _acquire_idle_workers_for_hot_reset(
        self,
        require_all_idle: bool = True,
        preferred_process_id: Optional[str] = None,
        max_targets: Optional[int] = None
    ) -> List[Tuple[str, socket.socket]]:
        reset_targets: List[Tuple[str, socket.socket]] = []
        with self._pool_lock:
            if self._is_shutdown or not self._running or not self.processes:
                return reset_targets
            if self._active_ocr_requests > 0:
                return reset_targets

            if require_all_idle:
                for process_info in self.processes.values():
                    if process_info.is_busy:
                        return reset_targets

            candidate_ids: List[str] = []
            if preferred_process_id and preferred_process_id in self.processes:
                candidate_ids.append(preferred_process_id)
            for process_id in sorted(self.processes.keys()):
                if preferred_process_id and process_id == preferred_process_id:
                    continue
                candidate_ids.append(process_id)

            for process_id in candidate_ids:
                process_info = self.processes.get(process_id)
                if process_info is None:
                    continue
                if not process_info.is_active:
                    continue
                if process_info.process is None or process_info.socket_conn is None:
                    continue
                if not _is_process_alive(process_info.process):
                    process_info.is_active = False
                    continue

                process_info.is_busy = True
                reset_targets.append((process_id, process_info.socket_conn))
                if max_targets is not None and len(reset_targets) >= max_targets:
                    break
        return reset_targets

    def _execute_hot_reset(self, reset_targets: List[Tuple[str, socket.socket]], force: bool = False) -> bool:
        if not reset_targets:
            return False

        has_success_reset = False

        for process_id, sock in reset_targets:
            communication_ok = True
            reset_applied = False
            try:
                if not _send_message(sock, {'command': 'RESET_ENGINE', 'force': bool(force)}):
                    communication_ok = False
                else:
                    response = _recv_message(sock, timeout=2.0)
                    if not isinstance(response, dict) or response.get('type') != 'reset_engine':
                        communication_ok = False
                    else:
                        # success=False（如冷却中）不是通信故障，只是不执行重置
                        reset_applied = bool(response.get('success', False))
            except Exception:
                communication_ok = False
            finally:
                with self._pool_lock:
                    process_info = self.processes.get(process_id)
                    if process_info is None:
                        continue
                    process_info.is_busy = False
                    if communication_ok:
                        if reset_applied:
                            has_success_reset = True
                        process_info.last_used = time.time()
                    else:
                        process_info.is_active = False

        return has_success_reset

    def _hot_reset_workers_when_all_idle(self, force: bool = False) -> bool:
        reset_targets = self._acquire_idle_workers_for_hot_reset(require_all_idle=True)
        return self._execute_hot_reset(reset_targets, force=force)

    def _hot_reset_idle_workers(
        self,
        force: bool = False,
        preferred_process_id: Optional[str] = None,
        max_targets: int = 1
    ) -> bool:
        reset_targets = self._acquire_idle_workers_for_hot_reset(
            require_all_idle=False,
            preferred_process_id=preferred_process_id,
            max_targets=max_targets
        )
        return self._execute_hot_reset(reset_targets, force=force)

    def hot_reset_all_idle_workers(self, force: bool = True) -> bool:
        """公开接口：当OCR子进程全部空闲时，立即热重置引擎。"""
        try:
            return bool(self._hot_reset_workers_when_all_idle(force=force))
        except Exception as e:
            logger.error(f"热重置空闲OCR子进程失败: {e}")
            return False

    def release_idle_shared_memory_slots(self) -> int:
        """释放空闲OCR进程持有的共享内存槽（不销毁进程）。"""
        try:
            with self._pool_lock:
                releasable_ids = [
                    process_id
                    for process_id, process_info in self.processes.items()
                    if not process_info.is_busy
                ]

            released_count = 0
            for process_id in releasable_ids:
                self._release_shared_memory_slot(process_id)
                released_count += 1
            return released_count
        except Exception as e:
            logger.error(f"释放空闲共享内存槽失败: {e}")
            return 0

    def hot_reset_and_cleanup_idle_resources(self, force: bool = True) -> bool:
        """
        OCR->非OCR切换时使用：
        - 仅对空闲子进程做热重置
        - 释放空闲共享内存槽
        - 保留子进程本体，供下次OCR任务复用
        """
        try:
            # 不要求“全部空闲”，仅处理当前空闲进程
            reset_targets = self._acquire_idle_workers_for_hot_reset(
                require_all_idle=False,
                preferred_process_id=None,
                max_targets=None
            )
            reset_ok = bool(self._execute_hot_reset(reset_targets, force=force))
            released_slots = int(self.release_idle_shared_memory_slots())

            if released_slots > 0:
                logger.info(f"[OCR空闲清理] 已释放共享内存槽: {released_slots}")
            return bool(reset_ok or released_slots > 0)
        except Exception as e:
            logger.error(f"热重置并清理空闲资源失败: {e}")
            return False

    def _cleanup_old_log_files(self):
        """【日志优化】定期清理过期的OCR子进程日志文件

        清理规则：
        - 删除超过7天的日志文件
        - 立即删除所有备份日志文件（不再保留备份）
        """
        try:
            log_dir = get_logs_dir("LCA")
            if not os.path.exists(log_dir):
                return

            current_time = time.time()
            max_age_seconds = 7 * 24 * 3600  # 7天
            deleted_count = 0

            try:
                all_files = os.listdir(log_dir)
            except (OSError, PermissionError):
                return

            for f in all_files:
                if not f.startswith('ocr_worker_'):
                    continue

                file_path = os.path.join(log_dir, f)

                # 立即删除所有备份日志（.log.1, .log.2等）
                if '.log.' in f and not f.endswith('.log'):
                    try:
                        os.remove(file_path)
                        deleted_count += 1
                    except (OSError, PermissionError):
                        pass
                    continue

                # 删除超过7天的主日志文件
                if f.endswith('.log'):
                    try:
                        stat_info = os.stat(file_path)
                        if current_time - stat_info.st_mtime > max_age_seconds:
                            os.remove(file_path)
                            deleted_count += 1
                    except (OSError, PermissionError):
                        pass

            # Enforce total OCR log size cap to avoid runaway disk usage
            max_total_size = 50 * 1024 * 1024  # 50MB
            log_files = []
            total_size = 0

            for f in all_files:
                if not f.startswith('ocr_worker_'):
                    continue
                if not (f.endswith('.log') or '.log.' in f):
                    continue
                file_path = os.path.join(log_dir, f)
                try:
                    stat_info = os.stat(file_path)
                except (OSError, PermissionError):
                    continue
                total_size += stat_info.st_size
                log_files.append((file_path, stat_info.st_mtime, stat_info.st_size))

            if total_size > max_total_size:
                log_files.sort(key=lambda x: x[1])
                for file_path, _, file_size in log_files:
                    if total_size <= max_total_size:
                        break
                    try:
                        os.remove(file_path)
                        total_size -= file_size
                        deleted_count += 1
                    except (OSError, PermissionError):
                        pass

        except Exception:
            pass

    def _is_ocr_log_size_exceeded(self) -> bool:
        """Return True when OCR log total size exceeds the cap."""
        max_total_size = 50 * 1024 * 1024  # 50MB
        try:
            log_dir = get_logs_dir("LCA")
            if not os.path.exists(log_dir):
                return False
            total_size = 0
            with os.scandir(log_dir) as entries:
                for entry in entries:
                    if not entry.is_file():
                        continue
                    name = entry.name
                    if not name.startswith("ocr_worker_"):
                        continue
                    if not (name.endswith(".log") or ".log." in name):
                        continue
                    try:
                        total_size += entry.stat().st_size
                    except (OSError, PermissionError):
                        continue
                    if total_size > max_total_size:
                        return True
            return False
        except Exception:
            return False

    def _terminate_process_tree(self, process: Optional[subprocess.Popen], wait_timeout: float = 1.0) -> None:
        """终止进程及其子进程树（Windows优先使用 taskkill /T）。"""
        if process is None:
            return

        try:
            pid = int(process.pid)
        except Exception:
            return

        # 已退出则无需处理
        try:
            if process.poll() is not None:
                return
        except Exception:
            pass

        startupinfo = None
        creationflags = 0
        if os.name == 'nt':
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW
            except Exception:
                startupinfo = None
                creationflags = 0

        # 首选 Windows 原生整树终止
        if os.name == 'nt':
            try:
                subprocess.run(
                    ['taskkill', '/F', '/T', '/PID', str(pid)],
                    capture_output=True,
                    timeout=max(1.0, float(wait_timeout) + 1.0),
                    startupinfo=startupinfo,
                    creationflags=creationflags
                )
            except Exception:
                pass

        # 二次兜底：psutil 递归终止
        try:
            import psutil
            root = psutil.Process(pid)
            descendants = root.children(recursive=True)
            for child in descendants:
                try:
                    child.terminate()
                except Exception:
                    pass
            psutil.wait_procs(descendants, timeout=min(1.0, float(wait_timeout)))
            for child in descendants:
                try:
                    if child.is_running():
                        child.kill()
                except Exception:
                    pass
            if root.is_running():
                try:
                    root.terminate()
                    root.wait(timeout=float(wait_timeout))
                except Exception:
                    try:
                        root.kill()
                    except Exception:
                        pass
        except Exception:
            pass

        # 句柄层兜底
        try:
            if _is_process_alive(process):
                process.terminate()
                try:
                    process.wait(timeout=float(wait_timeout))
                except subprocess.TimeoutExpired:
                    pass
        except Exception:
            pass
        try:
            if _is_process_alive(process):
                process.kill()
                try:
                    process.wait(timeout=0.3)
                except subprocess.TimeoutExpired:
                    pass
        except Exception:
            pass

    def _cleanup_inactive_processes(self, force_immediate: bool = False):
        """清理非活跃的进程 - 优化：立即终止空闲进程，释放资源

        Args:
            force_immediate: 如果为True，立即清理所有空闲进程（不等待超时）
        """
        current_time = time.time()
        processes_to_terminate = []

        with self._pool_lock:
            # 【修复OCR识别失败】使用快照避免迭代时字典被修改
            processes_snapshot = list(self.processes.items())

        # 【关键修复】在锁外分析，避免长时间持锁
        for process_id, process_info in processes_snapshot:
            # 跳过占位符
            if process_info.process is None:
                continue

            # 死亡进程优先清理，避免映射残留
            if not _is_process_alive(process_info.process):
                processes_to_terminate.append(process_id)
                continue

            if self._enable_legacy_queue_mode:
                # 【修复OCR识别失败】检查进程是否有pending请求，避免清理正在使用的进程
                has_pending_requests = False
                pending_snapshot = list(self._pending_responses.items())
                for req_id, queue in pending_snapshot:
                    if req_id and req_id.startswith(f"ocr_req_") and process_id in req_id:
                        has_pending_requests = True
                        break

                if has_pending_requests:
                    continue

            # 释放长时间空闲进程的共享内存槽，避免主进程RSS长期保持高水位
            if (
                self._shared_memory_reuse_enabled
                and not process_info.is_busy
                and self._shared_memory_idle_release_sec > 0
            ):
                idle_sec = current_time - process_info.last_used
                if idle_sec >= self._shared_memory_idle_release_sec:
                    self._release_shared_memory_slot(process_id)

            # 【优化】如果force_immediate=True，立即清理空闲进程
            # 否则使用配置的超时时间（已优化为60秒）
            should_terminate = False
            if force_immediate:
                # 立即清理模式：只要没有分配窗口就清理
                should_terminate = process_info.is_empty()
            else:
                if process_info.is_retiring and process_info.is_empty():
                    should_terminate = True
                # 【内存优化】使用配置的超时时间（从600秒优化为60秒）
                elif current_time - process_info.last_used > self._process_timeout and process_info.is_empty():
                    should_terminate = True

            if should_terminate:
                processes_to_terminate.append(process_id)

        # 【关键修复】在锁外终止进程，避免死锁
        for process_id in processes_to_terminate:
            with self._pool_lock:
                if process_id not in self.processes:
                    continue
                process_info = self.processes[process_id]

            try:
                # 检查是否为占位符进程
                if process_info.request_queue is not None:
                    # 发送停止信号
                    try:
                        process_info.request_queue.put({'command': 'STOP'}, timeout=0.5)
                    except:
                        pass

                # 整棵树终止，避免 venv 重定向器保留子进程
                if process_info.process is not None:
                    self._terminate_process_tree(process_info.process, wait_timeout=1.0)

                # 清理队列资源
                try:
                    if process_info.request_queue is not None:
                        process_info.request_queue.close()
                    if process_info.response_queue is not None:
                        process_info.response_queue.close()
                except Exception:
                    pass

                # 清理socket连接
                if process_info.socket_conn is not None:
                    try:
                        process_info.socket_conn.close()
                    except Exception:
                        pass
                    process_info.socket_conn = None

                # 从进程池中移除
                with self._pool_lock:
                    if process_id in self.processes:
                        del self.processes[process_id]
                        self._purge_resource_mappings_for_process_locked(process_id)
                    for hwnd in list(self.window_process_mapping.keys()):
                        if self.window_process_mapping[hwnd] == process_id:
                            del self.window_process_mapping[hwnd]
                self._release_shared_memory_slot(process_id)

            except Exception as e:
                logger.error(f"终止OCR进程失败: {process_id}, 错误: {e}")

    def cleanup_idle_processes_now(self):
        """立即清理所有空闲进程（供外部调用，停止任务时使用）"""
        self._cleanup_inactive_processes(force_immediate=True)

    def cleanup_all_processes_force(self):
        """强制清理所有OCR进程（停止任务时使用，不管是否有窗口分配）"""
        # 方案1：清理进程池中记录的进程
        processes_to_terminate = []
        with self._pool_lock:
            for process_id, process_info in self.processes.items():
                if process_info.process is not None:
                    processes_to_terminate.append(process_id)

        # 在锁外终止进程
        for process_id in processes_to_terminate:
            with self._pool_lock:
                if process_id not in self.processes:
                    continue
                process_info = self.processes[process_id]

            try:
                if process_info.process is None:
                    continue

                pid = process_info.process.pid
                self._terminate_process_tree(process_info.process, wait_timeout=0.8)
                if _is_process_alive(process_info.process):
                    logger.error(f"[强制清理] 进程仍然存活: {process_id}, PID: {pid}")

                # 清理队列资源
                try:
                    if process_info.request_queue is not None:
                        process_info.request_queue.close()
                    if process_info.response_queue is not None:
                        process_info.response_queue.close()
                except Exception:
                    pass

                # 从进程池中移除（无论是否成功终止）
                with self._pool_lock:
                    if process_id in self.processes:
                        del self.processes[process_id]
                        self._purge_resource_mappings_for_process_locked(process_id)
                    # 清理窗口映射
                    for hwnd in list(self.window_process_mapping.keys()):
                        if self.window_process_mapping[hwnd] == process_id:
                            del self.window_process_mapping[hwnd]
                self._release_shared_memory_slot(process_id)

            except Exception as e:
                logger.error(f"强制终止OCR进程失败: {process_id}, 错误: {e}")

        self._release_all_shared_memory_slots()

        # 最终验证
        still_alive = []
        with self._pool_lock:
            for process_id, process_info in self.processes.items():
                if process_info.process and _is_process_alive(process_info.process):
                    still_alive.append(process_id)

        if still_alive:
            logger.error(f"[强制清理] 仍有 {len(still_alive)} 个进程存活")

        # 清理旧日志文件
        self._cleanup_old_log_files()

        cleanup_orphan_ocr_subprocesses(main_pid=os.getpid())

    def _update_performance_stats(self):
        """更新性能统计"""
        with self._pool_lock:
            # 清理孤儿共享内存槽（对应进程已不存在）
            orphan_slot_ids = [pid for pid in list(self._shm_slots.keys()) if pid not in self.processes]
            for orphan_pid in orphan_slot_ids:
                self._release_shared_memory_slot(orphan_pid)
            self._prune_resource_mappings_locked()

            active_count = sum(1 for p in self.processes.values() if p.is_active)
            total_requests = sum(p.total_requests for p in self.processes.values())
            total_time = sum(p.total_processing_time for p in self.processes.values())
            effective_max = self._get_effective_max_processes_locked()
            shm_slots = len(self._shm_slots)
            shm_total_mb = sum(slot.capacity for slot in self._shm_slots.values()) / (1024 * 1024)

            self._performance_stats.update({
                "total_processes": len(self.processes),
                "active_processes": active_count,
                "total_requests": total_requests,
                "average_processing_time": total_time / total_requests if total_requests > 0 else 0.0,
                "effective_max_processes": effective_max,
                "shared_memory_slots": shm_slots,
                "shared_memory_total_mb": round(shm_total_mb, 2),
                "resource_routes": len(self._resource_process_mapping)
            })

    def get_stats(self) -> Dict:
        """获取性能统计"""
        with self._pool_lock:
            return self._performance_stats.copy()

    def check_and_ensure_process_for_window(
        self,
        window_hwnd: int,
        window_title: str,
        resource_key: Optional[str] = None
    ) -> bool:
        """
        检查并确保窗口有可用的OCR子进程

        Args:
            window_hwnd: 窗口句柄
            window_title: 窗口标题

        Returns:
            bool: 是否成功确保有可用的OCR子进程
        """
        resolved_resource_key = self._resolve_resource_key(window_hwnd=window_hwnd, resource_key=resource_key)
        # 1. 检查窗口是否已经分配了进程
        with self._pool_lock:
            if window_hwnd in self.window_process_mapping:
                process_id = self.window_process_mapping[window_hwnd]

                # 检查进程是否存在且真实运行
                if process_id in self.processes:
                    process_info = self.processes[process_id]

                    # 检查进程是否真实存在且活跃
                    if process_info.process is not None and _is_process_alive(process_info.process):
                        if resolved_resource_key:
                            self._touch_resource_mapping_locked(resolved_resource_key, process_id)
                        return True
                    elif process_info.is_creating:
                        if resolved_resource_key:
                            self._touch_resource_mapping_locked(resolved_resource_key, process_id)
                        return True
                    else:
                        # 进程已死亡，清理映射
                        del self.window_process_mapping[window_hwnd]
                        self._window_last_request_time.pop(window_hwnd, None)
                        if process_id in self.processes:
                            del self.processes[process_id]
                            self._purge_resource_mappings_for_process_locked(process_id)
                        self._release_shared_memory_slot(process_id)
                else:
                    # 进程不存在，清理映射
                    del self.window_process_mapping[window_hwnd]
                    self._window_last_request_time.pop(window_hwnd, None)
                    self._release_shared_memory_slot(process_id)

        # 窗口没有分配进程或原进程已失效
        process_id = self._find_best_process_for_window(
            window_hwnd,
            window_title,
            resource_key=resolved_resource_key
        )

        if not process_id:
            logger.error(f"[OCR] 分配进程失败: {window_hwnd}")
            return False
        return True

    def preregister_window(
        self,
        window_title: str,
        window_hwnd: int,
        wait_ready: bool = True,
        resource_key: Optional[str] = None
    ) -> bool:
        """预注册窗口

        Args:
            window_title: 窗口标题
            window_hwnd: 窗口句柄
            wait_ready: 是否等待进程真正就绪（默认True，确保返回时进程可用）
        """
        if not self._preregister_allocate_enabled:
            # 默认仅做登记，不提前分配OCR子进程，避免启动阶段瞬时扩容
            return True

        resolved_resource_key = self._resolve_resource_key(window_hwnd=window_hwnd, resource_key=resource_key)
        process_id = self._find_best_process_for_window(
            window_hwnd,
            window_title,
            resource_key=resolved_resource_key
        )
        if not process_id:
            logger.error(f"[预注册] 为窗口分配OCR进程失败: {window_title} (HWND: {window_hwnd})")
            return False

        # 等待进程真正就绪（不再是占位符状态）
        if wait_ready:
            max_wait = 10.0  # 最多等待10秒
            wait_start = time.time()
            while True:
                with self._pool_lock:
                    if process_id not in self.processes:
                        logger.error(f"[预注册] 进程在等待期间被删除: {process_id}")
                        return False

                    process_info = self.processes[process_id]
                    if process_info.process is not None and process_info.is_active:
                        return True

                # 检查超时
                elapsed = time.time() - wait_start
                if elapsed >= max_wait:
                    logger.error(f"[预注册] 等待OCR进程就绪超时({elapsed:.1f}s): {window_title} -> {process_id}")
                    return False

                # 继续等待
                time.sleep(0.1)
        else:
            return True

    def unregister_window(self, window_hwnd: int) -> bool:
        """注销窗口（线程安全，防止崩溃）"""
        try:
            with self._pool_lock:
                if window_hwnd not in self.window_process_mapping:
                    return False

                process_id = self.window_process_mapping[window_hwnd]
                if process_id not in self.processes:
                    del self.window_process_mapping[window_hwnd]
                    self._window_last_request_time.pop(window_hwnd, None)
                    return False

                process_info = self.processes[process_id]

                # 移除窗口映射
                process_info.remove_window(window_hwnd)

                # 如果进程已无窗口，标记为待清理
                if process_info.is_empty():
                    process_info.is_active = False
                    process_info.last_used = 0

                # 从窗口映射中移除
                del self.window_process_mapping[window_hwnd]
                self._window_last_request_time.pop(window_hwnd, None)
                return True

        except Exception as e:
            logger.error(f"注销窗口异常: HWND={window_hwnd}, 错误: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def shutdown(self):
        """关闭进程池"""
        logger.info("正在关闭多进程OCR池...")
        self._is_shutdown = True
        self._running = False

        # 【修复OCR识别失败】获取进程快照,在锁外操作
        with self._pool_lock:
            processes_snapshot = list(self.processes.items())

        # 停止所有进程
        for process_id, process_info in processes_snapshot:
            try:
                # 跳过占位符
                if process_info.process is None:
                    continue

                # 发送停止信号
                # 【修复闪退】检查 request_queue 是否为 None
                if process_info.request_queue is not None:
                    try:
                        process_info.request_queue.put({'command': 'STOP'}, timeout=1)
                    except:
                        pass

                # 等待进程结束（subprocess.Popen 使用 wait() 而非 join()）
                try:
                    process_info.process.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    self._terminate_process_tree(process_info.process, wait_timeout=2.0)
                except Exception:
                    self._terminate_process_tree(process_info.process, wait_timeout=2.0)

                # 清理 socket 连接
                if process_info.socket_conn is not None:
                    try:
                        process_info.socket_conn.close()
                    except:
                        pass
                    process_info.socket_conn = None

                # 【修复闪退】清理队列资源（需要检查None）
                try:
                    if process_info.request_queue is not None:
                        process_info.request_queue.close()
                    if process_info.response_queue is not None:
                        process_info.response_queue.close()
                except:
                    pass
                self._release_shared_memory_slot(process_id)

            except Exception as e:
                logger.error(f"停止OCR进程失败: {process_id}, 错误: {e}")

        # 清理响应队列和pending响应
        with self._pool_lock:
            self._pending_responses.clear()
            self.processes.clear()
            self.window_process_mapping.clear()
            self._window_last_request_time.clear()
            self._resource_process_mapping.clear()
            self._resource_last_used.clear()
        self._release_all_shared_memory_slots()

        # 等待清理线程退出
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=2)

        if self._response_collector_thread and self._response_collector_thread.is_alive():
            self._response_collector_thread.join(timeout=2)

        logger.info("多进程OCR池已关闭")


# 全局单例
_global_multiprocess_ocr_pool: Optional[MultiProcessOCRPool] = None
_global_pool_lock = threading.Lock()


def get_multiprocess_ocr_pool() -> MultiProcessOCRPool:
    """获取全局多进程OCR池单例"""
    global _global_multiprocess_ocr_pool

    if _global_multiprocess_ocr_pool is not None:
        return _global_multiprocess_ocr_pool

    with _global_pool_lock:
        if _global_multiprocess_ocr_pool is None:
            import threading
            _init_complete = threading.Event()

            def _init_pool():
                global _global_multiprocess_ocr_pool
                try:
                    _global_multiprocess_ocr_pool = MultiProcessOCRPool(
                        max_processes=10,
                        max_windows_per_process=3
                    )
                except Exception as e:
                    logger.error(f"OCR池初始化失败: {e}")
                finally:
                    _init_complete.set()

            init_thread = threading.Thread(target=_init_pool, daemon=True, name="OCRPool-Init")
            init_thread.start()
            init_wait_timeout = _read_float_env('OCR_POOL_INIT_WAIT_SEC', 2.0, 0.1, 10.0)
            _init_complete.wait(timeout=init_wait_timeout)

            if _global_multiprocess_ocr_pool is None:
                # 后台初始化仍未完成，兜底同步初始化一次
                try:
                    _global_multiprocess_ocr_pool = MultiProcessOCRPool(
                        max_processes=10,
                        max_windows_per_process=3
                    )
                except Exception as e:
                    logger.error(f"OCR池同步初始化失败: {e}")

            if _global_multiprocess_ocr_pool is None:
                logger.warning("OCR池初始化失败，返回占位池")
                class _PlaceholderPool:
                    _is_shutdown = True

                    def recognize_text(self, *args, **kwargs):
                        return []

                    def check_and_ensure_process_for_window(self, *args, **kwargs):
                        return False

                    def preregister_window(self, *args, **kwargs):
                        return False

                    def unregister_window(self, hwnd):
                        return False

                    def cleanup_all_processes_force(self):
                        return None

                    def cleanup_idle_processes_now(self):
                        return None

                    def _cleanup_inactive_processes(self, force_immediate: bool = False):
                        return None

                    def hot_reset_all_idle_workers(self, force: bool = True):
                        return False

                    def get_hot_reset_remaining_idle_sec(self, idle_seconds: float = 3.0):
                        return 0.0

                    def get_stats(self):
                        return {
                            "total_processes": 0,
                            "active_processes": 0,
                            "total_requests": 0,
                            "average_processing_time": 0.0,
                            "effective_max_processes": 0,
                            "shared_memory_slots": 0,
                            "shared_memory_total_mb": 0.0,
                            "resource_routes": 0
                        }

                    def shutdown(self):
                        return None

                return _PlaceholderPool()

        return _global_multiprocess_ocr_pool


# 兼容性别名（供旧代码使用）
def get_multi_ocr_pool() -> MultiProcessOCRPool:
    """兼容性函数 - 重定向到 get_multiprocess_ocr_pool"""
    return get_multiprocess_ocr_pool()


def get_existing_multiprocess_ocr_pool() -> Optional[MultiProcessOCRPool]:
    """仅返回已存在的OCR池，不触发初始化。"""
    with _global_pool_lock:
        return _global_multiprocess_ocr_pool


def cleanup_orphan_ocr_subprocesses(main_pid: Optional[int] = None) -> int:
    """兜底清理同工程 OCR worker 孤儿进程。"""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return cleanup_worker_processes(
        worker_flags=("--ocr-worker", "--ocr-worker-standalone"),
        project_root=project_root,
        main_pid=main_pid,
    )




def cleanup_ocr_services_on_stop(deep_cleanup: bool = False):
    """清理OCR服务 - 停止任务时调用

    Args:
        deep_cleanup: 是否执行深度清理（强制清理所有OCR子进程）
    """
    try:
        pool = get_existing_multiprocess_ocr_pool()
        if pool is None:
            return
        if deep_cleanup:
            pool.cleanup_all_processes_force()
        else:
            pool._cleanup_inactive_processes()
    except Exception as e:
        logger.error(f"[OCR清理] 清理失败: {e}")
