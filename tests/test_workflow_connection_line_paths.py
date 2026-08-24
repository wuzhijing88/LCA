import gc
import unittest
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from tasks import get_task_modules
from ui.workflow_parts.connection_line import ConnectionLine, get_line_animation_stats
from ui.workflow_parts.workflow_view import WorkflowView


class WorkflowConnectionLinePathsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _create_view(self):
        view = WorkflowView(task_modules=get_task_modules(), images_dir="images")
        state_manager = SimpleNamespace(get_current_state=lambda: "stopped")
        view.main_window = SimpleNamespace(task_state_manager=state_manager)
        self.addCleanup(self._cleanup_view, view)
        return view

    @staticmethod
    def _cleanup_view(view):
        for connection in view.connections:
            if connection.scene() is None:
                view.scene.addItem(connection)
        view.clear_workflow()

    def test_load_workflow_restores_non_empty_connection_paths(self):
        view = self._create_view()
        workflow_data = {
            "cards": [
                {
                    "id": 1,
                    "task_type": "线程起点",
                    "pos_x": -300,
                    "pos_y": -120,
                    "parameters": {},
                },
                {
                    "id": 2,
                    "task_type": "模拟鼠标操作",
                    "pos_x": 0,
                    "pos_y": -120,
                    "parameters": {},
                },
            ],
            "connections": [
                {"start_card_id": 1, "end_card_id": 2, "type": "sequential"},
            ],
        }

        view.load_workflow(workflow_data)

        self.assertEqual(len(view.connections), 1)
        connection = view.connections[0]
        self.assertIsInstance(connection, ConnectionLine)
        self.assertFalse(connection.path().isEmpty())

    def test_scene_membership_owns_animation_registration(self):
        view = self._create_view()
        # 动画注册表是 WeakSet，先回收其他测试遗留的连线，
        # 避免基数在测试中途被垃圾回收改变导致计数漂移。
        gc.collect()
        before_count = get_line_animation_stats()["registered_lines"]
        workflow_data = {
            "cards": [
                {"id": 1, "task_type": "线程起点", "pos_x": -300, "pos_y": 0, "parameters": {}},
                {"id": 2, "task_type": "模拟鼠标操作", "pos_x": 0, "pos_y": 0, "parameters": {}},
            ],
            "connections": [
                {"start_card_id": 1, "end_card_id": 2, "type": "sequential"},
            ],
        }

        view.load_workflow(workflow_data)
        connection = view.connections[0]
        self.assertEqual(get_line_animation_stats()["registered_lines"], before_count + 1)

        view.scene.removeItem(connection)
        self.assertEqual(get_line_animation_stats()["registered_lines"], before_count)


if __name__ == "__main__":
    unittest.main()
