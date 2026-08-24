"""JSONL logging formatter with context-local correlation fields."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app_core.diagnostics.context import current_diagnostic_context


class DiagnosticContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in current_diagnostic_context().as_log_fields().items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "process_id": record.process,
            "thread_id": record.thread,
        }
        for key in ("session_id", "job_id", "workflow_id", "request_id", "worker_pid"):
            value = getattr(record, key, None)
            if value not in (None, "", 0):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def create_jsonl_handler(path: str, level: int = logging.INFO) -> logging.Handler:
    handler = logging.FileHandler(path, mode="a", encoding="utf-8")
    handler.setLevel(level)
    handler.addFilter(DiagnosticContextFilter())
    handler.setFormatter(JsonLineFormatter())
    return handler


__all__ = ["DiagnosticContextFilter", "JsonLineFormatter", "create_jsonl_handler"]
