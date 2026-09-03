from __future__ import annotations

import copy
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence


def snapshot_assignments(window_workflows: Optional[Mapping[Any, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    snapshot: Dict[str, List[Dict[str, Any]]] = {}
    for window_id, workflows in (window_workflows or {}).items():
        items = workflows if isinstance(workflows, list) else [workflows]
        snapshot[str(window_id)] = copy.deepcopy([item for item in items if isinstance(item, dict)])
    return snapshot


def apply_generated_assignments(
    window_workflows: Dict[Any, Any],
    generated: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    for window_id, entries in (generated or {}).items():
        window_workflows[window_id] = [copy.deepcopy(dict(entry)) for entry in entries]


def assignment_entries_from_paths(file_paths: Sequence[str]) -> List[Dict[str, Any]]:
    from task_workflow.workflow_payload import load_workflow_file

    entries: List[Dict[str, Any]] = []
    for file_path in file_paths:
        workflow_data = load_workflow_file(file_path)
        entries.append(
            {
                "file_path": str(file_path),
                "data": copy.deepcopy(workflow_data) if isinstance(workflow_data, dict) else {},
                "name": os.path.basename(str(file_path)),
            }
        )
    return entries
