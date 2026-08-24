from types import SimpleNamespace

import pytest

import ui.workflow_parts.workflow_view_connection_sequence_mixin as sequence_module
from ui.workflow_parts.workflow_view_connection_sequence_mixin import WorkflowViewConnectionSequenceMixin


class _Card:
    def __init__(self, card_id, task_type, scene):
        self.card_id = card_id
        self.task_type = task_type
        self._scene = scene
        self.display_ids = []

    def scene(self):
        return self._scene

    def set_display_id(self, display_id):
        self.display_ids.append(display_id)


class _Connection:
    def __init__(self, start_item, end_item, line_type="sequential"):
        self.start_item = start_item
        self.end_item = end_item
        self.line_type = line_type


def _view(cards, connections):
    view = SimpleNamespace(
        cards={card.card_id: card for card in cards},
        connections=list(connections),
        scene=cards[0].scene() if cards else object(),
        _updating_sequence=False,
        validate_connections=lambda: 0,
        _is_start_task_type=lambda task_type: task_type == "线程起点",
    )
    return view


def test_sequence_numbering_starts_from_every_thread_start(monkeypatch):
    monkeypatch.setattr(sequence_module, "TaskCard", _Card)
    monkeypatch.setattr(sequence_module, "ConnectionLine", _Connection)
    scene = object()
    first_start = _Card(3, "线程起点", scene)
    first_task = _Card(4, "任务", scene)
    second_start = _Card(8, "线程起点", scene)
    second_task = _Card(9, "任务", scene)
    view = _view(
        [first_start, first_task, second_start, second_task],
        [_Connection(first_start, first_task), _Connection(second_start, second_task)],
    )

    assert WorkflowViewConnectionSequenceMixin.update_card_sequence_display(view) == 4
    assert first_start.display_ids == [None, 0]
    assert second_start.display_ids == [None, 1]
    assert first_task.display_ids == [None, 2]
    assert second_task.display_ids == [None, 3]


def test_sequence_update_flag_is_restored_after_validation_failure():
    view = SimpleNamespace(
        cards={},
        connections=[],
        _updating_sequence=False,
        validate_connections=lambda: 1,
    )

    with pytest.raises(RuntimeError, match="连线状态存在 1 项错误"):
        WorkflowViewConnectionSequenceMixin.update_card_sequence_display(view)
    assert view._updating_sequence is False


def test_sequence_update_rejects_reentry():
    view = SimpleNamespace(_updating_sequence=True, cards={}, connections=[])

    with pytest.raises(RuntimeError, match="拒绝重复进入"):
        WorkflowViewConnectionSequenceMixin.update_card_sequence_display(view)
