# -*- coding: utf-8 -*-
"""Windows Child Session（桌面分身）原语。"""

from .runtime import (
    CHILD_SESSION_FLAG,
    INSTANCE_SLOT_FLAG,
    apply_child_session_launch_args,
    child_session_window_suffix,
    is_child_session_instance,
    parse_child_session_argv,
)

__all__ = [
    "CHILD_SESSION_FLAG",
    "INSTANCE_SLOT_FLAG",
    "apply_child_session_launch_args",
    "child_session_window_suffix",
    "is_child_session_instance",
    "parse_child_session_argv",
]
