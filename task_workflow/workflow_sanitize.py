from __future__ import annotations

from typing import Any, Dict, Mapping

DEAD_WORKFLOW_KEYS = ("variables",)
DEAD_CARD_PARAM_KEYS = (
    "save_result_variable_name",
    "save_result_variable_mode",
    "_save_result_variable_seeded",
    "coordinate_x_var",
    "coordinate_y_var",
    "save_to_variable",
    "ocr_variable_names",
    "input_bindings",
    "output_bindings",
    "variable_scope",
    "countdown_variable",
)
REMOVED_COORDINATE_SOURCE_MODES = ("通过变量",)
YOLO_TASK_TYPE = "YOLO目标检测"
YOLO_REMOVED_ACTION_PARAM_KEYS = (
    "---action---",
    "---click_offset---",
    "---target---",
    "action_type",
    "approach_mode",
    "click_action",
    "click_button",
    "click_enable_auto_release",
    "click_hold_duration",
    "fixed_offset_x",
    "fixed_offset_y",
    "keypress_key",
    "offset_selector_tool",
    "position_mode",
    "random_offset_x",
    "random_offset_y",
    "target_selection",
)


def sanitize_card_parameters(parameters: Any, task_type: Any = "") -> Dict[str, Any]:
    """校验现行参数；旧字段必须先经工程转换层迁移。"""
    if not isinstance(parameters, Mapping):
        raise ValueError("卡片参数必须是对象")
    cleaned = dict(parameters)
    removed = [key for key in DEAD_CARD_PARAM_KEYS if key in cleaned]
    if str(task_type or "").strip() == YOLO_TASK_TYPE:
        removed.extend(key for key in YOLO_REMOVED_ACTION_PARAM_KEYS if key in cleaned)
    if removed:
        raise ValueError(f"卡片参数含有旧字段：{'、'.join(removed)}，请先转换为现行工程格式")
    if cleaned.get("coordinate_source_mode") in REMOVED_COORDINATE_SOURCE_MODES:
        raise ValueError("旧坐标来源无法直接使用，请先转换为现行工程格式")
    return cleaned


def sanitize_workflow_data(workflow_data: Any) -> Any:
    if not isinstance(workflow_data, dict):
        return workflow_data

    if any(key in workflow_data for key in DEAD_WORKFLOW_KEYS):
        raise ValueError("工作流含有旧字段，请先转换为现行工程格式")

    nested = workflow_data.get("workflow")
    if isinstance(nested, dict) and nested is not workflow_data:
        sanitize_workflow_data(nested)

    cards = workflow_data.get("cards")
    if isinstance(cards, list):
        for card in cards:
            if not isinstance(card, dict):
                continue
            card["parameters"] = sanitize_card_parameters(
                card.get("parameters"),
                card.get("task_type"),
            )
    return workflow_data
