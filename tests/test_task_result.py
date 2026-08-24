import pytest

from task_workflow.task_result import TaskResult, Transition, TransitionKind, normalize_task_result


@pytest.mark.parametrize(
    ("action", "kind"),
    [
        ("执行下一步", TransitionKind.NEXT),
        ("跳转到步骤", TransitionKind.JUMP),
        ("继续执行本步骤", TransitionKind.RETRY),
        ("停止工作流", TransitionKind.STOP),
    ],
)
def test_legacy_actions_normalize_to_typed_transitions(action, kind):
    result = normalize_task_result((True, action, 12, "detail"))

    assert result.transition.kind is kind
    assert result.transition.target_card_id == 12
    assert result.detail == "detail"


def test_typed_result_round_trips_through_legacy_adapter():
    source = TaskResult(
        success=False,
        transition=Transition(TransitionKind.JUMP, 7),
        detail="not found",
    )

    assert normalize_task_result(source) is source
    assert source.as_legacy_tuple() == (False, "跳转到步骤", 7, "not found")


def test_invalid_legacy_result_is_rejected():
    with pytest.raises(ValueError):
        normalize_task_result((True, "执行下一步"))
