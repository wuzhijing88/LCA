"""Copy an AI workflow result into an existing canvas with fresh card IDs."""

from __future__ import annotations

import ast
import copy
import hashlib
import io
import math
import tokenize
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple


_CARD_REFERENCE_HINTS = frozenset(
    {"card_selector", "jump_target_selector", "workflow_card_selector"}
)
_EXPLICIT_CARD_REFERENCES = frozenset({"success_jump_target_id", "failure_jump_target_id"})
_THREAD_SPECIAL_VALUES = frozenset({"当前线程", "全部线程"})
_LINE_TYPES = frozenset({"sequential", "success", "failure", "random"})
_CARD_WIDTH = 200
_APPEND_GAP = 120


class _UncertainScriptCardReference(ValueError):
    """A script lookup cannot be assigned to a known card ID before execution."""


def _card_id(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} 必须是非负整数")
    return value


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} 必须是有限数字")
    return float(value)


def _numeric_reference(value: Any, field: str) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError(f"{field} 必须是数字字符串")
    return int(value)


def _index_workflow(
    workflow: Mapping[str, Any], label: str
) -> Tuple[Dict[int, Dict[str, Any]], List[Dict[str, Any]]]:
    if not isinstance(workflow, Mapping):
        raise ValueError(f"{label}数据必须是字典")
    if not isinstance(workflow.get("cards"), list) or not isinstance(workflow.get("connections"), list):
        raise ValueError(f"{label}的 cards 和 connections 必须是列表")
    cards: Dict[int, Dict[str, Any]] = {}
    for item in workflow["cards"]:
        if not isinstance(item, dict):
            raise ValueError(f"{label}存在无效卡片")
        card_id = _card_id(item.get("id"), "卡片 ID")
        if card_id in cards:
            raise ValueError(f"{label}存在重复卡片 ID: {card_id}")
        if not isinstance(item.get("task_type"), str) or not item["task_type"].strip():
            raise ValueError(f"卡片 {card_id} 的 task_type 必须是非空字符串")
        _number(item.get("pos_x"), f"卡片 {card_id} 的 pos_x")
        _number(item.get("pos_y"), f"卡片 {card_id} 的 pos_y")
        if not isinstance(item.get("parameters"), dict):
            raise ValueError(f"卡片 {card_id} 的 parameters 必须是字典")
        cards[card_id] = item
    connections: List[Dict[str, Any]] = []
    keys = set()
    for item in workflow["connections"]:
        if not isinstance(item, dict):
            raise ValueError(f"{label}存在无效连线")
        start = _card_id(item.get("start_card_id"), "连线 start_card_id")
        end = _card_id(item.get("end_card_id"), "连线 end_card_id")
        line_type = item.get("type")
        if not isinstance(line_type, str) or line_type not in _LINE_TYPES:
            raise ValueError(f"{label}的连线类型无效: {line_type!r}")
        if start not in cards or end not in cards:
            raise ValueError(f"{label}的连线指向不存在的卡片: {start} -> {end}")
        key = (start, end, line_type)
        if key in keys:
            raise ValueError(f"{label}存在重复连线: {start} -> {end} ({line_type})")
        keys.add(key)
        connections.append(item)
    return cards, connections


def _parameter_definitions(card: Mapping[str, Any], task_modules: Mapping[str, Any]) -> Dict[str, Any]:
    card_id = card["id"]
    module = task_modules.get(card["task_type"])
    getter = getattr(module, "get_params_definition", None)
    if not callable(getter):
        raise ValueError(f"卡片 {card_id} 没有现行参数定义接口")
    definitions = getter()
    if not isinstance(definitions, dict):
        raise ValueError(f"卡片 {card_id} 的参数定义必须是字典")
    for name, definition in definitions.items():
        if not isinstance(name, str) or not name or not isinstance(definition, dict):
            raise ValueError(f"卡片 {card_id} 的参数定义无效")
    return definitions


def _script_references(source: Any, card_id: int) -> List[Tuple[int, int, int]]:
    """Return exact integer-token spans for the script's static card lookups."""
    from task_workflow.script_sandbox import normalize_script_punctuation

    if not isinstance(source, str):
        raise ValueError(f"卡片 {card_id} 的 script_source 必须是字符串")
    # 现行中文标点规范化保持字符数和换行位置，解析出的范围仍对应原始源码。
    normalized = normalize_script_punctuation(source)
    try:
        with io.StringIO(normalized) as reader:
            tokens = list(tokenize.generate_tokens(reader.readline))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        raise ValueError(f"卡片 {card_id} 的脚本引用无法解析：{exc}") from exc
    for token in tokens:
        if token.type != tokenize.STRING:
            continue
        prefix_length = len(token.string) - len(token.string.lstrip("rRuUbBfF"))
        prefix = token.string[:prefix_length]
        if "f" not in prefix.lower():
            continue
        try:
            expression = ast.parse(token.string, mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"卡片 {card_id} 的脚本格式化字符串无法解析：{exc}") from exc
        if any(isinstance(node, ast.Name) and node.id == "卡片" for node in ast.walk(expression)):
            raise _UncertainScriptCardReference(
                f"卡片 {card_id} 的脚本格式化字符串含有卡片引用，无法确定追加后的目标"
            )
    ignored = {
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.NL,
        tokenize.COMMENT,
        tokenize.ENDMARKER,
    }
    tokens = [token for token in tokens if token.type not in ignored]
    line_offsets = [0]
    for line in source.splitlines(keepends=True):
        line_offsets.append(line_offsets[-1] + len(line))
    references = []
    for index, token in enumerate(tokens):
        if token.type != tokenize.NAME or token.string != "卡片":
            continue
        if index and tokens[index - 1].string == ".":
            continue
        following = tokens[index + 1 : index + 4]
        if (
            len(following) != 3
            or following[0].string != "["
            or following[1].type != tokenize.NUMBER
            or following[2].string != "]"
        ):
            raise _UncertainScriptCardReference(
                f"卡片 {card_id} 的脚本含有动态卡片引用，无法确定追加后的目标"
            )
        integer_token = following[1]
        try:
            target = ast.literal_eval(integer_token.string)
        except (SyntaxError, ValueError) as exc:
            raise ValueError(f"卡片 {card_id} 的脚本卡片引用必须是非负整数") from exc
        target = _card_id(target, f"卡片 {card_id} 的脚本卡片引用")
        start = line_offsets[integer_token.start[0] - 1] + integer_token.start[1]
        end = line_offsets[integer_token.end[0] - 1] + integer_token.end[1]
        references.append((start, end, target))
    return references


def _card_references(
    card: Mapping[str, Any], definitions: Mapping[str, Any]
) -> Tuple[Set[int], Set[str], Set[str], List[Tuple[int, int, int]]]:
    card_id = card["id"]
    parameters = card["parameters"]
    selector_names = set(_EXPLICIT_CARD_REFERENCES)
    selector_names.update(
        name for name, definition in definitions.items()
        if definition.get("widget_hint") in _CARD_REFERENCE_HINTS
    )
    thread_names = {
        name for name, definition in definitions.items()
        if definition.get("widget_hint") == "thread_target_selector"
    }
    references: Set[int] = set()
    for name in selector_names:
        value = parameters.get(name)
        if value is not None:
            references.add(_card_id(value, f"卡片 {card_id} 的引用参数 {name}"))
    for name in thread_names:
        if name not in parameters:
            continue
        value = parameters[name]
        if isinstance(value, str) and value in _THREAD_SPECIAL_VALUES:
            continue
        from task_workflow.thread_start import validate_thread_target

        validate_thread_target(value)
        targets = value if isinstance(value, list) else [value]
        references.update(_numeric_reference(target, f"卡片 {card_id} 的引用参数 {name}") for target in targets)
    if "random_weights" in parameters:
        weights = parameters["random_weights"]
        if not isinstance(weights, dict):
            raise ValueError(f"卡片 {card_id} 的随机跳转权重必须是字典")
        references.update(
            _numeric_reference(target, f"卡片 {card_id} 的随机跳转目标 ID")
            for target in weights
        )
    if "_random_connections" in parameters:
        connections = parameters["_random_connections"]
        if not isinstance(connections, list):
            raise ValueError(f"卡片 {card_id} 的随机跳转目标清单必须是列表")
        for item in connections:
            if not isinstance(item, dict):
                raise ValueError(f"卡片 {card_id} 的随机跳转目标项必须是字典")
            references.add(_card_id(item.get("card_id"), f"卡片 {card_id} 的随机跳转目标 ID"))
    script_references = []
    if card["task_type"] == "自定义脚本" and "script_source" in parameters:
        script_references = _script_references(parameters["script_source"], card_id)
        references.update(target for _start, _end, target in script_references)
    return references, selector_names, thread_names, script_references


def _remap_parameters(
    card: Mapping[str, Any],
    reference_info: Tuple[Set[int], Set[str], Set[str], List[Tuple[int, int, int]]],
    id_mapping: Mapping[int, int],
) -> Dict[str, Any]:
    parameters = copy.deepcopy(card["parameters"])
    _references, selector_names, thread_names, script_references = reference_info
    for name in selector_names:
        if name in parameters and parameters[name] is not None:
            parameters[name] = id_mapping[parameters[name]]
    for name in thread_names:
        if name not in parameters:
            continue
        value = parameters[name]
        if isinstance(value, list):
            parameters[name] = [str(id_mapping[int(target)]) for target in value]
        elif value not in _THREAD_SPECIAL_VALUES:
            parameters[name] = str(id_mapping[int(value)])
    if "random_weights" in parameters:
        weights = {}
        for target, weight in parameters["random_weights"].items():
            mapped = str(id_mapping[int(target)])
            if mapped in weights:
                raise ValueError(f"卡片 {card['id']} 的随机跳转权重映射发生冲突")
            weights[mapped] = weight
        parameters["random_weights"] = weights
    for item in parameters.get("_random_connections", []):
        item["card_id"] = id_mapping[item["card_id"]]
    if script_references:
        source = parameters["script_source"]
        for start, end, target in reversed(script_references):
            source = source[:start] + str(id_mapping[target]) + source[end:]
        parameters["script_source"] = source
        if "script_source_sha256" in parameters:
            parameters["script_source_sha256"] = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return parameters


def is_self_contained_card_references(
    ops: Sequence[Mapping[str, Any]], task_modules: Mapping[str, Any]
) -> bool:
    """Whether every explicit card reference belongs to a card declared by these ops."""
    added_ids = {item["id"] for item in ops if item["op"] == "add_card"}
    if not added_ids:
        return False
    if not isinstance(task_modules, Mapping) or not task_modules:
        raise ValueError("当前编辑器没有现行卡片目录")
    declared_cards = {}
    for item in ops:
        op_name = item["op"]
        if op_name == "add_card":
            declared_cards[item["id"]] = copy.deepcopy(dict(item))
        elif op_name == "set_parameters":
            if item["id"] not in declared_cards:
                return False
            declared_cards[item["id"]]["parameters"].update(copy.deepcopy(item["parameters"]))
        else:
            continue
        card = declared_cards[item["id"]]
        definitions = _parameter_definitions(card, task_modules)
        try:
            references, _selectors, _threads, _script_spans = _card_references(card, definitions)
        except _UncertainScriptCardReference:
            return False
        if not references.issubset(added_ids):
            return False
    return True


def append_workflow_result(
    current: Mapping[str, Any],
    generated: Mapping[str, Any],
    *,
    task_modules: Mapping[str, Any],
    card_ids: Optional[Set[int]] = None,
) -> Dict[str, Any]:
    """Append a closed group of fresh card copies, preserving the current workflow."""
    current_cards, _current_connections = _index_workflow(current, "当前工作流")
    generated_cards, generated_connections = _index_workflow(generated, "AI 工作流")
    if not isinstance(task_modules, Mapping) or not task_modules:
        raise ValueError("当前编辑器没有现行卡片目录")
    if card_ids is None:
        selected = set(generated_cards)
    else:
        if not isinstance(card_ids, (set, frozenset)):
            raise ValueError("待追加卡片 ID 必须是集合")
        selected = {_card_id(value, "待追加卡片 ID") for value in card_ids}
    missing = selected.difference(generated_cards)
    if missing:
        raise ValueError(f"待追加卡片不存在: {sorted(missing)}")
    if not selected:
        raise ValueError("这份修正没有可追加的卡片")

    adjacency = {card_id: set() for card_id in generated_cards}
    for item in generated_connections:
        adjacency[item["start_card_id"]].add(item["end_card_id"])
        adjacency[item["end_card_id"]].add(item["start_card_id"])
    reference_infos = {}
    pending = list(selected)
    while pending:
        card_id = pending.pop()
        card = generated_cards[card_id]
        definitions = _parameter_definitions(card, task_modules)
        info = _card_references(card, definitions)
        reference_infos[card_id] = info
        missing = info[0].difference(generated_cards)
        if missing:
            raise ValueError(f"卡片 {card_id} 引用了 AI 工作流中不存在的卡片: {sorted(missing)}")
        added = (adjacency[card_id] | info[0]).difference(selected)
        selected.update(added)
        pending.extend(added)

    next_id = max(current_cards, default=-1) + 1
    id_mapping = {card_id: next_id + index for index, card_id in enumerate(sorted(selected))}
    if current_cards:
        offset_x = (
            max(card["pos_x"] for card in current_cards.values()) + _CARD_WIDTH + _APPEND_GAP
            - min(generated_cards[card_id]["pos_x"] for card_id in selected)
        )
        offset_y = (
            min(card["pos_y"] for card in current_cards.values())
            - min(generated_cards[card_id]["pos_y"] for card_id in selected)
        )
    else:
        offset_x = offset_y = 0
    result = copy.deepcopy(dict(current))
    for card_id in sorted(selected):
        card = copy.deepcopy(generated_cards[card_id])
        card["id"] = id_mapping[card_id]
        card["pos_x"] = _number(card["pos_x"] + offset_x, f"卡片 {card_id} 的追加横坐标")
        card["pos_y"] = _number(card["pos_y"] + offset_y, f"卡片 {card_id} 的追加纵坐标")
        card["parameters"] = _remap_parameters(card, reference_infos[card_id], id_mapping)
        result["cards"].append(card)
    for item in generated_connections:
        if item["start_card_id"] not in selected or item["end_card_id"] not in selected:
            continue
        connection = copy.deepcopy(item)
        connection["start_card_id"] = id_mapping[item["start_card_id"]]
        connection["end_card_id"] = id_mapping[item["end_card_id"]]
        result["connections"].append(connection)
    return result
