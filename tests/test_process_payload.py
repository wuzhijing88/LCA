import pytest

from task_workflow.process_payload import build_process_workflow_payload


def _payload(**overrides):
    values = {
        "cards_data": {1: {"id": 1, "task_type": "线程起点"}},
        "connections_data": [],
        "execution_mode": "foreground",
        "screenshot_engine": "wgc",
        "images_dir": None,
        "workflow_id": "workflow-1",
        "start_card_ids": [1],
    }
    values.update(overrides)
    return build_process_workflow_payload(**values)


def test_single_session_payload_is_normalized():
    payload = _payload()

    assert payload["payload_version"] == 2
    assert payload["session_mode"] == "single"
    assert payload["start_card_id"] == 1
    assert payload["screenshot_engine"] == "wgc"


def test_payload_rejects_duplicate_start_ids():
    with pytest.raises(ValueError, match="重复"):
        _payload(start_card_ids=[1, 1])


def test_payload_rejects_unknown_screenshot_engine():
    with pytest.raises(ValueError, match="screenshot_engine"):
        _payload(screenshot_engine="unknown")


def test_payload_can_use_hashed_file_reference(tmp_path):
    workflow = tmp_path / "workflow.json"
    workflow.write_text('{"cards":[],"connections":[]}', encoding="utf-8")

    payload = _payload(
        workflow_filepath=str(workflow),
        prefer_file_reference=True,
    )

    assert "cards_data" not in payload
    assert payload["workflow_reference"]["path"] == str(workflow)
    assert len(payload["workflow_reference"]["sha256"]) == 64
import unittest

from task_workflow.process_payload import build_process_workflow_payload


def _card(card_id):
    return {"id": card_id, "task_type": "线程起点", "parameters": {}}


class ProcessWorkflowPayloadTests(unittest.TestCase):
    def _build(self, **overrides):
        values = {
            "cards_data": {1: _card(1), 2: _card(2)},
            "connections_data": [],
            "execution_mode": "foreground_driver",
            "screenshot_engine": "wgc",
            "images_dir": None,
            "workflow_id": "workflow-1",
            "start_card_ids": [1],
        }
        values.update(overrides)
        return build_process_workflow_payload(**values)

    def test_single_mode_uses_only_explicit_first_start(self):
        payload = self._build(start_card_ids=[2], test_mode="card")

        self.assertEqual(payload["session_mode"], "single")
        self.assertEqual(payload["start_card_id"], 2)
        self.assertEqual(payload["test_mode"], "card")
        self.assertNotIn("start_card_ids", payload)

    def test_multiple_starts_create_multi_thread_payload(self):
        payload = self._build(start_card_ids=[1, 2], thread_labels={1: "A", 2: "B"})

        self.assertEqual(payload["session_mode"], "multi_thread")
        self.assertEqual(payload["start_card_ids"], [1, 2])
        self.assertEqual(payload["thread_labels"], {1: "A", 2: "B"})
        self.assertNotIn("start_card_id", payload)

    def test_empty_starts_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "至少需要一个线程起点"):
            self._build(start_card_ids=[])

    def test_non_integer_start_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "必须是整数"):
            self._build(start_card_ids=["1"])

    def test_duplicate_start_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "重复"):
            self._build(start_card_ids=[1, 1])

    def test_missing_start_card_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "卡片不存在"):
            self._build(start_card_ids=[3])

    def test_invalid_connection_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "缺少起点或终点"):
            self._build(connections_data=[{"start_card_id": 1}])

    def test_invalid_screenshot_engine_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不支持"):
            self._build(screenshot_engine="automatic")


if __name__ == "__main__":
    unittest.main()
