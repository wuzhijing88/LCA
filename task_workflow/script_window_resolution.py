# -*- coding: utf-8 -*-
"""自定义脚本：解析并应用窗口客户区分辨率。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from utils.window.hwnd_utils import as_hwnd


class ResolutionError(ValueError):
    """参数或目标窗口无法解析。"""


@dataclass(frozen=True)
class ResolutionCall:
    width: Optional[int]
    height: Optional[int]
    target: Any
    raise_on_error: bool


def _is_number(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    text = str(value).strip()
    if not text:
        return False
    try:
        float(text)
    except (TypeError, ValueError):
        return False
    return True


def _as_int(value: Any, label: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ResolutionError(f"{label}必须是整数") from exc
    return number


def parse_resolution_args(*args: Any, 报错: Any = True) -> ResolutionCall:
    raise_on_error = bool(报错)
    if len(args) == 1 and _is_number(args[0]):
        raise ResolutionError("单独一个数字不允许，宽高请成对写，序号请放在第三个位置或列表里")
    if len(args) == 0:
        return ResolutionCall(None, None, None, raise_on_error)
    if len(args) == 1:
        return ResolutionCall(None, None, args[0], raise_on_error)
    if len(args) == 2:
        if not (_is_number(args[0]) and _is_number(args[1])):
            raise ResolutionError("宽高必须成对写成数字，例如 窗口.设置分辨率(1280, 720)")
        return ResolutionCall(_as_int(args[0], "宽"), _as_int(args[1], "高"), None, raise_on_error)
    if len(args) == 3:
        if not (_is_number(args[0]) and _is_number(args[1])):
            raise ResolutionError("前两个参数必须是宽和高")
        return ResolutionCall(_as_int(args[0], "宽"), _as_int(args[1], "高"), args[2], raise_on_error)
    raise ResolutionError("窗口.设置分辨率 参数太多")


def enabled_bound_windows(windows: Optional[Iterable[Any]]) -> List[Dict[str, Any]]:
    enabled: List[Dict[str, Any]] = []
    if not isinstance(windows, Iterable) or isinstance(windows, (str, bytes)):
        return enabled
    for item in windows:
        if not isinstance(item, dict):
            continue
        if item.get("enabled", True) is False:
            continue
        hwnd = as_hwnd(item.get("hwnd"))
        if not hwnd:
            continue
        title = str(item.get("title") or "").strip()
        enabled.append({"hwnd": hwnd, "title": title, "enabled": True})
    return enabled


def _dedupe(windows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result: List[Dict[str, Any]] = []
    for item in windows:
        hwnd = int(item["hwnd"])
        if hwnd in seen:
            continue
        seen.add(hwnd)
        result.append(item)
    return result


def _match_title(windows: Sequence[Dict[str, Any]], title: str) -> List[Dict[str, Any]]:
    needle = str(title or "").strip()
    if not needle:
        raise ResolutionError("窗口标题不能为空")
    exact = [item for item in windows if item["title"] == needle]
    if exact:
        return exact
    contains = [item for item in windows if needle in item["title"]]
    if contains:
        return contains
    raise ResolutionError(f"没有标题匹配「{needle}」的绑定窗口")


def _match_index(windows: Sequence[Dict[str, Any]], index: int) -> Dict[str, Any]:
    if index < 1 or index > len(windows):
        raise ResolutionError(f"窗口序号越界：{index}")
    return windows[index - 1]


def _match_current(windows: Sequence[Dict[str, Any]], current_hwnd: Any) -> Dict[str, Any]:
    hwnd = as_hwnd(current_hwnd)
    if not hwnd:
        raise ResolutionError("没有当前窗口")
    for item in windows:
        if int(item["hwnd"]) == hwnd:
            return item
    raise ResolutionError("当前窗口不在绑定列表里")


def _match_one(windows: Sequence[Dict[str, Any]], current_hwnd: Any, item: Any) -> List[Dict[str, Any]]:
    if item is None:
        return [_match_current(windows, current_hwnd)]
    if isinstance(item, bool):
        raise ResolutionError("目标不能是真假值")
    if isinstance(item, (int, float)) and not isinstance(item, bool):
        return [_match_index(windows, _as_int(item, "序号"))]
    if isinstance(item, str):
        text = item.strip()
        if text in {"当前", "current"}:
            return [_match_current(windows, current_hwnd)]
        if text in {"全部", "所有", "all"}:
            if not windows:
                raise ResolutionError("没有可调整的绑定窗口")
            return list(windows)
        return _match_title(windows, text)
    raise ResolutionError(f"无法识别的窗口目标: {item!r}")


def resolve_resolution_targets(
    *,
    windows: Optional[Iterable[Any]],
    current_hwnd: Any,
    target: Any,
) -> List[Dict[str, Any]]:
    enabled = enabled_bound_windows(windows)
    if isinstance(target, (list, tuple)):
        if not target:
            raise ResolutionError("窗口列表不能为空")
        matched: List[Dict[str, Any]] = []
        for item in target:
            matched.extend(_match_one(enabled, current_hwnd, item))
        return _dedupe(matched)
    return _dedupe(_match_one(enabled, current_hwnd, target))


def apply_window_resolution(
    *,
    call: ResolutionCall,
    windows: Optional[Iterable[Any]],
    current_hwnd: Any,
    global_size: Tuple[int, int],
    adjust: Callable[[int, int, int], bool],
) -> Dict[str, Any]:
    width, height = call.width, call.height
    if width is None or height is None:
        required_width, required_height = int(global_size[0] or 0), int(global_size[1] or 0)
        if required_width <= 0 or required_height <= 0:
            error = "未写宽高，且全局自定义分辨率是 0×0"
            if call.raise_on_error:
                raise ResolutionError(error)
            return {"ok": False, "kind": "window", "width": 0, "height": 0, "error": error}
        width, height = required_width, required_height
    if int(width) <= 0 or int(height) <= 0:
        error = "宽高必须大于 0"
        if call.raise_on_error:
            raise ResolutionError(error)
        return {"ok": False, "kind": "window", "width": 0, "height": 0, "error": error}

    try:
        targets = resolve_resolution_targets(
            windows=windows,
            current_hwnd=current_hwnd,
            target=call.target,
        )
    except ResolutionError as exc:
        if call.raise_on_error:
            raise
        return {"ok": False, "kind": "window", "width": 0, "height": 0, "error": str(exc)}

    errors: List[str] = []
    last_ok = (int(width), int(height))
    for item in targets:
        hwnd = int(item["hwnd"])
        title = item.get("title") or "窗口"
        try:
            ok = bool(adjust(hwnd, int(width), int(height)))
        except Exception as exc:
            ok = False
            errors.append(f"「{title}」{exc}")
            continue
        if ok:
            last_ok = (int(width), int(height))
        else:
            errors.append(f"「{title}」调整失败")
    if errors:
        message = "；".join(errors)
        if call.raise_on_error:
            raise ResolutionError(message)
        return {
            "ok": False,
            "kind": "window",
            "width": last_ok[0],
            "height": last_ok[1],
            "error": message,
        }
    return {"ok": True, "kind": "window", "width": last_ok[0], "height": last_ok[1], "error": ""}


def default_adjust_window(hwnd: int, width: int, height: int) -> bool:
    from utils.window.universal_window_manager import UniversalWindowManager

    result = UniversalWindowManager().adjust_single_window(int(hwnd), int(width), int(height))
    return bool(getattr(result, "success", False))
