from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set

from task_workflow.sub_workflow_path import resolve_sub_workflow_path
from task_workflow.workflow_payload import workflow_body
from task_workflow.workflow_sanitize import sanitize_workflow_data
from task_workflow.workspace import resolve_runtime_resource_dirs
from task_workflow.script_resources import (
    DICT_TEXT_EXTS,
    IMAGE_EXTS,
    list_script_resources,
    resource_kind,
    rewrite_resource_literal,
)
from utils.app_paths import (
    get_images_dir,
    get_sounds_dir,
)
from utils.image_paths import get_image_path_resolver


YOLO_TASK_TYPES = {"YOLO目标检测"}
SUB_WORKFLOW_TASK_TYPE = "子工作流"
SCRIPT_TASK_TYPE = "自定义脚本"
PATH_PARAM_KEYS = {
    "image_path",
    "image_paths",
    "template_path",
    "workflow_file",
    "dict_path",
    "dict_file",
    "sound_path",
    "audio_path",
    "audio_file",
    "model_path",
}


@dataclass
class CollectedAsset:
    kind: str
    source: str
    package_relpath: str
    workflow_data: Optional[Dict[str, Any]] = None
    content: Optional[bytes] = None


@dataclass
class CollectionResult:
    workflow_data: Dict[str, Any]
    assets: List[CollectedAsset] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    has_yolo: bool = False


def _as_path_list(value: Any) -> List[str]:
    from task_workflow.resource_path import format_resource_text, unwrap_resource_path

    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        paths = []
        for item in value:
            text = unwrap_resource_path(item) if not isinstance(item, str) else item.strip()
            if text:
                paths.append(text)
        return paths
    text = format_resource_text(value)
    if not text:
        return []
    if "\n" in text:
        return [line.strip() for line in text.splitlines() if line.strip()]
    return [text]


def _normalize_package_files(files: Optional[Mapping[str, bytes]]) -> Dict[str, bytes]:
    normalized: Dict[str, bytes] = {}
    for path, data in dict(files or {}).items():
        logical = str(path or "").strip().replace("\\", "/")
        if logical.startswith("memory://"):
            logical = logical[len("memory://") :]
        logical = logical.lstrip("/")
        if logical:
            normalized[logical] = bytes(data)
    return normalized


def _package_file(
    package_files: Mapping[str, bytes],
    raw_path: object,
    *,
    parent_workflow_file: str = "",
    kind: str = "",
) -> tuple[str, Optional[bytes]]:
    logical = str(raw_path or "").strip().replace("\\", "/")
    if logical.startswith("memory://"):
        logical = logical[len("memory://") :]
    logical = logical.lstrip("/")
    candidates = [logical]
    if logical.startswith("images/"):
        candidates.append(f"assets/{logical}")
    if logical.startswith("sounds/"):
        candidates.append(f"assets/{logical}")
    if logical.startswith("dicts/"):
        candidates.append(f"assets/{logical}")
    if logical.startswith("assets/dicts/"):
        candidates.append(logical[len("assets/") :])
    if str(kind or "").strip() == "dict" or _is_packaged_dict_path(logical):
        name = Path(logical).name
        if name:
            candidates.extend(
                (
                    f"dicts/{name}",
                    f"assets/dicts/{name}",
                    f"assets/images/dicts/{name}",
                    f"images/dicts/{name}",
                    f"assets/images/{name}",
                    f"images/{name}",
                    name,
                )
            )
    parent = str(parent_workflow_file or "").replace("\\", "/")
    if parent and not os.path.isabs(parent):
        folder = str(Path(parent).parent).replace("\\", "/")
        if folder not in {"", "."}:
            candidates.append(f"{folder}/{logical}".lstrip("/"))
    for candidate in candidates:
        data = package_files.get(candidate)
        if data is not None:
            return candidate, data
    return logical, None


def _resolve_existing_file(
    raw_path: str,
    images_dir: str,
    sounds_dir: str,
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
    dicts_dir: str = "",
) -> str:
    text = str(raw_path or "").strip()
    if not text or text.startswith("memory://"):
        return ""
    if os.path.isfile(text):
        return os.path.abspath(text)

    from task_workflow.script_resources import resolve_resource_path

    resolved = resolve_resource_path(
        text,
        images_dir=images_dir,
        sounds_dir=sounds_dir,
        yolo_dir=yolo_dir,
        replays_dir=replays_dir,
        plugins_dir=plugins_dir,
        dicts_dir=dicts_dir,
        enforce_jail=False,
    )
    if resolved and os.path.isfile(resolved):
        return os.path.abspath(resolved)

    resolver = get_image_path_resolver()
    resolved = resolver.resolve(text)
    if resolved and os.path.isfile(resolved):
        return os.path.abspath(resolved)
    return ""


def _unique_relpath(used: Set[str], kind: str, source_path: str) -> str:
    name = os.path.basename(source_path) or "asset"
    folder = {
        "image": "assets/images",
        "audio": "assets/sounds",
        "model": "assets/yolo",
        "replay": "assets/replays",
        "dict": "assets/dicts",
        "component": "assets/components",
        "workflow": "workflows/subs",
    }.get(kind, "assets/misc")
    relpath = f"{folder}/{name}".replace("\\", "/")
    if relpath not in used:
        used.add(relpath)
        return relpath
    stem, ext = os.path.splitext(name)
    index = 2
    while True:
        candidate = f"{folder}/{stem}_{index}{ext}".replace("\\", "/")
        if candidate not in used:
            used.add(candidate)
            return candidate
        index += 1


def _rewrite_image_value(source_path: str, relpath: str) -> str:
    # 独立程序包内图片统一走 memory://，运行时只在内存中提供，不落盘
    if relpath.startswith("assets/images/"):
        return "memory://images/" + relpath[len("assets/images/") :]
    if relpath.startswith("assets/"):
        return "memory://" + relpath
    return "memory://" + relpath.lstrip("/")


def _logical_export_path(kind: str, relpath: str, source_path: str) -> str:
    name = os.path.basename(str(relpath or "").replace("\\", "/"))
    if kind == "image":
        return _rewrite_image_value(source_path, relpath)
    if kind == "audio":
        return name
    if kind == "model":
        return f"yolo/{name}" if name else relpath
    if kind == "component":
        return f"plugins/{name}" if name else relpath
    if kind == "replay":
        return f"replays/{name}" if name else relpath
    if kind == "dict":
        return f"dicts/{name}" if name else relpath
    return relpath


def _register_model_sidecars(
    result: CollectionResult,
    model_abs: str,
    used_relpaths: Set[str],
) -> None:
    parent = os.path.dirname(os.path.abspath(str(model_abs or "").strip()))
    if not parent:
        return
    sidecar = os.path.join(parent, "classes.txt")
    if os.path.isfile(sidecar):
        _register_asset(result, "model", sidecar, used_relpaths)


def collect_workflow_package(
    workflow_data: Mapping[str, Any],
    *,
    parent_workflow_file: str = "",
    images_dir: str = "",
    sounds_dir: str = "",
    preloaded_files: Optional[Mapping[str, bytes]] = None,
) -> CollectionResult:
    package_files = _normalize_package_files(preloaded_files)
    if not package_files and str(parent_workflow_file or "").lower().endswith(".lca"):
        from app_core.lca_format.project_io import load_lca_project

        _loaded, session = load_lca_project(parent_workflow_file)
        package_files = session.snapshot_files()
    result = CollectionResult(workflow_data=sanitize_workflow_data(json.loads(json.dumps(workflow_data))))
    resource_dirs = resolve_runtime_resource_dirs(
        result.workflow_data,
        workflow_filepath=parent_workflow_file,
        default_images_dir=str(images_dir or "").strip() or get_images_dir("LCA"),
    )
    images_root = str(resource_dirs.get("images_dir") or "")
    sounds_root = str(resource_dirs.get("sounds_dir") or "").strip() or str(sounds_dir or "").strip() or get_sounds_dir("LCA")
    yolo_root = str(resource_dirs.get("yolo_dir") or "")
    replays_root = str(resource_dirs.get("replays_dir") or "")
    plugins_root = str(resource_dirs.get("plugins_dir") or "")
    dicts_root = str(resource_dirs.get("dicts_dir") or "")
    used_relpaths: Set[str] = set()
    visited_workflows: Set[str] = set()
    _collect_workflow(
        result,
        result.workflow_data,
        parent_workflow_file=parent_workflow_file,
        images_dir=images_root,
        sounds_dir=sounds_root,
        yolo_dir=yolo_root,
        replays_dir=replays_root,
        plugins_dir=plugins_root,
        dicts_dir=dicts_root,
        used_relpaths=used_relpaths,
        visited_workflows=visited_workflows,
        package_files=package_files,
    )
    return result


def _is_packaged_dict_path(normalized: str) -> bool:
    lowered = str(normalized or "").replace("\\", "/").lower().lstrip("/")
    suffix = Path(lowered).suffix
    if suffix == ".dict":
        return True
    return "/dicts/" in f"/{lowered}" or lowered.startswith(("dicts/", "assets/dicts/"))


def _collect_disk_gallery(
    result: CollectionResult,
    root: str,
    used_relpaths: Set[str],
    *,
    dicts_tree: bool,
) -> None:
    base = str(root or "").strip()
    if not base or not os.path.isdir(base):
        return
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in {"__pycache__", ".git", ".idea", ".vscode", "backups"}
        ]
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            abs_path = os.path.abspath(os.path.join(dirpath, filename))
            is_dict = dicts_tree or "dicts" in Path(dirpath).parts or ext == ".dict"
            if is_dict:
                if ext not in DICT_TEXT_EXTS and ext not in IMAGE_EXTS:
                    continue
                kind = "dict"
            elif ext not in IMAGE_EXTS:
                continue
            else:
                kind = "image"
            _register_asset(result, kind, abs_path, used_relpaths)


def _collect_gallery_tree(
    result: CollectionResult,
    images_dir: str,
    used_relpaths: Set[str],
    package_files: Mapping[str, bytes],
    dicts_dir: str = "",
) -> None:
    for logical_path, data in package_files.items():
        normalized = logical_path.replace("\\", "/").lstrip("/")
        if not normalized.startswith(("assets/images/", "images/", "assets/dicts/", "dicts/")):
            continue
        suffix = Path(normalized).suffix.lower()
        if _is_packaged_dict_path(normalized):
            if suffix not in DICT_TEXT_EXTS and suffix not in IMAGE_EXTS:
                continue
            kind = "dict"
        elif suffix not in IMAGE_EXTS:
            continue
        else:
            kind = "image"
        _register_asset(
            result,
            kind,
            f"memory://{normalized}",
            used_relpaths,
            content=data,
        )
    images_root = str(images_dir or "").strip()
    _collect_disk_gallery(result, images_root, used_relpaths, dicts_tree=False)
    dicts_root = str(dicts_dir or "").strip()
    if not dicts_root or not os.path.isdir(dicts_root):
        return
    images_key = os.path.normcase(os.path.abspath(images_root)) if images_root else ""
    dicts_key = os.path.normcase(os.path.abspath(dicts_root))
    if images_key and (dicts_key == images_key or dicts_key.startswith(images_key + os.sep)):
        return
    _collect_disk_gallery(result, dicts_root, used_relpaths, dicts_tree=True)


def _collect_workflow(
    result: CollectionResult,
    workflow_data: Dict[str, Any],
    *,
    parent_workflow_file: str,
    images_dir: str,
    sounds_dir: str,
    used_relpaths: Set[str],
    visited_workflows: Set[str],
    package_files: Mapping[str, bytes],
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
    dicts_dir: str = "",
) -> None:
    body = workflow_body(workflow_data)
    resource_dirs = resolve_runtime_resource_dirs(
        workflow_data,
        workflow_filepath=parent_workflow_file,
        default_images_dir=images_dir,
    )
    if resource_dirs.get("custom") or (
        str(parent_workflow_file or "").strip() and os.path.isfile(parent_workflow_file)
    ):
        local_images = str(resource_dirs.get("images_dir") or images_dir)
        local_sounds = str(resource_dirs.get("sounds_dir") or sounds_dir)
        local_yolo = str(resource_dirs.get("yolo_dir") or yolo_dir)
        local_replays = str(resource_dirs.get("replays_dir") or replays_dir)
        local_plugins = str(resource_dirs.get("plugins_dir") or plugins_dir)
        local_dicts = str(resource_dirs.get("dicts_dir") or dicts_dir)
    else:
        local_images = images_dir
        local_sounds = sounds_dir
        local_yolo = yolo_dir
        local_replays = replays_dir
        local_plugins = plugins_dir
        local_dicts = dicts_dir
    cards = body.get("cards")
    if not isinstance(cards, list):
        result.errors.append("工作流缺少 cards")
        return

    for card in cards:
        if not isinstance(card, Mapping):
            continue
        task_type = str(card.get("task_type") or "").strip()
        if task_type in YOLO_TASK_TYPES:
            result.has_yolo = True
        parameters = card.get("parameters")
        if not isinstance(parameters, dict):
            continue
        if task_type == SCRIPT_TASK_TYPE:
            _collect_script_resources(
                result,
                parameters,
                images_dir=local_images,
                sounds_dir=local_sounds,
                yolo_dir=local_yolo,
                replays_dir=local_replays,
                plugins_dir=local_plugins,
                dicts_dir=local_dicts,
                used_relpaths=used_relpaths,
                package_files=package_files,
            )
        if task_type == SUB_WORKFLOW_TASK_TYPE:
            _collect_sub_workflow(
                result,
                parameters,
                card_id=card.get("id"),
                parent_workflow_file=parent_workflow_file,
                images_dir=local_images,
                sounds_dir=local_sounds,
                yolo_dir=local_yolo,
                replays_dir=local_replays,
                plugins_dir=local_plugins,
                dicts_dir=local_dicts,
                used_relpaths=used_relpaths,
                visited_workflows=visited_workflows,
                package_files=package_files,
            )
        _collect_parameter_files(
            result,
            parameters,
            images_dir=local_images,
            sounds_dir=local_sounds,
            yolo_dir=local_yolo,
            replays_dir=local_replays,
            plugins_dir=local_plugins,
            dicts_dir=local_dicts,
            used_relpaths=used_relpaths,
            skip_keys={"workflow_file"} if task_type == SUB_WORKFLOW_TASK_TYPE else set(),
            package_files=package_files,
        )
        if task_type in YOLO_TASK_TYPES and not str(parameters.get("model_path") or "").strip():
            default_model = _resolve_existing_file(
                "yolo/yolov8n.onnx",
                local_images,
                local_sounds,
                yolo_dir=local_yolo,
                replays_dir=local_replays,
                plugins_dir=local_plugins,
                dicts_dir=local_dicts,
            )
            if default_model:
                _register_asset(result, "model", default_model, used_relpaths)
                _register_model_sidecars(result, default_model, used_relpaths)
            else:
                result.errors.append(
                    f"卡片 {card.get('id')} 的 YOLO 模型文件不存在: yolo/yolov8n.onnx"
                )
    _collect_gallery_tree(
        result,
        local_images,
        used_relpaths,
        package_files,
        dicts_dir=local_dicts,
    )


def _collect_script_resources(
    result: CollectionResult,
    parameters: Dict[str, Any],
    *,
    images_dir: str,
    sounds_dir: str,
    used_relpaths: Set[str],
    package_files: Mapping[str, bytes],
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
    dicts_dir: str = "",
) -> None:
    source = str(parameters.get("script_source") or "")
    if not source.strip():
        return
    from tasks.script_task import script_source_hash

    expected = parameters.get("script_source_sha256")
    if expected and expected != script_source_hash(source):
        result.errors.append("自定义脚本源码完整性校验失败，拒绝导出")
        return
    resources = list_script_resources(
        source,
        images_dir=images_dir,
        sounds_dir=sounds_dir,
        yolo_dir=yolo_dir,
        replays_dir=replays_dir,
        plugins_dir=plugins_dir,
        dicts_dir=dicts_dir,
    )
    rewritten = source
    for item in resources:
        kind = str(item.get("kind") or "")
        raw_path = str(item.get("path") or "")
        abs_path = str(item.get("abs_path") or "")
        if kind == "model":
            result.has_yolo = True
        logical_path, package_data = _package_file(package_files, raw_path, kind=kind)
        if package_data is not None:
            relpath = _register_asset(
                result,
                kind or "image",
                f"memory://{logical_path}",
                used_relpaths,
                content=package_data,
            )
            replacement = _logical_export_path(kind or "image", relpath, raw_path)
            rewritten = rewrite_resource_literal(rewritten, raw_path, replacement)
            continue
        if not abs_path or not os.path.isfile(abs_path):
            result.errors.append(f"脚本资源不存在: {raw_path}")
            continue
        relpath = _register_asset(result, kind or "image", abs_path, used_relpaths)
        if kind == "model":
            _register_model_sidecars(result, abs_path, used_relpaths)
        replacement = _logical_export_path(kind or "image", relpath, abs_path)
        rewritten = rewrite_resource_literal(rewritten, raw_path, replacement)
    parameters["script_source"] = rewritten
    parameters["script_source_sha256"] = script_source_hash(rewritten)


def _nested_workflow_has_yolo(workflow_data: Mapping[str, Any]) -> bool:
    body = workflow_body(workflow_data)
    cards = body.get("cards")
    if not isinstance(cards, list):
        return False
    for card in cards:
        if not isinstance(card, dict):
            continue
        if str(card.get("task_type") or "").strip() in YOLO_TASK_TYPES:
            return True
        parameters = card.get("parameters")
        if isinstance(parameters, dict) and str(parameters.get("model_path") or "").strip():
            return True
    return False


def _card_label(card_id: Any) -> str:
    if card_id is None or card_id == "":
        return "子工作流卡片"
    return f"子工作流卡片 #{card_id}"


def _collect_sub_workflow(
    result: CollectionResult,
    parameters: Dict[str, Any],
    *,
    card_id: Any = None,
    parent_workflow_file: str,
    images_dir: str,
    sounds_dir: str,
    yolo_dir: str,
    replays_dir: str,
    plugins_dir: str,
    dicts_dir: str,
    used_relpaths: Set[str],
    visited_workflows: Set[str],
    package_files: Mapping[str, bytes],
) -> None:
    label = _card_label(card_id)
    raw_path = str(parameters.get("workflow_file") or "").strip()
    if not raw_path:
        result.errors.append(f"{label}未填写工作流文件")
        return
    logical_path, package_data = _package_file(
        package_files,
        raw_path,
        parent_workflow_file=parent_workflow_file,
    )
    if package_data is not None:
        real = f"memory://{logical_path}"
        if real in visited_workflows:
            result.warnings.append(f"{label}重复引用，已跳过: {raw_path}")
            return
        visited_workflows.add(real)
        try:
            from app_core.lca_format.container import LcaFormatError
            from app_core.lca_format.project_io import (
                _workflow_contains_sub_workflow,
                load_lca_from_bytes,
            )

            nested, _nested_session = load_lca_from_bytes(package_data)
        except LcaFormatError as exc:
            result.errors.append(f"无法读取{label}的工作流 {raw_path}: {exc}")
            return
        if not isinstance(nested, dict):
            result.errors.append(f"{label}的工作流格式无效: {raw_path}")
            return
        if _workflow_contains_sub_workflow(nested):
            result.errors.append(f"{label}不允许再嵌套子工作流")
            return
        relpath = _register_asset(
            result,
            "workflow",
            real,
            used_relpaths,
            content=package_data,
        )
        parameters["workflow_file"] = os.path.relpath(relpath, "workflows").replace("\\", "/")
        if _nested_workflow_has_yolo(nested):
            result.has_yolo = True
        return
    resolved = resolve_sub_workflow_path(raw_path, parent_workflow_file=parent_workflow_file)
    if not resolved or not os.path.isfile(resolved):
        result.errors.append(f"{label}的工作流文件不存在: {raw_path}")
        return
    real = os.path.abspath(resolved)
    if real in visited_workflows:
        result.warnings.append(f"{label}重复引用，已跳过: {raw_path}")
        return
    visited_workflows.add(real)
    try:
        from app_core.lca_format.container import LcaFormatError
        from app_core.lca_format.project_io import (
            _workflow_contains_sub_workflow,
            is_lca_path,
            load_lca_project,
            seal_workflow_package,
        )

        if not is_lca_path(real):
            result.errors.append(f"{label}的工作流必须是 .lca 工程: {raw_path}")
            return
        nested, nested_session = load_lca_project(real)
        if not isinstance(nested, dict):
            result.errors.append(f"{label}的工作流格式无效: {raw_path}")
            return
        if _workflow_contains_sub_workflow(nested):
            result.errors.append(f"{label}不允许再嵌套子工作流")
            return
        sealed = seal_workflow_package(
            nested,
            source_session=nested_session,
            display_name=Path(real).stem,
            source_dir=str(Path(real).parent),
            workflow_filepath=real,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError, LcaFormatError) as exc:
        result.errors.append(f"无法读取{label}的工作流 {raw_path}: {exc}")
        return
    relpath = _register_asset(
        result,
        "workflow",
        real,
        used_relpaths,
        content=sealed,
    )
    parameters["workflow_file"] = os.path.relpath(relpath, "workflows").replace("\\", "/")
    if _nested_workflow_has_yolo(nested):
        result.has_yolo = True


def _collect_parameter_files(
    result: CollectionResult,
    parameters: Dict[str, Any],
    *,
    images_dir: str,
    sounds_dir: str,
    used_relpaths: Set[str],
    skip_keys: Optional[Set[str]] = None,
    package_files: Mapping[str, bytes],
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
    dicts_dir: str = "",
) -> None:
    ignored = skip_keys or set()
    for key, value in list(parameters.items()):
        if key in ignored:
            continue
        if key not in PATH_PARAM_KEYS and not (
            isinstance(value, str) and resource_kind(value)
        ):
            if key not in PATH_PARAM_KEYS:
                continue
        paths = _as_path_list(value)
        if not paths:
            continue
        rewritten: List[str] = []
        for raw_path in paths:
            kind = resource_kind(raw_path) or ("audio" if "sound" in key or "audio" in key else "image")
            if key in {"dict_file", "dict_path"} or kind == "dict":
                kind = "dict"
            elif key == "model_path" or kind == "model":
                kind = "model"
                result.has_yolo = True
            logical_path, package_data = _package_file(package_files, raw_path, kind=kind)
            if package_data is not None:
                relpath = _register_asset(
                    result,
                    kind,
                    f"memory://{logical_path}",
                    used_relpaths,
                    content=package_data,
                )
                rewritten.append(_logical_export_path(kind, relpath, raw_path))
                continue
            abs_path = _resolve_existing_file(
                raw_path,
                images_dir,
                sounds_dir,
                yolo_dir=yolo_dir,
                replays_dir=replays_dir,
                plugins_dir=plugins_dir,
                dicts_dir=dicts_dir,
            )
            if not abs_path:
                result.errors.append(f"资源文件不存在: {raw_path}")
                rewritten.append(raw_path)
                continue
            relpath = _register_asset(result, kind, abs_path, used_relpaths)
            if kind == "model":
                _register_model_sidecars(result, abs_path, used_relpaths)
            rewritten.append(_logical_export_path(kind, relpath, abs_path))
        if isinstance(value, str) and "\n" in value:
            parameters[key] = "\n".join(rewritten)
        elif isinstance(value, list):
            parameters[key] = rewritten
        elif rewritten:
            parameters[key] = rewritten[0]


def _register_asset(
    result: CollectionResult,
    kind: str,
    source_path: str,
    used_relpaths: Set[str],
    *,
    content: Optional[bytes] = None,
) -> str:
    for existing in result.assets:
        if os.path.normcase(existing.source) == os.path.normcase(source_path):
            return existing.package_relpath
    relpath = _unique_relpath(used_relpaths, kind, source_path)
    result.assets.append(
        CollectedAsset(
            kind=kind,
            source=source_path,
            package_relpath=relpath,
            content=bytes(content) if content is not None else None,
        )
    )
    return relpath


def collection_to_memory_files(
    result: CollectionResult,
    entry_name: str = "workflows/main.json",
) -> Dict[str, bytes]:
    """把工作流和资源读进内存，不在磁盘生成明文 package 目录。"""
    files: Dict[str, bytes] = {}
    for asset in result.assets:
        relpath = str(asset.package_relpath or "").replace("\\", "/").lstrip("/")
        if not relpath:
            continue
        if asset.workflow_data is not None:
            files[relpath] = json.dumps(asset.workflow_data, ensure_ascii=False, indent=4).encode("utf-8")
            continue
        if asset.content is not None:
            files[relpath] = bytes(asset.content)
            continue
        source = Path(asset.source)
        files[relpath] = source.read_bytes()
    files[entry_name] = json.dumps(result.workflow_data, ensure_ascii=False, indent=4).encode("utf-8")
    return files


def write_collected_package(package_dir: Path, result: CollectionResult, entry_name: str = "workflows/main.json") -> None:
    package_dir.mkdir(parents=True, exist_ok=True)
    for asset in result.assets:
        destination = package_dir / asset.package_relpath
        destination.parent.mkdir(parents=True, exist_ok=True)
        if asset.workflow_data is not None:
            destination.write_text(
                json.dumps(asset.workflow_data, ensure_ascii=False, indent=4),
                encoding="utf-8",
            )
            continue
        if asset.content is not None:
            destination.write_bytes(asset.content)
            continue
        shutil.copy2(asset.source, destination)

    entry_path = package_dir / entry_name
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    entry_path.write_text(
        json.dumps(result.workflow_data, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )
