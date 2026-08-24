import importlib
import sys
import unittest
from unittest import mock


class MultiprocessOCRWorkerImportTests(unittest.TestCase):
    def tearDown(self):
        sys.modules.pop("services.multiprocess_ocr_worker", None)

    def test_import_does_not_configure_root_logging(self):
        sys.modules.pop("services.multiprocess_ocr_worker", None)

        with mock.patch("logging.basicConfig") as basic_config_mock:
            module = importlib.import_module("services.multiprocess_ocr_worker")

        self.assertIsNotNone(module)
        basic_config_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
