import unittest

from tasks.conditional_control import _execute_condition_control, execute_task


COND_COUNTER = "\u8ba1\u6570\u5668\u5224\u65ad"
ACTION_NEXT = "\u6267\u884c\u4e0b\u4e00\u6b65"
ACTION_REPEAT = "\u7ee7\u7eed\u6267\u884c\u672c\u6b65\u9aa4"
COMPARE_GE = ">="
RESET_ON_SUCCESS = "\u6761\u4ef6\u6ee1\u8db3\u65f6"
RESET_ON_FAILURE = "\u6761\u4ef6\u4e0d\u6ee1\u8db3\u65f6"


class ConditionalControlCounterResetTests(unittest.TestCase):
    def _run_counter_case(self, params, repeats=1):
        counters = {}
        results = []
        for _ in range(repeats):
            results.append(
                _execute_condition_control(params, counters, "foreground", None, 7)
            )
        return results, counters

    def test_reset_on_success_when_enabled(self):
        results, counters = self._run_counter_case(
            {
                "condition_type": COND_COUNTER,
                "target_execution_count": 2,
                "counter_comparison": COMPARE_GE,
                "enable_counter_reset": True,
                "counter_reset_timing": RESET_ON_SUCCESS,
                "on_success": ACTION_NEXT,
                "on_failure": ACTION_NEXT,
            },
            repeats=2,
        )

        self.assertEqual(
            results,
            [
                (False, ACTION_NEXT, None, "条件不满足"),
                (True, ACTION_NEXT, None),
            ],
        )
        self.assertEqual(counters["__card_exec_count_7"], 0)

    def test_reset_on_failure_when_enabled(self):
        results, counters = self._run_counter_case(
            {
                "condition_type": COND_COUNTER,
                "target_execution_count": 2,
                "counter_comparison": COMPARE_GE,
                "enable_counter_reset": True,
                "counter_reset_timing": RESET_ON_FAILURE,
                "on_success": ACTION_NEXT,
                "on_failure": ACTION_NEXT,
            }
        )

        self.assertEqual(results, [(False, ACTION_NEXT, None, "条件不满足")])
        self.assertEqual(counters["__card_exec_count_7"], 0)

    def test_disable_reset_keeps_counter_value(self):
        results, counters = self._run_counter_case(
            {
                "condition_type": COND_COUNTER,
                "target_execution_count": 1,
                "counter_comparison": COMPARE_GE,
                "enable_counter_reset": False,
                "counter_reset_timing": RESET_ON_SUCCESS,
                "on_success": ACTION_NEXT,
                "on_failure": ACTION_NEXT,
            }
        )

        self.assertEqual(results, [(True, ACTION_NEXT, None)])
        self.assertEqual(counters["__card_exec_count_7"], 1)

    def test_legacy_params_keep_original_success_behavior(self):
        results, counters = self._run_counter_case(
            {
                "condition_type": COND_COUNTER,
                "target_execution_count": 1,
                "counter_comparison": COMPARE_GE,
                "on_success": ACTION_REPEAT,
                "on_failure": ACTION_NEXT,
            }
        )

        self.assertEqual(results, [(True, ACTION_REPEAT, 7)])
        self.assertEqual(counters["__card_exec_count_7"], 1)

    def test_execute_task_keeps_condition_not_met_detail(self):
        result = execute_task(
            {
                "condition_type": COND_COUNTER,
                "target_execution_count": 2,
                "counter_comparison": COMPARE_GE,
                "on_success": ACTION_NEXT,
                "on_failure": ACTION_NEXT,
            },
            {},
            "foreground",
            None,
            card_id=7,
        )

        self.assertEqual(result, (False, ACTION_NEXT, None, "条件不满足"))


if __name__ == "__main__":
    unittest.main()
