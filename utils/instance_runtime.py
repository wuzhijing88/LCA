# -*- coding: utf-8 -*-
"""多开实例隔离：槽位、配置副本、热键归属。"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from utils.window.hwnd_utils import as_hwnd

logger = logging.getLogger(__name__)

INSTANCE_SLOT_ENV = "LCA_INSTANCE_SLOT"
MAX_INSTANCE_SLOTS = 32

_SLOT: Optional[int] = None
_OWNS_LOCK = False
_INSTANCES_DIR_OVERRIDE: Optional[str] = None

PidAliveFn = Callable[[int], bool]
HwndAncestryFn = Callable[[int], Sequence[int]]
WindowPidFn = Callable[[int], int]
ForegroundFn = Callable[[], int]


def reset_instance_runtime_for_tests() -> None:
    """测试用：清掉进程内槽位状态。"""
    global _SLOT, _OWNS_LOCK, _INSTANCES_DIR_OVERRIDE
    _SLOT = None
    _OWNS_LOCK = False
    _INSTANCES_DIR_OVERRIDE = None
    os.environ.pop(INSTANCE_SLOT_ENV, None)


def set_instances_dir_for_tests(path: Optional[str]) -> None:
    global _INSTANCES_DIR_OVERRIDE
    _INSTANCES_DIR_OVERRIDE = path


def get_instance_slot() -> int:
    if _SLOT is not None:
        return int(_SLOT)
    env_slot = _parse_slot(os.environ.get(INSTANCE_SLOT_ENV, ""))
    return env_slot or 1


def get_instance_title_suffix() -> str:
    slot = get_instance_slot()
    if slot <= 1:
        return ""
    return f" #{slot}"


def get_instance_display_name(base: str) -> str:
    suffix = get_instance_title_suffix()
    return f"{base}{suffix}" if suffix else base


def get_qsettings_application_name(base: str = "LCA") -> str:
    slot = get_instance_slot()
    if slot <= 1:
        return base
    return f"{base}-{slot}"


def create_app_settings():
    from PySide6.QtCore import QSettings

    return QSettings("LCA", get_qsettings_application_name())


def get_instance_window_offset(step: int = 40) -> tuple[int, int]:
    extra = max(0, get_instance_slot() - 1)
    delta = extra * max(1, int(step))
    return (delta, delta)


def apply_instance_window_offset(
    x: int,
    y: int,
    width: int,
    height: int,
    bounds: Optional[tuple[int, int, int, int]] = None,
    step: int = 40,
) -> tuple[int, int]:
    dx, dy = get_instance_window_offset(step=step)
    new_x = int(x) + dx
    new_y = int(y) + dy
    if not bounds:
        return new_x, new_y
    left, top, right, bottom = (int(value) for value in bounds)
    max_x = right - int(width) + 1
    max_y = bottom - int(height) + 1
    new_x = min(max(new_x, left), max(left, max_x))
    new_y = min(max(new_y, top), max(top, max_y))
    return new_x, new_y


def adopt_instance_slot_from_env() -> int:
    """子进程沿用父进程槽位，不抢锁。"""
    global _SLOT
    env_slot = _parse_slot(os.environ.get(INSTANCE_SLOT_ENV, ""))
    if env_slot:
        _SLOT = env_slot
        return env_slot
    return get_instance_slot()


def claim_instance_slot(
    *,
    instances_dir: Optional[str] = None,
    pid: Optional[int] = None,
    pid_is_running: Optional[PidAliveFn] = None,
) -> int:
    """主进程领取最低空闲槽位，并写入环境变量供子进程继承。"""
    global _SLOT, _OWNS_LOCK

    env_slot = _parse_slot(os.environ.get(INSTANCE_SLOT_ENV, ""))
    if env_slot and not _OWNS_LOCK:
        _SLOT = env_slot
        return env_slot
    if _SLOT is not None and _OWNS_LOCK:
        return int(_SLOT)

    current_pid = int(pid or os.getpid())
    alive = pid_is_running or default_pid_is_running
    directory = _resolve_instances_dir(instances_dir)
    os.makedirs(directory, exist_ok=True)

    for slot in range(1, MAX_INSTANCE_SLOTS + 1):
        lock_path = _lock_path(directory, slot)
        if _try_create_lock(lock_path, slot, current_pid, alive):
            _SLOT = slot
            _OWNS_LOCK = True
            os.environ[INSTANCE_SLOT_ENV] = str(slot)
            if instances_dir is None:
                _seed_instance_config(slot)
            logger.info("多开实例槽位已领取: slot=%s pid=%s", slot, current_pid)
            return slot

    raise RuntimeError(f"无法领取 LCA 实例槽位（已达 {MAX_INSTANCE_SLOTS}）")


def release_instance_slot(*, instances_dir: Optional[str] = None) -> None:
    global _SLOT, _OWNS_LOCK
    if not _OWNS_LOCK or _SLOT is None:
        return
    lock_path = _lock_path(_resolve_instances_dir(instances_dir), int(_SLOT))
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except OSError as exc:
        logger.debug("释放实例锁失败: %s", exc)
    _OWNS_LOCK = False


def publish_bound_hwnds(
    bound_windows: Optional[Iterable[Any]],
    *,
    instances_dir: Optional[str] = None,
) -> None:
    if not _OWNS_LOCK:
        return
    _update_lock_record(
        instances_dir=instances_dir,
        bound_hwnds=extract_bound_hwnds(bound_windows),
    )


def mark_ui_focused(*, instances_dir: Optional[str] = None) -> None:
    if not _OWNS_LOCK:
        return
    _update_lock_record(instances_dir=instances_dir, last_ui_focus_ts=time.time())


def extract_bound_hwnds(bound_windows: Optional[Iterable[Any]]) -> List[int]:
    hwnds: List[int] = []
    seen = set()
    if not bound_windows:
        return hwnds
    for item in bound_windows:
        if not isinstance(item, dict) or not item.get("enabled", True):
            continue
        hwnd = as_hwnd(item.get("hwnd"))
        if hwnd and hwnd not in seen:
            seen.add(hwnd)
            hwnds.append(hwnd)
    return hwnds


def should_handle_hotkey(
    bound_windows: Optional[Iterable[Any]] = None,
    *,
    foreground_hwnd: Optional[int] = None,
    current_pid: Optional[int] = None,
    current_slot: Optional[int] = None,
    peer_records: Optional[Sequence[Dict[str, Any]]] = None,
    instances_dir: Optional[str] = None,
    pid_is_running: Optional[PidAliveFn] = None,
    hwnd_ancestry: Optional[HwndAncestryFn] = None,
    window_pid: Optional[WindowPidFn] = None,
    get_foreground: Optional[ForegroundFn] = None,
    own_last_ui_focus_ts: Optional[float] = None,
) -> bool:
    """多开时只让“对得上”的实例响应热键；单开保持全局热键。"""
    slot = int(current_slot or get_instance_slot())
    pid = int(current_pid or os.getpid())
    alive = pid_is_running or default_pid_is_running
    peers = list(peer_records) if peer_records is not None else list_peer_records(
        instances_dir=instances_dir,
        current_slot=slot,
        pid_is_running=alive,
    )
    if not peers:
        return True

    fg = as_hwnd(foreground_hwnd if foreground_hwnd is not None else _safe_foreground(get_foreground))
    if not fg:
        return False

    ancestry_fn = hwnd_ancestry or default_hwnd_ancestry
    pid_fn = window_pid or default_window_pid
    try:
        chain = [as_hwnd(value) for value in ancestry_fn(fg) if as_hwnd(value)]
    except Exception:
        chain = [fg]
    if fg not in chain:
        chain.insert(0, fg)

    if any(pid_fn(hwnd) == pid for hwnd in chain):
        return True

    our_hwnds = set(extract_bound_hwnds(bound_windows))
    matched = [hwnd for hwnd in chain if hwnd in our_hwnds]
    our_focus = _own_focus_ts(own_last_ui_focus_ts, instances_dir, slot)

    if matched:
        competitors = []
        for peer in peers:
            peer_hwnds = {as_hwnd(value) for value in peer.get("bound_hwnds") or [] if as_hwnd(value)}
            if any(hwnd in peer_hwnds for hwnd in matched):
                competitors.append(peer)
        if not competitors:
            return True
        return _is_latest_focused(slot, our_focus, competitors)

    for peer in peers:
        peer_pid = int(peer.get("pid") or 0)
        peer_hwnds = {as_hwnd(value) for value in peer.get("bound_hwnds") or [] if as_hwnd(value)}
        if peer_pid and any(pid_fn(hwnd) == peer_pid for hwnd in chain):
            return False
        if any(hwnd in peer_hwnds for hwnd in chain):
            return False

    return _is_latest_focused(slot, our_focus, peers)


def _own_focus_ts(
    own_last_ui_focus_ts: Optional[float],
    instances_dir: Optional[str],
    slot: int,
) -> float:
    if own_last_ui_focus_ts is not None:
        return float(own_last_ui_focus_ts)
    record = _read_own_record(instances_dir=instances_dir, slot=slot) or {}
    return float(record.get("last_ui_focus_ts") or 0.0)


def _is_latest_focused(slot: int, our_focus: float, competitors: Sequence[Dict[str, Any]]) -> bool:
    best_slot = slot
    best_focus = our_focus
    for peer in competitors:
        peer_focus = float(peer.get("last_ui_focus_ts") or 0.0)
        peer_slot = int(peer.get("slot") or 0)
        if peer_focus > best_focus or (peer_focus == best_focus and peer_slot and peer_slot < best_slot):
            best_focus = peer_focus
            best_slot = peer_slot
    return best_slot == slot


def list_peer_records(
    *,
    instances_dir: Optional[str] = None,
    current_slot: Optional[int] = None,
    pid_is_running: Optional[PidAliveFn] = None,
) -> List[Dict[str, Any]]:
    directory = _resolve_instances_dir(instances_dir)
    if not os.path.isdir(directory):
        return []
    slot = int(current_slot or get_instance_slot())
    alive = pid_is_running or default_pid_is_running
    records: List[Dict[str, Any]] = []
    for name in os.listdir(directory):
        if not name.startswith("slot-") or not name.endswith(".lock"):
            continue
        path = os.path.join(directory, name)
        record = _read_lock_record(path)
        if not record:
            continue
        peer_slot = int(record.get("slot") or 0)
        peer_pid = int(record.get("pid") or 0)
        if peer_slot == slot or peer_pid <= 0:
            continue
        if not alive(peer_pid):
            continue
        records.append(record)
    return records


def default_pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        process_query_limited_information = 0x1000
        still_active = 259
        handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return int(exit_code.value) == still_active
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def default_window_pid(hwnd: int) -> int:
    hwnd = as_hwnd(hwnd)
    if not hwnd or os.name != "nt":
        return 0
    try:
        import ctypes
        from ctypes import wintypes

        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def default_hwnd_ancestry(hwnd: int) -> List[int]:
    hwnd = as_hwnd(hwnd)
    if not hwnd:
        return []
    chain = [hwnd]
    if os.name != "nt":
        return chain
    try:
        import ctypes

        user32 = ctypes.windll.user32
        ga_root = 2
        root = as_hwnd(user32.GetAncestor(hwnd, ga_root))
        if root and root not in chain:
            chain.append(root)
        current = hwnd
        for _ in range(16):
            parent = as_hwnd(user32.GetParent(current))
            if not parent or parent in chain:
                break
            chain.append(parent)
            current = parent
    except Exception:
        return chain
    return chain


def _safe_foreground(get_foreground: Optional[ForegroundFn]) -> int:
    if get_foreground is not None:
        try:
            return as_hwnd(get_foreground())
        except Exception:
            return 0
    if os.name != "nt":
        return 0
    try:
        import ctypes

        return as_hwnd(ctypes.windll.user32.GetForegroundWindow())
    except Exception:
        return 0


def _parse_slot(value: Any) -> int:
    text = str(value or "").strip()
    if not text.isdigit():
        return 0
    slot = int(text)
    return slot if slot >= 1 else 0


def _resolve_instances_dir(instances_dir: Optional[str] = None) -> str:
    if instances_dir:
        return instances_dir
    if _INSTANCES_DIR_OVERRIDE:
        return _INSTANCES_DIR_OVERRIDE
    from utils.app_paths import get_app_root

    return os.path.join(get_app_root(), "runtime", "instances")


def _lock_path(directory: str, slot: int) -> str:
    return os.path.join(directory, f"slot-{int(slot)}.lock")


def _try_create_lock(lock_path: str, slot: int, pid: int, pid_is_running: PidAliveFn) -> bool:
    record = {
        "slot": int(slot),
        "pid": int(pid),
        "bound_hwnds": [],
        "last_ui_focus_ts": 0.0,
    }
    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
    try:
        fd = os.open(lock_path, flags)
    except FileExistsError:
        existing = _read_lock_record(lock_path)
        existing_pid = int((existing or {}).get("pid") or 0)
        if existing_pid and pid_is_running(existing_pid):
            return False
        try:
            os.remove(lock_path)
        except OSError:
            return False
        try:
            fd = os.open(lock_path, flags)
        except FileExistsError:
            return False
    except OSError:
        return False

    try:
        payload = json.dumps(record, ensure_ascii=False).encode("utf-8")
        os.write(fd, payload)
        os.close(fd)
        return True
    except OSError:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.remove(lock_path)
        except OSError:
            pass
        return False


def _read_lock_record(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _read_own_record(*, instances_dir: Optional[str], slot: int) -> Optional[Dict[str, Any]]:
    return _read_lock_record(_lock_path(_resolve_instances_dir(instances_dir), slot))


def _update_lock_record(
    *,
    instances_dir: Optional[str] = None,
    bound_hwnds: Optional[Sequence[int]] = None,
    last_ui_focus_ts: Optional[float] = None,
) -> None:
    if _SLOT is None:
        return
    path = _lock_path(_resolve_instances_dir(instances_dir), int(_SLOT))
    record = _read_lock_record(path) or {
        "slot": int(_SLOT),
        "pid": os.getpid(),
        "bound_hwnds": [],
        "last_ui_focus_ts": 0.0,
    }
    if bound_hwnds is not None:
        record["bound_hwnds"] = [as_hwnd(value) for value in bound_hwnds if as_hwnd(value)]
    if last_ui_focus_ts is not None:
        record["last_ui_focus_ts"] = float(last_ui_focus_ts)
    record["slot"] = int(_SLOT)
    record["pid"] = int(record.get("pid") or os.getpid())
    tmp_path = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False)
        os.replace(tmp_path, path)
    except OSError as exc:
        logger.debug("更新实例锁失败: %s", exc)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass


def _seed_instance_config(slot: int) -> None:
    if slot <= 1:
        return
    from utils.app_paths import get_app_root

    root = get_app_root()
    primary = os.path.join(root, "config.json")
    dest = os.path.join(root, f"config.instance-{slot}.json")
    if os.path.exists(dest) or not os.path.exists(primary):
        return
    try:
        with open(primary, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return
        data["bound_windows"] = []
        data["active_bound_windows"] = []
        data["target_window_title"] = None
        data["window_binding_mode"] = "single"
        tmp_path = f"{dest}.tmp.{os.getpid()}"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=4, ensure_ascii=False)
        os.replace(tmp_path, dest)
        logger.info("已从主配置复制实例配置（已清空窗口绑定）: %s", dest)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("复制实例配置失败: %s", exc)
