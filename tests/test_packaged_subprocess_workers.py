# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from build_assets.packaging.run_nuitka_main_build import INCLUDE_MODULES
from tools.verify_packaged_subprocess_workers import _verify_build_modules


ROOT_DIR = Path(__file__).resolve().parents[1]


class PackagedSubprocessWorkersTests(unittest.TestCase):
    def test_nuitka_build_includes_workflow_process_worker(self):
        self.assertIn("task_workflow.process_worker", INCLUDE_MODULES)
        removed_prefixes = (
            "services." + "map" + "_navigation",
            "services." + "lk" + "maptools_runtime",
        )
        self.assertFalse(
            any(str(module_name).startswith(prefix) for prefix in removed_prefixes for module_name in INCLUDE_MODULES)
        )
        self.assertNotIn("services.multiprocess_match_pool", INCLUDE_MODULES)

    def test_build_module_verifier_requires_workflow_process_worker(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            build_dir = Path(tmp_dir)
            ok, missing = _verify_build_modules(build_dir)

        self.assertFalse(ok)
        self.assertIn("module.task_workflow.process_worker.c", missing)
        removed_tokens = ("map" + "_navigation", "lk" + "maptools_runtime")
        self.assertFalse(any(token in module_name for token in removed_tokens for module_name in missing))
        self.assertNotIn("module.services.multiprocess_match_pool.c", missing)

    def test_unused_match_process_pool_is_removed(self):
        self.assertFalse((ROOT_DIR / "services" / "multiprocess_match_pool.py").exists())

        recognizer_source = (ROOT_DIR / "tasks" / "parallel_image_recognition.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("multiprocess_match_pool", recognizer_source)
        self.assertNotIn("_use_subprocess_match", recognizer_source)


if __name__ == "__main__":
    unittest.main()
