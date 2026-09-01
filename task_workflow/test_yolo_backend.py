import pytest

from task_workflow.script_commands import CommandHost, build_yolo_params, resolve_yolo_model
from task_workflow.yolo_backend import YOLO_BACKEND_NATIVE, normalize_yolo_backend, resolve_workflow_yolo_backend


def test_normalize_yolo_backend_maps_plugin_to_native():
    assert normalize_yolo_backend(None) == YOLO_BACKEND_NATIVE
    assert normalize_yolo_backend("插件") == YOLO_BACKEND_NATIVE
    assert normalize_yolo_backend("plugin") == YOLO_BACKEND_NATIVE
    assert normalize_yolo_backend("op") == YOLO_BACKEND_NATIVE


def test_resolve_workflow_yolo_backend_accepts_legacy_plugin_card():
    cards = {1: {"task_type": "YOLO目标检测", "parameters": {"yolo_backend": "插件"}}}
    assert resolve_workflow_yolo_backend(cards) == YOLO_BACKEND_NATIVE


def test_resolve_workflow_yolo_backend_requires_one_card():
    with pytest.raises(ValueError, match="YOLO"):
        resolve_workflow_yolo_backend({})


def test_build_yolo_params_records_backend_and_model():
    params = build_yolo_params(类别="敌人", 阈值=0.6, 后端="插件", 模型="yolo/x.onnx")
    assert params["yolo_backend"] == "原生"
    assert params["target_classes"] == "敌人"
    assert params["model_path"] == "yolo/x.onnx"


def test_detect_normalizes_legacy_plugin_card_to_native():
    ran = []
    host = CommandHost(
        store=type("S", (), {"last": lambda self: {}, "publish": lambda *a, **k: None})(),
        context={"executor": type("E", (), {"cards_data": {
            1: {
                "task_type": "YOLO目标检测",
                "parameters": {"yolo_backend": "插件", "model_path": "yolo/card.onnx"},
            },
        }})()},
    )
    host._run = lambda task_type, params: ran.append(params) or True
    assert host.检测(类别="敌人") is True
    assert ran[0]["yolo_backend"] == "原生"
    assert ran[0]["model_path"] == "yolo/card.onnx"
    assert ran[0]["target_classes"] == "敌人"


def test_detect_requires_model_when_card_has_none():
    host = CommandHost(
        store=type("S", (), {"last": lambda self: {}, "publish": lambda *a, **k: None})(),
        context={"executor": type("E", (), {"cards_data": {
            1: {"task_type": "YOLO目标检测", "parameters": {"yolo_backend": "插件"}},
        }})()},
    )
    with pytest.raises(ValueError, match="onnx"):
        host.检测()


def test_native_detect_still_requires_onnx():
    with pytest.raises(ValueError, match="onnx"):
        resolve_yolo_model("", {"yolo_backend": "原生"})
