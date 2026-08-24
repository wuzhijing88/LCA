import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


class MouseScrollChainCleanupTests(unittest.TestCase):
    def test_legacy_mouse_scroll_task_file_removed(self):
        self.assertFalse((ROOT_DIR / "tasks" / "mouse_scroll.py").exists())

    def test_mouse_action_task_uses_runtime_module(self):
        file_text = (ROOT_DIR / "tasks" / "mouse_action_task.py").read_text(encoding="utf-8")

        self.assertIn("from tasks.mouse_scroll_runtime import execute_mouse_scroll", file_text)
        self.assertNotIn("from tasks.mouse_scroll import execute_task", file_text)

    def test_runtime_module_no_longer_exposes_legacy_task_entry(self):
        file_text = (ROOT_DIR / "tasks" / "mouse_scroll_runtime.py").read_text(encoding="utf-8")

        self.assertNotIn('TASK_TYPE = "鼠标滚轮操作"', file_text)
        self.assertNotIn("def get_params_definition(", file_text)

    def test_scroll_runtime_uses_fixed_single_step_delta(self):
        file_text = (ROOT_DIR / "tasks" / "mouse_scroll_runtime.py").read_text(encoding="utf-8")

        self.assertNotIn("steps_per_scroll", file_text)
        self.assertNotIn("unit_scroll_count", file_text)
        self.assertNotIn("scroll_value_total", file_text)
        self.assertIn("wparam = win32api.MAKELONG(0, int(scroll_value_per_unit))", file_text)
        self.assertIn("pyautogui.scroll(scroll_value_per_unit)", file_text)
        self.assertNotIn("plugin", file_text.lower())

    def test_mouse_action_task_no_longer_exposes_scroll_steps_parameter(self):
        file_text = (ROOT_DIR / "tasks" / "mouse_action_task.py").read_text(encoding="utf-8")

        self.assertIn('"label": "滚动步数"', file_text)
        self.assertIn('"max": 999', file_text)
        self.assertNotIn('"scroll_steps_per_scroll"', file_text)


if __name__ == "__main__":
    unittest.main()
