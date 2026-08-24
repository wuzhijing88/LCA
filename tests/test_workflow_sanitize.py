import unittest

from task_workflow.workflow_sanitize import sanitize_card_parameters, sanitize_workflow_data


class WorkflowSanitizeTests(unittest.TestCase):
    def test_strips_dead_variable_fields_without_migrating_them(self):
        workflow_data = {
            "cards": [
                {
                    "id": 1,
                    "task_type": "条件控制",
                    "parameters": {
                        "countdown_variable": "00:00:12",
                        "save_result_variable_name": "卡片1结果",
                        "coordinate_x_var": "",
                        "coordinate_y_var": "",
                        "coordinate_source_mode": "通过变量",
                        "on_success": "执行下一步",
                    },
                }
            ],
            "connections": [],
            "variables": {"global_vars": {"name": "value"}, "var_sources": {}},
        }

        sanitize_workflow_data(workflow_data)

        self.assertNotIn("variables", workflow_data)
        params = workflow_data["cards"][0]["parameters"]
        self.assertNotIn("countdown_data", params)
        self.assertNotIn("countdown_variable", params)
        self.assertNotIn("save_result_variable_name", params)
        self.assertNotIn("coordinate_x_var", params)
        self.assertEqual(params["coordinate_source_mode"], "坐标工具获取坐标")
        self.assertEqual(params["on_success"], "执行下一步")

    def test_keeps_existing_countdown_data(self):
        params = sanitize_card_parameters(
            {
                "countdown_data": "00:01:00",
                "countdown_variable": "extracted_var",
            }
        )
        self.assertEqual(params["countdown_data"], "00:01:00")
        self.assertNotIn("countdown_variable", params)


if __name__ == "__main__":
    unittest.main()
