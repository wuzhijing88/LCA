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
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional, Tuple

from task_workflow.runtime_store import RuntimeStore
from task_workflow.script_parameters import (
    boolean_parameter as _as_bool,
    finite_seconds,
    integer_parameter,
    number_parameter,
)

logger = logging.getLogger(__name__)

# 每个脚本宿主最多保留的用户线程数，避免长时间运行时无界创建线程耗尽资源。
MAX_THREAD_RECORDS = 256
MAX_THREAD_ERRORS = 256

RESULT_FIELD_ALIASES = {
    "通过": "ok",
    "输出": "outputs",
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
    "已启动": "started",
    "已完成": "completed",
    "已超时": "timed_out",
    "查询成功": "query_ok",
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
    "截断": "truncated",
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
    x = getattr(value, "x", None)
    y = getattr(value, "y", None)
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


def resolve_xy(
    x: Any = None,
    y: Any = None,
    目标: Any = None,
) -> Optional[Tuple[int, int]]:
    if 目标 is not None and x is None:
        x = 目标
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
    "OCR文字识别": "ocr",
    "点阵字库OCR": "ocr",
    "YOLO目标检测": "yolo",
}


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


def _as_duration(value: Any, default: float = 0.5, *, label: str = "时长") -> float:
    if value is None:
        return float(default)
    if isinstance(value, (tuple, list)) and len(value) == 2:
        low, high = finite_seconds(value[0], f"{label}起点"), finite_seconds(value[1], f"{label}终点")
        if high < low:
            raise ValueError(f"{label}终点不能小于起点")
        if low == high:
            return low
        return random.uniform(low, high)
    return finite_seconds(value, label)


def _as_int(value: Any, default: int = 0) -> int:
    if value is None:
        return int(default)
    return integer_parameter(value, "整数参数")


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
    if isinstance(区域, (tuple, list)) and len(区域) == 4:
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
    偏移x: Any = 0,
    偏移y: Any = 0,
    随机: Any = None,
    随机横坐标: Any = None,
    随机纵坐标: Any = None,
    动作: Any = None,
    次数: Any = None,
    间隔: Any = None,
    按住秒: Any = None,
    自动松开: Any = None,
) -> Dict[str, Any]:
    double = _as_bool(双击)
    fixed_x = integer_parameter(偏移x, "偏移x")
    fixed_y = integer_parameter(偏移y, "偏移y")
    random_range = 0 if 随机 is None else integer_parameter(随机, "随机", minimum=0)
    rand_x = random_range if 随机横坐标 is None else integer_parameter(随机横坐标, "随机横坐标", minimum=0)
    rand_y = random_range if 随机纵坐标 is None else integer_parameter(随机纵坐标, "随机纵坐标", minimum=0)
    if fixed_x or fixed_y:
        mode = "固定偏移"
    elif rand_x or rand_y:
        mode = "随机偏移"
    else:
        mode = "精准坐标"
    action = "双击" if double else "完整点击"
    raw_action = str(动作 or "").strip()
    if double and raw_action and raw_action != "双击":
        raise ValueError("双击=真不能与其他点击动作同时使用")
    if raw_action == "仅按下":
        action = "仅按下"
        double = False
    elif raw_action == "仅松开":
        action = "仅松开"
        double = False
    elif raw_action == "双击":
        action = "双击"
        double = True
    elif raw_action == "完整点击":
        action = "完整点击"
        double = False
    elif raw_action:
        raise ValueError("点击动作只能是 完整点击、双击、仅按下 或 仅松开")
    requested_count = 1 if 次数 is None else integer_parameter(次数, "次数", minimum=1)
    if double and 次数 is not None and requested_count != 2:
        raise ValueError("双击只支持次数=2；多次完整点击请省略双击")
    if action in {"仅按下", "仅松开"} and requested_count != 1:
        raise ValueError("仅按下或仅松开不支持重复次数")
    click_count = 2 if double else requested_count
    interval = 0.0 if 间隔 is None else finite_seconds(间隔, "间隔")
    hold = 0.0 if 按住秒 is None else _as_duration(按住秒, 0.0, label="按住秒")
    hold = finite_seconds(hold, "按住秒")
    if action == "仅松开" and (hold or interval):
        raise ValueError("仅松开不支持按住秒或间隔")
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


def collect_find_image_args(图片: Any, extra: Tuple[Any, ...] = ()) -> list:
    items = []
    if 图片 is not None:
        items.append(图片)
    items.extend(extra)
    images = []
    for item in items:
        if item is None:
            continue
        if isinstance(item, (list, tuple)) and not isinstance(item, (str, bytes)):
            images.extend(collect_find_image_args(None, tuple(item)))
            continue
        if not isinstance(item, str):
            raise ValueError("找图的图片必须是路径文本；阈值请使用阈值=参数")
        text = item.strip()
        if not text:
            continue
        images.extend(part.strip() for part in text.replace(";", "\n").splitlines() if part.strip())
    return images


def build_find_image_params(
    图片: Any,
    阈值: Any = 0.8,
    点击: Any = False,
    defaults: Optional[Dict[str, Any]] = None,
    双击: Any = False,
    偏移x: Any = 0,
    偏移y: Any = 0,
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
    images = collect_find_image_args(图片, extra_images)
    if not images:
        raise ValueError("找图至少需要一张图片")
    params = dict(defaults or {})
    params["image_path"] = str(images[0] if images else 图片 or "")
    params["_script_images"] = images
    params["confidence"] = float(number_parameter(阈值, "找图阈值"))
    if not 0 <= params["confidence"] <= 1:
        raise ValueError("找图阈值必须在0到1之间")
    params["enable_click"] = _as_bool(点击)
    try:
        scale = float(缩放)
        if not math.isfinite(scale):
            raise ValueError
        if not 0.25 <= scale <= 4.0:
            raise ValueError
        params["template_scale"] = scale
    except (TypeError, ValueError):
        raise ValueError("图像缩放必须是 0.25 到 4 的数字")
    mode = str(图像模式).strip()
    if mode not in {"彩色", "灰度"}:
        raise ValueError("图像模式只能是 彩色 或 灰度")
    params["image_mode"] = mode
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
            偏移x=偏移x,
            偏移y=偏移y,
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
    偏移x: Any = 0,
    偏移y: Any = 0,
    随机: Any = None,
    随机横坐标: Any = None,
    随机纵坐标: Any = None,
    动作: Any = None,
    次数: Any = None,
    间隔: Any = None,
    按住秒: Any = None,
    自动松开: Any = None,
) -> Dict[str, Any]:
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
            偏移x=偏移x,
            偏移y=偏移y,
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
    if raw == "按下":
        params["combo_key_action"] = "只按下"
    elif raw == "松开":
        params["combo_key_action"] = "只释放"
    elif raw:
        raise ValueError("按键动作只能是 按下 或 松开，省略动作时执行完整按键")
    return params


def build_type_params(
    文本: Any,
    defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    params = dict(defaults or {})
    params["input_type"] = "文本输入"
    params["text_input_mode"] = "单组文本"
    params["text_to_type"] = str(文本 or "")
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
    params["confidence_threshold"] = float(number_parameter(阈值, "检测阈值"))
    if not 0 <= params["confidence_threshold"] <= 1:
        raise ValueError("检测阈值必须在0到1之间")
    if 类别 is not None and not isinstance(类别, str):
        raise ValueError("检测类别必须是模型中的类别名称文本")
    params["target_classes"] = 类别.strip() if 类别 and 类别.strip() else "全部类别"
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
    偏移x: Any = 0,
    偏移y: Any = 0,
    随机: Any = None,
    随机横坐标: Any = None,
    随机纵坐标: Any = None,
) -> Dict[str, Any]:
    params = dict(defaults or {})
    params["operation_mode"] = "找色功能"
    params["target_color"] = _as_color(颜色)
    params["color_enable_click"] = _as_bool(点击)
    params.update(
        build_click_style_params(
            双击=双击,
            偏移x=偏移x,
            偏移y=偏移y,
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
        amount = integer_parameter(方向, "滚轮步数")
        if amount == 0:
            raise ValueError("滚轮步数不能为0")
        steps = abs(amount)
        direction = "向上" if amount < 0 else "向下"
    elif isinstance(方向, (int, float)) and not isinstance(方向, bool):
        amount = integer_parameter(方向, "滚轮步数")
        if amount == 0:
            raise ValueError("滚轮步数不能为0")
        steps = abs(amount)
        direction = "向上" if amount < 0 else "向下"
    params["operation_mode"] = "鼠标滚轮"
    if direction not in {"向上", "向下"}:
        raise ValueError("滚轮方向只能是向上或向下")
    params["scroll_direction"] = direction
    params["scroll_clicks"] = integer_parameter(steps, "滚轮步数", minimum=1)
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
    偏移x: Any = 0,
    偏移y: Any = 0,
    随机: Any = None,
    随机横坐标: Any = None,
    随机纵坐标: Any = None,
) -> Dict[str, Any]:
    params = dict(defaults or {})
    params["operation_mode"] = "文字点击"
    params["text_enable_click"] = _as_bool(点击)
    params["text_match_mode"] = "包含"
    params["button"] = str(键 or "左键")
    params.update(
        build_click_style_params(
            双击=双击,
            偏移x=偏移x,
            偏移y=偏移y,
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
    params["element_found_index"] = integer_parameter(序号, "序号", minimum=0)
    params["element_search_depth"] = integer_parameter(搜索深度, "搜索深度", minimum=1)
    params["element_timeout"] = finite_seconds(超时, "超时")
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
        self._owned_processes: Dict[int, Any] = {}
        self._process_lock = threading.Lock()

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

    @staticmethod
    def _dm_int(value: Any, label: str, minimum: Optional[int] = None) -> int:
        return integer_parameter(value, label, minimum=max(-2147483648, minimum) if minimum is not None else -2147483648, maximum=2147483647)

    @classmethod
    def _dm_address(cls, value: Any, label: str = "地址") -> str:
        if label == "模块":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("模块必须是已加载的模块名称文本")
            return value.strip()
        if isinstance(value, bool):
            raise ValueError(f"{label}必须是地址文本或非负整数")
        if isinstance(value, int):
            if value < 0 or value > 0x7FFFFFFFFFFFFFFF:
                raise ValueError(f"{label}超出非负 64 位整数范围")
            return format(value, "X")
        if not isinstance(value, str):
            raise ValueError(f"{label}必须是地址文本或非负整数")
        text = value.strip()
        if not text:
            raise ValueError(f"{label}不能为空")
        return text

    @classmethod
    def _dm_range(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text or "-" not in text:
            raise ValueError("范围必须是起始地址-结束地址")
        start, end = text.split("-", 1)
        if not start.strip() or not end.strip():
            raise ValueError("范围必须是起始地址-结束地址")
        return text

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
        return self._dm_memory_call("module_base", module=self._dm_address(模块, "模块"))

    def 大漠内存_模块大小(self, 模块: Any) -> Any:
        return self._dm_memory_call("module_size", module=self._dm_address(模块, "模块"))

    def 大漠内存_读取整数(self, 地址: Any, 类型: Any = 0) -> Any:
        return self._dm_memory_call("read_int", addr=self._dm_address(地址), type=self._dm_int(类型, "类型"))

    def 大漠内存_读取单精度(self, 地址: Any) -> Any:
        return self._dm_memory_call("read_float", addr=self._dm_address(地址))

    def 大漠内存_读取双精度(self, 地址: Any) -> Any:
        return self._dm_memory_call("read_double", addr=self._dm_address(地址))

    def 大漠内存_读取文本(self, 地址: Any, 类型: Any, 长度: Any) -> Any:
        return self._dm_memory_call("read_string", addr=self._dm_address(地址), type=self._dm_int(类型, "类型"), length=self._dm_int(长度, "长度", 1))

    def 大漠内存_读取数据(self, 地址: Any, 长度: Any) -> Any:
        return self._dm_memory_call("read_data", addr=self._dm_address(地址), length=self._dm_int(长度, "长度", 1))

    def 大漠内存_写入整数(self, 地址: Any, 类型: Any, 值: Any) -> ScriptResult:
        raw = self._dm_memory_call("write_int", addr=self._dm_address(地址), type=self._dm_int(类型, "类型"), value=self._dm_int(值, "值"))
        return ScriptResult({"ok": bool(raw), "value": raw})

    def 大漠内存_写入单精度(self, 地址: Any, 值: Any) -> ScriptResult:
        raw = self._dm_memory_call("write_float", addr=self._dm_address(地址), value=float(值))
        return ScriptResult({"ok": bool(raw), "value": raw})

    def 大漠内存_写入双精度(self, 地址: Any, 值: Any) -> ScriptResult:
        raw = self._dm_memory_call("write_double", addr=self._dm_address(地址), value=float(值))
        return ScriptResult({"ok": bool(raw), "value": raw})

    def 大漠内存_写入文本(self, 地址: Any, 类型: Any, 值: Any) -> ScriptResult:
        raw = self._dm_memory_call("write_string", addr=self._dm_address(地址), type=self._dm_int(类型, "类型"), value=str(值))
        return ScriptResult({"ok": bool(raw), "value": raw})

    def 大漠内存_写入数据(self, 地址: Any, 数据: Any) -> ScriptResult:
        raw = self._dm_memory_call("write_data", addr=self._dm_address(地址), value=str(数据))
        return ScriptResult({"ok": bool(raw), "value": raw})

    def 大漠内存_搜索整数(self, 范围: Any, 最小值: Any, 最大值: Any, 类型: Any = 0) -> Any:
        return self._dm_memory_call("find_int", range=self._dm_range(范围), min=self._dm_int(最小值, "最小值"), max=self._dm_int(最大值, "最大值"), type=self._dm_int(类型, "类型"))

    def 大漠内存_搜索单精度(self, 范围: Any, 最小值: Any, 最大值: Any) -> Any:
        return self._dm_memory_call("find_float", range=self._dm_range(范围), min=float(最小值), max=float(最大值))

    def 大漠内存_搜索双精度(self, 范围: Any, 最小值: Any, 最大值: Any) -> Any:
        return self._dm_memory_call("find_double", range=self._dm_range(范围), min=float(最小值), max=float(最大值))

    def 大漠内存_搜索文本(self, 范围: Any, 文本: Any, 类型: Any) -> Any:
        return self._dm_memory_call("find_string", range=self._dm_range(范围), value=str(文本), type=self._dm_int(类型, "类型"))

    def 大漠内存_搜索数据(self, 范围: Any, 数据: Any) -> Any:
        return self._dm_memory_call("find_data", range=self._dm_range(范围), value=str(数据))

    def 大漠内存_申请(self, 地址: Any, 大小: Any, 类型: Any) -> Any:
        return self._dm_memory_call("virtual_alloc", addr=self._dm_address(地址), size=self._dm_int(大小, "大小", 1), allocation_type=self._dm_int(类型, "类型"))

    def 大漠内存_释放(self, 地址: Any) -> ScriptResult:
        raw = self._dm_memory_call("virtual_free", addr=self._dm_address(地址))
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
        return self._dm_memory_call("asm_call", mode=self._dm_int(模式, "模式"))

    def 大漠汇编_基址调用(self, 模式: Any, 基址: Any) -> Any:
        return self._dm_memory_call("asm_call_ex", mode=self._dm_int(模式, "模式"), addr=self._dm_address(基址, "基址"))

    def 大漠汇编_超时(self, 毫秒: Any, 参数: Any) -> ScriptResult:
        raw = self._dm_memory_call("asm_timeout", timeout=self._dm_int(毫秒, "毫秒", 0), param=self._dm_int(参数, "参数"))
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

    def _resolve_component_entry(self, path: Any, component_type: Any = "") -> str:
        from task_workflow.script_resources import _is_module_offset_literal

        raw = os.path.expandvars(os.path.expanduser(str(path or "").strip()))
        if not raw:
            raise ValueError("缺少组件入口")
        if _is_module_offset_literal(raw):
            raise ValueError("模块地址不能作为组件入口，请使用大漠内存或大漠汇编命令")
        if component_type == "com":
            if any(part in raw for part in ("/", "\\")) or os.path.splitdrive(raw)[0] or os.path.isfile(raw):
                raise ValueError("COM 组件入口必须是已注册的 ProgID 或 CLSID，不能使用文件路径")
            return raw
        if component_type == "process":
            from task_workflow.script_resources import resolve_script_program_path

            return resolve_script_program_path(raw, require_file=True, **self._resource_dirs())
        if os.path.isabs(raw):
            absolute = os.path.abspath(raw)
            if os.path.isfile(absolute):
                return absolute
            raise ValueError(f"找不到组件文件: {absolute}")
        normalized = raw.replace("\\", "/").lower()
        if "/" in raw and not normalized.startswith(("plugins/", "assets/components/")):
            absolute = os.path.abspath(raw)
            if os.path.isfile(absolute):
                return absolute
            raise ValueError(f"找不到组件文件: {absolute}")
        if normalized.startswith(("plugins/", "assets/components/")):
            from task_workflow.script_resources import resolve_resource_path

            located = resolve_resource_path(raw, enforce_jail=False, **self._resource_dirs())
            if located and os.path.isfile(located):
                return os.path.abspath(located)
            raise ValueError(f"找不到组件文件: {raw}")
        if os.path.splitext(raw)[1].lower() == ".py":
            absolute = os.path.abspath(raw)
            if os.path.isfile(absolute):
                return absolute
            raise ValueError(f"找不到组件文件: {raw}")
        if os.path.isfile(raw):
            return os.path.abspath(raw)
        return raw

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
            raise ValueError("多图识别需要有效的目标窗口")
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
        if self.should_stop():
            raise ValueError("已停止")
        errors = [str(item.error_message) for item in results if item.error_message]
        if errors or not results:
            raise ValueError("多图识别失败: " + "；".join(errors or ["未返回查询结果"]))
        if any(item.success and (item.center_x is None or item.center_y is None) for item in results):
            raise ValueError("多图识别命中但坐标未知")
        if (all_matches or not any(item.success for item in results)) and len(results) != len(images):
            raise ValueError("多图识别结果不完整，目标状态未知")
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
            "query_ok": True,
            "kind": "image",
            "x": None if first is None else int(first.center_x),
            "y": None if first is None else int(first.center_y),
            "score": None if first is None else float(first.confidence),
            "threshold": float(threshold),
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
        modes = {
            "前台驱动": "foreground_driver",
            "前台脚本": "foreground_py",
            "后台消息": "background_sendmessage",
            "后台投递": "background_postmessage",
        }
        if 模式 is None:
            # 线程上下文使用执行器的内部模式标识；脚本参数只接受目录中文名。
            resolved = "foreground_driver" if inherited == "foreground" else inherited
            if resolved not in set(modes.values()):
                raise ValueError("线程执行模式未知")
            return resolved
        resolved = modes.get(str(模式).strip())
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
        偏移x: Any = 0,
        偏移y: Any = 0,
        随机: Any = None,
        随机横坐标: Any = None,
        随机纵坐标: Any = None,
        区域: Any = None,
        模式: Any = None,
        **kwargs: Any,
    ) -> ScriptResult:
        if kwargs:
            raise ValueError("找图不支持" + "、".join(str(name) for name in kwargs))
        params = build_find_image_params(
            图片,
            阈值,
            点击,
            self._defaults("模拟鼠标操作"),
            双击=双击,
            偏移x=偏移x,
            偏移y=偏移y,
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
                        偏移x=偏移x,
                        偏移y=偏移y,
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
            image_params = dict(params)
            image_params["operation_mode"] = "找图功能"
            image_params["image_enable_click"] = bool(image_params.pop("enable_click", False))
            image_params["button"] = "左键"
            image_params["image_click_action"] = image_params.get("click_action", "完整点击")
            image_params["interval"] = float(image_params.get("click_interval", 0.0) or 0.0)
            image_params["image_hold_duration"] = float(
                image_params.get("hold_duration", 0.0) or 0.0
            )
            image_params["image_enable_auto_release"] = bool(
                image_params.get("enable_auto_release", True)
            )
            image_params["image_fixed_offset_x"] = int(image_params.get("fixed_offset_x", 0) or 0)
            image_params["image_fixed_offset_y"] = int(image_params.get("fixed_offset_y", 0) or 0)
            image_params["image_random_offset_x"] = int(image_params.get("random_offset_x", 0) or 0)
            image_params["image_random_offset_y"] = int(image_params.get("random_offset_y", 0) or 0)
            last = self._run("模拟鼠标操作", image_params, 模式=模式)
            if last:
                return last
        return last

    def 点击(
        self,
        x: Any = None,
        y: Any = None,
        键: Any = "左键",
        目标: Any = None,
        双击: Any = False,
        偏移x: Any = 0,
        偏移y: Any = 0,
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
        if 目标 is not None and (x is not None or y is not None):
            raise ValueError("点击的目标与坐标不能同时提供")
        if 目标 is not None:
            x = 目标
        if isinstance(x, str) and y is None and not _is_number_like(x):
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
                偏移x=偏移x,
                偏移y=偏移y,
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
        目标: Any = None,
        模式: Any = None,
    ) -> bool:
        target = resolve_xy(x, y, 目标)
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
        按键: Any,
        秒: Any = None,
        动作: Any = None,
        模式: Any = None,
        连发: Any = None,
        间隔: Any = None,
    ) -> bool:
        action_text = str(动作 or "").strip()
        if action_text not in {"", "按下", "松开"}:
            raise ValueError("按键动作只能是 按下 或 松开，省略动作时执行完整按键")
        if action_text == "松开" and (秒 is not None or 连发 is not None or 间隔 is not None):
            raise ValueError("松开动作不支持 秒、连发 或 间隔")
        if 连发 is not None and 秒 is None:
            raise ValueError("连发只在按住时有效，请同时写 秒=")
        if 间隔 is not None and 秒 is None:
            raise ValueError("间隔只在按住连发时有效，请同时写 秒=")
        if 秒 is not None:
            hold = _as_duration(秒, 0.5)
            if not math.isfinite(hold) or hold < 0:
                raise ValueError("按住时长必须是大于等于0的有限秒数")
            params = build_key_params(
                build_hold_key_sequence(按键, hold),
                self._defaults("模拟键盘操作"),
            )
            params["combo_key_action"] = "完整执行"
            params["combo_key_repeat"] = (action_text != "按下") if 连发 is None else _as_bool(连发)
            if 间隔 is not None:
                if not params["combo_key_repeat"]:
                    raise ValueError("间隔只在连发=真时有效")
                interval = float(间隔)
                if not math.isfinite(interval) or interval <= 0:
                    raise ValueError("间隔必须大于0")
                params["combo_key_repeat_interval"] = interval
            return self._run("模拟键盘操作", params, 模式=模式)
        return self._run("模拟键盘操作", build_key_params(按键, self._defaults("模拟键盘操作"), 动作=动作), 模式=模式)

    def 输入(self, 文本: Any, 模式: Any = None) -> bool:
        return self._run("模拟键盘操作", build_type_params(文本, self._defaults("模拟键盘操作")), 模式=模式)

    def 延时(self, 秒: Any) -> bool:
        seconds = finite_seconds(秒, "延时秒数")
        if self._invoke is not None:
            return self._run("延迟", build_delay_params(seconds, {}))
        return self._sleep_interruptible(seconds)

    def _sleep_interruptible(self, seconds: float) -> ScriptResult:
        deadline = time.monotonic() + finite_seconds(seconds, "延时秒数")
        stop = self.context.get("stop_checker")
        pause = self.context.get("pause_checker")
        while True:
            now = time.monotonic()
            if self.should_stop():
                raise ValueError("已停止")
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
        unsupported = set(kwargs).intersection({"点击", "双击", "动作", "次数", "按住秒", "自动松开"})
        if unsupported:
            raise ValueError("持续找图只识别，不支持" + "、".join(sorted(unsupported)))
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
                        if len(self._user_thread_errors) > MAX_THREAD_ERRORS:
                            del self._user_thread_errors[:-MAX_THREAD_ERRORS]
                finally:
                    with self._thread_lock:
                        if record.get("finished_at") is None:
                            record["finished_at"] = time.time()
                        self._user_idents.pop(current_ident, None)
                        # 保留最近的完成记录供“线程结果”查询，但清掉旧线程
                        # 的控制对象和结果，避免脚本反复创建不同名字后无限增长。
                        if len(self._user_thread_records) > MAX_THREAD_RECORDS:
                            for old_name, old_record in list(self._user_thread_records.items()):
                                if len(self._user_thread_records) <= MAX_THREAD_RECORDS:
                                    break
                                if old_record is record:
                                    continue
                                if str(old_record.get("status") or "") in {"starting", "running", "stopping"}:
                                    continue
                                self._user_thread_records.pop(old_name, None)
                                self._user_stops.pop(old_name, None)
                                self._user_threads.pop(old_name, None)

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
        handle = self._script_hotkeys.get(label)
        if handle is None:
            return False
        try:
            import keyboard

            keyboard.remove_hotkey(handle)
        except Exception as exc:
            raise ValueError(f"注销脚本热键失败: {exc}") from exc
        self._script_hotkeys.pop(label, None)
        return True

    def 全部注销热键(self) -> int:
        labels = list(self._script_hotkeys)
        errors = []
        for label in labels:
            try:
                self.注销热键(label)
            except Exception as exc:
                errors.append(f"{label}：{exc}")
        if errors:
            raise ValueError("注销热键失败：" + "；".join(errors))
        return len(labels)

    def 启动定时器(self, 名字: Any, 间隔: Any, 回调: Callable[[], Any], 次数: Any = 0) -> ScriptResult:
        label = str(名字 or "定时器").strip() or "定时器"
        seconds = finite_seconds(间隔, "定时器间隔", positive=True)
        count = integer_parameter(次数, "定时器次数", minimum=0)
        if not callable(回调):
            raise ValueError("定时器回调必须是子程序")
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
        errors = []

        def release(label, callback):
            try:
                callback()
                return True
            except Exception as exc:
                errors.append(f"{label}：{exc}")
                return False

        release("停止回放", self.停止回放)
        from task_workflow.media_player import stop_owned_audio

        release("停止音频", lambda: stop_owned_audio(self))
        for key in list(self._watch_stops):
            self._stop_watch(key, join=False)
        for name in list(self._user_stops):
            self._stop_user_thread(name, join=False)
        release("注销热键", self.全部注销热键)
        for thread in list(self._watch_threads.values()) + list(self._user_threads.values()):
            if thread is not None and thread.is_alive() and thread is not threading.current_thread():
                thread.join()
        self._watch_threads.clear()
        self._watch_stops.clear()
        self._user_threads.clear()
        self._user_stops.clear()
        self._user_idents.clear()
        self._user_thread_records.clear()
        self._latest.clear()
        self._regions.clear()
        release("关闭进程", self._close_owned_processes)
        manager = self._external_component_manager
        if manager is not None and release("关闭外部组件", manager.shutdown):
            self._external_component_manager = None
        if errors:
            raise ValueError("脚本资源释放失败：" + "；".join(errors))

    def _register_process(self, process: Any) -> None:
        pid = int(getattr(process, "pid", 0) or 0)
        if pid <= 0:
            return
        with self._process_lock:
            self._owned_processes[pid] = process

    def _forget_process(self, process: Any) -> None:
        pid = int(getattr(process, "pid", 0) or 0)
        if pid <= 0:
            return
        with self._process_lock:
            current = self._owned_processes.get(pid)
            if current is process:
                self._owned_processes.pop(pid, None)

    def _close_owned_processes(self) -> None:
        import subprocess

        with self._process_lock:
            processes = list(self._owned_processes.values())
        errors = []
        for process in processes:
            process_error = None
            try:
                detached = bool(getattr(process, "_lca_detached", False))
                if not detached and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        if process.poll() is None:
                            process.kill()
                            process.wait(timeout=2.0)
                if not detached and process.poll() is None:
                    raise ValueError("进程仍在运行")
                for name in ("stdin", "stdout", "stderr"):
                    stream = getattr(process, name, None)
                    if stream is not None:
                        stream.close()
            except Exception as exc:
                process_error = exc
            close = getattr(process, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as exc:
                    process_error = exc if process_error is None else ValueError(f"{process_error}；{exc}")
                finally:
                    self._forget_process(process)
            elif process_error is None:
                self._forget_process(process)
            if process_error is not None:
                errors.append(f"进程{process.pid}：{process_error}")
        if errors:
            raise ValueError("；".join(errors))

    def _components(self):
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
        调用约定: Any = None,
        超时: Any = 10,
    ) -> ScriptResult:
        component_type = str(类型 or "").strip().lower()
        entry = self._resolve_component_entry(入口, component_type)
        try:
            value = self._components().load(component_type, entry, calling_convention=调用约定, timeout=超时)
        except Exception as exc:
            raise ValueError(f"外部组件加载失败: {exc}") from exc
        return self._component_result(value, handle=value.get("handle"), component_type=value.get("type"))

    def 组件调用(
        self,
        句柄: Any,
        方法: Any = "",
        *参数: Any,
        参数类型: Any = None,
        返回类型: Any = None,
        关键字参数: Any = None,
        超时: Any = 30,
        输入: Any = None,
        工作目录: Any = None,
        环境变量: Any = None,
        编码: Any = None,
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
        raw = str(程序 or "").strip()
        if raw.replace("\\", "/").lower().endswith(".dll"):
            raise ValueError('组件.运行只能运行程序（.exe）。DLL 请用 组件.加载("dll", 路径)')
        resolved_program = self._resolve_component_entry(程序, "process")
        if 工作目录 is None and os.path.isabs(resolved_program):
            工作目录 = os.path.dirname(resolved_program)
        loaded = self.组件加载("process", resolved_program, 超时=超时)
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
            self.组件关闭(handle)
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
        interval = finite_seconds(间隔, "后台识别间隔", positive=True)
        if self._closed:
            raise ValueError("已停止")
        self._stop_watch(key)
        stop = threading.Event()
        self._watch_stops[key] = stop

        def loop() -> None:
            ident = threading.get_ident()
            with self._thread_lock:
                self._user_idents[ident] = stop
            try:
                while not stop.is_set() and not self._closed:
                    if self._is_stopped():
                        break
                    self._wait_if_paused()
                    if stop.is_set() or self._closed:
                        break
                    fn()
                    if stop.wait(interval):
                        break
            except Exception as exc:
                if not _is_stop_error(exc) and type(exc).__name__ != "ScriptOutcome":
                    self.logger.warning("[自定义脚本] 后台%s失败: %s", key, exc)
                    with self._thread_lock:
                        self._user_thread_errors.append(f"后台{key}: {exc}")
                        del self._user_thread_errors[:-MAX_THREAD_ERRORS]
            finally:
                with self._thread_lock:
                    self._user_idents.pop(ident, None)

        thread = threading.Thread(target=loop, name=f"lca-script-watch-{key}", daemon=True)
        self._watch_threads[key] = thread
        thread.start()

    def _stop_watch(self, key: str, join: bool = True) -> None:
        event = self._watch_stops.get(key)
        if event is not None:
            event.set()
        thread = self._watch_threads.get(key)
        if join and thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join()
        if thread is None or not thread.is_alive():
            self._watch_stops.pop(key, None)
            self._watch_threads.pop(key, None)

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
        except Exception as exc:
            raise ValueError(f"停止检查失败: {exc}") from exc

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
            except Exception as exc:
                raise ValueError(f"暂停检查失败: {exc}") from exc
            if not paused:
                return
            time.sleep(0.05)

    def 找色(
        self,
        颜色: Any,
        点击: Any = False,
        区域: Any = None,
        双击: Any = False,
        偏移x: Any = 0,
        偏移y: Any = 0,
        随机: Any = None,
        随机横坐标: Any = None,
        随机纵坐标: Any = None,
        模式: Any = None,
    ) -> bool:
        return self._run(
            "模拟鼠标操作",
            build_find_color_params(
                颜色,
                点击,
                self._resolve_region(区域),
                self._defaults("模拟鼠标操作"),
                双击=双击,
                偏移x=偏移x,
                偏移y=偏移y,
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
        模式: Any = None,
    ) -> bool:
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
        point = resolve_xy(x, y, target)
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
        偏移x: Any = 0,
        偏移y: Any = 0,
        随机: Any = None,
        随机横坐标: Any = None,
        随机纵坐标: Any = None,
        模式: Any = None,
    ) -> ScriptResult:
        found = self.找字(目标=目标, 区域=区域)
        if not found:
            return found if isinstance(found, ScriptResult) else ScriptResult(ok=False)
        return self._run(
            "模拟鼠标操作",
            build_text_click_params(
                点击,
                键,
                self._defaults("模拟鼠标操作"),
                双击=双击,
                偏移x=偏移x,
                偏移y=偏移y,
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
        偏移x: Any = 0,
        偏移y: Any = 0,
        随机: Any = None,
        随机横坐标: Any = None,
        随机纵坐标: Any = None,
        模式: Any = None,
    ) -> ScriptResult:
        found = self.找字库(目标=目标, 字库=字库, 颜色=颜色, 相似度=相似度, 区域=区域)
        if not found:
            return found if isinstance(found, ScriptResult) else ScriptResult(ok=False)
        return self._run(
            "模拟鼠标操作",
            build_text_click_params(
                点击,
                键,
                self._defaults("模拟鼠标操作"),
                双击=双击,
                偏移x=偏移x,
                偏移y=偏移y,
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
        timeout = finite_seconds(超时, "超时")
        deadline = time.monotonic() + timeout
        last = ScriptResult(ok=False)
        pause = finite_seconds(间隔, "间隔", positive=True)
        while True:
            if self.should_stop():
                raise ValueError("已停止")
            self._wait_if_paused()
            if self.should_stop():
                raise ValueError("已停止")
            last = finder()
            found = bool(last)
            if isinstance(last, ScriptResult):
                state = last._payload
                if state.get("error") or state.get("query_ok") is False or (not found and state.get("query_ok") is not True):
                    raise ValueError(str(state.get("error") or "查询失败，目标状态未知"))
                if not found and state.get("matched") is True:
                    raise ValueError("识别已命中，但后续动作失败")
            elif not found:
                raise ValueError("查询未返回明确状态，目标状态未知")
            if 消失 and not found:
                return ScriptResult({"ok": True, "kind": "wait"})
            if not 消失 and found:
                return last if isinstance(last, ScriptResult) else ScriptResult(ok=True)
            if time.monotonic() >= deadline:
                if 消失:
                    return ScriptResult({"ok": False, "kind": "wait"})
                return last if isinstance(last, ScriptResult) else ScriptResult(ok=False)
            self.延时(min(pause, max(0.0, deadline - time.monotonic())))

    def 按下(
        self,
        x: Any = None,
        y: Any = None,
        键: Any = "左键",
        目标: Any = None,
        按键: Any = None,
        模式: Any = None,
        秒: Any = None,
        连发: Any = None,
        间隔: Any = None,
        **kwargs: Any,
    ) -> ScriptResult:
        if 秒 is not None:
            return self.按住(
                x, y, 秒=秒, 键=键,
                目标=目标, 按键=按键, 模式=模式,
                连发=False if 连发 is None else 连发, 间隔=间隔, **kwargs,
            )
        if 连发 is not None or 间隔 is not None:
            raise ValueError("按下选择连发时必须同时写 秒=，到时自动松开；持续按下请省略这些参数")
        return self._press_or_release(
            "仅按下",
            x,
            y,
            键=键,
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
        目标: Any = None,
        按键: Any = None,
        模式: Any = None,
        连发: Any = False,
        间隔: Any = None,
        **kwargs: Any,
    ) -> ScriptResult:
        hold = _as_duration(秒, 0.5)
        if not math.isfinite(hold) or hold < 0:
            raise ValueError("按住时长必须是大于等于0的有限秒数")
        key_name = 按键 if 按键 is not None else (x if y is None and 目标 is None and _looks_like_key(x) else None)
        if key_name is not None and y is None:
            if kwargs:
                raise ValueError("键盘按住不支持" + "、".join(str(name) for name in kwargs))
            return self.按键(key_name, 秒=hold, 连发=连发, 间隔=间隔, 模式=模式)
        if _as_bool(连发) or 间隔 is not None:
            raise ValueError("连发和间隔只用于键盘按住，鼠标连续点击请使用 连点")
        return self._press_or_release(
            "仅按下",
            x,
            y,
            键=键,
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
        目标: Any = None,
        模式: Any = None,
        **kwargs: Any,
    ) -> ScriptResult:
        return self.点击(
            x,
            y,
            键=键,
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
        目标: Any = None,
        按键: Any = None,
        **kwargs: Any,
    ) -> ScriptResult:
        模式 = kwargs.pop("模式", None)
        key_name = 按键 if 按键 is not None else (x if y is None and 目标 is None and _looks_like_key(x) else None)
        if key_name is not None:
            key_action = "按下" if 动作 == "仅按下" else "松开"
            return self._run("模拟键盘操作", build_key_params(key_name, self._defaults("模拟键盘操作"), 动作=key_action), 模式=模式)
        return self.点击(
            x,
            y,
            键=键,
            目标=目标,
            动作=动作,
            模式=模式,
            **kwargs,
        )

    def 取色(
        self,
        x: Any = None,
        y: Any = None,
        目标: Any = None,
    ) -> ScriptResult:
        if 目标 is not None and x is None:
            x = 目标
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
        目标: Any = None,
    ) -> ScriptResult:
        expected = 颜色
        if expected is None and isinstance(x, str) and y is None and _parse_rgb(x) is not None:
            expected = x
            x = None
        if expected is None and y is not None and not _is_number_like(y) and _parse_rgb(y) is not None:
            expected = y
            y = None
        current = self.取色(x, y, 目标=目标)
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
        images = collect_find_image_args(图片, 更多图片)
        if not images:
            raise ValueError("找所有图至少需要一张图片")
        threshold = float(阈值)
        if not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError("找所有图阈值必须在0到1之间")
        region = self._resolve_region(区域)
        images = [self._constrain_path(image) for image in images if str(image or "").strip()]
        limit = self._dm_int(最多, "最多", 1)
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
            "query_ok": True,
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
        template, loaded_path = _load_template_image(image, self.context.get("card_id"))
        if template is None:
            raise ValueError(f"找所有图失败：无法读取模板 {image}")
        frame = _capture_window_frame(self.context.get("target_hwnd"))
        if frame is None:
            raise ValueError("找所有图失败：无法获取窗口截图")
        from utils.match.smart_image_matcher import match_template_all, normalize_match_image
        import cv2

        needle = normalize_match_image(template)
        if needle is None:
            raise ValueError("找所有图失败：模板格式无效")
        scale = float(params["template_scale"])
        if abs(scale - 1.0) > 1e-6:
            height, width = needle.shape[:2]
            needle = cv2.resize(needle, (max(1, int(round(width * scale))), max(1, int(round(height * scale)))), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        matches = match_template_all(frame, needle, threshold, region, limit,
                                     mode=params["image_mode"], rotation=params["image_rotation"])
        return [{"ok": True, "kind": "image", "x": int(match.center[0]),
                 "y": int(match.center[1]), "score": float(match.confidence),
                 "threshold": threshold, "path": loaded_path}
                for match in matches]

    def 等毫秒(self, 毫秒: Any) -> bool:
        return self.延时(finite_seconds(毫秒, "毫秒") / 1000.0)

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
        from task_workflow.media_player import audio_owner, play_audio
        from task_workflow.script_resources import resolve_resource_path

        # 先判空再做路径约束，否则用户看到的是笼统的“缺少资源路径”而不是这条命令的用法
        if not str(文件 or "").strip():
            raise ValueError('播放要写音频文件，例如 播放("提示.wav")')
        path = self._constrain_path(文件)
        if not path:
            raise ValueError('播放要写音频文件，例如 播放("提示.wav")')
        resolved = resolve_resource_path(path, enforce_jail=False, **self._resource_dirs())
        if not resolved:
            raise ValueError(f"播放文件不存在: {文件}")
        try:
            with audio_owner(self):
                played = play_audio(resolved, wait=_as_bool(等待), stop_checker=self.should_stop)
        except FileNotFoundError as exc:
            raise ValueError(str(exc)) from exc
        return ScriptResult({"ok": True, "kind": "audio", "path": played})

    def 停止播放(self) -> ScriptResult:
        from task_workflow.media_player import stop_audio

        stop_audio()
        return ScriptResult({"ok": True, "kind": "audio"})

    def 回放(self, 文件: Any, 速度: Any = 1.0, 次数: Any = 1, 等待: Any = True) -> ScriptResult:
        from task_workflow.script_resources import read_resource_bytes

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
        data = read_resource_bytes(relative, **dirs)
        if not data:
            raise ValueError(f"回放文件不存在: {raw}")
        try:
            payload = json.loads(data.decode("utf-8"))
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
            thread.join()
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

        frame = _capture_window_frame(self.context.get("target_hwnd"))
        if frame is None:
            return ScriptResult({"ok": False, "kind": "image"})
        dirs = dict(self._resource_dirs())
        root = str(dirs.get("images_dir") or "").strip()
        if not root:
            raise ValueError("截图失败：未绑定图片目录")
        dirs["images_dir"] = root
        name = str(文件 or "").strip().replace("\\", "/")
        if not name:
            import uuid

            name = time.strftime("shot_%Y%m%d_%H%M%S_") + uuid.uuid4().hex + ".png"
        if not os.path.splitext(os.path.basename(name))[1]:
            name = f"{name}.png"
        target = name if os.path.isabs(name) else os.path.join(root, name)
        dest = constrain_script_path(target, **dirs)
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        try:
            import cv2

            image = frame
            if getattr(image, "ndim", 0) == 3 and image.shape[2] == 4:
                image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
            extension = os.path.splitext(dest)[1]
            wrote, encoded = cv2.imencode(extension, image)
            if wrote:
                with open(dest, "wb") as output:
                    output.write(encoded.tobytes())
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
            return ScriptResult({"ok": down, "query_ok": True, "kind": "key"})

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

    @contextmanager
    def _task_input_guard(self, task_type, params, module, context):
        """脚本动作与卡片共用输入锁，整段拖拽期间不能交叉发送键鼠事件。"""
        from utils.input.input_guard import (
            acquire_input_guard,
            get_input_lock_timeout_seconds,
            get_input_lock_wait_warn_ms,
            resolve_input_lock_resource,
            task_requires_input_lock,
        )

        if not task_requires_input_lock(task_type, params, module):
            yield
            return
        resource = resolve_input_lock_resource(
            context["execution_mode"], context.get("target_hwnd"), task_type
        )
        owner = f"script={context.get('card_id')}, task={task_type}, thread={threading.get_ident()}, resource={resource}"
        wait_slice = max(0.05, min(0.2, get_input_lock_timeout_seconds()))
        total_wait_ms = 0.0
        stop_checker = context.get("stop_checker")
        while True:
            if self.should_stop() or (callable(stop_checker) and stop_checker()):
                raise ValueError("已停止")
            self._wait_if_paused()
            with acquire_input_guard(owner=owner, timeout=wait_slice, resource=resource) as (acquired, wait_ms):
                total_wait_ms += max(0.0, float(wait_ms))
                if not acquired:
                    continue
                # 等待期间可能收到停止请求，取得锁后仍不能发出输入。
                if self.should_stop() or (callable(stop_checker) and stop_checker()):
                    raise ValueError("已停止")
                if total_wait_ms >= get_input_lock_wait_warn_ms():
                    self.logger.warning("[输入调度] 脚本等待输入锁 %.1fms: %s", total_wait_ms, owner)
                yield
                return

    def _run(
        self,
        task_type: str,
        params: Dict[str, Any],
        模式: Any = None,
        stop_checker: Any = None,
        pause_checker: Any = None,
    ) -> ScriptResult:
        self._allowed(task_type)
        module = self._module(task_type)
        execution_mode = self._resolve_input_mode(模式, self.context.get("execution_mode", "foreground"))
        context = dict(self.context, execution_mode=execution_mode)
        if stop_checker is not None:
            context["stop_checker"] = stop_checker
        if pause_checker is not None:
            context["pause_checker"] = pause_checker
        operation = str(params.get("operation_mode") or "")
        image_perception = task_type == "模拟鼠标操作" and operation == "找图功能"
        color_perception = task_type == "模拟鼠标操作" and operation == "找色功能"
        perception_task = image_perception or color_perception or task_type in {"OCR文字识别", "点阵字库OCR", "YOLO目标检测"}
        kind = "image" if image_perception else (_KIND_BY_TASK.get(task_type) or "")
        with self._task_input_guard(task_type, params, module, context):
            if perception_task:
                self.store.publish(context.get("card_id"), kind=kind, ok=False, query_ok=None)
            before = self.store.last()
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
            # 感知任务即使重复命中同一位置，也返回完整结果；普通动作不沿用旧字段。
            changed = after != before
            payload = dict(after) if perception_task else {"ok": ok}
            payload["ok"] = ok
            if perception_task:
                payload["query_ok"] = True if ok else after.get("query_ok") is True
                payload["matched"] = ok or (after.get("ok") is True and payload["query_ok"])
                if not payload["query_ok"]:
                    payload["error"] = after.get("error") or "识别执行失败，目标状态未知"
            payload["execution_mode"] = execution_mode
            kind = kind or str(payload.get("kind") or "")
            if kind:
                remembered = dict(payload) if perception_task else dict(after)
                remembered["ok"] = ok
                remembered.setdefault("kind", kind)
                if perception_task or changed or remembered.get("x") is not None or remembered.get("items"):
                    self._remember(kind, remembered)
                if changed and not perception_task:
                    payload = remembered
            payload.setdefault("execution_mode", execution_mode)
            return ScriptResult(payload)
