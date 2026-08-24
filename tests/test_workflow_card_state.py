from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ui.workflow_parts.task_card import TaskCard
from ui.workflow_parts.workflow_view_card_layout_mixin import WorkflowViewCardLayoutMixin


class _Card:
    def __init__(self, scene):
        self._scene = scene
        self.set_execution_state = Mock(return_value=True)
        self.sceneBoundingRect = Mock(return_value="card-rect")
        self.stop_flash = Mock()

    def scene(self):
        return self._scene


def _view_with_cards(cards):
    scene = SimpleNamespace(update=Mock())
    viewport = SimpleNamespace(update=Mock())
    view = SimpleNamespace(
        cards=cards,
        scene=scene,
        viewport=Mock(return_value=viewport),
    )
    view.set_card_state = lambda card_id, state: WorkflowViewCardLayoutMixin.set_card_state(
        view, card_id, state
    )
    return view, scene, viewport


def test_set_card_state_updates_card_and_viewport():
    view, scene, viewport = _view_with_cards({})
    card = _Card(scene)
    view.cards[3] = card

    assert WorkflowViewCardLayoutMixin.set_card_state(view, 3, "success") is True
    card.set_execution_state.assert_called_once_with("success")
    scene.update.assert_called_once_with("card-rect")
    viewport.update.assert_called_once_with()


def test_set_card_state_rejects_invalid_state():
    view, _, _ = _view_with_cards({})

    with pytest.raises(ValueError, match="无效的卡片执行状态"):
        WorkflowViewCardLayoutMixin.set_card_state(view, 0, "running")


def test_set_card_state_rejects_card_from_another_scene():
    view, _, _ = _view_with_cards({})
    view.cards[1] = _Card(SimpleNamespace())

    with pytest.raises(RuntimeError, match="不属于当前工作流场景"):
        WorkflowViewCardLayoutMixin.set_card_state(view, 1, "executing")


def test_reset_card_states_updates_and_stops_each_card_once():
    view, scene, _ = _view_with_cards({})
    cards = {1: _Card(scene), 2: _Card(scene)}
    view.cards.update(cards)

    WorkflowViewCardLayoutMixin.reset_card_states(view)

    for card in cards.values():
        card.set_execution_state.assert_called_once_with("idle")
        card.stop_flash.assert_called_once_with()


def test_task_card_state_change_updates_flash_restore_border():
    card = SimpleNamespace(
        VALID_EXECUTION_STATES=TaskCard.VALID_EXECUTION_STATES,
        card_id=8,
        execution_state="executing",
        state_colors={"success": "success-color"},
        state_border_pens={"success": "success-border"},
        _cached_bg_color=None,
        _cached_border_pen=None,
        _is_flashing=True,
        _flash_border_on=False,
        _original_border_pen_before_flash="executing-border",
        _current_border_pen="executing-border",
        update=Mock(),
    )

    assert TaskCard.set_execution_state(card, "success") is True
    assert card.execution_state == "success"
    assert card._original_border_pen_before_flash == "success-border"
    assert card._current_border_pen == "success-border"
    card.update.assert_called_once_with()
