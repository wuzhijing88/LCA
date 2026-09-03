# -*- coding: utf-8 -*-
"""窗口稳定身份：HWND 只作运行时缓存，重启后按特征重连。"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from utils.window.hwnd_utils import as_hwnd, get_window_text
from utils.window.window_finder import sanitize_window_lookup_title

logger = logging.getLogger(__name__)

WindowSnapshot = Dict[str, Any]
AliveChecker = Callable[[int], bool]
SnapshotProvider = Callable[[bool], List[WindowSnapshot]]


def is_window_alive(hwnd: Any) -> bool:
    """窗口是否仍存在。最小化也算有效，不要求可见。"""
    handle = as_hwnd(hwnd)
    if handle == 0:
        return False
    try:
        import win32gui

        return bool(win32gui.IsWindow(handle))
    except Exception:
        return False


_DESKTOP_CLASSES = frozenset({"progman", "workerw", "#32769"})
_DESKTOP_CHILD_CLASSES = frozenset({"shelldll_defview"})
_DESKTOP_LIST_CLASSES = frozenset({"syslistview32"})
_DESKTOP_TITLES = frozenset({"program manager", "folderview"})


def _is_desktop_identity(class_name: Any, title: Any = "", parent_class: Any = "") -> bool:
    """按类名/标题/父窗口类判断是否为桌面层。不使用 GetAncestor，避免把普通顶层窗口误判成桌面。"""
    class_key = _normalize_key(class_name)
    title_key = _normalize_key(title)
    parent_key = _normalize_key(parent_class)
    if class_key in _DESKTOP_CLASSES:
        return True
    if title_key in _DESKTOP_TITLES and class_key in _DESKTOP_CLASSES.union(_DESKTOP_CHILD_CLASSES):
        return True
    if parent_key in _DESKTOP_CLASSES and (
        class_key in _DESKTOP_CHILD_CLASSES or class_key in _DESKTOP_LIST_CLASSES
    ):
        return True
    return False


def _get_shell_window_hwnd() -> int:
    try:
        import win32gui

        if hasattr(win32gui, "GetShellWindow"):
            return as_hwnd(win32gui.GetShellWindow())
    except Exception:
        pass
    try:
        import ctypes

        return as_hwnd(ctypes.windll.user32.GetShellWindow())
    except Exception:
        return 0


def is_desktop_window(hwnd: Any) -> bool:
    """是否为桌面或其桌面图标层，不能作为普通窗口捕获目标。"""
    handle = as_hwnd(hwnd)
    if handle == 0:
        return False
    try:
        import win32gui

        if not win32gui.IsWindow(handle):
            return False
        desktop_hwnd = as_hwnd(win32gui.GetDesktopWindow())
        if desktop_hwnd and handle == desktop_hwnd:
            return True
        shell_hwnd = _get_shell_window_hwnd()
        if shell_hwnd and handle == shell_hwnd:
            return True

        class_name = win32gui.GetClassName(handle)
        title = get_window_text(handle)
        parent = as_hwnd(win32gui.GetParent(handle))
        parent_class = win32gui.GetClassName(parent) if parent else ""
        if _is_desktop_identity(class_name, title, parent_class):
            return True

        current = parent
        for _ in range(6):
            if not current:
                break
            current_class = win32gui.GetClassName(current)
            if _normalize_key(current_class) in _DESKTOP_CLASSES:
                return True
            current = as_hwnd(win32gui.GetParent(current))
        return False
    except Exception:
        return False


def find_desktop_icon_layer() -> Tuple[int, int, int]:
    """定位桌面图标层 (Progman/WorkerW, SHELLDLL_DefView, SysListView32)，找不到的环节返回 0。

    绑定「桌面」时后台消息应送到图标层，而不是屏幕上该点最上层的随便哪个窗口
    （任务栏、透明覆盖层、别的程序）。开启壁纸幻灯片等情况下 DefView 会被挂到某个 WorkerW 下。
    """
    try:
        import win32gui
    except Exception:
        return 0, 0, 0
    try:
        progman = as_hwnd(win32gui.FindWindow("Progman", None))
        host = progman
        defview = as_hwnd(win32gui.FindWindowEx(progman, 0, "SHELLDLL_DefView", None)) if progman else 0
        if not defview:
            candidates: List[Tuple[int, int]] = []

            def _collect(hwnd, acc):
                try:
                    if win32gui.GetClassName(hwnd) == "WorkerW":
                        found = as_hwnd(win32gui.FindWindowEx(hwnd, 0, "SHELLDLL_DefView", None))
                        if found:
                            acc.append((as_hwnd(hwnd), found))
                except Exception:
                    pass
                return True

            win32gui.EnumWindows(_collect, candidates)
            if candidates:
                host, defview = candidates[0]
        listview = as_hwnd(win32gui.FindWindowEx(defview, 0, "SysListView32", None)) if defview else 0
        return host, defview, listview
    except Exception:
        return 0, 0, 0


WGC_DESKTOP_ENGINE_MESSAGE = (
    "WGC 无法捕获桌面。请到全局设置将截图引擎改为 PrintWindow、GDI 或 DXGI。"
)


def is_desktop_bound_window(window_info: Any) -> bool:
    """绑定项是否指向桌面。"""
    info = window_info if isinstance(window_info, dict) else {}
    handle = as_hwnd(info.get("hwnd"))
    title = _normalize_text(info.get("title"))
    if handle and is_desktop_window(handle):
        return True
    return _normalize_key(title) in {"桌面", "program manager"}


def has_desktop_bound_window(windows: Optional[Iterable[Any]] = None) -> bool:
    for window in windows or []:
        if is_desktop_bound_window(window):
            return True
    return False


def is_wgc_with_desktop_target(engine: Any, windows: Optional[Iterable[Any]] = None) -> bool:
    """WGC 不能捕获桌面，该组合需要用户改引擎，禁止自动回退。"""
    if str(engine or "").strip().lower() != "wgc":
        return False
    return has_desktop_bound_window(windows)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_key(value: Any) -> str:
    return _normalize_text(value).lower()


def _sanitize_title(value: Any) -> str:
    return sanitize_window_lookup_title(_normalize_text(value))


def _build_instance_key(cmdline: Optional[Sequence[str]]) -> str:
    """从启动参数提取多开实例键。不含 exe 路径，重启后通常仍相同。"""
    if not cmdline:
        return ""
    args = [_normalize_text(part) for part in list(cmdline)[1:]]
    args = [part for part in args if part]
    key = " ".join(args).strip().lower()
    key = " ".join(key.split())
    if not key:
        return ""
    if len(key) > 300:
        return "h:" + hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()
    return key


def _cmdline_instance_key(process: Any, timeout_sec: float = 0.15) -> str:
    """cmdline() 可能在受保护进程上挂起，必须限时。"""
    result = [""]

    def worker() -> None:
        try:
            result[0] = _build_instance_key(process.cmdline())
        except Exception:
            result[0] = ""

    thread = threading.Thread(target=worker, daemon=True, name="WindowCmdlineProbe")
    thread.start()
    thread.join(max(0.05, float(timeout_sec)))
    return result[0]


def _get_window_process_info(
    hwnd: int,
    pid_cache: Optional[Dict[int, Dict[str, str]]] = None,
    include_instance_key: bool = True,
) -> Tuple[str, str]:
    try:
        import win32process

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        pid = int(pid or 0)
        if pid <= 0:
            return "", ""
        if pid_cache is not None and pid in pid_cache:
            cached = pid_cache[pid]
            return cached.get("name", ""), cached.get("instance_key", "")

        process_name = ""
        instance_key = ""
        try:
            import psutil

            process = psutil.Process(pid)
            process_name = _normalize_text(process.name())
            if include_instance_key:
                instance_key = _cmdline_instance_key(process)
        except Exception:
            process_name = ""

        if not process_name:
            try:
                import win32api
                import win32con

                handle = win32api.OpenProcess(
                    win32con.PROCESS_QUERY_LIMITED_INFORMATION,
                    False,
                    pid,
                )
                try:
                    process_name = _normalize_text(os.path.basename(win32process.GetModuleFileNameEx(handle, 0)))
                finally:
                    win32api.CloseHandle(handle)
            except Exception:
                process_name = ""

        if pid_cache is not None:
            pid_cache[pid] = {"name": process_name, "instance_key": instance_key}
        return process_name, instance_key
    except Exception:
        return "", ""


def capture_window_identity(
    hwnd: Any,
    pid_cache: Optional[Dict[int, Dict[str, str]]] = None,
    include_instance_key: bool = True,
) -> Dict[str, str]:
    """采集窗口的稳定特征。HWND / PID 都不是稳定身份。"""
    identity = {
        "title": "",
        "class_name": "",
        "process_name": "",
        "instance_key": "",
    }
    handle = as_hwnd(hwnd)
    if handle == 0:
        return identity

    try:
        import win32gui

        if not win32gui.IsWindow(handle):
            return identity
        identity["title"] = _normalize_text(get_window_text(handle))
        try:
            identity["class_name"] = _normalize_text(win32gui.GetClassName(handle))
        except Exception:
            identity["class_name"] = ""
        process_name, instance_key = _get_window_process_info(
            handle,
            pid_cache,
            include_instance_key=include_instance_key,
        )
        identity["process_name"] = process_name
        identity["instance_key"] = instance_key
    except Exception:
        return identity
    return identity


def _snapshot_from_hwnd(hwnd: int, pid_cache: Optional[Dict[int, Dict[str, str]]] = None) -> Optional[WindowSnapshot]:
    handle = as_hwnd(hwnd)
    if handle == 0:
        return None
    identity = capture_window_identity(handle, pid_cache, include_instance_key=False)
    title = _normalize_text(identity.get("title"))
    if not title and is_desktop_window(handle):
        title = "桌面"
    if not title:
        return None
    return {
        "hwnd": handle,
        "title": title,
        "class_name": _normalize_text(identity.get("class_name")),
        "process_name": _normalize_text(identity.get("process_name")),
        "instance_key": _normalize_text(identity.get("instance_key")),
    }


def enumerate_window_snapshots(include_children: bool = False) -> List[WindowSnapshot]:
    """枚举当前可见窗口快照。默认只扫顶级窗口，子窗口按需补充。"""
    snapshots: List[WindowSnapshot] = []
    seen: set[int] = set()
    pid_cache: Dict[int, Dict[str, str]] = {}

    try:
        import win32gui
    except Exception:
        return snapshots

    def _append(hwnd: int) -> None:
        handle = as_hwnd(hwnd)
        if handle == 0 or handle in seen:
            return
        try:
            if not win32gui.IsWindow(handle):
                return
        except Exception:
            return
        snapshot = _snapshot_from_hwnd(handle, pid_cache)
        if not snapshot:
            return
        seen.add(handle)
        snapshots.append(snapshot)

    def _enum_top(hwnd, _):
        try:
            if win32gui.IsWindowVisible(hwnd):
                _append(hwnd)
                if include_children:
                    def _enum_child(child, __):
                        _append(child)
                        return True

                    try:
                        win32gui.EnumChildWindows(hwnd, _enum_child, 0)
                    except Exception:
                        pass
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(_enum_top, None)
    except Exception as exc:
        logger.debug("枚举窗口快照失败: %s", exc)
    return snapshots


def _identity_from_window_info(window_info: Optional[Dict[str, Any]]) -> Dict[str, str]:
    if not isinstance(window_info, dict):
        return {"title": "", "class_name": "", "process_name": "", "instance_key": ""}
    return {
        "title": _sanitize_title(window_info.get("title")),
        "class_name": _normalize_text(window_info.get("class_name")),
        "process_name": _normalize_text(window_info.get("process_name")),
        "instance_key": _normalize_text(window_info.get("instance_key")),
    }


def _snapshot_sort_key(snapshot: WindowSnapshot) -> Tuple[int, int, int]:
    rect = snapshot.get("rect") or (0, 0, 0, 0)
    try:
        left, top = int(rect[0]), int(rect[1])
    except Exception:
        left, top = 0, 0
    return (left, top, as_hwnd(snapshot.get("hwnd")))


def _fingerprint_key(window_info: Dict[str, Any]) -> Tuple[str, str, str, str]:
    identity = _identity_from_window_info(window_info)
    return (
        identity.get("title", ""),
        _normalize_key(identity.get("class_name")),
        _normalize_key(identity.get("process_name")),
        _normalize_key(identity.get("instance_key")),
    )


def _assign_identical_windows(
    bindings: Sequence[Dict[str, Any]],
    candidates: Sequence[WindowSnapshot],
    occupied_hwnds: Optional[Iterable[Any]] = None,
) -> Dict[int, int]:
    """只在能唯一确认时分配。优先用启动参数实例键，绝不靠位置猜。"""
    occupied = {as_hwnd(item) for item in (occupied_hwnds or []) if as_hwnd(item)}
    unused = [item for item in candidates if as_hwnd(item.get("hwnd")) not in occupied]
    assigned: Dict[int, int] = {}
    if not bindings or not unused:
        return assigned

    claimed_candidates: set[int] = set()
    for binding in bindings:
        expected_key = _normalize_key(_identity_from_window_info(binding).get("instance_key"))
        if not expected_key:
            continue
        matches = [
            item
            for item in unused
            if as_hwnd(item.get("hwnd")) not in claimed_candidates
            and _normalize_key(item.get("instance_key")) == expected_key
        ]
        if len(matches) == 1:
            handle = as_hwnd(matches[0].get("hwnd"))
            assigned[id(binding)] = handle
            claimed_candidates.add(handle)

    leftover_bindings = [binding for binding in bindings if id(binding) not in assigned]
    leftover_candidates = [
        item for item in unused if as_hwnd(item.get("hwnd")) not in claimed_candidates
    ]
    if len(leftover_bindings) == 1 and len(leftover_candidates) == 1:
        assigned[id(leftover_bindings[0])] = as_hwnd(leftover_candidates[0].get("hwnd"))
    elif leftover_bindings and leftover_candidates:
        logger.warning(
            "存在 %s 个相同窗口无法可靠区分，已跳过自动重连，避免绑错",
            len(leftover_bindings),
        )
    return assigned


def _same_fingerprint(snapshot: WindowSnapshot, identity: Dict[str, str], *, require_title: bool) -> bool:
    if identity.get("class_name") and _normalize_key(snapshot.get("class_name")) != _normalize_key(identity["class_name"]):
        return False
    if identity.get("process_name") and _normalize_key(snapshot.get("process_name")) != _normalize_key(identity["process_name"]):
        return False
    if identity.get("instance_key") and _normalize_key(snapshot.get("instance_key")) != _normalize_key(identity["instance_key"]):
        return False
    if require_title and identity.get("title"):
        return _sanitize_title(snapshot.get("title")) == identity["title"]
    return True


def hwnd_matches_identity(hwnd: Any, window_info: Optional[Dict[str, Any]]) -> bool:
    """缓存句柄是否仍指向原来的那扇窗口。"""
    handle = as_hwnd(hwnd)
    if handle == 0 or not is_window_alive(handle):
        return False

    identity = _identity_from_window_info(window_info)
    live = capture_window_identity(handle)
    if identity["class_name"] and _normalize_key(live.get("class_name")) != _normalize_key(identity["class_name"]):
        return False
    if identity["process_name"] and _normalize_key(live.get("process_name")) != _normalize_key(identity["process_name"]):
        return False
    if identity.get("instance_key") and _normalize_key(live.get("instance_key")) != _normalize_key(identity["instance_key"]):
        return False
    if identity["title"]:
        if _sanitize_title(live.get("title")) == identity["title"]:
            return True
        # 标题常会变，类名+进程名都在时允许标题变化
        return bool(identity["class_name"] and identity["process_name"])
    return True


def _select_candidates(
    snapshots: Sequence[WindowSnapshot],
    identity: Dict[str, str],
) -> List[WindowSnapshot]:
    if not snapshots:
        return []

    strict = [item for item in snapshots if _same_fingerprint(item, identity, require_title=True)]
    if strict:
        return sorted(strict, key=_snapshot_sort_key)

    # 标题变了，但类名和进程名都还在，用宽松匹配
    if identity.get("class_name") and identity.get("process_name"):
        relaxed = [item for item in snapshots if _same_fingerprint(item, identity, require_title=False)]
        return sorted(relaxed, key=_snapshot_sort_key)
    return []


def resolve_bound_window_hwnd(
    window_info: Optional[Dict[str, Any]],
    occupied_hwnds: Optional[Iterable[Any]] = None,
    *,
    snapshots: Optional[Sequence[WindowSnapshot]] = None,
    snapshot_provider: Optional[SnapshotProvider] = None,
    hwnd_alive: Optional[AliveChecker] = None,
) -> int:
    """按稳定特征解析当前 HWND。找不到唯一/可区分目标时返回 0。"""
    if not isinstance(window_info, dict):
        return 0

    identity = _identity_from_window_info(window_info)
    alive = hwnd_alive or is_window_alive
    cached_hwnd = as_hwnd(window_info.get("hwnd"))
    if cached_hwnd and alive(cached_hwnd):
        if snapshots is not None:
            cached_snapshot = next(
                (item for item in snapshots if as_hwnd(item.get("hwnd")) == cached_hwnd),
                None,
            )
            if cached_snapshot and (
                _same_fingerprint(cached_snapshot, identity, require_title=True)
                or (
                    identity.get("class_name")
                    and identity.get("process_name")
                    and _same_fingerprint(cached_snapshot, identity, require_title=False)
                )
            ):
                return cached_hwnd
        elif hwnd_matches_identity(cached_hwnd, window_info):
            return cached_hwnd

    if not any(identity.values()):
        return 0

    provider = snapshot_provider or (lambda include_children: enumerate_window_snapshots(include_children))
    current_snapshots = list(snapshots) if snapshots is not None else provider(False)
    candidates = _select_candidates(current_snapshots, identity)
    if not candidates and identity.get("title") and snapshots is None:
        candidates = _select_candidates(provider(True), identity)

    assigned = _assign_identical_windows([window_info], candidates, occupied_hwnds)
    return assigned.get(id(window_info), 0)


def apply_window_identity(
    window_info: Dict[str, Any],
    hwnd: Any,
    *,
    snapshots: Optional[Sequence[WindowSnapshot]] = None,
) -> Dict[str, Any]:
    """把当前句柄和稳定特征写回绑定记录。标题有值时不覆盖，避免冲掉用户看到的名字。"""
    handle = as_hwnd(hwnd)
    window_info["hwnd"] = handle
    if handle == 0:
        return window_info

    live = capture_window_identity(handle)
    if live.get("class_name"):
        window_info["class_name"] = live["class_name"]
    if live.get("process_name"):
        window_info["process_name"] = live["process_name"]
    if live.get("instance_key"):
        window_info["instance_key"] = live["instance_key"]
    if not _normalize_text(window_info.get("title")) and live.get("title"):
        window_info["title"] = live["title"]
    if not _normalize_text(window_info.get("bind_id")):
        window_info["bind_id"] = str(uuid.uuid4())

    identity = _identity_from_window_info(window_info)
    if snapshots is not None:
        peers = _select_candidates(list(snapshots), identity)
        for index, peer in enumerate(peers):
            if as_hwnd(peer.get("hwnd")) == handle:
                window_info["instance_index"] = index
                break
    return window_info


def refresh_bound_windows(
    windows: Optional[List[Any]],
    *,
    snapshots: Optional[Sequence[WindowSnapshot]] = None,
    snapshot_provider: Optional[SnapshotProvider] = None,
    hwnd_alive: Optional[AliveChecker] = None,
) -> bool:
    """就地刷新绑定列表的 HWND。找不到也不删除记录。有句柄变化时返回 True。"""
    if not isinstance(windows, list) or not windows:
        return False

    alive = hwnd_alive or is_window_alive
    provider = snapshot_provider or (lambda include_children: enumerate_window_snapshots(include_children))
    current_snapshots = list(snapshots) if snapshots is not None else provider(False)
    occupied: set[int] = set()
    pending: List[Dict[str, Any]] = []
    changed = False

    for window_info in windows:
        if not isinstance(window_info, dict):
            continue
        cached_hwnd = as_hwnd(window_info.get("hwnd"))
        if cached_hwnd:
            window_info["hwnd"] = cached_hwnd
        if cached_hwnd and alive(cached_hwnd) and hwnd_matches_identity(cached_hwnd, window_info):
            had_identity = bool(window_info.get("class_name") or window_info.get("process_name"))
            apply_window_identity(window_info, cached_hwnd, snapshots=current_snapshots)
            occupied.add(cached_hwnd)
            if not had_identity and (window_info.get("class_name") or window_info.get("process_name")):
                changed = True
        else:
            pending.append(window_info)

    grouped: Dict[Tuple[str, str, str, str], List[Dict[str, Any]]] = {}
    for window_info in pending:
        grouped.setdefault(_fingerprint_key(window_info), []).append(window_info)

    for group_windows in grouped.values():
        identity = _identity_from_window_info(group_windows[0])
        group_snapshots = _select_candidates(current_snapshots, identity)
        if not group_snapshots and snapshots is None and identity.get("title"):
            child_snapshots = provider(True)
            group_snapshots = _select_candidates(child_snapshots, identity)
            if group_snapshots:
                current_snapshots = list(child_snapshots)

        assigned = _assign_identical_windows(group_windows, group_snapshots, occupied)
        for window_info in group_windows:
            new_hwnd = assigned.get(id(window_info), 0)
            old_hwnd = as_hwnd(window_info.get("hwnd"))
            if new_hwnd:
                apply_window_identity(window_info, new_hwnd, snapshots=current_snapshots)
                occupied.add(new_hwnd)
                if old_hwnd != new_hwnd:
                    changed = True
                    logger.info(
                        "绑定窗口句柄已重连: %s -> %s => %s",
                        window_info.get("title"),
                        old_hwnd,
                        new_hwnd,
                    )
            else:
                logger.warning(
                    "绑定窗口暂未重连，保留配置: %s (旧HWND: %s)",
                    window_info.get("title"),
                    old_hwnd,
                )
    return changed


def match_bound_window(
    windows: Optional[Sequence[Any]],
    *,
    hwnd: Any = None,
    title: Any = None,
    bind_id: Any = None,
    enabled_only: bool = True,
) -> Optional[Dict[str, Any]]:
    """在绑定列表里找回同一条记录。句柄变了也能靠 bind_id / 唯一标题对上。"""
    if not isinstance(windows, Sequence):
        return None

    enabled: List[Dict[str, Any]] = []
    for window_info in windows:
        if not isinstance(window_info, dict):
            continue
        if enabled_only and window_info.get("enabled", True) is not True:
            continue
        enabled.append(window_info)
    if not enabled:
        return None

    target_hwnd = as_hwnd(hwnd)
    if target_hwnd:
        for window_info in enabled:
            if as_hwnd(window_info.get("hwnd")) == target_hwnd:
                return window_info

    bind_key = bind_id
    if bind_key not in (None, ""):
        for window_info in enabled:
            if window_info.get("bind_id") == bind_key or window_info.get("window_id") == bind_key:
                return window_info

    clean_title = _sanitize_title(title)
    if clean_title:
        same_title = [
            window_info
            for window_info in enabled
            if _sanitize_title(window_info.get("title")) == clean_title
        ]
        if len(same_title) == 1:
            return same_title[0]

    if len(enabled) == 1 and (target_hwnd or clean_title or bind_key not in (None, "")):
        return enabled[0]
    return None


def resolve_workflow_window_binding(
    window_binding: Optional[Dict[str, Any]],
    bound_windows: Optional[Sequence[Any]],
    *,
    hwnd_alive: Optional[AliveChecker] = None,
) -> Optional[Dict[str, Any]]:
    """把工作流保存的旧 HWND 迁移到当前全局绑定；无法可信匹配时返回 None。"""
    if not isinstance(window_binding, dict):
        return None

    alive = hwnd_alive or is_window_alive
    old_hwnd = as_hwnd(window_binding.get("target_hwnd"))
    bind_id = window_binding.get("bound_window_id")
    title = _normalize_text(window_binding.get("target_window_title"))

    matched = match_bound_window(
        bound_windows,
        hwnd=old_hwnd,
        title=title,
        bind_id=bind_id,
        enabled_only=True,
    )
    if matched is not None:
        matched_hwnd = as_hwnd(matched.get("hwnd"))
        same_id = bind_id not in (None, "") and (
            matched.get("bind_id") == bind_id or matched.get("window_id") == bind_id
        )
        same_title = bool(title) and _sanitize_title(matched.get("title")) == _sanitize_title(title)
        same_hwnd = bool(old_hwnd) and matched_hwnd == old_hwnd

        # 单窗口匹配有便捷回退；导入时仍需稳定依据，避免静默绑到无关窗口。
        if same_id or same_title or same_hwnd:
            if not alive(matched_hwnd):
                matched_hwnd = resolve_bound_window_hwnd(matched, hwnd_alive=alive)
            if matched_hwnd and alive(matched_hwnd):
                resolved = dict(window_binding)
                resolved["target_hwnd"] = matched_hwnd
                resolved["target_window_title"] = _normalize_text(matched.get("title")) or title
                resolved["bound_window_id"] = (
                    matched.get("bind_id")
                    or matched.get("window_id")
                    or bind_id
                )
                return resolved

    if old_hwnd and alive(old_hwnd):
        resolved = dict(window_binding)
        resolved["target_hwnd"] = old_hwnd
        return resolved
    return None
