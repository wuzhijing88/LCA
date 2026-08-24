import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tasks import task_utils


class ImagePathResolverPriorityTests(unittest.TestCase):
    def tearDown(self):
        task_utils.ImagePathResolver.reset_instance()

    def test_frozen_runtime_prefers_per_user_images_over_app_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_dir = root / "app"
            user_root = root / "user"
            cwd_dir = root / "cwd"

            app_image = app_dir / "images" / "target.png"
            user_image = user_root / "LCA" / "images" / "target.png"
            cwd_image = cwd_dir / "images" / "target.png"
            for path in (app_image, user_image, cwd_image):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(path.parent.as_posix().encode("utf-8"))

            fake_exe = app_dir / "LCA.exe"
            fake_exe.write_bytes(b"")

            task_utils.ImagePathResolver.reset_instance()
            with mock.patch.object(task_utils.sys, "frozen", True, create=True), mock.patch.object(
                task_utils.sys,
                "executable",
                str(fake_exe),
                create=True,
            ), mock.patch.dict(os.environ, {"LOCALAPPDATA": str(user_root)}), mock.patch.object(
                task_utils.Path,
                "cwd",
                return_value=cwd_dir,
            ):
                resolver = task_utils.ImagePathResolver()
                resolved = resolver.resolve("images/target.png")

            self.assertEqual(os.path.normcase(os.path.abspath(resolved)), os.path.normcase(str(user_image)))

    def test_frozen_runtime_keeps_user_images_as_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_dir = root / "app"
            user_root = root / "user"

            user_image = user_root / "LCA" / "images" / "target.png"
            user_image.parent.mkdir(parents=True, exist_ok=True)
            user_image.write_bytes(b"user")

            fake_exe = app_dir / "LCA.exe"
            fake_exe.parent.mkdir(parents=True, exist_ok=True)
            fake_exe.write_bytes(b"")

            task_utils.ImagePathResolver.reset_instance()
            with mock.patch.object(task_utils.sys, "frozen", True, create=True), mock.patch.object(
                task_utils.sys,
                "executable",
                str(fake_exe),
                create=True,
            ), mock.patch.dict(os.environ, {"LOCALAPPDATA": str(user_root)}):
                resolver = task_utils.ImagePathResolver()
                resolved = resolver.resolve("images/target.png")

            self.assertEqual(os.path.normcase(os.path.abspath(resolved)), os.path.normcase(str(user_image)))


if __name__ == "__main__":
    unittest.main()
