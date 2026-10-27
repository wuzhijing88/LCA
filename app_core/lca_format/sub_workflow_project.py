"""子工作流的独立工程目录与资源落盘。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from app_core.lca_format.constants import ENTRY_WORKFLOW
from app_core.lca_format.container import LcaFormatError, seal_lca_bytes
from app_core.lca_format.project_io import (
    _workflow_body,
    _workflow_contains_sub_workflow,
    is_lca_path,
    load_lca_from_bytes,
    load_lca_project,
    seal_workflow_package,
)
from app_core.lca_format.session import materialize_package_assets
from task_workflow.workspace import SUB_WORKFLOW_DIRECTORY, ensure_workflow_resource_subdirs


def require_main_workflow_path(filepath: object) -> Path:
    text = str(filepath or "").strip()
    if not text:
        raise ValueError("当前主工作流文件路径未绑定，无法导入子工作流")
    if text.startswith("memory://"):
        raise LcaFormatError("子工作流不允许嵌套")
    path = Path(text).resolve()
    if not is_lca_path(path):
        raise ValueError("主工作流必须是现行 .lca 工程")
    if path.parent.parent.name == SUB_WORKFLOW_DIRECTORY:
        raise LcaFormatError("子工作流不允许嵌套")
    return path


def sub_workflow_project_path(parent_filepath: object, logical_path: str) -> Path:
    parent = require_main_workflow_path(parent_filepath)
    logical = str(logical_path).removeprefix("memory://")
    name = Path(logical).stem
    if not name or name in {".", ".."} or not is_lca_path(logical):
        raise LcaFormatError("子工作流路径无效")
    return parent.parent / SUB_WORKFLOW_DIRECTORY / name / f"{name}.lca"


def bind_sub_workflow_project(workflow_data: dict, project: Path) -> None:
    metadata = _workflow_body(workflow_data).setdefault("metadata", {})
    if not isinstance(metadata, dict):
        raise LcaFormatError("子工作流元数据无效")
    metadata["custom_resource_path"] = str(project.parent)


def _write_sub_workflow_project(payload: bytes, project: Path, *, resource_root: Path) -> None:
    data, session = load_lca_from_bytes(payload)
    try:
        bind_sub_workflow_project(data, project)
        files = session.snapshot_files()
        files[ENTRY_WORKFLOW] = json.dumps(data, ensure_ascii=False, indent=4).encode("utf-8")
        sealed = seal_lca_bytes(files)
        ensure_workflow_resource_subdirs(str(resource_root))
        (resource_root / "plugins").mkdir(exist_ok=True)
        materialize_package_assets(session, str(resource_root))
        target = resource_root / project.name
        temporary_name = ""
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=resource_root, suffix=".tmp", delete=False) as handle:
                temporary_name = handle.name
                handle.write(sealed)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, target)
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
    finally:
        session.close()


def import_sub_workflow(source_filepath: str, parent_filepath: object) -> str:
    parent = require_main_workflow_path(parent_filepath)
    source = Path(source_filepath).resolve()
    if not is_lca_path(source):
        raise LcaFormatError("请选择 .lca 工作流工程")
    if source == parent:
        raise LcaFormatError("主工作流不能引用自身作为子工作流")
    data, session = load_lca_project(source)
    try:
        if _workflow_contains_sub_workflow(data):
            raise LcaFormatError("子工作流不允许嵌套")
        payload = seal_workflow_package(
            data, source_session=session, display_name=source.stem,
            source_dir=str(source.parent), workflow_filepath=str(source),
        )
    finally:
        session.close()
    folder = parent.parent / SUB_WORKFLOW_DIRECTORY
    if source.parent.parent == folder and source.name == f"{source.parent.name}.lca":
        return source.relative_to(parent.parent).as_posix()
    name = source.stem
    index = 2
    while (folder / name).exists():
        name = f"{source.stem}_{index}"
        index += 1
    project = folder / name / f"{name}.lca"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix=".导入-", dir=folder) as staging:
            staging_root = Path(staging) / name
            _write_sub_workflow_project(payload, project, resource_root=staging_root)
            staging_root.rename(project.parent)
    except BaseException:
        if folder.exists() and not any(folder.iterdir()):
            folder.rmdir()
        raise
    return project.relative_to(parent.parent).as_posix()


def materialize_sub_workflow_projects(parent_filepath: object, workflow_data: dict, session) -> None:
    cards = _workflow_body(workflow_data).get("cards", [])
    written = set()
    for card in cards:
        if not isinstance(card, dict) or card.get("task_type") != "子工作流":
            continue
        logical = str(card.get("parameters", {}).get("workflow_file") or "").removeprefix("memory://")
        if not logical.startswith("workflows/subs/") or logical in written:
            continue
        payload = session.get_bytes(logical)
        if payload is None:
            raise LcaFormatError(f"父工程中不存在子工作流：{logical}")
        project = sub_workflow_project_path(parent_filepath, logical)
        _write_sub_workflow_project(payload, project, resource_root=project.parent)
        written.add(logical)
