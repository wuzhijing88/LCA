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
from task_workflow.workspace import get_effective_workflow_images_dir
from ui.dialogs.script_resources import IMAGE_EXTS, list_script_resources, resource_kind
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
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
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


def _resolve_existing_file(raw_path: str, images_dir: str, sounds_dir: str) -> str:
    text = str(raw_path or "").strip()
    if not text or text.startswith("memory://"):
        return ""
    if os.path.isfile(text):
        return os.path.abspath(text)

    kind = resource_kind(text)
    candidates = []
    if kind == "audio":
        candidates.append(os.path.join(sounds_dir, os.path.basename(text)))
    if kind in {"image", "model", ""}:
        candidates.append(os.path.join(images_dir, os.path.basename(text)))
        if text.replace("\\", "/").lower().startswith("images/"):
            candidates.append(os.path.join(images_dir, text.replace("\\", "/")[7:]))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return os.path.abspath(candidate)

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
        "model": "assets/models",
        "dict": "assets/images/dicts",
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
    sounds_root = str(sounds_dir or "").strip() or get_sounds_dir("LCA")
    result = CollectionResult(workflow_data=sanitize_workflow_data(json.loads(json.dumps(workflow_data))))
    images_root = get_effective_workflow_images_dir(
        result.workflow_data,
        str(images_dir or "").strip() or get_images_dir("LCA"),
    )
    used_relpaths: Set[str] = set()
    visited_workflows: Set[str] = set()
    _collect_workflow(
        result,
        result.workflow_data,
        parent_workflow_file=parent_workflow_file,
        images_dir=images_root,
        sounds_dir=sounds_root,
        used_relpaths=used_relpaths,
        visited_workflows=visited_workflows,
        package_files=package_files,
    )
    return result


def _collect_gallery_tree(
    result: CollectionResult,
    images_dir: str,
    used_relpaths: Set[str],
    package_files: Mapping[str, bytes],
) -> None:
    for logical_path, data in package_files.items():
        normalized = logical_path.replace("\\", "/").lstrip("/")
        if not normalized.startswith(("assets/images/", "images/")):
            continue
        if Path(normalized).suffix.lower() not in IMAGE_EXTS:
            continue
        kind = "dict" if "/dicts/" in f"/{normalized}" else "image"
        _register_asset(
            result,
            kind,
            f"memory://{normalized}",
            used_relpaths,
            content=data,
        )
    root = str(images_dir or "").strip()
    if not root or not os.path.isdir(root):
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in {"__pycache__", ".git", ".idea", ".vscode", "backups"}
        ]
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in IMAGE_EXTS:
                continue
            abs_path = os.path.abspath(os.path.join(dirpath, filename))
            kind = "dict" if "dicts" in Path(dirpath).parts else "image"
            _register_asset(result, kind, abs_path, used_relpaths)


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
) -> None:
    body = workflow_body(workflow_data)
    local_images = get_effective_workflow_images_dir(workflow_data, images_dir)
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
            result.errors.append(f"卡片 {card.get('id')} 使用了 YOLO，官方独立包不包含 YOLO 模型")
        parameters = card.get("parameters")
        if not isinstance(parameters, dict):
            continue
        if task_type == SCRIPT_TASK_TYPE:
            _collect_script_resources(
                result,
                parameters,
                images_dir=local_images,
                sounds_dir=sounds_dir,
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
                sounds_dir=sounds_dir,
                used_relpaths=used_relpaths,
                visited_workflows=visited_workflows,
                package_files=package_files,
            )
        _collect_parameter_files(
            result,
            parameters,
            images_dir=local_images,
            sounds_dir=sounds_dir,
            used_relpaths=used_relpaths,
            skip_keys={"workflow_file"} if task_type == SUB_WORKFLOW_TASK_TYPE else set(),
            package_files=package_files,
        )
    _collect_gallery_tree(result, local_images, used_relpaths, package_files)


def _collect_script_resources(
    result: CollectionResult,
    parameters: Dict[str, Any],
    *,
    images_dir: str,
    sounds_dir: str,
    used_relpaths: Set[str],
    package_files: Mapping[str, bytes],
) -> None:
    source = str(parameters.get("script_source") or "")
    if not source.strip():
        return
    resources = list_script_resources(source, images_dir=images_dir, sounds_dir=sounds_dir)
    rewritten = source
    for item in resources:
        kind = str(item.get("kind") or "")
        raw_path = str(item.get("path") or "")
        abs_path = str(item.get("abs_path") or "")
        if kind == "model":
            result.has_yolo = True
            result.errors.append(f"脚本引用了模型文件，独立导出不支持: {raw_path}")
            continue
        logical_path, package_data = _package_file(package_files, raw_path)
        if package_data is not None:
            relpath = _register_asset(
                result,
                kind or "image",
                f"memory://{logical_path}",
                used_relpaths,
                content=package_data,
            )
            replacement = _rewrite_image_value(raw_path, relpath) if kind == "image" else os.path.basename(relpath)
            if raw_path and raw_path in rewritten:
                rewritten = rewritten.replace(raw_path, replacement)
            continue
        if not abs_path or not os.path.isfile(abs_path):
            result.errors.append(f"脚本资源不存在: {raw_path}")
            continue
        relpath = _register_asset(result, kind or "image", abs_path, used_relpaths)
        replacement = _rewrite_image_value(abs_path, relpath) if kind == "image" else os.path.basename(relpath)
        if raw_path and raw_path in rewritten:
            rewritten = rewritten.replace(raw_path, replacement)
    parameters["script_source"] = rewritten


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
            nested = json.loads(package_data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
            result.errors.append(f"无法读取{label}的工作流 {raw_path}: {exc}")
            return
        if not isinstance(nested, dict):
            result.errors.append(f"{label}的工作流格式无效: {raw_path}")
            return
        relpath = _register_asset(
            result,
            "workflow",
            real,
            used_relpaths,
            content=package_data,
        )
        parameters["workflow_file"] = os.path.relpath(relpath, "workflows").replace("\\", "/")
        _collect_workflow(
            result,
            nested,
            parent_workflow_file=logical_path,
            images_dir=images_dir,
            sounds_dir=sounds_dir,
            used_relpaths=used_relpaths,
            visited_workflows=visited_workflows,
            package_files=package_files,
        )
        for asset in result.assets:
            if asset.source == real and asset.kind == "workflow":
                asset.workflow_data = sanitize_workflow_data(nested)
                asset.content = None
                break
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
    relpath = _register_asset(result, "workflow", real, used_relpaths)
    parameters["workflow_file"] = os.path.relpath(relpath, "workflows").replace("\\", "/")
    try:
        nested = json.loads(Path(real).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        result.errors.append(f"无法读取{label}的工作流 {raw_path}: {exc}")
        return
    if not isinstance(nested, dict):
        result.errors.append(f"{label}的工作流格式无效: {raw_path}")
        return
    _collect_workflow(
        result,
        nested,
        parent_workflow_file=real,
        images_dir=images_dir,
        sounds_dir=sounds_dir,
        used_relpaths=used_relpaths,
        visited_workflows=visited_workflows,
        package_files=package_files,
    )
    for asset in result.assets:
        if asset.source == real and asset.kind == "workflow":
            asset.workflow_data = sanitize_workflow_data(nested)
            break


def _collect_parameter_files(
    result: CollectionResult,
    parameters: Dict[str, Any],
    *,
    images_dir: str,
    sounds_dir: str,
    used_relpaths: Set[str],
    skip_keys: Optional[Set[str]] = None,
    package_files: Mapping[str, bytes],
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
            if kind == "model":
                result.has_yolo = True
                result.errors.append(f"参数 {key} 引用了模型文件: {raw_path}")
                rewritten.append(raw_path)
                continue
            logical_path, package_data = _package_file(package_files, raw_path)
            if package_data is not None:
                relpath = _register_asset(
                    result,
                    kind,
                    f"memory://{logical_path}",
                    used_relpaths,
                    content=package_data,
                )
                if kind == "image":
                    rewritten.append(_rewrite_image_value(raw_path, relpath))
                elif kind == "audio":
                    rewritten.append(os.path.basename(relpath))
                else:
                    rewritten.append(relpath)
                continue
            abs_path = _resolve_existing_file(raw_path, images_dir, sounds_dir)
            if not abs_path:
                result.errors.append(f"资源文件不存在: {raw_path}")
                rewritten.append(raw_path)
                continue
            relpath = _register_asset(result, kind, abs_path, used_relpaths)
            if kind == "image":
                rewritten.append(_rewrite_image_value(abs_path, relpath))
            elif kind == "audio":
                rewritten.append(os.path.basename(relpath))
            else:
                rewritten.append(relpath)
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
