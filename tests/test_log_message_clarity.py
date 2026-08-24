import logging
import unittest
from utils.log_runtime_control import RuntimeLogNoiseFilter, configure_noisy_logger_levels


class LogMessageClarityTests(unittest.TestCase):
    def test_comtypes_code_cache_info_is_filtered_as_noise(self):
        noise_filter = RuntimeLogNoiseFilter()

        info_record = logging.LogRecord(
            name="comtypes.client._code_cache",
            level=logging.INFO,
            pathname=__file__,
            lineno=83,
            msg="Using writeable comtypes cache directory: '%s'",
            args=("C:\\\\temp\\\\comtypes\\\\gen",),
            exc_info=None,
        )
        warning_record = logging.LogRecord(
            name="comtypes.client._code_cache",
            level=logging.WARNING,
            pathname=__file__,
            lineno=102,
            msg="Creating comtypes.gen package failed: %s",
            args=("boom",),
            exc_info=None,
        )

        self.assertFalse(noise_filter.filter(info_record))
        self.assertTrue(noise_filter.filter(warning_record))

    def test_configure_noisy_logger_levels_raises_comtypes_code_cache_level(self):
        target_logger = logging.getLogger("comtypes.client._code_cache")
        original_level = target_logger.level
        try:
            target_logger.setLevel(logging.NOTSET)
            configure_noisy_logger_levels()
            self.assertEqual(target_logger.level, logging.WARNING)
        finally:
            target_logger.setLevel(original_level)


if __name__ == "__main__":
    unittest.main()
