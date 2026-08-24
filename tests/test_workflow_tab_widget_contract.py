import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ui.workflow_parts.workflow_tab_widget as workflow_tab_widget_module
from ui.workflow_parts.workflow_tab_widget import WorkflowTabWidget
from ui.main_window_parts.main_window_favorites_mixin import MainWindowFavoritesMixin


class _DummyTabHost:
    def __init__(self, bound_windows=None):
        self.task_manager = SimpleNamespace(config={"bound_windows": bound_windows or []})


class WorkflowTabWidgetImportContractTests(unittest.TestCase):
    def _validate(self, workflow_data, filepath=r"F:\workflows\current.json"):
        return WorkflowTabWidget._validate_workflow_import_data(
            _DummyTabHost(),
            workflow_data,
            filepath,
        )

    def test_current_minimal_workflow_is_accepted(self):
        jump_config, window_binding = self._validate({"cards": [], "connections": []})

        self.assertIsNone(jump_config)
        self.assertIsNone(window_binding)

    def test_current_full_workflow_is_accepted(self):
        workflow_data = {
            "cards": [],
            "connections": [],
            "jump_config": {
                "enabled": True,
                "rules": {"success": {"id": 2}},
                "delay": 0,
                "first_execute": False,
            },
            "window_binding": {
                "bound_window_id": None,
                "target_window_title": "",
                "target_hwnd": None,
            },
        }

        jump_config, window_binding = self._validate(workflow_data)

        self.assertEqual(jump_config["rules"], {"success": {"id": 2}})
        self.assertIsNone(window_binding["target_hwnd"])

    def test_json_variables_field_is_discarded(self):
        workflow_data = {
            "cards": [],
            "connections": [],
            "variables": {"global_vars": {"name": "value"}, "var_sources": {}},
        }
        self._validate(workflow_data, r"F:\workflows\legacy.json")
        self.assertNotIn("variables", workflow_data)

    def test_legacy_integer_jump_target_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "id"):
            self._validate(
                {
                    "cards": [],
                    "connections": [],
                    "jump_config": {
                        "enabled": True,
                        "rules": {"success": 2},
                        "delay": 0,
                        "first_execute": False,
                    },
                },
                r"F:\workflows\legacy.json",
            )

    def test_invalid_bound_window_is_rejected_without_unbinding(self):
        workflow_data = {
            "cards": [],
            "connections": [],
            "window_binding": {
                "bound_window_id": 123,
                "target_window_title": "target",
                "target_hwnd": 123,
            },
        }

        with patch("win32gui.IsWindow", return_value=False):
            jump_config, window_binding = self._validate(workflow_data)

        self.assertIsNone(jump_config)
        self.assertEqual(window_binding["target_hwnd"], 123)
        self.assertEqual(workflow_data["window_binding"]["target_hwnd"], 123)

    def test_sub_workflow_path_does_not_search_for_same_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            parent_file = root / "main.json"
            parent_file.write_text("{}", encoding="utf-8")
            nested_dir = root / "nested"
            nested_dir.mkdir()
            (nested_dir / "child.json").write_text("{}", encoding="utf-8")

            with self.assertRaises(FileNotFoundError):
                WorkflowTabWidget._resolve_explicit_sub_workflow_path(
                    "child.json",
                    str(parent_file),
                )

    def test_recent_workflows_do_not_silently_drop_missing_paths(self):
        tab = SimpleNamespace(_is_backup_path=lambda _path: False)
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            missing_path = Path(temp_dir) / "missing.json"
            config_path.write_text(
                '{"recent_workflows": ["' + str(missing_path).replace('\\', '\\\\') + '"]}',
                encoding="utf-8",
            )
            with patch.object(workflow_tab_widget_module, "get_config_path", return_value=str(config_path)):
                with self.assertRaises(FileNotFoundError):
                    WorkflowTabWidget.load_recent_workflows(tab)

            self.assertIn("missing.json", config_path.read_text(encoding="utf-8"))


class WorkflowTabWidgetCloseContractTests(unittest.TestCase):
    @staticmethod
    def _task(status="idle", executor=None, executor_thread=None):
        task = SimpleNamespace(
            task_id=1,
            name="workflow",
            status=status,
            executor=executor,
            executor_thread=executor_thread,
            filepath=r"F:\workflows\current.json",
            modified=False,
        )
        task.stop = Mock()
        return task

    @staticmethod
    def _tab_harness(task, remove_result=True):
        manager = SimpleNamespace(
            get_task=Mock(return_value=task),
            remove_task=Mock(return_value=remove_result),
            _task_has_active_runtime=Mock(return_value=False),
        )
        tab = SimpleNamespace(
            count=Mock(return_value=2),
            tab_to_task={0: 1},
            task_manager=manager,
            _remove_from_recent_workflows=Mock(),
            workflow_closed=SimpleNamespace(emit=Mock()),
        )
        tab._task_has_active_close_state = lambda current_task: (
            WorkflowTabWidget._task_has_active_close_state(tab, current_task)
        )
        return tab

    def test_silent_close_rejects_running_task_without_stopping(self):
        task = self._task(status="running")
        tab = self._tab_harness(task)

        result = WorkflowTabWidget.close_tab_silent(tab, 0)

        self.assertFalse(result)
        task.stop.assert_not_called()
        tab.task_manager.remove_task.assert_not_called()
        tab._remove_from_recent_workflows.assert_not_called()

    def test_close_rejects_runtime_references_without_stopping(self):
        task = self._task(status="completed", executor=object())
        tab = self._tab_harness(task)

        with patch.object(workflow_tab_widget_module.QMessageBox, "warning") as warning:
            result = WorkflowTabWidget._on_tab_close_requested(tab, 0)

        self.assertFalse(result)
        task.stop.assert_not_called()
        tab.task_manager.remove_task.assert_not_called()
        warning.assert_called_once()

    def test_silent_close_removes_idle_task_immediately(self):
        task = self._task()
        tab = self._tab_harness(task)

        result = WorkflowTabWidget.close_tab_silent(tab, 0)

        self.assertTrue(result)
        task.stop.assert_not_called()
        tab.task_manager.remove_task.assert_called_once_with(1)
        tab._remove_from_recent_workflows.assert_called_once_with(task.filepath)
        tab.workflow_closed.emit.assert_called_once_with(1)

    def test_dispose_view_does_not_disconnect_all_scene_selection_slots(self):
        class _SelectionSignal:
            def disconnect(self, *_args):
                raise AssertionError("页面销毁不得无目标断开场景选择信号")

        class _Scene:
            selectionChanged = _SelectionSignal()

            def __init__(self):
                self.clear = Mock()

        class _WorkflowView:
            def __init__(self):
                self.main_window = object()
                self.scene = _Scene()
                self.undo_stack = []
                self.flashing_card_ids = set()
                self._deleting_cards = set()
                self.cards = {}
                self.connections = []
                self.setParent = Mock()
                self.deleteLater = Mock()

        view = _WorkflowView()
        with patch.object(workflow_tab_widget_module, "WorkflowView", _WorkflowView):
            WorkflowTabWidget._dispose_workflow_widget(SimpleNamespace(), view)

        view.scene.clear.assert_called_once_with()
        view.setParent.assert_called_once_with(None)
        view.deleteLater.assert_called_once_with()


class FavoriteWorkflowCheckContractTests(unittest.TestCase):
    def test_unchecking_closed_favorite_is_already_satisfied(self):
        host = SimpleNamespace(
            task_manager=SimpleNamespace(find_task_by_filepath=Mock(return_value=None)),
            workflow_tab_widget=SimpleNamespace(task_to_tab={}, close_tab_silent=Mock()),
            _open_workflow_reference=Mock(),
        )

        MainWindowFavoritesMixin._on_favorite_workflow_check_changed(
            host,
            r"F:\workflows\closed.json",
            False,
        )

        host._open_workflow_reference.assert_not_called()
        host.workflow_tab_widget.close_tab_silent.assert_not_called()

    def test_unchecking_open_favorite_closes_its_tab_once(self):
        task = SimpleNamespace(task_id=7)
        host = SimpleNamespace(
            task_manager=SimpleNamespace(find_task_by_filepath=Mock(return_value=task)),
            workflow_tab_widget=SimpleNamespace(task_to_tab={7: 2}, close_tab_silent=Mock()),
            _open_workflow_reference=Mock(),
        )

        MainWindowFavoritesMixin._on_favorite_workflow_check_changed(
            host,
            r"F:\workflows\open.json",
            False,
        )

        host.workflow_tab_widget.close_tab_silent.assert_called_once_with(2)


if __name__ == "__main__":
    unittest.main()
