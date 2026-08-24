from types import SimpleNamespace
from pathlib import Path
import threading
import time

import numpy as np
import pytest

import app_core.runtime.process_tree as process_tree_module
import services.multiprocess_ocr_pool as ocr_pool_module
import ui.runtime_parts.enhanced_multi_window_stop_manager as stop_manager_module
from services.multiprocess_ocr_pool import (
    MultiProcessOCRPool,
    OCRPoolError,
    OCRProcessInfo,
    OCRProcessTerminationError,
)


ROOT_DIR = Path(__file__).resolve().parents[1]


def _pool_with_busy_worker(monkeypatch):
    monkeypatch.setattr(MultiProcessOCRPool, "_start_cleanup_thread", lambda self: None)
    pool = MultiProcessOCRPool()
    pool.processes["worker"] = OCRProcessInfo(
        process_id="worker",
        process=None,
        is_active=True,
        is_busy=True,
    )
    return pool


def _waiter_count(pool, expected, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with pool._pool_lock:
            if len(pool._process_waiters.get("worker", ())) == expected:
                return
        time.sleep(0.005)
    raise AssertionError(f"expected {expected} queued OCR waiters")


def test_process_slot_waiters_are_served_fifo(monkeypatch):
    pool = _pool_with_busy_worker(monkeypatch)
    acquired = []
    threads = []

    def run(index):
        assert pool._acquire_process_slot("worker", 2.0)
        acquired.append(index)
        with pool._process_available:
            pool.processes["worker"].is_busy = False
            pool._process_available.notify_all()

    for index in range(5):
        thread = threading.Thread(target=run, args=(index,))
        thread.start()
        threads.append(thread)
        _waiter_count(pool, index + 1)

    with pool._process_available:
        pool.processes["worker"].is_busy = False
        pool._process_available.notify_all()

    for thread in threads:
        thread.join(timeout=2.0)
        assert not thread.is_alive()

    assert acquired == [0, 1, 2, 3, 4]
    assert not pool._process_waiters


def test_process_slot_waiter_wakes_on_shutdown(monkeypatch):
    pool = _pool_with_busy_worker(monkeypatch)
    result = []
    thread = threading.Thread(
        target=lambda: result.append(pool._acquire_process_slot("worker", 10.0))
    )
    thread.start()
    _waiter_count(pool, 1)

    with pool._process_available:
        pool._is_shutdown = True
        pool._running = False
        pool._process_available.notify_all()

    thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert result == [False]
    assert not pool._process_waiters


def test_process_slot_timeout_removes_waiter(monkeypatch):
    pool = _pool_with_busy_worker(monkeypatch)

    assert pool._acquire_process_slot("worker", 0.01) is False
    assert not pool._process_waiters


def test_invalid_environment_configuration_is_rejected(monkeypatch):
    monkeypatch.setattr(MultiProcessOCRPool, "_start_cleanup_thread", lambda self: None)
    monkeypatch.setenv("OCR_POOL_MAX_PROCESSES", "invalid")

    with pytest.raises(ValueError, match="OCR_POOL_MAX_PROCESSES must be an integer"):
        MultiProcessOCRPool()


def test_global_pool_initialization_error_is_propagated(monkeypatch):
    monkeypatch.setattr(ocr_pool_module, "_global_multiprocess_ocr_pool", None)

    def fail_initialization():
        raise RuntimeError("initialization failed")

    monkeypatch.setattr(ocr_pool_module, "MultiProcessOCRPool", fail_initialization)

    with pytest.raises(RuntimeError, match="initialization failed"):
        ocr_pool_module.get_multiprocess_ocr_pool()

    assert ocr_pool_module._global_multiprocess_ocr_pool is None


def test_worker_termination_does_not_fall_back_after_taskkill_failure(monkeypatch):
    monkeypatch.setattr(MultiProcessOCRPool, "_start_cleanup_thread", lambda self: None)
    pool = MultiProcessOCRPool()

    class Process:
        pid = 32123

        @staticmethod
        def poll():
            return None

    calls = []

    def failed_taskkill(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(process_tree_module.os, "name", "nt")
    monkeypatch.setattr(process_tree_module.subprocess, "run", failed_taskkill)

    with pytest.raises(OCRProcessTerminationError, match="taskkill exit code 1"):
        pool._terminate_process_tree(Process(), wait_timeout=1.0)

    assert len(calls) == 1


def test_large_image_shared_memory_failure_is_not_downgraded(monkeypatch):
    monkeypatch.setattr(MultiProcessOCRPool, "_start_cleanup_thread", lambda self: None)
    pool = MultiProcessOCRPool()

    class Process:
        @staticmethod
        def poll():
            return None

    process_info = OCRProcessInfo(
        process_id="worker",
        process=Process(),
        socket_conn=object(),
        is_active=True,
    )
    process_info.add_window(1, "window")
    pool.processes["worker"] = process_info
    pool.window_process_mapping[1] = "worker"

    import multiprocessing.shared_memory as shared_memory

    monkeypatch.setattr(
        shared_memory,
        "SharedMemory",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("shared memory unavailable")),
    )
    send_calls = []
    monkeypatch.setattr(
        ocr_pool_module,
        "_send_message",
        lambda *args, **kwargs: send_calls.append((args, kwargs)),
    )

    image = np.zeros((400, 400), dtype=np.uint8)
    with pytest.raises(OCRPoolError, match="failed to create OCR request shared memory"):
        pool.recognize_text("window", 1, image, resource_key="lane")

    assert send_calls == []


def test_late_worker_creation_is_terminated_after_placeholder_removal(monkeypatch):
    monkeypatch.setattr(MultiProcessOCRPool, "_start_cleanup_thread", lambda self: None)
    pool = MultiProcessOCRPool()
    pool.processes["pending"] = OCRProcessInfo(
        process_id="pending",
        process=None,
        is_active=False,
        is_creating=True,
    )

    started = threading.Event()
    release = threading.Event()
    terminated = threading.Event()

    class Process:
        pid = 45678

        @staticmethod
        def poll():
            return None

    late_process = Process()

    def create_worker(_process_id):
        started.set()
        assert release.wait(timeout=1.0)
        return OCRProcessInfo(
            process_id="pending",
            process=late_process,
            socket_conn=None,
        )

    monkeypatch.setattr(pool, "_create_ocr_process", create_worker)
    monkeypatch.setattr(
        pool,
        "_terminate_process_tree",
        lambda process, wait_timeout: terminated.set() if process is late_process else None,
    )

    pool._start_async_create_for_process("pending")
    assert started.wait(timeout=1.0)
    with pool._pool_lock:
        del pool.processes["pending"]
    release.set()

    assert terminated.wait(timeout=1.0)


def test_obsolete_ocr_stop_manager_is_removed():
    assert not (ROOT_DIR / "services" / "enhanced_ocr_pool_stop_manager.py").exists()

    for relative_path in (
        "ui/runtime_parts/enhanced_multi_window_stop_manager.py",
        "ui/runtime_parts/multi_window_stop_integration.py",
    ):
        source = (ROOT_DIR / relative_path).read_text(encoding="utf-8")
        assert "enhanced_ocr_pool_stop_manager" not in source
        assert "get_ocr_stop_manager" not in source


def test_unregister_ocr_windows_does_not_initialize_pool(monkeypatch):
    monkeypatch.setattr(
        stop_manager_module,
        "get_existing_multiprocess_ocr_pool",
        lambda: None,
    )

    assert stop_manager_module.unregister_ocr_windows([101, 202]) == 0


def test_unregister_ocr_windows_targets_each_unique_window_once(monkeypatch):
    class Pool:
        def __init__(self):
            self.calls = []

        def unregister_window(self, window_hwnd):
            self.calls.append(window_hwnd)
            return window_hwnd == 101

    pool = Pool()
    monkeypatch.setattr(
        stop_manager_module,
        "get_existing_multiprocess_ocr_pool",
        lambda: pool,
    )

    assert stop_manager_module.unregister_ocr_windows([101, 202, 101]) == 1
    assert pool.calls == [101, 202]


def test_unregister_ocr_windows_propagates_pool_errors(monkeypatch):
    class Pool:
        @staticmethod
        def unregister_window(_window_hwnd):
            raise RuntimeError("pool state is inconsistent")

    monkeypatch.setattr(
        stop_manager_module,
        "get_existing_multiprocess_ocr_pool",
        lambda: Pool(),
    )

    with pytest.raises(RuntimeError, match="pool state is inconsistent"):
        stop_manager_module.unregister_ocr_windows([101])
