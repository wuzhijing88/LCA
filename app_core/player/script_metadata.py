"""Shared release metadata for packaged workflows (no UI dependencies)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


def workflow_sha256(workflow: Mapping[str, Any]) -> str:
    if not isinstance(workflow, Mapping):
        raise ValueError("发布脚本的工作流必须是对象")
    raw = json.dumps(dict(workflow), ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_release_metadata(metadata: Mapping[str, Any]) -> dict[str, str]:
    """Validate required release metadata."""
    version = metadata.get("version")
    digest = metadata.get("workflow_sha256")
    if not isinstance(version, str) or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise ValueError("发布脚本版本必须是主版本.次版本.修订号")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("发布脚本缺少有效工作流哈希")
    return {"version": version, "workflow_sha256": digest}


def build_release_metadata(workflow: Mapping[str, Any], version: str = "1.0.0") -> dict[str, str]:
    return validate_release_metadata({"version": version, "workflow_sha256": workflow_sha256(workflow)})


def verify_release_workflow(metadata: Mapping[str, Any], workflow: Mapping[str, Any]) -> None:
    checked = validate_release_metadata(metadata)
    if checked["workflow_sha256"] != workflow_sha256(workflow):
        raise ValueError(f"发布脚本工作流完整性校验失败: {metadata.get('id', '')}")
