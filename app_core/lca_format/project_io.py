from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from app_core.lca_format.constants import (
    ENTRY_WORKFLOW,
    LCA_EXTENSION,
    SCRIPTS_PAYLOAD_NAME,
    USER_ERROR_INVALID,
)
from app_core.lca_format.container import LcaFormatError, seal_lca_bytes, unseal_lca_bytes
from app_core.lca_format.session import (
    LcaPackageSession,
    clear_path,
    get_active_path,
    get_for_path,
    materialize_package_assets,
    register,
)
from task_workflow.workspace import _resource_param_kind, workflow_resource_dirs
from task_workflow.workflow_sanitize import sanitize_workflow_data

logger = logging.getLogger(__name__)

PATH_PARAM_KEYS = {
    "image_path",
    "image_paths",
    "raw_image_paths",
    "target_image_path",
    "pre_image_path",
    "condition_image_path",
    "drag_start_image_path",
    "drag_end_image_path",
    "template_path",
    "workflow_file",
    "dict_path",
    "dict_file",
    "sound_path",
    "audio_path",
    "audio_file",
    "model_path",
}
SUB_WORKFLOW_KEYS = {"workflow_file"}
IMAGE_EXTENSIONS = {".bmp", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".wma", ".m4a", ".ogg", ".flac"}
MODEL_EXTENSIONS = {".onnx"}


def is_lca_path(path: object) -> bool:
    return bool(str(path or "").strip()) and Path(str(path)).suffix.lower() == LCA_EXTENSION


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=4).encode("utf-8")


def _manifest_payload(display_name: str, extra_records: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    records = list(extra_records or [])
    return {
        "schema_version": 2,
        "format": "lca_editor",
        "name": str(display_name or "子工作流"),
        "entry_workflow": ENTRY_WORKFLOW,
        "scripts_payload": SCRIPTS_PAYLOAD_NAME,
        "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": [{"path": ENTRY_WORKFLOW, "role": "entry"}, *records],
    }


def _workflow_contains_sub_workflow(workflow_data: Mapping[str, Any]) -> bool:
    body = _workflow_body(dict(workflow_data))
    cards = body.get("cards")
    if not isinstance(cards, list):
        return False
    return any(
        isinstance(card, dict) and str(card.get("task_type") or "").strip() == "子工作流"
        for card in cards
    )


def seal_workflow_package(
    workflow_data: Mapping[str, Any],
    *,
    source_session: Optional[LcaPackageSession] = None,
    display_name: str = "",
    source_dir: str = "",
    workflow_filepath: str = "",
) -> bytes:
    if _workflow_contains_sub_workflow(workflow_data):
        raise LcaFormatError("子工作流不允许嵌套")
    source_path = Path(str(source_dir or "").strip() or ".")
    collector = _ProjectCollector(source_path, package_assets=True)
    cleaned = collector.collect(
        dict(workflow_data),
        source_session=source_session,
        workflow_filepath=str(workflow_filepath or source_dir or ""),
    )
    collector.files[ENTRY_WORKFLOW] = _json_bytes(cleaned)
    collector.files["manifest.json"] = _json_bytes(
        _manifest_payload(display_name, collector.file_records)
    )
    return seal_lca_bytes(collector.files)


def _nested_sub_workflow_bytes(workflow_data: Dict[str, Any], display_name: str) -> bytes:
    files = {
        ENTRY_WORKFLOW: _json_bytes(workflow_data),
        "manifest.json": _json_bytes(_manifest_payload(display_name)),
    }
    return seal_lca_bytes(files)


def _workflow_body(workflow_data: Dict[str, Any]) -> Dict[str, Any]:
    nested = workflow_data.get("workflow")
    if isinstance(nested, dict) and "cards" not in workflow_data:
        return nested
    return workflow_data


def _path_values(value: object) -> Sequence[str]:
    from task_workflow.resource_path import format_resource_text, unwrap_resource_path

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
        return [item.strip() for item in text.splitlines() if item.strip()]
    return [text]


def _kind_for_path(raw_path: str, key: str = "") -> str:
    from task_workflow.script_resources import resource_kind

    lowered_key = str(key or "").lower()
    if "dict" in lowered_key:
        return "dict"
    kind = resource_kind(raw_path)
    if kind:
        return kind
    if "sound" in lowered_key or "audio" in lowered_key:
        return "audio"
    if key in PATH_PARAM_KEYS:
        return "image"
    return ""


def _workflow_resource_path(kind: str, packaged_path: str) -> str:
    name = Path(str(packaged_path or "").replace("\\", "/")).name
    if kind == "dict" and name:
        return f"dicts/{name}"
    return packaged_path


class _ProjectCollector:
    def __init__(self, output_dir: Path, *, package_assets: bool = False):
        self.output_dir = output_dir
        self.package_assets = bool(package_assets)
        self.files: Dict[str, bytes] = {}
        self.file_records = []
        self._used_paths = set()
        self._workflow_paths: Dict[Tuple[object, ...], str] = {}
        self._packaged_assets: Dict[Tuple[object, ...], str] = {}
        self._missing = set()

    def collect(
        self,
        workflow_data: Mapping[str, Any],
        *,
        source_session: Optional[LcaPackageSession] = None,
        workflow_filepath: str = "",
    ) -> Dict[str, Any]:
        copied = copy.deepcopy(dict(workflow_data))
        cleaned = sanitize_workflow_data(copied)
        from task_workflow.workspace import resolve_runtime_resource_dirs
        from utils.app_paths import get_app_root, get_images_dir, get_plugin_dir, get_sounds_dir

        app_root = Path(get_app_root())
        resource_dirs = resolve_runtime_resource_dirs(
            cleaned,
            workflow_filepath=workflow_filepath,
            default_images_dir=get_images_dir("LCA"),
        )
        self._collect_workflow(
            cleaned,
            source_dir=self.output_dir,
            source_session=source_session,
            source_workflow_path=ENTRY_WORKFLOW,
            images_dir=Path(str(resource_dirs.get("images_dir") or get_images_dir("LCA"))),
            sounds_dir=Path(str(resource_dirs.get("sounds_dir") or get_sounds_dir("LCA"))),
            yolo_dir=Path(str(resource_dirs.get("yolo_dir") or (app_root / "yolo"))),
            replays_dir=Path(str(resource_dirs.get("replays_dir") or (app_root / "replays"))),
            plugins_dir=Path(str(resource_dirs.get("plugins_dir") or get_plugin_dir())),
            dicts_dir=Path(str(resource_dirs.get("dicts_dir") or "")),
        )
        if self._missing:
            paths = "\n".join(f"- {path}" for path in sorted(self._missing))
            raise LcaFormatError(f"资源或子工作流不存在:\n{paths}")
        return cleaned

    def _collect_workflow(
        self,
        workflow_data: Dict[str, Any],
        *,
        source_dir: Optional[Path],
        source_session: Optional[LcaPackageSession],
        source_workflow_path: str,
        images_dir: Path,
        sounds_dir: Path,
        yolo_dir: Optional[Path] = None,
        replays_dir: Optional[Path] = None,
        plugins_dir: Optional[Path] = None,
        dicts_dir: Optional[Path] = None,
    ) -> None:
        resource_dirs = workflow_resource_dirs(workflow_data, str(images_dir))
        if resource_dirs.get("custom"):
            local_images_dir = Path(str(resource_dirs.get("images_dir") or images_dir))
            local_sounds_dir = Path(str(resource_dirs.get("sounds_dir") or sounds_dir))
            local_yolo_dir = Path(str(resource_dirs.get("yolo_dir") or yolo_dir or ""))
            local_replays_dir = Path(str(resource_dirs.get("replays_dir") or replays_dir or ""))
            local_plugins_dir = Path(str(resource_dirs.get("plugins_dir") or plugins_dir or ""))
            local_dicts_dir = Path(str(resource_dirs.get("dicts_dir") or dicts_dir or ""))
        else:
            local_images_dir = images_dir
            local_sounds_dir = sounds_dir
            local_yolo_dir = Path(str(yolo_dir or ""))
            local_replays_dir = Path(str(replays_dir or ""))
            local_plugins_dir = Path(str(plugins_dir or ""))
            local_dicts_dir = Path(str(dicts_dir or ""))
        cards = _workflow_body(workflow_data).get("cards")
        if not isinstance(cards, list):
            return
        for card in cards:
            if not isinstance(card, dict):
                continue
            parameters = card.get("parameters")
            if not isinstance(parameters, dict):
                continue
            task_type = str(card.get("task_type") or "").strip()
            plugin_file_keys = set()
            if task_type == "脚本卡片":
                plugin_file_keys = self._collect_card_plugin_inputs(
                    parameters, source_session=source_session,
                    images_dir=local_images_dir, sounds_dir=local_sounds_dir,
                    dicts_dir=local_dicts_dir, yolo_dir=local_yolo_dir,
                    replays_dir=local_replays_dir, plugins_dir=local_plugins_dir,
                )
            if task_type == "自定义脚本":
                self._collect_script_resources(
                    parameters,
                    source_dir=source_dir,
                    source_session=source_session,
                    images_dir=local_images_dir,
                    sounds_dir=local_sounds_dir,
                    yolo_dir=local_yolo_dir,
                    replays_dir=local_replays_dir,
                    plugins_dir=local_plugins_dir,
                    dicts_dir=local_dicts_dir,
                )
            for key, value in list(parameters.items()):
                if key in plugin_file_keys:
                    continue
                if key in SUB_WORKFLOW_KEYS and (
                    task_type == "子工作流"
                    or any(str(item).lower().endswith(LCA_EXTENSION) for item in _path_values(value))
                ):
                    parameters[key] = self._collect_sub_workflow(
                        value,
                        source_dir=source_dir,
                        source_session=source_session,
                        source_workflow_path=source_workflow_path,
                        images_dir=local_images_dir,
                        sounds_dir=local_sounds_dir,
                        yolo_dir=local_yolo_dir,
                        replays_dir=local_replays_dir,
                        plugins_dir=local_plugins_dir,
                        dicts_dir=local_dicts_dir,
                    )
                    continue
                if key not in PATH_PARAM_KEYS and not _resource_param_kind(key):
                    continue
                values = _path_values(value)
                if not values:
                    continue
                rewritten = [
                    self._collect_asset(
                        raw_path,
                        key=key,
                        source_dir=source_dir,
                        source_session=source_session,
                        images_dir=local_images_dir,
                        sounds_dir=local_sounds_dir,
                        yolo_dir=local_yolo_dir,
                        replays_dir=local_replays_dir,
                        plugins_dir=local_plugins_dir,
                        dicts_dir=local_dicts_dir,
                    )
                    for raw_path in values
                ]
                if isinstance(value, list):
                    parameters[key] = rewritten
                elif isinstance(value, tuple):
                    parameters[key] = tuple(rewritten)
                elif isinstance(value, str) and "\n" in value:
                    parameters[key] = "\n".join(rewritten)
                else:
                    parameters[key] = rewritten[0]

    def _collect_card_plugin_inputs(self, parameters, *, source_session, **resource_dirs):
        from app_core.card_plugins import bundle_from_parameters, MAX_CONTENT_BYTES, input_parameter_key
        from app_core.card_plugin_conditions import prepare_parameter_storage
        from task_workflow.card_plugin_runtime import read_bound_resource
        from task_workflow.expr import contains_interpolation
        import hashlib

        bundle = bundle_from_parameters(parameters)
        definitions = bundle.manifest["parameters"]
        states = prepare_parameter_storage(definitions, parameters)
        file_keys = set()
        total = 0
        for name, definition in bundle.manifest["parameters"].items():
            if definition["type"] != "file":
                continue
            storage_key = input_parameter_key(name)
            file_keys.add(storage_key)
            if states[name].active is False:
                continue
            value = parameters[storage_key]
            if not isinstance(value, str):
                raise LcaFormatError(f"脚本卡片文件参数必须是文本：{name}")
            if contains_interpolation(value) or not value:
                continue
            kind = definition["resource_kind"]
            data = read_bound_resource(value, kind, {key: str(directory) for key, directory in resource_dirs.items()}, package_session=source_session, limit=MAX_CONTENT_BYTES - total)
            total += len(data)
            package_kind = "audio" if kind == "sound" else kind
            source_key = ("plugin_input", package_kind, hashlib.sha256(data).hexdigest())
            parameters[storage_key] = self._store_packaged_asset(value, package_kind, data, source_key)
        return file_keys

    def _collect_script_resources(
        self,
        parameters: Dict[str, Any],
        *,
        source_dir: Optional[Path],
        source_session: Optional[LcaPackageSession],
        images_dir: Path,
        sounds_dir: Path,
        yolo_dir: Optional[Path] = None,
        replays_dir: Optional[Path] = None,
        plugins_dir: Optional[Path] = None,
        dicts_dir: Optional[Path] = None,
    ) -> None:
        from task_workflow.script_resources import list_script_resources, rewrite_resource_literal
        from tasks.script_task import script_source_hash

        source = str(parameters.get("script_source") or "")
        if not source.strip():
            return
        expected = str(parameters.get("script_source_sha256") or "").strip().casefold()
        if expected and expected != script_source_hash(source):
            # 完整性哈希对不上：脚本可能被篡改。保持源码与哈希原样，
            # 让运行时仍能报出篡改（与导出收集器的拒绝行为一致），不做资源改写。
            logger.warning(
                "自定义脚本源码完整性哈希不匹配，跳过资源改写：脚本保持原样"
            )
            return
        rewritten = source
        resources = list_script_resources(
            source,
            images_dir=str(images_dir),
            sounds_dir=str(sounds_dir),
            yolo_dir=str(yolo_dir or ""),
            replays_dir=str(replays_dir or ""),
            plugins_dir=str(plugins_dir or ""),
            dicts_dir=str(dicts_dir or ""),
        )
        for item in resources:
            raw_path = str(item.get("path") or "").strip()
            if not raw_path:
                continue
            packaged_path = self._collect_asset(
                raw_path,
                key="script_source",
                kind=str(item.get("kind") or ""),
                source_dir=source_dir,
                source_session=source_session,
                images_dir=images_dir,
                sounds_dir=sounds_dir,
                yolo_dir=yolo_dir,
                replays_dir=replays_dir,
                plugins_dir=plugins_dir,
                dicts_dir=dicts_dir,
            )
            if packaged_path != raw_path:
                rewritten = rewrite_resource_literal(rewritten, raw_path, packaged_path)
        parameters["script_source"] = rewritten
        if expected and rewritten != source:
            parameters["script_source_sha256"] = script_source_hash(rewritten)

    @staticmethod
    def _asset_folder(kind: str) -> str:
        return {
            "image": "images",
            "audio": "sounds",
            "model": "yolo",
            "replay": "replays",
            "component": "components",
            "dict": "dicts",
        }.get(str(kind or "").strip(), "misc")

    def _source_session_asset(
        self,
        raw_path: str,
        source_session: Optional[LcaPackageSession],
        kind: str,
    ) -> Optional[Tuple[Tuple[object, ...], str, bytes]]:
        if source_session is None:
            return None
        normalized = str(raw_path or "").replace("\\", "/").strip().lstrip("/")
        if normalized.startswith("memory://"):
            normalized = normalized[len("memory://") :]
        if not normalized:
            return None
        candidates = [normalized]
        from app_core.lca_format.session import _package_alias_paths

        candidates.extend(_package_alias_paths(normalized))
        seen = set()
        for candidate in candidates:
            logical = str(candidate or "").replace("\\", "/").lstrip("/")
            if not logical or logical in seen:
                continue
            seen.add(logical)
            data = source_session.get_bytes(logical)
            if data is not None:
                canonical = logical
                for alias in _package_alias_paths(logical):
                    if alias.startswith("assets/"):
                        canonical = alias
                        break
                return ("session", id(source_session), canonical.casefold()), logical, bytes(data)
        return None

    def _store_packaged_asset(
        self,
        raw_path: str,
        kind: str,
        data: bytes,
        source_key: Tuple[object, ...],
    ) -> str:
        existing = self._packaged_assets.get(source_key)
        if existing is not None:
            return existing
        folder = f"assets/{self._asset_folder(kind)}"
        logical_path = self._unique_path(folder, Path(str(raw_path).replace("\\", "/")).name)
        self.files[logical_path] = bytes(data)
        self.file_records.append(
            {
                "path": logical_path,
                "role": "asset",
                "kind": kind,
                "original": raw_path,
            }
        )
        self._packaged_assets[source_key] = logical_path
        return _workflow_resource_path(kind, logical_path)

    def _collect_asset(
        self,
        raw_path: str,
        *,
        key: str,
        source_dir: Optional[Path],
        source_session: Optional[LcaPackageSession],
        images_dir: Path,
        sounds_dir: Path,
        yolo_dir: Optional[Path] = None,
        replays_dir: Optional[Path] = None,
        plugins_dir: Optional[Path] = None,
        dicts_dir: Optional[Path] = None,
        kind: str = "",
    ) -> str:
        kind = str(kind or "").strip() or _kind_for_path(raw_path, key) or "other"
        from task_workflow.script_resources import is_direct_component_path

        if is_direct_component_path(raw_path, kind):
            return raw_path
        if self.package_assets:
            packaged = self._source_session_asset(raw_path, source_session, kind)
            if packaged is not None:
                source_key, _logical, data = packaged
                return self._store_packaged_asset(raw_path, kind, data, source_key)
        resolved = self._resolve_disk_file(
            raw_path,
            source_dir,
            kind,
            images_dir=images_dir,
            sounds_dir=sounds_dir,
            yolo_dir=yolo_dir,
            replays_dir=replays_dir,
            plugins_dir=plugins_dir,
            dicts_dir=dicts_dir,
        )
        if resolved is not None:
            if self.package_assets:
                source_key = ("disk", os.path.normcase(str(resolved)))
                try:
                    data = resolved.read_bytes()
                except OSError:
                    data = None
                if data is not None:
                    return self._store_packaged_asset(raw_path, kind, data, source_key)
                self._missing.add(raw_path)
                return raw_path
            from task_workflow.script_resources import place_resource_file

            placed = place_resource_file(
                str(resolved),
                kind=kind,
                images_dir=str(images_dir or ""),
                sounds_dir=str(sounds_dir or ""),
                dicts_dir=str(dicts_dir or ""),
                yolo_dir=str(yolo_dir or ""),
                replays_dir=str(replays_dir or ""),
                plugins_dir=str(plugins_dir or ""),
            )
            if placed:
                return placed
            raise LcaFormatError(f"资源导入没有返回有效路径：{raw_path}")

        # 工作区文件不存在时，再从当前工程会话取包内资源。这样保存未
        # 预先落盘的工程时仍能保留资源，同时优先使用用户已经修改过的
        # 工作区文件。
        packaged = self._source_session_asset(raw_path, source_session, kind)
        if packaged is not None:
            source_key, _logical, data = packaged
            return self._store_packaged_asset(raw_path, kind, data, source_key)

        self._missing.add(raw_path)
        return raw_path

    def _collect_sub_workflow(
        self,
        value: object,
        *,
        source_dir: Optional[Path],
        source_session: Optional[LcaPackageSession],
        source_workflow_path: str,
        images_dir: Path,
        sounds_dir: Path,
        yolo_dir: Optional[Path] = None,
        replays_dir: Optional[Path] = None,
        plugins_dir: Optional[Path] = None,
        dicts_dir: Optional[Path] = None,
    ) -> object:
        values = _path_values(value)
        if not values:
            return value
        raw_path = values[0]
        loaded = self._load_sub_workflow(
            raw_path,
            source_dir=source_dir,
            source_session=source_session,
            source_workflow_path=source_workflow_path,
            images_dir=images_dir,
            sounds_dir=sounds_dir,
        )
        if loaded is None:
            self._missing.add(raw_path)
            return value

        nested, nested_dir, nested_session, identity, name, nested_source_path = loaded
        existing = self._workflow_paths.get(identity)
        if existing is not None:
            nested_session.close()
            return existing

        logical_path = self._unique_path(
            "workflows/subs",
            f"{Path(name).stem}{LCA_EXTENSION}",
        )
        self._workflow_paths[identity] = logical_path
        nested_path = Path(nested_dir) if nested_dir is not None else None
        source_dir_text = ""
        nested_filepath = ""
        if nested_path is not None and nested_path.is_file():
            nested_filepath = str(nested_path)
            source_dir_text = str(nested_path.parent)
        elif nested_path is not None:
            source_dir_text = str(nested_path)
        try:
            nested = sanitize_workflow_data(copy.deepcopy(nested))
            if _workflow_contains_sub_workflow(nested):
                raise LcaFormatError("子工作流不允许嵌套")
            self.files[logical_path] = seal_workflow_package(
                nested,
                source_session=nested_session,
                display_name=Path(name).stem,
                source_dir=source_dir_text,
                workflow_filepath=nested_filepath,
            )
        finally:
            nested_session.close()
        self.file_records.append({"path": logical_path, "role": "workflow", "original": raw_path})
        return logical_path

    def _load_sub_workflow(
        self,
        raw_path: str,
        *,
        source_dir: Optional[Path],
        source_session: Optional[LcaPackageSession],
        source_workflow_path: str,
        images_dir: Path,
        sounds_dir: Path,
    ):
        normalized = raw_path.replace("\\", "/").lstrip("/")
        if source_session is not None:
            candidates = [normalized]
            parent = str(Path(source_workflow_path).parent).replace("\\", "/")
            if parent not in {"", "."}:
                candidates.append(f"{parent}/{normalized}")
            for candidate in candidates:
                payload = source_session.get_bytes(candidate)
                if payload is None:
                    continue
                nested, nested_session = load_lca_from_bytes(payload)
                identity = ("session-workflow", id(source_session), candidate.lower())
                manifest_raw = nested_session.get_bytes("manifest.json")
                manifest = json.loads(manifest_raw) if manifest_raw else {}
                nested_source_path = str(manifest.get("entry_workflow") or ENTRY_WORKFLOW)
                return (
                    nested,
                    None,
                    nested_session,
                    identity,
                    Path(candidate).name,
                    nested_source_path,
                )

        resolved = self._resolve_disk_file(
            raw_path,
            source_dir,
            "workflow",
            images_dir=images_dir,
            sounds_dir=sounds_dir,
        )
        if resolved is None or not is_lca_path(resolved):
            return None
        identity = ("disk-workflow", os.path.normcase(str(resolved.resolve())))
        try:
            nested, nested_session = load_lca_project(resolved)
            manifest = json.loads(nested_session.get_bytes("manifest.json"))
            nested_source_path = str(manifest["entry_workflow"])
        except (OSError, UnicodeDecodeError, ValueError, TypeError, LcaFormatError):
            return None
        if not isinstance(nested, dict):
            return None
        return (
            nested,
            resolved,
            nested_session,
            identity,
            resolved.name,
            nested_source_path,
        )

    def _resolve_disk_file(
        self,
        raw_path: str,
        source_dir: Optional[Path],
        kind: str,
        *,
        images_dir: Path,
        sounds_dir: Path,
        yolo_dir: Optional[Path] = None,
        replays_dir: Optional[Path] = None,
        plugins_dir: Optional[Path] = None,
        dicts_dir: Optional[Path] = None,
    ) -> Optional[Path]:
        text = str(raw_path or "").strip().strip("\"'")
        if not text or text.startswith("memory://"):
            return None
        if kind == "workflow":
            path = Path(text)
            if not path.is_absolute():
                if source_dir is None:
                    return None
                path = source_dir / path
            return path.resolve() if path.is_file() else None
        path = Path(text).expanduser()
        if path.is_absolute():
            return path.resolve() if path.is_file() else None
        kind_roots = {
            "image": images_dir,
            "audio": sounds_dir,
            "model": yolo_dir,
            "replay": replays_dir,
            "component": plugins_dir,
            "dict": dicts_dir,
        }
        root = kind_roots.get(kind)
        if root is None:
            return None
        normalized = text.replace("\\", "/")
        folder = "plugins" if kind == "component" else self._asset_folder(kind)
        prefixes = (f"assets/{self._asset_folder(kind)}/", f"{folder}/")
        for prefix in prefixes:
            if normalized.startswith(prefix):
                path = root / normalized[len(prefix):]
                break
        else:
            if "/" not in normalized:
                path = root / normalized
            elif source_dir is not None:
                path = source_dir / normalized
            else:
                return None
        return path.resolve() if path.is_file() else None

    def _unique_path(self, folder: str, filename: str) -> str:
        safe_name = Path(filename).name or "file"
        stem = Path(safe_name).stem
        suffix = Path(safe_name).suffix
        candidate = f"{folder}/{safe_name}"
        index = 2
        while candidate.lower() in self._used_paths:
            candidate = f"{folder}/{stem}_{index}{suffix}"
            index += 1
        self._used_paths.add(candidate.lower())
        return candidate


def ensure_registered_lca_session(path: str | Path) -> Optional[LcaPackageSession]:
    text = str(path or "").strip()
    if not is_lca_path(text):
        return None
    existing = get_for_path(text)
    if existing is not None and existing.matches_source(text):
        return existing
    if existing is not None:
        clear_path(text)
    if not Path(text).is_file():
        return None
    _payload, session = load_lca_project(text)
    session.bind_source(text)
    register(text, session)
    return session


def save_lca_project(
    path: str | Path,
    workflow_data: dict,
    *,
    display_name: str = "",
    source_session: Optional[LcaPackageSession] = None,
) -> Path:
    destination = Path(path)
    collector = _ProjectCollector(destination.parent)
    cleaned = collector.collect(
        workflow_data,
        source_session=source_session if source_session is not None else get_for_path(destination),
        workflow_filepath=str(destination),
    )
    collector.files[ENTRY_WORKFLOW] = _json_bytes(cleaned)
    manifest = {
        "schema_version": 2,
        "format": "lca_editor",
        "name": str(display_name or destination.stem),
        "entry_workflow": ENTRY_WORKFLOW,
        "scripts_payload": SCRIPTS_PAYLOAD_NAME,
        "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": [{"path": ENTRY_WORKFLOW, "role": "entry"}, *collector.file_records],
    }
    collector.files["manifest.json"] = _json_bytes(manifest)
    sealed = seal_lca_bytes(collector.files)

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(sealed)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
    return destination


def load_lca_from_bytes(data: bytes) -> tuple[dict, LcaPackageSession]:
    try:
        files = unseal_lca_bytes(data)
        manifest_data = files.get("manifest.json")
        if manifest_data is None:
            raise ValueError("manifest missing")
        manifest = json.loads(manifest_data.decode("utf-8"))
        if not isinstance(manifest, dict) or manifest.get("format") != "lca_editor":
            raise ValueError("invalid manifest")
        entry = manifest.get("entry_workflow")
        if not isinstance(entry, str) or not entry or entry not in files:
            raise ValueError("entry missing")
        workflow_data = json.loads(files[entry].decode("utf-8"))
        if not isinstance(workflow_data, dict):
            raise ValueError("invalid workflow")
    except LcaFormatError:
        raise
    except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        raise LcaFormatError(USER_ERROR_INVALID) from None
    return workflow_data, LcaPackageSession(files)


def workflow_from_session(session: LcaPackageSession) -> dict:
    """从已注册的工程会话读取入口工作流，避免再次解包磁盘工程。"""
    if not isinstance(session, LcaPackageSession) or session._closed:
        raise LcaFormatError(USER_ERROR_INVALID)
    try:
        manifest_data = session.get_bytes("manifest.json")
        if manifest_data is None:
            raise ValueError("manifest missing")
        manifest = json.loads(manifest_data.decode("utf-8"))
        if not isinstance(manifest, dict) or manifest.get("format") != "lca_editor":
            raise ValueError("invalid manifest")
        entry = manifest.get("entry_workflow")
        if not isinstance(entry, str) or not entry:
            raise ValueError("entry missing")
        workflow_data = session.get_bytes(entry)
        if workflow_data is None:
            raise ValueError("entry missing")
        payload = json.loads(workflow_data.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalid workflow")
        return payload
    except (UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        raise LcaFormatError(USER_ERROR_INVALID) from None


def workflow_from_embedded_bytes(data: bytes) -> dict:
    workflow_data, session = load_lca_from_bytes(data)
    session.close()
    return workflow_data


def _iter_resource_literals(workflow_data: Mapping[str, Any]) -> Sequence[str]:
    body = _workflow_body(dict(workflow_data))
    cards = body.get("cards")
    if not isinstance(cards, list):
        return []
    found: list[str] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        parameters = card.get("parameters")
        if not isinstance(parameters, dict):
            continue
        if str(card.get("task_type") or "").strip() == "自定义脚本":
            source = str(parameters.get("script_source") or "")
            if source.strip():
                from task_workflow.script_resources import list_script_resources

                for item in list_script_resources(source):
                    text = str(item.get("path") or "").strip()
                    if text:
                        found.append(text)
        for key, value in parameters.items():
            if key not in PATH_PARAM_KEYS and not _resource_param_kind(key):
                continue
            found.extend(_path_values(value))
    return found


def inline_nested_workflow_assets(files: Mapping[str, bytes]) -> Mapping[str, bytes]:
    from app_core.lca_format.session import _package_alias_paths

    updated = {
        str(path or "").replace("\\", "/").lstrip("/"): bytes(data)
        for path, data in files.items()
        if str(path or "").strip()
    }
    changed = False
    for path, data in list(updated.items()):
        if not path.lower().endswith(LCA_EXTENSION) or not path.startswith("workflows/"):
            continue
        nested_data, nested_session = load_lca_from_bytes(data)
        try:
            nested_files = dict(nested_session.snapshot_files())
            nested_changed = False
            for literal in _iter_resource_literals(nested_data):
                logical = str(literal or "").replace("\\", "/").lstrip("/")
                if logical.startswith("memory://"):
                    logical = logical[len("memory://") :]
                if not logical or nested_session.get_bytes(logical) is not None:
                    continue
                parent_key = ""
                parent_data = None
                candidates = [logical, *_package_alias_paths(logical)]
                for candidate in candidates:
                    if candidate in updated and candidate != path:
                        parent_key = candidate
                        parent_data = updated[candidate]
                        break
                if parent_data is None or not parent_key:
                    continue
                nested_files[parent_key] = parent_data
                nested_changed = True
            if not nested_changed:
                continue
            updated[path] = seal_lca_bytes(nested_files)
            changed = True
        finally:
            nested_session.close()
    if not changed:
        return files
    return updated


def write_nested_workflow(
    host_path: str | Path,
    logical_path: str,
    workflow_data: Mapping[str, Any],
    *,
    source_session: Optional[LcaPackageSession] = None,
    display_name: str = "",
    source_dir: str | Path = "",
    workflow_filepath: str = "",
) -> None:
    host = Path(host_path)
    logical = str(logical_path or "").replace("\\", "/").lstrip("/")
    if logical.startswith("memory://"):
        logical = logical[len("memory://") :]
    if not logical:
        raise LcaFormatError("子工作流路径无效")
    nested_bytes = seal_workflow_package(
        workflow_data,
        source_session=source_session,
        display_name=display_name or Path(logical).stem,
        source_dir=str(source_dir or ""),
        workflow_filepath=str(workflow_filepath or ""),
    )
    files = unseal_lca_bytes(host.read_bytes())
    if logical not in files:
        raise LcaFormatError(f"父工程中不存在子工作流: {logical}")
    files[logical] = nested_bytes
    sealed = seal_lca_bytes(files)
    host.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=host.parent,
            prefix=f".{host.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(sealed)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, host)
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
    payload, session = load_lca_from_bytes(sealed)
    try:
        session.bind_source(host)
        _materialize_loaded_project(host, payload, session)
    except BaseException:
        session.close()
        raise
    from app_core.lca_format.session import activate, get_active_path

    previous = get_active_path()
    register(host, session)
    if previous and os.path.normcase(os.path.abspath(previous)) == os.path.normcase(
        os.path.abspath(str(host))
    ):
        activate(host)


def _materialize_loaded_project(
    path: str | Path,
    workflow_data: dict,
    session: LcaPackageSession,
) -> None:
    from task_workflow.workspace import extract_workflow_resource_path
    from app_core.lca_format.sub_workflow_project import materialize_sub_workflow_projects

    materialize_sub_workflow_projects(path, workflow_data, session)

    root = extract_workflow_resource_path(workflow_data)
    if not root:
        root = str(Path(path).resolve().parent)
        metadata = workflow_data.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            workflow_data["metadata"] = metadata
        metadata["custom_resource_path"] = root
    materialized = materialize_package_assets(
        session,
        root,
        logical_paths=_iter_resource_literals(workflow_data),
    )
    if materialized:
        logger.info("工程资源按引用落盘完成: %s 个文件", materialized)
    else:
        logger.debug("工程资源按引用落盘完成: 0 个文件")


def load_lca_project(path: str | Path) -> tuple[dict, LcaPackageSession]:
    try:
        from app_core.lca_format.legacy_convert import convert_project_file

        converted = convert_project_file(path)
        workflow_data, session = load_lca_from_bytes(converted.read_bytes())
        try:
            session.bind_source(converted)
            _materialize_loaded_project(converted, workflow_data, session)
        except BaseException:
            session.close()
            raise
        return workflow_data, session
    except LcaFormatError:
        raise
    except OSError:
        raise LcaFormatError(USER_ERROR_INVALID) from None
