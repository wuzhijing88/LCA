from types import SimpleNamespace
from unittest.mock import Mock

import ui.workflow_parts.workflow_view_connection_core_mixin as connection_core_module
from ui.workflow_parts.workflow_view_connection_core_mixin import WorkflowViewConnectionCoreMixin


class _Card:
    def __init__(self, card_id, parameters):
        self.card_id = card_id
        self.parameters = parameters


def _card(card_id, parameters):
    return _Card(card_id, parameters)


def _view(connections=()):
    view = SimpleNamespace(connections=list(connections))
    view._refresh_connection_parameter_display = Mock()
    view._JUMP_PARAMETER_KEYS = WorkflowViewConnectionCoreMixin._JUMP_PARAMETER_KEYS
    return view


def test_remove_success_connection_keeps_parameter_retargeted_elsewhere(monkeypatch):
    monkeypatch.setattr(connection_core_module, "TaskCard", _Card)
    source = _card(1, {"on_success": "跳转到步骤", "success_jump_target_id": 9})
    removed_target = _card(2, {})
    connection = SimpleNamespace(start_item=source, end_item=removed_target, line_type="success")
    view = _view([connection])

    assert WorkflowViewConnectionCoreMixin._clear_jump_parameters_for_connection(view, connection) is False
    assert source.parameters == {"on_success": "跳转到步骤", "success_jump_target_id": 9}
    view._refresh_connection_parameter_display.assert_not_called()


def test_remove_failure_connection_clears_its_matching_target(monkeypatch):
    monkeypatch.setattr(connection_core_module, "TaskCard", _Card)
    source = _card(1, {"on_failure": "跳转到步骤", "failure_jump_target_id": 2})
    removed_target = _card(2, {})
    connection = SimpleNamespace(start_item=source, end_item=removed_target, line_type="failure")
    view = _view([connection])

    assert WorkflowViewConnectionCoreMixin._clear_jump_parameters_for_connection(view, connection) is True
    assert source.parameters == {"on_failure": "执行下一步", "failure_jump_target_id": None}
    view._refresh_connection_parameter_display.assert_called_once_with(source)
