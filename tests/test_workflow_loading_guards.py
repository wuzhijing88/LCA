import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from ui.main_window_parts.main_window_favorites_batch_mixin import MainWindowFavoritesBatchMixin
from ui.workflow_parts.workflow_tab_widget import WorkflowTabWidget
from ui.workflow_parts.workflow_view_card_layout_mixin import WorkflowViewCardLayoutMixin


class WorkflowLoadingGuardTests(unittest.TestCase):
    def test_global_running_state_blocks_import(self):
        state_manager = SimpleNamespace(get_current_state=lambda: "running")
        widget = SimpleNamespace(window=lambda: SimpleNamespace(task_state_manager=state_manager))
        self.assertTrue(WorkflowTabWidget._global_runtime_blocks_import(widget))

    def test_global_stopped_state_allows_import(self):
        state_manager = SimpleNamespace(get_current_state=lambda: "stopped")
        widget = SimpleNamespace(window=lambda: SimpleNamespace(task_state_manager=state_manager))
        self.assertFalse(WorkflowTabWidget._global_runtime_blocks_import(widget))

    def test_loading_can_clear_new_view_while_global_state_is_running(self):
        scene = SimpleNamespace(clear=Mock())
        view = SimpleNamespace(
            _loading_workflow=True,
            _is_workflow_running=Mock(side_effect=AssertionError("loading must not consult runtime state")),
            _stop_all_flashing=Mock(),
            _sync_connections_with_scene=Mock(),
            cards={},
            connections=[],
            scene=scene,
            undo_stack=[],
            _update_card_render_cache_policy=Mock(),
        )
        self.assertTrue(WorkflowViewCardLayoutMixin.clear_workflow(view))
        scene.clear.assert_called_once_with()

    def test_empty_batch_restores_global_stopped_state(self):
        state_manager = SimpleNamespace(confirm_stopped=Mock())
        window = SimpleNamespace(
            task_manager=SimpleNamespace(has_active_runtime_tasks=lambda: False),
            task_state_manager=state_manager,
            _reset_run_button=Mock(),
            _floating_controller=None,
        )
        MainWindowFavoritesBatchMixin._finish_batch_execute(window)
        state_manager.confirm_stopped.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
