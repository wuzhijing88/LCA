"""Create a bounded, redacted support bundle without workflow media."""

from __future__ import annotations

import json
import os
import platform
import re
import time
import zipfile
from pathlib import Path
from typing import Any, Mapping, Optional

from app_core.app_config import APP_EDITION
from utils.app_paths import get_config_path, get_logs_dir, get_user_data_dir


_SENSITIVE_KEY = re.compile(
    r"(password|passwd|secret|token|credential|license|private[_-]?key|auth)",
    re.IGNORECASE,
)
MAX_LOG_BYTES = 5 * 1024 * 1024


def _redact(value: Any, key: str = "") -> Any:
    if _SENSITIVE_KEY.search(key):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {str(item_key): _redact(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, str):
        user_profile = str(Path.home())
        return value.replace(user_profile, "%USERPROFILE%")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _tail_bytes(path: Path, max_bytes: int = MAX_LOG_BYTES) -> bytes:
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - max_bytes))
        return stream.read(max_bytes)


def export_diagnostic_bundle(output_path: Optional[str] = None) -> str:
    user_data_dir = Path(get_user_data_dir("LCA"))
    if output_path:
        destination = Path(output_path).resolve()
    else:
        destination = user_data_dir / "diagnostics" / f"LCA_diagnostics_{int(time.time())}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)

    metadata = {
        "app_edition": APP_EDITION,
        "created_at": time.time(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "process_id": os.getpid(),
    }
    config_summary = _redact(_read_json(Path(get_config_path("LCA"))))

    try:
        from task_workflow.workflow_context import get_workflow_context_diagnostics

        context_diagnostics = _redact(get_workflow_context_diagnostics())
    except Exception:
        context_diagnostics = {}

    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(metadata, ensure_ascii=False, indent=2))
        archive.writestr(
            "config.summary.json",
            json.dumps(config_summary, ensure_ascii=False, indent=2),
        )
        if context_diagnostics:
            archive.writestr(
                "workflow_context.json",
                json.dumps(context_diagnostics, ensure_ascii=False, indent=2),
            )

        log_dir = Path(get_logs_dir("LCA"))
        logs = sorted(
            (path for path in log_dir.glob("app_*") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:3]
        for path in logs:
            archive.writestr(f"logs/{path.name}", _tail_bytes(path))

        third_party_manifest = (
            Path(__file__).resolve().parents[2]
            / "build_assets"
            / "third_party"
            / "manifest.json"
        )
        if third_party_manifest.is_file():
            archive.write(third_party_manifest, "third_party_manifest.json")
    return str(destination)


__all__ = ["export_diagnostic_bundle"]
