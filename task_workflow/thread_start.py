#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any


THREAD_START_TASK_TYPE = "线程起点"


def is_thread_start_task_type(task_type: Any) -> bool:
    return isinstance(task_type, str) and task_type.strip() == THREAD_START_TASK_TYPE
