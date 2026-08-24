# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
import types
from pathlib import Path

from utils.app_paths import get_runtime_data_dir

_WIN32COM_RUNTIME_PREPARED = False


def _resolve_win32com_gen_py_dir() -> Path:
    return Path(get_runtime_data_dir("LCA")).resolve(strict=False) / "win32com_gen_py"


def prepare_win32com_runtime() -> None:
    global _WIN32COM_RUNTIME_PREPARED

    if _WIN32COM_RUNTIME_PREPARED:
        return

    import win32com

    gen_py_dir = _resolve_win32com_gen_py_dir()
    gen_py_dir.mkdir(parents=True, exist_ok=True)
    gen_py_dir_str = str(gen_py_dir)

    win32com.__gen_path__ = gen_py_dir_str

    gen_py_module = sys.modules.get("win32com.gen_py")
    if gen_py_module is None:
        gen_py_module = types.ModuleType("win32com.gen_py")
        sys.modules[gen_py_module.__name__] = gen_py_module

    gen_py_module.__path__ = [gen_py_dir_str]
    setattr(win32com, "gen_py", gen_py_module)
    _WIN32COM_RUNTIME_PREPARED = True
