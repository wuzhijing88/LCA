import unittest
from pathlib import Path

from tasks import get_all_tasks


ROOT_DIR = Path(__file__).resolve().parents[1]


class OfflineOnlyArchitectureTests(unittest.TestCase):
    def test_removed_online_components_are_absent(self):
        removed_paths = (
            "app_core/license_runtime.py",
            "app_core/license_store.py",
            "app_core/client_identity.py",
            "build_assets/market_update_server",
            "build_assets/packaging/create_manifest.py",
            "build_assets/packaging/downloader.spec",
            "build_assets/site",
            "jw3-auth-server-ubuntu-deploy",
            "market",
            "OLA",
            "plugins",
            "services/ai",
            "services/mcp",
            "app_core/plugin_bridge.py",
            "services/ola_binding_probe.py",
            "services/ola_binding_probe_worker.py",
            "tasks/dict_ocr_task.py",
            "utils/input_simulation/plugin_simulator.py",
            "ui/market",
            "utils/ntfy_push.py",
            "utils/qrcode_security.py",
            "utils/updater.py",
            "utils/generate_manifest.py",
        )

        for relative_path in removed_paths:
            self.assertFalse((ROOT_DIR / relative_path).exists(), relative_path)

    def test_runtime_python_sources_have_no_web_urls(self):
        source_roots = (
            "app_core",
            "services",
            "task_workflow",
            "tasks",
            "ui",
            "utils",
        )

        for source_root in source_roots:
            for source_path in (ROOT_DIR / source_root).rglob("*.py"):
                source_text = source_path.read_text(encoding="utf-8")
                self.assertNotIn("http://", source_text, str(source_path))
                self.assertNotIn("https://", source_text, str(source_path))

    def test_task_registry_excludes_online_ai_task(self):
        self.assertNotIn("AI工具", get_all_tasks())
        self.assertNotIn("字库识别", get_all_tasks())

    def test_main_event_loop_cleanup_timeout_is_defined(self):
        main_source = (ROOT_DIR / "main.py").read_text(encoding="utf-8")

        self.assertIn("_EXIT_CLEANUP_JOIN_TIMEOUT_SEC = 2.0", main_source)
        self.assertIn(
            "exit_cleanup_join_timeout_sec=_EXIT_CLEANUP_JOIN_TIMEOUT_SEC",
            main_source,
        )
        self.assertIn("启动 Qt 事件循环前发生错误", main_source)

    def test_shutdown_paths_do_not_late_import_async_pipeline(self):
        main_source = (ROOT_DIR / "main.py").read_text(encoding="utf-8")
        screenshot_source = (ROOT_DIR / "utils/screenshot_helper.py").read_text(encoding="utf-8")
        late_import = "from utils.async_screenshot import shutdown_global_pipeline"

        self.assertNotIn(late_import, main_source)
        self.assertNotIn(late_import, screenshot_source)

    def test_runtime_bootstrap_has_no_online_service_cleanup(self):
        bootstrap_source = (ROOT_DIR / "app_core/app_runtime_bootstrap.py").read_text(encoding="utf-8")

        self.assertNotIn("后台授权检查", bootstrap_source)
        self.assertNotIn("update_integration", bootstrap_source)

    def test_runtime_sources_do_not_import_removed_plugin_modules(self):
        forbidden_imports = (
            "app_core.plugin_bridge",
            "plugins.adapters.ola",
            "plugins.core",
        )
        for source_root in ("app_core", "services", "task_workflow", "tasks", "ui", "utils"):
            for source_path in (ROOT_DIR / source_root).rglob("*.py"):
                source_text = source_path.read_text(encoding="utf-8")
                for forbidden_import in forbidden_imports:
                    self.assertNotIn(forbidden_import, source_text, str(source_path))

    def test_requirements_exclude_removed_editor_stack(self):
        requirements_text = (ROOT_DIR / "requirements-runtime.txt").read_text(encoding="utf-8")

        self.assertNotIn("qtmonaco", requirements_text.lower())
        self.assertNotIn("QtPy", requirements_text)
        self.assertNotIn("PySide6==", requirements_text)
        self.assertNotIn("PySide6_Addons", requirements_text)
        self.assertNotIn("QtWebEngine", requirements_text)
        self.assertNotIn("cryptography", requirements_text)
        self.assertNotIn("fastapi", requirements_text.lower())
        self.assertNotIn("pyinstaller", requirements_text.lower())
        self.assertIn("PySide6_Essentials==", requirements_text)

    def test_installer_script_excludes_removed_editor_stack(self):
        setup_text = (ROOT_DIR / "build_assets" / "packaging" / "setup.iss").read_text(encoding="utf-8")

        self.assertIn("qtmonaco\\*", setup_text)
        self.assertIn("QtWebEngineProcess.exe", setup_text)
        self.assertIn("*Qt6WebEngine*", setup_text)
        self.assertIn("{app}\\qtmonaco", setup_text)

    def test_app_config_contains_only_local_application_identity(self):
        app_config_source = (ROOT_DIR / "app_core" / "app_config.py").read_text(encoding="utf-8")

        self.assertIn('APP_NAME = "LCA"', app_config_source)
        self.assertIn("APP_VERSION = ", app_config_source)
        self.assertIn('APP_SOURCE_REPOSITORY = "github.com/wuzhijing88/LCA"', app_config_source)
        self.assertNotIn("SERVER", app_config_source)
        self.assertNotIn("MANIFEST", app_config_source)
        self.assertNotIn("INSTALLER_URL", app_config_source)


if __name__ == "__main__":
    unittest.main()
