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
DEFAULT_COORDINATE_SOURCE_MODE = "坐标工具获取坐标"
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
    "refresh_classes",
    "target_classes",
    "target_selection",
)


def sanitize_card_parameters(parameters: Any, task_type: Any = "") -> Dict[str, Any]:
    if not isinstance(parameters, Mapping):
        return {}
    cleaned = dict(parameters)
    for key in DEAD_CARD_PARAM_KEYS:
        cleaned.pop(key, None)
    if str(task_type or "").strip() == YOLO_TASK_TYPE:
        for key in YOLO_REMOVED_ACTION_PARAM_KEYS:
            cleaned.pop(key, None)
    source_mode = str(cleaned.get("coordinate_source_mode") or "").strip()
    if source_mode in REMOVED_COORDINATE_SOURCE_MODES:
        cleaned["coordinate_source_mode"] = DEFAULT_COORDINATE_SOURCE_MODE
    return cleaned


def sanitize_workflow_data(workflow_data: Any) -> Any:
    if not isinstance(workflow_data, dict):
        return workflow_data

    for key in DEAD_WORKFLOW_KEYS:
        workflow_data.pop(key, None)

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
