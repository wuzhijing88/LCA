# -*- coding: utf-8 -*-
"""
统一的子进程兜底清理工具。

用于在池对象不存在或状态丢失时，按命令行标记回收工程内孤儿 worker 进程。
"""

from __future__ import annotations

import os
import subprocess
from typing import Iterable, List, Optional, Set, Tuple


def _normalize_flags(worker_flags: Iterable[str]) -> Tuple[str, ...]:
    flags: List[str] = []
    for flag in worker_flags:
        text = str(flag or "").strip().lower()
        if text and text not in flags:
            flags.append(text)
    return tuple(flags)


def _normalize_cmdline(cmdline_raw) -> str:
    try:
        if isinstance(cmdline_raw, (list, tuple)):
            return " ".join(str(part) for part in cmdline_raw).lower()
        return str(cmdline_raw or "").lower()
    except Exception:
        return ""


def _cmdline_matches(cmdline_text: str, worker_flags: Tuple[str, ...], project_root_lc: str) -> bool:
    if not cmdline_text:
        return False
    if project_root_lc and project_root_lc not in cmdline_text:
        return False
    return any(flag in cmdline_text for flag in worker_flags)


def _normalize_path_text(path_raw) -> str:
    try:
        text = str(path_raw or "").strip()
        if not text:
            return ""
        return os.path.abspath(text).lower()
    except Exception:
        return ""


def _is_path_within_project(path_text: str, project_root_lc: str) -> bool:
    normalized_path = _normalize_path_text(path_text)
    normalized_root = _normalize_path_text(project_root_lc)
    if not normalized_path or not normalized_root:
        return False

    try:
        return os.path.commonpath([normalized_path, normalized_root]) == normalized_root
    except Exception:
        return False


def _extract_process_path(proc, info_key: str, getter_name: str) -> str:
    try:
        info = getattr(proc, "info", None)
        if isinstance(info, dict):
            candidate = info.get(info_key)
            if candidate:
                return _normalize_path_text(candidate)
    except Exception:
        pass

    try:
        getter = getattr(proc, getter_name, None)
        if callable(getter):
            return _normalize_path_text(getter())
    except Exception:
        pass
    return ""


def _process_matches_worker(
    proc,
    worker_flags: Tuple[str, ...],
    project_root_lc: str,
    *,
    require_project_root: bool,
) -> bool:
    try:
        info = getattr(proc, "info", None)
        if isinstance(info, dict):
            cmd_text = _normalize_cmdline(info.get("cmdline") or [])
        else:
            cmd_text = _normalize_cmdline(getattr(proc, "cmdline", lambda: [])())
    except Exception:
        cmd_text = ""

    if not any(flag in cmd_text for flag in worker_flags):
        return False
    if not require_project_root or not project_root_lc:
        return True
    if project_root_lc in cmd_text:
        return True

    exe_path = _extract_process_path(proc, "exe", "exe")
    if _is_path_within_project(exe_path, project_root_lc):
        return True

    cwd_path = _extract_process_path(proc, "cwd", "cwd")
    return _is_path_within_project(cwd_path, project_root_lc)


def _kill_pid_tree(pid: int) -> bool:
    if pid <= 0:
        return False

    # Windows 下优先 taskkill /T，保证整棵子树回收。
    if os.name == "nt":
        startupinfo = None
        creationflags = 0
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW
        except Exception:
            startupinfo = None
            creationflags = 0

        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3.0,
                check=False,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
        except Exception:
            pass

    try:
        import psutil

        if not psutil.pid_exists(pid):
            return True

        proc = psutil.Process(pid)
        children = proc.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except Exception:
                pass
        try:
            psutil.wait_procs(children, timeout=1.0)
        except Exception:
            pass
        for child in children:
            try:
                if child.is_running():
                    child.kill()
            except Exception:
                pass

        try:
            if proc.is_running():
                proc.terminate()
                proc.wait(timeout=1.0)
        except Exception:
            try:
                if proc.is_running():
                    proc.kill()
            except Exception:
                pass

        return not psutil.pid_exists(pid)
    except Exception:
        return False


def cleanup_worker_processes(
    worker_flags: Iterable[str],
    project_root: Optional[str] = None,
    main_pid: Optional[int] = None,
) -> int:
    """
    清理当前工程内匹配命令行标记的 worker 进程。

    Args:
        worker_flags: worker 命令行标记，如 '--ocr-worker'
        project_root: 工程根路径（用于缩小匹配范围）
        main_pid: 主进程 PID（默认当前进程）

    Returns:
        成功回收的进程数量
    """
    flags = _normalize_flags(worker_flags)
    if not flags:
        return 0

    current_pid = int(main_pid or os.getpid())
    root = project_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_root_lc = os.path.abspath(root).lower()
    target_pids: Set[int] = set()

    try:
        import psutil

        # 先收集当前主进程子树中的目标进程（即使命令行未完整读取，也优先尝试）
        try:
            parent_proc = psutil.Process(current_pid)
            for child in parent_proc.children(recursive=True):
                try:
                    child_pid = int(child.pid)
                except Exception:
                    continue
                if child_pid <= 0 or child_pid == current_pid:
                    continue
                if _process_matches_worker(
                    child,
                    flags,
                    project_root_lc,
                    require_project_root=False,
                ):
                    target_pids.add(child_pid)
        except Exception:
            pass

        # 再扫描同工程的旧代孤儿进程
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                pid = int(proc.info.get("pid") or 0)
            except Exception:
                continue
            if pid <= 0 or pid == current_pid:
                continue
            if _process_matches_worker(
                proc,
                flags,
                project_root_lc,
                require_project_root=True,
            ):
                target_pids.add(pid)
    except Exception:
        return 0

    cleaned_count = 0
    for pid in sorted(target_pids):
        if _kill_pid_tree(pid):
            cleaned_count += 1
    return cleaned_count
