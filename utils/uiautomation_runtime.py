# -*- coding: utf-8 -*-
"""UIAutomation 运行时辅助。

统一处理开发环境与打包环境下的 UIAutomation/comtypes 依赖差异。
"""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import logging
import os
import sys
from contextlib import nullcontext
from pathlib import Path

logger = logging.getLogger(__name__)

_UIAUTOMATION_RUNTIME_PREPARED = False
_DLL_DIRECTORY_HANDLES = []


def _iter_runtime_roots():
    roots = []

    if getattr(sys, "frozen", False):
        exe_path = os.path.abspath(sys.executable)
        try:
            exe_path = os.path.realpath(exe_path)
        except Exception:
            pass
        roots.append(Path(exe_path).resolve().parent)

    try:
        roots.append(Path(__file__).resolve().parents[1])
    except Exception:
        pass

    visited = set()
    for root in roots:
        normalized = os.path.normcase(os.path.normpath(str(root)))
        if normalized in visited:
            continue
        visited.add(normalized)
        yield root


def _resolve_packaged_comtypes_gen_dir() -> Path | None:
    for root in _iter_runtime_roots():
        gen_dir = root / "comtypes" / "gen"
        if gen_dir.is_dir():
            return gen_dir
    return None


def _resolve_packaged_uiautomation_bin_dir() -> Path | None:
    for root in _iter_runtime_roots():
        bin_dir = root / "uiautomation" / "bin"
        if bin_dir.is_dir():
            return bin_dir
    return None


def _module_sort_key(module_file: Path) -> tuple[int, str]:
    name = module_file.stem.lower()
    if name == "_00020430_0000_0000_c000_000000000046_0_2_0":
        return (0, name)
    if name == "stdole":
        return (1, name)
    if module_file.stem.startswith("_"):
        return (2, name)
    return (3, name)


def _load_comtypes_module(module_file: Path, comtypes_gen_module) -> None:
    module_name = module_file.stem
    full_name = f"comtypes.gen.{module_name}"

    existing_module = sys.modules.get(full_name)
    if existing_module is not None:
        setattr(comtypes_gen_module, module_name, existing_module)
        return

    module_path = str(module_file)
    suffix = module_file.suffix.lower()
    if suffix == ".pyc":
        loader = importlib.machinery.SourcelessFileLoader(full_name, module_path)
        spec = importlib.util.spec_from_loader(full_name, loader)
    else:
        spec = importlib.util.spec_from_file_location(full_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法创建 comtypes 模块加载器: {full_name}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    try:
        spec.loader.exec_module(module)
        setattr(comtypes_gen_module, module_name, module)
    except Exception:
        sys.modules.pop(full_name, None)
        raise


def _preload_packaged_comtypes_modules() -> None:
    gen_dir = _resolve_packaged_comtypes_gen_dir()
    if gen_dir is None:
        return

    import comtypes.client
    import comtypes.gen

    gen_dir_str = str(gen_dir)
    package_paths = list(getattr(comtypes.gen, "__path__", []))
    if gen_dir_str not in package_paths:
        comtypes.gen.__path__ = package_paths + [gen_dir_str]

    try:
        comtypes.client.gen_dir = gen_dir_str
    except Exception:
        pass

    module_file_map: dict[str, Path] = {}
    for suffix in ("*.pyc", "*.py"):
        for module_file in gen_dir.glob(suffix):
            if module_file.stem == "__init__":
                continue
            module_file_map.setdefault(module_file.stem, module_file)

    module_files = sorted(module_file_map.values(), key=_module_sort_key)
    for module_file in module_files:
        _load_comtypes_module(module_file, comtypes.gen)


def _register_uiautomation_bin_dir() -> None:
    bin_dir = _resolve_packaged_uiautomation_bin_dir()
    if bin_dir is None:
        return

    bin_dir_str = str(bin_dir)
    current_path = os.environ.get("PATH", "")
    path_parts = [part for part in current_path.split(os.pathsep) if part]
    normalized_parts = {os.path.normcase(os.path.normpath(part)) for part in path_parts}
    normalized_bin_dir = os.path.normcase(os.path.normpath(bin_dir_str))
    if normalized_bin_dir not in normalized_parts:
        os.environ["PATH"] = bin_dir_str + os.pathsep + current_path

    if hasattr(os, "add_dll_directory"):
        try:
            handle = os.add_dll_directory(bin_dir_str)
            _DLL_DIRECTORY_HANDLES.append(handle)
        except Exception:
            logger.debug("[UIAutomation] 注册 DLL 目录失败: %s", bin_dir_str, exc_info=True)


def prepare_uiautomation_runtime() -> None:
    global _UIAUTOMATION_RUNTIME_PREPARED

    if _UIAUTOMATION_RUNTIME_PREPARED:
        return

    _register_uiautomation_bin_dir()
    _preload_packaged_comtypes_modules()
    _UIAUTOMATION_RUNTIME_PREPARED = True


def import_uiautomation():
    prepare_uiautomation_runtime()
    return importlib.import_module("uiautomation")


def is_uiautomation_available() -> bool:
    try:
        import_uiautomation()
        return True
    except Exception:
        return False


def uiautomation_thread_context(auto_module=None):
    auto = auto_module or import_uiautomation()
    initializer = getattr(auto, "UIAutomationInitializerInThread", None)
    if initializer is None:
        return nullcontext()
    return initializer()
