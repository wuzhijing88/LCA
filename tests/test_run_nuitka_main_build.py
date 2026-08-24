# -*- coding: utf-8 -*-
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from build_assets.packaging.run_nuitka_main_build import (
    DATA_DIR_SPECS,
    INCLUDE_PACKAGES,
    ProcessInfo,
    _build_command,
    _extract_ccache_owner_pids,
    _find_process_tree_root,
    _is_project_nuitka_process,
    _remove_excluded_runtime_dlls,
    _remove_unused_qt_editor_runtime,
    _resolve_output_dir,
    _wait_for_build_artifact,
)


class RunNuitkaMainBuildTests(unittest.TestCase):
    def test_extract_ccache_owner_pids_only_returns_numeric_pid_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            build_dir = Path(tmp_dir)
            (build_dir / "ccache-22308.txt").write_text("", encoding="utf-8")
            (build_dir / "ccache-37660.txt").write_text("", encoding="utf-8")
            (build_dir / "ccache-abc.txt").write_text("", encoding="utf-8")
            (build_dir / "build.log").write_text("", encoding="utf-8")

            self.assertEqual(_extract_ccache_owner_pids(build_dir), {22308, 37660})

    def test_build_command_excludes_onnxruntime_gpu_runtime_dlls(self):
        command = _build_command(r"C:\tmp\build_output")

        self.assertIn("--noinclude-dlls=onnxruntime_providers_cuda.dll", command)
        self.assertIn("--noinclude-dlls=onnxruntime_providers_tensorrt.dll", command)
        self.assertIn("--noinclude-dlls=cublas*.dll", command)
        self.assertIn("--noinclude-dlls=cufft*.dll", command)
        self.assertIn("--noinclude-dlls=cudnn*.dll", command)

    def test_build_command_does_not_package_removed_online_services(self):
        command = _build_command(r"C:\tmp\build_output")
        included_data_dirs = {source for source, _target in DATA_DIR_SPECS}

        self.assertNotIn("certs", included_data_dirs)
        self.assertNotIn("market", INCLUDE_PACKAGES)
        self.assertNotIn("--include-package=market", command)
        self.assertNotIn("--include-package=jw3-auth-server-ubuntu-deploy", command)
        self.assertNotIn("--include-data-dir=certs=certs", command)

    def test_build_command_excludes_removed_variable_editor_stack(self):
        command = _build_command(r"C:\tmp\build_output")
        included_data_dirs = {source for source, _target in DATA_DIR_SPECS}

        self.assertNotIn("qtmonaco", included_data_dirs)
        self.assertNotIn("--include-package=qtmonaco", command)
        self.assertIn("--nofollow-import-to=PySide6.QtWebEngineWidgets", command)
        self.assertIn("--nofollow-import-to=qtmonaco", command)
        self.assertIn("--noinclude-data-files=qtmonaco/*", command)
        self.assertIn("--noinclude-data-files=*qtwebengine*", command)
        self.assertIn("--noinclude-qt-plugins=webengine", command)
        self.assertIn("--noinclude-qt-plugins=qml", command)
        self.assertIn("--noinclude-qt-plugins=multimedia", command)
        self.assertIn("--noinclude-qt-translations", command)
        self.assertNotIn("--nofollow-import-to=jedi", command)
        self.assertNotIn("--nofollow-import-to=pylsp", command)

    def test_remove_unused_qt_editor_runtime_deletes_monaco_and_webengine(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dist_dir = Path(tmp_dir)
            monaco_dir = dist_dir / "qtmonaco"
            monaco_dir.mkdir()
            monaco_file = monaco_dir / "index.html"
            webengine_exe = dist_dir / "QtWebEngineProcess.exe"
            webengine_dll = dist_dir / "PySide6" / "Qt6WebEngineCore.dll"
            locales = dist_dir / "PySide6" / "resources" / "qtwebengine_locales"
            locales.mkdir(parents=True)
            locale_file = locales / "en-US.pak"
            keep_dll = dist_dir / "PySide6" / "Qt6Core.dll"
            webengine_dll.parent.mkdir(parents=True, exist_ok=True)
            for path in (monaco_file, webengine_exe, webengine_dll, locale_file, keep_dll):
                path.write_bytes(b"qt")

            removed = _remove_unused_qt_editor_runtime(dist_dir)
            removed_paths = {relative_path.as_posix() for relative_path, _size in removed}

            self.assertIn("qtmonaco/index.html", removed_paths)
            self.assertIn("QtWebEngineProcess.exe", removed_paths)
            self.assertIn("PySide6/Qt6WebEngineCore.dll", removed_paths)
            self.assertFalse(monaco_dir.exists())
            self.assertFalse(webengine_exe.exists())
            self.assertFalse(webengine_dll.exists())
            self.assertFalse(locales.exists())
            self.assertTrue(keep_dll.exists())

    def test_remove_excluded_runtime_dlls_deletes_gpu_provider_files_only(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dist_dir = Path(tmp_dir)
            capi_dir = dist_dir / "onnxruntime" / "capi"
            capi_dir.mkdir(parents=True, exist_ok=True)
            cuda_provider = capi_dir / "onnxruntime_providers_cuda.dll"
            shared_provider = capi_dir / "onnxruntime_providers_shared.dll"
            cublas = dist_dir / "cublasLt64_11.dll"
            normal = dist_dir / "normal_runtime.dll"
            for path in (cuda_provider, shared_provider, cublas, normal):
                path.write_bytes(b"dll")

            removed = _remove_excluded_runtime_dlls(dist_dir)

            removed_paths = {relative_path.as_posix() for relative_path, _size in removed}
            self.assertEqual(
                removed_paths,
                {
                    "cublasLt64_11.dll",
                    "onnxruntime/capi/onnxruntime_providers_cuda.dll",
                },
            )
            self.assertFalse(cuda_provider.exists())
            self.assertFalse(cublas.exists())
            self.assertTrue(shared_provider.exists())
            self.assertTrue(normal.exists())

    def test_is_project_nuitka_process_matches_scons_process(self):
        process = ProcessInfo(
            process_id=22308,
            parent_process_id=37660,
            name="python.exe",
            executable_path=r"C:\Users\LS\AppData\Local\Programs\Python\Python310\python.exe",
            command_line=(
                r"\"C:\Users\LS\AppData\Local\Programs\Python\Python310\python.exe\" "
                r"-W ignore "
                r"C:\Users\LS\Desktop\LCA\venv\Lib\site-packages\nuitka\build\inline_copy\bin\scons.py "
                r"result_exe=C:\Users\LS\Desktop\LCA\build_assets\packaging\build_output\main.dist\main.exe"
            ),
        )

        self.assertTrue(_is_project_nuitka_process(process, Path(r"C:\Users\LS\Desktop\LCA")))

    def test_find_process_tree_root_uses_highest_matching_parent(self):
        project_root = Path(r"C:\Users\LS\Desktop\LCA")
        processes_by_pid = {
            37660: ProcessInfo(
                process_id=37660,
                parent_process_id=1122,
                name="python.exe",
                executable_path=r"C:\Users\LS\Desktop\LCA\venv\Scripts\python.exe",
                command_line=(
                    r"\"C:\Users\LS\Desktop\LCA\venv\Scripts\python.exe\" "
                    r"build_assets\packaging\run_nuitka_main_build.py "
                    r"--project-root \"C:\Users\LS\Desktop\LCA\" "
                    r"--output-dir \"C:\Users\LS\Desktop\LCA\build_assets\packaging\build_output\""
                ),
            ),
            22308: ProcessInfo(
                process_id=22308,
                parent_process_id=37660,
                name="python.exe",
                executable_path=r"C:\Users\LS\AppData\Local\Programs\Python\Python310\python.exe",
                command_line=(
                    r"\"C:\Users\LS\AppData\Local\Programs\Python\Python310\python.exe\" "
                    r"-W ignore "
                    r"C:\Users\LS\Desktop\LCA\venv\Lib\site-packages\nuitka\build\inline_copy\bin\scons.py "
                    r"result_exe=C:\Users\LS\Desktop\LCA\build_assets\packaging\build_output\main.dist\main.exe"
                ),
            ),
        }

        self.assertEqual(_find_process_tree_root(processes_by_pid, 22308, project_root), 37660)

    def test_resolve_output_dir_normalizes_relative_path(self):
        project_root = Path(r"C:\Users\LS\Desktop\LCA")

        self.assertEqual(
            _resolve_output_dir(project_root, r"build_assets\packaging\build_output"),
            Path(r"C:\Users\LS\Desktop\LCA\build_assets\packaging\build_output"),
        )

    def test_wait_for_build_artifact_accepts_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            exe_path = Path(tmp_dir) / "main.dist" / "main.exe"
            exe_path.parent.mkdir(parents=True, exist_ok=True)
            exe_path.write_bytes(b"MZ")

            _wait_for_build_artifact(exe_path, timeout_seconds=0.01, poll_interval_seconds=0.0)

    def test_wait_for_build_artifact_raises_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            exe_path = Path(tmp_dir) / "main.dist" / "main.exe"

            with (
                mock.patch(
                    "build_assets.packaging.run_nuitka_main_build.time.monotonic",
                    side_effect=[0.0, 0.5, 1.1],
                ),
                mock.patch("build_assets.packaging.run_nuitka_main_build.time.sleep"),
            ):
                with self.assertRaises(FileNotFoundError):
                    _wait_for_build_artifact(exe_path, timeout_seconds=1.0, poll_interval_seconds=0.1)


if __name__ == "__main__":
    unittest.main()
