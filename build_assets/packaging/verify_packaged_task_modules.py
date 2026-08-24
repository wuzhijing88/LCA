#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tasks import TASK_MODULES_DICT, _EXPORT_MODULES


def _collect_task_module_paths() -> List[str]:
    module_paths = []
    for module_path in list(dict.values(TASK_MODULES_DICT)) + list(_EXPORT_MODULES.values()):
        if isinstance(module_path, str) and module_path.startswith("tasks."):
            module_paths.append(module_path)
    return sorted(set(module_paths))


def _find_missing_modules(build_dir: Path, module_paths: Iterable[str]) -> List[str]:
    missing = []
    for module_path in module_paths:
        compiled_prefix = f"module.{module_path}"
        if not any(build_dir.glob(f"{compiled_prefix}.*")):
            missing.append(module_path)
    return missing


def _compiled_task_module_name(filename: str) -> Optional[str]:
    name = Path(filename).name
    if not name.startswith("module.tasks") or not name.endswith(".c"):
        return None
    module = name[len("module.") : -2]
    if module == "tasks" or not module.startswith("tasks."):
        return None
    return module


def _task_source_exists(module: str, project_root: Path = PROJECT_ROOT) -> bool:
    relative = Path(*module.split("."))
    return (project_root / f"{relative}.py").is_file() or (project_root / relative / "__init__.py").is_file()


def _find_stale_task_modules(build_dir: Path, project_root: Path = PROJECT_ROOT) -> List[str]:
    stale = []
    for c_file in build_dir.glob("module.tasks*.c"):
        module = _compiled_task_module_name(c_file.name)
        if module and not _task_source_exists(module, project_root):
            stale.append(module)
    return sorted(set(stale))


def main() -> int:
    parser = argparse.ArgumentParser(description="校验打包产物是否包含全部任务模块")
    parser.add_argument("--build-dir", required=True, help="Nuitka 构建目录，例如 build_assets/packaging/build_output/main.build")
    args = parser.parse_args()

    build_dir = Path(args.build_dir).resolve()
    if not build_dir.exists():
        print(f"构建目录不存在: {build_dir}", file=sys.stderr)
        return 1

    task_module_paths = _collect_task_module_paths()
    missing_modules = _find_missing_modules(build_dir, task_module_paths)
    if missing_modules:
        print("任务模块打包校验失败，以下模块未进入构建产物：", file=sys.stderr)
        for module_name in missing_modules:
            print(f"  - {module_name}", file=sys.stderr)
        return 1

    stale_modules = _find_stale_task_modules(build_dir)
    if stale_modules:
        print("任务模块打包校验失败，构建产物仍含已删除的模块：", file=sys.stderr)
        for module_name in stale_modules:
            print(f"  - {module_name}", file=sys.stderr)
        return 1

    print(f"任务模块打包校验通过，共 {len(task_module_paths)} 个模块。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
