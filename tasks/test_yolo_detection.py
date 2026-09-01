import inspect

import numpy as np

from tasks.yolo_detection import execute_task, get_params_definition


REMOVED_YOLO_ACTION_KEYS = {
    "---action---",
    "---click_offset---",
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
}

REMOVED_YOLO_CARD_TARGET_KEYS = {
    "---target---",
    "refresh_classes",
    "target_classes",
    "target_selection",
}


class _FakeDetection:
    center_x = 12
    center_y = 34
    x1 = 0
    y1 = 0
    x2 = 24
    y2 = 68
    class_name = "enemy"
    confidence = 0.91
    area = 24 * 68


def test_yolo_params_have_no_mouse_or_key_actions():
    assert REMOVED_YOLO_ACTION_KEYS.isdisjoint(get_params_definition())


def test_yolo_params_have_no_card_target_filters():
    assert REMOVED_YOLO_CARD_TARGET_KEYS.isdisjoint(get_params_definition())


def test_yolo_params_native_backend_only():
    params = get_params_definition()
    assert params["yolo_backend"]["options"] == ["原生"]
    assert params["yolo_backend"]["default"] == "原生"
    assert "condition" not in params["model_path"]
    assert "yolo_url" not in params
    assert "plugin_yolo_url" not in params


def test_yolo_action_helpers_are_gone():
    import tasks.yolo_detection as yolo

    for name in ("_execute_action", "_click", "_keypress", "_mouse_move", "_apply_click_offsets"):
        assert not hasattr(yolo, name)


def test_execute_task_detect_only_ignores_legacy_action_params(monkeypatch):
    click_calls = []

    class _Engine:
        def detect_from_hwnd(self, *args, **kwargs):
            return [_FakeDetection()], np.zeros((80, 80, 3), dtype=np.uint8)

    monkeypatch.setattr("utils.capture.screenshot_helper.get_screenshot_engine", lambda: "wgc")
    monkeypatch.setattr("utils.match.yolo_engine.get_yolo_engine", lambda **kwargs: _Engine())
    monkeypatch.setattr(
        "tasks.click_coordinate._click_with_new_simulator",
        lambda *args, **kwargs: click_calls.append((args, kwargs)) or True,
    )
    monkeypatch.setattr("win32gui.IsWindow", lambda hwnd: True)
    monkeypatch.setattr("win32gui.IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(
        "task_workflow.workflow_context.set_yolo_result",
        lambda *args, **kwargs: None,
    )

    result = execute_task(
        {
            "model_path": "yolo/x.onnx",
            "action_type": "点击",
            "approach_mode": "鼠标移动",
            "click_button": "左键",
            "click_action": "完整点击",
            "keypress_key": "f",
            "on_success": "执行下一步",
            "on_failure": "执行下一步",
        },
        {},
        "foreground",
        12345,
        None,
        card_id=7,
    )

    assert result[0] is True
    assert result[1] == "执行下一步"
    assert click_calls == []
    assert "action_type" not in inspect.signature(execute_task).parameters

