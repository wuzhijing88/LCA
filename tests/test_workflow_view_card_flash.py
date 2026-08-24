from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ui.workflow_parts.task_card import TaskCard
from ui.workflow_parts.workflow_view_render_mixin import WorkflowViewRenderMixin
from ui.workflow_parts.workflow_view_card_layout_mixin import WorkflowViewCardLayoutMixin


class _Card:
    def __init__(self, scene):
        self._scene = scene
        self.flash = Mock()
        self.stop_flash = Mock()

    def scene(self):
        return self._scene


def _view(scene, cards, flashing=None):
    view = SimpleNamespace(
        scene=scene,
        cards=cards,
        connections=[],
        flashing_card_ids=set(flashing or ()),
    )
    view._stop_all_flashing = lambda: WorkflowViewRenderMixin._stop_all_flashing(view)
    return view


def test_stop_all_flashing_stops_registered_cards_once():
    scene = object()
    cards = {1: _Card(scene), 2: _Card(scene)}
    view = _view(scene, cards, flashing={2, 1})

    assert WorkflowViewRenderMixin._stop_all_flashing(view) == 2
    assert view.flashing_card_ids == set()
    cards[1].stop_flash.assert_called_once_with()
    cards[2].stop_flash.assert_called_once_with()


def test_stop_all_flashing_rejects_stale_registration():
    scene = object()
    view = _view(scene, {}, flashing={9})

    with pytest.raises(RuntimeError, match="未登记"):
        WorkflowViewRenderMixin._stop_all_flashing(view)
    assert view.flashing_card_ids == {9}


def test_click_rejects_unknown_card_without_starting_flash():
    view = _view(object(), {})

    assert WorkflowViewRenderMixin._handle_card_clicked(view, 3) is False


def test_click_rejects_invalid_connection_object():
    scene = object()
    card = _Card(scene)
    view = _view(scene, {1: card})
    view.connections = [object()]

    with pytest.raises(TypeError, match="无效对象"):
        WorkflowViewRenderMixin._handle_card_clicked(view, 1)


def test_clear_workflow_stops_flashing_before_scene_clear():
    scene = SimpleNamespace(clear=Mock())
    view = SimpleNamespace(
        cards={},
        connections=[],
        scene=scene,
        undo_stack=[],
        _next_card_id=4,
        _max_loaded_id=3,
        _loading_workflow=True,
        _is_workflow_running=lambda: False,
        _stop_all_flashing=Mock(return_value=2),
        _sync_connections_with_scene=Mock(),
        _update_card_render_cache_policy=Mock(),
    )

    assert WorkflowViewCardLayoutMixin.clear_workflow(view) is True
    view._stop_all_flashing.assert_called_once_with()
    scene.clear.assert_called_once_with()


def test_task_card_flash_marks_state_only_after_timer_starts():
    events = []
    timer = SimpleNamespace(start=lambda interval: events.append(("start", interval)))
    card = SimpleNamespace(
        _is_flashing=False,
        _ensure_flash_timer=lambda: timer,
        flash_interval_ms=300,
        execution_state="success",
        state_border_pens={"success": "success-border"},
        _original_border_pen_before_flash=None,
        _flash_border_on=False,
        _current_border_pen=None,
        flash_border_pen="flash-border",
        _is_animation_visible=lambda: True,
        update=lambda: events.append(("update", None)),
    )

    assert TaskCard.flash(card) is True
    assert events == [("start", 300), ("update", None)]
    assert card._is_flashing is True
    assert card._original_border_pen_before_flash == "success-border"


def test_task_card_flash_does_not_mark_state_when_timer_start_fails():
    def fail_start(_interval):
        raise RuntimeError("timer failed")

    timer = SimpleNamespace(start=fail_start)
    card = SimpleNamespace(
        _is_flashing=False,
        _ensure_flash_timer=lambda: timer,
        flash_interval_ms=300,
    )

    with pytest.raises(RuntimeError, match="timer failed"):
        TaskCard.flash(card)
    assert card._is_flashing is False


def test_flash_callback_stops_timer_when_flash_is_inactive():
    timer = SimpleNamespace(stop=Mock())
    card = SimpleNamespace(_is_flashing=False, flash_toggle_timer=timer)

    assert TaskCard._toggle_flash_border(card) is False
    timer.stop.assert_called_once_with()
