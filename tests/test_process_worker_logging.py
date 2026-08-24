import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from task_workflow import process_worker


class _FakeFileHandler(logging.Handler):
    def __init__(self, filename, *args, **kwargs):
        super().__init__()
        self.baseFilename = str(filename)


class ProcessWorkerLoggingTests(unittest.TestCase):
    def setUp(self):
        self.root_logger = logging.getLogger()
        self.original_handlers = list(self.root_logger.handlers)
        self.original_level = self.root_logger.level
        process_worker._WORKFLOW_LOGGING_CONFIGURED = False

    def tearDown(self):
        self.root_logger.handlers = self.original_handlers
        self.root_logger.setLevel(self.original_level)
        process_worker._WORKFLOW_LOGGING_CONFIGURED = False

    def test_configure_logging_adds_file_handler_and_is_idempotent_with_existing_handlers(self):
        existing_handler = logging.StreamHandler()
        self.root_logger.handlers = [existing_handler]

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_file_handler = _FakeFileHandler(Path(temp_dir) / "app_test.log")
            with mock.patch(
                "task_workflow.process_worker.get_logs_dir",
                return_value=temp_dir,
            ), mock.patch(
                "task_workflow.process_worker.logging.FileHandler",
                return_value=fake_file_handler,
            ) as file_handler_mock, mock.patch(
                "task_workflow.process_worker.install_runtime_log_filters",
            ) as filters_mock, mock.patch(
                "task_workflow.process_worker.configure_noisy_logger_levels",
            ) as noisy_mock, mock.patch(
                "utils.log_message_translator.install_log_message_translator",
            ) as translator_mock:
                process_worker._configure_logging()
                process_worker._configure_logging()

        file_handler_mock.assert_called_once()
        filters_mock.assert_called_once()
        noisy_mock.assert_called_once()
        translator_mock.assert_called_once()
        self.assertIn(existing_handler, self.root_logger.handlers)
        self.assertIn(fake_file_handler, self.root_logger.handlers)


if __name__ == "__main__":
    unittest.main()
