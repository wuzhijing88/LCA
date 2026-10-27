"""把旧工程转换成现行 LCA 包：外层 zip，只加密脚本，YOLO 等资源不加密。

现行打开路径只认转换后的格式。本模块读取：
- 旧 JSON 工作流
- 旧整包加密 LCA1
- 中间明文 zip 工程
并写成现行包。封装与卡片参数分别检查；现行封装中的旧参数也必须迁移。
"""

from __future__ import annotations

import copy
import io
import json
import math
import re
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Mapping, Optional

from app_core.lca_format.constants import (
    ENTRY_WORKFLOW,
    LCA_EXTENSION,
    LCA_MAGIC,
    SCRIPTS_PAYLOAD_NAME,
    USER_ERROR_CONVERT,
    USER_ERROR_INVALID,
)
from app_core.lca_format.container import (
    ZIP_MAGIC,
    LcaFormatError,
    _unseal_lca1_blob,
    _zip_bytes_to_files,
    seal_lca_bytes,
    unseal_lca_bytes,
)
from task_workflow.workflow_sanitize import (
    DEAD_CARD_PARAM_KEYS,
    DEAD_WORKFLOW_KEYS,
    YOLO_REMOVED_ACTION_PARAM_KEYS,
    YOLO_TASK_TYPE,
    sanitize_workflow_data,
)

KIND_CURRENT = "current"
KIND_LEGACY_LCA1 = "legacy_lca1"
KIND_PLAIN_ZIP = "plain_zip"
KIND_JSON = "json"


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=4).encode("utf-8")


def _is_workflow_payload(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    if isinstance(data.get("cards"), list):
        return True
    nested = data.get("workflow")
    return isinstance(nested, dict) and isinstance(nested.get("cards"), list)


def _parse_json_bytes(blob: bytes) -> Optional[dict]:
    text = blob.decode("utf-8-sig")
    payload = json.loads(text)
    if _is_workflow_payload(payload):
        return payload
    return None


def _zip_member_names(blob: bytes) -> Optional[set[str]]:
    try:
        with zipfile.ZipFile(io.BytesIO(blob), "r") as archive:
            names = set()
            for member in archive.infolist():
                if member.is_dir():
                    continue
                name = str(member.filename or "").replace("\\", "/").lstrip("/")
                if name:
                    names.add(name)
            return names
    except zipfile.BadZipFile:
        return None


def inspect_project_bytes(blob: bytes) -> str:
    if blob.startswith(LCA_MAGIC):
        return KIND_LEGACY_LCA1
    if blob.startswith(ZIP_MAGIC):
        names = _zip_member_names(blob)
        if names is None:
            raise LcaFormatError(USER_ERROR_CONVERT)
        if SCRIPTS_PAYLOAD_NAME in names and "manifest.json" in names:
            return KIND_CURRENT
        if "manifest.json" in names or ENTRY_WORKFLOW in names:
            return KIND_PLAIN_ZIP
        raise LcaFormatError(USER_ERROR_CONVERT)
    try:
        if _parse_json_bytes(blob) is not None:
            return KIND_JSON
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        pass
    raise LcaFormatError(USER_ERROR_CONVERT)


def _manifest_bytes(display_name: str) -> bytes:
    from datetime import datetime, timezone

    return _json_bytes(
        {
            "schema_version": 2,
            "format": "lca_editor",
            "name": str(display_name or "工作流"),
            "entry_workflow": ENTRY_WORKFLOW,
            "scripts_payload": SCRIPTS_PAYLOAD_NAME,
            "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "files": [{"path": ENTRY_WORKFLOW, "role": "entry"}],
        }
    )


def _legacy_coordinate_pair(value: object) -> tuple[int, int]:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("{", "[")):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                raise LcaFormatError("旧坐标无法转换：坐标 JSON 格式无效") from None
        else:
            value = re.split(r"[,，\s]+", text)
    if isinstance(value, dict):
        for x_key, y_key in (("x", "y"), ("X", "Y"), ("坐标X", "坐标Y")):
            if x_key in value and y_key in value:
                value = [value[x_key], value[y_key]]
                break
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise LcaFormatError("旧坐标无法转换：需要明确的 X、Y 坐标")
    coordinates = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            raise LcaFormatError("旧坐标无法转换：坐标必须是有限数值")
        if isinstance(item, int):
            coordinates.append(item)
            continue
        if isinstance(item, str) and not re.fullmatch(
            r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", item.strip()
        ):
            raise LcaFormatError("旧坐标无法转换：坐标必须是有限数值")
        try:
            number = float(item)
        except (ValueError, OverflowError):
            raise LcaFormatError("旧坐标无法转换：坐标必须是有限数值") from None
        if not math.isfinite(number):
            raise LcaFormatError("旧坐标无法转换：坐标必须是有限数值")
        coordinates.append(int(number))
    return coordinates[0], coordinates[1]


def _convert_mouse_parameters(parameters: dict) -> None:
    for key in ("test_image_recognition", "test_color_recognition", "enable_parallel_recognition"):
        parameters.pop(key, None)
    source_mode = parameters.get("coordinate_source_mode")
    had_value = "coordinate_value" in parameters
    value = parameters.pop("coordinate_value", None)
    if parameters.get("operation_mode", "坐标点击") != "坐标点击":
        return
    if source_mode == "无坐标":
        return
    has_x = "coordinate_x" in parameters
    has_y = "coordinate_y" in parameters
    if had_value and source_mode is None and has_x and has_y:
        parameters["coordinate_source_mode"] = "坐标工具获取坐标"
        return
    if source_mode not in (None, "坐标工具获取坐标", "手动输入", "无坐标", "通过变量"):
        if had_value:
            raise LcaFormatError("旧坐标无法转换：坐标来源未知")
        return
    if source_mode != "通过变量" and has_x and has_y:
        return
    if source_mode == "通过变量" or (had_value and value not in (None, "")):
        if source_mode != "通过变量" and has_x != has_y:
            raise LcaFormatError("旧坐标无法转换：现行 X、Y 坐标不完整")
        x, y = _legacy_coordinate_pair(value)
        parameters.update(coordinate_x=x, coordinate_y=y, coordinate_source_mode="手动输入")


def _convert_workflow_payload(payload: Mapping[str, object]) -> dict:
    cleaned = copy.deepcopy(dict(payload))

    def convert_body(workflow: dict) -> None:
        for key in DEAD_WORKFLOW_KEYS:
            workflow.pop(key, None)
        nested = workflow.get("workflow")
        if isinstance(nested, dict):
            convert_body(nested)
        cards = workflow.get("cards")
        if not isinstance(cards, list):
            return
        for card in cards:
            if not isinstance(card, dict):
                continue
            parameters = card.get("parameters")
            if parameters is None:
                parameters = {}
                card["parameters"] = parameters
            if not isinstance(parameters, dict):
                raise LcaFormatError("旧卡片参数无法转换：参数必须是对象")
            task_type = card.get("task_type")
            if task_type == "模拟鼠标操作":
                try:
                    _convert_mouse_parameters(parameters)
                except LcaFormatError as exc:
                    raise LcaFormatError(f"卡片 {card.get('id')}（{task_type}）：{exc}") from None
            for key in DEAD_CARD_PARAM_KEYS:
                parameters.pop(key, None)
            if task_type == YOLO_TASK_TYPE:
                for key in YOLO_REMOVED_ACTION_PARAM_KEYS:
                    parameters.pop(key, None)

    convert_body(cleaned)
    try:
        return sanitize_workflow_data(cleaned)
    except ValueError as exc:
        raise LcaFormatError(f"旧卡片参数无法转换：{exc}") from None


def _convert_workflow_member(files: Mapping[str, bytes]) -> Dict[str, bytes]:
    converted = dict(files)
    try:
        manifest = json.loads(files["manifest.json"].decode("utf-8"))
        if not isinstance(manifest, dict) or manifest.get("format") != "lca_editor":
            raise ValueError
        entry = manifest["entry_workflow"]
        if not isinstance(entry, str) or not entry:
            raise ValueError
        workflow = json.loads(files[entry].decode("utf-8-sig"))
        if not _is_workflow_payload(workflow):
            raise ValueError
    except (KeyError, UnicodeDecodeError, ValueError, TypeError):
        raise LcaFormatError("旧工程无法转换：工程清单或入口工作流无效") from None
    cleaned = _convert_workflow_payload(workflow)
    if cleaned != workflow:
        converted[entry] = _json_bytes(cleaned)
    return converted


def convert_json_payload(payload: Mapping[str, object], *, display_name: str = "") -> bytes:
    cleaned = _convert_workflow_payload(payload)
    files = {
        ENTRY_WORKFLOW: _json_bytes(cleaned),
        "manifest.json": _manifest_bytes(display_name),
    }
    return seal_lca_bytes(files)


def _convert_nested_members(files: Mapping[str, bytes]) -> Dict[str, bytes]:
    converted: Dict[str, bytes] = {}
    for path, data in files.items():
        if _normalize_is_lca(path):
            converted[path] = convert_project_bytes(data)
        else:
            converted[path] = data
    return converted


def _normalize_is_lca(path: object) -> bool:
    return _normalize_member(path).lower().endswith(LCA_EXTENSION)


def _normalize_member(path: object) -> str:
    return str(path or "").replace("\\", "/").lstrip("/")


_DICT_SCRIPT_CALLS = ("找字库", "点字库", "等字库", "等字库消失")
_DICT_FILE_SUFFIXES = {".txt", ".dict"}


def _workflow_cards(workflow: Mapping[str, object]) -> list:
    cards = workflow.get("cards")
    if isinstance(cards, list):
        return cards
    nested = workflow.get("workflow")
    if isinstance(nested, dict):
        nested_cards = nested.get("cards")
        if isinstance(nested_cards, list):
            return nested_cards
    return []


def _iter_dict_literals(workflow: Mapping[str, object]) -> list[str]:
    from task_workflow.script_resources import enclosing_call_name, extract_string_literals

    refs: list[str] = []
    for card in _workflow_cards(workflow):
        if not isinstance(card, dict):
            continue
        parameters = card.get("parameters")
        if not isinstance(parameters, dict):
            continue
        for key in ("dict_file", "dict_path"):
            value = parameters.get(key)
            if isinstance(value, str) and value.strip():
                refs.append(value.strip())
        source = str(parameters.get("script_source") or "")
        for literal, start, _end in extract_string_literals(source):
            if enclosing_call_name(source, start) in _DICT_SCRIPT_CALLS and literal.strip():
                refs.append(literal.strip())
    return refs


def _rewrite_dict_literals(workflow: dict, mapping: Mapping[str, str]) -> bool:
    from task_workflow.script_resources import rewrite_resource_literal

    changed = False
    for card in _workflow_cards(workflow):
        if not isinstance(card, dict):
            continue
        parameters = card.get("parameters")
        if not isinstance(parameters, dict):
            continue
        for key in ("dict_file", "dict_path"):
            value = parameters.get(key)
            if not isinstance(value, str):
                continue
            replacement = mapping.get(value.strip().replace("\\", "/").lstrip("/"))
            if replacement and replacement != value:
                parameters[key] = replacement
                changed = True
        source = str(parameters.get("script_source") or "")
        rewritten = source
        for old, new in mapping.items():
            rewritten = rewrite_resource_literal(rewritten, old, new)
        if rewritten != source:
            from tasks.script_task import script_source_hash

            parameters["script_source"] = rewritten
            if parameters.get("script_source_sha256"):
                parameters["script_source_sha256"] = script_source_hash(rewritten)
            changed = True
    return changed


def _relocate_dict_assets(files: Mapping[str, bytes]) -> Dict[str, bytes]:
    result = {
        _normalize_member(path): bytes(data)
        for path, data in files.items()
        if _normalize_member(path)
    }
    original = dict(result)
    path_map: Dict[str, str] = {}

    def take(name: str) -> str:
        return f"assets/dicts/{name}"

    for path, data in list(result.items()):
        rest = ""
        if path.startswith("assets/images/dicts/"):
            rest = path[len("assets/images/dicts/") :]
        elif path.startswith("images/dicts/"):
            rest = path[len("images/dicts/") :]
        if not rest:
            continue
        destination = take(rest)
        if destination not in result:
            result[destination] = data
        if path != destination:
            del result[path]
        path_map[path] = f"dicts/{rest}"
        path_map[f"dicts/{rest}"] = f"dicts/{rest}"
        path_map[f"assets/dicts/{rest}"] = f"dicts/{rest}"

    workflow_raw = result.get(ENTRY_WORKFLOW)
    if workflow_raw:
        try:
            workflow = json.loads(workflow_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            workflow = None
        if isinstance(workflow, dict):
            for ref in _iter_dict_literals(workflow):
                logical = ref.replace("\\", "/").lstrip("/")
                name = Path(logical).name
                if not name or Path(name).suffix.lower() not in _DICT_FILE_SUFFIXES:
                    continue
                source = ""
                payload = None
                for candidate in (
                    logical,
                    f"assets/dicts/{name}",
                    f"dicts/{name}",
                    f"assets/images/dicts/{name}",
                    f"images/dicts/{name}",
                    f"assets/images/{name}",
                    f"images/{name}",
                    name,
                ):
                    if candidate in result:
                        source = candidate
                        payload = result[candidate]
                        break
                if payload is None:
                    continue
                destination = take(name)
                if source != destination:
                    if destination not in result:
                        result[destination] = payload
                    image_like = source.startswith("assets/images/") and "/dicts/" not in f"/{source}"
                    nested_old = source.startswith(("assets/images/dicts/", "images/dicts/"))
                    if image_like or nested_old:
                        del result[source]
                path_map[ref] = f"dicts/{name}"
                path_map[logical] = f"dicts/{name}"
            if _rewrite_dict_literals(workflow, path_map):
                result[ENTRY_WORKFLOW] = _json_bytes(workflow)

    if result == original:
        return dict(files)
    return result


def convert_project_bytes(blob: bytes, *, display_name: str = "") -> bytes:
    kind = inspect_project_bytes(blob)
    if kind == KIND_JSON:
        payload = _parse_json_bytes(blob)
        if payload is None:
            raise LcaFormatError(USER_ERROR_CONVERT)
        return convert_json_payload(payload, display_name=display_name)
    if kind == KIND_CURRENT:
        files = unseal_lca_bytes(blob)
    elif kind == KIND_LEGACY_LCA1:
        files = _unseal_lca1_blob(blob)
    else:
        files = _zip_bytes_to_files(blob)
    converted = _convert_workflow_member(_convert_nested_members(files))
    from app_core.lca_format.project_io import inline_nested_workflow_assets

    converted = inline_nested_workflow_assets(converted)
    relocated = _relocate_dict_assets(converted)
    if kind == KIND_CURRENT and relocated == files:
        return blob
    return seal_lca_bytes(relocated)


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def convert_project_file(path: str | Path) -> Path:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"工作流文件不存在: {source}")
    blob = source.read_bytes()
    converted = convert_project_bytes(blob, display_name=source.stem)
    if converted == blob:
        return source
    suffix = source.suffix.lower()
    if suffix == LCA_EXTENSION:
        _write_bytes(source, converted)
        return source
    if suffix == ".json":
        destination = source.with_suffix(LCA_EXTENSION)
        _write_bytes(destination, converted)
        if source.resolve() != destination.resolve():
            source.unlink()
        return destination
    raise LcaFormatError(USER_ERROR_INVALID)
