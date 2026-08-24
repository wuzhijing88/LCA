from unittest import mock

from task_workflow import runtime_factory


def test_subprocess_factory_preserves_legacy_runtime_api():
    sentinel = (object(), object())
    with mock.patch(
        "task_workflow.process_proxy.create_process_workflow_runtime",
        return_value=sentinel,
    ) as create:
        result = runtime_factory.create_subprocess_runtime(workflow_id="wf")

    assert result is sentinel
    create.assert_called_once_with(workflow_id="wf")


def test_inprocess_factory_creates_single_executor(monkeypatch):
    executor = object()
    monkeypatch.setattr(
        "task_workflow.executor.WorkflowExecutor",
        lambda **_kwargs: executor,
    )

    result = runtime_factory.create_inprocess_runtime(
        {
            "session_mode": "single",
            "cards_data": {1: {"id": 1}},
            "connections_data": [],
            "start_card_id": 1,
            "workflow_id": "wf",
        },
        task_modules={},
    )

    assert result is executor
