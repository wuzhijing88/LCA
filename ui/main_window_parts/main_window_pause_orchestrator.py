from .main_window_pause_controller import (
    pause_main_window_workflow,
    resume_main_window_workflow,
    toggle_main_window_pause,
)


def main_window_toggle_pause_workflow_floating(ctx):
    return toggle_main_window_pause(ctx, source="floating")


def main_window_resume_workflow(ctx):
    return resume_main_window_workflow(ctx, source="manual")


def main_window_toggle_pause_workflow(ctx):
    return toggle_main_window_pause(ctx, source="hotkey")


def main_window_pause_workflow(ctx):
    return pause_main_window_workflow(ctx, source="manual")
