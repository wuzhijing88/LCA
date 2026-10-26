"""每次脚本卡片执行独享的参数、输出和临时资源。"""
from __future__ import annotations

import copy
import json
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import threading

from app_core.card_plugins import (
    BUNDLE_PARAMETER, CardPluginError, MAX_CONTENT_BYTES, RESOURCE_FOLDERS, package_member,
    input_parameter_key, validate_value,
)


_ACTIVE_INVOCATION = ContextVar("lca_card_plugin_invocation", default=None)


@contextmanager
def plugin_execution_scope(invocation):
    token = _ACTIVE_INVOCATION.set(invocation)
    try:
        yield
    finally:
        _ACTIVE_INVOCATION.reset(token)


def register_owned_resource(path, label, cleanup):
    invocation = _ACTIVE_INVOCATION.get()
    if invocation is None:
        return
    candidate = Path(path)
    if candidate.is_absolute() and candidate.resolve().is_relative_to(invocation.root):
        invocation.register_cleanup(label, cleanup)



def resolve_input_file(value, kind, resource_dirs):
    if not isinstance(value, str) or not value:
        raise CardPluginError("文件参数必须提供路径")
    target = Path(value)
    if not target.is_absolute():
        folder, directory_key = RESOURCE_FOLDERS[kind]
        normalized = package_member(value)
        prefix = f"assets/{folder}/"
        plain_prefix = "plugins/" if kind == "component" else f"{folder}/"
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
        elif normalized.startswith(plain_prefix):
            normalized = normalized[len(plain_prefix):]
        root = resource_dirs.get(directory_key)
        if not isinstance(root, str) or not root:
            raise CardPluginError(f"文件参数缺少绑定的资源目录：{folder}")
        root = Path(root).resolve()
        target = (root / normalized).resolve()
        if not target.is_relative_to(root):
            raise CardPluginError("文件参数超出了所绑定的资源目录")
    if not target.is_file():
        raise CardPluginError(f"文件参数指向的文件不存在：{value}")
    return str(target.resolve())


def read_bound_resource(value, kind, resource_dirs, *, package_session=None, files=None, limit=MAX_CONTENT_BYTES):
    """依据明确的资源所有者读取文件；找不到时不转向其他来源。"""
    if not isinstance(value, str) or not value:
        raise CardPluginError("资源文件路径不能为空")
    if Path(value).is_absolute():
        target = Path(resolve_input_file(value, kind, resource_dirs))
    elif package_session is not None or files is not None:
        normalized = value[len("memory://"):] if value.startswith("memory://") else value
        folder = RESOURCE_FOLDERS[kind][0]
        script_folder = "plugins" if kind == "component" else folder
        if normalized.startswith(f"assets/{folder}/"):
            member = package_member(normalized)
        elif normalized.startswith(f"{script_folder}/"):
            member = package_member(f"assets/{folder}/" + normalized[len(script_folder) + 1:])
        else:
            member = package_member(f"assets/{folder}/" + normalized)
        data = package_session.get_bytes(member) if package_session is not None else files.get(member)
        if not isinstance(data, bytes):
            raise CardPluginError(f"当前资源包中不存在文件：{value}")
        if len(data) > limit:
            raise CardPluginError("资源文件超过本次执行的容量上限")
        return data
    else:
        target = Path(resolve_input_file(value, kind, resource_dirs))
    try:
        if target.stat().st_size > limit:
            raise CardPluginError("资源文件超过本次执行的容量上限")
        before = target.stat()
        with target.open("rb") as handle:
            data = handle.read(limit + 1)
        after = target.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise CardPluginError("资源文件在读取期间发生变化，请重试")
        if len(data) > limit:
            raise CardPluginError("资源文件读取期间超过容量上限")
        return data
    except OSError as exc:
        raise CardPluginError(f"无法读取资源文件：{value}") from exc


class CardPluginInvocation:
    def __init__(self, bundle, parameters, root, resource_dirs, *, package_session=None, files=None):
        definitions = bundle.manifest["parameters"]
        if set(parameters) != {BUNDLE_PARAMETER, *(input_parameter_key(name) for name in definitions)}:
            raise CardPluginError("脚本卡片参数缺失或包含未声明的参数")
        self._lock = threading.RLock()
        self._closed = False
        self._cleanups = {}
        self._outputs = {}
        self._output_definitions = copy.deepcopy(bundle.manifest["outputs"])
        self._manifest_parameters = copy.deepcopy(bundle.manifest["parameters"])
        from app_core.card_plugin_conditions import validate_inputs, values_from_parameters
        values, self._parameter_states = validate_inputs(definitions, values_from_parameters(definitions, parameters))
        self._parameters = {}
        self.resource_dirs = {}
        self._resource_paths = {}
        root = Path(root).resolve()
        self.root = root
        for _, (folder, directory_key) in RESOURCE_FOLDERS.items():
            directory = root / "assets" / folder
            directory.mkdir(parents=True, exist_ok=True)
            self.resource_dirs[directory_key] = str(directory)
        total_bytes = 0
        for index, (key, definition) in enumerate(definitions.items()):
            value = values[key]
            if self._parameter_states[key].active and definition["type"] == "file" and value:
                kind = definition["resource_kind"]
                data = read_bound_resource(value, kind, resource_dirs, package_session=package_session, files=files, limit=MAX_CONTENT_BYTES - total_bytes)
                total_bytes += len(data)
                filename = Path(value.replace("\\", "/")).name
                if not filename:
                    raise CardPluginError("插件输入文件缺少文件名")
                destination = root / "inputs" / str(index) / filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                value = str(destination)
                self._resource_paths[destination.resolve()] = kind
            self._parameters[key] = value

    def require_resource(self, kind, value):
        with self._lock:
            self._check_open()
            if isinstance(value, (list, tuple)) and value:
                for item in value:
                    self.require_resource(kind, item)
                return value
            if not isinstance(value, str) or not value or self._resource_paths.get(Path(value).resolve()) != kind:
                raise CardPluginError("插件资源必须来自对应类型的文件参数，不能使用文本参数或未传入的路径")
            return value

    def register_cleanup(self, label, cleanup):
        with self._lock:
            self._check_open()
            if label not in self._cleanups and len(self._cleanups) >= 8:
                raise CardPluginError("插件运行资源种类超过上限")
            self._cleanups[label] = cleanup

    def declare(self, kind, name):
        with self._lock:
            self._check_open()
            definitions = self._output_definitions if kind == "输出" else self._manifest_parameters
            if name not in definitions:
                raise CardPluginError(f"未声明的插件{kind}：{name}")
            return True

    def _check_open(self):
        if self._closed:
            raise CardPluginError("脚本卡片执行上下文已关闭")

    def parameter(self, name):
        with self._lock:
            self._check_open()
            if not isinstance(name, str) or name not in self._parameters:
                raise CardPluginError(f"未声明的脚本卡片参数：{name}")
            if self._parameter_states[name].active is not True:
                raise CardPluginError(f"插件参数当前不可用：{name}，请先满足显示和启用条件")
            return copy.deepcopy(self._parameters[name])

    def set_output(self, name, value):
        with self._lock:
            self._check_open()
            if not isinstance(name, str) or name not in self._output_definitions:
                raise CardPluginError(f"未声明的脚本卡片输出：{name}")
            result = validate_value(value, self._output_definitions[name], f"输出 {name}", output=True)
            from task_workflow.runtime_store import normalize_var_value
            candidate = normalize_var_value({**self._outputs, name: result})
            try:
                size = 0
                for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False).iterencode(candidate):
                    size += len(chunk.encode("utf-8"))
                    if size > 256 * 1024:
                        raise CardPluginError("脚本卡片输出总量不能超过 256 KB")
            except CardPluginError:
                raise
            except (TypeError, ValueError, OverflowError) as exc:
                raise CardPluginError("脚本卡片输出不能序列化或超过容量上限") from exc
            self._outputs = candidate
            return copy.deepcopy(result)

    def finish(self):
        with self._lock:
            self._check_open()
            missing = [name for name, definition in self._output_definitions.items() if definition["required"] and name not in self._outputs]
            if missing:
                raise CardPluginError("脚本卡片未提供必填输出：" + "、".join(missing))
            return copy.deepcopy(self._outputs)

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            cleanups = list(self._cleanups.items())
            self._cleanups.clear()
            self._parameters.clear()
            self._outputs.clear()
            self._output_definitions.clear()
            self._manifest_parameters.clear()
            self._parameter_states.clear()
            self.resource_dirs.clear()
            self._resource_paths.clear()
        errors = []
        for label, cleanup in reversed(cleanups):
            try:
                cleanup(self.root)
            except Exception as exc:
                errors.append(f"{label}：{exc}")
        if errors:
            raise CardPluginError("插件资源未能全部释放：" + "；".join(errors))


def guard_resource_command(callback, invocation, kind, parameter, *, more_parameter=None, component=False):
    from functools import wraps
    import inspect

    signature = inspect.signature(callback)

    @wraps(callback)
    def guarded(*args, **kwargs):
        arguments = signature.bind(*args, **kwargs).arguments
        value = arguments.get(parameter)
        if component and arguments.get("类型") == "python" and isinstance(value, str) and not value.lower().endswith(".py"):
            return callback(*args, **kwargs)
        invocation.require_resource(kind, value)
        if more_parameter is not None:
            for extra in arguments.get(more_parameter, ()):
                invocation.require_resource(kind, extra)
        return callback(*args, **kwargs)

    return guarded


class PluginParameterView:
    def __init__(self, invocation):
        self._invocation = invocation

    def 声明(self, 名字, *, 类型, 默认=None, 必填=True, 最小=None, 最大=None, 步长=None, 小数位=None, 选项=None, 说明="", 工具=None):
        if self._invocation is None:
            raise CardPluginError("参数.声明只能在插件模式中使用")
        return self._invocation.declare("参数", 名字)

    def 获取(self, 名字):
        if self._invocation is None:
            raise CardPluginError("参数.获取只能在脚本卡片中使用，请先声明卡片参数")
        return self._invocation.parameter(名字)


class PluginOutputView:
    def __init__(self, invocation):
        self._invocation = invocation

    def 声明(self, 名字, *, 类型, 必填=True, 说明=""):
        if self._invocation is None:
            raise CardPluginError("输出.声明只能在插件模式中使用")
        return self._invocation.declare("输出", 名字)

    def 设置(self, 名字, 值):
        if self._invocation is None:
            raise CardPluginError("输出.设置只能在脚本卡片中使用，请先声明卡片输出")
        return self._invocation.set_output(名字, 值)
