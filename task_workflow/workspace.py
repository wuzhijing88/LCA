import copy
import json
import os
import shutil
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from task_workflow.thread_start import THREAD_START_TASK_TYPE

from utils.app_paths import (
    get_app_root,
    get_dicts_dir,
    get_images_dir,
    get_sounds_dir,
    get_plugin_dir,
    get_user_data_dir,
    get_workflows_dir,
    normalize_workflow_image_path,
)

WORKFLOW_RESOURCE_SUBDIRS = ("images", "sounds", "dicts", "yolo", "replays")
_WORKFLOW_FILE_EXTENSIONS = {".json", ".lca"}

WORKSPACE_FAVORITES_SCHEMA_VERSION = 3
_WORKSPACE_PROJECT_CACHE_MAX = 256
_WORKSPACE_PROJECT_CACHE: "OrderedDict[str, Tuple[Tuple[int, int], Dict[str, Any], str]]" = OrderedDict()


def _workspace_project_stat(filepath: str) -> Optional[Tuple[int, int]]:
    try:
        stat = os.stat(filepath)
    except OSError:
        return None
    return int(stat.st_mtime_ns), int(stat.st_size)


def _cache_workspace_project(
    filepath: str,
    file_stat: Tuple[int, int],
    workflow_data: Dict[str, Any],
    source_path: str,
) -> None:
    key = os.path.normcase(os.path.abspath(filepath))
    _WORKSPACE_PROJECT_CACHE[key] = (
        file_stat,
        copy.deepcopy(workflow_data),
        str(source_path or ""),
    )
    _WORKSPACE_PROJECT_CACHE.move_to_end(key)
    while len(_WORKSPACE_PROJECT_CACHE) > _WORKSPACE_PROJECT_CACHE_MAX:
        _WORKSPACE_PROJECT_CACHE.popitem(last=False)


def favorite_path_key(filepath: str) -> str:
    normalized = str(filepath or "").strip()
    if not normalized:
        return ""
    return os.path.normcase(os.path.abspath(normalized))


def workflow_stem_key(filepath: str) -> str:
    raw_path = str(filepath or "").strip()
    if not raw_path:
        return ""
    root, _extension = os.path.splitext(os.path.abspath(raw_path))
    return os.path.normcase(root)


def resolve_existing_workflow_path(filepath: str) -> str:
    raw_path = str(filepath or "").strip()
    if not raw_path:
        return ""
    return os.path.abspath(raw_path)


def backup_workflow_file(filepath: str) -> str:
    import shutil
    from datetime import datetime

    abs_filepath = os.path.abspath(str(filepath or "").strip())
    if not abs_filepath or not os.path.isfile(abs_filepath):
        raise FileNotFoundError(f"工作流文件不存在: {filepath}")

    backups_dir = os.path.join(os.path.dirname(abs_filepath), "backups")
    os.makedirs(backups_dir, exist_ok=True)
    name, extension = os.path.splitext(os.path.basename(abs_filepath))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = os.path.join(backups_dir, f"{name}_backup_{timestamp}{extension or '.lca'}")
    shutil.copy2(abs_filepath, backup_path)
    return backup_path


def workflow_path_keys(filepath: str) -> List[str]:
    raw_path = str(filepath or "").strip()
    if not raw_path:
        return []

    return [favorite_path_key(raw_path)]


def path_is_under_workspace(filepath: str, workspace_dir: str) -> bool:
    raw_path = str(filepath or "").strip()
    workspace_abs = normalize_workspace_dir(workspace_dir)
    if not raw_path or not workspace_abs:
        return False
    file_abs = os.path.abspath(raw_path)
    file_key = os.path.normcase(file_abs)
    workspace_key = os.path.normcase(workspace_abs)
    try:
        return os.path.commonpath([file_key, workspace_key]) == workspace_key
    except ValueError:
        return False


def resolve_favorite_workspace_dir(
    filepath: str,
    workspaces: List[str],
    current: str = "",
) -> str:
    current_workspace = normalize_workspace_dir(current)
    if current_workspace and path_is_under_workspace(filepath, current_workspace):
        return current_workspace

    matches = [
        normalize_workspace_dir(workspace)
        for workspace in workspaces
        if normalize_workspace_dir(workspace) and path_is_under_workspace(filepath, workspace)
    ]
    if not matches:
        return current_workspace
    matches.sort(key=len, reverse=True)
    return matches[0]


def normalize_workspace_dir(path: str) -> str:
    raw_path = str(path or "").strip()
    if not raw_path:
        return ""
    return os.path.abspath(os.path.normpath(raw_path))


def is_workflow_json_data(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if isinstance(data.get("cards"), list):
        return True
    workflow_data = data.get("workflow")
    return isinstance(workflow_data, dict) and isinstance(workflow_data.get("cards"), list)


def _load_workspace_project(filepath: str) -> Optional[Tuple[Dict[str, Any], str]]:
    workflow_path = str(filepath or "").strip()
    if not workflow_path or not os.path.exists(workflow_path):
        return None
    file_stat = _workspace_project_stat(workflow_path)
    if file_stat is None:
        return None
    cache_key = os.path.normcase(os.path.abspath(workflow_path))
    cached = _WORKSPACE_PROJECT_CACHE.get(cache_key)
    if cached is not None:
        cached_stat, cached_data, cached_source_path = cached
        if cached_stat == file_stat:
            _WORKSPACE_PROJECT_CACHE.move_to_end(cache_key)
            return copy.deepcopy(cached_data), cached_source_path
        _WORKSPACE_PROJECT_CACHE.pop(cache_key, None)
    from app_core.lca_format.container import LcaFormatError
    from app_core.lca_format.project_io import load_lca_project

    try:
        data, session = load_lca_project(workflow_path)
    except LcaFormatError:
        return None
    try:
        if not is_workflow_json_data(data):
            raise ValueError("工作流必须包含卡片列表")
        from task_workflow.workflow_sanitize import sanitize_workflow_data

        if session.source_path is None:
            raise ValueError("磁盘工程未提供现行文件路径")
        sanitized = sanitize_workflow_data(data)
        _cache_workspace_project(workflow_path, file_stat, sanitized, session.source_path)
        return copy.deepcopy(sanitized), session.source_path
    finally:
        session.close()


def load_workspace_workflow(filepath: str) -> Optional[Dict[str, Any]]:
    project = _load_workspace_project(filepath)
    return project[0] if project is not None else None


def get_workflow_body(workflow_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(workflow_data, dict):
        return {}
    if isinstance(workflow_data.get("cards"), list):
        return workflow_data
    nested_workflow = workflow_data.get("workflow")
    if isinstance(nested_workflow, dict):
        return nested_workflow
    return workflow_data


def extract_workflow_metadata(workflow_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(workflow_data, dict):
        return {}
    metadata = workflow_data.get("metadata")
    if not isinstance(metadata, dict):
        workflow_body = get_workflow_body(workflow_data)
        if workflow_body is not workflow_data:
            metadata = workflow_body.get("metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def extract_workflow_resource_path(workflow_data: Optional[Dict[str, Any]]) -> str:
    metadata = extract_workflow_metadata(workflow_data)
    resource_path = str(metadata.get("custom_resource_path") or "").strip()
    if not resource_path:
        return ""
    return os.path.abspath(os.path.normpath(resource_path))


def project_resource_dirs(resource_path: str) -> Dict[str, Any]:
    root = normalize_workspace_dir(resource_path)
    if not root:
        raise ValueError("资源目录不能为空")
    return {
        "root": root,
        "images_dir": os.path.join(root, "images"),
        "sounds_dir": os.path.join(root, "sounds"),
        "dicts_dir": os.path.join(root, "dicts"),
        "yolo_dir": os.path.join(root, "yolo"),
        "replays_dir": os.path.join(root, "replays"),
        "plugins_dir": get_plugin_dir(),
        "custom": True,
    }


def global_resource_dirs(default_images_dir: str = "") -> Dict[str, Any]:
    app_root = get_app_root()
    images_dir = str(default_images_dir or "").strip() or get_images_dir("LCA")
    return {
        "root": "",
        "images_dir": images_dir,
        "sounds_dir": get_sounds_dir("LCA"),
        "dicts_dir": get_dicts_dir("LCA"),
        "yolo_dir": os.path.join(app_root, "yolo"),
        "replays_dir": os.path.join(app_root, "replays"),
        "plugins_dir": get_plugin_dir(),
        "custom": False,
    }


def workflow_resource_dirs(
    workflow_data: Optional[Dict[str, Any]],
    default_images_dir: str = "",
) -> Dict[str, Any]:
    resource_path = extract_workflow_resource_path(workflow_data)
    if resource_path:
        return project_resource_dirs(resource_path)
    return global_resource_dirs(default_images_dir)


def get_effective_workflow_images_dir(
    workflow_data: Optional[Dict[str, Any]],
    default_images_dir: str,
) -> str:
    return str(workflow_resource_dirs(workflow_data, default_images_dir).get("images_dir") or "")


def ensure_workflow_resource_subdirs(resource_dir: str) -> None:
    root = normalize_workspace_dir(resource_dir)
    if not root:
        raise ValueError("资源目录不能为空")
    os.makedirs(root, exist_ok=True)
    for name in WORKFLOW_RESOURCE_SUBDIRS:
        os.makedirs(os.path.join(root, name), exist_ok=True)


def list_root_workflow_files(folder: str) -> List[str]:
    root = normalize_workspace_dir(folder)
    if not root or not os.path.isdir(root):
        return []
    try:
        names = os.listdir(root)
    except OSError:
        return []
    files: List[str] = []
    for name in names:
        extension = os.path.splitext(name)[1].lower()
        if extension not in _WORKFLOW_FILE_EXTENSIONS:
            continue
        full_path = os.path.abspath(os.path.join(root, name))
        if os.path.isfile(full_path):
            files.append(full_path)
    files.sort(key=lambda path: path.lower())
    return files


def is_exclusive_workflow_dir(folder: str, workflow_path: str) -> bool:
    files = list_root_workflow_files(folder)
    if not files:
        return True
    current_keys = set(workflow_path_keys(workflow_path))
    current_stem = workflow_stem_key(workflow_path)
    for path in files:
        if favorite_path_key(path) in current_keys:
            continue
        if current_stem and workflow_stem_key(path) == current_stem:
            continue
        return False
    return True


def exclusive_workflow_filepath(desired_file: str) -> str:
    raw_path = str(desired_file or "").strip()
    if not raw_path:
        raise ValueError("工作流路径不能为空")
    abs_path = os.path.abspath(raw_path)
    folder, filename = os.path.split(abs_path)
    stem, extension = os.path.splitext(filename)
    if not stem:
        raise ValueError("工作流路径不能为空")
    if not extension:
        extension = ".lca"
    candidate = os.path.join(folder, f"{stem}{extension}")
    if is_exclusive_workflow_dir(folder, candidate):
        return candidate
    return os.path.join(folder, stem, f"{stem}{extension}")


def is_default_app_workspace(path: str) -> bool:
    """软件默认保存目录不算用户添加的工作区。"""
    root = normalize_workspace_dir(path)
    if not root:
        return False
    defaults = (
        normalize_workspace_dir(get_workflows_dir()),
        normalize_workspace_dir(get_user_data_dir("LCA")),
    )
    root_key = os.path.normcase(root)
    return any(root_key == os.path.normcase(item) for item in defaults if item)


def blank_workflow_data(project_dir: str) -> Dict[str, Any]:
    root = os.path.abspath(str(project_dir or "").strip())
    return {
        "cards": [
            {
                "id": 0,
                "task_type": THREAD_START_TASK_TYPE,
                "pos_x": 0,
                "pos_y": 0,
                "parameters": {},
            }
        ],
        "connections": [],
        "metadata": {
            "created": "blank",
            "place_start_at_viewport": True,
            "version": "1.0",
            "custom_resource_path": root,
        },
    }


def default_new_workflow_filepath(name: str) -> str:
    return new_workflow_filepath(name, "")


def new_workflow_filepath(name: str, workspace_dir: str = "") -> str:
    """新建工程固定独占工作区下的同名目录；这里只计算路径，不创建工程目录。"""
    text = str(name or "").strip()
    if text.lower().endswith(".lca"):
        text = text[:-4]
    if not text:
        raise ValueError("工作流名称不能为空")
    if (
        text in {".", ".."}
        or any(char in text for char in '\\/:*?"<>|')
        or text.endswith((".", " "))
        or any(ord(char) < 32 for char in text)
    ):
        raise ValueError("工作流名称不能包含路径或文件名非法字符")
    root = normalize_workspace_dir(workspace_dir) or get_workflows_dir()
    return os.path.join(root, text, f"{text}.lca")


def apply_resource_dirs_to_task(task: Any, dirs: Dict[str, Any], default_images_dir: str = "") -> None:
    task.images_dir = str(dirs.get("images_dir") or default_images_dir or "")
    task.sounds_dir = str(dirs.get("sounds_dir") or "")
    task.dicts_dir = str(dirs.get("dicts_dir") or "")
    task.yolo_dir = str(dirs.get("yolo_dir") or "")
    task.replays_dir = str(dirs.get("replays_dir") or "")
    task.plugins_dir = str(dirs.get("plugins_dir") or "")


def apply_updated_workflow_resource_dir(
    task: Any,
    resource_dir: str = "",
    workflow_data: Optional[Dict[str, Any]] = None,
    default_images_dir: str = "",
) -> Dict[str, Any]:
    if isinstance(workflow_data, dict):
        task.workflow_data = workflow_data
    data = task.workflow_data if isinstance(getattr(task, "workflow_data", None), dict) else {}
    if not isinstance(data, dict):
        data = {"cards": [], "connections": [], "metadata": {}}
        task.workflow_data = data
    normalized = normalize_workspace_dir(resource_dir)
    if normalized:
        metadata = data.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            data["metadata"] = metadata
        metadata["custom_resource_path"] = normalized
        dirs = project_resource_dirs(normalized)
    else:
        dirs = resolve_runtime_resource_dirs(
            data,
            workflow_filepath=str(getattr(task, "filepath", "") or ""),
            default_images_dir=default_images_dir,
        )
    apply_resource_dirs_to_task(task, dirs, default_images_dir)
    return dirs


def resolve_runtime_resource_dirs(
    workflow_data: Optional[Dict[str, Any]] = None,
    *,
    workflow_filepath: str = "",
    default_images_dir: str = "",
) -> Dict[str, Any]:
    dirs = workflow_resource_dirs(workflow_data, default_images_dir)
    if dirs.get("custom"):
        return dirs
    filepath = str(workflow_filepath or "").strip()
    if not filepath or not os.path.isfile(filepath):
        return dirs
    folder = os.path.dirname(os.path.abspath(filepath))
    if is_exclusive_workflow_dir(folder, filepath):
        return project_resource_dirs(folder)
    return dirs


def resource_runtime_kwargs(dirs: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    data = dirs if isinstance(dirs, dict) else {}
    return {
        "images_dir": str(data.get("images_dir") or ""),
        "sounds_dir": str(data.get("sounds_dir") or ""),
        "dicts_dir": str(data.get("dicts_dir") or ""),
        "yolo_dir": str(data.get("yolo_dir") or ""),
        "replays_dir": str(data.get("replays_dir") or ""),
        "plugins_dir": str(data.get("plugins_dir") or get_plugin_dir()),
    }


def prepare_exclusive_workflow_save(
    workflow_data: Dict[str, Any],
    desired_file: str,
    *,
    source_filepath: str = "",
) -> str:
    filepath = exclusive_workflow_filepath(desired_file)
    root = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(root, exist_ok=True)
    ensure_workflow_resource_subdirs(root)
    migrate_workflow_resources_to_dir(
        workflow_data,
        root,
        workflow_filepath=source_filepath or filepath,
    )
    metadata = workflow_data.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        workflow_data["metadata"] = metadata
    metadata["custom_resource_path"] = root
    return filepath


def iter_workspace_workflow_files(workspace_dir: str) -> List[str]:
    normalized_dir = normalize_workspace_dir(workspace_dir)
    if not normalized_dir or not os.path.isdir(normalized_dir):
        return []

    workflow_files: set[str] = set()
    for root, dirnames, filenames in os.walk(normalized_dir):
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname not in {"__pycache__", ".git", ".idea", ".vscode", "backups"}
        ]
        for filename in filenames:
            if not filename.lower().endswith((".json", ".lca")):
                continue
            full_path = os.path.abspath(os.path.join(root, filename))
            project = _load_workspace_project(full_path)
            if project is None:
                continue
            workflow_files.add(project[1])
    return sorted(workflow_files, key=lambda path: path.lower())


def _normalize_saved_local_favorite(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    filepath = str(item.get("filepath") or "").strip()
    if not filepath:
        return None
    abs_path = os.path.abspath(filepath)
    normalized_item = {
        "filepath": abs_path,
        "checked": bool(item.get("checked", False)),
        "name": str(item.get("name") or "").strip(),
    }
    resource_path = str(item.get("resource_path") or "").strip()
    if resource_path:
        normalized_item["resource_path"] = os.path.abspath(os.path.normpath(resource_path))
    workspace_dir = normalize_workspace_dir(item.get("workspace_dir"))
    if workspace_dir:
        normalized_item["workspace_dir"] = workspace_dir
    if os.path.isfile(abs_path):
        project = _load_workspace_project(abs_path)
        if project is not None:
            normalized_item["filepath"] = project[1]
    return normalized_item


def _normalize_workspace_entries(raw_workspaces: Any) -> List[str]:
    normalized_workspaces: List[str] = []
    seen = set()
    if not isinstance(raw_workspaces, list):
        return normalized_workspaces

    for item in raw_workspaces:
        if isinstance(item, dict):
            workspace_dir = normalize_workspace_dir(item.get("path"))
        else:
            workspace_dir = normalize_workspace_dir(item)
        if not workspace_dir or workspace_dir in seen:
            continue
        seen.add(workspace_dir)
        normalized_workspaces.append(workspace_dir)
    return normalized_workspaces


def _normalize_path_list(raw_paths: Any) -> List[str]:
    normalized: List[str] = []
    seen = set()
    if not isinstance(raw_paths, list):
        return normalized
    for item in raw_paths:
        if isinstance(item, dict):
            raw_path = str(item.get("filepath") or item.get("path") or "").strip()
        else:
            raw_path = str(item or "").strip()
        if not raw_path:
            continue
        abs_path = os.path.abspath(raw_path)
        key = favorite_path_key(abs_path)
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(abs_path)
    return normalized


def workflow_matches_any(filepath: str, path_list: List[str]) -> bool:
    keys = set(workflow_path_keys(filepath))
    if not keys:
        return False
    for item in path_list or []:
        if keys & set(workflow_path_keys(item)):
            return True
    return False


def add_workspace_workflow(
    filepath: str,
    workspaces: List[str],
    excluded_paths: Optional[List[str]] = None,
    extra_paths: Optional[List[str]] = None,
) -> Tuple[str, List[str], List[str]]:
    resolved = resolve_existing_workflow_path(filepath)
    if not resolved or not os.path.isfile(resolved):
        return "invalid", _normalize_path_list(excluded_paths), _normalize_path_list(extra_paths)
    project = _load_workspace_project(resolved)
    if project is None:
        return "invalid", _normalize_path_list(excluded_paths), _normalize_path_list(extra_paths)

    abs_path = project[1]
    excluded = _normalize_path_list(excluded_paths)
    extras = _normalize_path_list(extra_paths)
    new_excluded = [path for path in excluded if not workflow_matches_any(abs_path, [path])]
    was_excluded = len(new_excluded) != len(excluded)
    in_workspace = any(path_is_under_workspace(abs_path, workspace) for workspace in workspaces)

    if in_workspace:
        return ("restored" if was_excluded else "exists"), new_excluded, extras

    if workflow_matches_any(abs_path, extras):
        return ("restored" if was_excluded else "exists"), new_excluded, extras

    extras.append(abs_path)
    return ("restored" if was_excluded else "added"), new_excluded, extras


def remove_workspace_workflow(
    filepath: str,
    workspaces: List[str],
    excluded_paths: Optional[List[str]] = None,
    extra_paths: Optional[List[str]] = None,
) -> Tuple[List[str], List[str]]:
    abs_path = os.path.abspath(str(filepath or "").strip())
    if os.path.isfile(abs_path):
        project = _load_workspace_project(abs_path)
        if project is not None:
            abs_path = project[1]
    excluded = _normalize_path_list(excluded_paths)
    extras = [path for path in _normalize_path_list(extra_paths) if not workflow_matches_any(abs_path, [path])]
    if any(path_is_under_workspace(abs_path, workspace) for workspace in workspaces):
        if not workflow_matches_any(abs_path, excluded):
            excluded.append(abs_path)
    return excluded, extras


def delete_workspace_workflow(filepath: str) -> str:
    resolved = resolve_existing_workflow_path(filepath)
    if not resolved or not os.path.isfile(resolved):
        raise FileNotFoundError(f"工作流文件不存在: {filepath}")
    os.remove(resolved)
    return resolved


def forget_deleted_workspace_workflow(
    filepath: str,
    workspaces: List[str],
    excluded_paths: Optional[List[str]] = None,
    extra_paths: Optional[List[str]] = None,
) -> Tuple[List[str], List[str]]:
    raw_path = str(filepath or "").strip()
    abs_path = os.path.abspath(raw_path) if raw_path else ""
    excluded = _normalize_path_list(excluded_paths)
    extras = [path for path in _normalize_path_list(extra_paths) if not workflow_matches_any(abs_path, [path])]
    if not abs_path:
        return excluded, extras
    if any(path_is_under_workspace(abs_path, workspace) for workspace in workspaces or []):
        if not workflow_matches_any(abs_path, excluded):
            excluded.append(abs_path)
    return excluded, extras


def explorer_select_args(filepath: str) -> List[str]:
    resolved = resolve_existing_workflow_path(filepath) or str(filepath or "").strip()
    return ["explorer", "/select," + os.path.normpath(os.path.abspath(resolved))]


def build_workspace_favorites(
    workspaces: List[str],
    saved_favorites: Optional[List[Dict[str, Any]]] = None,
    excluded_paths: Optional[List[str]] = None,
    extra_paths: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    saved_favorites = saved_favorites if isinstance(saved_favorites, list) else []
    excluded_paths = _normalize_path_list(excluded_paths)
    extra_paths = _normalize_path_list(extra_paths)
    saved_state_map: Dict[str, Dict[str, Any]] = {}

    for item in saved_favorites:
        normalized_item = _normalize_saved_local_favorite(item)
        if not normalized_item:
            continue
        saved_state_map[favorite_path_key(normalized_item["filepath"])] = normalized_item

    favorites: List[Dict[str, Any]] = []
    existing_keys: set = set()
    ordered_workspaces = sorted(
        (
            normalized
            for normalized in (normalize_workspace_dir(item) for item in workspaces)
            if normalized
        ),
        key=lambda path: (-len(path), path.lower()),
    )
    for normalized_workspace in ordered_workspaces:
        if not os.path.isdir(normalized_workspace):
            offline_entries: List[Dict[str, Any]] = []
            for item in saved_favorites:
                saved_state = _normalize_saved_local_favorite(item) if isinstance(item, dict) else None
                if not saved_state:
                    continue
                item_workspace = normalize_workspace_dir(
                    (item or {}).get("workspace_dir") if isinstance(item, dict) else ""
                ) or str(saved_state.get("workspace_dir") or "")
                if item_workspace != normalized_workspace and not path_is_under_workspace(
                    saved_state["filepath"],
                    normalized_workspace,
                ):
                    continue
                if workflow_matches_any(saved_state["filepath"], excluded_paths):
                    continue
                if set(workflow_path_keys(saved_state["filepath"])) & existing_keys:
                    continue
                offline_entries.append(
                    _make_workspace_favorite_entry(
                        saved_state["filepath"],
                        normalized_workspace,
                        saved_state,
                        None,
                    )
                )
            favorites.extend(offline_entries)
            for entry in offline_entries:
                existing_keys.update(workflow_path_keys(str(entry.get("filepath") or "")))
            continue

        for workflow_path in iter_workspace_workflow_files(normalized_workspace):
            if workflow_matches_any(workflow_path, excluded_paths):
                continue
            if set(workflow_path_keys(workflow_path)) & existing_keys:
                continue
            workflow_data = load_workspace_workflow(workflow_path)
            saved_state = _lookup_saved_favorite_state(workflow_path, saved_state_map)
            favorites.append(
                _make_workspace_favorite_entry(
                    workflow_path,
                    normalized_workspace,
                    saved_state,
                    workflow_data,
                )
            )
            existing_keys.update(workflow_path_keys(workflow_path))

    for extra_path in extra_paths:
        if workflow_matches_any(extra_path, excluded_paths):
            continue
        if set(workflow_path_keys(extra_path)) & existing_keys:
            continue
        workflow_data = load_workspace_workflow(extra_path) if os.path.isfile(extra_path) else None
        if workflow_data is None and os.path.isfile(extra_path):
            continue
        saved_state = _lookup_saved_favorite_state(extra_path, saved_state_map)
        workspace_dir = resolve_favorite_workspace_dir(extra_path, workspaces, current="")
        favorites.append(
            _make_workspace_favorite_entry(
                extra_path,
                workspace_dir,
                saved_state,
                workflow_data,
                source="extra",
            )
        )
        existing_keys.update(workflow_path_keys(extra_path))

    return favorites


def _lookup_saved_favorite_state(
    filepath: str,
    saved_state_map: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    for key in workflow_path_keys(filepath):
        saved_state = saved_state_map.get(key)
        if saved_state:
            return saved_state
    return {}


def _make_workspace_favorite_entry(
    filepath: str,
    workspace_dir: str,
    saved_state: Dict[str, Any],
    workflow_data: Optional[Dict[str, Any]],
    source: str = "workspace",
) -> Dict[str, Any]:
    resource_path = extract_workflow_resource_path(workflow_data) if workflow_data else ""
    if not resource_path:
        resource_path = str(saved_state.get("resource_path") or "").strip()
        if resource_path:
            resource_path = os.path.abspath(os.path.normpath(resource_path))

    display_name = str(saved_state.get("name") or "").strip()
    if not display_name:
        display_name = os.path.splitext(os.path.basename(filepath))[0]

    entry = {
        "name": display_name,
        "filepath": filepath,
        "checked": bool(saved_state.get("checked", False)),
        "source": source,
    }
    if workspace_dir:
        entry["workspace_dir"] = workspace_dir
    if resource_path:
        entry["resource_path"] = resource_path
    return entry


def load_workspace_favorites_snapshot(
    config_path: str,
    *,
    rebuild: bool = True,
) -> Tuple[List[str], List[Dict[str, Any]], List[str], List[str], bool]:
    """读取工作区收藏快照。

    ``rebuild`` 为真时会扫描工作区并解析其中的工作流文件，供收藏面板刷新使用。
    启动路径只需要已保存的收藏条目，传入假值可避免在主线程递归解包整个工作区。
    """
    if not config_path or not os.path.exists(config_path):
        return [], [], [], [], False

    with open(config_path, "r", encoding="utf-8") as file_obj:
        data = json.load(file_obj)

    if not isinstance(data, dict):
        raise ValueError("工作区配置必须是字典")
    if {"excluded", "extras"}.intersection(data):
        raise ValueError("工作区配置包含已停用字段，请使用 excluded_paths 和 extra_paths")

    raw_favorites = data.get("favorites")
    raw_workspaces = data.get("workspaces")
    excluded_paths = _normalize_path_list(data.get("excluded_paths"))
    extra_paths = _normalize_path_list(data.get("extra_paths"))

    workspaces = _normalize_workspace_entries(raw_workspaces)
    changed = False

    saved_favorites = raw_favorites if isinstance(raw_favorites, list) else []
    if rebuild:
        favorites = build_workspace_favorites(
            workspaces,
            saved_favorites,
            excluded_paths,
            extra_paths,
        )
    else:
        favorites = [dict(item) for item in saved_favorites if isinstance(item, dict)]

    expected_data = {
        "schema_version": WORKSPACE_FAVORITES_SCHEMA_VERSION,
        "workspaces": workspaces,
        "favorites": favorites,
        "excluded_paths": excluded_paths,
        "extra_paths": extra_paths,
    }
    if data != expected_data:
        changed = True
    return workspaces, favorites, excluded_paths, extra_paths, changed


def _existing_snapshot_path_lists(config_path: str) -> Tuple[List[str], List[str]]:
    if not config_path or not os.path.exists(config_path):
        return [], []
    with open(config_path, "r", encoding="utf-8") as file_obj:
        data = json.load(file_obj)
    if not isinstance(data, dict):
        raise ValueError("工作区配置必须是字典")
    if {"excluded", "extras"}.intersection(data):
        raise ValueError("工作区配置包含已停用字段，请使用 excluded_paths 和 extra_paths")
    return (
        _normalize_path_list(data.get("excluded_paths")),
        _normalize_path_list(data.get("extra_paths")),
    )


def save_workspace_favorites_snapshot(
    config_path: str,
    workspaces: List[str],
    favorites: List[Dict[str, Any]],
    excluded_paths: Optional[List[str]] = None,
    extra_paths: Optional[List[str]] = None,
) -> None:
    existing_excluded, existing_extras = _existing_snapshot_path_lists(config_path)
    if excluded_paths is None:
        excluded_paths = existing_excluded
    if extra_paths is None:
        extra_paths = existing_extras
    data = {
        "schema_version": WORKSPACE_FAVORITES_SCHEMA_VERSION,
        "workspaces": [normalize_workspace_dir(path) for path in workspaces if normalize_workspace_dir(path)],
        "favorites": favorites,
        "excluded_paths": _normalize_path_list(excluded_paths),
        "extra_paths": _normalize_path_list(extra_paths),
    }
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as file_obj:
        json.dump(data, file_obj, ensure_ascii=False, indent=2)


def _split_multi_image_value(raw_value: str) -> Tuple[List[str], str]:
    value = str(raw_value or "")
    if not value:
        return [], "\n"
    if "\n" in value or "\r" in value:
        return [line.strip() for line in value.splitlines()], "\n"
    if ";" in value:
        return [part.strip() for part in value.split(";")], ";"
    return [value.strip()], "\n"


def _strip_resource_prefix(relative_path: str) -> str:
    text = str(relative_path or "").replace("\\", "/").lstrip("./")
    lowered = text.lower()
    for prefix in ("images/", "sounds/", "dicts/", "yolo/", "replays/", "plugins/"):
        if lowered.startswith(prefix):
            return text[len(prefix):]
    return text


def _match_resource_file(raw_value: str, root: str) -> str:
    value = str(raw_value or "").strip()
    if not value or value.startswith("memory://"):
        return ""
    root_abs = normalize_workspace_dir(root)
    if not root_abs:
        return ""
    relative = _strip_resource_prefix(value)
    basename = os.path.basename(value.replace("\\", "/"))
    candidates = [
        os.path.join(root_abs, relative.replace("/", os.sep)),
        os.path.join(root_abs, basename),
    ]
    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        abs_candidate = os.path.abspath(candidate)
        key = os.path.normcase(abs_candidate)
        if key in seen:
            continue
        seen.add(key)
        if os.path.isfile(abs_candidate):
            return abs_candidate
    return ""


def _normalize_synced_resource_path(resolved: str, dest_dirs: Dict[str, Any]) -> str:
    abs_value = os.path.abspath(resolved)
    abs_key = os.path.normcase(abs_value)
    for key, folder in (
        ("sounds_dir", "sounds"),
        ("dicts_dir", "dicts"),
        ("yolo_dir", "yolo"),
        ("replays_dir", "replays"),
        ("images_dir", "images"),
    ):
        root = normalize_workspace_dir(str(dest_dirs.get(key) or ""))
        if not root:
            continue
        root_key = os.path.normcase(root)
        if abs_key == root_key:
            return folder
        if abs_key.startswith(root_key + os.sep):
            relative_path = os.path.relpath(abs_value, root).replace(os.sep, "/")
            return f"{folder}/{relative_path}"
    return normalize_workflow_image_path(
        resolved,
        images_dir=str(dest_dirs.get("images_dir") or ""),
    )


def _resource_param_kind(param_key: str) -> str:
    key = str(param_key or "").strip()
    if not key:
        return ""
    if key in {"image_paths", "raw_image_paths"} or key.endswith("_image_paths"):
        return "images_multi"
    if key in {"image_path", "template_path"} or key.endswith("_image_path"):
        return "image"
    if key in {"sound_path", "audio_path", "audio_file"} or key.endswith(
        ("_sound_path", "_audio_path", "_audio_file")
    ):
        return "sound"
    if key in {"dict_path", "dict_file"} or key.endswith(("_dict_path", "_dict_file")):
        return "dict"
    if key in {"model_path"} or key.endswith("_model_path"):
        return "model"
    if key in {"replay_path", "replay_file"} or key.endswith(("_replay_path", "_replay_file")):
        return "replay"
    return ""


def _sync_single_resource_value(
    raw_value: Any,
    root: str,
    dest_dirs: Dict[str, Any],
) -> Tuple[Any, bool]:
    value = str(raw_value or "").strip()
    if not value or value.startswith("memory://"):
        return raw_value, False
    resolved = _match_resource_file(value, root)
    if not resolved:
        return raw_value, False
    normalized_value = _normalize_synced_resource_path(resolved, dest_dirs)
    if normalized_value == raw_value:
        return raw_value, False
    return normalized_value, True


def _sync_multi_resource_value(
    raw_value: Any,
    root: str,
    dest_dirs: Dict[str, Any],
) -> Tuple[Any, int]:
    if not isinstance(raw_value, str):
        return raw_value, 0

    parts, separator = _split_multi_image_value(raw_value)
    if not parts:
        return raw_value, 0

    changed_count = 0
    normalized_parts: List[str] = []
    for part in parts:
        if not part or part.startswith("#"):
            normalized_parts.append(part)
            continue
        normalized_part, changed = _sync_single_resource_value(
            part,
            root,
            dest_dirs,
        )
        if changed:
            changed_count += 1
        normalized_parts.append(str(normalized_part or "").strip())

    if changed_count <= 0:
        return raw_value, 0

    if separator == ";":
        return ";".join(normalized_parts), changed_count
    return "\n".join(normalized_parts), changed_count


def sync_workflow_resources_from_root(workflow_data: Dict[str, Any], resource_dir: str) -> int:
    workflow_body = get_workflow_body(workflow_data)
    if not isinstance(workflow_body, dict):
        return 0
    root = normalize_workspace_dir(resource_dir)
    if not root or not os.path.isdir(root):
        return 0
    dest_dirs = project_resource_dirs(root)
    kind_roots = {
        "image": str(dest_dirs.get("images_dir") or ""),
        "sound": str(dest_dirs.get("sounds_dir") or ""),
        "dict": str(dest_dirs.get("dicts_dir") or ""),
        "model": str(dest_dirs.get("yolo_dir") or ""),
        "replay": str(dest_dirs.get("replays_dir") or ""),
    }

    cards = workflow_body.get("cards")
    if not isinstance(cards, list):
        return 0

    updated_count = 0
    for card_data in cards:
        if not isinstance(card_data, dict):
            continue
        parameters = card_data.get("parameters")
        if not isinstance(parameters, dict):
            continue

        for param_name, param_value in list(parameters.items()):
            kind = _resource_param_kind(param_name)
            if kind == "images_multi":
                normalized_value, changed_count = _sync_multi_resource_value(
                    param_value,
                    kind_roots["image"],
                    dest_dirs,
                )
                if changed_count > 0:
                    parameters[param_name] = normalized_value
                    updated_count += changed_count
                continue
            search_root = kind_roots.get(kind) or ""
            if not search_root:
                continue
            normalized_value, changed = _sync_single_resource_value(
                param_value,
                search_root,
                dest_dirs,
            )
            if changed:
                parameters[param_name] = normalized_value
                updated_count += 1

    return updated_count


def _workflow_file_token(filepath: str) -> str:
    raw = os.path.splitext(os.path.basename(str(filepath or "").strip()))[0]
    if not raw:
        return ""
    invalid_chars = set('<>:"/\\|?*')
    chars = []
    for ch in raw:
        if ch in invalid_chars or ord(ch) < 32 or ch.isspace():
            chars.append("_")
        else:
            chars.append(ch)
    token = "".join(chars).strip("._ ")
    while "__" in token:
        token = token.replace("__", "_")
    return token[:64]


def _path_is_under_root(path: str, root: str) -> bool:
    path_abs = normalize_workspace_dir(path)
    root_abs = normalize_workspace_dir(root)
    if not path_abs or not root_abs:
        return False
    path_key = os.path.normcase(path_abs)
    root_key = os.path.normcase(root_abs)
    return path_key == root_key or path_key.startswith(root_key + os.sep)


def _unique_dirs(*dirs: str) -> List[str]:
    result: List[str] = []
    seen = set()
    for raw in dirs:
        text = normalize_workspace_dir(raw)
        if not text:
            continue
        key = os.path.normcase(text)
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _card_id_value(card_data: Dict[str, Any]) -> Optional[int]:
    value = card_data.get("id")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _strip_leading_kind_folder(relative_path: str, folder: str) -> str:
    text = str(relative_path or "").replace("\\", "/").lstrip("./")
    folder_name = str(folder or "").strip("/").lower()
    if not text or not folder_name:
        return text
    lowered = text.lower()
    if lowered == folder_name:
        return ""
    prefix = folder_name + "/"
    if lowered.startswith(prefix):
        return text[len(prefix) :]
    if folder_name == "dicts":
        for extra in ("images/dicts/", "images/"):
            if lowered.startswith(extra):
                text = text[len(extra) :]
                lowered = text.lower()
                if extra == "images/" and lowered.startswith("dicts/"):
                    return text[len("dicts/") :]
                return text
    return text


def _resource_layout(
    kind: str,
    dest_dirs: Dict[str, Any],
    old_root: str,
    source_dirs: Dict[str, Any],
) -> Tuple[str, List[str], List[str], str]:
    dest_root = str(dest_dirs.get("root") or "")
    old_images = os.path.join(old_root, "images") if old_root else ""
    old_sounds = os.path.join(old_root, "sounds") if old_root else ""
    old_dicts = os.path.join(old_root, "dicts") if old_root else ""
    old_yolo = os.path.join(old_root, "yolo") if old_root else ""
    old_replays = os.path.join(old_root, "replays") if old_root else ""
    if kind == "sound":
        dest_kind = str(dest_dirs.get("sounds_dir") or "")
        return (
            dest_kind,
            _unique_dirs(old_sounds, old_root, str(source_dirs.get("sounds_dir") or "")),
            _unique_dirs(dest_kind, old_sounds, str(source_dirs.get("sounds_dir") or "")),
            "sounds",
        )
    if kind == "dict":
        dest_kind = str(dest_dirs.get("dicts_dir") or "")
        return (
            dest_kind,
            _unique_dirs(
                old_dicts,
                os.path.join(old_images, "dicts") if old_images else "",
                old_root,
                str(source_dirs.get("dicts_dir") or ""),
                str(source_dirs.get("images_dir") or ""),
            ),
            _unique_dirs(
                dest_kind,
                old_dicts,
                str(source_dirs.get("dicts_dir") or ""),
                str(source_dirs.get("images_dir") or ""),
            ),
            "dicts",
        )
    if kind == "model":
        dest_kind = str(dest_dirs.get("yolo_dir") or "")
        return (
            dest_kind,
            _unique_dirs(old_yolo, old_root, str(source_dirs.get("yolo_dir") or "")),
            _unique_dirs(dest_kind, old_yolo, str(source_dirs.get("yolo_dir") or "")),
            "yolo",
        )
    if kind == "replay":
        dest_kind = str(dest_dirs.get("replays_dir") or "")
        return (
            dest_kind,
            _unique_dirs(old_replays, old_root, str(source_dirs.get("replays_dir") or "")),
            _unique_dirs(dest_kind, old_replays, str(source_dirs.get("replays_dir") or "")),
            "replays",
        )
    dest_kind = str(dest_dirs.get("images_dir") or dest_root)
    return (
        dest_kind,
        _unique_dirs(old_images, old_root, str(source_dirs.get("images_dir") or "")),
        _unique_dirs(dest_kind, old_images, str(source_dirs.get("images_dir") or "")),
        "images",
    )


def _locate_resource_source(
    raw_value: str,
    dest_kind_dir: str,
    search_dirs: List[str],
    dest_root: str = "",
) -> str:
    value = str(raw_value or "").strip()
    if not value or value.startswith("memory://"):
        return ""
    for root in _unique_dirs(dest_kind_dir, dest_root):
        found = _match_resource_file(value, root)
        if found:
            return found
    if os.path.isabs(value) and os.path.isfile(value):
        return os.path.abspath(value)
    for root in search_dirs:
        found = _match_resource_file(value, root)
        if found:
            return found
    return ""


def _resource_dest_path(
    src: str,
    dest_kind_dir: str,
    preserve_roots: List[str],
    kind_folder: str,
) -> str:
    src_abs = os.path.abspath(src)
    for root in preserve_roots:
        if not _path_is_under_root(src_abs, root):
            continue
        relative = os.path.relpath(src_abs, root).replace("\\", "/")
        relative = _strip_leading_kind_folder(relative, kind_folder)
        if not relative or relative in {".", ""}:
            return os.path.join(dest_kind_dir, os.path.basename(src_abs))
        return os.path.join(dest_kind_dir, *relative.split("/"))
    return os.path.join(dest_kind_dir, os.path.basename(src_abs))


def _try_copy_resource_file(src: str, dest: str) -> Tuple[str, bool]:
    src_abs = os.path.abspath(src)
    dest_abs = os.path.abspath(dest)
    if os.path.normcase(src_abs) == os.path.normcase(dest_abs):
        return dest_abs, False
    if os.path.isfile(dest_abs):
        return dest_abs, False
    try:
        parent = os.path.dirname(dest_abs)
        if parent:
            os.makedirs(parent, exist_ok=True)
        shutil.copy2(src_abs, dest_abs)
    except OSError:
        return "", False
    return dest_abs, True


def _copy_model_sidecars(src_file: str, dest_file: str) -> int:
    if os.path.splitext(src_file)[1].lower() != ".onnx":
        return 0
    src_classes = os.path.join(os.path.dirname(os.path.abspath(src_file)), "classes.txt")
    if not os.path.isfile(src_classes):
        return 0
    dest_classes = os.path.join(os.path.dirname(os.path.abspath(dest_file)), "classes.txt")
    _dest, copied = _try_copy_resource_file(src_classes, dest_classes)
    return 1 if copied else 0


def _migrate_one_resource_path(
    raw_value: Any,
    kind: str,
    dest_dirs: Dict[str, Any],
    old_root: str,
    source_dirs: Dict[str, Any],
) -> Tuple[Any, int, int, int]:
    value = str(raw_value or "").strip()
    if not value or value.startswith("memory://"):
        return raw_value, 0, 0, 0
    dest_kind_dir, search_dirs, preserve_roots, kind_folder = _resource_layout(
        kind,
        dest_dirs,
        old_root,
        source_dirs,
    )
    extra_dest = str(dest_dirs.get("root") or "") if kind in {"image", "dict"} else ""
    source_path = _locate_resource_source(value, dest_kind_dir, search_dirs, extra_dest)
    if not source_path:
        return raw_value, 0, 1, 0
    dest_path = _resource_dest_path(source_path, dest_kind_dir, preserve_roots, kind_folder)
    dest_file, copied = _try_copy_resource_file(source_path, dest_path)
    if not dest_file or not os.path.isfile(dest_file):
        return raw_value, 0, 1, 0
    copied_count = 1 if copied else 0
    if kind == "model":
        copied_count += _copy_model_sidecars(source_path, dest_file)
    normalized = _normalize_synced_resource_path(dest_file, dest_dirs)
    if normalized == value:
        return raw_value, copied_count, 0, 0
    return normalized, copied_count, 0, 1


def _migrate_multi_resource_paths(
    raw_value: Any,
    dest_dirs: Dict[str, Any],
    old_root: str,
    source_dirs: Dict[str, Any],
) -> Tuple[Any, int, int, int]:
    if not isinstance(raw_value, str):
        return raw_value, 0, 0, 0
    parts, separator = _split_multi_image_value(raw_value)
    if not parts:
        return raw_value, 0, 0, 0
    copied_count = 0
    missing_count = 0
    updated_count = 0
    normalized_parts: List[str] = []
    for part in parts:
        if not part or part.startswith("#"):
            normalized_parts.append(part)
            continue
        new_part, copied, missing, updated = _migrate_one_resource_path(
            part,
            "image",
            dest_dirs,
            old_root,
            source_dirs,
        )
        copied_count += copied
        missing_count += missing
        updated_count += updated
        normalized_parts.append(str(new_part or "").strip())
    if updated_count <= 0:
        return raw_value, copied_count, missing_count, 0
    if separator == ";":
        return ";".join(normalized_parts), copied_count, missing_count, updated_count
    return "\n".join(normalized_parts), copied_count, missing_count, updated_count


def _script_migrate_kind(item: Dict[str, Any]) -> str:
    kind = str(item.get("kind") or "").strip().lower()
    mapping = {
        "image": "image",
        "audio": "sound",
        "model": "model",
        "replay": "replay",
    }
    if kind in mapping:
        return mapping[kind]
    return ""


def migrate_workflow_resources_to_dir(
    workflow_data: Dict[str, Any],
    dest_dir: str,
    *,
    source_images_dir: str = "",
    source_sounds_dir: str = "",
    source_yolo_dir: str = "",
    source_replays_dir: str = "",
    workflow_filepath: str = "",
) -> Dict[str, Any]:
    """把工作流引用的分类资源复制到 dest_dir，并改写卡片路径。不删除源文件。"""
    dest_root = normalize_workspace_dir(dest_dir)
    if not dest_root:
        raise ValueError("资源目录不能为空")
    ensure_workflow_resource_subdirs(dest_root)
    dest_dirs = project_resource_dirs(dest_root)
    app_root = get_app_root()
    images_source = (
        normalize_workspace_dir(source_images_dir)
        if str(source_images_dir or "").strip()
        else get_images_dir("LCA")
    )
    sounds_source = (
        normalize_workspace_dir(source_sounds_dir)
        if str(source_sounds_dir or "").strip()
        else get_sounds_dir("LCA")
    )
    if str(source_images_dir or "").strip():
        dicts_source = os.path.join(images_source, "dicts")
    else:
        dicts_source = get_dicts_dir("LCA")
    source_dirs = {
        "images_dir": images_source,
        "sounds_dir": sounds_source,
        "dicts_dir": dicts_source,
        "yolo_dir": (
            normalize_workspace_dir(source_yolo_dir)
            if str(source_yolo_dir or "").strip()
            else os.path.join(app_root, "yolo")
        ),
        "replays_dir": (
            normalize_workspace_dir(source_replays_dir)
            if str(source_replays_dir or "").strip()
            else os.path.join(app_root, "replays")
        ),
        "plugins_dir": get_plugin_dir(),
    }

    old_root = extract_workflow_resource_path(workflow_data)
    if old_root and os.path.normcase(old_root) == os.path.normcase(dest_root):
        old_root = ""

    workflow_body = get_workflow_body(workflow_data)
    cards = workflow_body.get("cards") if isinstance(workflow_body, dict) else None
    if not isinstance(cards, list):
        return {"copied_count": 0, "missing_count": 0, "updated_count": 0}

    from task_workflow.script_resources import (
        list_card_files,
        list_script_resources,
        resource_kind,
        rewrite_resource_literal,
    )

    copied_count = 0
    missing_count = 0
    updated_count = 0
    workflow_token = _workflow_file_token(workflow_filepath)
    migrate_kinds = {"image", "sound", "dict", "model", "replay"}

    for card_data in cards:
        if not isinstance(card_data, dict):
            continue
        parameters = card_data.get("parameters")
        if not isinstance(parameters, dict):
            continue

        for param_name, param_value in list(parameters.items()):
            kind = _resource_param_kind(param_name)
            if kind == "images_multi":
                new_value, copied, missing, updated = _migrate_multi_resource_paths(
                    param_value,
                    dest_dirs,
                    old_root,
                    source_dirs,
                )
                copied_count += copied
                missing_count += missing
                updated_count += updated
                if updated > 0:
                    parameters[param_name] = new_value
                continue
            if kind in migrate_kinds:
                new_value, copied, missing, updated = _migrate_one_resource_path(
                    param_value,
                    kind,
                    dest_dirs,
                    old_root,
                    source_dirs,
                )
                copied_count += copied
                missing_count += missing
                updated_count += updated
                if updated > 0:
                    parameters[param_name] = new_value

        source = str(parameters.get("script_source") or "")
        if not source.strip():
            continue
        card_id = _card_id_value(card_data)
        rewritten = source
        script_updated = 0
        for item in list_script_resources(
            source,
            images_dir=images_source,
            sounds_dir=sounds_source,
            card_id=card_id,
            workflow_token=workflow_token,
            yolo_dir=str(source_dirs.get("yolo_dir") or ""),
            replays_dir=str(source_dirs.get("replays_dir") or ""),
            dicts_dir=str(source_dirs.get("dicts_dir") or ""),
        ):
            if int(item.get("used") or 0) <= 0:
                continue
            migrate_kind = _script_migrate_kind(item)
            if not migrate_kind:
                continue
            raw_path = str(item.get("path") or "").strip()
            if not raw_path:
                continue
            new_value, copied, missing, updated = _migrate_one_resource_path(
                raw_path,
                migrate_kind,
                dest_dirs,
                old_root,
                source_dirs,
            )
            copied_count += copied
            missing_count += missing
            if updated > 0 and new_value:
                rewritten = rewrite_resource_literal(rewritten, raw_path, str(new_value))
                script_updated += 1
        if rewritten != source:
            parameters["script_source"] = rewritten
            if str(parameters.get("script_source_sha256") or "").strip():
                from tasks.script_task import script_source_hash

                parameters["script_source_sha256"] = script_source_hash(rewritten)
            updated_count += script_updated

    prefix_roots = _unique_dirs(
        old_root,
        os.path.join(old_root, "images") if old_root else "",
        os.path.join(old_root, "sounds") if old_root else "",
        os.path.join(old_root, "yolo") if old_root else "",
        os.path.join(old_root, "replays") if old_root else "",
        images_source,
        sounds_source,
        str(source_dirs.get("yolo_dir") or ""),
        str(source_dirs.get("replays_dir") or ""),
    )
    kind_map = {
        "audio": "sound",
        "image": "image",
        "model": "model",
        "replay": "replay",
    }
    for card_data in cards:
        if not isinstance(card_data, dict):
            continue
        card_id = _card_id_value(card_data)
        if card_id is None:
            continue
        for root in prefix_roots:
            for abs_path in list_card_files(root, card_id, workflow_token):
                migrate_kind = kind_map.get(resource_kind(abs_path) or "")
                if not migrate_kind:
                    continue
                dest_kind_dir, _search_dirs, preserve_roots, kind_folder = _resource_layout(
                    migrate_kind,
                    dest_dirs,
                    old_root,
                    source_dirs,
                )
                dest_path = _resource_dest_path(
                    abs_path,
                    dest_kind_dir,
                    preserve_roots,
                    kind_folder,
                )
                dest_file, copied = _try_copy_resource_file(abs_path, dest_path)
                if copied:
                    copied_count += 1
                if dest_file and migrate_kind == "model":
                    copied_count += _copy_model_sidecars(abs_path, dest_file)

    return {
        "copied_count": copied_count,
        "missing_count": missing_count,
        "updated_count": updated_count,
    }


def update_workflow_resource_path(filepath: str, resource_dir: str) -> Dict[str, Any]:
    workflow_path = str(filepath or "").strip()
    if not workflow_path:
        raise ValueError("工作流路径不能为空")
    normalized_resource = normalize_workspace_dir(resource_dir)
    if not normalized_resource or not os.path.isdir(normalized_resource):
        raise ValueError("资源目录不存在")
    if not is_exclusive_workflow_dir(normalized_resource, workflow_path):
        raise ValueError("该文件夹已有其他工作流")

    project = _load_workspace_project(workflow_path)
    if project is None:
        raise ValueError("工作流文件不存在或格式无效")
    workflow_data, workflow_path = project

    metadata = workflow_data.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        workflow_data["metadata"] = metadata

    ensure_workflow_resource_subdirs(normalized_resource)
    migrate_result = migrate_workflow_resources_to_dir(
        workflow_data,
        normalized_resource,
        workflow_filepath=workflow_path,
    )
    copied_count = int(migrate_result.get("copied_count") or 0)
    missing_count = int(migrate_result.get("missing_count") or 0)
    updated_count = int(migrate_result.get("updated_count") or 0)
    metadata["custom_resource_path"] = normalized_resource

    stem = os.path.splitext(os.path.basename(workflow_path))[0]
    dest_file = os.path.join(normalized_resource, f"{stem}.lca")
    if os.path.isfile(workflow_path):
        try:
            backup_workflow_file(workflow_path)
        except OSError as exc:
            raise ValueError(f"备份失败，已取消更新资源路径: {exc}") from exc
    saved_path = _relocate_workspace_workflow(workflow_path, dest_file, workflow_data)

    return {
        "resource_path": normalized_resource,
        "updated_count": updated_count,
        "copied_count": copied_count,
        "missing_count": missing_count,
        "workflow_data": workflow_data,
        "changed": True,
        "filepath": saved_path,
    }


def _relocate_workspace_workflow(
    src_path: str,
    dest_path: str,
    workflow_data: Dict[str, Any],
) -> str:
    src_abs = os.path.abspath(str(src_path or "").strip())
    dest_abs = os.path.abspath(str(dest_path or "").strip())
    if not dest_abs:
        raise ValueError("工作流路径不能为空")
    dest_dir = os.path.dirname(dest_abs)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)
    same = bool(src_abs) and os.path.normcase(src_abs) == os.path.normcase(dest_abs)
    if (
        not same
        and src_abs.lower().endswith(".lca")
        and dest_abs.lower().endswith(".lca")
        and os.path.isfile(src_abs)
        and not os.path.isfile(dest_abs)
    ):
        shutil.copy2(src_abs, dest_abs)
    saved = _write_workspace_workflow(dest_abs, workflow_data)
    saved_abs = os.path.abspath(saved)
    if (
        not same
        and src_abs
        and os.path.isfile(src_abs)
        and os.path.normcase(src_abs) != os.path.normcase(saved_abs)
    ):
        try:
            os.remove(src_abs)
        except OSError:
            pass
    return saved


def _write_workspace_workflow(filepath: str, workflow_data: Dict[str, Any]) -> str:
    abs_path = os.path.abspath(str(filepath or "").strip())
    if not abs_path:
        raise ValueError("工作流路径不能为空")
    if not abs_path.lower().endswith(".lca"):
        raise ValueError("只能保存现行 .lca 工程，旧格式须先经工程转换")
    from app_core.lca_format.container import seal_lca_bytes
    from app_core.lca_format.project_io import load_lca_project

    _payload, session = load_lca_project(abs_path)
    try:
        files = session.snapshot_files()
        manifest = json.loads(files["manifest.json"].decode("utf-8"))
        entry = manifest["entry_workflow"]
        files[entry] = json.dumps(workflow_data, ensure_ascii=False, indent=4).encode("utf-8")
        sealed = seal_lca_bytes(files)
    finally:
        session.close()
    tmp_path = abs_path + ".tmp"
    try:
        with open(tmp_path, "wb") as handle:
            handle.write(sealed)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, abs_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return abs_path
