from __future__ import annotations

from typing import Any, Iterable, Optional, Tuple

from utils.window.hwnd_utils import as_hwnd


def normalize_required_client_size(width: Any, height: Any) -> Tuple[int, int]:
    try:
        required_width = int(width or 0)
    except (TypeError, ValueError):
        required_width = 0
    try:
        required_height = int(height or 0)
    except (TypeError, ValueError):
        required_height = 0
    if required_width <= 0 or required_height <= 0:
        return (0, 0)
    return (required_width, required_height)


def required_client_size(*, package=None, config: Optional[dict] = None) -> Tuple[int, int]:
    """优先用程序包里的要求，其次才看运行配置。宽或高为 0 表示不限制。"""
    width = height = 0
    manifest = getattr(package, "manifest", None) if package is not None else None
    if isinstance(manifest, dict):
        width, height = normalize_required_client_size(
            manifest.get("required_client_width"),
            manifest.get("required_client_height"),
        )
    if (width <= 0 or height <= 0) and isinstance(config, dict):
        width, height = normalize_required_client_size(
            config.get("custom_width"),
            config.get("custom_height"),
        )
    return (width, height)


def required_client_size_from_main(main) -> Tuple[int, int]:
    width = int(getattr(main, "custom_width", 0) or 0)
    height = int(getattr(main, "custom_height", 0) or 0)
    size = normalize_required_client_size(width, height)
    if size != (0, 0):
        return size
    config = getattr(main, "config", None) or {}
    if not isinstance(config, dict):
        return (0, 0)
    return normalize_required_client_size(config.get("custom_width"), config.get("custom_height"))


def get_window_client_size(hwnd: Any) -> Optional[Tuple[int, int]]:
    handle = as_hwnd(hwnd)
    if not handle:
        return None
    try:
        import win32gui

        if not win32gui.IsWindow(handle):
            return None
        left, top, right, bottom = win32gui.GetClientRect(handle)
    except Exception:
        return None
    return (int(right - left), int(bottom - top))


def format_size(size: Tuple[int, int]) -> str:
    return f"{int(size[0])}×{int(size[1])}"


def find_resolution_mismatches(
    windows: Iterable[dict],
    required_width: int,
    required_height: int,
) -> list[str]:
    required = normalize_required_client_size(required_width, required_height)
    if required == (0, 0):
        return []
    from utils.window.window_identity import is_window_alive

    messages: list[str] = []
    for item in windows:
        if not isinstance(item, dict):
            continue
        hwnd = as_hwnd(item.get("hwnd"))
        title = str(item.get("title") or "窗口").strip() or "窗口"
        if not hwnd or not is_window_alive(hwnd):
            continue
        actual = get_window_client_size(hwnd)
        if actual is None:
            messages.append(f"「{title}」无法读取客户区尺寸")
            continue
        if actual != required:
            messages.append(
                f"「{title}」当前 {format_size(actual)}，要求 {format_size(required)}"
            )
    return messages


def assert_bound_windows_resolution(
    windows: Iterable[dict],
    required_width: int,
    required_height: int,
) -> None:
    required = normalize_required_client_size(required_width, required_height)
    if required == (0, 0):
        return
    mismatches = find_resolution_mismatches(windows, required[0], required[1])
    if not mismatches:
        return
    raise RuntimeError(
        "目标窗口分辨率不符合要求：\n"
        + "\n".join(mismatches)
        + f"\n\n请将窗口客户区调整为 {format_size(required)} 后再开始。"
    )


def adjust_window_to_required_client_size(
    hwnd: Any,
    required_width: int,
    required_height: int,
    *,
    title: str = "窗口",
) -> Tuple[bool, str]:
    """把窗口客户区调到要求尺寸。

    返回 ``(ok, message)``：已符合或调整成功为 ``(True, "")``；
    无要求时 ``(True, "")``；失败为 ``(False, 说明)``。
    """
    required = normalize_required_client_size(required_width, required_height)
    if required == (0, 0):
        return True, ""
    handle = as_hwnd(hwnd)
    label = str(title or "窗口").strip() or "窗口"
    if not handle:
        return False, f"无法调整「{label}」：窗口句柄无效"
    actual = get_window_client_size(handle)
    if actual is None:
        return False, f"无法读取「{label}」的客户区尺寸，请确认窗口可见后重试"
    if actual == required:
        return True, ""
    try:
        from utils.window.universal_window_manager import get_universal_window_manager

        result = get_universal_window_manager().adjust_single_window(
            handle,
            required[0],
            required[1],
            async_mode=False,
        )
    except Exception as exc:
        return (
            False,
            f"自动调整「{label}」到 {format_size(required)} 失败：{exc}\n"
            f"请手动把窗口客户区调整为 {format_size(required)} 后再绑定。",
        )
    if not getattr(result, "success", False):
        detail = str(getattr(result, "message", "") or "").strip()
        suffix = f"：{detail}" if detail else ""
        return (
            False,
            f"自动调整「{label}」到 {format_size(required)} 失败{suffix}\n"
            f"当前 {format_size(actual)}。请手动调整后再绑定。",
        )
    after = get_window_client_size(handle)
    if after == required:
        return True, ""
    shown = format_size(after) if after is not None else "未知"
    return (
        False,
        f"已尝试调整「{label}」，但仍为 {shown}，要求 {format_size(required)}。\n"
        "请手动把窗口客户区调整到要求尺寸后再绑定。",
    )


def ensure_bound_windows_resolution(
    windows: Iterable[dict],
    required_width: int,
    required_height: int,
) -> list[str]:
    """对已绑定窗口逐个尝试自动调整；返回仍不符合的说明列表。"""
    required = normalize_required_client_size(required_width, required_height)
    if required == (0, 0):
        return []
    from utils.window.window_identity import is_window_alive

    errors: list[str] = []
    for item in windows:
        if not isinstance(item, dict):
            continue
        hwnd = as_hwnd(item.get("hwnd"))
        title = str(item.get("title") or "窗口").strip() or "窗口"
        if not hwnd or not is_window_alive(hwnd):
            continue
        ok, message = adjust_window_to_required_client_size(
            hwnd,
            required[0],
            required[1],
            title=title,
        )
        if not ok:
            errors.append(message.replace("\n", " "))
    return errors
