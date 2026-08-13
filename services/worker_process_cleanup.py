# -*- coding: utf-8 -*-
"""Strict lifecycle registry for subprocess workers owned by this process."""

from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import dataclass
from typing import Iterable, Tuple


class WorkerProcessCleanupError(RuntimeError):
    def __init__(self, failed_pids: Iterable[int]):
        self.failed_pids = tuple(sorted({int(pid) for pid in failed_pids}))
        super().__init__(
            "failed to terminate registered worker processes: "
            + ", ".join(str(pid) for pid in self.failed_pids)
        )


@dataclass(frozen=True)
class _RegisteredWorker:
    pid: int
    flag: str
    process: subprocess.Popen


_REGISTRY_LOCK = threading.RLock()
_REGISTERED_WORKERS: dict[int, _RegisteredWorker] = {}


def _normalize_flags(worker_flags: Iterable[str]) -> Tuple[str, ...]:
    if isinstance(worker_flags, (str, bytes)):
        raise TypeError("worker_flags must be an iterable of flag strings")

    flags = []
    for raw_flag in worker_flags:
        if not isinstance(raw_flag, str):
            raise TypeError("worker flag must be a string")
        flag = raw_flag.strip().lower()
        if not flag.startswith("--") or any(character.isspace() for character in flag):
            raise ValueError(f"invalid worker flag: {raw_flag!r}")
        if flag in flags:
            raise ValueError(f"duplicate worker flag: {flag}")
        flags.append(flag)
    if not flags:
        raise ValueError("at least one worker flag is required")
    return tuple(flags)


def _process_pid(process: subprocess.Popen) -> int:
    if process is None:
        raise TypeError("process cannot be None")
    pid = getattr(process, "pid", None)
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError(f"worker process has an invalid pid: {pid!r}")
    if pid == os.getpid():
        raise ValueError("cannot register the current process as a worker")
    if not callable(getattr(process, "poll", None)):
        raise TypeError("process must provide poll()")
    return pid


def register_worker_process(process: subprocess.Popen, worker_flag: str) -> int:
    pid = _process_pid(process)
    (flag,) = _normalize_flags((worker_flag,))
    if process.poll() is not None:
        raise RuntimeError(f"cannot register an exited worker process: pid={pid}")

    with _REGISTRY_LOCK:
        if pid in _REGISTERED_WORKERS:
            raise RuntimeError(f"worker process is already registered: pid={pid}")
        _REGISTERED_WORKERS[pid] = _RegisteredWorker(
            pid=pid,
            flag=flag,
            process=process,
        )
    return pid


def unregister_worker_process(process_or_pid) -> bool:
    if isinstance(process_or_pid, bool):
        raise TypeError("worker pid must be an integer")
    if isinstance(process_or_pid, int):
        pid = process_or_pid
    else:
        pid = _process_pid(process_or_pid)
    if pid <= 0:
        raise ValueError("worker pid must be greater than zero")

    with _REGISTRY_LOCK:
        return _REGISTERED_WORKERS.pop(pid, None) is not None


def get_registered_worker_pids(worker_flags: Iterable[str]) -> Tuple[int, ...]:
    flags = set(_normalize_flags(worker_flags))
    with _REGISTRY_LOCK:
        return tuple(
            sorted(
                pid
                for pid, registration in _REGISTERED_WORKERS.items()
                if registration.flag in flags
            )
        )


def _kill_registered_process(registration: _RegisteredWorker, timeout: float = 3.0) -> bool:
    process = registration.process
    if process.poll() is not None:
        return True

    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(registration.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=float(timeout),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0 and process.poll() is None:
            return False
    else:
        process.terminate()

    try:
        process.wait(timeout=float(timeout))
    except subprocess.TimeoutExpired:
        return False
    return process.poll() is not None


def cleanup_worker_processes(worker_flags: Iterable[str]) -> int:
    flags = set(_normalize_flags(worker_flags))
    with _REGISTRY_LOCK:
        registrations = tuple(
            registration
            for registration in _REGISTERED_WORKERS.values()
            if registration.flag in flags
        )

    cleaned_count = 0
    failed_pids = []
    for registration in registrations:
        try:
            terminated = _kill_registered_process(registration)
        except (OSError, subprocess.SubprocessError):
            terminated = False

        if not terminated:
            failed_pids.append(registration.pid)
            continue

        with _REGISTRY_LOCK:
            _REGISTERED_WORKERS.pop(registration.pid, None)
        cleaned_count += 1

    if failed_pids:
        raise WorkerProcessCleanupError(failed_pids)
    return cleaned_count


def cleanup_all_registered_worker_processes() -> int:
    with _REGISTRY_LOCK:
        flags = tuple(sorted({registration.flag for registration in _REGISTERED_WORKERS.values()}))
    if not flags:
        return 0
    return cleanup_worker_processes(flags)
