import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app_core.user_data_migration import ensure_user_data_migrated
from utils import app_paths


class ImagesDirResolutionTests(unittest.TestCase):
    def test_get_images_dir_uses_local_app_data_in_frozen_runtime(self):
        fake_exe = r"C:\Program Files\LCA\LCA.exe"
        local_app_data = r"C:\Users\Test\AppData\Local"
        expected = os.path.join(local_app_data, "LCA", "images")

        with mock.patch.object(app_paths.sys, "frozen", True, create=True), mock.patch.object(
            app_paths.sys,
            "executable",
            fake_exe,
            create=True,
        ), mock.patch.dict(os.environ, {"LOCALAPPDATA": local_app_data}), mock.patch.object(
            app_paths, "_ensure_dir", side_effect=lambda path: path
        ):
            actual = app_paths.get_images_dir("LCA")

        self.assertEqual(actual, expected)

    def test_runtime_dirs_use_local_app_data_in_frozen_runtime(self):
        fake_exe = r"C:\Program Files\LCA\LCA.exe"
        local_app_data = r"C:\Users\Test\AppData\Local"
        user_root = os.path.join(local_app_data, "LCA")

        with mock.patch.object(app_paths.sys, "frozen", True, create=True), mock.patch.object(
            app_paths.sys,
            "executable",
            fake_exe,
            create=True,
        ), mock.patch.dict(os.environ, {"LOCALAPPDATA": local_app_data}), mock.patch.object(
            app_paths, "_ensure_dir", side_effect=lambda path: path
        ):
            self.assertEqual(app_paths.get_logs_dir("LCA"), os.path.join(user_root, "logs"))
            self.assertEqual(app_paths.get_workflows_dir("LCA"), os.path.join(user_root, "workflows"))
            self.assertEqual(app_paths.get_runtime_data_dir("LCA"), os.path.join(user_root, "runtime_data"))
            self.assertEqual(
                app_paths.get_runtime_state_dir("LCA"),
                os.path.join(user_root, "runtime", "state"),
            )
            self.assertEqual(app_paths.get_config_path("LCA"), os.path.join(user_root, "config.json"))
            self.assertEqual(
                app_paths.get_favorites_path("LCA"),
                os.path.join(user_root, "workflow_favorites.json"),
            )

    def test_config_migrates_from_app_root_to_local_app_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_root = root / "app"
            local_app_data = root / "localappdata"
            app_root.mkdir(parents=True)
            (app_root / "config.json").write_text('{"from":"legacy"}', encoding="utf-8")
            user_root = local_app_data / "LCA"

            ensure_user_data_migrated(app_root=app_root, user_data_root=user_root)
            config_path = user_root / "config.json"

            self.assertEqual(Path(config_path).read_text(encoding="utf-8"), '{"from":"legacy"}')

    def test_main_window_creation_uses_shared_images_dir_helper(self):
        main_text = (app_paths.os.path.dirname(app_paths.os.path.dirname(__file__)))
        with open(os.path.join(main_text, "main.py"), "r", encoding="utf-8") as handle:
            file_text = handle.read()

        self.assertIn('images_dir=get_images_dir("LCA")', file_text)
        self.assertNotIn('images_dir=os.path.join(APP_ROOT, "images")', file_text)


if __name__ == "__main__":
    unittest.main()
