from .main_window_pause_controller import (
    pause_main_window_workflow,
    resume_main_window_workflow,
    toggle_main_window_pause,
)


def main_window_toggle_pause_workflow_compact_log(ctx):
    return toggle_main_window_pause(ctx, source="compact_log")


def main_window_resume_workflow(ctx, source="manual"):
    return resume_main_window_workflow(ctx, source=source)


def main_window_toggle_pause_workflow(ctx):
    return toggle_main_window_pause(ctx, source="hotkey")


def main_window_pause_workflow(ctx, source="manual"):
    return pause_main_window_workflow(ctx, source=source)

