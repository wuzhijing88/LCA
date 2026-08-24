import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def _read_repo_file(relative_path: str) -> str:
    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


class ScreenshotSaveDirContextTests(unittest.TestCase):
    def test_parameter_panel_screenshot_overlay_uses_panel_images_dir(self):
        file_text = _read_repo_file("ui/panels/media/parameter_panel_media_screenshot_overlay_mixin.py")

        self.assertIn("def _resolve_screenshot_save_dir(self) -> str:", file_text)
        self.assertIn("save_dir=self._resolve_screenshot_save_dir()", file_text)
        self.assertNotIn("save_dir='images'", file_text)

    def test_quick_screenshot_button_follows_parent_panel_images_dir(self):
        file_text = _read_repo_file("ui/selectors/screenshot_tool.py")

        self.assertIn("def _get_context_images_dir(context) -> str:", file_text)
        self.assertIn("self.save_dir = _get_context_images_dir(parent_panel)", file_text)
        self.assertIn("def _normalize_screenshot_save_dir(save_dir: str) -> str:", file_text)
        self.assertIn("get_images_dir", file_text)
        self.assertIn("self.save_dir = _normalize_screenshot_save_dir(save_dir)", file_text)


if __name__ == "__main__":
    unittest.main()
