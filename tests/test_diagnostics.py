import json
import logging
import zipfile

from app_core.diagnostics import export_bundle
from app_core.diagnostics.context import bind_diagnostic_context
from app_core.diagnostics.structured_logging import DiagnosticContextFilter, JsonLineFormatter


def test_structured_log_contains_bound_context():
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", (), None)
    with bind_diagnostic_context(workflow_id="wf-1", request_id="req-1"):
        assert DiagnosticContextFilter().filter(record)
        payload = json.loads(JsonLineFormatter().format(record))

    assert payload["workflow_id"] == "wf-1"
    assert payload["request_id"] == "req-1"
    assert payload["message"] == "hello"


def test_diagnostic_bundle_redacts_sensitive_config(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text('{"api_token":"secret","path":"C:/safe"}', encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "app_test.log").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(export_bundle, "get_config_path", lambda _name: str(config))
    monkeypatch.setattr(export_bundle, "get_logs_dir", lambda _name: str(logs))
    monkeypatch.setattr(export_bundle, "get_user_data_dir", lambda _name: str(tmp_path))
    output = tmp_path / "diagnostics.zip"

    export_bundle.export_diagnostic_bundle(str(output))

    with zipfile.ZipFile(output) as archive:
        summary = json.loads(archive.read("config.summary.json"))
        assert summary["api_token"] == "<redacted>"
        assert archive.read("logs/app_test.log") == b"hello"
