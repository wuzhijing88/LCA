#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List

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

    print(f"任务模块打包校验通过，共 {len(task_module_paths)} 个模块。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
