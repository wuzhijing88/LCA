import importlib.util
import tempfile
import unittest
from pathlib import Path


def _load_module(name: str, relative: str):
    script = Path(__file__).resolve().parents[1] / relative
    spec = importlib.util.spec_from_file_location(name, script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


verify_tasks = _load_module("lca_verify_task_modules", "tools/verify_packaged_task_modules.py")
verify_packaging_tasks = _load_module(
    "lca_packaging_verify_task_modules",
    "build_assets/packaging/verify_packaged_task_modules.py",
)


class VerifyPackagedTaskModulesTests(unittest.TestCase):
    def test_finds_leftover_deleted_task_module(self):
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "src"
            build_dir = Path(raw) / "main.build"
            (project / "tasks").mkdir(parents=True)
            (project / "tasks" / "click_coordinate.py").write_text("", encoding="utf-8")
            build_dir.mkdir()
            (build_dir / "module.tasks.click_coordinate.c").write_text("", encoding="utf-8")
            (build_dir / "module.tasks.virtual_mouse_state.c").write_text("", encoding="utf-8")

            stale = verify_tasks._find_stale_task_modules(build_dir, project)
            packaging_stale = verify_packaging_tasks._find_stale_task_modules(build_dir, project)
            self.assertEqual(stale, ["tasks.virtual_mouse_state"])
            self.assertEqual(packaging_stale, ["tasks.virtual_mouse_state"])


if __name__ == "__main__":
    unittest.main()
