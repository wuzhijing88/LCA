import unittest

from utils.log_message_translator import translate_log_message


class LogMessageTranslatorTests(unittest.TestCase):
    def test_translate_function_address_message(self):
        self.assertEqual(
            translate_log_message("Failed to get function address for CreateABC"),
            "获取函数地址失败： CreateABC",
        )


if __name__ == "__main__":
    unittest.main()
