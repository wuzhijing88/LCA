import unittest

from app_core.app_config import (
    APP_EDITION,
    APP_LICENSE_NAME,
    APP_LICENSE_SPDX,
    APP_NAME,
    APP_SOURCE_REPOSITORY,
    APP_SUMMARY,
    app_source_url,
)


class AppConfigTests(unittest.TestCase):
    def test_offline_identity_and_source_repository(self):
        self.assertEqual(APP_NAME, "LCA")
        self.assertEqual(APP_EDITION, "离线版")
        self.assertEqual(APP_SOURCE_REPOSITORY, "github.com/wuzhijing88/LCA")
        self.assertEqual(APP_LICENSE_SPDX, "AGPL-3.0-only")
        self.assertIn("Affero", APP_LICENSE_NAME)
        self.assertTrue(APP_SUMMARY)

    def test_source_url_uses_https_without_embedding_it_in_config_text(self):
        self.assertEqual(app_source_url(), "https://github.com/wuzhijing88/LCA")


if __name__ == "__main__":
    unittest.main()
