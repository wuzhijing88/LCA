from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import ui.workflow_parts.workflow_view_context_menu_mixin as context_menu_module
from ui.workflow_parts.workflow_view_context_menu_mixin import WorkflowViewContextMenuMixin


class _Action:
    def __init__(self, text):
        self.text = text
        self.enabled = True
        self.tooltip = ""

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def setToolTip(self, tooltip):
        self.tooltip = tooltip


class _Menu:
    selected_text = None
    latest = None

    def __init__(self, *_args, **_kwargs):
        self.actions = []
        type(self).latest = self

    def addAction(self, text):
        action = _Action(text)
        self.actions.append(action)
        return action

    def addSeparator(self):
        return None

    def exec(self, _position):
        return next(
            (action for action in self.actions if action.text == type(self).selected_text),
            None,
        )


class _Card:
    def __init__(self, card_id):
        self.card_id = card_id
        self.parameters = {"value": card_id}
        self.open_parameter_dialog = Mock()


class _Connection:
    pass


class _Scene:
    def __init__(self, selected=None):
        self.selected = list(selected or [])

    def selectedItems(self):
        return list(self.selected)


class _View(WorkflowViewContextMenuMixin):
    def __init__(self, item=None, *, running=False, selected=None):
        self.item = item
        self.running = running
        self.editing_enabled = True
        self.scene = _Scene(selected)
        self.undo_stack = []
        self.main_window = SimpleNamespace(_handle_save_action=Mock())
        self.running_checks = 0
        self.handle_copy_card = Mock()
        self.handle_copy_selected_cards = Mock()
        self._delete_selected_cards = Mock()
        self.handle_rename_card = Mock()
        self.handle_change_card_id = Mock()
        self._handle_test_card = Mock()
        self._handle_test_flow = Mock()
        self.delete_card = Mock()
        self.remove_connection = Mock()
        self.handle_paste_card = Mock()
        self.undo_last_operation = Mock()
        self.fit_view_to_items = Mock()

    def mapToScene(self, _pos):
        return SimpleNamespace(x=lambda: 10, y=lambda: 20)

    def itemAt(self, _pos):
        return self.item

    def mapToGlobal(self, pos):
        return pos

    def _is_workflow_running(self):
        self.running_checks += 1
        return self.running

    def is_paste_available(self):
        return True


@pytest.fixture(autouse=True)
def _replace_menu_types(monkeypatch):
    monkeypatch.setattr(context_menu_module, "TaskCard", _Card)
    monkeypatch.setattr(context_menu_module, "ConnectionLine", _Connection)
    monkeypatch.setattr(context_menu_module, "QMenu", _Menu)
    monkeypatch.setattr(context_menu_module, "apply_unified_menu_style", lambda menu, **_kwargs: menu)
    _Menu.selected_text = None


def test_card_copy_is_dispatched_once_without_using_card_signal():
    card = _Card(7)
    view = _View(card)
    _Menu.selected_text = "复制卡片"

    view.show_context_menu(object())

    view.handle_copy_card.assert_called_once_with(7, card.parameters)
    assert view.running_checks == 1
    assert view.editing_enabled is True


def test_running_state_disables_card_actions_without_mutating_editing_flag():
    card = _Card(1)
    view = _View(card, running=True)

    view.show_context_menu(object())

    assert view.running_checks == 1
    assert view.editing_enabled is True
    assert _Menu.latest.actions
    assert all(not action.enabled for action in _Menu.latest.actions)


def test_right_clicking_unselected_card_does_not_apply_multi_selection_action():
    clicked = _Card(9)
    selected = [_Card(1), _Card(2)]
    view = _View(clicked, selected=selected)
    _Menu.selected_text = "复制卡片"

    view.show_context_menu(object())

    view.handle_copy_card.assert_called_once_with(9, clicked.parameters)
    view.handle_copy_selected_cards.assert_not_called()


def test_connection_delete_is_dispatched_once():
    connection = _Connection()
    view = _View(connection)
    _Menu.selected_text = "删除连接"

    view.show_context_menu(object())

    view.remove_connection.assert_called_once_with(connection)


def test_task_dialog_is_released_after_cancel(monkeypatch):
    dialog = SimpleNamespace(
        exec=Mock(return_value=context_menu_module.QDialog.DialogCode.Rejected),
        selected_task_type=Mock(),
        deleteLater=Mock(),
    )
    monkeypatch.setattr("tasks.get_available_tasks", lambda: ["测试任务"])
    monkeypatch.setattr(context_menu_module, "SelectTaskDialog", lambda *_args: dialog)
    view = _View()
    view.add_task_card = Mock()
    view.update_card_sequence_display = Mock()

    view.prompt_and_add_card_at(SimpleNamespace(x=lambda: 1, y=lambda: 2))

    dialog.deleteLater.assert_called_once_with()
    view.add_task_card.assert_not_called()


def test_task_dialog_adds_exactly_one_card_and_is_released(monkeypatch):
    dialog = SimpleNamespace(
        exec=Mock(return_value=context_menu_module.QDialog.DialogCode.Accepted),
        selected_task_type=Mock(return_value="测试任务"),
        deleteLater=Mock(),
    )
    monkeypatch.setattr("tasks.get_available_tasks", lambda: ["测试任务"])
    monkeypatch.setattr(context_menu_module, "SelectTaskDialog", lambda *_args: dialog)
    view = _View()
    view.add_task_card = Mock(return_value=object())
    view.update_card_sequence_display = Mock()

    view.prompt_and_add_card_at(SimpleNamespace(x=lambda: 1, y=lambda: 2))

    view.add_task_card.assert_called_once_with(1, 2, task_type="测试任务")
    view.update_card_sequence_display.assert_called_once_with()
    dialog.deleteLater.assert_called_once_with()
