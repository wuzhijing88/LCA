from __future__ import annotations

import copy
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from app_core.lca_format.constants import LCA_EXTENSION, USER_ERROR_INVALID
from app_core.lca_format.container import LcaFormatError, seal_lca_bytes, unseal_lca_bytes
from app_core.lca_format.session import LcaPackageSession
from task_workflow.workspace import get_effective_workflow_images_dir
from task_workflow.workflow_sanitize import sanitize_workflow_data

ENTRY_WORKFLOW = "workflows/main.json"
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
}
SUB_WORKFLOW_KEYS = {"workflow_file", "workflow_path", "sub_workflow_path"}
IMAGE_EXTENSIONS = {".bmp", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".wma", ".m4a", ".ogg", ".flac"}
MODEL_EXTENSIONS = {".onnx"}


def is_lca_path(path: object) -> bool:
    return bool(str(path or "").strip()) and Path(str(path)).suffix.lower() == LCA_EXTENSION


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=4).encode("utf-8")


def _workflow_body(workflow_data: Dict[str, Any]) -> Dict[str, Any]:
    nested = workflow_data.get("workflow")
    if isinstance(nested, dict) and "cards" not in workflow_data:
        return nested
    return workflow_data


def _path_values(value: object) -> Sequence[str]:
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    if "\n" in text:
        return [item.strip() for item in text.splitlines() if item.strip()]
    return [text]


def _kind_for_path(raw_path: str, key: str = "") -> str:
    normalized = raw_path.replace("\\", "/").lower()
    extension = Path(normalized).suffix
    if extension in IMAGE_EXTENSIONS or normalized.startswith(("images/", "assets/images/")):
        return "image"
    if extension in AUDIO_EXTENSIONS or normalized.startswith(("sounds/", "assets/sounds/")):
        return "audio"
    if extension in MODEL_EXTENSIONS or normalized.startswith(("yolo/", "assets/models/")):
        return "model"
    lowered_key = key.lower()
    if "sound" in lowered_key or "audio" in lowered_key:
        return "audio"
    if "dict" in lowered_key:
        return "dict"
    if key in PATH_PARAM_KEYS:
        return "image"
    return ""


class _ProjectCollector:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.files: Dict[str, bytes] = {}
        self.file_records = []
        self._used_paths = set()
        self._asset_paths: Dict[Tuple[object, ...], str] = {}
        self._workflow_paths: Dict[Tuple[object, ...], str] = {}
        self._missing = set()

    def collect(self, workflow_data: Mapping[str, Any]) -> Dict[str, Any]:
        copied = copy.deepcopy(dict(workflow_data))
        cleaned = sanitize_workflow_data(copied)
        from utils.app_paths import get_images_dir, get_sounds_dir

        self._collect_workflow(
            cleaned,
            source_dir=self.output_dir,
            source_session=None,
            source_workflow_path=ENTRY_WORKFLOW,
            images_dir=Path(get_images_dir("LCA")),
            sounds_dir=Path(get_sounds_dir("LCA")),
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
    ) -> None:
        local_images_dir = Path(
            get_effective_workflow_images_dir(workflow_data, str(images_dir))
        )
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
            if task_type == "自定义脚本":
                self._collect_script_resources(
                    parameters,
                    source_dir=source_dir,
                    source_session=source_session,
                    images_dir=local_images_dir,
                    sounds_dir=sounds_dir,
                )
            for key, value in list(parameters.items()):
                if key in SUB_WORKFLOW_KEYS and (
                    task_type == "子工作流"
                    or any(str(item).lower().endswith((".json", ".lca")) for item in _path_values(value))
                ):
                    parameters[key] = self._collect_sub_workflow(
                        value,
                        source_dir=source_dir,
                        source_session=source_session,
                        source_workflow_path=source_workflow_path,
                        images_dir=local_images_dir,
                        sounds_dir=sounds_dir,
                    )
                    continue
                kind = _kind_for_path(str(value or ""), key)
                if key not in PATH_PARAM_KEYS and not kind:
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
                        sounds_dir=sounds_dir,
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

    def _collect_script_resources(
        self,
        parameters: Dict[str, Any],
        *,
        source_dir: Optional[Path],
        source_session: Optional[LcaPackageSession],
        images_dir: Path,
        sounds_dir: Path,
    ) -> None:
        from ui.dialogs.script_resources import list_script_resources

        source = str(parameters.get("script_source") or "")
        if not source.strip():
            return
        rewritten = source
        resources = list_script_resources(
            source,
            images_dir=str(images_dir),
            sounds_dir=str(sounds_dir),
        )
        for item in resources:
            raw_path = str(item.get("path") or "").strip()
            if not raw_path:
                continue
            packaged_path = self._collect_asset(
                raw_path,
                key="script_source",
                source_dir=source_dir,
                source_session=source_session,
                images_dir=images_dir,
                sounds_dir=sounds_dir,
            )
            if packaged_path != raw_path:
                rewritten = rewritten.replace(raw_path, packaged_path)
        parameters["script_source"] = rewritten

    def _collect_asset(
        self,
        raw_path: str,
        *,
        key: str,
        source_dir: Optional[Path],
        source_session: Optional[LcaPackageSession],
        images_dir: Path,
        sounds_dir: Path,
    ) -> str:
        kind = _kind_for_path(raw_path, key) or "other"
        package_data = source_session.get_bytes(raw_path) if source_session is not None else None
        if package_data is not None:
            identity = ("session", id(source_session), raw_path.replace("\\", "/").lower())
            source_hint = raw_path
            filename = Path(raw_path.replace("\\", "/")).name
            return self._register_asset(identity, package_data, filename, kind, source_hint)

        resolved = self._resolve_disk_file(
            raw_path,
            source_dir,
            kind,
            images_dir=images_dir,
            sounds_dir=sounds_dir,
        )
        if resolved is None:
            self._missing.add(raw_path)
            return raw_path
        identity = ("disk", os.path.normcase(str(resolved.resolve())))
        return self._register_asset(
            identity,
            resolved.read_bytes(),
            resolved.name,
            kind,
            raw_path,
        )

    def _collect_sub_workflow(
        self,
        value: object,
        *,
        source_dir: Optional[Path],
        source_session: Optional[LcaPackageSession],
        source_workflow_path: str,
        images_dir: Path,
        sounds_dir: Path,
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
            return existing

        logical_path = self._unique_path("workflows/subs", f"{Path(name).stem}.json")
        self._workflow_paths[identity] = logical_path
        nested = sanitize_workflow_data(copy.deepcopy(nested))
        self._collect_workflow(
            nested,
            source_dir=nested_dir,
            source_session=nested_session,
            source_workflow_path=nested_source_path,
            images_dir=images_dir,
            sounds_dir=sounds_dir,
        )
        self.files[logical_path] = _json_bytes(nested)
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
                if payload is None or not candidate.lower().endswith(".json"):
                    continue
                try:
                    nested = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, ValueError, TypeError):
                    return None
                if isinstance(nested, dict):
                    identity = ("session-workflow", id(source_session), candidate.lower())
                    return (
                        nested,
                        None,
                        source_session,
                        identity,
                        Path(candidate).name,
                        candidate,
                    )

        resolved = self._resolve_disk_file(
            raw_path,
            source_dir,
            "workflow",
            images_dir=images_dir,
            sounds_dir=sounds_dir,
        )
        if resolved is None:
            return None
        identity = ("disk-workflow", os.path.normcase(str(resolved.resolve())))
        try:
            if is_lca_path(resolved):
                nested, nested_session = load_lca_project(resolved)
                manifest = json.loads(nested_session.get_bytes("manifest.json"))
                nested_source_path = str(manifest["entry_workflow"])
                return (
                    nested,
                    None,
                    nested_session,
                    identity,
                    resolved.name,
                    nested_source_path,
                )
            nested = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, TypeError, LcaFormatError):
            return None
        if not isinstance(nested, dict):
            return None
        return nested, resolved.parent, None, identity, resolved.name, str(resolved)

    def _resolve_disk_file(
        self,
        raw_path: str,
        source_dir: Optional[Path],
        kind: str,
        *,
        images_dir: Path,
        sounds_dir: Path,
    ) -> Optional[Path]:
        text = str(raw_path or "").strip().strip("\"'")
        if not text or text.startswith("memory://"):
            return None
        path = Path(text).expanduser()
        candidates = [path]
        if source_dir is not None and not path.is_absolute():
            candidates.insert(0, source_dir / path)
        root = sounds_dir if kind == "audio" else images_dir
        candidates.extend((root / path.name, root / path))
        normalized = text.replace("\\", "/")
        if normalized.lower().startswith(("images/", "sounds/")):
            candidates.append(root / normalized.split("/", 1)[1])
        try:
            from utils.image_paths import get_image_path_resolver

            resolved = get_image_path_resolver().resolve(text)
            if resolved and not str(resolved).startswith("memory://"):
                candidates.append(Path(resolved))
        except Exception:
            pass
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        return None

    def _register_asset(
        self,
        identity: Tuple[object, ...],
        data: bytes,
        filename: str,
        kind: str,
        original: str,
    ) -> str:
        existing = self._asset_paths.get(identity)
        if existing is not None:
            return existing
        folder = {
            "image": "assets/images",
            "audio": "assets/sounds",
            "model": "assets/models",
            "dict": "assets/images/dicts",
        }.get(kind, "assets/other")
        logical_path = self._unique_path(folder, filename or "asset")
        self._asset_paths[identity] = logical_path
        self.files[logical_path] = bytes(data)
        self.file_records.append({"path": logical_path, "role": "asset", "original": original})
        return logical_path

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


def save_lca_project(
    path: str | Path,
    workflow_data: dict,
    *,
    display_name: str = "",
) -> Path:
    destination = Path(path)
    collector = _ProjectCollector(destination.parent)
    cleaned = collector.collect(workflow_data)
    collector.files[ENTRY_WORKFLOW] = _json_bytes(cleaned)
    manifest = {
        "schema_version": 1,
        "format": "lca_editor",
        "name": str(display_name or destination.stem),
        "entry_workflow": ENTRY_WORKFLOW,
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


def load_lca_project(path: str | Path) -> tuple[dict, LcaPackageSession]:
    try:
        files = unseal_lca_bytes(Path(path).read_bytes())
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
    except (OSError, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        raise LcaFormatError(USER_ERROR_INVALID) from None
    return workflow_data, LcaPackageSession(files)
