import json
import os
from typing import Any, Dict, List, Optional, Tuple

from utils.image_paths import get_image_path_resolver
from utils.app_paths import normalize_workflow_image_path


WORKSPACE_FAVORITES_SCHEMA_VERSION = 3


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
    abs_path = os.path.abspath(raw_path)
    if os.path.isfile(abs_path):
        return abs_path
    root, extension = os.path.splitext(abs_path)
    if extension.lower() == ".json":
        sibling = root + ".lca"
    elif extension.lower() == ".lca":
        sibling = root + ".json"
    else:
        return abs_path
    if os.path.isfile(sibling):
        return sibling
    return abs_path


def backup_workflow_file(filepath: str) -> str:
    import shutil
    from datetime import datetime

    abs_filepath = os.path.abspath(str(filepath or "").strip())
    if not abs_filepath or not os.path.isfile(abs_filepath):
        raise FileNotFoundError(f"工作流文件不存在: {filepath}")

    backups_dir = os.path.join(os.path.dirname(abs_filepath), "backups")
    os.makedirs(backups_dir, exist_ok=True)
    name, extension = os.path.splitext(os.path.basename(abs_filepath))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backups_dir, f"{name}_backup_{timestamp}{extension or '.lca'}")
    shutil.copy2(abs_filepath, backup_path)
    return backup_path


def workflow_path_keys(filepath: str) -> List[str]:
    raw_path = str(filepath or "").strip()
    if not raw_path:
        return []

    candidates = [raw_path]
    root, extension = os.path.splitext(raw_path)
    if extension.lower() == ".json":
        candidates.append(root + ".lca")
    elif extension.lower() == ".lca":
        candidates.append(root + ".json")

    keys: List[str] = []
    seen = set()
    for candidate in candidates:
        key = favorite_path_key(candidate)
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


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


def load_workflow_json(filepath: str) -> Optional[Dict[str, Any]]:
    workflow_path = str(filepath or "").strip()
    if not workflow_path or not os.path.exists(workflow_path):
        return None
    try:
        with open(workflow_path, "r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
    except Exception:
        return None
    if not is_workflow_json_data(data):
        return None
    from task_workflow.workflow_sanitize import sanitize_workflow_data

    return sanitize_workflow_data(data)


def load_workspace_workflow(filepath: str) -> Optional[Dict[str, Any]]:
    workflow_path = str(filepath or "").strip()
    if not workflow_path or not os.path.exists(workflow_path):
        return None
    if workflow_path.lower().endswith(".lca"):
        try:
            from app_core.lca_format.project_io import load_lca_project

            data, _session = load_lca_project(workflow_path)
        except Exception:
            return None
        if not is_workflow_json_data(data):
            return None
        from task_workflow.workflow_sanitize import sanitize_workflow_data

        return sanitize_workflow_data(data)
    return load_workflow_json(workflow_path)


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


def extract_workflow_gallery_path(workflow_data: Optional[Dict[str, Any]]) -> str:
    metadata = extract_workflow_metadata(workflow_data)
    gallery_path = str(metadata.get("custom_gallery_path") or "").strip()
    if not gallery_path:
        return ""
    return os.path.abspath(os.path.normpath(gallery_path))


def get_effective_workflow_images_dir(
    workflow_data: Optional[Dict[str, Any]],
    default_images_dir: str,
) -> str:
    gallery_path = extract_workflow_gallery_path(workflow_data)
    if gallery_path and os.path.isdir(gallery_path):
        return gallery_path
    return str(default_images_dir or "").strip()


def iter_workspace_workflow_files(workspace_dir: str) -> List[str]:
    normalized_dir = normalize_workspace_dir(workspace_dir)
    if not normalized_dir or not os.path.isdir(normalized_dir):
        return []

    workflow_files: List[str] = []
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
            workflow_data = load_workspace_workflow(full_path)
            if workflow_data is None:
                continue
            workflow_files.append(full_path)
    workflow_files.sort(key=lambda path: path.lower())
    lca_keys = {
        favorite_path_key(path)
        for path in workflow_files
        if path.lower().endswith(".lca")
    }
    filtered_files: List[str] = []
    for path in workflow_files:
        if path.lower().endswith(".json"):
            sibling_lca = os.path.splitext(path)[0] + ".lca"
            if favorite_path_key(sibling_lca) in lca_keys:
                continue
        filtered_files.append(path)
    return filtered_files


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
    gallery_path = str(item.get("gallery_path") or "").strip()
    if gallery_path:
        normalized_item["gallery_path"] = os.path.abspath(os.path.normpath(gallery_path))
    workspace_dir = normalize_workspace_dir(item.get("workspace_dir"))
    if workspace_dir:
        normalized_item["workspace_dir"] = workspace_dir
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
    if load_workspace_workflow(resolved) is None:
        return "invalid", _normalize_path_list(excluded_paths), _normalize_path_list(extra_paths)

    abs_path = os.path.abspath(resolved)
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
        for candidate in _workflow_sibling_paths(abs_path):
            if not workflow_matches_any(candidate, excluded):
                excluded.append(os.path.abspath(candidate))
    return excluded, extras


def _workflow_sibling_paths(filepath: str) -> List[str]:
    raw_path = str(filepath or "").strip()
    if not raw_path:
        return []
    abs_path = os.path.abspath(raw_path)
    candidates = [abs_path]
    root, extension = os.path.splitext(abs_path)
    if extension.lower() == ".json":
        candidates.append(root + ".lca")
    elif extension.lower() == ".lca":
        candidates.append(root + ".json")
    return candidates


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
    for workspace_dir in workspaces:
        normalized_workspace = normalize_workspace_dir(workspace_dir)
        if not normalized_workspace:
            continue
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
                offline_entries.append(
                    _make_workspace_favorite_entry(
                        saved_state["filepath"],
                        normalized_workspace,
                        saved_state,
                        None,
                    )
                )
            favorites.extend(_prefer_lca_sibling_favorites(offline_entries))
            continue

        for workflow_path in iter_workspace_workflow_files(normalized_workspace):
            if workflow_matches_any(workflow_path, excluded_paths):
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

    existing_keys = set()
    for favorite in favorites:
        existing_keys.update(workflow_path_keys(str(favorite.get("filepath") or "")))
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


def _prefer_lca_sibling_favorites(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_stem: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for entry in entries:
        stem = workflow_stem_key(str(entry.get("filepath") or ""))
        if not stem:
            continue
        existing = by_stem.get(stem)
        if existing is None:
            by_stem[stem] = entry
            order.append(stem)
            continue
        incoming_is_lca = str(entry.get("filepath") or "").lower().endswith(".lca")
        existing_is_lca = str(existing.get("filepath") or "").lower().endswith(".lca")
        keep = entry if incoming_is_lca and not existing_is_lca else existing
        drop = existing if keep is entry else entry
        keep["checked"] = bool(keep.get("checked")) or bool(drop.get("checked"))
        if not str(keep.get("name") or "").strip():
            keep["name"] = drop.get("name") or keep.get("name")
        if not keep.get("gallery_path") and drop.get("gallery_path"):
            keep["gallery_path"] = drop.get("gallery_path")
        by_stem[stem] = keep
    return [by_stem[stem] for stem in order]


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
    gallery_path = extract_workflow_gallery_path(workflow_data) if workflow_data else ""
    if not gallery_path:
        gallery_path = str(saved_state.get("gallery_path") or "").strip()
        if gallery_path:
            gallery_path = os.path.abspath(os.path.normpath(gallery_path))

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
    if gallery_path:
        entry["gallery_path"] = gallery_path
    return entry


def load_workspace_favorites_snapshot(
    config_path: str,
) -> Tuple[List[str], List[Dict[str, Any]], List[str], List[str], bool]:
    if not config_path or not os.path.exists(config_path):
        return [], [], [], [], False

    try:
        with open(config_path, "r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
    except Exception:
        return [], [], [], [], False

    if not isinstance(data, dict):
        return [], [], [], [], True

    raw_favorites = data.get("favorites")
    raw_workspaces = data.get("workspaces")
    excluded_paths = _read_named_path_list(data, "excluded_paths", "excluded")
    extra_paths = _read_named_path_list(data, "extra_paths", "extras")

    workspaces = _normalize_workspace_entries(raw_workspaces)
    changed = False

    favorites = build_workspace_favorites(
        workspaces,
        raw_favorites if isinstance(raw_favorites, list) else [],
        excluded_paths,
        extra_paths,
    )

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


def _read_named_path_list(data: Dict[str, Any], primary: str, fallback: str) -> List[str]:
    if primary in data:
        return _normalize_path_list(data.get(primary))
    if fallback in data:
        return _normalize_path_list(data.get(fallback))
    return []


def _existing_snapshot_path_lists(config_path: str) -> Tuple[List[str], List[str]]:
    if not config_path or not os.path.exists(config_path):
        return [], []
    try:
        with open(config_path, "r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
    except Exception:
        return [], []
    if not isinstance(data, dict):
        return [], []
    return (
        _read_named_path_list(data, "excluded_paths", "excluded"),
        _read_named_path_list(data, "extra_paths", "extras"),
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


def _sync_single_image_value(
    resolver,
    raw_value: Any,
) -> Tuple[Any, bool]:
    value = str(raw_value or "").strip()
    if not value or value.startswith("memory://"):
        return raw_value, False
    resolved = resolver.resolve(value)
    if not resolved:
        return raw_value, False
    normalized_value = normalize_workflow_image_path(resolved)
    if normalized_value == raw_value:
        return raw_value, False
    return normalized_value, True


def _sync_multi_image_value(
    resolver,
    raw_value: Any,
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
        normalized_part, changed = _sync_single_image_value(resolver, part)
        if changed:
            changed_count += 1
        normalized_parts.append(str(normalized_part or "").strip())

    if changed_count <= 0:
        return raw_value, 0

    if separator == ";":
        return ";".join(normalized_parts), changed_count
    return "\n".join(normalized_parts), changed_count


def sync_workflow_images_from_gallery(workflow_data: Dict[str, Any], gallery_dir: str) -> int:
    workflow_body = get_workflow_body(workflow_data)
    if not isinstance(workflow_body, dict):
        return 0
    normalized_gallery = normalize_workspace_dir(gallery_dir)
    if not normalized_gallery or not os.path.isdir(normalized_gallery):
        return 0

    resolver = get_image_path_resolver()
    resolver.add_search_path(normalized_gallery, priority=0)

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
            param_key = str(param_name or "").strip()
            if not param_key:
                continue

            if param_key == "image_path" or param_key.endswith("_image_path"):
                normalized_value, changed = _sync_single_image_value(resolver, param_value)
                if changed:
                    parameters[param_name] = normalized_value
                    updated_count += 1
                continue

            if param_key == "image_paths" or param_key == "raw_image_paths" or param_key.endswith("_image_paths"):
                normalized_value, changed_count = _sync_multi_image_value(resolver, param_value)
                if changed_count > 0:
                    parameters[param_name] = normalized_value
                    updated_count += changed_count

    return updated_count


def update_workflow_gallery_path(filepath: str, gallery_dir: str) -> Dict[str, Any]:
    workflow_path = str(filepath or "").strip()
    if not workflow_path:
        raise ValueError("工作流路径不能为空")
    workflow_data = load_workspace_workflow(workflow_path)
    if workflow_data is None:
        raise ValueError("工作流文件不存在或格式无效")

    normalized_gallery = normalize_workspace_dir(gallery_dir)
    if normalized_gallery and not os.path.isdir(normalized_gallery):
        raise ValueError("图库目录不存在")

    metadata = workflow_data.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        workflow_data["metadata"] = metadata

    old_gallery = str(metadata.get("custom_gallery_path") or "").strip()
    changed = False
    if normalized_gallery:
        if old_gallery != normalized_gallery:
            metadata["custom_gallery_path"] = normalized_gallery
            changed = True
    elif old_gallery:
        metadata.pop("custom_gallery_path", None)
        changed = True

    updated_image_count = 0
    if normalized_gallery:
        updated_image_count = sync_workflow_images_from_gallery(workflow_data, normalized_gallery)
        if updated_image_count > 0:
            changed = True

    saved_path = workflow_path
    if changed:
        if os.path.isfile(workflow_path):
            try:
                backup_workflow_file(workflow_path)
            except OSError as exc:
                raise ValueError(f"备份失败，已取消更新图库: {exc}") from exc
        from task_workflow.workflow_payload import save_workflow_file

        saved_path = str(save_workflow_file(workflow_path, workflow_data))

    return {
        "gallery_path": normalized_gallery,
        "updated_image_count": updated_image_count,
        "workflow_data": workflow_data,
        "changed": changed,
        "filepath": saved_path,
    }
