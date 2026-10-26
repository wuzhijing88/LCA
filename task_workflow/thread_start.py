#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any


THREAD_START_TASK_TYPE = "线程起点"


def validate_thread_target(value: Any) -> None:
    if isinstance(value, str) and value in {"当前线程", "全部线程"}:
        return
    targets = value if isinstance(value, list) else [value]
    if not targets:
        raise ValueError("请至少选择一个目标线程")
    seen = set()
    for target in targets:
        if not isinstance(target, str) or not target.isascii() or not target.isdecimal() or str(int(target)) != target:
            raise ValueError("目标线程必须是当前线程、全部线程、起点编号的数字字符串或数字字符串列表")
        if target in seen:
            raise ValueError(f"目标线程重复: {target}")
        seen.add(target)


def is_thread_start_task_type(task_type: Any) -> bool:
    return isinstance(task_type, str) and task_type.strip() == THREAD_START_TASK_TYPE
