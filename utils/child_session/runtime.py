# -*- coding: utf-8 -*-
"""桌面分身进程标记：子会话里启动的 LCA 不再套一层 Child Session。"""

from __future__ import annotations

import os
import sys
from typing import Optional, Sequence

from utils.instance_runtime import INSTANCE_SLOT_ENV

CHILD_SESSION_FLAG = "--child-session"
INSTANCE_SLOT_FLAG = "--instance-slot"
CHILD_SESSION_ENV = "LCA_CHILD_SESSION"


def parse_child_session_argv(argv: Optional[Sequence[str]] = None) -> tuple[bool, Optional[int]]:
    args = list(sys.argv if argv is None else argv)
    enabled = False
    slot: Optional[int] = None
    index = 1
    while index < len(args):
        token = str(args[index])
        if token == CHILD_SESSION_FLAG:
            enabled = True
            index += 1
            continue
        if token == INSTANCE_SLOT_FLAG:
            if index + 1 >= len(args):
                raise ValueError("缺少 --instance-slot 参数值")
            slot = _parse_slot_value(args[index + 1])
            index += 2
            continue
        if token.startswith(INSTANCE_SLOT_FLAG + "="):
            slot = _parse_slot_value(token.split("=", 1)[1])
            index += 1
            continue
        index += 1
    if slot is not None and not enabled:
        raise ValueError("--instance-slot 只能与 --child-session 一起使用")
    return enabled, slot


def apply_child_session_launch_args(argv: Optional[Sequence[str]] = None) -> bool:
    enabled, slot = parse_child_session_argv(argv)
    if not enabled:
        return False
    os.environ[CHILD_SESSION_ENV] = "1"
    if slot is not None:
        os.environ[INSTANCE_SLOT_ENV] = str(int(slot))
    return True


def is_child_session_instance(argv: Optional[Sequence[str]] = None) -> bool:
    if str(os.environ.get(CHILD_SESSION_ENV, "")).strip() == "1":
        return True
    enabled, _slot = parse_child_session_argv(argv)
    return enabled


def child_session_window_suffix() -> str:
    if not is_child_session_instance():
        return ""
    return " [桌面分身]"


def _parse_slot_value(raw: object) -> int:
    try:
        slot = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"--instance-slot 的值无效: {raw!r}") from exc
    if slot < 1:
        raise ValueError(f"--instance-slot 必须是正整数: {raw!r}")
    return slot
