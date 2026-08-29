from __future__ import annotations

from typing import Any, Callable


def hold_key_via_keyboard_task(
    key: str,
    seconds: float,
    *,
    execution_mode: str,
    target_hwnd: Any,
    stop_checker: Callable[[], bool] | None,
) -> bool:
    if stop_checker is not None and stop_checker():
        return False

    from tasks.keyboard_input import KEY_MOUSE_INPUT_TYPE, execute_task as keyboard_execute

    result = keyboard_execute(
        {
            "input_type": KEY_MOUSE_INPUT_TYPE,
            "main_key": key,
            "main_key_hold_duration": seconds,
            "on_success": "执行下一步",
            "on_failure": "执行下一步",
        },
        {},
        execution_mode=execution_mode,
        target_hwnd=target_hwnd,
        stop_checker=stop_checker,
    )
    return bool(result and result[0])
