import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from task_workflow.workflow_context import (
    WorkflowContext,
    clear_workflow_context,
    get_current_workflow_context,
    get_workflow_context,
    set_current_workflow_context,
)
from tasks import sub_workflow_task
from utils.sub_workflow_path import resolve_sub_workflow_path


class _DummySignal:
    def connect(self, *_args, **_kwargs):
        return None


class _RecordingSignal:
    def __init__(self):
        self.connections = []
        self.emitted = []

    def connect(self, slot, *_args, **_kwargs):
        self.connections.append(slot)

    def emit(self, *args):
        self.emitted.append(args)
        for slot in list(self.connections):
            slot(*args)


class SubWorkflowPathTests(unittest.TestCase):
    def test_resolve_recovers_old_absolute_path_by_parent_workflow_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workflows_dir = Path(temp_dir) / "workflows"
            workflows_dir.mkdir()
            parent_path = workflows_dir / "main.json"
            child_path = workflows_dir / "child.json"
            parent_path.write_text("{}", encoding="utf-8")
            child_path.write_text("{}", encoding="utf-8")

            resolved = resolve_sub_workflow_path(
                r"C:\Users\admin\Desktop\LCA\child.json",
                parent_workflow_file=str(parent_path),
            )

            self.assertEqual(Path(resolved), child_path)


class SubWorkflowExecutionTests(unittest.TestCase):
    def test_execute_task_rejects_nested_sub_workflow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            child_path = Path(temp_dir) / "child.json"
            child_path.write_text(
                json.dumps(
                    {
                        "cards": [
                            {"id": 1, "task_type": "线程起点", "parameters": {}},
                            {
                                "id": 2,
                                "task_type": "子工作流",
                                "parameters": {"workflow_file": "other.json"},
                            },
                        ],
                        "connections": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with mock.patch.object(sub_workflow_task, "_execute_sub_workflow") as execute_sub:
                result = sub_workflow_task.execute_task(
                    {
                        "workflow_file": str(child_path),
                        "on_failure": "停止工作流",
                    },
                    {},
                    card_id=9,
                )

            self.assertEqual(result, (False, "停止工作流", None))
            execute_sub.assert_not_called()

    def test_sub_workflow_binds_current_context_for_child_task_modules(self):
        parent_context = WorkflowContext(workflow_id="parent-test")
        previous_context = get_workflow_context()
        seen_contexts = []
        captured_kwargs = []
        captured_notes = []
        parent_executor = mock.Mock()
        parent_executor.step_log = _DummySignal()
        parent_executor.target_window_title = "win"

        class FakeWorkflowExecutor:
            def __init__(self, **kwargs):
                captured_kwargs.append(kwargs)
                self._last_execution_success = True
                self.step_log = _DummySignal()
                self._persistent_counters = {}

            def run(self):
                from task_workflow.workflow_context import get_current_workflow_context

                context = get_current_workflow_context()
                seen_contexts.append(context)
                context.set_card_data(7, "note", "ok")
                captured_notes.append(context.get_card_data(7, "note"))

        try:
            set_current_workflow_context(parent_context)
            cards = [
                {"id": 6, "task_type": "线程起点", "parameters": {}},
                {"id": 7, "task_type": "延迟", "parameters": {}},
            ]

            with mock.patch("task_workflow.executor.WorkflowExecutor", FakeWorkflowExecutor):
                success = sub_workflow_task._execute_sub_workflow(
                    cards=cards,
                    connections=[{"start_card_id": 6, "end_card_id": 7, "type": "sequential"}],
                    counters={},
                    execution_mode="foreground",
                    parent_card_id=99,
                    inherit_window=True,
                    valid_card_ids={6, 7},
                    workflow_filepath=str(Path.cwd() / "workflows" / "child.json"),
                    workflow_context=parent_context,
                    executor=parent_executor,
                )

            self.assertTrue(success)
            self.assertTrue(captured_kwargs)
            self.assertIs(captured_kwargs[0]["workflow_context"], seen_contexts[0])
            self.assertIsNone(captured_kwargs[0]["max_execution_steps"])
            self.assertFalse(captured_kwargs[0]["clear_runtime_state_on_start"])
            self.assertTrue(captured_kwargs[0]["infinite_loop_guard_enabled"])
            self.assertIsNot(seen_contexts[0], parent_context)
            self.assertEqual(captured_notes, ["ok"])
            self.assertIsNone(parent_context.get_card_data(7, "note"))
            self.assertIs(get_current_workflow_context(), parent_context)
        finally:
            set_current_workflow_context(previous_context)
            clear_workflow_context("parent-test")

    def test_sub_workflow_forwards_warning_signal_to_parent_executor(self):
        parent_context = WorkflowContext(workflow_id="parent-warning-test")
        previous_context = get_workflow_context()
        parent_executor = mock.Mock()
        parent_executor.step_log = _DummySignal()
        parent_executor.show_warning = _RecordingSignal()

        class FakeWorkflowExecutor:
            def __init__(self, **_kwargs):
                self._last_execution_success = False
                self.step_log = _DummySignal()
                self.show_warning = _RecordingSignal()
                self._persistent_counters = {}

            def run(self):
                self.show_warning.emit("loop", "blocked")

        try:
            set_current_workflow_context(parent_context)
            cards = [
                {"id": 6, "task_type": sub_workflow_task.THREAD_START_TASK_TYPE, "parameters": {}},
                {"id": 7, "task_type": "dummy", "parameters": {}},
            ]

            with mock.patch("task_workflow.executor.WorkflowExecutor", FakeWorkflowExecutor):
                success = sub_workflow_task._execute_sub_workflow(
                    cards=cards,
                    connections=[{"start_card_id": 6, "end_card_id": 7, "type": "sequential"}],
                    counters={},
                    execution_mode="foreground",
                    parent_card_id=99,
                    inherit_window=True,
                    valid_card_ids={6, 7},
                    workflow_filepath=str(Path.cwd() / "workflows" / "child.json"),
                    workflow_context=parent_context,
                    executor=parent_executor,
                )

            self.assertFalse(success)
            self.assertEqual(parent_executor.show_warning.emitted, [("loop", "blocked")])
        finally:
            set_current_workflow_context(previous_context)
            clear_workflow_context("parent-warning-test")


if __name__ == "__main__":
    unittest.main()
