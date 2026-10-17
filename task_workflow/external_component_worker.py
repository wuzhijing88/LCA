# -*- coding: utf-8 -*-
"""Isolated host for external process, Python, COM, and native DLL components."""

from __future__ import annotations

import argparse
import ctypes
import importlib
import importlib.util
import os
import socket
import struct
import subprocess
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from services.socket_message_utils import recv_message_with_status, send_message


class ExternalComponentWorkerError(RuntimeError):
    pass


_COMPONENT_TYPES = {"process", "python", "com", "dll"}

_CTYPES = {
    "void": None,
    "bool": ctypes.c_bool,
    "int8": ctypes.c_int8,
    "uint8": ctypes.c_uint8,
    "int16": ctypes.c_int16,
    "uint16": ctypes.c_uint16,
    "int32": ctypes.c_int32,
    "uint32": ctypes.c_uint32,
    "long": ctypes.c_long,
    "ulong": ctypes.c_ulong,
    "int64": ctypes.c_int64,
    "uint64": ctypes.c_uint64,
    "float": ctypes.c_float,
    "double": ctypes.c_double,
    "str": ctypes.c_char_p,
    "wstr": ctypes.c_wchar_p,
    "bytes": ctypes.c_char_p,
    "ptr": ctypes.c_void_p,
    "handle": ctypes.c_void_p,
    "size_t": ctypes.c_size_t,
    "ssize_t": ctypes.c_ssize_t,
}


def normalize_component_type(value: Any) -> str:
    key = str(value or "").strip().lower()
    if key not in _COMPONENT_TYPES:
        raise ExternalComponentWorkerError(f"不支持的组件类型: {value}")
    return key


def resolve_ctype(value: Any, *, allow_void: bool = True):
    key = str(value).strip().lower()
    if key not in _CTYPES:
        raise ExternalComponentWorkerError(f"不支持的 DLL 类型: {value}")
    resolved = _CTYPES[key]
    if resolved is None and not allow_void:
        raise ExternalComponentWorkerError("DLL 参数类型不能是 void")
    return resolved


def parse_arg_types(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        if not all(parts):
            raise ExternalComponentWorkerError("参数类型不能包含空项")
        return parts
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value]
    raise ExternalComponentWorkerError("参数类型请写成列表或逗号分隔文字")


def _convert_dll_arg(value: Any, type_name: str) -> Any:
    ctype = resolve_ctype(type_name, allow_void=False)
    if ctype is ctypes.c_char_p:
        if value is None:
            return None
        return value if isinstance(value, bytes) else str(value).encode("utf-8")
    if ctype is ctypes.c_wchar_p:
        return None if value is None else str(value)
    if ctype is ctypes.c_void_p:
        return None if value is None else int(value)
    return value


def _resolve_member(root: Any, member: str) -> tuple[Any, str]:
    parts = [part for part in str(member or "").split(".") if part]
    if not parts:
        raise ExternalComponentWorkerError("缺少方法名")
    owner = root
    for part in parts[:-1]:
        if part.startswith("_"):
            raise ExternalComponentWorkerError("方法名不能以下划线开头")
        owner = getattr(owner, part)
    name = parts[-1]
    if name.startswith("_"):
        raise ExternalComponentWorkerError("方法名不能以下划线开头")
    return owner, name


def _pe_architecture(path: str) -> str:
    try:
        with open(path, "rb") as handle:
            header = handle.read(64)
            if len(header) < 64 or header[:2] != b"MZ":
                return ""
            handle.seek(struct.unpack_from("<I", header, 60)[0])
            signature = handle.read(6)
            if len(signature) < 6 or signature[:4] != b"PE\0\0":
                return ""
            machine = struct.unpack_from("<H", signature, 4)[0]
    except OSError:
        return ""
    return {0x014C: "x86", 0x8664: "x64", 0xAA64: "arm64"}.get(machine, hex(machine))


def normalize_result(value: Any, *, _seen: Optional[set[int]] = None) -> Any:
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    if isinstance(value, Path):
        return str(value)
    seen = _seen if _seen is not None else set()
    identity = id(value)
    if identity in seen:
        return repr(value)
    seen.add(identity)
    if isinstance(value, dict):
        result = {str(key): normalize_result(item, _seen=seen) for key, item in value.items()}
        seen.remove(identity)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        result = [normalize_result(item, _seen=seen) for item in value]
        seen.remove(identity)
        return result
    if hasattr(value, "value"):
        try:
            result = normalize_result(value.value, _seen=seen)
            seen.remove(identity)
            return result
        except Exception:
            pass
    seen.remove(identity)
    return repr(value)


class ComponentRegistry:
    def __init__(self) -> None:
        self._components: Dict[str, Dict[str, Any]] = {}

    def load(self, kind: Any, target: Any, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        component_type = normalize_component_type(kind)
        entry = str(target or "").strip()
        if not entry:
            raise ExternalComponentWorkerError("缺少组件入口")
        settings = dict(options or {})
        component: Any
        allowed = {"calling_convention"} if component_type == "dll" else set()
        if set(settings).difference(allowed):
            raise ExternalComponentWorkerError("调用约定只适用于 DLL 组件")

        if component_type == "process":
            component = entry
        elif component_type == "python":
            if os.path.isfile(entry):
                module_name = f"lca_external_{uuid.uuid4().hex}"
                spec = importlib.util.spec_from_file_location(module_name, entry)
                if spec is None or spec.loader is None:
                    raise ExternalComponentWorkerError(f"无法加载 Python 文件: {entry}")
                component = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = component
                try:
                    spec.loader.exec_module(component)
                except BaseException:
                    sys.modules.pop(module_name, None)
                    raise
                settings["module_name"] = module_name
            else:
                component = importlib.import_module(entry)
        elif component_type == "com":
            if os.name != "nt":
                raise ExternalComponentWorkerError("COM 组件仅支持 Windows")
            try:
                import win32com.client

                component = win32com.client.Dispatch(entry)
            except Exception as exc:
                raise ExternalComponentWorkerError(f"COM 组件加载失败: {exc}") from exc
        else:
            absolute_entry = os.path.abspath(entry)
            file_entry = absolute_entry if os.path.isfile(absolute_entry) else ""
            load_entry = file_entry or entry
            architecture = _pe_architecture(file_entry) if file_entry else ""
            host_architecture = "x64" if ctypes.sizeof(ctypes.c_void_p) == 8 else "x86"
            if architecture and architecture != host_architecture:
                raise ExternalComponentWorkerError(
                    f"DLL 位数不匹配: 组件={architecture}，当前宿主={host_architecture}；请使用对应位数的组件宿主"
                )
            convention = str(settings.get("calling_convention", "cdecl")).strip().lower()
            if convention not in {"cdecl", "stdcall"}:
                raise ExternalComponentWorkerError(f"不支持的调用约定: {convention}")
            dll_directory = None
            if file_entry and os.name == "nt" and callable(getattr(os, "add_dll_directory", None)):
                dll_directory = os.add_dll_directory(os.path.dirname(file_entry))
            try:
                if convention == "stdcall":
                    if os.name != "nt":
                        raise ExternalComponentWorkerError("stdcall DLL 仅支持 Windows")
                    component = ctypes.WinDLL(load_entry, use_last_error=True)
                else:
                    component = ctypes.CDLL(load_entry, use_errno=True)
            except BaseException:
                if dll_directory is not None:
                    dll_directory.close()
                raise
            settings["calling_convention"] = convention
            settings["dll_directory"] = dll_directory

        handle = uuid.uuid4().hex
        self._components[handle] = {
            "type": component_type,
            "target": entry,
            "object": component,
            "options": settings,
        }
        return {"handle": handle, "type": component_type, "target": entry}

    def _get(self, handle: Any) -> Dict[str, Any]:
        key = str(handle or "").strip()
        component = self._components.get(key)
        if component is None:
            raise ExternalComponentWorkerError("组件句柄不存在或已经关闭")
        return component

    def call(
        self,
        handle: Any,
        member: Any,
        args: Any = None,
        kwargs: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Any:
        component = self._get(handle)
        component_type = component["type"]
        values = list(args or [])
        named = dict(kwargs or {})
        settings = dict(options or {})

        action = str(settings.get("action", "call")).strip().lower()
        if action not in {"call", "get", "set"}:
            raise ExternalComponentWorkerError(f"不支持的调用动作: {action}")
        if action != "call" and component_type not in {"python", "com"}:
            raise ExternalComponentWorkerError("属性读取和写入只支持 Python 或 COM 组件")
        allowed = {"action", "call_timeout"}
        if component_type == "process":
            allowed.update({"process_timeout", "stdin", "cwd", "env", "encoding"})
            if str(member or "").strip() or named:
                raise ExternalComponentWorkerError("进程组件不支持方法名或关键字参数")
        elif component_type == "dll":
            allowed.update({"arg_types", "return_type"})
            if named:
                raise ExternalComponentWorkerError("DLL 组件不支持关键字参数")
        unsupported = sorted(set(settings).difference(allowed))
        if unsupported:
            raise ExternalComponentWorkerError(f"{component_type} 组件不支持选项: {'、'.join(unsupported)}")

        if component_type == "process":
            return self._run_process(component["object"], values, settings)
        if component_type == "dll":
            owner, name = _resolve_member(component["object"], str(member or ""))
            function = getattr(owner, name)
            arg_type_names = parse_arg_types(settings.get("arg_types"))
            if len(arg_type_names) != len(values):
                raise ExternalComponentWorkerError(
                    f"DLL 参数数量与参数类型不一致: {len(values)} != {len(arg_type_names)}"
                )
            function.argtypes = [resolve_ctype(item, allow_void=False) for item in arg_type_names]
            function.restype = resolve_ctype(settings.get("return_type", "int32"))
            converted = [_convert_dll_arg(value, arg_type_names[index]) for index, value in enumerate(values)]
            return function(*converted)

        owner, name = _resolve_member(component["object"], str(member or ""))
        if action == "get":
            if values or named:
                raise ExternalComponentWorkerError("读取属性时不能传入参数")
            return getattr(owner, name)
        if action == "set":
            if len(values) != 1 or named:
                raise ExternalComponentWorkerError("写入属性需要且只能提供一个值")
            setattr(owner, name, values[0])
            return values[0]
        if action != "call":
            raise ExternalComponentWorkerError(f"不支持的调用动作: {action}")
        callable_obj = getattr(owner, name)
        if not callable(callable_obj):
            raise ExternalComponentWorkerError(f"组件成员不可调用: {member}")
        return callable_obj(*values, **named)

    def _run_process(self, executable: str, args: list[Any], settings: Dict[str, Any]) -> Dict[str, Any]:
        command = [str(executable), *(str(item) for item in args)]
        cwd = str(settings.get("cwd") or "").strip() or None
        stdin_value = settings.get("stdin")
        input_text = None if stdin_value is None else str(stdin_value)
        env_updates = settings.get("env")
        env = None
        if env_updates is not None:
            if not isinstance(env_updates, dict):
                raise ExternalComponentWorkerError("进程环境变量必须是字典")
            env = os.environ.copy()
            env.update({str(key): str(value) for key, value in env_updates.items()})
        encoding = str(settings.get("encoding", "utf-8"))
        import codecs

        codecs.lookup(encoding)
        from task_workflow.script_parameters import finite_seconds

        timeout = finite_seconds(settings.get("process_timeout", settings.get("call_timeout", 30.0)), "进程超时", positive=True)
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding=encoding,
            errors="replace",
            shell=False,
            creationflags=creation_flags,
        )
        try:
            stdout, stderr = process.communicate(input=input_text, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            from app_core.runtime.process_tree import terminate_process_tree

            terminate_process_tree(process, wait_timeout=2.0, force=True)
            raise ExternalComponentWorkerError(f"外部进程执行超时: {timeout:g} 秒") from exc
        except BaseException:
            from app_core.runtime.process_tree import terminate_process_tree

            terminate_process_tree(process, wait_timeout=2.0, force=True)
            raise
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        return {
            "exit_code": int(process.returncode or 0),
            "stdout": str(stdout or ""),
            "stderr": str(stderr or ""),
            "pid": int(process.pid or 0),
        }

    def close(self, handle: Any = None) -> int:
        if handle is None or str(handle or "").strip() == "":
            count = len(self._components)
            components = list(self._components.values())
            self._components.clear()
            errors = []
            for component in components:
                try:
                    self._release_component(component)
                except Exception as exc:
                    errors.append(str(exc))
            if errors:
                raise ExternalComponentWorkerError("组件释放失败：" + "；".join(errors))
            return count
        key = str(handle).strip()
        component = self._components.pop(key, None)
        if component is None:
            raise ExternalComponentWorkerError("组件句柄不存在或已经关闭")
        self._release_component(component)
        return 1

    @staticmethod
    def _release_component(component: Dict[str, Any]) -> None:
        options = component.get("options", {})
        module_name = options.get("module_name")
        if module_name:
            sys.modules.pop(module_name, None)
        instance = component.pop("object")
        directory = options.get("dll_directory")
        try:
            if component["type"] == "dll":
                import _ctypes

                if os.name == "nt":
                    _ctypes.FreeLibrary(instance._handle)
                else:
                    _ctypes.dlclose(instance._handle)
                instance._handle = 0
        finally:
            if directory is not None:
                directory.close()


def _response(request_id: Any, *, success: bool, **payload: Any) -> Dict[str, Any]:
    return {"type": "response", "request_id": request_id, "success": bool(success), **payload}


def run_external_component_worker_standalone(port: int, token: str) -> int:
    if int(port or 0) <= 0 or not str(token or ""):
        return 2
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    registry = ComponentRegistry()
    try:
        sock.connect(("127.0.0.1", int(port)))
        if not send_message(sock, {"type": "ready", "token": str(token), "pid": os.getpid()}):
            return 3
        while True:
            message, status = recv_message_with_status(sock, timeout=60.0, max_message_bytes=0xFFFFFFFF)
            if status == "timeout":
                continue
            if status != "ok" or message is None:
                return 0 if status == "closed" else 6
            request_id = message.get("request_id")
            if str(message.get("token") or "") != str(token):
                send_message(sock, _response(request_id, success=False, error="身份校验失败"))
                return 4
            command = str(message.get("command") or "").strip().upper()
            try:
                if command == "PING":
                    result = {"pid": os.getpid()}
                elif command == "LOAD":
                    result = registry.load(message.get("component_type"), message.get("target"), message.get("options"))
                elif command == "CALL":
                    result = registry.call(
                        message.get("handle"),
                        message.get("member"),
                        message.get("args"),
                        message.get("kwargs"),
                        message.get("options"),
                    )
                elif command == "CLOSE":
                    result = registry.close(message.get("handle"))
                elif command == "SHUTDOWN":
                    registry.close()
                    send_message(sock, _response(request_id, success=True, result=True))
                    return 0
                else:
                    raise ExternalComponentWorkerError(f"未知组件宿主命令: {command}")
                if not send_message(sock, _response(request_id, success=True, result=normalize_result(result))):
                    return 5
            except BaseException as exc:
                error = str(exc) or exc.__class__.__name__
                details = "".join(traceback.format_exception_only(type(exc), exc)).strip()
                if not send_message(sock, _response(request_id, success=False, error=error, details=details)):
                    return 5
    finally:
        try:
            registry.close()
        finally:
            sock.close()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="LCA external component worker")
    parser.add_argument("--external-component-worker-standalone", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", default="")
    args = parser.parse_args(argv)
    if not args.external_component_worker_standalone:
        return 1
    return run_external_component_worker_standalone(args.port, args.token)


if __name__ == "__main__":
    raise SystemExit(main())
