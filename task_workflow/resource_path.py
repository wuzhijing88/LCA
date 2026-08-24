# -*- coding: utf-8 -*-
"""把图片/音频等路径参数规范成普通字符串。"""

from __future__ import annotations

from typing import Any, List, Optional


def _payload_path(value: dict) -> str:
    for key in ("path", "filepath", "file", "value"):
        text = str(value.get(key) or "").strip()
        if text:
            return text
    return ""


def unwrap_resource_path(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, dict):
        text = _payload_path(value)
        return text or None
    if isinstance(value, (list, tuple)):
        for item in value:
            text = unwrap_resource_path(item)
            if text:
                return text
    return None


def format_resource_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return unwrap_resource_path(value) or ""
    if isinstance(value, (list, tuple)):
        paths: List[str] = []
        for item in value:
            text = unwrap_resource_path(item) if not isinstance(item, str) else item.strip()
            if text:
                paths.append(text)
        return "\n".join(paths)
    text = unwrap_resource_path(value)
    return text or ""
