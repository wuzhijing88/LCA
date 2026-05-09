import json
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

from tasks.task_utils import get_image_path_resolver
from utils.app_paths import normalize_workflow_image_path


WORKSPACE_FAVORITES_SCHEMA_VERSION = 2


def favorite_path_key(filepath: str) -> str:
    normalized = str(filepath or "").strip()
    if not normalized:
        return ""
    return os.path.normcase(os.path.abspath(normalized))


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
    return data


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
            if not filename.lower().endswith(".json"):
                continue
            full_path = os.path.abspath(os.path.join(root, filename))
            workflow_data = load_workflow_json(full_path)
            if workflow_data is None:
                continue
            workflow_files.append(full_path)
    workflow_files.sort(key=lambda path: path.lower())
    return workflow_files


def _normalize_saved_local_favorite(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    filepath = str(item.get("filepath") or "").strip()
    if not filepath:
        return None
    abs_path = os.path.abspath(filepath)
    return {
        "filepath": abs_path,
        "checked": bool(item.get("checked", True)),
        "name": str(item.get("name") or "").strip(),
    }


def _normalize_saved_manual_favorite(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return None


def _derive_workspaces_from_legacy_favorites(raw_favorites: Iterable[Dict[str, Any]]) -> List[str]:
    workspaces: List[str] = []
    seen = set()
    for item in raw_favorites or []:
        normalized_item = _normalize_saved_local_favorite(item)
        if not normalized_item:
            continue
        workspace_dir = normalize_workspace_dir(os.path.dirname(normalized_item["filepath"]))
        if not workspace_dir or workspace_dir in seen or not os.path.isdir(workspace_dir):
            continue
        seen.add(workspace_dir)
        workspaces.append(workspace_dir)
    return workspaces


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
        if not workspace_dir or workspace_dir in seen or not os.path.isdir(workspace_dir):
            continue
        seen.add(workspace_dir)
        normalized_workspaces.append(workspace_dir)
    return normalized_workspaces


def build_workspace_favorites(
    workspaces: List[str],
    saved_favorites: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    saved_favorites = saved_favorites if isinstance(saved_favorites, list) else []
    saved_state_map: Dict[str, Dict[str, Any]] = {}
    manual_favorites: List[Dict[str, Any]] = []

    for item in saved_favorites:
        manual_entry = _normalize_saved_manual_favorite(item)
        if manual_entry:
            manual_favorites.append(manual_entry)
            continue

        normalized_item = _normalize_saved_local_favorite(item)
        if not normalized_item:
            continue
        saved_state_map[favorite_path_key(normalized_item["filepath"])] = normalized_item

    favorites: List[Dict[str, Any]] = []
    for workspace_dir in workspaces:
        for workflow_path in iter_workspace_workflow_files(workspace_dir):
            workflow_data = load_workflow_json(workflow_path)
            gallery_path = extract_workflow_gallery_path(workflow_data)
            saved_state = saved_state_map.get(favorite_path_key(workflow_path), {})
            display_name = str(saved_state.get("name") or "").strip()
            if not display_name:
                display_name = os.path.splitext(os.path.basename(workflow_path))[0]

            favorites.append(
                {
                    "name": display_name,
                    "filepath": workflow_path,
                    "checked": bool(saved_state.get("checked", False)),
                    "workspace_dir": workspace_dir,
                    "gallery_path": gallery_path,
                    "source": "workspace",
                }
            )

    favorites.extend(manual_favorites)
    return favorites


def load_workspace_favorites_snapshot(config_path: str) -> Tuple[List[str], List[Dict[str, Any]], bool]:
    if not config_path or not os.path.exists(config_path):
        return [], [], False

    try:
        with open(config_path, "r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
    except Exception:
        return [], [], False

    if not isinstance(data, dict):
        return [], [], True

    raw_favorites = data.get("favorites")
    raw_workspaces = data.get("workspaces")

    workspaces = _normalize_workspace_entries(raw_workspaces)
    changed = False
    if not workspaces and isinstance(raw_favorites, list):
        workspaces = _derive_workspaces_from_legacy_favorites(raw_favorites)
        if workspaces:
            changed = True

    favorites = build_workspace_favorites(workspaces, raw_favorites if isinstance(raw_favorites, list) else [])

    expected_data = {
        "schema_version": WORKSPACE_FAVORITES_SCHEMA_VERSION,
        "workspaces": workspaces,
        "favorites": favorites,
    }
    if data != expected_data:
        changed = True
    return workspaces, favorites, changed


def save_workspace_favorites_snapshot(
    config_path: str,
    workspaces: List[str],
    favorites: List[Dict[str, Any]],
) -> None:
    data = {
        "schema_version": WORKSPACE_FAVORITES_SCHEMA_VERSION,
        "workspaces": [normalize_workspace_dir(path) for path in workspaces if normalize_workspace_dir(path)],
        "favorites": favorites,
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
    workflow_data = load_workflow_json(workflow_path)
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

    if changed:
        with open(workflow_path, "w", encoding="utf-8") as file_obj:
            json.dump(workflow_data, file_obj, ensure_ascii=False, indent=2)

    return {
        "gallery_path": normalized_gallery,
        "updated_image_count": updated_image_count,
        "workflow_data": workflow_data,
        "changed": changed,
    }
