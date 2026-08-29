from __future__ import annotations

import logging
from typing import Any, Optional

import cv2
import numpy as np

from app_core.maps.input_hold import hold_key_via_keyboard_task
from app_core.maps.loop import PathLoopConfig, run_path_loop, validate_run
from app_core.maps.record import (
    format_map_option,
    list_maps,
    load_map,
    parse_map_option,
    save_map,
)
from tasks.task_utils import (
    capture_window_smart,
    get_standard_action_params,
    handle_failure_action,
    handle_success_action,
    safe_imread,
)

logger = logging.getLogger(__name__)

TASK_TYPE = "A*寻路"
TASK_NAME = "A*寻路"


def requires_input_lock(_params: dict[str, Any]) -> bool:
    return True


def open_map_stitcher(params: dict[str, Any], target_hwnd=None, **kwargs):
    try:
        from ui.maps.stitcher_dialog import open_stitcher_dialog
        map_id = parse_map_option(str(params.get("map_option") or "")) or None
        option = open_stitcher_dialog(
            kwargs.get("parameter_panel") or kwargs.get("main_window"),
            map_id,
        )
    except Exception:
        return False
    return option or True


def _map_options() -> list[str]:
    try:
        return [format_map_option(map_id, name) for map_id, name in list_maps()]
    except Exception:
        logger.exception("读取地图库失败")
        return []


def get_params_definition() -> dict[str, dict[str, Any]]:
    params = {
        "---map---": {"type": "separator", "label": "地图与定位"},
        "minimap_region": {
            "label": "小地图区域",
            "type": "button",
            "button_text": "选择小地图区域",
            "widget_hint": "motion_region_selector",
        },
        "minimap_x": {"label": "小地图 X", "type": "hidden", "default": 0},
        "minimap_y": {"label": "小地图 Y", "type": "hidden", "default": 0},
        "minimap_width": {"label": "小地图宽度", "type": "hidden", "default": 50},
        "minimap_height": {"label": "小地图高度", "type": "hidden", "default": 50},
        "map_option": {
            "label": "地图",
            "type": "select",
            "options": _map_options(),
            "default": "",
        },
        "open_stitcher": {
            "label": "拼图工具",
            "type": "button",
            "action": "open_map_stitcher",
            "button_text": "打开拼图工具",
        },
        "marker_type": {
            "label": "角色标记",
            "type": "select",
            "options": ["箭头", "圆点"],
            "default": "圆点",
        },
        "map_rotates": {
            "label": "小地图旋转",
            "type": "select",
            "options": ["不转", "转"],
            "default": "不转",
        },
        "arrow_template_path": {
            "label": "箭头模板",
            "type": "file",
            "default": "",
            "condition": {"param": "marker_type", "value": "箭头"},
        },
        "death_image_paths": {
            "label": "死亡状态图",
            "type": "file",
            "default": "",
            "multiline": True,
        },
        "---movement---": {"type": "separator", "label": "寻路按键"},
        "direction_mode": {
            "label": "移动方向",
            "type": "select",
            "options": ["四向", "八向"],
            "default": "八向",
        },
        "key_up": {"label": "上", "type": "text", "default": "w"},
        "key_down": {"label": "下", "type": "text", "default": "s"},
        "key_left": {"label": "左", "type": "text", "default": "a"},
        "key_right": {"label": "右", "type": "text", "default": "d"},
        "key_up_left": {
            "label": "左上",
            "type": "text",
            "default": "q",
            "condition": {"param": "direction_mode", "value": "八向"},
        },
        "key_up_right": {
            "label": "右上",
            "type": "text",
            "default": "e",
            "condition": {"param": "direction_mode", "value": "八向"},
        },
        "key_down_left": {
            "label": "左下",
            "type": "text",
            "default": "z",
            "condition": {"param": "direction_mode", "value": "八向"},
        },
        "key_down_right": {
            "label": "右下",
            "type": "text",
            "default": "c",
            "condition": {"param": "direction_mode", "value": "八向"},
        },
        "hold_seconds": {
            "label": "按住时长（秒）",
            "type": "float",
            "default": 0.15,
            "min": 0.01,
        },
        "match_fail_limit": {
            "label": "定位失败上限",
            "type": "int",
            "default": 8,
            "min": 1,
        },
        "stuck_limit": {
            "label": "卡住上限",
            "type": "int",
            "default": 8,
            "min": 1,
        },
    }
    params.update(get_standard_action_params())
    return params


def _split_paths(value: Any) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def validate_card_params(params: dict[str, Any]) -> str | None:
    death_paths = _split_paths(params.get("death_image_paths"))
    marker = str(params.get("marker_type") or "圆点")
    arrow_path = str(params.get("arrow_template_path") or "").strip()

    if not death_paths:
        return validate_run(None, [], marker, None)  # type: ignore[arg-type]

    map_id = parse_map_option(str(params.get("map_option") or ""))
    if not map_id:
        return "未配置地图"
    try:
        record = load_map(map_id)
    except Exception:
        return "地图不存在或无法读取"

    death_templates = [object() for _path in death_paths]
    arrow_template = object() if arrow_path else None
    return validate_run(record, death_templates, marker, arrow_template)  # type: ignore[arg-type]


def _load_image(path: str, get_image_data=None) -> np.ndarray | None:
    if path.startswith("memory://") and callable(get_image_data):
        try:
            image_data = get_image_data(path)
            if isinstance(image_data, np.ndarray):
                return image_data
            if image_data:
                buffer = np.frombuffer(image_data, dtype=np.uint8)
                image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
                if image is not None:
                    return image
        except Exception:
            logger.exception("读取内存图片失败: %s", path)
    return safe_imread(path)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def execute_task(
    params: dict[str, Any],
    counters: dict[str, int],
    execution_mode: str = "foreground",
    target_hwnd=None,
    **kwargs,
) -> tuple[bool, str, Optional[int]]:
    del counters
    card_id = kwargs.get("card_id")
    stop_checker = kwargs.get("stop_checker")
    if not callable(stop_checker):
        stop_checker = lambda: False
    get_image_data = kwargs.get("get_image_data")

    map_id = parse_map_option(str(params.get("map_option") or ""))
    try:
        if not map_id:
            raise ValueError("未配置地图")
        record = load_map(map_id)
    except Exception:
        logger.exception("地图不存在或无法读取: %s", map_id)
        return handle_failure_action(params, card_id)

    death_templates = [
        image
        for image in (
            _load_image(path, get_image_data)
            for path in _split_paths(params.get("death_image_paths"))
        )
        if image is not None
    ]
    marker = str(params.get("marker_type") or "圆点")
    arrow_path = str(params.get("arrow_template_path") or "").strip()
    arrow_template = _load_image(arrow_path, get_image_data) if arrow_path else None

    validation_error = validate_run(record, death_templates, marker, arrow_template)
    if validation_error is not None:
        logger.error("A*寻路参数校验失败: %s", validation_error)
        return handle_failure_action(params, card_id)

    if not target_hwnd:
        logger.error("A*寻路缺少目标窗口句柄，无法截图")
        return handle_failure_action(params, card_id)

    minimap_x = _as_int(params.get("minimap_x"), 0)
    minimap_y = _as_int(params.get("minimap_y"), 0)
    minimap_width = _as_int(params.get("minimap_width"), 50)
    minimap_height = _as_int(params.get("minimap_height"), 50)

    def capture_frame():
        return capture_window_smart(target_hwnd)

    def capture_minimap():
        frame = capture_frame()
        if frame is None or minimap_width <= 0 or minimap_height <= 0:
            return None
        height, width = frame.shape[:2]
        x1 = max(0, minimap_x)
        y1 = max(0, minimap_y)
        x2 = min(width, minimap_x + minimap_width)
        y2 = min(height, minimap_y + minimap_height)
        if x2 <= x1 or y2 <= y1:
            return None
        return frame[y1:y2, x1:x2].copy()

    key_map = {
        "up": str(params.get("key_up") or "w"),
        "down": str(params.get("key_down") or "s"),
        "left": str(params.get("key_left") or "a"),
        "right": str(params.get("key_right") or "d"),
        "up_left": str(params.get("key_up_left") or "q"),
        "up_right": str(params.get("key_up_right") or "e"),
        "down_left": str(params.get("key_down_left") or "z"),
        "down_right": str(params.get("key_down_right") or "c"),
    }
    config = PathLoopConfig(
        marker=marker,
        map_rotates=str(params.get("map_rotates") or "不转") == "转",
        direction_mode=str(params.get("direction_mode") or "八向"),
        key_map=key_map,
        hold_seconds=_as_float(params.get("hold_seconds"), 0.15),
        match_fail_limit=_as_int(params.get("match_fail_limit"), 8),
        stuck_limit=_as_int(params.get("stuck_limit"), 8),
    )

    def hold_key(key: str, seconds: float) -> bool:
        return hold_key_via_keyboard_task(
            key,
            seconds,
            execution_mode=execution_mode,
            target_hwnd=target_hwnd,
            stop_checker=stop_checker,
        )

    ok, reason = run_path_loop(
        record=record,
        capture_minimap=capture_minimap,
        capture_frame=capture_frame,
        death_templates=death_templates,
        arrow_template=arrow_template,
        config=config,
        hold_key=hold_key,
        persist=save_map,
        stop_checker=stop_checker,
    )
    logger.info("A*寻路结束: %s", reason)
    if ok:
        return handle_success_action(params, card_id, stop_checker)
    return handle_failure_action(params, card_id, stop_checker)
