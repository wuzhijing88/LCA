from unittest.mock import patch

from app_core.runtime.task_state_manager import TaskStateManager


def test_task_state_manager_preserves_state_and_signal_contract(qt_application):
    manager = TaskStateManager()
    observed_states = []
    manager.task_state_changed.connect(observed_states.append)

    try:
        assert manager.get_current_state() == "stopped"
        assert manager.request_start() is True
        manager.confirm_started()
        assert manager.is_running() is True
        assert manager.request_stop() is True

        with (
            patch(
                "app_core.runtime.task_state_manager.cleanup_yolo_runtime_resources",
                return_value=False,
            ) as cleanup_yolo,
            patch.object(manager, "_start_background_thread", return_value=None),
        ):
            manager.confirm_stopped()
            manager.confirm_stopped()

        assert cleanup_yolo.call_count == 1
        assert manager.get_current_state() == "stopped"
        assert manager.is_state_changing() is False
        assert observed_states == ["starting", "running", "stopping", "stopped"]
    finally:
        manager.shutdown(timeout=0)
