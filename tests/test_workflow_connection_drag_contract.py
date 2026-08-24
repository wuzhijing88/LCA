from types import SimpleNamespace

import pytest

from ui.workflow_parts.workflow_view_connection_drag_mixin import WorkflowViewConnectionDragMixin


class _TempLine:
    def __init__(self, scene):
        self._scene = scene

    def scene(self):
        return self._scene


def _view():
    view = SimpleNamespace(
        temp_line=None,
        is_dragging_line=False,
        drag_start_card=None,
        drag_start_port_type=None,
        is_snapped=False,
        snapped_target_card=None,
        _original_drag_mode="original",
        setDragMode=lambda mode: setattr(view, "drag_mode", mode),
        scene=object(),
    )
    return view


def test_cleanup_drag_state_resets_state_before_reporting_foreign_scene():
    view = _view()
    view.temp_line = _TempLine(object())
    view.is_dragging_line = True
    view.drag_start_card = object()
    view.drag_start_port_type = "sequential"
    view.is_snapped = True
    view.snapped_target_card = object()

    with pytest.raises(RuntimeError, match="其他场景"):
        WorkflowViewConnectionDragMixin._cleanup_drag_state(view)

    assert view.temp_line is None
    assert view.is_dragging_line is False
    assert view.drag_start_card is None
    assert view.drag_start_port_type is None
    assert view.is_snapped is False
    assert view.snapped_target_card is None
    assert view.drag_mode == "original"
