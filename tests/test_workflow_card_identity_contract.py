import pytest

import ui.workflow_parts.workflow_view_identity_mixin as identity_module
from ui.workflow_parts.workflow_view_identity_mixin import WorkflowViewIdentityMixin
from ui.workflow_parts.workflow_view_undo_apply_mixin import WorkflowViewUndoApplyMixin


class _Card:
    def __init__(self, card_id, parameters=None, param_definitions=None):
        self.card_id = card_id
        self.parameters = parameters or {}
        self.param_definitions = param_definitions or {}
        self.sequence_id = None
        self.custom_name = None
        self.task_type = "测试卡片"

    def set_display_id(self, _sequence_id):
        return None

    def update(self):
        return None


class _View(WorkflowViewIdentityMixin):
    def __init__(self, cards):
        self.cards = {card.card_id: card for card in cards}
        self.flashing_card_ids = set()
        self.main_window = None
        self.saved_undo_states = []

    def _refresh_thread_start_custom_names(self):
        return None

    def _save_undo_state(self, operation_type, operation_data):
        self.saved_undo_states.append((operation_type, operation_data))


def _view(cards):
    return _View(cards)


def _apply(view, mapping, monkeypatch):
    monkeypatch.setattr(identity_module, "TaskCard", _Card)
    return WorkflowViewIdentityMixin._apply_card_id_mapping(view, mapping)


def test_swap_card_ids_remaps_references_once(monkeypatch):
    first = _Card(1)
    second = _Card(2)
    source = _Card(
        3,
        {
            "on_success": "跳转到步骤",
            "success_jump_target_id": 1,
            "on_failure": "跳转到步骤",
            "failure_jump_target_id": 2,
        },
        {
            "success_jump_target_id": {"widget_hint": "card_selector"},
            "failure_jump_target_id": {"widget_hint": "card_selector"},
        },
    )
    random_card = _Card(
        4,
        {
            "random_weights": {"1": 10, "2": 20},
            "_random_connections": [{"card_id": 1}, {"card_id": 2}],
        },
    )
    view = _view([first, second, source, random_card])

    _apply(view, {1: 2, 2: 1}, monkeypatch)

    assert view.cards[2] is first
    assert view.cards[1] is second
    assert source.parameters["success_jump_target_id"] == 2
    assert source.parameters["failure_jump_target_id"] == 1
    assert random_card.parameters["random_weights"] == {"2": 10, "1": 20}
    assert random_card.parameters["_random_connections"] == [{"card_id": 2}, {"card_id": 1}]


def test_change_card_id_does_not_guess_coordinate_fields_as_references(monkeypatch):
    card = _Card(1, {"coordinate_x": 1, "coordinate_y": 1})
    view = _view([card])

    _apply(view, {1: 7}, monkeypatch)

    assert card.parameters["coordinate_x"] == 1
    assert card.parameters["coordinate_y"] == 1


def test_reverse_mapping_restores_ids_and_references(monkeypatch):
    target = _Card(1)
    source = _Card(
        2,
        {"on_success": "跳转到步骤", "success_jump_target_id": 1},
        {"success_jump_target_id": {"widget_hint": "card_selector"}},
    )
    view = _view([target, source])

    _apply(view, {1: 7}, monkeypatch)
    _apply(view, {7: 1}, monkeypatch)

    assert view.cards == {1: target, 2: source}
    assert source.parameters["success_jump_target_id"] == 1


def test_swap_is_one_undo_step_and_restores_all_references(monkeypatch):
    monkeypatch.setattr(identity_module, "TaskCard", _Card)
    first = _Card(0)
    second = _Card(7)
    source = _Card(
        8,
        {"on_success": "跳转到步骤", "success_jump_target_id": 0},
        {"success_jump_target_id": {"widget_hint": "card_selector"}},
    )
    view = _view([first, second, source])

    view._swap_card_ids(first, second)

    assert view.saved_undo_states == [("change_card_ids", {"id_mapping": {0: 7, 7: 0}})]
    assert source.parameters["success_jump_target_id"] == 7

    WorkflowViewUndoApplyMixin._undo_change_card_ids(
        view,
        view.saved_undo_states[0][1],
    )

    assert view.cards == {0: first, 7: second, 8: source}
    assert source.parameters["success_jump_target_id"] == 0


def test_conflicting_id_mapping_is_rejected_without_mutation(monkeypatch):
    first = _Card(1)
    second = _Card(2)
    view = _view([first, second])

    with pytest.raises(ValueError, match="发生冲突"):
        _apply(view, {1: 2}, monkeypatch)

    assert view.cards == {1: first, 2: second}
    assert first.card_id == 1
    assert second.card_id == 2


def test_active_missing_reference_is_rejected_without_cleanup(monkeypatch):
    source = _Card(
        1,
        {"on_success": "跳转到步骤", "success_jump_target_id": 9},
        {
            "success_jump_target_id": {
                "widget_hint": "card_selector",
                "condition": {"param": "on_success", "value": "跳转到步骤"},
            }
        },
    )
    view = _view([source])
    monkeypatch.setattr(identity_module, "TaskCard", _Card)

    with pytest.raises(ValueError, match="指向不存在的卡片 9"):
        WorkflowViewIdentityMixin._validate_card_references(view)

    assert source.parameters["success_jump_target_id"] == 9


def test_inactive_reference_still_requires_current_integer_format(monkeypatch):
    source = _Card(
        1,
        {"on_success": "执行下一步", "success_jump_target_id": "9"},
        {
            "success_jump_target_id": {
                "widget_hint": "card_selector",
                "condition": {"param": "on_success", "value": "跳转到步骤"},
            }
        },
    )
    view = _view([source])
    monkeypatch.setattr(identity_module, "TaskCard", _Card)

    with pytest.raises(TypeError, match="必须是非负整数或 None"):
        view._validate_card_references()

    assert source.parameters["success_jump_target_id"] == "9"
