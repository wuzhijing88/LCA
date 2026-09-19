"""Parse and apply AI workflow corrections to the active editor."""

from __future__ import annotations

import copy
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from task_workflow.thread_window_binding import is_valid_thread_window_limit_connection

LINE_TYPES = frozenset({"sequential", "success", "failure", "random"})
_NO_INPUT_TASK_TYPES = frozenset({"附加条件", "线程窗口限制"})
_RANDOM_ONLY_TASK_TYPES = frozenset({"随机跳转"})
_SEQUENTIAL_ONLY_TASK_TYPES = frozenset(
    {
        "延迟",
        "模拟键盘操作",
        "线程起点",
        "附加条件",
        "线程窗口限制",
    }
)
_ADD_CARD_REQUIRED = {"op", "id", "task_type", "pos_x", "pos_y", "parameters"}
_ADD_CARD_OPTIONAL = frozenset({"custom_name"})
_OP_REQUIRED = {
    "set_parameters": {"op", "id", "parameters"},
    "set_custom_name": {"op", "id", "custom_name"},
    "add_card": _ADD_CARD_REQUIRED,
    "remove_card": {"op", "id"},
    "add_connection": {"op", "start_card_id", "end_card_id", "type"},
    "remove_connection": {"op", "start_card_id", "end_card_id", "type"},
}


def _require_mapping(value: Any, message: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or isinstance(value, (str, bytes)):
        raise ValueError(message)
    return value


def _require_non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} 必须是非负整数")
    return value


def _require_finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field_name} 必须是有限数字")
    return float(value)


def _require_line_type(value: Any) -> str:
    line_type = str(value or "").strip()
    if line_type not in LINE_TYPES:
        raise ValueError(f"连线类型无效: {value!r}")
    return line_type


def _connection_rule_error(
    start_id: int,
    start_type: str,
    end_id: int,
    end_type: str,
    line_type: str,
) -> Optional[str]:
    if start_id == end_id:
        return f"卡片 {start_id} 不能连接到自己"
    if end_type in _NO_INPUT_TASK_TYPES:
        return f"卡片 {end_id} 没有输入端口"
    restricted = start_type in _SEQUENTIAL_ONLY_TASK_TYPES or start_type in _RANDOM_ONLY_TASK_TYPES
    if line_type in {"success", "failure"} and restricted:
        return f"卡片 {start_id} 的 {line_type} 输出端口不可用"
    if line_type == "random" and start_type not in _RANDOM_ONLY_TASK_TYPES:
        return f"卡片 {start_id} 没有随机输出端口"
    if not is_valid_thread_window_limit_connection(start_type, end_type, line_type):
        return "线程窗口限制只能用顺序连线连接到线程起点"
    return None


def _require_exact_keys(item: Mapping[str, Any], required: Set[str], *, extra: Set[str] = frozenset()) -> None:
    keys = set(item)
    missing = required - keys
    if missing:
        raise ValueError(f"操作缺少字段: {sorted(missing)}")
    unknown = keys - required - extra
    if unknown:
        raise ValueError(f"操作含有未知字段: {sorted(unknown)}")


def parse_workflow_proposal(text: str) -> List[Dict[str, Any]]:
    """Parse a ```工作流 JSON block into a non-empty ops list."""
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("工作流代码块为空")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"工作流代码块不是有效 JSON：{exc.msg}") from exc
    payload = _require_mapping(data, "工作流代码块必须是 JSON 对象")
    unknown = set(payload) - {"ops"}
    if unknown:
        raise ValueError(f"工作流代码块含有未知字段: {sorted(unknown)}")
    ops = payload.get("ops")
    if not isinstance(ops, list) or not ops:
        raise ValueError("工作流代码块必须包含非空的 ops 列表")
    parsed: List[Dict[str, Any]] = []
    for index, item in enumerate(ops, start=1):
        try:
            parsed.append(_parse_op(item))
        except ValueError as exc:
            raise ValueError(f"第 {index} 项操作无效：{exc}") from exc
    return parsed


def _parse_op(item: Any) -> Dict[str, Any]:
    mapping = _require_mapping(item, "操作必须是 JSON 对象")
    op_name = str(mapping.get("op") or "").strip()
    required = _OP_REQUIRED.get(op_name)
    if required is None:
        raise ValueError(f"未知操作: {mapping.get('op')!r}")
    extra = _ADD_CARD_OPTIONAL if op_name == "add_card" else frozenset()
    _require_exact_keys(mapping, required, extra=extra)
    parsed: Dict[str, Any] = {"op": op_name}
    if op_name in {"set_parameters", "set_custom_name", "add_card", "remove_card"}:
        parsed["id"] = _require_non_negative_int(mapping.get("id"), "id")
    if op_name == "set_parameters":
        parameters = mapping.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError("parameters 必须是对象")
        parsed["parameters"] = copy.deepcopy(parameters)
        return parsed
    if op_name == "set_custom_name":
        custom_name = mapping.get("custom_name")
        if custom_name is not None and not isinstance(custom_name, str):
            raise ValueError("custom_name 必须是字符串或 null")
        parsed["custom_name"] = custom_name
        return parsed
    if op_name == "add_card":
        task_type = str(mapping.get("task_type") or "").strip()
        if not task_type:
            raise ValueError("task_type 必须是非空字符串")
        parameters = mapping.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError("parameters 必须是对象")
        parsed["task_type"] = task_type
        parsed["pos_x"] = _require_finite_number(mapping.get("pos_x"), "pos_x")
        parsed["pos_y"] = _require_finite_number(mapping.get("pos_y"), "pos_y")
        parsed["parameters"] = copy.deepcopy(parameters)
        if "custom_name" in mapping:
            custom_name = mapping.get("custom_name")
            if custom_name is not None and not isinstance(custom_name, str):
                raise ValueError("custom_name 必须是字符串或 null")
            parsed["custom_name"] = custom_name
        return parsed
    if op_name == "remove_card":
        return parsed
    parsed["start_card_id"] = _require_non_negative_int(mapping.get("start_card_id"), "start_card_id")
    parsed["end_card_id"] = _require_non_negative_int(mapping.get("end_card_id"), "end_card_id")
    parsed["type"] = _require_line_type(mapping.get("type"))
    return parsed


def _card_index(cards: Sequence[Mapping[str, Any]]) -> Dict[int, Dict[str, Any]]:
    indexed: Dict[int, Dict[str, Any]] = {}
    for card in cards:
        if not isinstance(card, dict):
            raise ValueError("存在无效卡片")
        card_id = _require_non_negative_int(card.get("id"), "卡片 id")
        if card_id in indexed:
            raise ValueError(f"工作流存在重复卡片 ID: {card_id}")
        indexed[card_id] = card
    return indexed


def _connection_key(item: Mapping[str, Any]) -> Tuple[int, int, str]:
    return (
        _require_non_negative_int(item.get("start_card_id"), "start_card_id"),
        _require_non_negative_int(item.get("end_card_id"), "end_card_id"),
        _require_line_type(item.get("type")),
    )


def _connection_index(connections: Sequence[Mapping[str, Any]]) -> Dict[Tuple[int, int, str], Dict[str, Any]]:
    indexed: Dict[Tuple[int, int, str], Dict[str, Any]] = {}
    for item in connections:
        if not isinstance(item, dict):
            raise ValueError("存在无效连线")
        key = _connection_key(item)
        if key in indexed:
            raise ValueError(f"工作流存在重复连线: {key[0]} -> {key[1]} ({key[2]})")
        indexed[key] = item
    return indexed


def _require_card(cards: Mapping[int, Dict[str, Any]], card_id: int) -> Dict[str, Any]:
    card = cards.get(card_id)
    if card is None:
        raise ValueError(f"卡片不存在: {card_id}")
    return card


def build_workflow_from_proposal(
    proposal_text: str,
    source_workflow: Mapping[str, Any],
    *,
    known_task_types: Iterable[str],
) -> Dict[str, Any]:
    """Apply a ```工作流 ops block to a source dict. Does not write the editor or disk."""
    ops = parse_workflow_proposal(proposal_text)
    if not isinstance(source_workflow, Mapping) or isinstance(source_workflow, (str, bytes)):
        raise ValueError("工作流数据不是字典")
    base = copy.deepcopy(dict(source_workflow))
    if not isinstance(base.get("cards"), list):
        base["cards"] = []
    if not isinstance(base.get("connections"), list):
        base["connections"] = []
    return apply_workflow_ops(base, ops, known_task_types=known_task_types)


def write_workflow_lca(
    path: str | Path,
    workflow: Mapping[str, Any],
    *,
    display_name: str = "",
) -> Path:
    """Write a current-format .lca. Does not convert or replace the original file."""
    from app_core.lca_format.constants import LCA_EXTENSION
    from app_core.lca_format.legacy_convert import convert_json_payload

    if not isinstance(workflow, Mapping) or isinstance(workflow, (str, bytes)):
        raise ValueError("工作流数据不是字典")
    destination = Path(path)
    if not str(destination).strip():
        raise ValueError("保存路径无效")
    if destination.suffix.lower() != LCA_EXTENSION:
        destination = destination.with_suffix(LCA_EXTENSION)
    blob = convert_json_payload(dict(workflow), display_name=str(display_name or destination.stem))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(destination.parent),
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(blob)
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


def apply_workflow_ops(
    workflow: Mapping[str, Any],
    ops: Sequence[Mapping[str, Any]],
    *,
    known_task_types: Iterable[str],
) -> Dict[str, Any]:
    """Return a new workflow dict after applying ops. Current canvas is not mutated."""
    source = _require_mapping(workflow, "当前工作流数据必须是字典")
    cards_raw = source.get("cards")
    connections_raw = source.get("connections")
    if not isinstance(cards_raw, list):
        raise ValueError("当前工作流 cards 必须是列表")
    if not isinstance(connections_raw, list):
        raise ValueError("当前工作流 connections 必须是列表")
    if not ops:
        raise ValueError("没有可应用的操作")
    known = {str(item).strip() for item in known_task_types if str(item).strip()}
    if not known:
        raise ValueError("当前编辑器没有现行卡片目录")

    cards = _card_index(copy.deepcopy(list(cards_raw)))
    connections = _connection_index(copy.deepcopy(list(connections_raw)))
    for item in ops:
        _apply_one_op(item, cards, connections, known)

    result = copy.deepcopy(dict(source))
    result["cards"] = [cards[card_id] for card_id in sorted(cards)]
    result["connections"] = [
        connections[key]
        for key in sorted(connections, key=lambda item: (item[0], item[1], item[2]))
    ]
    _validate_result_workflow(result, known)
    return result


def _apply_one_op(
    item: Mapping[str, Any],
    cards: Dict[int, Dict[str, Any]],
    connections: Dict[Tuple[int, int, str], Dict[str, Any]],
    known: Set[str],
) -> None:
    op_name = str(item.get("op") or "")
    if op_name == "set_parameters":
        card = _require_card(cards, int(item["id"]))
        parameters = card.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError(f"卡片 {item['id']} 的 parameters 必须是对象")
        parameters.update(copy.deepcopy(item["parameters"]))
        return
    if op_name == "set_custom_name":
        card = _require_card(cards, int(item["id"]))
        card["custom_name"] = item.get("custom_name")
        return
    if op_name == "add_card":
        card_id = int(item["id"])
        if card_id in cards:
            raise ValueError(f"卡片 ID 已存在: {card_id}")
        task_type = str(item["task_type"])
        if task_type not in known:
            raise ValueError(f"卡片 {card_id} 的类型不是现行卡片: {task_type}")
        card = {
            "id": card_id,
            "task_type": task_type,
            "pos_x": item["pos_x"],
            "pos_y": item["pos_y"],
            "parameters": copy.deepcopy(item["parameters"]),
            "custom_name": item.get("custom_name"),
        }
        cards[card_id] = card
        return
    if op_name == "remove_card":
        card_id = int(item["id"])
        _require_card(cards, card_id)
        del cards[card_id]
        for key in [key for key in connections if card_id in (key[0], key[1])]:
            del connections[key]
        return
    if op_name == "add_connection":
        key = (int(item["start_card_id"]), int(item["end_card_id"]), str(item["type"]))
        start_card = _require_card(cards, key[0])
        end_card = _require_card(cards, key[1])
        rule_error = _connection_rule_error(
            key[0],
            str(start_card.get("task_type") or "").strip(),
            key[1],
            str(end_card.get("task_type") or "").strip(),
            key[2],
        )
        if rule_error:
            raise ValueError(rule_error)
        if key in connections:
            raise ValueError(f"连线已存在: {key[0]} -> {key[1]} ({key[2]})")
        connections[key] = {
            "start_card_id": key[0],
            "end_card_id": key[1],
            "type": key[2],
        }
        return
    if op_name == "remove_connection":
        key = (int(item["start_card_id"]), int(item["end_card_id"]), str(item["type"]))
        if key not in connections:
            raise ValueError(f"连线不存在: {key[0]} -> {key[1]} ({key[2]})")
        del connections[key]
        return
    raise ValueError(f"未知操作: {op_name!r}")


def _validate_result_workflow(workflow: Mapping[str, Any], known: Set[str]) -> None:
    cards = workflow.get("cards")
    connections = workflow.get("connections")
    if not isinstance(cards, list) or not isinstance(connections, list):
        raise ValueError("修正后的工作流缺少 cards 或 connections")
    indexed = _card_index(cards)
    for card in indexed.values():
        task_type = str(card.get("task_type") or "").strip()
        if not task_type:
            raise ValueError(f"卡片 {card.get('id')} 的 task_type 必须是非空字符串")
        if task_type not in known:
            raise ValueError(f"卡片 {card.get('id')} 的类型不是现行卡片: {task_type}")
        _require_finite_number(card.get("pos_x"), f"卡片 {card.get('id')} 的 pos_x")
        _require_finite_number(card.get("pos_y"), f"卡片 {card.get('id')} 的 pos_y")
        if not isinstance(card.get("parameters"), dict):
            raise ValueError(f"卡片 {card.get('id')} 的 parameters 必须是对象")
        custom_name = card.get("custom_name")
        if custom_name is not None and not isinstance(custom_name, str):
            raise ValueError(f"卡片 {card.get('id')} 的 custom_name 必须是字符串或 null")
    seen: Set[Tuple[int, int, str]] = set()
    for item in connections:
        if not isinstance(item, dict):
            raise ValueError("存在无效连线")
        start_id, end_id, line_type = _connection_key(item)
        if start_id not in indexed or end_id not in indexed:
            raise ValueError(f"连线指向不存在的卡片: {start_id} -> {end_id}")
        rule_error = _connection_rule_error(
            start_id,
            str(indexed[start_id].get("task_type") or "").strip(),
            end_id,
            str(indexed[end_id].get("task_type") or "").strip(),
            line_type,
        )
        if rule_error:
            raise ValueError(rule_error)
        key = (start_id, end_id, line_type)
        if key in seen:
            raise ValueError(f"工作流存在重复连线: {start_id} -> {end_id} ({line_type})")
        seen.add(key)


def bind_proposal_camera(workflow: Mapping[str, Any], current: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Keep the editor camera and metadata when the proposal omitted them."""
    result = copy.deepcopy(dict(workflow))
    source = current if isinstance(current, Mapping) else {}
    if "metadata" not in result:
        metadata = source.get("metadata")
        result["metadata"] = copy.deepcopy(metadata) if isinstance(metadata, dict) else {}
    elif not isinstance(result.get("metadata"), dict):
        raise ValueError("工作流 metadata 必须是字典")
    for key in ("view_transform", "view_center"):
        if key in result:
            continue
        if key in source:
            result[key] = copy.deepcopy(source[key])
    return result


def _close_editor_overlays(main_window: Any) -> None:
    panel = getattr(main_window, "parameter_panel", None) if main_window is not None else None
    if panel is not None and callable(getattr(panel, "hide_panel", None)) and bool(getattr(panel, "isVisible", lambda: False)()):
        panel.hide_panel()
    editors = getattr(main_window, "_script_editors", None) if main_window is not None else None
    if not editors:
        return
    for dialog in list(editors.values()):
        if dialog is None:
            continue
        setattr(dialog, "_leave_confirmed", True)
        closer = getattr(dialog, "close", None)
        if callable(closer):
            closer()


def apply_editor_workflow(
    main_window: Any,
    proposal_text: str,
    *,
    source_workflow: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate ops against the live canvas or an uploaded workflow, then load the result."""
    from app_core.ai_assistant import _current_editor_view

    ops = parse_workflow_proposal(proposal_text)
    view, _task = _current_editor_view(main_window)
    serialize = getattr(view, "serialize_workflow", None)
    load = getattr(view, "load_workflow", None)
    if view is None or not callable(serialize) or not callable(load):
        raise RuntimeError("当前没有打开的工作流")
    if not bool(getattr(view, "editing_enabled", True)):
        raise RuntimeError("当前工作流不可编辑，无法应用修正")
    running = getattr(view, "_is_workflow_running", None)
    if callable(running) and running():
        raise RuntimeError("工作流正在运行，无法应用修正")
    modules = getattr(view, "task_modules", None)
    if not isinstance(modules, dict) or not modules:
        raise RuntimeError("当前编辑器没有现行卡片目录")

    _close_editor_overlays(main_window)
    try:
        current = serialize()
    except Exception as exc:
        raise RuntimeError(f"无法读取当前工作流：{exc}") from exc
    if not isinstance(current, dict):
        raise RuntimeError("当前工作流数据不是字典")
    if source_workflow is None:
        base = current
    else:
        if not isinstance(source_workflow, Mapping) or isinstance(source_workflow, (str, bytes)):
            raise ValueError("上传的工作流数据不是字典")
        base = copy.deepcopy(dict(source_workflow))
        if not isinstance(base.get("cards"), list):
            base["cards"] = []
        if not isinstance(base.get("connections"), list):
            base["connections"] = []

    prepared = bind_proposal_camera(
        apply_workflow_ops(base, ops, known_task_types=modules.keys()),
        current,
    )
    try:
        load(prepared)
    except Exception as exc:
        try:
            load(current)
        except Exception as restore_exc:
            raise RuntimeError(
                f"应用失败且无法恢复原工作流：{exc}；恢复失败：{restore_exc}"
            ) from exc
        raise RuntimeError(f"应用失败，已恢复原工作流：{exc}") from exc

    save_undo = getattr(view, "_save_undo_state", None)
    if callable(save_undo):
        save_undo("replace_workflow", {"workflow_data": current})
    mark_dirty = getattr(view, "_mark_workflow_dirty", None)
    if callable(mark_dirty):
        mark_dirty()
    return {
        "ops": len(ops),
        "cards": len(prepared.get("cards") or []),
        "connections": len(prepared.get("connections") or []),
    }
