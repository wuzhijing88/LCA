import importlib
import sys
import unittest
from unittest.mock import patch


class TasksLazyImportTests(unittest.TestCase):
    def setUp(self):
        for module_name in (
            "tasks",
            "tasks.image_match_click",
            "tasks.yolo_detection",
        ):
            sys.modules.pop(module_name, None)

    def test_import_tasks_does_not_preload_heavy_task_modules(self):
        tasks_pkg = importlib.import_module("tasks")

        self.assertNotIn("tasks.image_match_click", sys.modules)
        self.assertNotIn("tasks.yolo_detection", sys.modules)
        self.assertIn("图片点击", tasks_pkg.TASK_MODULES)
        self.assertIn("YOLO目标检测", tasks_pkg.TASK_MODULES)

    def test_task_module_is_imported_lazily_on_first_access(self):
        tasks_pkg = importlib.import_module("tasks")
        tasks_pkg._MODULE_CACHE.clear()
        sentinel = object()

        with patch("tasks.importlib.import_module", return_value=sentinel) as import_module:
            module = tasks_pkg.TASK_MODULES["图片点击"]

        self.assertIs(module, sentinel)
        import_module.assert_called_once_with("tasks.image_match_click")


if __name__ == "__main__":
    unittest.main()
