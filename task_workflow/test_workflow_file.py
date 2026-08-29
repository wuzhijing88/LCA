from __future__ import annotations

import json

from app_core.lca_format import load_lca_project
from app_core.lca_format import session as lca_session
from task_workflow import workflow_payload
from task_workflow.workflow_task import WorkflowTask


def _workflow_task(tmp_path, filepath):
    return WorkflowTask(
        task_id=1,
        name="demo",
        filepath=str(filepath),
        workflow_data={"cards": [], "connections": []},
        task_modules={},
        images_dir=str(tmp_path),
        config={},
    )


def test_save_workflow_file_changes_json_target_to_lca(tmp_path):
    json_path = tmp_path / "demo.json"
    workflow = {"cards": [], "connections": []}

    saved_path = workflow_payload.save_workflow_file(json_path, workflow)

    assert saved_path == tmp_path / "demo.lca"
    assert saved_path.is_file()
    assert not json_path.exists()
    loaded, _session = load_lca_project(saved_path)
    assert loaded == workflow


def test_load_workflow_file_activates_lca_session(tmp_path):
    workflow = {"cards": [], "connections": []}
    saved_path = workflow_payload.save_workflow_file(tmp_path / "demo.lca", workflow)
    previous_session = lca_session.LcaPackageSession({"old": b"session"}).activate()

    loaded = workflow_payload.load_workflow_file(saved_path)

    assert loaded == workflow
    assert lca_session.get_current_session() is not previous_session


def test_load_workflow_file_keeps_json_compatibility(tmp_path):
    workflow = {"cards": [], "connections": [], "name": "legacy"}
    json_path = tmp_path / "legacy.json"
    json_path.write_text(json.dumps(workflow), encoding="utf-8")

    assert workflow_payload.load_workflow_file(json_path) == workflow


def test_load_workflow_file_reads_active_lca_session_memory_uri():
    workflow = {"cards": [], "connections": [], "name": "child"}
    lca_session.LcaPackageSession(
        {"workflows/subs/child.json": json.dumps(workflow).encode("utf-8")}
    ).activate()

    assert (
        workflow_payload.load_workflow_file("memory://workflows/subs/child.json")
        == workflow
    )


def test_workflow_task_save_updates_json_filepath_to_lca(tmp_path):
    json_path = tmp_path / "demo.json"
    task = _workflow_task(tmp_path, json_path)

    assert task.save()

    assert task.filepath == str(tmp_path / "demo.lca")
    assert (tmp_path / "demo.lca").is_file()


def test_save_and_backup_preserves_old_json_before_conversion(tmp_path):
    json_path = tmp_path / "demo.json"
    original = b'{"legacy": true}'
    json_path.write_bytes(original)
    task = _workflow_task(tmp_path, json_path)

    assert task.save_and_backup()

    assert task.filepath == str(tmp_path / "demo.lca")
    backups = list((tmp_path / "backups").glob("demo_backup_*.json"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
