# -*- coding: utf-8 -*-
"""自定义脚本命令：组参数后调用现有 execute_task。"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from task_workflow.runtime_store import RuntimeStore

logger = logging.getLogger(__name__)

# 每个脚本宿主最多保留的用户线程数，避免长时间运行时无界创建线程耗尽资源。
MAX_USER_THREADS = 32

RESULT_FIELD_ALIASES = {
    "通过": "ok",
    "成功": "ok",
    "类型": "kind",
    "内容": "text",
    "文字": "text",
    "分数": "score",
    "阈值": "threshold",
    "类别": "class_name",
    "路径": "path",
    "列表": "items",
    "横坐标": "x",
    "纵坐标": "y",
    "宽": "width",
    "高": "height",
    "左": "x1",
    "上": "y1",
    "右": "x2",
    "下": "y2",
    "颜色": "color",
    "红": "r",
    "绿": "g",
    "蓝": "b",
    "句柄": "handle",
    "返回值": "value",
    "值": "value",
    "退出码": "exit_code",
    "标准输出": "stdout",
    "标准错误": "stderr",
    "进程号": "pid",
    "状态": "status",
    "模式": "execution_mode",
    "消息": "message",
    "投递": "posted",
    "DPI": "dpi",
    "缩放": "scale",
    "父句柄": "parent_hwnd",
    "深度": "depth",
    "运行": "running",
    "结果": "result",
    "错误": "error",
    "名字": "name",
    "名称": "name",
    "自动化ID": "automation_id",
    "类名": "class_name",
    "控件类型": "control_type",
    "开始时间": "started_at",
    "完成时间": "finished_at",
    "状态码": "status",
    "头": "headers",
    "字节数": "bytes",
    "地址": "url",
    "勾选": "checked",
    "展开": "expanded",
    "启用": "enabled",
    "脱离屏幕": "offscreen",
    "聚焦": "focused",
    "动作": "action",
    "设备号": "id",
    "按钮": "buttons",
    "摇杆X": "x",
    "摇杆Y": "y",
    "摇杆Z": "z",
    "方向帽": "pov",
    "已连接": "connected",
    "DPI感知": "dpi_aware",
    "管理员": "admin",
    "DirectX": "directx",
    "OpenGL": "opengl",
    "截图": "screenshot",
    "截图诊断": "screenshot_diagnostics",
    "窗口DPI": "window_dpi",
    "窗口进程号": "window_pid",
    "窗口管理员": "window_admin",
    "窗口完整性": "window_integrity",
    "运行时": "runtime",
    "内存(MB)": "rss_mb",
    "CPU占用": "cpu_percent",
    "脚本线程": "script_threads",
    "后台线程": "watch_threads",
    "截图线程上限": "screenshot_worker_limit",
    "可用": "available",
    "内存字节": "rss_bytes",
    "内存MB": "rss_mb",
    "CPU占用率": "cpu_percent",
    "进程线程": "threads",
    "脚本线程数": "script_threads",
    "后台监视线程": "watch_threads",
    "设备": "devices",
    "WinMM": "winmm",
    "HIDAPI": "hidapi",
    "虚拟手柄": "virtual_gamepad",
    "可读游戏杆": "can_read_joystick",
    "可读HID": "can_read_hid",
    "可注入": "can_inject",
    "数据": "data",
}


class ScriptResult:
    """找图/点击等命令的返回值：if 里当真假，也可以读 x、y。"""

    def __init__(self, payload: Optional[Dict[str, Any]] = None, ok: Optional[bool] = None) -> None:
        self._payload = dict(payload or {})
        _fill_box_fields(self._payload)
        if ok is not None:
            self._payload["ok"] = bool(ok)
        else:
            self._payload.setdefault("ok", False)

    def __bool__(self) -> bool:
        return bool(self._payload.get("ok"))

    def __repr__(self) -> str:
        return f"ScriptResult(ok={bool(self)}, x={self._payload.get('x')}, y={self._payload.get('y')})"

    def coords(self) -> Tuple[Any, Any]:
        return self._payload.get("x"), self._payload.get("y")

    def 点(self, 横向: Any = 0.5, 纵向: Any = 0.5) -> "ScriptResult":
        point = point_in_result(self, 横向, 纵向)
        if point is None:
            raise ValueError("没有框，算不出框内点")
        return ScriptResult({"ok": True, "kind": "point", "x": point[0], "y": point[1]})

    def 随机点(self, 边距: Any = 2) -> "ScriptResult":
        point = point_in_result(self, 随机=True, 边距=边距)
        if point is None:
            raise ValueError("没有框，算不出随机点")
        return ScriptResult({"ok": True, "kind": "point", "x": point[0], "y": point[1]})

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        key = RESULT_FIELD_ALIASES.get(name, name)
        if key in self._payload:
            if key == "items":
                return wrap_result_items(self._payload.get("items"))
            return self._payload[key]
        raise AttributeError(f"没有字段: {name}")

    def __len__(self) -> int:
        items = self._payload.get("items")
        if isinstance(items, list):
            return len(items)
        return 1 if bool(self) else 0

    def __iter__(self):
        items = self._payload.get("items")
        if isinstance(items, list):
            return iter(wrap_result_items(items))
        return iter((self,) if bool(self) else ())

    def __getitem__(self, key: Any) -> Any:
        items = self._payload.get("items")
        if isinstance(items, list) and not isinstance(key, bool):
            if isinstance(key, int) or (isinstance(key, str) and str(key).lstrip("-").isdigit()):
                return wrap_result_item(items[int(key)])
        key_name = RESULT_FIELD_ALIASES.get(str(key), key)
        if key_name in self._payload:
            if key_name == "items":
                return wrap_result_items(self._payload.get("items"))
            return self._payload[key_name]
        raise AttributeError(f"没有字段: {key}")


def result_coords(value: Any) -> Optional[Tuple[Any, Any]]:
    if value is None or isinstance(value, (bool, int, float, str)):
        return None
    if isinstance(value, ScriptResult):
        x, y = value.coords()
        if x is None or y is None:
            return None
        return x, y
    if isinstance(value, dict):
        x, y = value.get("x"), value.get("y")
        if x is None or y is None:
            return None
        return x, y
    for x_name, y_name in (("横坐标", "纵坐标"), ("x", "y")):
        x = getattr(value, x_name, None)
        y = getattr(value, y_name, None)
        if x is not None and y is not None:
            return x, y
    return None


def wrap_result_item(item: Any) -> Any:
    if isinstance(item, ScriptResult):
        return item
    if not isinstance(item, dict):
        return item
    payload = dict(item)
    if payload.get("class_name") is None:
        payload["class_name"] = payload.get("类别") or payload.get("文字")
    if payload.get("score") is None:
        payload["score"] = payload.get("confidence") or payload.get("分数")
    payload.setdefault("ok", True)
    payload.setdefault("kind", payload.get("kind") or "item")
    return ScriptResult(payload)


def _fill_box_fields(payload: Dict[str, Any]) -> None:
    x1, y1, x2, y2 = payload.get("x1"), payload.get("y1"), payload.get("x2"), payload.get("y2")
    if None not in (x1, y1, x2, y2):
        if payload.get("x") is None:
            payload["x"] = (int(x1) + int(x2)) // 2
        if payload.get("y") is None:
            payload["y"] = (int(y1) + int(y2)) // 2
        if payload.get("width") is None:
            payload["width"] = int(x2) - int(x1)
        if payload.get("height") is None:
            payload["height"] = int(y2) - int(y1)
        return
    x, y = payload.get("x"), payload.get("y")
    width, height = payload.get("width"), payload.get("height")
    if None in (x, y, width, height):
        return
    if payload.get("x1") is None:
        payload["x1"] = int(x) - int(width) // 2
        payload["y1"] = int(y) - int(height) // 2
        payload["x2"] = payload["x1"] + int(width)
        payload["y2"] = payload["y1"] + int(height)


def wrap_result_items(items: Any) -> Any:
    if not isinstance(items, list):
        return items
    return [wrap_result_item(item) for item in items]


def _payload_of(value: Any) -> Optional[Dict[str, Any]]:
    if isinstance(value, ScriptResult):
        return value._payload
    if isinstance(value, dict):
        return value
    return None


def result_box(value: Any) -> Optional[Tuple[int, int, int, int]]:
    payload = _payload_of(value)
    if not payload:
        return None
    x1, y1, x2, y2 = payload.get("x1"), payload.get("y1"), payload.get("x2"), payload.get("y2")
    if None not in (x1, y1, x2, y2):
        return int(x1), int(y1), int(x2), int(y2)
    x, y = payload.get("x"), payload.get("y")
    width, height = payload.get("width"), payload.get("height")
    if None not in (x, y, width, height):
        left = int(x) - int(width) // 2
        top = int(y) - int(height) // 2
        return left, top, left + int(width), top + int(height)
    return None


def point_in_result(
    value: Any,
    横向: Any = 0.5,
    纵向: Any = 0.5,
    随机: bool = False,
    边距: Any = 0,
) -> Optional[Tuple[int, int]]:
    box = result_box(value)
    if box is None:
        return result_coords(value)
    left, top, right, bottom = box
    inset = max(0, _as_int(边距, 0))
    left += inset
    top += inset
    right -= inset
    bottom -= inset
    if right < left:
        left = right = (box[0] + box[2]) // 2
    if bottom < top:
        top = bottom = (box[1] + box[3]) // 2
    if 随机:
        return random.randint(left, right), random.randint(top, bottom)
    ratio_x = min(1.0, max(0.0, float(横向 if 横向 is not None else 0.5)))
    ratio_y = min(1.0, max(0.0, float(纵向 if 纵向 is not None else 0.5)))
    return int(left + (right - left) * ratio_x), int(top + (bottom - top) * ratio_y)


def _offset_alias(偏移x: Any, 偏移y: Any, 偏移横坐标: Any, 偏移纵坐标: Any) -> Tuple[Any, Any]:
    return (偏移横坐标 if 偏移x is None else 偏移x, 偏移纵坐标 if 偏移y is None else 偏移y)


def resolve_xy(
    x: Any = None,
    y: Any = None,
    横坐标: Any = None,
    纵坐标: Any = None,
    目标: Any = None,
) -> Optional[Tuple[int, int]]:
    if 目标 is not None and x is None:
        x = 目标
    if 横坐标 is not None:
        x = 横坐标
    if 纵坐标 is not None:
        y = 纵坐标
    if y is None:
        found = result_coords(x)
        if found is not None:
            return int(found[0]), int(found[1])
    if _is_number_like(x) and _is_number_like(y):
        return int(x), int(y)
    return None


def resolve_drag(
    x1: Any,
    y1: Any,
    x2: Any = None,
    y2: Any = None,
) -> Optional[Tuple[int, int, int, int]]:
    start = result_coords(x1)
    end = result_coords(y1)
    if start is not None and end is not None and x2 is None and y2 is None:
        return int(start[0]), int(start[1]), int(end[0]), int(end[1])
    if start is not None and _is_number_like(y1) and _is_number_like(x2) and y2 is None:
        return int(start[0]), int(start[1]), int(y1), int(x2)
    if _is_number_like(x1) and _is_number_like(y1) and _is_number_like(x2) and _is_number_like(y2):
        return int(x1), int(y1), int(x2), int(y2)
    return None


FORBIDDEN_TASK_TYPES = frozenset(
    {
        "自定义脚本",
        "子工作流",
        "线程控制",
        "随机跳转",
        "附加条件",
        "线程起点",
        "线程窗口限制",
    }
)
ALLOWED_TASK_TYPES = frozenset(
    {
        "图片点击",
        "模拟鼠标操作",
        "模拟键盘操作",
        "延迟",
        "OCR文字识别",
        "点阵字库OCR",
        "YOLO目标检测",
        "录制回放",
    }
)
_KIND_BY_TASK = {
    "图片点击": "image",
    "OCR文字识别": "ocr",
    "点阵字库OCR": "ocr",
    "YOLO目标检测": "yolo",
}
MIN_WATCH_INTERVAL = 0.05


def _is_stop_error(exc: BaseException) -> bool:
    message = str(exc or "")
    return message.startswith(("已停止", "停止检查")) or "已停止" in message


def defaults_from_definition(param_definitions: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    if not isinstance(param_definitions, dict):
        return params
    for name, spec in param_definitions.items():
        if not isinstance(name, str) or not isinstance(spec, dict):
            continue
        if spec.get("type") in {"separator", "button"}:
            continue
        if "default" in spec:
            params[name] = spec["default"]
    return params


def task_succeeded(result: Any) -> bool:
    if result is None:
        return False
    if isinstance(result, tuple) and result:
        return bool(result[0])
    return bool(result)


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        text = value.strip()
        if text in {"真", "True", "true", "1", "是"}:
            return True
        if text in {"假", "False", "false", "0", "否", ""}:
            return False
    return bool(value)


def _as_duration(value: Any, default: float = 0.5) -> float:
    if value is None or value == "":
        return float(default)
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        low, high = float(value[0]), float(value[1])
        if high < low:
            low, high = high, low
        if low == high:
            return low
        return random.uniform(low, high)
    return float(value)


def _as_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return int(default)
    return int(value)


def _as_region(
    区域: Any,
    regions: Optional[Dict[str, Tuple[int, int, int, int]]] = None,
) -> Optional[Tuple[int, int, int, int]]:
    if 区域 is None or 区域 is False:
        return None
    if isinstance(区域, str):
        name = 区域.strip()
        rect = (regions or {}).get(name) if name else None
        if rect is None:
            raise ValueError(f"没有这个区域: {name}")
        return rect
    if isinstance(区域, (tuple, list)) and len(区域) >= 4:
        try:
            left, top, width, height = int(区域[0]), int(区域[1]), int(区域[2]), int(区域[3])
        except (TypeError, ValueError) as exc:
            raise ValueError("区域请写成 (横坐标, 纵坐标, 宽, 高)") from exc
        if width <= 0 or height <= 0:
            raise ValueError("宽和高必须大于 0")
        return left, top, width, height
    raise ValueError("区域请写成 (横坐标, 纵坐标, 宽, 高)")


def _two_points(点1: Any, 点2: Any = None, x2: Any = None, y2: Any = None) -> Optional[Tuple[float, float, float, float]]:
    if _is_number_like(点1) and _is_number_like(点2) and _is_number_like(x2) and _is_number_like(y2):
        return float(点1), float(点2), float(x2), float(y2)
    start = result_coords(点1)
    end = result_coords(点2)
    if start is None or end is None:
        return None
    return float(start[0]), float(start[1]), float(end[0]), float(end[1])


def _is_number_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("+", "-")):
            text = text[1:]
        return bool(text) and text.isdigit()
    return False


def build_click_style_params(
    双击: Any = False,
    偏移横坐标: Any = 0,
    偏移纵坐标: Any = 0,
    偏移x: Any = None,
    偏移y: Any = None,
    随机: Any = None,
    随机横坐标: Any = None,
    随机纵坐标: Any = None,
    动作: Any = None,
    次数: Any = None,
    间隔: Any = None,
    按住秒: Any = None,
    自动松开: Any = None,
) -> Dict[str, Any]:
    偏移横坐标, 偏移纵坐标 = _offset_alias(偏移x, 偏移y, 偏移横坐标, 偏移纵坐标)
    double = _as_bool(双击)
    fixed_x = _as_int(偏移横坐标, 0)
    fixed_y = _as_int(偏移纵坐标, 0)
    rand_x = _as_int(随机横坐标 if 随机横坐标 is not None else (0 if 随机 is None else 随机), 0)
    rand_y = _as_int(随机纵坐标 if 随机纵坐标 is not None else (0 if 随机 is None else 随机), 0)
    if fixed_x or fixed_y:
        mode = "固定偏移"
    elif rand_x or rand_y:
        mode = "随机偏移"
    else:
        mode = "精准坐标"
    action = "双击" if double else "完整点击"
    raw_action = str(动作 or "").strip()
    if raw_action in {"仅按下", "按下"}:
        action = "仅按下"
        double = False
    elif raw_action in {"仅松开", "松开", "弹起", "释放"}:
        action = "仅松开"
        double = False
    elif raw_action in {"双击"}:
        action = "双击"
        double = True
    elif raw_action in {"完整点击", "单击"}:
        action = "完整点击"
        double = False
    click_count = 2 if double else max(1, _as_int(次数, 1) if 次数 is not None else 1)
    interval = 0.0 if 间隔 is None or 间隔 == "" else float(间隔)
    hold = 0.0 if 按住秒 is None or 按住秒 == "" else _as_duration(按住秒, 0.0)
    if 自动松开 is None:
        auto_release = action != "仅按下"
    else:
        auto_release = _as_bool(自动松开)
    params = {
        "click_action": action,
        "clicks": click_count,
        "click_interval": interval,
        "position_mode": mode,
        "image_position_mode": mode,
        "coordinate_position_mode": mode,
        "click_position_mode": mode,
        "text_position_mode": mode,
        "coordinate_click_action": action,
        "color_click_action": action,
        "text_click_action": action,
        "coordinate_click_clicks": click_count,
        "color_click_clicks": click_count,
        "text_click_clicks": click_count,
        "coordinate_click_interval": interval,
        "color_click_interval": interval,
        "text_click_interval": interval,
        "fixed_offset_x": fixed_x,
        "fixed_offset_y": fixed_y,
        "coordinate_fixed_offset_x": fixed_x,
        "coordinate_fixed_offset_y": fixed_y,
        "color_fixed_offset_x": fixed_x,
        "color_fixed_offset_y": fixed_y,
        "text_fixed_offset_x": fixed_x,
        "text_fixed_offset_y": fixed_y,
        "random_offset_x": rand_x,
        "random_offset_y": rand_y,
        "coordinate_random_offset_x": rand_x,
        "coordinate_random_offset_y": rand_y,
        "color_random_offset_x": rand_x,
        "color_random_offset_y": rand_y,
        "text_random_offset_x": rand_x,
        "text_random_offset_y": rand_y,
        "enable_auto_release": auto_release,
        "coordinate_enable_auto_release": auto_release,
        "color_enable_auto_release": auto_release,
        "text_enable_auto_release": auto_release,
    }
    if hold:
        params["hold_duration"] = hold
        params["coordinate_hold_duration"] = hold
        params["color_hold_duration"] = hold
        params["text_hold_duration"] = hold
        params["image_hold_duration"] = hold
    return params


def collect_find_image_args(图片: Any, extra: Tuple[Any, ...] = ()) -> Tuple[list, Optional[float]]:
    items = []
    if 图片 is not None:
        items.append(图片)
    items.extend(extra)
    images = []
    threshold = None
    for item in items:
        if item is None:
            continue
        if isinstance(item, (list, tuple)) and not isinstance(item, (str, bytes)):
            nested, nested_threshold = collect_find_image_args(None, tuple(item))
            images.extend(nested)
            if nested_threshold is not None:
                threshold = nested_threshold
            continue
        if isinstance(item, (int, float)) and not isinstance(item, bool) and images:
            threshold = float(item)
            continue
        text = str(item).strip()
        if not text:
            continue
        images.extend(part.strip() for part in text.replace(";", "\n").splitlines() if part.strip())
    return images, threshold


def build_find_image_params(
    图片: Any,
    阈值: Any = 0.8,
    点击: Any = False,
    defaults: Optional[Dict[str, Any]] = None,
    双击: Any = False,
    偏移横坐标: Any = 0,
    偏移纵坐标: Any = 0,
    随机: Any = None,
    随机横坐标: Any = None,
    随机纵坐标: Any = None,
    区域: Any = None,
    extra_images: Tuple[Any, ...] = (),
    动作: Any = None,
    次数: Any = None,
    间隔: Any = None,
    按住秒: Any = None,
    自动松开: Any = None,
    缩放: Any = 1.0,
    图像模式: Any = "彩色",
    旋转: Any = 0,
) -> Dict[str, Any]:
    images, inferred_threshold = collect_find_image_args(图片, extra_images)
    if inferred_threshold is not None:
        阈值 = inferred_threshold
    params = dict(defaults or {})
    params["image_path"] = str(images[0] if images else 图片 or "")
    params["_script_images"] = images
    params["confidence"] = float(阈值)
    params["enable_click"] = _as_bool(点击)
    try:
        params["template_scale"] = max(0.25, min(4.0, float(缩放)))
    except (TypeError, ValueError):
        raise ValueError("图像缩放必须是 0.25 到 4 的数字")
    mode = str(图像模式 or "彩色").strip()
    if mode.casefold() not in {"彩色", "灰度", "gray", "grey", "grayscale"}:
        raise ValueError("图像模式只能是 彩色 或 灰度")
    params["image_mode"] = "灰度" if mode.casefold() in {"灰度", "gray", "grey", "grayscale"} else "彩色"
    raw_angles = 旋转 if isinstance(旋转, (list, tuple, set)) else [旋转]
    angles = []
    try:
        for raw_angle in raw_angles:
            angle = float(raw_angle or 0)
            if not math.isfinite(angle) or angle < -180 or angle > 180:
                raise ValueError
            if all(abs(angle - old) > 1e-6 for old in angles):
                angles.append(angle)
    except (TypeError, ValueError) as exc:
        raise ValueError("图像旋转必须是 -180 到 180 的数字") from exc
    params["image_rotation"] = angles if isinstance(旋转, (list, tuple, set)) else (angles[0] if angles else 0.0)
    params.update(
        build_click_style_params(
            双击=双击,
            偏移横坐标=偏移横坐标,
            偏移纵坐标=偏移纵坐标,
            随机=随机,
            随机横坐标=随机横坐标,
            随机纵坐标=随机纵坐标,
            动作=动作,
            次数=次数,
            间隔=间隔,
            按住秒=按住秒,
            自动松开=自动松开,
        )
    )
    region = _as_region(区域)
    if region:
        left, top, width, height = region
        params["use_recognition_region"] = True
        params["recognition_region_x"] = left
        params["recognition_region_y"] = top
        params["recognition_region_width"] = width
        params["recognition_region_height"] = height
    return params


def build_click_params(
    x: Any = None,
    y: Any = None,
    键: Any = "左键",
    last: Optional[Dict[str, Any]] = None,
    defaults: Optional[Dict[str, Any]] = None,
    双击: Any = False,
    偏移横坐标: Any = 0,
    偏移纵坐标: Any = 0,
    偏移x: Any = None,
    偏移y: Any = None,
    随机: Any = None,
    随机横坐标: Any = None,
    随机纵坐标: Any = None,
    动作: Any = None,
    次数: Any = None,
    间隔: Any = None,
    按住秒: Any = None,
    自动松开: Any = None,
) -> Dict[str, Any]:
    偏移横坐标, 偏移纵坐标 = _offset_alias(偏移x, 偏移y, 偏移横坐标, 偏移纵坐标)
    params = dict(defaults or {})
    payload = last or {}
    if x is None and y is None and payload.get("ok") is False:
        raise ValueError("点击缺少坐标，请传入横坐标、纵坐标或先找图")
    resolved_x = payload.get("x") if x is None else x
    resolved_y = payload.get("y") if y is None else y
    if resolved_x is None or resolved_y is None:
        raise ValueError("点击缺少坐标，请传入横坐标、纵坐标或先找图")
    if isinstance(resolved_x, str) and y is None and not _is_number_like(resolved_x):
        raise ValueError('文字请用 点文字("...")，坐标请传入数字或找图结果')
    params["operation_mode"] = "坐标点击"
    params["coordinate_source_mode"] = "手动输入"
    params["coordinate_x"] = int(resolved_x)
    params["coordinate_y"] = int(resolved_y)
    params["coordinate_enable_click"] = True
    params["button"] = str(键 or "左键")
    params.update(
        build_click_style_params(
            双击=双击,
            偏移横坐标=偏移横坐标,
            偏移纵坐标=偏移纵坐标,
            随机=随机,
            随机横坐标=随机横坐标,
            随机纵坐标=随机纵坐标,
            动作=动作,
            次数=次数,
            间隔=间隔,
            按住秒=按住秒,
            自动松开=自动松开,
        )
    )
    return params


def build_move_params(
    start_x: Any,
    start_y: Any,
    end_x: Any,
    end_y: Any,
    defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    params = dict(defaults or {})
    params["operation_mode"] = "鼠标移动"
    params["move_mode"] = "绝对移动"
    params["move_start_position"] = f"{int(start_x)},{int(start_y)}"
    params["move_end_position"] = f"{int(end_x)},{int(end_y)}"
    params["move_enable_click"] = False
    return params


def build_relative_move_params(
    offset_x: Any,
    offset_y: Any,
    defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    params = dict(defaults or {})
    params["operation_mode"] = "鼠标移动"
    params["move_mode"] = "相对移动"
    params["move_offset_mode"] = "固定偏移"
    params["move_offset_x"] = _as_int(offset_x, 0)
    params["move_offset_y"] = _as_int(offset_y, 0)
    params["move_enable_click"] = False
    return params


def _format_hold_wait(seconds: float) -> str:
    text = f"{max(0.0, float(seconds)):.6f}".rstrip("0").rstrip(".")
    return text or "0"


def build_hold_key_sequence(按键内容: Any, 秒: Any) -> str:
    text = str(按键内容 or "").strip()
    wait_text = _format_hold_wait(_as_duration(秒, 0.5))
    chord = text.replace("＋", "+")
    if "+" in chord and "(" not in text:
        keys = [part.strip() for part in chord.split("+") if part.strip()]
        if len(keys) >= 2:
            downs = ", ".join(f"{key}(按下)" for key in keys)
            ups = ", ".join(f"{key}(松开)" for key in reversed(keys))
            return f"{downs}, wait({wait_text}), {ups}"
    return f"{text}(按下), wait({wait_text}), {text}(松开)"


def build_key_params(
    按键内容: Any,
    defaults: Optional[Dict[str, Any]] = None,
    动作: Any = None,
) -> Dict[str, Any]:
    params = dict(defaults or {})
    params["input_type"] = "键盘按键"
    params["combo_key_sequence_text"] = str(按键内容 or "")
    raw = str(动作 or "").strip()
    if raw in {"仅按下", "按下", "只按下"}:
        params["combo_key_action"] = "只按下"
    elif raw in {"仅松开", "松开", "弹起", "释放", "只释放"}:
        params["combo_key_action"] = "只释放"
    return params


def build_type_params(
    文本: Any,
    defaults: Optional[Dict[str, Any]] = None,
    方式: Any = None,
) -> Dict[str, Any]:
    params = dict(defaults or {})
    params["input_type"] = "文本输入"
    params["text_input_mode"] = "单组文本"
    params["text_to_type"] = str(文本 or "")
    method = str(方式 or params.get("foreground_text_method") or "仿真输入").strip()
    if method in {"粘贴", "复制粘贴", "clipboard", "paste"}:
        params["foreground_text_method"] = "复制粘贴"
    else:
        params["foreground_text_method"] = "仿真输入"
    return params


_KEY_CN_ALIASES = {
    "空格": "space",
    "回车": "enter",
    "换行": "enter",
    "退出": "esc",
    "逃脱": "esc",
    "删除": "delete",
    "退格": "backspace",
    "上": "up",
    "下": "down",
    "左": "left",
    "右": "right",
}


def _script_key_vks(name: Any) -> list:
    from utils.input.normal_hd_driver import resolve_virtual_key

    text = str(name or "").strip()
    if not text:
        raise ValueError('等按键要写按键，例如 等按键("F1")')
    parts = [part.strip() for part in text.replace("＋", "+").split("+") if part.strip()]
    vks = []
    for part in parts:
        mapped = _KEY_CN_ALIASES.get(part) or _KEY_CN_ALIASES.get(part.lower()) or part
        vk = resolve_virtual_key(mapped)
        if vk is None:
            vk = resolve_virtual_key(str(mapped).lower())
        if vk is None:
            raise ValueError(f"不认识这个按键: {part}")
        vks.append(int(vk))
    return vks


def build_delay_params(秒: Any, defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    params = dict(defaults or {})
    params["delay_mode"] = "固定延迟"
    params["fixed_delay"] = float(秒)
    return params


def build_ocr_params(
    目标: Any = None,
    区域: Any = None,
    defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    params = dict(defaults or {})
    params["region_mode"] = "整个窗口"
    params["force_save_ocr_context"] = True
    if 目标:
        params["target_text"] = str(目标)
        params["text_recognition_mode"] = "单组文字"
    region = _as_region(区域)
    if region:
        left, top, width, height = region
        params["region_mode"] = "指定区域"
        params["region_x"] = int(left)
        params["region_y"] = int(top)
        params["region_width"] = int(width)
        params["region_height"] = int(height)
    return params


def build_dict_ocr_params(
    目标: Any = None,
    字库: Any = None,
    颜色: Any = None,
    相似度: Any = None,
    区域: Any = None,
    defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    params = dict(defaults or {})
    params["region_mode"] = "整个窗口"
    params["force_save_ocr_context"] = True
    if 目标:
        params["target_text"] = str(目标)
    if 字库:
        params["dict_file"] = str(字库)
    if 颜色 is not None:
        params["color_format"] = str(颜色)
    if 相似度 is not None:
        params["similarity"] = float(相似度)
    region = _as_region(区域)
    if region:
        left, top, width, height = region
        params["region_mode"] = "指定区域"
        params["region_x"] = int(left)
        params["region_y"] = int(top)
        params["region_width"] = int(width)
        params["region_height"] = int(height)
    return params


_YOLO_STRATEGIES = frozenset({"最近", "最大", "置信度最高"})


def _as_yolo_strategy(策略: Any) -> Optional[str]:
    text = str(策略 or "").strip()
    if not text:
        return None
    if text not in _YOLO_STRATEGIES:
        raise ValueError("策略只能是 最近、最大 或 置信度最高")
    return text


def _looks_like_model_path(模型: Any) -> bool:
    from task_workflow.resource_path import unwrap_resource_path

    text = unwrap_resource_path(模型) or ""
    if not text:
        return False
    lower = text.lower()
    return lower.endswith(".onnx") or "/" in text or "\\" in text


def resolve_yolo_model(
    模型: Any = None,
    defaults: Optional[Dict[str, Any]] = None,
) -> str:
    from task_workflow.resource_path import unwrap_resource_path

    model = unwrap_resource_path(模型) or ""
    if not model:
        model = unwrap_resource_path((defaults or {}).get("model_path")) or ""
    if not model:
        raise ValueError('检测要写模型，例如 检测("yolo/xxx.onnx")')
    if not _looks_like_model_path(model):
        raise ValueError('检测的模型要写成 onnx 路径，例如 "yolo/xxx.onnx"。类别写成 类别="敌人"')
    return model


def build_yolo_params(
    类别: Any = None,
    阈值: Any = 0.5,
    defaults: Optional[Dict[str, Any]] = None,
    区域: Any = None,
    策略: Any = None,
    模型: Any = None,
    后端: Any = None,
) -> Dict[str, Any]:
    from task_workflow.yolo_backend import normalize_yolo_backend

    params = dict(defaults or {})
    backend = normalize_yolo_backend(后端 if 后端 is not None else params.get("yolo_backend"))
    params["yolo_backend"] = backend
    from task_workflow.resource_path import unwrap_resource_path

    model = unwrap_resource_path(模型) or unwrap_resource_path(params.get("model_path")) or ""
    if model:
        params["model_path"] = model
    params["confidence_threshold"] = float(阈值)
    params["target_classes"] = str(类别) if 类别 else "全部类别"
    strategy = _as_yolo_strategy(策略)
    if strategy:
        params["target_selection"] = strategy
    region = _as_region(区域)
    if region:
        left, top, width, height = region
        params["use_region"] = True
        params["region_x"] = left
        params["region_y"] = top
        params["region_width"] = width
        params["region_height"] = height
    return params


def _as_color(颜色: Any) -> str:
    if isinstance(颜色, (tuple, list)) and len(颜色) >= 3:
        return f"{int(颜色[0])},{int(颜色[1])},{int(颜色[2])}"
    return str(颜色 or "").strip()


def _apply_region(params: Dict[str, Any], 区域: Any, enabled_key: str, x_key: str, y_key: str, w_key: str, h_key: str) -> None:
    region = _as_region(区域)
    if not region:
        return
    left, top, width, height = region
    params[enabled_key] = True
    params[x_key] = left
    params[y_key] = top
    params[w_key] = width
    params[h_key] = height


def build_find_color_params(
    颜色: Any,
    点击: Any = False,
    区域: Any = None,
    defaults: Optional[Dict[str, Any]] = None,
    双击: Any = False,
    偏移横坐标: Any = 0,
    偏移纵坐标: Any = 0,
    偏移x: Any = None,
    偏移y: Any = None,
    随机: Any = None,
    随机横坐标: Any = None,
    随机纵坐标: Any = None,
) -> Dict[str, Any]:
    偏移横坐标, 偏移纵坐标 = _offset_alias(偏移x, 偏移y, 偏移横坐标, 偏移纵坐标)
    params = dict(defaults or {})
    params["operation_mode"] = "找色功能"
    params["target_color"] = _as_color(颜色)
    params["color_enable_click"] = _as_bool(点击)
    params.update(
        build_click_style_params(
            双击=双击,
            偏移横坐标=偏移横坐标,
            偏移纵坐标=偏移纵坐标,
            随机=随机,
            随机横坐标=随机横坐标,
            随机纵坐标=随机纵坐标,
        )
    )
    _apply_region(
        params,
        区域,
        "search_region_enabled",
        "search_region_x",
        "search_region_y",
        "search_region_width",
        "search_region_height",
    )
    return params


def build_drag_params(
    x1: Any,
    y1: Any,
    x2: Any,
    y2: Any,
    defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    params = dict(defaults or {})
    params["operation_mode"] = "鼠标拖拽"
    params["drag_mode"] = "简单拖拽"
    params["drag_start_mode"] = "坐标"
    params["drag_end_mode"] = "坐标"
    params["drag_start_position"] = f"{int(x1)},{int(y1)}"
    params["drag_end_position"] = f"{int(x2)},{int(y2)}"
    return params


def build_scroll_params(
    方向: Any = "向下",
    步数: Any = 3,
    x: Any = None,
    y: Any = None,
    last: Optional[Dict[str, Any]] = None,
    defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    params = dict(defaults or {})
    direction = 方向
    steps = 步数
    if (
        y is None
        and x is not None
        and _is_number_like(方向)
        and _is_number_like(步数)
    ):
        y = x
        x = 步数
        steps = abs(int(方向))
        direction = "向上" if int(方向) < 0 else "向下"
    elif isinstance(方向, (int, float)) and not isinstance(方向, bool):
        steps = abs(int(方向))
        direction = "向上" if int(方向) < 0 else "向下"
    params["operation_mode"] = "鼠标滚轮"
    params["scroll_direction"] = str(direction or "向下")
    params["scroll_clicks"] = max(1, int(steps))
    payload = last or {}
    resolved_x = payload.get("x") if x is None else x
    resolved_y = payload.get("y") if y is None else y
    if resolved_x is not None and resolved_y is not None:
        params["scroll_start_position"] = f"{int(resolved_x)},{int(resolved_y)}"
    return params


def build_text_click_params(
    点击: Any = True,
    键: Any = "左键",
    defaults: Optional[Dict[str, Any]] = None,
    双击: Any = False,
    偏移横坐标: Any = 0,
    偏移纵坐标: Any = 0,
    偏移x: Any = None,
    偏移y: Any = None,
    随机: Any = None,
    随机横坐标: Any = None,
    随机纵坐标: Any = None,
) -> Dict[str, Any]:
    偏移横坐标, 偏移纵坐标 = _offset_alias(偏移x, 偏移y, 偏移横坐标, 偏移纵坐标)
    params = dict(defaults or {})
    params["operation_mode"] = "文字点击"
    params["text_enable_click"] = _as_bool(点击)
    params["text_match_mode"] = "包含"
    params["button"] = str(键 or "左键")
    params.update(
        build_click_style_params(
            双击=双击,
            偏移横坐标=偏移横坐标,
            偏移纵坐标=偏移纵坐标,
            随机=随机,
            随机横坐标=随机横坐标,
            随机纵坐标=随机纵坐标,
        )
    )
    return params


def _parse_rgb(颜色: Any) -> Optional[Tuple[int, int, int]]:
    if isinstance(颜色, (tuple, list)) and len(颜色) >= 3:
        return int(颜色[0]), int(颜色[1]), int(颜色[2])
    text = str(颜色 or "").strip()
    if not text:
        return None
    first = text.split("|", 1)[0]
    parts = [part.strip() for part in first.replace("，", ",").split(",") if part.strip()]
    if len(parts) < 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except Exception:
        return None


def colors_match(left: Any, right: Any, 偏色: Any = 20) -> bool:
    a = _parse_rgb(left)
    b = _parse_rgb(right)
    if a is None or b is None:
        return False
    tolerance = max(0, _as_int(偏色, 20))
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


def _looks_like_key(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    if any(mark in text for mark in {".", "/", "\\"}):
        return False
    if "," in text:
        return _parse_rgb(text) is None
    return True


def _color_payload(rgb: Tuple[int, int, int], x: Any = None, y: Any = None, ok: bool = True) -> Dict[str, Any]:
    red, green, blue = rgb
    color = f"{red},{green},{blue}"
    payload = {
        "ok": bool(ok),
        "kind": "pixel",
        "color": color,
        "text": color,
        "r": red,
        "g": green,
        "b": blue,
    }
    if x is not None:
        payload["x"] = int(x)
    if y is not None:
        payload["y"] = int(y)
    return payload


def _read_pixel_color(hwnd: Any, x: int, y: int) -> Optional[Tuple[int, int, int]]:
    handle = int(hwnd or 0)
    if handle <= 0:
        return None
    try:
        from utils.capture.screenshot_helper import get_window_pixel_color

        rgb = get_window_pixel_color(handle, int(x), int(y), True)
        if rgb and len(rgb) >= 3:
            return int(rgb[0]), int(rgb[1]), int(rgb[2])
    except Exception:
        return None
    return None


def _load_template_image(path: Any, card_id: Any = None):
    text = str(path or "").strip()
    if not text:
        return None, ""
    try:
        from tasks.task_utils import correct_single_image_path, safe_imread
        import cv2

        absolute = correct_single_image_path(text, card_id)
        if not absolute:
            return None, text
        image = safe_imread(absolute, flags=cv2.IMREAD_UNCHANGED)
        return image, absolute
    except Exception:
        return None, text


def _capture_window_frame(hwnd: Any):
    handle = int(hwnd or 0)
    if handle <= 0:
        return None
    try:
        from utils.capture.screenshot_helper import capture_window_frame

        return capture_window_frame(handle, client_area_only=True)
    except Exception:
        return None


def build_element_click_params(
    名称: Any,
    点击: Any = True,
    defaults: Optional[Dict[str, Any]] = None,
    自动化ID: Any = None,
    类名: Any = None,
    控件类型: Any = None,
    序号: Any = 0,
    搜索深度: Any = 30,
    超时: Any = 5.0,
    调用: Any = True,
    按钮: Any = "左键",
) -> Dict[str, Any]:
    params = dict(defaults or {})
    params["operation_mode"] = "元素点击"
    params["element_name"] = str(名称 or "")
    params["element_automation_id"] = str(自动化ID or "")
    params["element_class_name"] = str(类名 or "")
    params["element_control_type"] = str(控件类型 or "")
    params["element_found_index"] = max(0, _as_int(序号, 0))
    params["element_search_depth"] = max(1, _as_int(搜索深度, 30))
    params["element_timeout"] = max(0.0, float(超时 or 0))
    params["element_use_invoke"] = _as_bool(调用)
    # Script commands must not silently switch from Invoke/UIA to a mouse
    # coordinate or Click() fallback when the requested pattern is missing.
    params["element_strict_invoke"] = True
    params["element_button"] = str(按钮 or "左键")
    params["element_enable_click"] = _as_bool(点击)
    return params


class CommandHost:
    """把中文命令转到现有任务模块。"""

    def __init__(
        self,
        store: RuntimeStore,
        context: Optional[Dict[str, Any]] = None,
        logger_obj: Optional[logging.Logger] = None,
        modules: Optional[Dict[str, Any]] = None,
        invoke: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.store = store
        self.context = dict(context or {})
        self.logger = logger_obj or logger
        self._modules = modules
        self._invoke = invoke
        self._closed = False
        self._latest: Dict[str, Dict[str, Any]] = {}
        self._latest_lock = threading.Lock()
        self._watch_stops: Dict[str, threading.Event] = {}
        self._watch_threads: Dict[str, threading.Thread] = {}
        self._user_stops: Dict[str, threading.Event] = {}
        self._user_threads: Dict[str, threading.Thread] = {}
        self._user_idents: Dict[int, threading.Event] = {}
        self._thread_lock = threading.Lock()
        self._outer_stop = self.context.get("stop_checker")
        self._user_thread_errors: list[str] = []
        # Persistent, queryable state for user-created script threads.  The
        # thread/event maps above are lifecycle controls; this record is kept
        # after exit so a script can inspect the result or exception.
        self._user_thread_records: Dict[str, Dict[str, Any]] = {}
        self._external_component_manager = None
        self._script_hotkeys: Dict[str, Any] = {}
        self._replay_lock = threading.Lock()
        self._replay_stop = threading.Event()
        self._replay_pause = threading.Event()
        self._replay_thread: Optional[threading.Thread] = None
        self._replay_active = False
        self._regions: Dict[str, Tuple[int, int, int, int]] = {}
        self._regions_lock = threading.Lock()

    @staticmethod
    def _dm_memory_addr(value: Any) -> str:
        text = str(value or "").replace("\\", "/").strip()
        if not text:
            return ""
        if "-" in text and "/" in text:
            start, end = text.split("-", 1)
            return f"{CommandHost._dm_memory_addr_one(start)}-{CommandHost._dm_memory_addr_one(end)}"
        return CommandHost._dm_memory_addr_one(text)

    @staticmethod
    def _dm_memory_addr_one(text: str) -> str:
        body = str(text or "").replace("\\", "/").strip()
        if "/" not in body:
            return body
        leading = ""
        while body.startswith("["):
            leading += "["
            body = body[1:]
        plus = body.find("+")
        if plus >= 0:
            module, rest = body[:plus], body[plus:]
        else:
            module, rest = body, ""
        return leading + module.rsplit("/", 1)[-1] + rest

    def _dm_memory_call(self, operation: str, **arguments: Any) -> Any:
        from utils.plugin.bind_modes import normalize_plugin_bind_mode, normalize_plugin_keypad, normalize_plugin_mouse
        from utils.plugin.session import get_shared_plugin_client, plugin_bind_extras
        from utils.runtime_config import get_runtime_config

        for key in ("addr", "module", "range"):
            if key in arguments:
                arguments[key] = self._dm_memory_addr(arguments[key])
        if "instruction" in arguments:
            from task_workflow.script_resources import strip_plugin_module_prefix

            arguments["instruction"] = strip_plugin_module_prefix(arguments["instruction"])
        hwnd = int(self.context.get("target_hwnd") or 0)
        if hwnd <= 0:
            raise ValueError("大漠内存命令缺少当前目标窗口")
        cfg = get_runtime_config()
        public, fake_active = plugin_bind_extras(cfg)
        if "dx.public.memory" not in public.split("|"):
            raise ValueError("请先在插件公共属性中启用“突破内存防护”")
        display = str(cfg.get("plugin_input_display") or "").strip()
        if not display:
            raise ValueError("大漠内存命令缺少插件绑定图显")
        session = get_shared_plugin_client(hwnd)
        if not session.ensure_input_bind(
            hwnd, display,
            mouse=normalize_plugin_mouse(cfg.get("plugin_mouse")),
            keypad=normalize_plugin_keypad(cfg.get("plugin_keypad")),
            mode=normalize_plugin_bind_mode(cfg.get("plugin_bind_mode")),
            input_hwnd=hwnd, bind_extras=(public, fake_active),
        ):
            raise RuntimeError(f"大漠内存绑定失败：{session.last_bind_failure_text()}")
        return session._client.memory_call(operation, hwnd, **arguments)

    def 大漠内存_模块基址(self, 模块: Any) -> Any:
        return self._dm_memory_call("module_base", module=str(模块))

    def 大漠内存_模块大小(self, 模块: Any) -> Any:
        return self._dm_memory_call("module_size", module=str(模块))

    def 大漠内存_读取整数(self, 地址: Any, 类型: Any = 0) -> Any:
        return self._dm_memory_call("read_int", addr=str(地址), type=int(类型))

    def 大漠内存_读取单精度(self, 地址: Any) -> Any:
        return self._dm_memory_call("read_float", addr=str(地址))

    def 大漠内存_读取双精度(self, 地址: Any) -> Any:
        return self._dm_memory_call("read_double", addr=str(地址))

    def 大漠内存_读取文本(self, 地址: Any, 类型: Any, 长度: Any) -> Any:
        return self._dm_memory_call("read_string", addr=str(地址), type=int(类型), length=int(长度))

    def 大漠内存_读取数据(self, 地址: Any, 长度: Any) -> Any:
        return self._dm_memory_call("read_data", addr=str(地址), length=int(长度))

    def 大漠内存_写入整数(self, 地址: Any, 类型: Any, 值: Any) -> ScriptResult:
        raw = self._dm_memory_call("write_int", addr=str(地址), type=int(类型), value=int(值))
        return ScriptResult({"ok": bool(raw), "value": raw})

    def 大漠内存_写入单精度(self, 地址: Any, 值: Any) -> ScriptResult:
        raw = self._dm_memory_call("write_float", addr=str(地址), value=float(值))
        return ScriptResult({"ok": bool(raw), "value": raw})

    def 大漠内存_写入双精度(self, 地址: Any, 值: Any) -> ScriptResult:
        raw = self._dm_memory_call("write_double", addr=str(地址), value=float(值))
        return ScriptResult({"ok": bool(raw), "value": raw})

    def 大漠内存_写入文本(self, 地址: Any, 类型: Any, 值: Any) -> ScriptResult:
        raw = self._dm_memory_call("write_string", addr=str(地址), type=int(类型), value=str(值))
        return ScriptResult({"ok": bool(raw), "value": raw})

    def 大漠内存_写入数据(self, 地址: Any, 数据: Any) -> ScriptResult:
        raw = self._dm_memory_call("write_data", addr=str(地址), value=str(数据))
        return ScriptResult({"ok": bool(raw), "value": raw})

    def 大漠内存_搜索整数(self, 范围: Any, 最小值: Any, 最大值: Any, 类型: Any = 0) -> Any:
        return self._dm_memory_call("find_int", range=str(范围), min=int(最小值), max=int(最大值), type=int(类型))

    def 大漠内存_搜索单精度(self, 范围: Any, 最小值: Any, 最大值: Any) -> Any:
        return self._dm_memory_call("find_float", range=str(范围), min=float(最小值), max=float(最大值))

    def 大漠内存_搜索双精度(self, 范围: Any, 最小值: Any, 最大值: Any) -> Any:
        return self._dm_memory_call("find_double", range=str(范围), min=float(最小值), max=float(最大值))

    def 大漠内存_搜索文本(self, 范围: Any, 文本: Any, 类型: Any) -> Any:
        return self._dm_memory_call("find_string", range=str(范围), value=str(文本), type=int(类型))

    def 大漠内存_搜索数据(self, 范围: Any, 数据: Any) -> Any:
        return self._dm_memory_call("find_data", range=str(范围), value=str(数据))

    def 大漠内存_申请(self, 地址: Any, 大小: Any, 类型: Any) -> Any:
        return self._dm_memory_call("virtual_alloc", addr=str(地址), size=int(大小), allocation_type=int(类型))

    def 大漠内存_释放(self, 地址: Any) -> ScriptResult:
        raw = self._dm_memory_call("virtual_free", addr=str(地址))
        return ScriptResult({"ok": bool(raw), "value": raw})

    def 大漠内存_清理(self) -> ScriptResult:
        raw = self._dm_memory_call("free_process_memory")
        return ScriptResult({"ok": bool(raw), "value": raw})

    def 大漠汇编_添加(self, 指令: Any) -> ScriptResult:
        from task_workflow.script_resources import strip_plugin_module_prefix

        raw = self._dm_memory_call("asm_add", instruction=strip_plugin_module_prefix(指令))
        return ScriptResult({"ok": bool(raw), "value": raw})

    def 大漠汇编_清空(self) -> ScriptResult:
        raw = self._dm_memory_call("asm_clear")
        return ScriptResult({"ok": bool(raw), "value": raw})

    def 大漠汇编_调用(self, 模式: Any) -> Any:
        return self._dm_memory_call("asm_call", mode=int(模式))

    def 大漠汇编_基址调用(self, 模式: Any, 基址: Any) -> Any:
        return self._dm_memory_call("asm_call_ex", mode=int(模式), addr=str(基址))

    def 大漠汇编_超时(self, 毫秒: Any, 参数: Any) -> ScriptResult:
        raw = self._dm_memory_call("asm_timeout", timeout=int(毫秒), param=int(参数))
        return ScriptResult({"ok": bool(raw), "value": raw})

    def _resolve_region(self, 区域: Any) -> Optional[Tuple[int, int, int, int]]:
        if isinstance(区域, str):
            name = 区域.strip()
            with self._regions_lock:
                rect = self._regions.get(name) if name else None
            if rect is None:
                raise ValueError(f"没有这个区域: {name}")
            return rect
        return _as_region(区域)

    def _resource_dirs(self) -> Dict[str, str]:
        from task_workflow.resource_context import RESOURCE_DIR_KEYS, current_resource_dirs

        executor = self.context.get("executor")
        current = current_resource_dirs()
        dirs: Dict[str, str] = {}
        for key in RESOURCE_DIR_KEYS:
            value = self.context.get(key)
            text = str(value or "").strip()
            if not text and executor is not None:
                text = str(getattr(executor, key, "") or "").strip()
            dirs[key] = text or current[key]
        return dirs

    def _constrain_path(self, path: Any) -> str:
        from task_workflow.script_resources import constrain_script_path

        return constrain_script_path(str(path or ""), **self._resource_dirs())

    def _resolve_component_entry(self, path: Any) -> str:
        from task_workflow.script_resources import constrain_script_path, resolve_resource_path

        raw = str(path or "").strip()
        if not raw:
            raise ValueError("缺少组件入口")
        dirs = self._resource_dirs()
        relative = constrain_script_path(raw, **dirs)
        located = resolve_resource_path(relative, enforce_jail=True, **dirs)
        if located and os.path.isfile(located):
            return os.path.abspath(located)
        lowered = relative.replace("\\", "/").lower()
        if lowered.startswith("plugins/"):
            raise ValueError(f"找不到组件: {raw}")
        return relative

    def _run_parallel_images(
        self,
        images: List[str],
        params: Dict[str, Any],
        *,
        模式: Any,
        all_matches: bool,
    ) -> list:
        from tasks.parallel_image_recognition import RecognitionMode, get_parallel_recognizer

        hwnd = self.context.get("target_hwnd")
        if not hwnd:
            return []
        mode = RecognitionMode.ALL_MATCHES if all_matches else RecognitionMode.FIRST_MATCH
        execution_mode = self._resolve_input_mode(模式, self.context.get("execution_mode", "foreground"))
        results = get_parallel_recognizer().recognize_images_parallel(
            image_paths=list(images),
            params=params,
            execution_mode=execution_mode,
            target_hwnd=int(hwnd),
            mode=mode,
            get_image_data=self.context.get("get_image_data"),
            stop_checker=self.context.get("stop_checker"),
        )
        hits = [
            item
            for item in results
            if item.success and item.center_x is not None and item.center_y is not None
        ]
        hits.sort(key=lambda item: int(item.index))
        if not all_matches and hits:
            return [hits[0]]
        return hits

    def _publish_image_hits(self, hits: list, threshold: Any, items: Optional[list] = None) -> ScriptResult:
        first = hits[0] if hits else None
        payload = {
            "ok": bool(hits),
            "kind": "image",
            "x": None if first is None else int(first.center_x),
            "y": None if first is None else int(first.center_y),
            "score": None if first is None else float(first.confidence),
            "threshold": float(threshold or 0.8),
            "path": None if first is None else first.image_path,
        }
        if items is not None:
            payload["items"] = items
        try:
            self.store.publish(self.context.get("card_id"), **payload)
        except Exception:
            pass
        self._remember("image", payload)
        return ScriptResult(payload)

    @staticmethod
    def _resolve_input_mode(模式: Any, inherited: Any) -> str:
        """Resolve one explicit script input mode without silent mode fallback."""
        aliases = {
            "前台": "foreground_driver",
            "前台驱动": "foreground_driver",
            "前台脚本": "foreground_py",
            "后台": "background_sendmessage",
            "后台消息": "background_sendmessage",
            "后台发送": "background_sendmessage",
            "后台投递": "background_postmessage",
            "后台异步": "background_postmessage",
            "foreground": "foreground_driver",
            "foreground_driver": "foreground_driver",
            "foreground_py": "foreground_py",
            "background": "background_sendmessage",
            "background_sendmessage": "background_sendmessage",
            "background_postmessage": "background_postmessage",
        }
        selected = inherited if 模式 is None or str(模式).strip() == "" else 模式
        key = str(selected or "foreground").strip().lower()
        resolved = aliases.get(key) or aliases.get(str(selected).strip())
        if not resolved:
            raise ValueError("执行模式只能是 前台驱动、前台脚本、后台消息、后台投递")
        return resolved

    def 找图(
        self,
        图片: Any,
        *更多图片: Any,
        阈值: Any = 0.8,
        点击: Any = False,
        双击: Any = False,
        偏移横坐标: Any = 0,
        偏移纵坐标: Any = 0,
        偏移x: Any = None,
        偏移y: Any = None,
        随机: Any = None,
        随机横坐标: Any = None,
        随机纵坐标: Any = None,
        区域: Any = None,
        模式: Any = None,
        **kwargs: Any,
    ) -> ScriptResult:
        if kwargs:
            raise ValueError("找图不支持" + "、".join(str(name) for name in kwargs))
        偏移横坐标, 偏移纵坐标 = _offset_alias(偏移x, 偏移y, 偏移横坐标, 偏移纵坐标)
        params = build_find_image_params(
            图片,
            阈值,
            点击,
            self._defaults("图片点击"),
            双击=双击,
            偏移横坐标=偏移横坐标,
            偏移纵坐标=偏移纵坐标,
            随机=随机,
            随机横坐标=随机横坐标,
            随机纵坐标=随机纵坐标,
            区域=self._resolve_region(区域),
            extra_images=更多图片,
        )
        images = list(params.pop("_script_images", []) or [])
        if not images:
            images = [str(图片 or "")]
        images = [self._constrain_path(image) for image in images]
        if len(images) > 1:
            hits = self._run_parallel_images(images, params, 模式=模式, all_matches=False)
            result = self._publish_image_hits(hits, params.get("confidence", 0.8))
            if result and params.get("enable_click") and hits:
                first = hits[0]
                clicked = self._run(
                    "模拟鼠标操作",
                    build_click_params(
                        first.center_x,
                        first.center_y,
                        last={"ok": True, "x": first.center_x, "y": first.center_y},
                        defaults=self._defaults("模拟鼠标操作"),
                        双击=双击,
                        偏移横坐标=偏移横坐标,
                        偏移纵坐标=偏移纵坐标,
                        随机=随机,
                        随机横坐标=随机横坐标,
                        随机纵坐标=随机纵坐标,
                    ),
                    模式=模式,
                )
                if not clicked:
                    payload = dict(getattr(result, "_payload", {}) or {})
                    payload["ok"] = False
                    return ScriptResult(payload)
            return result
        last = ScriptResult(ok=False)
        for image in images:
            params["image_path"] = image
            last = self._run("图片点击", dict(params), 模式=模式)
            if last:
                return last
        return last

    def 点击(
        self,
        x: Any = None,
        y: Any = None,
        键: Any = "左键",
        横坐标: Any = None,
        纵坐标: Any = None,
        目标: Any = None,
        双击: Any = False,
        偏移横坐标: Any = 0,
        偏移纵坐标: Any = 0,
        偏移x: Any = None,
        偏移y: Any = None,
        随机: Any = None,
        随机横坐标: Any = None,
        随机纵坐标: Any = None,
        动作: Any = None,
        次数: Any = None,
        间隔: Any = None,
        按住秒: Any = None,
        自动松开: Any = None,
        模式: Any = None,
    ) -> ScriptResult:
        if 目标 is not None and x is None:
            x = 目标
        if 横坐标 is not None:
            x = 横坐标
        if 纵坐标 is not None:
            y = 纵坐标
        偏移横坐标, 偏移纵坐标 = _offset_alias(偏移x, 偏移y, 偏移横坐标, 偏移纵坐标)
        if isinstance(x, str) and y is None and 横坐标 is None and not _is_number_like(x):
            raise ValueError('文字请用 点文字("...")，坐标请传入数字或找图结果')
        target = resolve_xy(x, y)
        if target is not None:
            x, y = target
        return self._run(
            "模拟鼠标操作",
            build_click_params(
                x,
                y,
                键,
                self.store.last(),
                self._defaults("模拟鼠标操作"),
                双击=双击,
                偏移横坐标=偏移横坐标,
                偏移纵坐标=偏移纵坐标,
                随机=随机,
                随机横坐标=随机横坐标,
                随机纵坐标=随机纵坐标,
                动作=动作,
                次数=次数,
                间隔=间隔,
                按住秒=按住秒,
                自动松开=自动松开,
            ),
            模式=模式,
        )

    def 移动(
        self,
        x: Any = None,
        y: Any = None,
        横坐标: Any = None,
        纵坐标: Any = None,
        目标: Any = None,
        模式: Any = None,
    ) -> bool:
        target = resolve_xy(x, y, 横坐标, 纵坐标, 目标)
        if target is None:
            raise ValueError("移动缺少横坐标、纵坐标")
        end_x, end_y = target
        from tasks.mouse_action_task import _resolve_relative_move_start

        execution_mode = self._resolve_input_mode(模式, self.context.get("execution_mode", "foreground"))
        start_x, start_y = _resolve_relative_move_start(
            execution_mode,
            int(self.context.get("target_hwnd") or 0),
        )
        return self._run(
            "模拟鼠标操作",
            build_move_params(start_x, start_y, end_x, end_y, self._defaults("模拟鼠标操作")),
            模式=模式,
        )

    def 按键(
        self,
        按键内容: Any,
        秒: Any = None,
        动作: Any = None,
        模式: Any = None,
        连发: Any = None,
        间隔: Any = None,
    ) -> bool:
        action_text = str(动作 or "").strip()
        hold_actions = {"仅按下", "按下", "只按下", "仅松开", "松开", "弹起", "释放", "只释放"}
        if 连发 is not None and 秒 is None:
            raise ValueError("连发只在按住时有效，请同时写 秒=")
        if 间隔 is not None and 秒 is None:
            raise ValueError("间隔只在按住连发时有效，请同时写 秒=")
        if 连发 is not None and action_text in hold_actions:
            raise ValueError("连发不能和 动作=按下/松开 一起用")
        if 间隔 is not None and action_text in hold_actions:
            raise ValueError("间隔不能和 动作=按下/松开 一起用")
        if 秒 is not None and action_text not in hold_actions:
            params = build_key_params(
                build_hold_key_sequence(按键内容, 秒),
                self._defaults("模拟键盘操作"),
            )
            params["combo_key_action"] = "完整执行"
            params["combo_key_repeat"] = True if 连发 is None else _as_bool(连发)
            if 间隔 is not None:
                if not params["combo_key_repeat"]:
                    raise ValueError("间隔只在连发=真时有效")
                interval = float(间隔)
                if interval <= 0:
                    raise ValueError("间隔必须大于0")
                params["combo_key_repeat_interval"] = interval
            return self._run("模拟键盘操作", params, 模式=模式)
        return self._run("模拟键盘操作", build_key_params(按键内容, self._defaults("模拟键盘操作"), 动作=动作), 模式=模式)

    def 输入(self, 文本: Any, 方式: Any = None, 模式: Any = None) -> bool:
        return self._run("模拟键盘操作", build_type_params(文本, self._defaults("模拟键盘操作"), 方式=方式), 模式=模式)

    def 延时(self, 秒: Any) -> bool:
        if self._invoke is not None:
            return self._run("延迟", build_delay_params(秒, {}))
        return self._sleep_interruptible(float(秒))

    def _sleep_interruptible(self, seconds: float) -> ScriptResult:
        deadline = time.monotonic() + max(0.0, float(seconds))
        stop = self.context.get("stop_checker")
        pause = self.context.get("pause_checker")
        while True:
            now = time.monotonic()
            if callable(stop):
                try:
                    if stop():
                        raise ValueError("已停止")
                except ValueError:
                    raise
                except Exception as exc:
                    raise ValueError(f"停止检查失败: {exc}") from exc
            if now >= deadline:
                break
            if callable(pause):
                try:
                    paused = bool(pause())
                except Exception as exc:
                    raise ValueError(f"暂停检查失败: {exc}") from exc
                if paused:
                    time.sleep(0.05)
                    continue
            time.sleep(min(0.12, deadline - now))
        return ScriptResult({"ok": True, "kind": "delay"})

    def 找字(self, 目标: Any = None, 区域: Any = None) -> bool:
        return self._run(
            "OCR文字识别",
            build_ocr_params(目标, self._resolve_region(区域), self._defaults("OCR文字识别")),
        )

    def 找字库(
        self,
        目标: Any = None,
        字库: Any = None,
        颜色: Any = None,
        相似度: Any = None,
        区域: Any = None,
    ) -> bool:
        if 字库:
            字库 = self._constrain_path(字库)
        return self._run(
            "点阵字库OCR",
            build_dict_ocr_params(
                目标, 字库, 颜色, 相似度, self._resolve_region(区域), self._defaults("点阵字库OCR")
            ),
        )

    def 检测(
        self,
        模型: Any = None,
        类别: Any = None,
        阈值: Any = 0.5,
        区域: Any = None,
        策略: Any = None,
    ) -> bool:
        from task_workflow.yolo_backend import first_yolo_card_parameters, resolve_workflow_yolo_backend

        cards = self._workflow_cards()
        defaults = dict(self._defaults("YOLO目标检测"))
        defaults.update(first_yolo_card_parameters(cards))
        # An explicit model path is a complete standalone configuration.  A
        # YOLO card is still used for inherited defaults when one is present,
        # but it must not be required for the documented script-only form.
        try:
            backend = resolve_workflow_yolo_backend(cards)
        except ValueError:
            if not str(模型 or "").strip():
                raise
            backend = "原生"
        model = self._constrain_path(resolve_yolo_model(模型, defaults))
        return self._run(
            "YOLO目标检测",
            build_yolo_params(
                类别,
                阈值,
                defaults,
                区域=self._resolve_region(区域),
                策略=策略,
                模型=model,
                后端=backend,
            ),
        )

    def 框内点(self, 目标: Any, 横向: Any = 0.5, 纵向: Any = 0.5) -> ScriptResult:
        point = point_in_result(目标, 横向, 纵向)
        if point is None:
            raise ValueError("框内点缺少目标框")
        return ScriptResult({"ok": True, "kind": "point", "x": point[0], "y": point[1]})

    def 随机点(self, 目标: Any, 边距: Any = 2) -> ScriptResult:
        point = point_in_result(目标, 随机=True, 边距=边距)
        if point is None:
            raise ValueError("随机点缺少目标框")
        return ScriptResult({"ok": True, "kind": "point", "x": point[0], "y": point[1]})

    def 距离(self, 点1: Any, 点2: Any = None, x2: Any = None, y2: Any = None) -> int:
        points = _two_points(点1, 点2, x2, y2)
        if points is None:
            raise ValueError("距离缺少坐标")
        x1, y1, end_x, end_y = points
        dx = end_x - x1
        dy = end_y - y1
        return int(round((dx * dx + dy * dy) ** 0.5))

    def 角度(self, 点1: Any, 点2: Any = None, x2: Any = None, y2: Any = None) -> float:
        points = _two_points(点1, 点2, x2, y2)
        if points is None:
            raise ValueError("角度缺少坐标")
        x1, y1, end_x, end_y = points
        return math.degrees(math.atan2(end_y - y1, end_x - x1))

    def 等检测(
        self,
        模型: Any = None,
        类别: Any = None,
        超时: Any = 8,
        间隔: Any = 0.3,
        **kwargs: Any,
    ) -> ScriptResult:
        return self._wait_found(lambda: self.检测(模型, 类别, **kwargs), 超时, 间隔)

    def 等检测消失(
        self,
        模型: Any = None,
        类别: Any = None,
        超时: Any = 8,
        间隔: Any = 0.3,
        **kwargs: Any,
    ) -> ScriptResult:
        return self._wait_found(lambda: self.检测(模型, 类别, **kwargs), 超时, 间隔, 消失=True)

    def latest(self, kind: str) -> Optional[Dict[str, Any]]:
        with self._latest_lock:
            payload = self._latest.get(str(kind or ""))
            return dict(payload) if payload is not None else None

    def 持续检测(self, 模型: Any = None, 类别: Any = None, 间隔: Any = 0.3, **kwargs: Any) -> ScriptResult:
        from task_workflow.yolo_backend import first_yolo_card_parameters, resolve_workflow_yolo_backend

        cards = self._workflow_cards()
        defaults = dict(self._defaults("YOLO目标检测"))
        defaults.update(first_yolo_card_parameters(cards))
        try:
            resolve_workflow_yolo_backend(cards)
        except ValueError:
            if not str(模型 or "").strip():
                raise
        resolve_yolo_model(模型, defaults)
        self._start_watch(
            "yolo",
            间隔,
            lambda: self.检测(模型, 类别, **kwargs),
        )
        return ScriptResult({"ok": True, "kind": "watch"})

    def 停止检测(self) -> ScriptResult:
        self._stop_watch("yolo")
        return ScriptResult({"ok": True, "kind": "watch"})

    def 持续找图(self, 图片: Any, *更多图片: Any, 间隔: Any = 0.3, **kwargs: Any) -> ScriptResult:
        kwargs.pop("点击", None)
        kwargs.pop("双击", None)
        self._start_watch(
            "image",
            间隔,
            lambda: self.找图(图片, *更多图片, 点击=False, **kwargs),
        )
        return ScriptResult({"ok": True, "kind": "watch"})

    def 停止找图(self) -> ScriptResult:
        self._stop_watch("image")
        return ScriptResult({"ok": True, "kind": "watch"})

    def 多线程(self, 目标: Any, 名字: Any = None) -> ScriptResult:
        if self.should_stop():
            raise ValueError("已停止")
        func = 目标
        label = 名字
        if isinstance(目标, str):
            raise ValueError("多线程请传入子程序，例如 多线程(按W)")
        if not callable(func):
            raise ValueError("多线程请传入子程序，例如 多线程(按W)")
        name = str(label or getattr(func, "__name__", "") or "后台").strip() or "后台"
        with self._thread_lock:
            if self._closed:
                raise ValueError("已停止")
            current = self._user_threads.get(name)
            if current is not None and current.is_alive():
                raise ValueError(f"线程已在跑：{name}")
            active_count = sum(1 for thread in self._user_threads.values() if thread.is_alive())
            if active_count >= MAX_USER_THREADS:
                raise ValueError(f"脚本线程数已达上限（{MAX_USER_THREADS}）")
            stop = threading.Event()
            self._user_stops[name] = stop
            record: Dict[str, Any] = {
                "name": name,
                "status": "starting",
                "result": None,
                "error": "",
                "started_at": time.time(),
                "finished_at": None,
                "thread": None,
                "stop": stop,
            }
            self._user_thread_records[name] = record

            def runner() -> None:
                current_ident = threading.get_ident()
                with self._thread_lock:
                    self._user_idents[current_ident] = stop
                    record["status"] = "running"
                try:
                    value = func()
                    with self._thread_lock:
                        record["result"] = value
                        record["status"] = "stopped" if stop.is_set() else "completed"
                except Exception as exc:
                    if type(exc).__name__ == "ScriptOutcome":
                        with self._thread_lock:
                            record["error"] = str(getattr(exc, "detail", "") or "")
                            record["status"] = "completed" if bool(getattr(exc, "success", False)) else "stopped"
                        return
                    if _is_stop_error(exc):
                        with self._thread_lock:
                            record["error"] = str(exc) if str(exc) else ""
                            record["status"] = "stopped"
                        return
                    self.logger.warning("[自定义脚本] 线程%s失败: %s", name, exc)
                    with self._thread_lock:
                        record["error"] = str(exc)
                        record["status"] = "failed"
                        self._user_thread_errors.append(f"{name}: {exc}")
                finally:
                    with self._thread_lock:
                        if record.get("finished_at") is None:
                            record["finished_at"] = time.time()
                        self._user_idents.pop(current_ident, None)

            thread = threading.Thread(target=runner, name=f"lca-script-fn-{name}", daemon=True)
            record["thread"] = thread
            self._user_threads[name] = thread
            thread.start()
        return ScriptResult({"ok": True, "kind": "thread", "text": name})

    def _thread_payload(self, name: str, record: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Build a safe snapshot without exposing Thread/Event internals."""
        if record is None:
            return {"ok": False, "kind": "thread", "name": name, "status": "missing", "running": False,
                    "result": None, "error": "没有这个线程", "started_at": None, "finished_at": None}
        thread = record.get("thread")
        status = str(record.get("status") or "unknown")
        payload: Dict[str, Any] = {
            "ok": True,
            "kind": "thread",
            "name": name,
            "status": status,
            "running": bool(thread is not None and thread.is_alive()),
            "result": record.get("result"),
            "error": str(record.get("error") or ""),
            "started_at": record.get("started_at"),
            "finished_at": record.get("finished_at"),
        }
        return payload

    def 线程状态(self, 名字: Any = None) -> ScriptResult:
        """查询脚本线程状态；省略名字时返回全部线程。"""
        with self._thread_lock:
            if 名字 is None or str(名字).strip() == "":
                items = [self._thread_payload(key, value) for key, value in self._user_thread_records.items()]
                return ScriptResult({"ok": True, "kind": "thread_status", "items": items, "count": len(items)})
            name = str(getattr(名字, "__name__", "") or 名字).strip() or "后台"
            return ScriptResult(self._thread_payload(name, self._user_thread_records.get(name)))

    def 等待线程(self, 名字: Any, 超时: Any = None) -> ScriptResult:
        """等待指定脚本线程结束，并返回其状态、结果或异常。"""
        name = str(getattr(名字, "__name__", "") or 名字).strip() or "后台"
        with self._thread_lock:
            record = self._user_thread_records.get(name)
            thread = record.get("thread") if record else None
        if record is None:
            return ScriptResult(self._thread_payload(name, None))
        if thread is threading.current_thread():
            raise ValueError("线程不能等待自身")
        timeout = None if 超时 is None else float(超时)
        if timeout is not None and (not math.isfinite(timeout) or timeout < 0):
            raise ValueError("等待线程的超时必须是大于等于0的秒数")
        deadline = None if timeout is None else time.monotonic() + timeout
        while thread is not None and thread.is_alive():
            if self.should_stop():
                raise ValueError("已停止")
            self._wait_if_paused()
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                break
            thread.join(timeout=0.05 if remaining is None else min(0.05, remaining))
        with self._thread_lock:
            return ScriptResult(self._thread_payload(name, self._user_thread_records.get(name)))

    def 线程结果(self, 名字: Any) -> ScriptResult:
        """读取线程最近一次返回值及异常；不会阻塞。"""
        name = str(getattr(名字, "__name__", "") or 名字).strip() or "后台"
        with self._thread_lock:
            record = self._user_thread_records.get(name)
            payload = self._thread_payload(name, record)
        payload["kind"] = "thread_result"
        return ScriptResult(payload)

    def 关闭线程(self, 名字: Any = None) -> ScriptResult:
        if 名字 is None or 名字 == "":
            names = list(self._user_stops)
        elif callable(名字):
            names = [str(getattr(名字, "__name__", "") or "后台")]
        else:
            names = [str(名字).strip() or "后台"]
        for name in names:
            self._stop_user_thread(name)
        return ScriptResult({"ok": True, "kind": "thread"})

    def 注册热键(self, 按键: Any, 回调: Callable[[], Any], 名字: Any = None) -> ScriptResult:
        """Register a global keyboard hook owned by this script instance."""
        key = str(按键 or "").strip()
        if not key:
            raise ValueError("热键不能为空")
        if not callable(回调):
            raise ValueError("热键回调必须是子程序")
        try:
            import keyboard
        except Exception as exc:
            raise ValueError(f"热键 API 不可用: {exc}") from exc
        label = str(名字 or key).strip() or key
        self.注销热键(label)

        def on_hotkey() -> None:
            if self.should_stop():
                return
            try:
                回调()
            except Exception as exc:
                self.logger.warning("[自定义脚本] 热键%s回调失败: %s", label, exc)

        try:
            handle = keyboard.add_hotkey(key, on_hotkey, suppress=False)
        except Exception as exc:
            raise ValueError(f"注册热键失败: {exc}") from exc
        self._script_hotkeys[label] = handle
        return ScriptResult({"ok": True, "kind": "hotkey", "name": label, "key": key})

    def 注销热键(self, 名字: Any) -> bool:
        label = str(名字 or "").strip()
        handle = self._script_hotkeys.pop(label, None)
        if handle is None:
            return False
        try:
            import keyboard

            keyboard.remove_hotkey(handle)
        except Exception:
            self.logger.debug("注销脚本热键失败", exc_info=True)
        return True

    def 全部注销热键(self) -> int:
        labels = list(self._script_hotkeys)
        for label in labels:
            self.注销热键(label)
        return len(labels)

    def 启动定时器(self, 名字: Any, 间隔: Any, 回调: Callable[[], Any], 次数: Any = 0) -> ScriptResult:
        label = str(名字 or "定时器").strip() or "定时器"
        try:
            seconds = float(间隔)
            count = int(次数 or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("定时器间隔和次数必须是数字") from exc
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("定时器间隔必须大于 0")
        if count < 0:
            raise ValueError("定时器次数不能小于 0")
        thread_name = f"定时器:{label}"

        def runner() -> None:
            run_count = 0
            while count == 0 or run_count < count:
                self.延时(seconds)
                if self.should_stop():
                    return
                回调()
                run_count += 1

        return self.多线程(runner, thread_name)

    def 停止定时器(self, 名字: Any) -> ScriptResult:
        label = str(名字 or "定时器").strip() or "定时器"
        return self.关闭线程(f"定时器:{label}")

    def close(self) -> None:
        self._closed = True
        self.停止回放()
        for key in list(self._watch_stops):
            self._stop_watch(key, join=False)
        for name in list(self._user_stops):
            self._stop_user_thread(name, join=False)
        self.全部注销热键()
        for thread in list(self._watch_threads.values()) + list(self._user_threads.values()):
            if thread is not None and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=2.0)
        manager = self._external_component_manager
        self._external_component_manager = None
        if manager is not None:
            manager.shutdown()

    def _components(self):
        if not bool(self.context.get("allow_external_components", False)):
            raise ValueError("外部组件未在本机信任，请打开脚本编辑器勾选‘允许外部组件’")
        if self._external_component_manager is None:
            from task_workflow.external_components import ExternalComponentManager

            self._external_component_manager = ExternalComponentManager(stop_checker=self.should_stop)
        return self._external_component_manager

    @staticmethod
    def _component_handle(value: Any) -> str:
        payload = _payload_of(value)
        if payload is not None:
            value = payload.get("handle")
        handle = str(value or "").strip()
        if not handle:
            raise ValueError("外部组件缺少有效句柄")
        return handle

    @staticmethod
    def _component_result(value: Any, **extra: Any) -> ScriptResult:
        payload: Dict[str, Any] = {"ok": True, "kind": "component", "value": value, **extra}
        if isinstance(value, list):
            payload["items"] = value
        if isinstance(value, dict):
            payload.update({key: item for key, item in value.items() if key not in payload})
            if "exit_code" in value:
                payload["ok"] = int(value.get("exit_code") or 0) == 0
        return ScriptResult(payload)

    def 组件加载(
        self,
        类型: Any,
        入口: Any,
        调用约定: Any = "cdecl",
        超时: Any = 10,
    ) -> ScriptResult:
        entry = 入口
        raw_entry = str(入口 or "").strip()
        from task_workflow.script_resources import _is_module_offset_literal

        if _is_module_offset_literal(raw_entry):
            raise ValueError("这是模块地址，不能当外部组件加载")
        lowered = raw_entry.replace("\\", "/").lower()
        looks_like_resource = (
            lowered.startswith("plugins/")
            or lowered.endswith((".dll", ".py"))
            or (
                lowered.endswith(".exe")
                and not os.path.isabs(raw_entry)
                and "/" in lowered
            )
        )
        if looks_like_resource:
            entry = self._resolve_component_entry(入口)
        try:
            value = self._components().load(类型, entry, calling_convention=调用约定, timeout=超时)
        except Exception as exc:
            raise ValueError(f"外部组件加载失败: {exc}") from exc
        return self._component_result(value, handle=value.get("handle"), component_type=value.get("type"))

    def 组件调用(
        self,
        句柄: Any,
        方法: Any = "",
        *参数: Any,
        参数类型: Any = None,
        返回类型: Any = "int32",
        关键字参数: Any = None,
        超时: Any = 30,
        输入: Any = None,
        工作目录: Any = None,
        环境变量: Any = None,
        编码: Any = "utf-8",
    ) -> ScriptResult:
        handle = self._component_handle(句柄)
        if 关键字参数 is not None and not isinstance(关键字参数, dict):
            raise ValueError("外部组件关键字参数必须是字典")
        try:
            value = self._components().call(
                handle,
                方法,
                *参数,
                timeout=超时,
                kwargs=关键字参数,
                arg_types=参数类型,
                return_type=返回类型,
                stdin=输入,
                cwd=工作目录,
                env=环境变量,
                encoding=编码,
            )
        except Exception as exc:
            raise ValueError(f"外部组件调用失败: {exc}") from exc
        return self._component_result(value, handle=handle)

    def 组件读取(self, 句柄: Any, 属性: Any, 超时: Any = 30) -> ScriptResult:
        handle = self._component_handle(句柄)
        try:
            value = self._components().call(handle, 属性, timeout=超时, action="get")
        except Exception as exc:
            raise ValueError(f"外部组件读取失败: {exc}") from exc
        return self._component_result(value, handle=handle)

    def 组件写入(self, 句柄: Any, 属性: Any, 值: Any, 超时: Any = 30) -> ScriptResult:
        handle = self._component_handle(句柄)
        try:
            value = self._components().call(handle, 属性, 值, timeout=超时, action="set")
        except Exception as exc:
            raise ValueError(f"外部组件写入失败: {exc}") from exc
        return self._component_result(value, handle=handle)

    def 组件运行(
        self,
        程序: Any,
        *参数: Any,
        超时: Any = 30,
        输入: Any = None,
        工作目录: Any = None,
        环境变量: Any = None,
        编码: Any = "utf-8",
    ) -> ScriptResult:
        self._components()
        raw = str(程序 or "").strip()
        if raw.replace("\\", "/").lower().endswith(".dll"):
            raise ValueError('组件.运行只能运行程序（.exe）。DLL 请用 组件.加载("dll", 路径)')
        loaded = self.组件加载("process", 程序, 超时=min(10.0, float(超时 or 30)))
        handle = self._component_handle(loaded)
        try:
            result = self.组件调用(
                handle,
                "",
                *参数,
                超时=超时,
                输入=输入,
                工作目录=工作目录,
                环境变量=环境变量,
                编码=编码,
            )
        finally:
            try:
                self.组件关闭(handle)
            except Exception:
                pass
        return result

    def 组件关闭(self, 句柄: Any = None, 超时: Any = 5) -> ScriptResult:
        handle = None if 句柄 is None or 句柄 == "" else self._component_handle(句柄)
        try:
            count = self._components().close(handle, timeout=超时)
        except Exception as exc:
            raise ValueError(f"外部组件关闭失败: {exc}") from exc
        return self._component_result(count, handle=handle or "")

    def thread_failure(self) -> str:
        with self._thread_lock:
            return str(self._user_thread_errors[0]) if self._user_thread_errors else ""

    def _remember(self, kind: str, payload: Dict[str, Any]) -> None:
        if not kind:
            return
        with self._latest_lock:
            self._latest[kind] = dict(payload)

    def _start_watch(self, key: str, 间隔: Any, fn: Callable[[], Any]) -> None:
        self._stop_watch(key)
        interval = max(MIN_WATCH_INTERVAL, float(间隔 or 0.3))
        stop = threading.Event()
        self._watch_stops[key] = stop

        def loop() -> None:
            while not stop.is_set() and not self._closed:
                if self._is_stopped():
                    break
                self._wait_if_paused()
                if stop.is_set() or self._closed:
                    break
                try:
                    fn()
                except Exception as exc:
                    if _is_stop_error(exc) or type(exc).__name__ == "ScriptOutcome":
                        break
                    self.logger.warning("[自定义脚本] 后台%s失败: %s", key, exc)
                if stop.wait(interval):
                    break

        thread = threading.Thread(target=loop, name=f"lca-script-watch-{key}", daemon=True)
        self._watch_threads[key] = thread
        thread.start()

    def _stop_watch(self, key: str, join: bool = True) -> None:
        event = self._watch_stops.pop(key, None)
        if event is not None:
            event.set()
        thread = self._watch_threads.pop(key, None)
        if join and thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def _stop_user_thread(self, name: str, join: bool = True) -> None:
        # Keep the cancellation mapping until the runner actually exits.  A
        # timed-out join must never make a still-running worker lose its stop
        # event, or permit another worker with the same name to start.
        with self._thread_lock:
            event = self._user_stops.get(name)
            thread = self._user_threads.get(name)
            if event is not None:
                event.set()
            record = self._user_thread_records.get(name)
            if record is not None and thread is not None and thread.is_alive():
                record["status"] = "stopping"
        if join and thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def should_stop(self) -> bool:
        if self._closed:
            return True
        event = self._user_idents.get(threading.get_ident())
        if event is not None and event.is_set():
            return True
        checker = self._outer_stop
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception:
            return True

    def _is_stopped(self) -> bool:
        return self.should_stop()

    def _wait_if_paused(self) -> None:
        checker = self.context.get("pause_checker")
        if not callable(checker):
            return
        while True:
            if self._is_stopped():
                return
            try:
                paused = bool(checker())
            except Exception:
                return
            if not paused:
                return
            time.sleep(0.05)

    def 找色(
        self,
        颜色: Any,
        点击: Any = False,
        区域: Any = None,
        双击: Any = False,
        偏移横坐标: Any = 0,
        偏移纵坐标: Any = 0,
        偏移x: Any = None,
        偏移y: Any = None,
        随机: Any = None,
        随机横坐标: Any = None,
        随机纵坐标: Any = None,
        模式: Any = None,
    ) -> bool:
        偏移横坐标, 偏移纵坐标 = _offset_alias(偏移x, 偏移y, 偏移横坐标, 偏移纵坐标)
        return self._run(
            "模拟鼠标操作",
            build_find_color_params(
                颜色,
                点击,
                self._resolve_region(区域),
                self._defaults("模拟鼠标操作"),
                双击=双击,
                偏移横坐标=偏移横坐标,
                偏移纵坐标=偏移纵坐标,
                随机=随机,
                随机横坐标=随机横坐标,
                随机纵坐标=随机纵坐标,
            ),
            模式=模式,
        )

    def 拖拽(
        self,
        x1: Any = None,
        y1: Any = None,
        x2: Any = None,
        y2: Any = None,
        起点横坐标: Any = None,
        起点纵坐标: Any = None,
        终点横坐标: Any = None,
        终点纵坐标: Any = None,
        模式: Any = None,
    ) -> bool:
        if 起点横坐标 is not None:
            x1 = 起点横坐标
        if 起点纵坐标 is not None:
            y1 = 起点纵坐标
        if 终点横坐标 is not None:
            x2 = 终点横坐标
        if 终点纵坐标 is not None:
            y2 = 终点纵坐标
        drag = resolve_drag(x1, y1, x2, y2)
        if drag is None:
            raise ValueError("拖拽缺少起点或终点坐标")
        x1, y1, x2, y2 = drag
        return self._run(
            "模拟鼠标操作",
            build_drag_params(x1, y1, x2, y2, self._defaults("模拟鼠标操作")),
            模式=模式,
        )

    def 滚轮(
        self,
        目标: Any = None,
        方向: Any = "向下",
        步数: Any = 3,
        x: Any = None,
        y: Any = None,
        横坐标: Any = None,
        纵坐标: Any = None,
        模式: Any = None,
    ) -> bool:
        target = None
        direction = 方向
        steps = 步数
        if 目标 is not None and (result_coords(目标) is not None or result_box(目标) is not None):
            target = 目标
        elif _is_number_like(目标) and _is_number_like(方向) and _is_number_like(步数) and x is None and y is None:
            direction, x, y = 目标, 方向, 步数
            steps = 3
        elif _is_number_like(目标) and not _is_number_like(方向):
            direction = 目标
        elif isinstance(目标, str):
            direction = 目标
            if _is_number_like(方向):
                steps = 方向
        elif 目标 is not None:
            target = 目标
        point = resolve_xy(x, y, 横坐标, 纵坐标, target)
        if point is not None:
            x, y = point
        return self._run(
            "模拟鼠标操作",
            build_scroll_params(direction, steps, x, y, self.store.last(), self._defaults("模拟鼠标操作")),
            模式=模式,
        )

    def 点文字(
        self,
        目标: Any,
        点击: Any = True,
        键: Any = "左键",
        区域: Any = None,
        双击: Any = False,
        偏移横坐标: Any = 0,
        偏移纵坐标: Any = 0,
        偏移x: Any = None,
        偏移y: Any = None,
        随机: Any = None,
        随机横坐标: Any = None,
        随机纵坐标: Any = None,
        模式: Any = None,
    ) -> ScriptResult:
        found = self.找字(目标=目标, 区域=区域)
        if not found:
            return found if isinstance(found, ScriptResult) else ScriptResult(ok=False)
        偏移横坐标, 偏移纵坐标 = _offset_alias(偏移x, 偏移y, 偏移横坐标, 偏移纵坐标)
        return self._run(
            "模拟鼠标操作",
            build_text_click_params(
                点击,
                键,
                self._defaults("模拟鼠标操作"),
                双击=双击,
                偏移横坐标=偏移横坐标,
                偏移纵坐标=偏移纵坐标,
                随机=随机,
                随机横坐标=随机横坐标,
                随机纵坐标=随机纵坐标,
            ),
            模式=模式,
        )

    def 点字库(
        self,
        目标: Any,
        字库: Any = None,
        颜色: Any = None,
        相似度: Any = None,
        点击: Any = True,
        键: Any = "左键",
        区域: Any = None,
        双击: Any = False,
        偏移横坐标: Any = 0,
        偏移纵坐标: Any = 0,
        偏移x: Any = None,
        偏移y: Any = None,
        随机: Any = None,
        随机横坐标: Any = None,
        随机纵坐标: Any = None,
        模式: Any = None,
    ) -> ScriptResult:
        found = self.找字库(目标=目标, 字库=字库, 颜色=颜色, 相似度=相似度, 区域=区域)
        if not found:
            return found if isinstance(found, ScriptResult) else ScriptResult(ok=False)
        偏移横坐标, 偏移纵坐标 = _offset_alias(偏移x, 偏移y, 偏移横坐标, 偏移纵坐标)
        return self._run(
            "模拟鼠标操作",
            build_text_click_params(
                点击,
                键,
                self._defaults("模拟鼠标操作"),
                双击=双击,
                偏移横坐标=偏移横坐标,
                偏移纵坐标=偏移纵坐标,
                随机=随机,
                随机横坐标=随机横坐标,
                随机纵坐标=随机纵坐标,
            ),
            模式=模式,
        )

    def 点元素(
        self,
        名称: Any = None,
        点击: Any = True,
        自动化ID: Any = None,
        类名: Any = None,
        控件类型: Any = None,
        序号: Any = 0,
        搜索深度: Any = 30,
        超时: Any = 5.0,
        调用: Any = True,
        按钮: Any = "左键",
        模式: Any = None,
    ) -> bool:
        return self._run(
            "模拟鼠标操作",
            build_element_click_params(
                名称,
                点击,
                self._defaults("模拟鼠标操作"),
                自动化ID=自动化ID,
                类名=类名,
                控件类型=控件类型,
                序号=序号,
                搜索深度=搜索深度,
                超时=超时,
                调用=调用,
                按钮=按钮,
            ),
            模式=模式,
        )

    def 等图(
        self,
        图片: Any,
        *更多图片: Any,
        超时: Any = 8,
        间隔: Any = 0.3,
        **kwargs: Any,
    ) -> ScriptResult:
        return self._wait_found(lambda: self.找图(图片, *更多图片, **kwargs), 超时, 间隔)

    def 等色(
        self,
        颜色: Any,
        超时: Any = 8,
        间隔: Any = 0.3,
        **kwargs: Any,
    ) -> ScriptResult:
        return self._wait_found(lambda: self.找色(颜色, **kwargs), 超时, 间隔)

    def 等文字(
        self,
        目标: Any = None,
        超时: Any = 8,
        间隔: Any = 0.3,
        **kwargs: Any,
    ) -> ScriptResult:
        return self._wait_found(lambda: self.找字(目标=目标, **kwargs), 超时, 间隔)

    def 等图消失(
        self,
        图片: Any,
        *更多图片: Any,
        超时: Any = 8,
        间隔: Any = 0.3,
        **kwargs: Any,
    ) -> ScriptResult:
        return self._wait_found(lambda: self.找图(图片, *更多图片, **kwargs), 超时, 间隔, 消失=True)

    def 等色消失(
        self,
        颜色: Any,
        超时: Any = 8,
        间隔: Any = 0.3,
        **kwargs: Any,
    ) -> ScriptResult:
        return self._wait_found(lambda: self.找色(颜色, **kwargs), 超时, 间隔, 消失=True)

    def 等文字消失(
        self,
        目标: Any = None,
        超时: Any = 8,
        间隔: Any = 0.3,
        **kwargs: Any,
    ) -> ScriptResult:
        return self._wait_found(lambda: self.找字(目标=目标, **kwargs), 超时, 间隔, 消失=True)

    def 等字库(
        self,
        目标: Any = None,
        字库: Any = None,
        超时: Any = 8,
        间隔: Any = 0.3,
        **kwargs: Any,
    ) -> ScriptResult:
        return self._wait_found(
            lambda: self.找字库(目标=目标, 字库=字库, **kwargs),
            超时,
            间隔,
        )

    def 等字库消失(
        self,
        目标: Any = None,
        字库: Any = None,
        超时: Any = 8,
        间隔: Any = 0.3,
        **kwargs: Any,
    ) -> ScriptResult:
        return self._wait_found(
            lambda: self.找字库(目标=目标, 字库=字库, **kwargs),
            超时,
            间隔,
            消失=True,
        )

    def _wait_found(self, finder, 超时: Any, 间隔: Any, 消失: bool = False) -> ScriptResult:
        timeout = max(0.0, float(超时 if 超时 is not None else 8))
        deadline = time.monotonic() + timeout
        last = ScriptResult(ok=False)
        pause = max(0.05, float(间隔 if 间隔 is not None else 0.3))
        while True:
            last = finder()
            found = bool(last)
            if 消失 and not found:
                return ScriptResult({"ok": True, "kind": "wait"})
            if not 消失 and found:
                return last if isinstance(last, ScriptResult) else ScriptResult(ok=True)
            if time.monotonic() >= deadline:
                if 消失:
                    return ScriptResult({"ok": False, "kind": "wait"})
                return last if isinstance(last, ScriptResult) else ScriptResult(ok=False)
            self.延时(pause)

    def 按下(
        self,
        x: Any = None,
        y: Any = None,
        键: Any = "左键",
        横坐标: Any = None,
        纵坐标: Any = None,
        目标: Any = None,
        按键: Any = None,
        模式: Any = None,
        **kwargs: Any,
    ) -> ScriptResult:
        return self._press_or_release(
            "仅按下",
            x,
            y,
            键=键,
            横坐标=横坐标,
            纵坐标=纵坐标,
            目标=目标,
            按键=按键,
            自动松开=False,
            模式=模式,
            **kwargs,
        )

    def 松开(
        self,
        x: Any = None,
        y: Any = None,
        键: Any = "左键",
        横坐标: Any = None,
        纵坐标: Any = None,
        目标: Any = None,
        按键: Any = None,
        模式: Any = None,
        **kwargs: Any,
    ) -> ScriptResult:
        return self._press_or_release(
            "仅松开",
            x,
            y,
            键=键,
            横坐标=横坐标,
            纵坐标=纵坐标,
            目标=目标,
            按键=按键,
            模式=模式,
            **kwargs,
        )

    def 按住(
        self,
        x: Any = None,
        y: Any = None,
        秒: Any = 0.5,
        键: Any = "左键",
        横坐标: Any = None,
        纵坐标: Any = None,
        目标: Any = None,
        按键: Any = None,
        模式: Any = None,
        **kwargs: Any,
    ) -> ScriptResult:
        hold = _as_duration(秒, 0.5)
        key_name = 按键 if 按键 is not None else (x if y is None and 目标 is None and _looks_like_key(x) else None)
        if key_name is not None and y is None and 横坐标 is None:
            params = build_key_params(
                build_hold_key_sequence(key_name, hold),
                self._defaults("模拟键盘操作"),
            )
            params["combo_key_action"] = "完整执行"
            return self._run("模拟键盘操作", params, 模式=模式)
        return self._press_or_release(
            "仅按下",
            x,
            y,
            键=键,
            横坐标=横坐标,
            纵坐标=纵坐标,
            目标=目标,
            按住秒=hold,
            自动松开=True,
            模式=模式,
            **kwargs,
        )

    def 连点(
        self,
        x: Any = None,
        y: Any = None,
        次数: Any = 3,
        间隔: Any = 0.08,
        键: Any = "左键",
        横坐标: Any = None,
        纵坐标: Any = None,
        目标: Any = None,
        模式: Any = None,
        **kwargs: Any,
    ) -> ScriptResult:
        return self.点击(
            x,
            y,
            键=键,
            横坐标=横坐标,
            纵坐标=纵坐标,
            目标=目标,
            次数=次数,
            间隔=间隔,
            模式=模式,
            **kwargs,
        )

    def _press_or_release(
        self,
        动作: str,
        x: Any = None,
        y: Any = None,
        键: Any = "左键",
        横坐标: Any = None,
        纵坐标: Any = None,
        目标: Any = None,
        按键: Any = None,
        **kwargs: Any,
    ) -> ScriptResult:
        模式 = kwargs.pop("模式", None)
        key_name = 按键 if 按键 is not None else (x if y is None and 目标 is None and 横坐标 is None and _looks_like_key(x) else None)
        if key_name is not None:
            return self._run("模拟键盘操作", build_key_params(key_name, self._defaults("模拟键盘操作"), 动作=动作), 模式=模式)
        return self.点击(
            x,
            y,
            键=键,
            横坐标=横坐标,
            纵坐标=纵坐标,
            目标=目标,
            动作=动作,
            模式=模式,
            **kwargs,
        )

    def 取色(
        self,
        x: Any = None,
        y: Any = None,
        横坐标: Any = None,
        纵坐标: Any = None,
        目标: Any = None,
    ) -> ScriptResult:
        if 目标 is not None and x is None:
            x = 目标
        if 横坐标 is not None:
            x = 横坐标
        if 纵坐标 is not None:
            y = 纵坐标
        target = result_coords(x)
        if target is not None and y is None:
            x, y = target
        if x is None or y is None:
            last = self.store.last() or {}
            x = last.get("x") if x is None else x
            y = last.get("y") if y is None else y
        if x is None or y is None:
            raise ValueError("取色缺少横坐标、纵坐标")
        rgb = _read_pixel_color(self.context.get("target_hwnd"), int(x), int(y))
        if rgb is None:
            payload = _color_payload((0, 0, 0), x, y, ok=False)
        else:
            payload = _color_payload(rgb, x, y, ok=True)
        try:
            self.store.publish(self.context.get("card_id"), kind="click", ok=payload["ok"], x=x, y=y, text=payload.get("color"))
        except Exception:
            pass
        return ScriptResult(payload)

    def 比色(
        self,
        x: Any = None,
        y: Any = None,
        颜色: Any = None,
        偏色: Any = 20,
        横坐标: Any = None,
        纵坐标: Any = None,
        目标: Any = None,
    ) -> ScriptResult:
        expected = 颜色
        if expected is None and isinstance(x, str) and y is None and _parse_rgb(x) is not None:
            expected = x
            x = None
        if expected is None and y is not None and not _is_number_like(y) and _parse_rgb(y) is not None:
            expected = y
            y = None
        current = self.取色(x, y, 横坐标=横坐标, 纵坐标=纵坐标, 目标=目标)
        matched = bool(current) and colors_match(getattr(current, "color", None), expected, 偏色)
        payload = dict(getattr(current, "_payload", {}) or {})
        payload["ok"] = matched
        return ScriptResult(payload)

    def 找所有图(
        self,
        图片: Any,
        *更多图片: Any,
        阈值: Any = 0.8,
        最多: Any = 20,
        区域: Any = None,
        **kwargs: Any,
    ) -> ScriptResult:
        if kwargs:
            raise ValueError("找所有图不支持" + "、".join(str(name) for name in kwargs))
        images, inferred = collect_find_image_args(图片, 更多图片)
        threshold = float(inferred if inferred is not None else 阈值 or 0.8)
        region = self._resolve_region(区域)
        images = [self._constrain_path(image) for image in images if str(image or "").strip()]
        limit = max(1, _as_int(最多, 20))
        if len(images) > 1:
            params = build_find_image_params(
                images[0],
                threshold,
                False,
                区域=region,
                extra_images=tuple(images[1:]),
            )
            hits = self._run_parallel_images(images, params, 模式=None, all_matches=True)[:limit]
            items = [
                {
                    "ok": True,
                    "kind": "image",
                    "x": int(hit.center_x),
                    "y": int(hit.center_y),
                    "score": float(hit.confidence),
                    "threshold": threshold,
                    "path": hit.image_path,
                }
                for hit in hits
            ]
            return self._publish_image_hits(hits, threshold, items=items)
        items = []
        for image in images:
            items = self._collect_image_matches(image, threshold, region, limit)
            if items:
                break
        first = items[0] if items else {}
        payload = {
            "ok": bool(items),
            "kind": "image",
            "items": items,
            "x": first.get("x"),
            "y": first.get("y"),
            "score": first.get("score"),
            "threshold": threshold,
            "path": first.get("path"),
        }
        try:
            self.store.publish(self.context.get("card_id"), **payload)
        except Exception:
            pass
        return ScriptResult(payload)

    def _collect_image_matches(self, image: Any, threshold: float, region: Any, limit: int, 缩放: Any = 1.0, 图像模式: Any = "彩色", 旋转: Any = 0) -> list:
        params = build_find_image_params(image, threshold, False, 区域=region, 缩放=缩放, 图像模式=图像模式, 旋转=旋转)
        official = None
        path = str(image or "")
        try:
            from tasks.image_match_click import locate_image_in_window

            ok, loc, located_path = locate_image_in_window(
                params,
                self.context.get("target_hwnd"),
                self.context.get("card_id"),
            )
            if located_path:
                path = located_path
            if ok and loc:
                left, top, width, height = loc[0], loc[1], loc[2], loc[3]
                official = {
                    "ok": True,
                    "kind": "image",
                    "x": int(left + width // 2),
                    "y": int(top + height // 2),
                    "score": threshold,
                    "threshold": threshold,
                    "path": path,
                }
        except Exception:
            official = None
        extras = []
        template, loaded_path = _load_template_image(image, self.context.get("card_id"))
        if loaded_path:
            path = loaded_path
        frame = _capture_window_frame(self.context.get("target_hwnd"))
        if template is not None and frame is not None:
            try:
                from utils.match.smart_image_matcher import match_template_all, normalize_match_image
                import cv2

                needle = normalize_match_image(template)
                scale = float(params.get("template_scale", 1.0) or 1.0)
                if abs(scale - 1.0) > 1e-6 and needle is not None:
                    height, width = needle.shape[:2]
                    needle = cv2.resize(needle, (max(1, int(round(width * scale))), max(1, int(round(height * scale)))), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
                for match in match_template_all(frame, needle if needle is not None else template, threshold, region, limit, mode=params.get("image_mode", "彩色"), rotation=params.get("image_rotation", 0)):
                    if not match.found or not match.center:
                        continue
                    extras.append(
                        {
                            "ok": True,
                            "kind": "image",
                            "x": int(match.center[0]),
                            "y": int(match.center[1]),
                            "score": float(match.confidence),
                            "threshold": threshold,
                            "path": path,
                        }
                    )
            except Exception:
                extras = []
        items = []
        if official:
            items.append(official)
            for item in extras:
                if abs(int(item["x"]) - int(official["x"])) <= 8 and abs(int(item["y"]) - int(official["y"])) <= 8:
                    official["score"] = item.get("score", official["score"])
                    continue
                items.append(item)
        else:
            items = extras
        return items[: max(1, limit)]

    def 等毫秒(self, 毫秒: Any) -> bool:
        return self.延时(max(0.0, float(毫秒 or 0) / 1000.0))

    def 鼠标位置(self) -> ScriptResult:
        try:
            import win32api
            import win32gui

            screen_x, screen_y = win32api.GetCursorPos()
            hwnd = int(self.context.get("target_hwnd") or 0)
            if hwnd > 0:
                x, y = win32gui.ScreenToClient(hwnd, (int(screen_x), int(screen_y)))
            else:
                x, y = int(screen_x), int(screen_y)
        except Exception:
            return ScriptResult({"ok": False, "kind": "click"})
        payload = {"ok": True, "kind": "click", "x": int(x), "y": int(y)}
        try:
            self.store.publish(self.context.get("card_id"), **payload)
        except Exception:
            pass
        return ScriptResult(payload)

    def 相对移动(self, 偏移x: Any = 0, 偏移y: Any = 0) -> bool:
        return self._run(
            "模拟鼠标操作",
            build_relative_move_params(偏移x, 偏移y, self._defaults("模拟鼠标操作")),
        )

    def 客户区尺寸(self) -> Tuple[int, int]:
        hwnd = int(self.context.get("target_hwnd") or 0)
        if hwnd <= 0:
            return 0, 0
        try:
            import win32gui

            left, top, right, bottom = win32gui.GetClientRect(hwnd)
            return max(0, int(right - left)), max(0, int(bottom - top))
        except Exception:
            return 0, 0

    def 播放(self, 文件: Any, 等待: Any = True) -> ScriptResult:
        from task_workflow.media_player import play_audio

        # 先判空再做路径约束，否则用户看到的是笼统的“缺少资源路径”而不是这条命令的用法
        if not str(文件 or "").strip():
            raise ValueError('播放要写音频文件，例如 播放("提示.wav")')
        path = self._constrain_path(文件)
        if not path:
            raise ValueError('播放要写音频文件，例如 播放("提示.wav")')
        try:
            resolved = play_audio(
                path,
                wait=_as_bool(等待),
                stop_checker=self.context.get("stop_checker"),
            )
        except FileNotFoundError as exc:
            raise ValueError(str(exc)) from exc
        return ScriptResult({"ok": True, "kind": "audio", "path": resolved})

    def 停止播放(self) -> ScriptResult:
        from task_workflow.media_player import stop_audio

        stop_audio()
        return ScriptResult({"ok": True, "kind": "audio"})

    def 回放(self, 文件: Any, 速度: Any = 1.0, 次数: Any = 1, 等待: Any = True) -> ScriptResult:
        from task_workflow.script_resources import resolve_resource_path

        wait = _as_bool(等待)
        if isinstance(次数, bool) or not isinstance(次数, int) or 次数 < 1:
            raise ValueError("回放次数必须是大于等于 1 的整数")
        try:
            speed = 1.0 if 速度 is None else float(速度)
        except (TypeError, ValueError) as exc:
            raise ValueError("回放速度必须是数字") from exc
        raw = str(文件 or "").strip()
        if not raw:
            raise ValueError('回放要写文件，例如 回放("replays/过图.replay.json")')
        dirs = self._resource_dirs()
        relative = self._constrain_path(raw)
        absolute = resolve_resource_path(relative, enforce_jail=True, **dirs)
        if not absolute or not os.path.isfile(absolute):
            raise ValueError(f"回放文件不存在: {raw}")
        try:
            with open(absolute, encoding="utf-8") as handle:
                payload = json.loads(handle.read())
        except Exception as exc:
            raise ValueError(f"回放文件读不出来: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("actions"), list):
            raise ValueError("回放文件格式不对，需要含 actions")
        params = {
            "recorded_actions": json.dumps(payload, ensure_ascii=False),
            "speed": speed,
            "loop_count": 次数,
        }
        with self._replay_lock:
            if self._closed:
                raise ValueError("已停止")
            if self._replay_active:
                raise ValueError("回放正在进行")
            self._replay_stop.clear()
            self._replay_pause.clear()
            self._replay_active = True
            if wait:
                self._replay_thread = None
            else:
                thread = threading.Thread(
                    target=self._run_replay_background,
                    args=(params,),
                    name="lca-script-replay",
                    daemon=True,
                )
                self._replay_thread = thread
        if wait:
            try:
                return self._execute_replay(params)
            finally:
                self._end_replay()
        thread = self._replay_thread
        try:
            thread.start()
        except Exception:
            self._end_replay()
            raise
        return ScriptResult({"ok": True, "kind": "replay"})

    def 暂停回放(self) -> ScriptResult:
        with self._replay_lock:
            if not self._replay_active:
                return ScriptResult({"ok": False, "kind": "replay", "error": "回放未在进行"})
            self._replay_pause.set()
        return ScriptResult({"ok": True, "kind": "replay"})

    def 继续回放(self) -> ScriptResult:
        with self._replay_lock:
            if not self._replay_active:
                return ScriptResult({"ok": False, "kind": "replay", "error": "回放未在进行"})
            if not self._replay_pause.is_set():
                return ScriptResult({"ok": False, "kind": "replay", "error": "回放未暂停"})
            self._replay_pause.clear()
        return ScriptResult({"ok": True, "kind": "replay"})

    def 停止回放(self) -> ScriptResult:
        with self._replay_lock:
            if self._replay_active:
                self._replay_stop.set()
            thread = self._replay_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        return ScriptResult({"ok": True, "kind": "replay"})

    def _execute_replay(self, params: Dict[str, Any]) -> ScriptResult:
        return self._run(
            "录制回放",
            params,
            stop_checker=self._replay_stop_checker,
            pause_checker=self._replay_pause_checker,
        )

    def _run_replay_background(self, params: Dict[str, Any]) -> None:
        try:
            self._execute_replay(params)
        except Exception as exc:
            if _is_stop_error(exc) or type(exc).__name__ == "ScriptOutcome":
                return
            self.logger.warning("[自定义脚本] 回放失败: %s", exc)
        finally:
            self._end_replay()

    def _end_replay(self) -> None:
        with self._replay_lock:
            self._replay_active = False
            self._replay_thread = None
            self._replay_pause.clear()

    def _replay_stop_checker(self) -> bool:
        if self._closed or self._replay_stop.is_set():
            return True
        return self._call_optional_checker(self.context.get("stop_checker"))

    def _replay_pause_checker(self) -> bool:
        if self._replay_pause.is_set():
            return True
        return self._call_optional_checker(self.context.get("pause_checker"))

    @staticmethod
    def _call_optional_checker(checker: Any) -> bool:
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception:
            return True

    def 截图(self, 文件: Any = None) -> ScriptResult:
        from task_workflow.script_resources import constrain_script_path, script_path_for_file
        from utils.app_paths import get_images_dir

        frame = _capture_window_frame(self.context.get("target_hwnd"))
        if frame is None:
            return ScriptResult({"ok": False, "kind": "image"})
        dirs = dict(self._resource_dirs())
        root = str(dirs.get("images_dir") or "").strip() or get_images_dir("LCA")
        dirs["images_dir"] = root
        name = str(文件 or "").strip().replace("\\", "/")
        if not name:
            name = time.strftime("shot_%Y%m%d_%H%M%S.png")
        if not os.path.splitext(os.path.basename(name))[1]:
            name = f"{name}.png"
        target = name if os.path.isabs(name) else os.path.join(root, os.path.basename(name))
        dest = constrain_script_path(target, **dirs)
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        try:
            import cv2

            image = frame
            if getattr(image, "ndim", 0) == 3 and image.shape[2] == 4:
                image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
            wrote = bool(cv2.imwrite(dest, image))
        except Exception as exc:
            raise ValueError(f"截图保存失败: {exc}") from exc
        if not wrote:
            return ScriptResult({"ok": False, "kind": "image"})
        relative = script_path_for_file(dest, "image", **dirs)
        payload = {"ok": True, "kind": "image", "path": relative}
        try:
            self.store.publish(self.context.get("card_id"), **payload)
        except Exception:
            pass
        self._remember("image", payload)
        return ScriptResult(payload)

    def 等按键(self, 按键: Any, 超时: Any = 8, 间隔: Any = 0.05) -> ScriptResult:
        vks = _script_key_vks(按键)
        checker = self.context.get("key_down_checker")

        def _pressed() -> ScriptResult:
            if callable(checker):
                down = all(bool(checker(vk)) for vk in vks)
            else:
                import ctypes

                user32 = ctypes.windll.user32
                down = all(int(user32.GetAsyncKeyState(int(vk))) & 0x8000 for vk in vks)
            return ScriptResult({"ok": down, "kind": "key"})

        return self._wait_found(_pressed, 超时, 间隔)

    def 设置分辨率(self, *args: Any, 报错: Any = True) -> ScriptResult:
        from task_workflow.script_window_resolution import (
            ResolutionError,
            apply_window_resolution,
            default_adjust_window,
            parse_resolution_args,
        )

        try:
            call = parse_resolution_args(*args, 报错=报错)
            adjust = self.context.get("adjust_window_resolution") or default_adjust_window
            payload = apply_window_resolution(
                call=call,
                windows=self.context.get("bound_windows"),
                current_hwnd=self.context.get("target_hwnd"),
                global_size=(
                    int(self.context.get("custom_width") or 0),
                    int(self.context.get("custom_height") or 0),
                ),
                adjust=adjust,
            )
        except ResolutionError as exc:
            raise ValueError(str(exc)) from exc
        return ScriptResult(payload, ok=bool(payload.get("ok")))

    def _workflow_cards(self) -> Any:
        executor = self.context.get("executor")
        return getattr(executor, "cards_data", None) or {}

    def _defaults(self, task_type: str) -> Dict[str, Any]:
        return {}

    def _allowed(self, task_type: str) -> None:
        if task_type not in ALLOWED_TASK_TYPES or task_type in FORBIDDEN_TASK_TYPES:
            raise ValueError(f"不允许调用: {task_type}")

    def _module(self, task_type: str) -> Any:
        self._allowed(task_type)
        if self._modules is not None:
            module = self._modules.get(task_type)
            if module is None:
                raise ValueError(f"未找到能力: {task_type}")
            return module
        from tasks import get_task_module

        module = get_task_module(task_type)
        if module is None:
            raise ValueError(f"未找到能力: {task_type}")
        return module

    def _run(
        self,
        task_type: str,
        params: Dict[str, Any],
        模式: Any = None,
        stop_checker: Any = None,
        pause_checker: Any = None,
    ) -> ScriptResult:
        self._allowed(task_type)
        before = self.store.last()
        module = self._module(task_type)
        execution_mode = self._resolve_input_mode(模式, self.context.get("execution_mode", "foreground"))
        context = dict(self.context, execution_mode=execution_mode)
        if stop_checker is not None:
            context["stop_checker"] = stop_checker
        if pause_checker is not None:
            context["pause_checker"] = pause_checker
        if self._invoke is not None:
            result = self._invoke(task_type, params, context)
        else:
            execute = getattr(module, "execute_task", None)
            if not callable(execute):
                raise ValueError(f"能力不可执行: {task_type}")
            result = execute(
                params=params,
                counters=context.get("counters") if isinstance(context.get("counters"), dict) else {},
                execution_mode=execution_mode,
                target_hwnd=context.get("target_hwnd"),
                window_region=context.get("window_region"),
                card_id=context.get("card_id"),
                get_image_data=context.get("get_image_data"),
                stop_checker=context.get("stop_checker"),
                pause_checker=context.get("pause_checker"),
                executor=context.get("executor"),
            )
        ok = task_succeeded(result)
        self.logger.info("[自定义脚本] %s => %s", task_type, ok)
        after = self.store.last()
        # 即使底层任务发布的感知结果与上一次完全相同，也必须把完整结果
        # （尤其是找图的 x/y/path）返回给脚本。此前用字典相等判断“结果未变”，
        # 会把重复找同一位置的成功结果裁剪成仅含 ok=True，导致 `结果.x`
        # 抛出“没有字段: x”。
        changed = after != before
        # 感知类任务始终返回完整快照；重复识别同一目标时快照可能与上次
        # 字典相等，但坐标/文本等字段仍是本次调用的有效结果。普通动作
        # （延时、按键等）则不能沿用旧的感知字段。
        perception_task = task_type in {"图片点击", "OCR文字识别", "点阵字库OCR", "YOLO目标检测"}
        payload = dict(after) if (perception_task and ok) else {"ok": ok}
        payload["ok"] = ok
        payload["execution_mode"] = execution_mode
        kind = _KIND_BY_TASK.get(task_type) or str(payload.get("kind") or "")
        if kind:
            remembered = dict(after)
            remembered["ok"] = ok
            remembered.setdefault("kind", kind)
            if changed or remembered.get("x") is not None or remembered.get("items"):
                self._remember(kind, remembered)
            if changed:
                payload = remembered
        payload.setdefault("execution_mode", execution_mode)
        return ScriptResult(payload)
