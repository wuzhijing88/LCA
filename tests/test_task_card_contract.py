from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import ui.workflow_parts.task_card as task_card_module
from ui.workflow_parts.task_card import TaskCard


def test_parameter_definitions_must_use_current_dict_format():
    card = SimpleNamespace(
        card_id=1,
        task_type="测试任务",
        task_module=SimpleNamespace(get_params_definition=lambda: [{"name": "value"}]),
        parameters={},
    )

    with pytest.raises(TypeError, match="参数定义必须是字典"):
        TaskCard.load_and_create_parameters(card)


def test_card_running_state_does_not_fall_back_to_editable():
    card = SimpleNamespace(card_id=1, view=None)

    with pytest.raises(RuntimeError, match="未绑定工作流运行状态入口"):
        TaskCard._is_workflow_running(card)


@pytest.mark.parametrize("value", [0, "0", "找图点击", "图片点击", "找色点击", ""])
def test_tooltip_operation_mode_rejects_legacy_values(value):
    with pytest.raises(ValueError, match="无效的鼠标操作模式"):
        TaskCard._normalize_operation_mode_for_tooltip(SimpleNamespace(), value)


def test_tooltip_condition_rejects_invalid_structure():
    card = SimpleNamespace(parameters={"operation_mode": "坐标点击"})
    card._normalize_operation_mode_for_tooltip = lambda value: (
        TaskCard._normalize_operation_mode_for_tooltip(card, value)
    )

    with pytest.raises(TypeError, match="必须包含 param 和 value"):
        TaskCard._tooltip_condition_matches(card, {"param": "operation_mode"})


def test_port_restriction_conflict_is_rejected_without_deleting_connection(monkeypatch):
    scene = object()
    connection = SimpleNamespace(
        start_item=None,
        line_type="success",
        scene=Mock(return_value=scene),
        update_path=Mock(),
    )
    card = SimpleNamespace(
        card_id=3,
        restricted_outputs=False,
        connections=[connection],
        scene=Mock(return_value=scene),
        update=Mock(),
        _calculate_restricted_outputs=Mock(return_value=True),
    )
    connection.start_item = card
    monkeypatch.setattr(task_card_module, "_qt_is_valid", lambda _item: True)

    with pytest.raises(RuntimeError, match="端口能力冲突"):
        TaskCard.update_port_restrictions(card)

    assert card.connections == [connection]
    assert card.restricted_outputs is False
    connection.update_path.assert_not_called()


def test_timer_cleanup_disconnects_only_its_owned_slot():
    slot = Mock()
    timer = SimpleNamespace(
        stop=Mock(),
        timeout=SimpleNamespace(disconnect=Mock()),
        deleteLater=Mock(),
    )
    card = SimpleNamespace(_drag_check_timer=timer)

    TaskCard._cleanup_timer_attr(card, "_drag_check_timer", slot)

    timer.stop.assert_called_once_with()
    timer.timeout.disconnect.assert_called_once_with(slot)
    timer.deleteLater.assert_called_once_with()
    assert card._drag_check_timer is None
