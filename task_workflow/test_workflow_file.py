from __future__ import annotations

import json

from app_core.lca_format import load_lca_project
from app_core.lca_format import session as lca_session
from task_workflow import workflow_payload
from task_workflow.workspace import iter_workspace_workflow_files
from task_workflow.workflow_task import WorkflowTask
from utils.image_paths import ImagePathResolver


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
    previous_session = lca_session.LcaPackageSession({"old": b"session"})
    lca_session.register(tmp_path / "old.lca", previous_session)
    lca_session.activate(tmp_path / "old.lca")

    loaded = workflow_payload.load_workflow_file(saved_path)

    assert loaded == workflow
    assert lca_session.get_active() is not previous_session
    assert lca_session.get_for_path(saved_path) is lca_session.get_active()


def test_load_workflow_file_keeps_json_compatibility(tmp_path):
    workflow = {"cards": [], "connections": [], "name": "legacy"}
    json_path = tmp_path / "legacy.json"
    json_path.write_text(json.dumps(workflow), encoding="utf-8")

    assert workflow_payload.load_workflow_file(json_path) == workflow


def test_loading_json_deactivates_previous_lca_assets(tmp_path):
    image_path = tmp_path / "session-only-asset.bmp"
    image_path.write_bytes(b"ONLY-IN-LCA")
    saved_path = workflow_payload.save_workflow_file(
        tmp_path / "asset-project.lca",
        {
            "cards": [
                {
                    "id": 1,
                    "task_type": "图像匹配点击",
                    "parameters": {"image_path": str(image_path)},
                }
            ],
            "connections": [],
        },
    )
    loaded_lca = workflow_payload.load_workflow_file(saved_path)
    logical_path = loaded_lca["cards"][0]["parameters"]["image_path"]
    image_path.unlink()
    resolver = ImagePathResolver()
    assert resolver.resolve(logical_path) is not None

    json_path = tmp_path / "plain.json"
    json_path.write_text('{"cards": [], "connections": []}', encoding="utf-8")
    workflow_payload.load_workflow_file(json_path)

    assert lca_session.get_active() is None
    assert lca_session.get_for_path(saved_path) is not None
    assert resolver.resolve(logical_path) is None


def test_load_workflow_file_reads_active_lca_session_memory_uri():
    workflow = {"cards": [], "connections": [], "name": "child"}
    session = lca_session.LcaPackageSession(
        {"workflows/subs/child.json": json.dumps(workflow).encode("utf-8")}
    )
    lca_session.register("memory-project.lca", session)
    lca_session.activate("memory-project.lca")

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


def test_workspace_enumerates_json_and_lca_workflows(tmp_path):
    json_path = tmp_path / "legacy.json"
    json_path.write_text('{"cards": [], "connections": []}', encoding="utf-8")
    lca_path = workflow_payload.save_workflow_file(
        tmp_path / "packaged.lca",
        {"cards": [], "connections": []},
    )
    (tmp_path / "not-workflow.json").write_text('{"value": 1}', encoding="utf-8")

    assert iter_workspace_workflow_files(str(tmp_path)) == sorted(
        [str(json_path), str(lca_path)],
        key=str.lower,
    )
