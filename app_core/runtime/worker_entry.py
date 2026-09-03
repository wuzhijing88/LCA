# -*- coding: utf-8 -*-
"""Subprocess worker entry helpers."""

from __future__ import annotations

import importlib
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from utils.app_paths import get_app_root, is_packaged_runtime, resolve_running_executable

_PYTHON_LAUNCHER_NAMES = {"python.exe", "pythonw.exe", "py.exe", "pyw.exe"}
_DLL_DIRECTORY_HANDLES: List[Any] = []


@dataclass(frozen=True)
class StandaloneSubprocessSpec:
    flag: str
    module_name: str
    callable_name: str
    logger_name: str
    error_label: str
    log_level: int = logging.INFO
    log_format: str = "%(asctime)s - %(levelname)s - [pid=%(process)d] - [%(module)s:%(lineno)d] - %(message)s"
    configure_root_logging: bool = True
    args_factory: Optional[Callable[[Sequence[str]], Tuple[Any, ...]]] = None
    startup_hook: Optional[Callable[[logging.Logger, Sequence[str], Tuple[Any, ...]], None]] = None

    def __post_init__(self) -> None:
        if not str(self.flag or "").startswith("--"):
            raise ValueError("subprocess flag must start with '--'")
        if not str(self.callable_name or "").isidentifier():
            raise ValueError("subprocess callable_name must be a valid identifier")
        module_parts = str(self.module_name or "").split(".")
        if not module_parts or any(not part.isidentifier() for part in module_parts):
            raise ValueError("subprocess module_name must be a valid dotted module name")
        if not str(self.logger_name or "").strip():
            raise ValueError("subprocess logger_name cannot be empty")
        if not str(self.error_label or "").strip():
            raise ValueError("subprocess error_label cannot be empty")
        if isinstance(self.log_level, bool) or not isinstance(self.log_level, int):
            raise TypeError("subprocess log_level must be an integer")
        if not str(self.log_format or "").strip():
            raise ValueError("subprocess log_format cannot be empty")
        if not isinstance(self.configure_root_logging, bool):
            raise TypeError("subprocess configure_root_logging must be boolean")
        if self.args_factory is not None and not callable(self.args_factory):
            raise TypeError("subprocess args_factory must be callable")
        if self.startup_hook is not None and not callable(self.startup_hook):
            raise TypeError("subprocess startup_hook must be callable")


def _normalize_path(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _is_non_python_executable(path: str) -> bool:
    candidate = os.path.abspath(str(path or "").strip())
    if not candidate or not os.path.isfile(candidate):
        return False
    base_name = os.path.basename(candidate).lower()
    if base_name in _PYTHON_LAUNCHER_NAMES:
        return False
    if os.name != "nt" and base_name.startswith("python"):
        return False
    if os.name == "nt":
        return base_name.endswith(".exe")
    if candidate.lower().endswith((".py", ".pyw")):
        return False
    return os.access(candidate, os.X_OK)


def resolve_project_root(project_root: Optional[str] = None) -> str:
    root = str(project_root or "").strip()
    if root:
        return os.path.abspath(root)
    return get_app_root()


def resolve_project_venv_root(project_root: Optional[str] = None) -> str:
    return os.path.join(resolve_project_root(project_root), "venv")


def resolve_project_venv_scripts_dir(project_root: Optional[str] = None) -> str:
    venv_root = resolve_project_venv_root(project_root)
    if os.name == "nt":
        return os.path.join(venv_root, "Scripts")
    return os.path.join(venv_root, "bin")


def resolve_project_site_packages_dir(project_root: Optional[str] = None) -> str:
    venv_root = resolve_project_venv_root(project_root)
    if os.name == "nt":
        return os.path.join(venv_root, "Lib", "site-packages")
    version_dir = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return os.path.join(venv_root, "lib", version_dir, "site-packages")


def _prepend_path_once(current_value: Optional[str], new_entry: Optional[str]) -> str:
    normalized_new_entry = str(new_entry or "").strip()
    if not normalized_new_entry:
        return str(current_value or "")

    existing_parts = [
        entry
        for entry in str(current_value or "").split(os.pathsep)
        if str(entry or "").strip()
    ]
    normalized_existing = {
        _normalize_path(entry)
        for entry in existing_parts
    }
    if _normalize_path(normalized_new_entry) not in normalized_existing:
        existing_parts.insert(0, normalized_new_entry)
    return os.pathsep.join(existing_parts)


def resolve_project_python_executable(
    project_root: Optional[str] = None,
    *,
    prefer_windowed: Optional[bool] = None,
) -> str:
    scripts_dir = resolve_project_venv_scripts_dir(project_root)
    if os.name == "nt":
        if prefer_windowed is None:
            prefer_windowed = os.path.basename(str(sys.executable or "")).lower() == "pythonw.exe"
        candidate_name = "pythonw.exe" if prefer_windowed else "python.exe"
    else:
        candidate_name = "python"

    project_python = os.path.join(scripts_dir, candidate_name)
    if os.path.isfile(project_python):
        return project_python
    raise FileNotFoundError(f"project Python executable not found: {project_python}")


def build_worker_process_env(
    base_env: Optional[Mapping[str, str]] = None,
    *,
    project_root: Optional[str] = None,
) -> Dict[str, str]:
    resolved_project_root = resolve_project_root(project_root)
    env = dict(base_env) if base_env is not None else os.environ.copy()
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in env.items()):
        raise TypeError("worker environment keys and values must be strings")

    env["PYTHONPATH"] = _prepend_path_once(env.get("PYTHONPATH"), resolved_project_root)

    venv_root = resolve_project_venv_root(resolved_project_root)
    if not is_packaged_runtime():
        scripts_dir = resolve_project_venv_scripts_dir(resolved_project_root)
        if not os.path.isdir(venv_root) or not os.path.isdir(scripts_dir):
            raise FileNotFoundError(f"project virtual environment is incomplete: {venv_root}")
        env["VIRTUAL_ENV"] = venv_root
        env["PATH"] = _prepend_path_once(env.get("PATH"), scripts_dir)

    try:
        from utils.plugin.runtime import plugin_attach_env

        env.update(plugin_attach_env())
    except Exception:
        pass
    return env


def bootstrap_current_process_virtual_environment(
    *,
    project_root: Optional[str] = None,
    runtime_label: str = "子进程",
    logger: Optional[Any] = None,
) -> Dict[str, str]:
    resolved_project_root = resolve_project_root(project_root)
    venv_root = resolve_project_venv_root(resolved_project_root)
    scripts_dir = resolve_project_venv_scripts_dir(resolved_project_root)
    site_packages = resolve_project_site_packages_dir(resolved_project_root)

    if not is_packaged_runtime():
        missing_paths = [
            path
            for path in (venv_root, scripts_dir, site_packages)
            if not os.path.isdir(path)
        ]
        if missing_paths:
            raise FileNotFoundError(
                "project virtual environment is incomplete: " + ", ".join(missing_paths)
            )

    normalized_sys_paths = {
        _normalize_path(entry)
        for entry in sys.path
        if str(entry or "").strip()
    }
    normalized_project_root = _normalize_path(resolved_project_root)
    if normalized_project_root not in normalized_sys_paths:
        sys.path.insert(0, resolved_project_root)
        normalized_sys_paths.add(normalized_project_root)

    if os.path.isdir(site_packages):
        normalized_site_packages = _normalize_path(site_packages)
        if normalized_site_packages not in normalized_sys_paths:
            sys.path.insert(0, site_packages)

    if os.path.isdir(scripts_dir):
        os.environ["PATH"] = _prepend_path_once(os.environ.get("PATH"), scripts_dir)
        os.environ["VIRTUAL_ENV"] = venv_root

        if hasattr(os, "add_dll_directory"):
            dll_dirs = (
                scripts_dir,
                os.path.join(site_packages, "onnxruntime", "capi"),
            )
            for dll_dir in dll_dirs:
                if not os.path.isdir(dll_dir):
                    continue
                handle = os.add_dll_directory(dll_dir)
                _DLL_DIRECTORY_HANDLES.append(handle)

    if logger is not None:
        logger.info(
            "%s虚拟环境已就绪: executable=%s, prefix=%s, venv=%s",
            runtime_label,
            sys.executable,
            sys.prefix,
            venv_root,
        )

    return {
        "project_root": resolved_project_root,
        "venv_root": venv_root,
        "scripts_dir": scripts_dir,
        "site_packages": site_packages,
    }


def _is_running_inside_virtual_environment() -> bool:
    return bool(hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix)


def ensure_project_main_runtime(
    *,
    entry_file: str,
    argv: Optional[Sequence[str]] = None,
    project_root: Optional[str] = None,
    relaunch_env_name: str = "LCA_VENV_RELAUNCHED",
    runtime_label: str = "主进程",
    logger: Optional[Any] = None,
) -> bool:
    if bool(getattr(sys, "frozen", False)):
        return True

    resolved_project_root = resolve_project_root(
        project_root or os.path.dirname(os.path.abspath(entry_file))
    )
    target_python = resolve_project_python_executable(
        resolved_project_root,
        prefer_windowed=None,
    )

    current_executable = _normalize_path(str(sys.executable or ""))
    target_executable = _normalize_path(target_python)
    if current_executable != target_executable:
        if os.environ.get(relaunch_env_name) == "1":
            raise RuntimeError(
                f"virtual environment relaunch did not switch Python: {target_python}"
            )
        relaunch_args = [
            target_python,
            os.path.abspath(entry_file),
            *(list(argv) if argv is not None else sys.argv[1:]),
        ]
        os.environ[relaunch_env_name] = "1"
        if logger is not None:
            logger.warning("%s relaunch with project Python: %s", runtime_label, target_python)
        try:
            os.execv(target_python, relaunch_args)
        except Exception as exc:
            raise RuntimeError(
                f"failed to relaunch with project Python: {target_python}"
            ) from exc

    if _is_running_inside_virtual_environment():
        if logger is not None:
            logger.info("%s已在虚拟环境中运行: %s", runtime_label, sys.prefix)
        return True

    bootstrap_current_process_virtual_environment(
        project_root=resolved_project_root,
        runtime_label=runtime_label,
        logger=logger,
    )
    return True


def resolve_main_executable() -> Optional[str]:
    """Return the running packaged exe, not Nuitka's compile-time sys.executable."""
    executable = str(resolve_running_executable() or "").strip()
    if executable and _is_non_python_executable(executable):
        return executable
    return None


def build_worker_launch_command(
    worker_flag: str,
    module_name: str,
    standalone_flag: str,
    extra_args: Optional[Sequence[str]] = None,
    *,
    python_executable: Optional[str] = None,
    project_root: Optional[str] = None,
) -> List[str]:
    flag = str(worker_flag or '').strip()
    module = str(module_name or '').strip()
    standalone = str(standalone_flag or '').strip()
    if not flag.startswith("--"):
        raise ValueError("worker_flag must start with '--'")
    if not module or any(not part.isidentifier() for part in module.split(".")):
        raise ValueError("module_name must be a valid dotted module name")
    if not standalone.startswith("--"):
        raise ValueError("standalone_flag must start with '--'")

    if extra_args and any(arg is None for arg in extra_args):
        raise ValueError("worker extra_args cannot contain None")
    resolved_extra_args = [str(arg) for arg in (extra_args or ())]

    if is_packaged_runtime():
        executable = resolve_main_executable()
        if not executable:
            raise FileNotFoundError(
                "packaged main executable not found: "
                f"sys.executable={sys.executable!r} argv0={sys.argv[0]!r}"
            )
        return [executable, flag, *resolved_extra_args]

    resolved_python = str(python_executable or "").strip()
    if not resolved_python:
        resolved_python = str(
            resolve_project_python_executable(project_root=project_root) or ""
        ).strip()
    if not resolved_python:
        raise FileNotFoundError("project Python executable not found")
    executable = os.path.abspath(resolved_python)
    if not os.path.isfile(executable):
        raise FileNotFoundError(executable)
    if _is_non_python_executable(executable):
        raise ValueError(f"worker executable is not Python: {executable}")

    return [executable, '-m', module, standalone, *resolved_extra_args]


def get_cli_argument_value(
    argv: Optional[Sequence[str]],
    flag: str,
    default: str = "",
) -> str:
    args = [str(arg) for arg in (argv or ())]
    target_flag = str(flag or "").strip()
    if not target_flag:
        raise ValueError("CLI flag cannot be empty")

    matching_indexes = [index for index, arg in enumerate(args) if arg == target_flag]
    if len(matching_indexes) > 1:
        raise ValueError(f"CLI flag was provided more than once: {target_flag}")
    if matching_indexes:
        index = matching_indexes[0]
        if index + 1 >= len(args):
            raise ValueError(f"CLI flag requires a value: {target_flag}")
        return str(args[index + 1])
    return str(default)


def get_cli_int_argument_value(
    argv: Optional[Sequence[str]],
    flag: str,
    default: int = 0,
) -> int:
    raw_value = get_cli_argument_value(argv, flag, str(int(default)))
    try:
        return int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"CLI flag requires an integer: {flag}={raw_value!r}") from exc


def find_standalone_subprocess_spec(
    argv: Optional[Sequence[str]],
    specs: Iterable[StandaloneSubprocessSpec],
) -> Optional[StandaloneSubprocessSpec]:
    spec_list = tuple(specs)
    flags = [str(spec.flag).strip() for spec in spec_list]
    if len(flags) != len(set(flags)):
        raise ValueError("standalone subprocess flags must be unique")

    arg_list = [str(arg) for arg in (argv or ())]
    args = set(arg_list)
    matches = [spec for spec in spec_list if spec.flag in args]
    if len(matches) > 1:
        raise ValueError(
            "multiple standalone subprocess flags were provided: "
            + ", ".join(spec.flag for spec in matches)
        )
    if matches and arg_list.count(matches[0].flag) > 1:
        raise ValueError(f"standalone subprocess flag was provided more than once: {matches[0].flag}")
    return matches[0] if matches else None


def is_standalone_subprocess_active(
    argv: Optional[Sequence[str]],
    specs: Iterable[StandaloneSubprocessSpec],
) -> bool:
    return find_standalone_subprocess_spec(argv, specs) is not None


def run_standalone_subprocess(
    argv: Optional[Sequence[str]],
    specs: Iterable[StandaloneSubprocessSpec],
) -> Optional[int]:
    spec = find_standalone_subprocess_spec(argv, specs)
    if spec is None:
        return None

    if bool(spec.configure_root_logging):
        logging.basicConfig(
            level=int(spec.log_level),
            format=str(spec.log_format),
        )
    logger = logging.getLogger(str(spec.logger_name or __name__))
    raw_args = spec.args_factory(argv or ()) if spec.args_factory is not None else ()
    args = tuple(raw_args or ())

    if spec.startup_hook is not None:
        spec.startup_hook(logger, tuple(argv or ()), args)

    module = importlib.import_module(str(spec.module_name))
    runner = getattr(module, str(spec.callable_name))
    if not callable(runner):
        raise TypeError(
            f"subprocess entry is not callable: {spec.module_name}.{spec.callable_name}"
        )
    result = runner(*args)
    if result is None:
        return 0
    if isinstance(result, bool) or not isinstance(result, int):
        raise TypeError("subprocess entry must return int or None")
    if result < 0 or result > 255:
        raise ValueError(f"subprocess exit code out of range: {result}")
    return result
