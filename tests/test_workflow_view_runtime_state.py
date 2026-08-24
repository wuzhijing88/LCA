from types import SimpleNamespace

import pytest

from ui.workflow_parts.workflow_view_render_mixin import WorkflowViewRenderMixin


class _StateManager:
    def __init__(self, state):
        self.state = state

    def get_current_state(self):
        return self.state


def _view(state):
    return SimpleNamespace(
        main_window=SimpleNamespace(task_state_manager=_StateManager(state)),
        _is_workflow_running=lambda: None,
    )


@pytest.mark.parametrize("state", ["starting", "running", "stopping"])
def test_workflow_running_for_non_stopped_states(state):
    view = _view(state)

    assert WorkflowViewRenderMixin._is_workflow_running(view) is True


def test_workflow_not_running_when_stopped():
    view = _view("stopped")

    assert WorkflowViewRenderMixin._is_workflow_running(view) is False


def test_workflow_state_requires_bound_main_window():
    view = SimpleNamespace(main_window=None)

    with pytest.raises(RuntimeError, match="未绑定主窗口"):
        WorkflowViewRenderMixin._is_workflow_running(view)


def test_workflow_state_rejects_unknown_state():
    view = _view("paused")

    with pytest.raises(RuntimeError, match="未知的任务运行状态"):
        WorkflowViewRenderMixin._is_workflow_running(view)


def test_edit_is_blocked_only_while_runtime_is_active():
    running_view = SimpleNamespace(_is_workflow_running=lambda: True)
    stopped_view = SimpleNamespace(_is_workflow_running=lambda: False)

    assert WorkflowViewRenderMixin._block_edit_if_running(running_view, "删除卡片") is True
    assert WorkflowViewRenderMixin._block_edit_if_running(stopped_view, "删除卡片") is False


def test_edit_block_requires_operation_name():
    view = SimpleNamespace(_is_workflow_running=lambda: False)

    with pytest.raises(TypeError, match="非空字符串"):
        WorkflowViewRenderMixin._block_edit_if_running(view, "")
