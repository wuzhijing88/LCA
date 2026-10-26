"""脚本卡片插件的现行包格式、快照、安装及运行占用管理。"""
from __future__ import annotations

import ast
import base64
import copy
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import threading
import zipfile
import zlib

PLUGIN_TASK_TYPE = "脚本卡片"
BUNDLE_PARAMETER = "plugin_bundle"
PACKAGE_EXTENSION = ".lcac"
FORMAT_VERSION = 2
RUNTIME_API_VERSION = 1
MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_CONTENT_BYTES = 128 * 1024 * 1024
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 128 * 1024
RESOURCE_FOLDERS = {
    "image": ("images", "images_dir"),
    "sound": ("sounds", "sounds_dir"),
    "dict": ("dicts", "dicts_dir"),
    "model": ("yolo", "yolo_dir"),
    "replay": ("replays", "replays_dir"),
    "component": ("components", "plugins_dir"),
}
_INPUT_TYPES = frozenset({"text", "int", "float", "bool", "choice", "file"})
_OUTPUT_TYPES = frozenset({"text", "int", "float", "bool", "object", "list"})
_BASE_FIELDS = frozenset({"format_version", "runtime_api", "id", "version", "name", "description", "category", "parameters", "outputs", "environment"})
_ID_RE = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*\Z")
_VERSION_RE = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[a-z0-9]+(?:[.-][a-z0-9]+)*)?\Z")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_active_lock = threading.RLock()
_active_packages: dict[str, int] = {}


class CardPluginError(ValueError):
    """插件包、参数或生命周期不满足现行契约。"""


def _text(value, label, *, limit=4096, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise CardPluginError(f"{label}必须是{'可为空的' if empty else '非空的'}文本，且不超过 {limit} 个字符")
    return value


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CardPluginError(f"插件清单包含重复字段：{key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise CardPluginError("插件清单不能包含非有限数字")


def _json_bytes(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise CardPluginError("插件清单包含无法序列化的值或超出范围的整数") from exc


def package_member(value):
    name = _text(value, "包内路径", limit=512)
    parts = name.split("/")
    if "\\" in name or name.startswith("/") or any(not part or part in {".", ".."} for part in parts):
        raise CardPluginError(f"包内路径无效：{name}")
    reserved = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}
    for part in parts:
        if part[-1:] in {".", " "} or any(char in part for char in ':<>"|?*') or any(ord(char) < 32 for char in part) or part.split(".")[0].casefold() in reserved:
            raise CardPluginError(f"包内路径不适用于当前文件系统：{name}")
    if str(PurePosixPath(name)) != name:
        raise CardPluginError(f"包内路径必须规范化：{name}")
    return name


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)):
        raise CardPluginError(f"{label}必须是有限数字")
    return value


def input_parameter_key(name):
    """插件业务参数使用独立存储命名空间，避免触发内置卡片字段规则。"""
    return "plugin_input_" + name.encode("utf-8").hex()




_DECLARATION_TYPES = {
    "文本": ("text", None), "多行文本": ("text", None), "整数": ("int", None), "小数": ("float", None), "真假": ("bool", None),
    "选项": ("choice", None), "图片文件": ("file", "image"), "音频文件": ("file", "sound"),
    "字库文件": ("file", "dict"), "模型文件": ("file", "model"), "回放文件": ("file", "replay"),
    "组件文件": ("file", "component"), "字典": ("object", None), "列表": ("list", None),
}
_DECLARATION_PARAMETER_KEYS = frozenset({"类型", "默认", "必填", "最小", "最大", "步长", "小数位", "选项", "说明", "工具"})
_DECLARATION_OUTPUT_KEYS = frozenset({"类型", "必填", "说明"})


def _ast_literal(node, label):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError) as exc:
        raise CardPluginError(f"{label}必须是固定值") from exc


def _call_path(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_path(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _definition_from_declaration(call, *, output):
    if len(call.args) != 1 or any(item.arg is None for item in call.keywords):
        raise CardPluginError("插件声明必须使用一个固定名称和命名参数")
    name = _ast_literal(call.args[0], "插件参数或输出名称")
    _text(name, "插件参数或输出名称", limit=64)
    allowed = _DECLARATION_OUTPUT_KEYS if output else _DECLARATION_PARAMETER_KEYS
    values = {}
    for keyword in call.keywords:
        if keyword.arg not in allowed:
            raise CardPluginError(f"插件声明不支持字段：{keyword.arg}")
        if keyword.arg in values:
            raise CardPluginError(f"插件声明字段重复：{keyword.arg}")
        values[keyword.arg] = _ast_literal(keyword.value, f"插件声明字段 {keyword.arg}")
    type_name = values.get("类型")
    if not isinstance(type_name, str) or type_name not in _DECLARATION_TYPES:
        raise CardPluginError("插件声明必须写受支持的 类型")
    if output and type_name == "多行文本":
        raise CardPluginError("输出不支持多行文本类型，请使用文本")
    kind, resource_kind = _DECLARATION_TYPES[type_name]
    if kind not in (_OUTPUT_TYPES if output else _INPUT_TYPES):
        raise CardPluginError(f"{'输出' if output else '参数'}不支持类型：{type_name}")
    definition = {"label": name, "type": kind, "required": values.get("必填", True), "tooltip": values.get("说明", "")}
    if not output:
        if kind == "file":
            if "默认" in values:
                raise CardPluginError(f"文件参数 {name} 不接受默认值，必须由工作流传入")
            definition["default"] = ""
            definition["resource_kind"] = resource_kind
        else:
            if "默认" not in values:
                raise CardPluginError(f"参数 {name} 必须显式填写默认值")
            definition["default"] = values["默认"]
        for source_key, target_key in (("最小", "min"), ("最大", "max"), ("步长", "step"), ("小数位", "decimals"), ("选项", "options")):
            if source_key in values:
                definition[target_key] = values[source_key]
        if type_name == "多行文本":
            definition["multiline"] = True
        if "工具" in values:
            definition["tool"] = values["工具"]
    return name, definition


def extract_plugin_declarations(source):
    from task_workflow.script_sandbox import parse_script
    try:
        tree = parse_script(source)
        compile(tree, "<脚本卡片>", "exec")
    except SyntaxError as exc:
        raise CardPluginError(f"插件脚本第 {exc.lineno or 1} 行语法无效：{exc.msg}") from exc
    except RecursionError as exc:
        raise CardPluginError("插件脚本结构过于复杂，无法完成校验，请拆分过长的表达式") from exc
    parameters, outputs = {}, {}
    top_level = set()
    body_started = False
    for index, statement in enumerate(tree.body):
        if index == 0 and isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
            continue
        is_declaration = isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call) and _call_path(statement.value.func) in {"参数.声明", "输出.声明"}
        if is_declaration:
            if body_started:
                raise CardPluginError("参数.声明和输出.声明必须集中写在脚本顶部，位于执行逻辑之前")
            top_level.add(statement.value)
        else:
            body_started = True
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        path = _call_path(node.func)
        if path not in {"参数.声明", "输出.声明"}:
            continue
        if node not in top_level:
            raise CardPluginError("参数.声明和输出.声明必须写在脚本顶层，不能放进条件、循环或函数")
        name, definition = _definition_from_declaration(node, output=path == "输出.声明")
        target = outputs if path == "输出.声明" else parameters
        if name in target:
            raise CardPluginError(f"插件声明名称重复：{name}")
        target[name] = definition
    _validate_definitions(parameters)
    _validate_definitions(outputs, output=True)
    return {"parameters": parameters, "outputs": outputs}


def validate_plugin_declarations(source, manifest):
    from inspect import signature
    from task_workflow.card_plugin_runtime import PluginParameterView, PluginOutputView
    from task_workflow.script_sandbox import parse_script

    declarations = extract_plugin_declarations(source)
    if declarations["parameters"] != manifest["parameters"] or declarations["outputs"] != manifest["outputs"]:
        raise CardPluginError("脚本声明与插件清单不一致，请重新导出插件")
    interfaces = {
        "参数.获取": (signature(PluginParameterView.获取), "parameters", "读取了未声明的参数"),
        "输出.设置": (signature(PluginOutputView.设置), "outputs", "写入了未声明的输出"),
    }
    for node in ast.walk(parse_script(source)):
        if not isinstance(node, ast.Call) or _call_path(node.func) not in interfaces:
            continue
        name = _call_path(node.func)
        call_signature, field, message = interfaces[name]
        keywords = {item.arg: item.value for item in node.keywords if item.arg is not None}
        expanded = any(isinstance(item, ast.Starred) for item in node.args) or any(item.arg is None for item in node.keywords)
        if expanded:
            reference = node.args[0] if node.args and not isinstance(node.args[0], ast.Starred) else keywords.get("名字")
        else:
            try:
                arguments = call_signature.bind(None, *node.args, **keywords).arguments
            except TypeError as exc:
                raise CardPluginError(f"{name}的调用参数无效，请按接口填写名字及必需的值") from exc
            reference = arguments["名字"]
        if isinstance(reference, ast.Constant) and isinstance(reference.value, str) and reference.value not in manifest[field]:
            raise CardPluginError(f"脚本{message}：{reference.value}")
    return declarations


def plugin_command_paths(source):
    from task_workflow.script_sandbox import parse_script

    return sorted({
        _call_path(node) for node in ast.walk(parse_script(source))
        if isinstance(node, ast.Attribute) and _call_path(node) in {
            "参数.声明", "参数.获取", "输出.声明", "输出.设置",
        }
    })


def validate_value(value, definition, label, *, output=False, allow_empty_file=False):
    kind = definition["type"]
    if kind in {"text", "file", "choice"}:
        _text(value, label, empty=True)
        if definition.get("required", True) and not value.strip() and not (kind == "file" and allow_empty_file):
            raise CardPluginError(f"{label}不能为空")
        if kind == "choice" and value not in definition["options"]:
            raise CardPluginError(f"{label}不属于允许的选项")
    elif kind == "bool":
        if not isinstance(value, bool):
            raise CardPluginError(f"{label}必须是真或假")
    elif kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise CardPluginError(f"{label}必须是整数")
    elif kind == "float":
        _finite(value, label)
    elif kind == "object":
        if not isinstance(value, dict):
            raise CardPluginError(f"{label}必须是字典")
    elif kind == "list":
        if not isinstance(value, list):
            raise CardPluginError(f"{label}必须是列表")
    else:
        raise CardPluginError(f"{label}使用了未知类型：{kind}")
    if kind in {"int", "float"}:
        if "min" in definition and value < definition["min"]:
            raise CardPluginError(f"{label}不能小于 {definition['min']}")
        if "max" in definition and value > definition["max"]:
            raise CardPluginError(f"{label}不能大于 {definition['max']}")
    from task_workflow.runtime_store import normalize_var_value
    return normalize_var_value(value)


def _validate_definitions(definitions, *, output=False):
    label = "输出" if output else "参数"
    if not isinstance(definitions, dict) or len(definitions) > 32:
        raise CardPluginError(f"{label}定义必须是对象，且最多 32 项")
    for key, definition in definitions.items():
        _text(key, f"{label}名称", limit=64)
        if key == BUNDLE_PARAMETER or key.startswith("__"):
            raise CardPluginError(f"{label}名称被系统保留：{key}")
        if not isinstance(definition, dict):
            raise CardPluginError(f"{label} {key} 的定义必须是对象")
        required = {"label", "type", "required"} | (set() if output else {"default"})
        allowed = required | {"tooltip"}
        if not output:
            allowed |= {"min", "max", "step", "decimals", "options", "resource_kind", "multiline", "tool"}
        if not required.issubset(definition) or set(definition) - allowed:
            raise CardPluginError(f"{label} {key} 的定义字段不完整或包含未知字段")
        _text(definition["label"], f"{label}标签", limit=128)
        if not isinstance(definition["type"], str) or definition["type"] not in (_OUTPUT_TYPES if output else _INPUT_TYPES):
            raise CardPluginError(f"{label} {key} 的类型不支持")
        if not isinstance(definition["required"], bool):
            raise CardPluginError(f"{label} {key} 的必填设置必须是真或假")
        if "tooltip" in definition:
            _text(definition["tooltip"], f"{label}说明", empty=True)
        kind = definition["type"]
        numeric = kind in {"int", "float"}
        for bound in ("min", "max", "step"):
            if bound in definition:
                if not numeric:
                    raise CardPluginError(f"{label} {key} 的数值范围只适用于数字")
                value = _finite(definition[bound], f"{key} 的{bound}")
                if kind == "int" and not isinstance(value, int):
                    raise CardPluginError(f"整数参数 {key} 的范围及步长必须是整数")
                if bound == "step" and value <= 0:
                    raise CardPluginError(f"参数 {key} 的步长必须大于 0")
        if "min" in definition and "max" in definition and definition["min"] > definition["max"]:
            raise CardPluginError(f"{label} {key} 的最小值不能大于最大值")
        if "decimals" in definition and (kind != "float" or isinstance(definition["decimals"], bool) or not isinstance(definition["decimals"], int) or not 0 <= definition["decimals"] <= 12):
            raise CardPluginError(f"参数 {key} 的小数位数必须是 0～12 的整数")
        if kind == "choice":
            options = definition.get("options")
            if not isinstance(options, list) or not 1 <= len(options) <= 100 or any(not isinstance(item, str) or not item for item in options) or len(options) != len(set(options)):
                raise CardPluginError(f"参数 {key} 的选项必须是非空且不重复的文本列表")
        elif "options" in definition:
            raise CardPluginError(f"参数 {key} 只有选项类型才能声明选项")
        if kind == "file":
            if not isinstance(definition.get("resource_kind"), str) or definition["resource_kind"] not in RESOURCE_FOLDERS:
                raise CardPluginError(f"文件参数 {key} 必须声明资源类型")
            if definition["default"] != "":
                raise CardPluginError(f"文件参数 {key} 的默认值必须为空，由工作流传入")
        elif "resource_kind" in definition:
            raise CardPluginError(f"参数 {key} 只有文件类型才能声明资源类型")
        if not output:
            if "multiline" in definition and (kind != "text" or definition["multiline"] is not True):
                raise CardPluginError(f"参数 {key} 的多行设置只适用于多行文本类型")
            validate_value(definition["default"], definition, f"参数 {key} 的默认值", allow_empty_file=True)
            if "decimals" in definition:
                from app_core.card_plugin_conditions import validate_effective_value
                validate_effective_value(definition["default"], definition, f"参数 {key} 的默认值")
    if not output:
        from app_core.card_plugin_presentation import validate_presentations
        validate_presentations(definitions)



def normalize_manifest(value, *, complete):
    if not isinstance(value, dict):
        raise CardPluginError("插件清单必须是对象")
    expected = _BASE_FIELDS | ({"entry", "files"} if complete else set())
    if set(value) != expected:
        raise CardPluginError("插件清单字段不完整或包含未知字段")
    result = copy.deepcopy(value)
    if type(result["format_version"]) is not int or result["format_version"] != FORMAT_VERSION:
        raise CardPluginError("插件包格式版本不支持")
    if type(result["runtime_api"]) is not int or result["runtime_api"] != RUNTIME_API_VERSION:
        raise CardPluginError("插件运行接口版本不支持")
    identity = _text(result["id"], "插件标识", limit=128)
    if not _ID_RE.fullmatch(identity):
        raise CardPluginError("插件标识须由小写字母、数字及分隔点、下划线或短横线组成")
    package_member(identity)
    if not _VERSION_RE.fullmatch(_text(result["version"], "插件版本", limit=64)):
        raise CardPluginError("插件版本须使用三段版本号，例如 1.0.0")
    _text(result["name"], "卡片名称", limit=128)
    _text(result["description"], "卡片说明", empty=True)
    _text(result["category"], "卡片分类", limit=64)
    _validate_definitions(result["parameters"])
    _validate_definitions(result["outputs"], output=True)
    if complete and result.get("files") != []:
        raise CardPluginError("插件只支持逻辑包，不允许内置资源")
    environment = result["environment"]
    if not isinstance(environment, dict) or set(environment) != {"mode", "interpreter", "requirements", "index_url"}:
        raise CardPluginError("插件环境必须完整声明执行模式、解释器、依赖和软件源")
    from app_core.script_environments import normalize_environment
    canonical_environment = normalize_environment(environment)
    if canonical_environment != environment:
        raise CardPluginError("插件环境设置必须使用现行规范格式")
    if complete and result["entry"] != "main.lcas":
        raise CardPluginError("插件脚本入口必须为 main.lcas")
    return result


@dataclass(frozen=True)
class CardPluginBundle:
    raw: bytes
    _manifest: dict
    source: str
    digest: str

    @property
    def manifest(self):
        return copy.deepcopy(self._manifest)

    def snapshot(self):
        return {"sha256": self.digest, "package": base64.b64encode(self.raw).decode("ascii")}

    def parameter_definitions(self):
        definitions = {BUNDLE_PARAMETER: {"type": "hidden", "default": self.snapshot()}}
        for key, definition in self.manifest["parameters"].items():
            field = copy.deepcopy(definition)
            field.pop("required")

            if field["type"] == "file":
                field["file_filter"] = "所有文件 (*.*)"
            definitions[input_parameter_key(key)] = field
        return definitions


def _read_package_member(archive, name, limit):
    with archive.open(name) as member:
        data = member.read(limit + 1)
    if len(data) > limit:
        raise CardPluginError("插件清单或脚本内容超过上限")
    return data


def read_package_bytes(raw):
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_PACKAGE_BYTES:
        raise CardPluginError("插件包为空或超过 64 MB 上限")
    try:
        with io.BytesIO(raw) as stream, zipfile.ZipFile(stream) as archive:
            infos = archive.infolist()
            if len(infos) != 2:
                raise CardPluginError("插件只支持逻辑包，仅允许清单和脚本入口")
            names = []
            total = 0
            for info in infos:
                name = package_member(info.filename)
                if info.is_dir() or info.flag_bits & 1 or stat.S_ISLNK(info.external_attr >> 16):
                    raise CardPluginError("插件包不允许目录条目、加密条目或符号链接")
                if info.file_size > MAX_CONTENT_BYTES:
                    raise CardPluginError("插件包文件大小超出上限")
                total += info.file_size
                names.append(name)
            if total > MAX_CONTENT_BYTES or len(names) != len({name.casefold() for name in names}):
                raise CardPluginError("插件包容量超过 128 MB 或存在重复路径")
            if "manifest.json" not in names or "main.lcas" not in names:
                raise CardPluginError("插件包缺少清单或脚本入口")
            if archive.getinfo("manifest.json").file_size > MAX_MANIFEST_BYTES or archive.getinfo("main.lcas").file_size > MAX_SOURCE_BYTES:
                raise CardPluginError("插件清单或脚本内容超过上限")
            manifest = json.loads(_read_package_member(archive, "manifest.json", MAX_MANIFEST_BYTES).decode("utf-8"), object_pairs_hook=_strict_object, parse_constant=_invalid_constant)
            manifest = normalize_manifest(manifest, complete=True)
            records = manifest["files"]
            if records != []:
                raise CardPluginError("插件只支持逻辑包，不允许内置资源")
            expected = {"manifest.json", "main.lcas"}
            if set(names) != expected:
                raise CardPluginError("插件包只允许清单和脚本入口")
            source = _read_package_member(archive, "main.lcas", MAX_SOURCE_BYTES).decode("utf-8")
    except CardPluginError:
        raise
    except (OSError, ValueError, KeyError, UnicodeError, zipfile.BadZipFile, zlib.error, NotImplementedError, RuntimeError) as exc:
        raise CardPluginError("无法读取插件包：内容损坏或压缩格式不支持") from exc
    if not source.strip():
        raise CardPluginError("插件脚本不能为空")
    from task_workflow.script_sandbox import parse_script, validate_script
    from tasks.script_task import validate_script_source
    declarations = validate_plugin_declarations(source, manifest)
    validate_script(source)
    validate_script_source(source)
    references = script_resource_references(source)
    if references:
        raise CardPluginError("插件不能写死资源路径，请为资源声明文件参数：" + "、".join(value for _kind, value in references))
    try:
        compile(parse_script(source), "<脚本卡片>", "exec")
    except SyntaxError as exc:
        raise CardPluginError(f"插件脚本第 {exc.lineno or 1} 行语法无效") from exc
    manifest.update(declarations)
    return CardPluginBundle(raw, manifest, source, hashlib.sha256(raw).hexdigest())


def read_package(path):
    target = Path(path)
    if target.suffix.lower() != PACKAGE_EXTENSION or target.is_symlink():
        raise CardPluginError("请选择有效的 .lcac 卡片插件包")
    try:
        if target.stat().st_size > MAX_PACKAGE_BYTES:
            raise CardPluginError("插件包超过 64 MB 上限")
        with target.open("rb") as handle:
            raw = handle.read(MAX_PACKAGE_BYTES + 1)
        return read_package_bytes(raw)
    except OSError as exc:
        raise CardPluginError("无法读取卡片插件包文件") from exc


def bundle_from_parameters(parameters):
    if not isinstance(parameters, dict) or BUNDLE_PARAMETER not in parameters:
        raise CardPluginError("脚本卡片缺少插件快照")
    snapshot = parameters[BUNDLE_PARAMETER]
    if not isinstance(snapshot, dict) or set(snapshot) != {"sha256", "package"} or not isinstance(snapshot["sha256"], str) or not _DIGEST_RE.fullmatch(snapshot["sha256"]):
        raise CardPluginError("插件快照格式无效")
    encoded = snapshot["package"]
    if not isinstance(encoded, str) or len(encoded) > ((MAX_PACKAGE_BYTES + 2) // 3) * 4:
        raise CardPluginError("插件快照内容无效或超过容量上限")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, UnicodeError) as exc:
        raise CardPluginError("插件快照编码无效") from exc
    if hashlib.sha256(raw).hexdigest() != snapshot["sha256"]:
        raise CardPluginError("插件快照完整性校验失败")
    return read_package_bytes(raw)


def build_package(manifest, source):
    manifest = normalize_manifest(manifest, complete=False)
    _text(source, "插件脚本", limit=MAX_SOURCE_BYTES)
    source_bytes = source.encode("utf-8")
    if len(source_bytes) > MAX_SOURCE_BYTES:
        raise CardPluginError("插件脚本超过 2 MB 上限")
    from task_workflow.script_sandbox import validate_script
    validate_plugin_declarations(source, manifest)
    validate_script(source)
    references = script_resource_references(source)
    if references:
        raise CardPluginError("插件不能写死资源路径，请为资源声明文件参数：" + "、".join(value for _kind, value in references))
    files = []
    manifest.update(entry="main.lcas", files=files)
    entries = {"main.lcas": source_bytes, "manifest.json": _json_bytes(manifest)}
    with io.BytesIO() as output:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
        raw = output.getvalue()
    return read_package_bytes(raw)


def write_package(path, bundle):
    destination = Path(path)
    if destination.suffix.lower() != PACKAGE_EXTENSION:
        raise CardPluginError("卡片插件文件必须使用 .lcac 扩展名")
    temporary = None
    write_error = None
    cleanup_error = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(bundle.raw)
        os.replace(temporary, destination)
    except OSError as exc:
        write_error = exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as exc:
                cleanup_error = exc
    if cleanup_error is not None:
        detail = "无法写入卡片插件包；" if write_error is not None else ""
        raise CardPluginError(f"{detail}插件临时文件未能清理，请检查目录权限及文件占用：{temporary}") from cleanup_error
    if write_error is not None:
        raise CardPluginError("无法写入卡片插件包，请检查目标目录权限及文件占用") from write_error


@contextmanager
def running_package(digest):
    with _active_lock:
        _active_packages[digest] = _active_packages.get(digest, 0) + 1
    try:
        yield
    finally:
        with _active_lock:
            remaining = _active_packages[digest] - 1
            if remaining:
                _active_packages[digest] = remaining
            else:
                del _active_packages[digest]


@dataclass(frozen=True)
class InstalledCardPlugin:
    path: Path
    digest: str
    manifest: dict

    def load(self):
        bundle = read_package(self.path)
        if bundle.digest != self.digest:
            raise CardPluginError("已安装插件内容发生变化")
        return bundle


@dataclass(frozen=True)
class InvalidInstalledCardPlugin:
    path: Path
    error: str
    identity: tuple | None


class CardPluginStore:
    def __init__(self, root=None):
        if root is None:
            from utils.app_paths import get_user_data_dir
            root = Path(get_user_data_dir()) / "card_plugins"
        self.root = Path(root).resolve()

    @contextmanager
    def _mutation(self):
        import msvcrt

        with _active_lock:
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                lock_path = self.root / ".store.lock"
                if lock_path.is_symlink():
                    raise CardPluginError("插件库锁文件不允许使用符号链接")
                with lock_path.open("a+b") as stream:
                    if stream.tell() == 0:
                        stream.write(b"0")
                        stream.flush()
                    stream.seek(0)
                    try:
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    except OSError as exc:
                        raise CardPluginError("插件库正在被其他进程修改或无法加锁，请稍后重试") from exc
                    try:
                        yield
                    finally:
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError as exc:
                raise CardPluginError("无法修改插件库，请检查目录权限及文件占用") from exc

    def _path(self, bundle):
        target = self.root / bundle.manifest["id"] / bundle.manifest["version"] / (bundle.digest + PACKAGE_EXTENSION)
        if not target.resolve().is_relative_to(self.root) or any(parent.is_symlink() for parent in (self.root, target.parent.parent, target.parent)):
            raise CardPluginError("插件安装目录无效")
        return target

    def inspect_installed(self):
        if not self.root.exists():
            return []
        if self.root.is_symlink():
            raise CardPluginError("插件安装目录不能是符号链接")
        paths = list(self.root.glob("*/*/*.lcac"))
        if len(paths) > 256:
            raise CardPluginError("已安装插件数量超过 256 项上限")
        result = []
        for path in sorted(paths):
            identity = None
            try:
                self._validate_installed_path(path)
                identity = self._file_identity(path)
                bundle = read_package(path)
                if self._path(bundle) != path or path.name != bundle.digest + PACKAGE_EXTENSION:
                    raise CardPluginError("已安装插件的目录或内容摘要不符")
            except (CardPluginError, OSError) as error:
                result.append(InvalidInstalledCardPlugin(path, str(error), identity))
            else:
                result.append(InstalledCardPlugin(path, bundle.digest, copy.deepcopy(bundle.manifest)))
        return result

    def list_installed(self):
        plugins = self.inspect_installed()
        for plugin in plugins:
            if isinstance(plugin, InvalidInstalledCardPlugin):
                raise CardPluginError(f"插件不可用：{plugin.path}：{plugin.error}")
        return plugins

    def _validate_installed_path(self, path):
        if not path.is_absolute() or not path.is_relative_to(self.root) or len(path.relative_to(self.root).parts) != 3:
            raise CardPluginError("插件文件不在当前安装库内")
        if not path.resolve().is_relative_to(self.root) or any(parent.is_symlink() for parent in (self.root, path.parent.parent, path.parent, path)):
            raise CardPluginError("插件文件路径无效或包含符号链接")
        if path.suffix != PACKAGE_EXTENSION or not path.is_file():
            raise CardPluginError("插件文件不存在或不是有效的安装包路径")

    @staticmethod
    def _file_identity(path):
        information = path.stat()
        return information.st_dev, information.st_ino, information.st_size, information.st_mtime_ns

    def uninstall_invalid(self, plugin):
        if not isinstance(plugin, InvalidInstalledCardPlugin) or plugin.identity is None:
            raise CardPluginError("无法确认失效插件的文件身份，请刷新后重试")
        target = plugin.path
        with self._mutation():
            self._validate_installed_path(target)
            if _active_packages.get(target.stem, 0):
                raise CardPluginError("插件正在运行，请停止后再卸载")
            if self._file_identity(target) != plugin.identity:
                raise CardPluginError("失效插件文件已经变化，请刷新后重试")
            target.unlink()
            for parent in (target.parent, target.parent.parent):
                if not any(parent.iterdir()):
                    parent.rmdir()

    def install(self, bundle):
        bundle = read_package_bytes(bundle.raw)
        target = self._path(bundle)
        with self._mutation():
            existing = list(target.parent.glob("*.lcac"))
            if existing:
                if len(existing) != 1 or existing[0] != target or read_package(target).raw != bundle.raw:
                    raise CardPluginError("相同标识和版本的插件内容不同；请先修改版本号")
                return target
            if sum(1 for _ in self.root.glob("*/*/*.lcac")) >= 256:
                raise CardPluginError("已安装插件数量达到 256 项上限")
            write_package(target, bundle)
            return target

    def uninstall(self, bundle):
        target = self._path(bundle)
        with self._mutation():
            if _active_packages.get(bundle.digest, 0):
                raise CardPluginError("插件正在运行，请停止后再卸载")
            if not target.is_file() or read_package(target).digest != bundle.digest:
                raise CardPluginError("已安装插件不存在或内容发生变化")
            target.unlink()
            for parent in (target.parent, target.parent.parent):
                if not any(parent.iterdir()):
                    parent.rmdir()


RESOURCE_COMMAND_ARGUMENTS = {
    "找图": ("image", "图片", 0, True), "等图": ("image", "图片", 0, True),
    "等图消失": ("image", "图片", 0, True), "持续找图": ("image", "图片", 0, True),
    "找所有图": ("image", "图片", 0, True), "图像.读取": ("image", "路径", 0, False),
    "检测": ("model", "模型", 0, False), "等检测": ("model", "模型", 0, False),
    "等检测消失": ("model", "模型", 0, False), "持续检测": ("model", "模型", 0, False),
    "播放": ("sound", "文件", 0, False), "回放": ("replay", "文件", 0, False),
    "组件.运行": ("component", "程序", 0, False), "找字库": ("dict", "字库", 1, False),
    "点字库": ("dict", "字库", 1, False), "等字库": ("dict", "字库", 1, False),
    "等字库消失": ("dict", "字库", 1, False),
}


def resource_argument_nodes(tree):
    """取得现行资源命令的路径表达式，禁止插件继承隐式资源。"""
    result = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_path(node.func)
        if name in RESOURCE_COMMAND_ARGUMENTS:
            kind, keyword_name, position, multiple = RESOURCE_COMMAND_ARGUMENTS[name]
            arguments = node.args[position:] if multiple else node.args[position:position + 1]
            arguments = list(arguments) + [keyword.value for keyword in node.keywords if keyword.arg == keyword_name]
            if not arguments and kind == "dict":
                arguments = [ast.copy_location(ast.Constant(value="ui.txt"), node)]
            result.extend((kind, argument.value if isinstance(argument, ast.Starred) else argument) for argument in arguments)
        if name == "组件.加载":
            values = {keyword.arg: keyword.value for keyword in node.keywords}
            kind_node = node.args[0] if node.args else values.get("类型")
            entry_node = node.args[1] if len(node.args) > 1 else values.get("入口")
            is_module = isinstance(kind_node, ast.Constant) and kind_node.value == "python" and isinstance(entry_node, ast.Constant) and isinstance(entry_node.value, str) and not entry_node.value.lower().endswith(".py")
            if entry_node is not None and not is_module:
                result.append(("component", entry_node))
    return result


def resource_literal_nodes(tree):
    def literals(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node]
        if isinstance(node, (ast.List, ast.Tuple)):
            return [value for item in node.elts for value in literals(item)]
        return []

    return [(kind, value) for kind, argument in resource_argument_nodes(tree) for value in literals(argument)]


def script_resource_references(source):
    """只识别现行资源命令的文字参数，不猜测普通文本或动态表达式。"""
    from task_workflow.script_sandbox import parse_script
    return list(dict.fromkeys((kind, node.value) for kind, node in resource_literal_nodes(parse_script(source))))
