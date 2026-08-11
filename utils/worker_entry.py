# -*- coding: utf-8 -*-
"""Subprocess worker entry helpers."""

from __future__ import annotations

import importlib
import logging
import os
import sys
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

_PYTHON_LAUNCHER_NAMES = {"python.exe", "pythonw.exe", "py.exe", "pyw.exe"}


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


def _normalize_path(path: str) -> str:
    try:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))
    except Exception:
        return os.path.normcase(os.path.abspath(path))


def _append_candidate(candidates: List[str], value: Optional[str]) -> None:
    text = str(value or "").strip()
    if not text:
        return
    path = os.path.abspath(text)
    if path not in candidates:
        candidates.append(path)


def _is_non_python_executable(path: str) -> bool:
    candidate = os.path.abspath(str(path or "").strip())
    if not candidate or not os.path.isfile(candidate):
        return False
    base_name = os.path.basename(candidate).lower()
    if base_name in _PYTHON_LAUNCHER_NAMES:
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
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
) -> Optional[str]:
    scripts_dir = resolve_project_venv_scripts_dir(project_root)
    candidate_names: List[str]
    if os.name == "nt":
        if prefer_windowed is None:
            prefer_windowed = os.path.basename(str(sys.executable or "")).lower() == "pythonw.exe"
        candidate_names = ["pythonw.exe", "python.exe"] if prefer_windowed else ["python.exe", "pythonw.exe"]
    else:
        candidate_names = ["python"]

    for candidate_name in candidate_names:
        project_python = os.path.join(scripts_dir, candidate_name)
        if os.path.isfile(project_python):
            return project_python

    current_executable = str(sys.executable or "").strip()
    if not current_executable:
        return None

    resolved_executable = os.path.abspath(current_executable)
    if not os.path.isfile(resolved_executable):
        return None
    if os.path.basename(resolved_executable).lower() in {"py.exe", "pyw.exe"}:
        return None
    if _is_non_python_executable(resolved_executable):
        return None
    return resolved_executable


def build_worker_process_env(
    base_env: Optional[Mapping[str, str]] = None,
    *,
    project_root: Optional[str] = None,
) -> Dict[str, str]:
    resolved_project_root = resolve_project_root(project_root)
    env = dict(base_env) if base_env is not None else os.environ.copy()

    env["PYTHONPATH"] = _prepend_path_once(env.get("PYTHONPATH"), resolved_project_root)

    venv_root = resolve_project_venv_root(resolved_project_root)
    if os.path.isdir(venv_root):
        env["VIRTUAL_ENV"] = venv_root
        scripts_dir = resolve_project_venv_scripts_dir(resolved_project_root)
        if os.path.isdir(scripts_dir):
            env["PATH"] = _prepend_path_once(env.get("PATH"), scripts_dir)

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
                try:
                    os.add_dll_directory(dll_dir)
                except Exception:
                    pass

    if os.path.isdir(venv_root):
        try:
            sys.prefix = venv_root
            sys.exec_prefix = venv_root
        except Exception:
            pass

    if logger is not None:
        try:
            logger.info(
                "%s虚拟环境已就绪: executable=%s, prefix=%s, venv=%s",
                runtime_label,
                sys.executable,
                sys.prefix,
                venv_root,
            )
        except Exception:
            pass

    return {
        "project_root": resolved_project_root,
        "venv_root": venv_root,
        "scripts_dir": scripts_dir,
        "site_packages": site_packages,
    }


def _is_running_inside_virtual_environment() -> bool:
    if hasattr(sys, "real_prefix"):
        return True
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

    if target_python and os.path.isfile(target_python):
        current_executable = _normalize_path(str(sys.executable or ""))
        target_executable = _normalize_path(target_python)
        if current_executable != target_executable and os.environ.get(relaunch_env_name) != "1":
            relaunch_args = [target_python, os.path.abspath(entry_file), *(list(argv) if argv is not None else sys.argv[1:])]
            os.environ[relaunch_env_name] = "1"
            if logger is not None:
                try:
                    logger.warning("%s解释器不是项目venv，正在重启到: %s", runtime_label, target_python)
                except Exception:
                    pass
            try:
                os.execv(target_python, relaunch_args)
            except Exception as exc:
                if logger is not None:
                    try:
                        logger.error("%s切换到项目venv解释器失败，继续执行路径注入: %s", runtime_label, exc)
                    except Exception:
                        pass

    if _is_running_inside_virtual_environment():
        if logger is not None:
            try:
                logger.info("%s已在虚拟环境中运行: %s", runtime_label, sys.prefix)
            except Exception:
                pass
        return True

    env_info = bootstrap_current_process_virtual_environment(
        project_root=resolved_project_root,
        runtime_label=runtime_label,
        logger=logger,
    )
    if os.path.isdir(env_info["venv_root"]):
        return True

    if logger is not None:
        try:
            logger.warning("%s未找到项目 venv，继续使用当前解释器", runtime_label)
        except Exception:
            pass
    return False


def is_packaged_runtime() -> bool:
    """Best-effort runtime packaging detection for worker routing."""
    if bool(getattr(sys, "frozen", False)):
        return True
    if hasattr(sys, "_MEIPASS"):
        return True

    main_module = sys.modules.get("__main__")
    if main_module is not None and hasattr(main_module, "__compiled__"):
        return True

    argv0 = os.path.abspath(str(sys.argv[0])) if sys.argv else ""
    if _is_non_python_executable(argv0):
        return True

    exe_path = os.path.abspath(str(sys.executable or ""))
    if _is_non_python_executable(exe_path):
        return True

    return False


def resolve_main_executable() -> Optional[str]:
    """Resolve packaged app executable path when available."""
    candidates: List[str] = []
    if sys.argv and sys.argv[0]:
        _append_candidate(candidates, sys.argv[0])
    if sys.executable:
        _append_candidate(candidates, sys.executable)
        _append_candidate(candidates, os.path.join(os.path.dirname(sys.executable), "main.exe"))
    if sys.argv and sys.argv[0]:
        _append_candidate(candidates, os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "main.exe"))

    for candidate in candidates:
        if _is_non_python_executable(candidate):
            return candidate

    # 兼容历史固定命名：main.exe
    for candidate in candidates:
        if os.path.basename(candidate).lower() == "main.exe" and os.path.isfile(candidate):
            return candidate
    return None



def resolve_project_main_script(project_root: Optional[str] = None) -> Optional[str]:
    root = str(project_root or '').strip()
    if root:
        root_path = os.path.abspath(root)
    else:
        root_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_path = os.path.join(root_path, 'main.py')
    if os.path.isfile(main_path):
        return main_path
    return None


def build_worker_launch_command(
    worker_flag: str,
    module_name: str,
    standalone_flag: str,
    extra_args: Optional[Sequence[str]] = None,
    *,
    python_executable: Optional[str] = None,
    require_python_executable: bool = False,
    allow_main_script: bool = False,
    project_root: Optional[str] = None,
) -> List[str]:
    flag = str(worker_flag or '').strip()
    module = str(module_name or '').strip()
    standalone = str(standalone_flag or '').strip()
    if not flag:
        raise ValueError("worker_flag 不能为空")
    if not module:
        raise ValueError("module_name 不能为空")
    if not standalone:
        raise ValueError("standalone_flag 不能为空")

    resolved_extra_args = [str(arg) for arg in extra_args] if extra_args else []
    packaged_cmd = build_main_worker_command(flag, resolved_extra_args)
    if packaged_cmd:
        return packaged_cmd

    if bool(getattr(sys, 'frozen', False)):
        return [sys.executable, flag, *resolved_extra_args]

    resolved_python = str(python_executable or "").strip()
    if not resolved_python:
        resolved_python = str(resolve_project_python_executable(project_root=project_root) or "").strip()
    executable = os.path.abspath(resolved_python) if resolved_python else ""
    if require_python_executable and (not executable or not os.path.isfile(executable)):
        raise FileNotFoundError(executable or str(python_executable or ''))

    if allow_main_script:
        main_path = resolve_project_main_script(project_root=project_root)
        if main_path:
            return [executable, main_path, flag, *resolved_extra_args]

    return [executable, '-m', module, standalone, *resolved_extra_args]


def build_main_worker_command(worker_flag: str, extra_args: Optional[Sequence[str]] = None) -> Optional[List[str]]:
    """Build command for packaged app worker entry."""
    flag = str(worker_flag or "").strip()
    if not flag:
        return None
    exe_path = resolve_main_executable()
    if not exe_path:
        return None
    command = [exe_path, flag]
    if extra_args:
        command.extend(str(arg) for arg in extra_args)
    return command


def get_cli_argument_value(
    argv: Optional[Sequence[str]],
    flag: str,
    default: str = "",
) -> str:
    args = [str(arg) for arg in (argv or ())]
    target_flag = str(flag or "").strip()
    if not target_flag:
        return str(default)

    for index, arg in enumerate(args):
        if arg == target_flag and index + 1 < len(args):
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
    except Exception:
        return int(default)


def find_standalone_subprocess_spec(
    argv: Optional[Sequence[str]],
    specs: Iterable[StandaloneSubprocessSpec],
) -> Optional[StandaloneSubprocessSpec]:
    args = {str(arg) for arg in (argv or ())}
    for spec in specs:
        if str(spec.flag or "").strip() in args:
            return spec
    return None


def is_standalone_subprocess_active(
    argv: Optional[Sequence[str]],
    specs: Iterable[StandaloneSubprocessSpec],
) -> bool:
    return find_standalone_subprocess_spec(argv, specs) is not None


def run_standalone_subprocess(
    argv: Optional[Sequence[str]],
    specs: Iterable[StandaloneSubprocessSpec],
) -> bool:
    spec = find_standalone_subprocess_spec(argv, specs)
    if spec is None:
        return False

    if bool(spec.configure_root_logging):
        logging.basicConfig(
            level=int(spec.log_level),
            format=str(spec.log_format),
        )
    logger = logging.getLogger(str(spec.logger_name or __name__))
    raw_args = spec.args_factory(argv or ()) if spec.args_factory is not None else ()
    args = tuple(raw_args or ())

    if spec.startup_hook is not None:
        try:
            spec.startup_hook(logger, tuple(argv or ()), args)
        except Exception as exc:
            logger.error("[%s] 启动钩子执行失败：%s", spec.error_label, exc)
            logger.debug(traceback.format_exc())

    try:
        module = importlib.import_module(str(spec.module_name))
        runner = getattr(module, str(spec.callable_name))
        runner(*args)
    except Exception as exc:
        if not logging.getLogger().handlers:
            logging.basicConfig(
                level=int(spec.log_level),
                format=str(spec.log_format),
            )
        logger.error("[%s] 子进程入口执行失败：%s", spec.error_label, exc)
        logger.error(traceback.format_exc())
    return True
