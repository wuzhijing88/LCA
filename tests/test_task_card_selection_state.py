from pathlib import Path


TASK_CARD_SOURCE = Path("ui/workflow_parts/task_card.py")
DELETE_CARD_SOURCE = Path("ui/workflow_parts/workflow_view_delete_card_mixin.py")


def test_selection_flash_legacy_state_is_removed():
    task_card_source = TASK_CARD_SOURCE.read_text(encoding="utf-8")

    obsolete_names = (
        "selection_flash_timer",
        "selection_flash_interval_ms",
        "selection_flash_border_pen",
        "_is_selection_flashing",
        "_selection_flash_border_on",
        "start_selection_flash",
        "stop_selection_flash",
        "_toggle_selection_flash_border",
    )
    for name in obsolete_names:
        assert name not in task_card_source


def test_card_delete_cleanup_has_no_selection_flash_timer_branch():
    delete_source = DELETE_CARD_SOURCE.read_text(encoding="utf-8")

    assert "selection_flash_timer" not in delete_source
