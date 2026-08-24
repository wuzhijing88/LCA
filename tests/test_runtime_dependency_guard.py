import unittest
from unittest.mock import patch

from utils import runtime_dependency_guard


class RuntimeDependencyGuardTests(unittest.TestCase):
    def setUp(self):
        runtime_dependency_guard._PRELOADED_MODULES.clear()

    def test_preload_optional_module_only_imports_once(self):
        sentinel = object()
        with patch("utils.runtime_dependency_guard.importlib.import_module", return_value=sentinel) as import_module:
            self.assertTrue(runtime_dependency_guard.preload_optional_module("onnxruntime"))
            self.assertTrue(runtime_dependency_guard.preload_optional_module("onnxruntime"))

        import_module.assert_called_once_with("onnxruntime")

    def test_preload_optional_module_returns_false_on_failure(self):
        with patch(
            "utils.runtime_dependency_guard.importlib.import_module",
            side_effect=ImportError("boom"),
        ) as import_module:
            self.assertFalse(runtime_dependency_guard.preload_optional_module("onnxruntime"))
            self.assertFalse(runtime_dependency_guard.preload_optional_module("onnxruntime"))

        self.assertEqual(import_module.call_count, 2)


if __name__ == "__main__":
    unittest.main()
