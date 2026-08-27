#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多进程OCR池管理器 - 管理多个OCR工作进程
使用进程池替代线程池，每个进程独立运行OCR引擎，避免GIL限制

OCR worker 仅使用 subprocess + socket 通信。
main.py 在加载 PySide6 前分派 OCR worker 入口。
"""

import logging
import socket
import subprocess
import sys
import threading
import time
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import os
from collections import deque

from app_core.runtime.process_tree import ProcessTerminationError, terminate_process_tree
from services.worker_process_cleanup import (
    cleanup_worker_processes,
    register_worker_process,
    unregister_worker_process,
)
from services.ocr_socket_message_utils import (
    recv_message as recv_ocr_socket_message,
    send_message as send_ocr_socket_message,
)
from utils.app_paths import get_app_root
from app_core.runtime.worker_entry import build_worker_launch_command, build_worker_process_env

logger = logging.getLogger(__name__)


class OCRPoolError(RuntimeError):
    """Base error for OCR pool lifecycle and protocol failures."""


class OCRProcessCreationError(OCRPoolError):
    """Raised when an OCR worker cannot be created or initialized."""


class OCRProcessTerminationError(OCRPoolError):
    """Raised when the configured termination strategy cannot stop a worker."""

    def __init__(self, pid: int, reason: str):
        self.pid = int(pid)
        super().__init__(f"failed to terminate OCR worker pid={self.pid}: {reason}")


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
    return process.poll() is None


def _read_int_env(name: str, default: int, min_value: int, max_value: Optional[int] = None) -> int:
    """Read a bounded integer setting and reject invalid configuration."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer, got {raw_value!r}") from exc
    if value < min_value:
        raise ValueError(f"{name} must be >= {min_value}, got {value}")
    if max_value is not None and value > max_value:
        raise ValueError(f"{name} must be <= {max_value}, got {value}")
    return value


def _read_float_env(name: str, default: float, min_value: float, max_value: Optional[float] = None) -> float:
    """Read a bounded float setting and reject invalid configuration."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number, got {raw_value!r}") from exc
    if value < min_value:
        raise ValueError(f"{name} must be >= {min_value}, got {value}")
    if max_value is not None and value > max_value:
        raise ValueError(f"{name} must be <= {max_value}, got {value}")
    return value


def _read_bool_env(name: str, default: bool = False) -> bool:
    """Read a boolean setting and reject invalid configuration."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    value = raw_value.strip().lower()
    if value in ('1', 'true', 'yes', 'on'):
        return True
    if value in ('0', 'false', 'no', 'off'):
        return False
    raise ValueError(f"{name} must be one of 1/0, true/false, yes/no, on/off")


@dataclass
class OCRProcessInfo:
    """OCR进程信息"""
    process_id: str
    process: Optional[subprocess.Popen]
    socket_conn: Optional[socket.socket] = None
    socket_port: int = 0
    is_active: bool = True
    last_used: float = 0.0
    total_requests: int = 0
    total_processing_time: float = 0.0
    assigned_windows: Dict[int, str] = field(default_factory=dict)  # hwnd -> window_title
    max_windows: int = 3  # 每个进程最多支持3个窗口
    is_creating: bool = False  # 【修复竞态条件】标记占位符正在创建真实进程
    creation_error: Optional[str] = None
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


class MultiProcessOCRPool:
    """多进程OCR池管理器"""

    def __init__(self, max_processes: int = 1, max_windows_per_process: int = 20):
        """
        初始化多进程OCR池

        Args:
            max_processes: 最大进程数量（建议不超过CPU核心数）
            max_windows_per_process: 每个进程最多支持的窗口数
        """
        # 限制最大进程数不超过CPU核心数
        cpu_count = os.cpu_count() or 1
        configured_max_processes = _read_int_env('OCR_POOL_MAX_PROCESSES', max_processes, 1, 2)
        configured_max_windows = _read_int_env('OCR_POOL_MAX_WINDOWS_PER_PROCESS', max_windows_per_process, 1, 20)
        self.max_processes = min(configured_max_processes, cpu_count, 2)
        self.max_windows_per_process = configured_max_windows
        self._adaptive_scale_enabled = _read_bool_env('OCR_POOL_ADAPTIVE_SCALE', True)
        self._adaptive_min_processes = _read_int_env('OCR_POOL_MIN_PROCESSES', 1, 1, self.max_processes)
        # 并发请求扩容粒度：每 N 个并发请求对应 1 个OCR子进程
        self._threads_per_process = _read_int_env('OCR_POOL_THREADS_PER_PROCESS', 3, 1, 64)
        self._effective_max_processes = self.max_processes

        # 进程管理
        self.processes: Dict[str, OCRProcessInfo] = {}
        self.window_process_mapping: Dict[int, str] = {}  # hwnd -> process_id
        self._resource_process_mapping: Dict[str, str] = {}  # resource_key -> process_id
        self._resource_last_used: Dict[str, float] = {}  # resource_key -> timestamp
        self._route_by_thread_start = _read_bool_env('LCA_ROUTE_POOL_BY_THREAD_START', True)
        self._resource_mapping_ttl_sec = _read_float_env(
            'OCR_POOL_RESOURCE_MAPPING_TTL_SEC', 90.0, 5.0, 3600.0
        )

        # 线程安全
        self._pool_lock = threading.RLock()
        self._process_available = threading.Condition(self._pool_lock)
        self._process_waiters: Dict[str, deque] = {}
        self._request_counter = 0
        self._counter_lock = threading.Lock()

        # 性能监控
        self._performance_stats = {
            "total_processes": 0,
            "active_processes": 0,
            "total_requests": 0,
            "average_processing_time": 0.0,
            "effective_max_processes": self._effective_max_processes,
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
        self._running = True
        self._is_shutdown = False  # 【修复闪退】标记是否正在关闭
        self._cleanup_in_progress = False
        self._cleanup_error: Optional[OCRPoolError] = None

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
        self._start_cleanup_thread()

    def _start_cleanup_thread(self):
        """启动清理线程"""
        def cleanup_worker():
            while self._running:
                try:
                    time.sleep(self._cleanup_interval)
                    if self._running:
                        with self._pool_lock:
                            self._prune_window_request_times_unlocked()
                            self._prune_resource_mappings_locked()
                        self._cleanup_inactive_processes()
                        self._update_performance_stats()

                except Exception as exc:
                    error = OCRPoolError(f"OCR cleanup thread failed: {exc}")
                    with self._process_available:
                        self._cleanup_error = error
                        self._running = False
                        self._process_available.notify_all()
                    logger.exception("OCR cleanup thread stopped after a fatal error")
                    return

        self._cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True, name="OCRPool-Cleaner")
        self._cleanup_thread.start()

    def _generate_process_id(self) -> str:
        """生成进程ID"""
        return f"ocr_process_{time.time_ns()}"

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
        if not isinstance(resource_key, str):
            raise TypeError("resource_key must be a string or None")
        normalized = resource_key.strip()
        return normalized or None

    def _resolve_resource_key(self, window_hwnd: Optional[int], resource_key: Optional[str] = None) -> Optional[str]:
        explicit_key = self._normalize_resource_key(resource_key)
        if explicit_key:
            return explicit_key
        if not self._route_by_thread_start:
            return None
        from task_workflow.workflow_context import get_current_resource_lane_key
        return self._normalize_resource_key(
            get_current_resource_lane_key(window_hwnd=window_hwnd)
        )

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

    def _start_async_create_for_process(self, process_id: str) -> None:
        """异步创建占位进程对应的真实OCR子进程。"""
        def _async_create():
            creation_error = None
            try:
                new_process_info = self._create_ocr_process(process_id)
            except Exception as exc:
                new_process_info = None
                creation_error = str(exc)
            with self._pool_lock:
                if new_process_info and process_id in self.processes:
                    placeholder = self.processes[process_id]
                    for hwnd, title in placeholder.assigned_windows.items():
                        new_process_info.add_window(hwnd, title)
                    new_process_info.is_creating = False
                    self.processes[process_id] = new_process_info
                elif new_process_info is not None:
                    self._terminate_process_tree(new_process_info.process, wait_timeout=3.0)
                    if new_process_info.socket_conn is not None:
                        new_process_info.socket_conn.close()
                else:
                    if process_id in self.processes and self.processes[process_id].is_creating:
                        placeholder = self.processes[process_id]
                        placeholder.is_creating = False
                        placeholder.creation_error = creation_error or "worker creation returned no process"
                        logger.error(
                            "OCR worker creation failed: %s: %s",
                            process_id,
                            placeholder.creation_error,
                        )

        thread = threading.Thread(target=_async_create, daemon=True, name=f"OCRCreate-{process_id}")
        thread.start()

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

    def _create_ocr_process(self, process_id: str) -> OCRProcessInfo:
        """Create and initialize one socket-based OCR worker."""
        process: Optional[subprocess.Popen] = None
        client_socket: Optional[socket.socket] = None
        try:
            if threading.current_thread() is threading.main_thread():
                raise OCRProcessCreationError(
                    f"OCR worker creation is not allowed on the main thread: {process_id}"
                )

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
                server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server_socket.bind(("127.0.0.1", 0))
                server_socket.listen(1)
                port = server_socket.getsockname()[1]
                project_root = get_app_root()
                cmd = build_worker_launch_command(
                    worker_flag="--ocr-worker",
                    module_name="services.multiprocess_ocr_worker",
                    standalone_flag="--ocr-worker-standalone",
                    extra_args=["--process-id", process_id, "--port", str(port)],
                    project_root=project_root,
                )
                child_env = build_worker_process_env(project_root=project_root)
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                with self._pool_lock:
                    if self._cleanup_in_progress or self._is_shutdown or not self._running:
                        raise OCRProcessCreationError(
                            f"OCR worker creation cancelled: {process_id}"
                        )
                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        cwd=project_root,
                        env=child_env,
                        creationflags=creation_flags,
                    )
                    register_worker_process(process, "--ocr-worker")
                server_socket.settimeout(self._worker_connect_timeout)
                client_socket, _addr = server_socket.accept()

            ready_msg = _recv_message(client_socket, timeout=self._worker_ready_timeout)
            if not ready_msg or ready_msg.get('type') != 'ready':
                raise OCRProcessCreationError(
                    f"OCR worker did not send a ready message: {ready_msg!r}"
                )

            return OCRProcessInfo(
                process_id=process_id,
                process=process,
                socket_conn=client_socket,
                socket_port=port,
                is_active=True,
                last_used=time.time(),
                max_windows=self.max_windows_per_process,
            )

        except Exception as exc:
            close_error = None
            if client_socket is not None:
                try:
                    client_socket.close()
                except OSError as socket_exc:
                    close_error = socket_exc
            if process is not None:
                self._terminate_process_tree(process, wait_timeout=3.0)
            if close_error is not None:
                raise OCRProcessCreationError(
                    f"OCR worker creation failed and socket cleanup failed: {close_error}"
                ) from exc
            if isinstance(exc, OCRPoolError):
                raise
            raise OCRProcessCreationError(
                f"failed to create OCR worker {process_id}: {exc}"
            ) from exc

    def _find_best_process_for_window(
        self,
        window_hwnd: int,
        window_title: str,
        resource_key: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve one worker in a single scheduling pass."""
        normalized_resource_key = self._normalize_resource_key(resource_key)
        new_process_id = None

        with self._pool_lock:
            if self._cleanup_error is not None:
                raise self._cleanup_error
            if self._cleanup_in_progress:
                raise OCRPoolError("OCR worker cleanup is in progress")
            if self._is_shutdown or not self._running:
                raise OCRPoolError("OCR pool is not running")
            now_ts = time.time()
            self._prune_resource_mappings_locked(now=now_ts)

            mapped_process_id = self.window_process_mapping.get(window_hwnd)
            if mapped_process_id is not None:
                process_info = self.processes.get(mapped_process_id)
                if process_info is None:
                    del self.window_process_mapping[window_hwnd]
                    raise OCRPoolError(f"window mapped to missing OCR worker: {mapped_process_id}")
                is_dead = process_info.process is not None and not _is_process_alive(process_info.process)
                is_invalid_placeholder = process_info.process is None and not process_info.is_creating
                if process_info.is_retiring or is_dead or is_invalid_placeholder:
                    process_info.remove_window(window_hwnd)
                    del self.window_process_mapping[window_hwnd]
                    if is_dead or is_invalid_placeholder:
                        self.processes.pop(mapped_process_id, None)
                        self._purge_resource_mappings_for_process_locked(mapped_process_id)
                    raise OCRPoolError(f"mapped OCR worker is unavailable: {mapped_process_id}")
                if process_info.process is not None and not process_info.is_active:
                    process_info.is_active = True
                    process_info.last_used = now_ts
                if normalized_resource_key:
                    self._touch_resource_mapping_locked(normalized_resource_key, mapped_process_id, now=now_ts)
                return mapped_process_id

            if normalized_resource_key:
                routed_process_id = self._resource_process_mapping.get(normalized_resource_key)
                if routed_process_id:
                    routed_info = self.processes.get(routed_process_id)
                    routed_dead = (
                        routed_info is not None
                        and routed_info.process is not None
                        and not _is_process_alive(routed_info.process)
                    )
                    routed_invalid = (
                        routed_info is None
                        or routed_info.is_retiring
                        or routed_dead
                        or (routed_info.process is None and not routed_info.is_creating)
                    )
                    if routed_invalid:
                        self._purge_resource_mappings_for_process_locked(routed_process_id)
                        raise OCRPoolError(f"routed OCR worker is unavailable: {routed_process_id}")
                    if routed_info.process is not None and not routed_info.is_active:
                        routed_info.is_active = True
                        routed_info.last_used = now_ts
                    if routed_info.add_window(window_hwnd, window_title):
                        self.window_process_mapping[window_hwnd] = routed_process_id
                        self._touch_resource_mapping_locked(normalized_resource_key, routed_process_id, now=now_ts)
                        return routed_process_id

            dead_process_ids = [
                process_id
                for process_id, process_info in self.processes.items()
                if process_info.process is not None
                and not _is_process_alive(process_info.process)
            ]
            if dead_process_ids:
                raise OCRPoolError(
                    "dead OCR workers require explicit cleanup: "
                    + ", ".join(sorted(dead_process_ids))
                )

            candidates = []
            for process_id, process_info in self.processes.items():
                if process_info.process is not None and not _is_process_alive(process_info.process):
                    continue
                if process_info.can_accept_window():
                    candidates.append((process_info.get_window_count(), process_id, process_info))

            if candidates:
                _, best_process_id, process_info = min(candidates, key=lambda item: (item[0], item[1]))
                if process_info.process is not None and not process_info.is_active:
                    process_info.is_active = True
                    process_info.last_used = now_ts
                process_info.add_window(window_hwnd, window_title)
                self.window_process_mapping[window_hwnd] = best_process_id
                if normalized_resource_key:
                    self._touch_resource_mapping_locked(normalized_resource_key, best_process_id, now=now_ts)
                return best_process_id

            effective_limit = self._get_effective_max_processes_locked()
            pending_windows_target = (
                (len(self.window_process_mapping) + self.max_windows_per_process)
                // self.max_windows_per_process
            )
            effective_limit = min(self.max_processes, max(effective_limit, pending_windows_target))
            active_process_count = sum(
                1
                for info in self.processes.values()
                if not info.is_retiring
                and (info.process is None or _is_process_alive(info.process))
            )
            if active_process_count < effective_limit:
                new_process_id = self._generate_process_id()
                placeholder_info = OCRProcessInfo(
                    process_id=new_process_id,
                    process=None,
                    is_active=False,
                    last_used=now_ts,
                    max_windows=self.max_windows_per_process,
                    is_creating=True,
                )
                placeholder_info.add_window(window_hwnd, window_title)
                self.processes[new_process_id] = placeholder_info
                self.window_process_mapping[window_hwnd] = new_process_id
                if normalized_resource_key:
                    self._touch_resource_mapping_locked(normalized_resource_key, new_process_id, now=now_ts)

        if new_process_id:
            self._start_async_create_for_process(new_process_id)
            return new_process_id
        return None

    def _remove_process_waiter_locked(self, process_id: str, ticket: object) -> None:
        waiters = self._process_waiters.get(process_id)
        if waiters is None:
            return
        try:
            waiters.remove(ticket)
        except ValueError:
            return
        if not waiters:
            self._process_waiters.pop(process_id, None)

    def _acquire_process_slot(self, process_id: str, timeout: float) -> bool:
        """Acquire one worker fairly without polling."""
        ticket = object()
        deadline = time.monotonic() + max(0.0, float(timeout))

        with self._process_available:
            waiters = self._process_waiters.setdefault(process_id, deque())
            waiters.append(ticket)

            while True:
                if self._is_shutdown or not self._running or self._cleanup_in_progress:
                    self._remove_process_waiter_locked(process_id, ticket)
                    self._process_available.notify_all()
                    return False

                process_info = self.processes.get(process_id)
                if process_info is None or not process_info.is_active:
                    self._remove_process_waiter_locked(process_id, ticket)
                    self._process_available.notify_all()
                    return False

                waiters = self._process_waiters.get(process_id)
                is_first = bool(waiters) and waiters[0] is ticket
                if is_first and not process_info.is_busy:
                    waiters.popleft()
                    if not waiters:
                        self._process_waiters.pop(process_id, None)
                    process_info.is_busy = True
                    self._mark_ocr_activity_locked()
                    return True

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._remove_process_waiter_locked(process_id, ticket)
                    self._process_available.notify_all()
                    return False
                self._process_available.wait(timeout=remaining)

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
        image_shm = None  # 【修复OCR识别失败】跟踪共享内存对象，确保所有路径清理
        process_id = None  # 【内存泄漏修复】确保 finally 中可以正确清理 is_busy
        is_busy_set = False  # 【内存泄漏修复】跟踪是否设置了 is_busy，用于 finally 清理
        request_tracked = False  # 全局在途请求计数是否已登记
        force_recycle_process = False  # 请求链路异常后，强制退役当前进程
        request_sent_to_worker = False  # 请求是否已发给worker（用于判定是否需要强制退役）

        try:
            with self._pool_lock:
                if self._cleanup_error is not None:
                    raise self._cleanup_error
                if self._is_shutdown or (not self._running):
                    raise OCRPoolError("OCR pool is shut down")
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
                raise OCRPoolError(f"no OCR worker is available for window {window_title!r}")

            # 获取进程信息（带等待机制，作为第二道保险）
            max_wait_for_process = max(self._process_ready_timeout, float(timeout))
            wait_start = time.time()

            while True:
                with self._pool_lock:
                    if process_id not in self.processes:
                        raise OCRPoolError(f"OCR worker disappeared before use: {process_id}")

                    process_info = self.processes[process_id]

                    # 【修复OCR识别失败】检查占位符是否创建失败（is_creating=False且process仍为None说明创建失败）
                    if process_info.process is None and not process_info.is_creating:
                        detail = process_info.creation_error or "unknown creation error"
                        raise OCRProcessCreationError(
                            f"OCR worker creation failed: {process_id}: {detail}"
                        )

                    # 检查进程是否就绪
                    if process_info.process is not None and process_info.is_active and _is_process_alive(process_info.process):
                        # 进程已就绪，退出等待循环
                        break
                    elif process_info.process is not None and not _is_process_alive(process_info.process):
                        stale_process_id = process_id
                        if stale_process_id in self.processes:
                            del self.processes[stale_process_id]
                            self._purge_resource_mappings_for_process_locked(stale_process_id)
                        if self.window_process_mapping.get(window_hwnd) == stale_process_id:
                            del self.window_process_mapping[window_hwnd]
                        raise OCRPoolError(f"OCR worker exited before request: {stale_process_id}")

                # 检查超时
                elapsed = time.time() - wait_start
                if elapsed >= max_wait_for_process:
                    with self._pool_lock:
                        # 【修复闪退】正确检查进程是否在字典中
                        proc_state = "占位符" if process_id in self.processes and self.processes[process_id].process is None else "未知"
                    raise OCRProcessCreationError(
                        f"timed out waiting for OCR worker {process_id} "
                        f"after {elapsed:.1f}s (state={proc_state})"
                    )

                # 继续等待
                time.sleep(0.1)

            # 每个 OCR worker 使用独立 FIFO，避免多窗口轮询竞争和请求饥饿。
            if not self._acquire_process_slot(process_id, self._busy_wait_timeout):
                raise OCRPoolError(f"timed out waiting for OCR worker slot: {process_id}")
            is_busy_set = True
            with self._pool_lock:
                process_info = self.processes.get(process_id)
                if process_info is None:
                    raise OCRPoolError(f"OCR worker disappeared before dispatch: {process_id}")

            # 生成请求ID
            request_id = self._generate_request_id()

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

                except Exception as exc:
                    raise OCRPoolError("failed to create OCR request shared memory") from exc

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
            if process_info.socket_conn is None:
                raise OCRPoolError(f"OCR worker has no socket connection: {process_id}")

            try:
                if not _send_message(process_info.socket_conn, request):
                    force_recycle_process = True
                    raise OCRPoolError(f"failed to send OCR request: {process_id}")
                request_sent_to_worker = True
            except OCRPoolError:
                raise
            except Exception as exc:
                with self._pool_lock:
                    process_info.is_active = False
                force_recycle_process = True
                raise OCRPoolError(f"failed to send OCR request: {process_id}") from exc

            if not use_shared_memory and 'image_bytes' in locals():
                del image_bytes
            del request

            try:
                response = _recv_message(process_info.socket_conn, timeout=timeout)
                if response is None:
                    force_recycle_process = request_sent_to_worker
                    raise OCRPoolError(f"timed out waiting for OCR response: {process_id}")
            except OCRPoolError:
                raise
            except Exception as exc:
                force_recycle_process = request_sent_to_worker
                raise OCRPoolError(f"failed to receive OCR response: {process_id}") from exc

            # 验证响应窗口句柄
            response_hwnd = response.get('window_hwnd', 0)
            if response_hwnd != window_hwnd:
                force_recycle_process = True
                raise OCRPoolError(
                    f"OCR response window mismatch: requested={window_hwnd}, received={response_hwnd}"
                )

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
                error = response.get('error') or "worker rejected OCR request"
                del response
                raise OCRPoolError(f"OCR worker request failed: {error}")

        except OCRPoolError:
            raise
        except Exception as exc:
            raise OCRPoolError(f"OCR recognition failed: {exc}") from exc
        finally:
            # 清理共享内存
            if image_shm is not None:
                active_error = sys.exc_info()[1]
                cleanup_errors = []
                try:
                    image_shm.close()
                except OSError as exc:
                    cleanup_errors.append(f"close: {exc}")
                try:
                    image_shm.unlink()
                except OSError as exc:
                    cleanup_errors.append(f"unlink: {exc}")
                if cleanup_errors:
                    cleanup_message = "OCR shared memory cleanup failed: " + "; ".join(cleanup_errors)
                    if active_error is not None and hasattr(active_error, "add_note"):
                        active_error.add_note(cleanup_message)
                    else:
                        raise OCRPoolError(cleanup_message)

            # 清除is_busy标志
            need_force_cleanup = False
            with self._process_available:
                if is_busy_set and process_id and process_id in self.processes:
                    self.processes[process_id].is_busy = False
                    self._mark_ocr_activity_locked()
                self._process_available.notify_all()

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
    ) -> List[Tuple[str, socket.socket]]:
        reset_targets: List[Tuple[str, socket.socket]] = []
        with self._pool_lock:
            if self._is_shutdown or not self._running or not self.processes:
                return reset_targets
            if self._active_ocr_requests > 0:
                return reset_targets

            if any(process_info.is_busy for process_info in self.processes.values()):
                return reset_targets

            for process_id in sorted(self.processes):
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
        return reset_targets

    def _execute_hot_reset(self, reset_targets: List[Tuple[str, socket.socket]], force: bool = False) -> bool:
        if not reset_targets:
            return False

        has_success_reset = False
        failures = []

        for process_id, sock in reset_targets:
            communication_ok = True
            reset_applied = False
            try:
                if not _send_message(sock, {'command': 'RESET_ENGINE', 'force': bool(force)}):
                    raise OCRPoolError(f"failed to send reset command to {process_id}")
                response = _recv_message(sock, timeout=2.0)
                if not isinstance(response, dict) or response.get('type') != 'reset_engine':
                    raise OCRPoolError(
                        f"invalid reset response from {process_id}: {response!r}"
                    )
                reset_applied = bool(response.get('success', False))
            except Exception as exc:
                communication_ok = False
                failures.append(f"{process_id}: {exc}")
            finally:
                with self._process_available:
                    process_info = self.processes.get(process_id)
                    if process_info is None:
                        continue
                    process_info.is_busy = False
                    self._process_available.notify_all()
                    if communication_ok:
                        if reset_applied:
                            has_success_reset = True
                        process_info.last_used = time.time()
                    else:
                        process_info.is_active = False

        if failures:
            raise OCRPoolError("OCR worker reset failed: " + "; ".join(failures))
        return has_success_reset

    def _hot_reset_workers_when_all_idle(self, force: bool = False) -> bool:
        reset_targets = self._acquire_idle_workers_for_hot_reset()
        return self._execute_hot_reset(reset_targets, force=force)

    def hot_reset_all_idle_workers(self, force: bool = True) -> bool:
        """公开接口：当OCR子进程全部空闲时，立即热重置引擎。"""
        return bool(self._hot_reset_workers_when_all_idle(force=force))

    def _terminate_process_tree(self, process: Optional[subprocess.Popen], wait_timeout: float = 1.0) -> None:
        """Terminate one worker with the single strategy for this platform."""
        if process is None:
            return

        try:
            pid = int(process.pid)
        except (TypeError, ValueError, AttributeError) as exc:
            raise OCRProcessTerminationError(0, "invalid process handle") from exc

        try:
            terminate_process_tree(
                process,
                wait_timeout=float(wait_timeout),
                force=True,
            )
        except ProcessTerminationError as exc:
            raise OCRProcessTerminationError(pid, str(exc)) from exc
        unregister_worker_process(pid)

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

            if process_info.process is not None:
                self._terminate_process_tree(process_info.process, wait_timeout=1.0)

            if process_info.socket_conn is not None:
                process_info.socket_conn.close()
                process_info.socket_conn = None

            with self._pool_lock:
                self.processes.pop(process_id, None)
                self._purge_resource_mappings_for_process_locked(process_id)
                for hwnd, mapped_process_id in list(self.window_process_mapping.items()):
                    if mapped_process_id == process_id:
                        del self.window_process_mapping[hwnd]

    def cleanup_all_processes(self):
        """强制清理所有OCR进程（停止任务时使用，不管是否有窗口分配）"""
        with self._process_available:
            if self._cleanup_in_progress:
                raise OCRPoolError("OCR worker cleanup is already in progress")
            self._cleanup_in_progress = True
            process_snapshot = list(self.processes.items())
            self._process_available.notify_all()

        try:
            for _process_id, process_info in process_snapshot:
                if process_info.process is not None:
                    self._terminate_process_tree(process_info.process, wait_timeout=3.0)
                if process_info.socket_conn is not None:
                    process_info.socket_conn.close()
                    process_info.socket_conn = None

            # Includes workers that were launched by an in-flight creation thread
            # before cleanup acquired the lifecycle lock.
            cleanup_registered_ocr_subprocesses()

            with self._process_available:
                self.processes.clear()
                self.window_process_mapping.clear()
                self._window_last_request_time.clear()
                self._resource_process_mapping.clear()
                self._resource_last_used.clear()
                self._process_waiters.clear()
                self._process_available.notify_all()
        finally:
            with self._process_available:
                self._cleanup_in_progress = False
                self._process_available.notify_all()

    def _update_performance_stats(self):
        """更新性能统计"""
        with self._pool_lock:
            self._prune_resource_mappings_locked()

            active_count = sum(1 for p in self.processes.values() if p.is_active)
            total_requests = sum(p.total_requests for p in self.processes.values())
            total_time = sum(p.total_processing_time for p in self.processes.values())
            effective_max = self._get_effective_max_processes_locked()
            self._performance_stats.update({
                "total_processes": len(self.processes),
                "active_processes": active_count,
                "total_requests": total_requests,
                "average_processing_time": total_time / total_requests if total_requests > 0 else 0.0,
                "effective_max_processes": effective_max,
                "resource_routes": len(self._resource_process_mapping)
            })

    def get_stats(self) -> Dict:
        """获取性能统计"""
        self._update_performance_stats()
        with self._pool_lock:
            return self._performance_stats.copy()

    @property
    def is_running(self) -> bool:
        with self._pool_lock:
            return bool(
                self._running
                and not self._is_shutdown
                and not self._cleanup_in_progress
                and self._cleanup_error is None
            )

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
                        del self.window_process_mapping[window_hwnd]
                        self._window_last_request_time.pop(window_hwnd, None)
                        del self.processes[process_id]
                        self._purge_resource_mappings_for_process_locked(process_id)
                        detail = process_info.creation_error or "worker is not running"
                        raise OCRPoolError(f"OCR worker is unavailable: {process_id}: {detail}")
                else:
                    del self.window_process_mapping[window_hwnd]
                    self._window_last_request_time.pop(window_hwnd, None)
                    raise OCRPoolError(f"window mapped to missing OCR worker: {process_id}")

        # 窗口没有分配进程或原进程已失效
        process_id = self._find_best_process_for_window(
            window_hwnd,
            window_title,
            resource_key=resolved_resource_key
        )

        if not process_id:
            raise OCRPoolError(f"OCR worker capacity exhausted for window {window_hwnd}")
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
        resolved_resource_key = self._resolve_resource_key(window_hwnd=window_hwnd, resource_key=resource_key)
        process_id = self._find_best_process_for_window(
            window_hwnd,
            window_title,
            resource_key=resolved_resource_key
        )
        if not process_id:
            raise OCRPoolError(f"OCR worker capacity exhausted for window {window_hwnd}")

        # 等待进程真正就绪（不再是占位符状态）
        if wait_ready:
            max_wait = self._process_ready_timeout
            wait_start = time.time()
            while True:
                with self._pool_lock:
                    if process_id not in self.processes:
                        raise OCRProcessCreationError(
                            f"OCR worker disappeared during preregistration: {process_id}"
                        )

                    process_info = self.processes[process_id]
                    if process_info.process is not None and process_info.is_active:
                        return True
                    if not process_info.is_creating:
                        detail = process_info.creation_error or "unknown creation error"
                        raise OCRProcessCreationError(
                            f"OCR worker creation failed: {process_id}: {detail}"
                        )

                # 检查超时
                elapsed = time.time() - wait_start
                if elapsed >= max_wait:
                    raise OCRProcessCreationError(
                        f"timed out waiting for OCR worker {process_id} after {elapsed:.1f}s"
                    )

                # 继续等待
                time.sleep(0.1)
        else:
            return True

    def unregister_window(self, window_hwnd: int) -> bool:
        """Unregister a window and expose inconsistent pool state."""
        with self._pool_lock:
            if window_hwnd not in self.window_process_mapping:
                return False

            process_id = self.window_process_mapping[window_hwnd]
            process_info = self.processes.get(process_id)
            if process_info is None:
                del self.window_process_mapping[window_hwnd]
                self._window_last_request_time.pop(window_hwnd, None)
                raise OCRPoolError(f"window mapped to missing OCR worker: {process_id}")

            process_info.remove_window(window_hwnd)
            if process_info.is_empty():
                process_info.is_active = False
                process_info.last_used = 0

            del self.window_process_mapping[window_hwnd]
            self._window_last_request_time.pop(window_hwnd, None)
            return True

    def shutdown(self):
        """关闭进程池"""
        logger.info("正在关闭多进程OCR池...")
        with self._process_available:
            self._is_shutdown = True
            self._running = False
            self._process_available.notify_all()

        self.cleanup_all_processes()

        with self._pool_lock:
            self._process_waiters.clear()
            self.processes.clear()
            self.window_process_mapping.clear()
            self._window_last_request_time.clear()
            self._resource_process_mapping.clear()
            self._resource_last_used.clear()

        # 等待清理线程退出
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=2)

        logger.info("多进程OCR池已关闭")


# 全局单例
_global_multiprocess_ocr_pool: Optional[MultiProcessOCRPool] = None
_global_pool_lock = threading.Lock()


def get_multiprocess_ocr_pool() -> MultiProcessOCRPool:
    """Return the global OCR pool, propagating initialization failures."""
    global _global_multiprocess_ocr_pool

    if _global_multiprocess_ocr_pool is not None:
        return _global_multiprocess_ocr_pool

    with _global_pool_lock:
        if _global_multiprocess_ocr_pool is None:
            _global_multiprocess_ocr_pool = MultiProcessOCRPool()

        return _global_multiprocess_ocr_pool


def get_existing_multiprocess_ocr_pool() -> Optional[MultiProcessOCRPool]:
    """仅返回已存在的OCR池，不触发初始化。"""
    with _global_pool_lock:
        return _global_multiprocess_ocr_pool


def cleanup_registered_ocr_subprocesses() -> int:
    """清理当前主进程明确登记的 OCR worker。"""
    return cleanup_worker_processes(
        worker_flags=("--ocr-worker",),
    )


def cleanup_ocr_services_on_stop() -> None:
    """Force-clean the existing OCR pool, propagating cleanup failures."""
    pool = get_existing_multiprocess_ocr_pool()
    if pool is not None:
        pool.cleanup_all_processes()
