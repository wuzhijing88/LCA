# -*- coding: utf-8 -*-
"""自定义脚本命令：组参数后调用现有 execute_task。"""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from task_workflow.runtime_store import RuntimeStore

logger = logging.getLogger(__name__)

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
    return message.startswith(("已停止", "执行超时", "停止检查")) or "已停止" in message


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


def _as_region(区域: Any) -> Optional[Tuple[int, int, int, int]]:
    if 区域 is None or 区域 is False:
        return None
    if isinstance(区域, (tuple, list)) and len(区域) >= 4:
        return int(区域[0]), int(区域[1]), int(区域[2]), int(区域[3])
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
    click_count = 2 if double else max(1, _as_int(次数, 1) if 次数 is not None else 1)
    interval = 0.0 if 间隔 is None or 间隔 == "" else float(间隔)
    hold = 0.0 if 按住秒 is None or 按住秒 == "" else _as_duration(按住秒, 0.0)
    auto_release = True if 自动松开 is None else _as_bool(自动松开)
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
) -> Dict[str, Any]:
    images, inferred_threshold = collect_find_image_args(图片, extra_images)
    if inferred_threshold is not None:
        阈值 = inferred_threshold
    params = dict(defaults or {})
    params["image_path"] = str(images[0] if images else 图片 or "")
    params["_script_images"] = images
    params["confidence"] = float(阈值)
    params["enable_click"] = _as_bool(点击)
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
    x: Any,
    y: Any,
    last: Optional[Dict[str, Any]] = None,
    defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    params = dict(defaults or {})
    payload = last or {}
    start_x = payload.get("x")
    start_y = payload.get("y")
    if start_x is None or start_y is None:
        start_x, start_y = x, y
    params["operation_mode"] = "鼠标移动"
    params["move_mode"] = "绝对移动"
    params["move_start_position"] = f"{int(start_x)},{int(start_y)}"
    params["move_end_position"] = f"{int(x)},{int(y)}"
    params["move_duration_mode"] = "固定持续时间"
    params["move_duration"] = 0.2
    params["move_enable_click"] = False
    return params


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


def build_type_params(文本: Any, defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    params = dict(defaults or {})
    params["input_type"] = "文本输入"
    params["text_input_mode"] = "单组文本"
    params["text_to_type"] = str(文本 or "")
    return params


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
    if 区域:
        left, top, width, height = 区域
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
    if 区域:
        left, top, width, height = 区域
        params["region_mode"] = "指定区域"
        params["region_x"] = int(left)
        params["region_y"] = int(top)
        params["region_width"] = int(width)
        params["region_height"] = int(height)
    return params


_YOLO_STRATEGIES = {
    "最近": "最近",
    "最大": "最大",
    "置信度最高": "置信度最高",
    "最高": "置信度最高",
}


def _as_yolo_strategy(策略: Any) -> Optional[str]:
    text = str(策略 or "").strip()
    if not text:
        return None
    return _YOLO_STRATEGIES.get(text, text)


def _looks_like_model_path(模型: Any) -> bool:
    text = str(模型 or "").strip()
    if not text:
        return False
    lower = text.lower()
    return lower.endswith(".onnx") or "/" in text or "\\" in text


def resolve_yolo_model(
    模型: Any = None,
    defaults: Optional[Dict[str, Any]] = None,
) -> str:
    model = str(模型 or "").strip()
    if not model:
        model = str((defaults or {}).get("model_path") or "").strip()
    if not model:
        raise ValueError('检测要写模型，例如 检测("yolo/xxx.onnx")')
    if not _looks_like_model_path(model):
        raise ValueError('检测的模型要写成 onnx 路径，例如 "yolo/xxx.onnx"。类别写成 类别="敌人"')
    return model


def build_yolo_params(
    类别: Any = None,
    阈值: Any = 0.5,
    defaults: Optional[Dict[str, Any]] = None,
    点击: Any = False,
    双击: Any = False,
    偏移横坐标: Any = 0,
    偏移纵坐标: Any = 0,
    随机: Any = None,
    随机横坐标: Any = None,
    随机纵坐标: Any = None,
    区域: Any = None,
    策略: Any = None,
    模型: Any = None,
) -> Dict[str, Any]:
    params = dict(defaults or {})
    model = str(模型 or params.get("model_path") or "").strip()
    if model:
        params["model_path"] = model
    params["confidence_threshold"] = float(阈值)
    params["target_classes"] = str(类别) if 类别 else "全部类别"
    params["action_type"] = "点击" if _as_bool(点击) else "无"
    params["approach_mode"] = "否"
    strategy = _as_yolo_strategy(策略)
    if strategy:
        params["target_selection"] = strategy
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
        from utils.capture.screenshot_helper import get_screenshot_engine

        engine = str(get_screenshot_engine() or "wgc").strip().lower()
        from utils import screenshot_helper

        reader = {
            "wgc": screenshot_helper.get_pixel_color_wgc,
            "printwindow": screenshot_helper.get_pixel_color_printwindow,
            "gdi": screenshot_helper.get_pixel_color_gdi,
            "dxgi": screenshot_helper.get_pixel_color_dxgi,
        }.get(engine, screenshot_helper.get_pixel_color_wgc)
        rgb = reader(handle, int(x), int(y), True)
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
        from utils.capture.screenshot_helper import get_screenshot_engine
        from utils import screenshot_helper

        engine = str(get_screenshot_engine() or "wgc").strip().lower()
        capture = {
            "wgc": screenshot_helper.capture_window_wgc,
            "printwindow": screenshot_helper.capture_window_printwindow,
            "gdi": screenshot_helper.capture_window_gdi,
            "dxgi": screenshot_helper.capture_window_dxgi,
        }.get(engine, screenshot_helper.capture_window_wgc)
        return capture(handle, client_area_only=True)
    except Exception:
        return None


def build_element_click_params(
    名称: Any,
    点击: Any = True,
    defaults: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    params = dict(defaults or {})
    params["operation_mode"] = "元素点击"
    params["element_name"] = str(名称 or "")
    params["element_enable_click"] = bool(点击)
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
    ) -> ScriptResult:
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
            区域=区域,
            extra_images=更多图片,
        )
        images = list(params.pop("_script_images", []) or [])
        if not images:
            images = [str(图片 or "")]
        last = ScriptResult(ok=False)
        for image in images:
            params["image_path"] = str(image)
            last = self._run("图片点击", dict(params))
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
        )

    def 移动(
        self,
        x: Any = None,
        y: Any = None,
        横坐标: Any = None,
        纵坐标: Any = None,
        目标: Any = None,
    ) -> bool:
        target = resolve_xy(x, y, 横坐标, 纵坐标, 目标)
        if target is None:
            raise ValueError("移动缺少横坐标、纵坐标")
        x, y = target
        return self._run(
            "模拟鼠标操作",
            build_move_params(x, y, self.store.last(), self._defaults("模拟鼠标操作")),
        )

    def 按键(self, 按键内容: Any, 秒: Any = None, 动作: Any = None) -> bool:
        if 秒 is not None and str(动作 or "").strip() not in {"仅按下", "按下", "只按下", "仅松开", "松开", "弹起", "释放", "只释放"}:
            hold = _as_duration(秒, 0.5)
            down = self._run("模拟键盘操作", build_key_params(按键内容, self._defaults("模拟键盘操作"), 动作="只按下"))
            if not down:
                return down
            self.延时(hold)
            return self._run("模拟键盘操作", build_key_params(按键内容, self._defaults("模拟键盘操作"), 动作="只释放"))
        return self._run("模拟键盘操作", build_key_params(按键内容, self._defaults("模拟键盘操作"), 动作=动作))

    def 输入(self, 文本: Any) -> bool:
        return self._run("模拟键盘操作", build_type_params(文本, self._defaults("模拟键盘操作")))

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
        return self._run("OCR文字识别", build_ocr_params(目标, 区域, self._defaults("OCR文字识别")))

    def 找字库(
        self,
        目标: Any = None,
        字库: Any = None,
        颜色: Any = None,
        相似度: Any = None,
        区域: Any = None,
    ) -> bool:
        return self._run(
            "点阵字库OCR",
            build_dict_ocr_params(目标, 字库, 颜色, 相似度, 区域, self._defaults("点阵字库OCR")),
        )

    def 检测(
        self,
        模型: Any = None,
        类别: Any = None,
        阈值: Any = 0.5,
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
        策略: Any = None,
    ) -> bool:
        defaults = self._defaults("YOLO目标检测")
        偏移横坐标, 偏移纵坐标 = _offset_alias(偏移x, 偏移y, 偏移横坐标, 偏移纵坐标)
        return self._run(
            "YOLO目标检测",
            build_yolo_params(
                类别,
                阈值,
                defaults,
                点击=点击,
                双击=双击,
                偏移横坐标=偏移横坐标,
                偏移纵坐标=偏移纵坐标,
                随机=随机,
                随机横坐标=随机横坐标,
                随机纵坐标=随机纵坐标,
                区域=区域,
                策略=策略,
                模型=resolve_yolo_model(模型, defaults),
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
        kwargs.pop("点击", None)
        kwargs.pop("双击", None)
        resolve_yolo_model(模型, self._defaults("YOLO目标检测"))
        self._start_watch(
            "yolo",
            间隔,
            lambda: self.检测(模型, 类别, 点击=False, **kwargs),
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
        func = 目标
        label = 名字
        if isinstance(目标, str):
            raise ValueError("多线程请传入子程序，例如 多线程(按W)")
        if not callable(func):
            raise ValueError("多线程请传入子程序，例如 多线程(按W)")
        name = str(label or getattr(func, "__name__", "") or "后台").strip() or "后台"
        with self._thread_lock:
            current = self._user_threads.get(name)
            if current is not None and current.is_alive():
                raise ValueError(f"线程已在跑：{name}")
            stop = threading.Event()
            self._user_stops[name] = stop

            def runner() -> None:
                try:
                    func()
                except Exception as exc:
                    if _is_stop_error(exc) or type(exc).__name__ == "ScriptOutcome":
                        return
                    self.logger.warning("[自定义脚本] 线程%s失败: %s", name, exc)

            thread = threading.Thread(target=runner, name=f"lca-script-fn-{name}", daemon=True)
            self._user_threads[name] = thread
            thread.start()
            if thread.ident is not None:
                self._user_idents[thread.ident] = stop
        return ScriptResult({"ok": True, "kind": "thread", "text": name})

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

    def close(self) -> None:
        self._closed = True
        for key in list(self._watch_stops):
            self._stop_watch(key, join=False)
        for name in list(self._user_stops):
            self._stop_user_thread(name, join=False)
        for thread in list(self._watch_threads.values()) + list(self._user_threads.values()):
            if thread is not None and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=2.0)

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
        event = self._user_stops.pop(name, None)
        if event is not None:
            event.set()
        thread = self._user_threads.pop(name, None)
        if thread is not None and thread.ident is not None:
            self._user_idents.pop(thread.ident, None)
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
    ) -> bool:
        偏移横坐标, 偏移纵坐标 = _offset_alias(偏移x, 偏移y, 偏移横坐标, 偏移纵坐标)
        return self._run(
            "模拟鼠标操作",
            build_find_color_params(
                颜色,
                点击,
                区域,
                self._defaults("模拟鼠标操作"),
                双击=双击,
                偏移横坐标=偏移横坐标,
                偏移纵坐标=偏移纵坐标,
                随机=随机,
                随机横坐标=随机横坐标,
                随机纵坐标=随机纵坐标,
            ),
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
        )

    def 点元素(self, 名称: Any, 点击: Any = True) -> bool:
        return self._run(
            "模拟鼠标操作",
            build_element_click_params(名称, 点击, self._defaults("模拟鼠标操作")),
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

    def _extend_deadline(self, seconds: Any) -> None:
        extra = max(0.0, float(seconds or 0))
        target = time.monotonic() + extra + 1.0
        guard = self.context.get("_guard")
        if guard is not None and getattr(guard, "deadline", None) is not None:
            guard.deadline = max(float(guard.deadline), target)
            self.context["_script_deadline"] = guard.deadline
            return
        current = self.context.get("_script_deadline")
        if current is None:
            return
        if target > float(current):
            self.context["_script_deadline"] = target

    def _wait_found(self, finder, 超时: Any, 间隔: Any, 消失: bool = False) -> ScriptResult:
        timeout = max(0.0, float(超时 if 超时 is not None else 8))
        self._extend_deadline(timeout)
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
        **kwargs: Any,
    ) -> ScriptResult:
        hold = _as_duration(秒, 0.5)
        key_name = 按键 if 按键 is not None else (x if y is None and 目标 is None and _looks_like_key(x) else None)
        if key_name is not None and y is None and 横坐标 is None:
            down = self._run("模拟键盘操作", build_key_params(key_name, self._defaults("模拟键盘操作"), 动作="只按下"))
            if not down:
                return down
            self.延时(hold)
            return self._run("模拟键盘操作", build_key_params(key_name, self._defaults("模拟键盘操作"), 动作="只释放"))
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
        key_name = 按键 if 按键 is not None else (x if y is None and 目标 is None and 横坐标 is None and _looks_like_key(x) else None)
        if key_name is not None:
            return self._run("模拟键盘操作", build_key_params(key_name, self._defaults("模拟键盘操作"), 动作=动作))
        return self.点击(
            x,
            y,
            键=键,
            横坐标=横坐标,
            纵坐标=纵坐标,
            目标=目标,
            动作=动作,
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
    ) -> ScriptResult:
        images, inferred = collect_find_image_args(图片, 更多图片)
        threshold = float(inferred if inferred is not None else 阈值 or 0.8)
        region = _as_region(区域)
        items = []
        for image in images:
            items = self._collect_image_matches(image, threshold, region, _as_int(最多, 20))
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

    def _collect_image_matches(self, image: Any, threshold: float, region: Any, limit: int) -> list:
        params = build_find_image_params(image, threshold, False, 区域=region)
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

                needle = normalize_match_image(template)
                for match in match_template_all(frame, needle if needle is not None else template, threshold, region, limit):
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

    def 相对移动(self, 偏移横坐标: Any = 0, 偏移纵坐标: Any = 0, x: Any = None, y: Any = None) -> bool:
        dx = 偏移横坐标 if x is None else x
        dy = 偏移纵坐标 if y is None else y
        pos = self.鼠标位置()
        if not pos:
            raise ValueError("移动缺少横坐标、纵坐标")
        return self.移动(int(pos.横坐标) + int(dx or 0), int(pos.纵坐标) + int(dy or 0))

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

        path = str(文件 or "").strip()
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

    def 激活(self) -> ScriptResult:
        hwnd = int(self.context.get("target_hwnd") or 0)
        if hwnd <= 0:
            return ScriptResult({"ok": False, "kind": "window"})
        try:
            from utils.window.window_activation_utils import activate_window

            activate_window(hwnd, log_prefix="脚本激活")
        except Exception as exc:
            raise ValueError(f"激活窗口失败: {exc}") from exc
        return ScriptResult({"ok": True, "kind": "window"})

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

    def _run(self, task_type: str, params: Dict[str, Any]) -> ScriptResult:
        self._allowed(task_type)
        before = self.store.last()
        module = self._module(task_type)
        context = self.context
        if self._invoke is not None:
            result = self._invoke(task_type, params, context)
        else:
            execute = getattr(module, "execute_task", None)
            if not callable(execute):
                raise ValueError(f"能力不可执行: {task_type}")
            result = execute(
                params=params,
                counters=context.get("counters") if isinstance(context.get("counters"), dict) else {},
                execution_mode=context.get("execution_mode", "foreground"),
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
        changed = after != before
        payload = dict(after) if changed else {"ok": ok}
        payload["ok"] = ok
        kind = _KIND_BY_TASK.get(task_type) or str(payload.get("kind") or "")
        if kind:
            remembered = dict(after)
            remembered["ok"] = ok
            remembered.setdefault("kind", kind)
            if changed or remembered.get("x") is not None or remembered.get("items"):
                self._remember(kind, remembered)
                if changed:
                    payload = remembered
        return ScriptResult(payload)
