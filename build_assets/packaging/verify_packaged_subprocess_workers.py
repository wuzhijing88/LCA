#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""校验 Nuitka 构建产物是否包含全部子进程 worker 模块。

worker 清单以 main.py 中的 `_STANDALONE_SUBPROCESS_SPECS` 为唯一事实来源，
通过 AST 解析提取，避免在校验阶段导入主程序。
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUILD_DIR = PROJECT_ROOT / "build_assets" / "packaging" / "build_output" / "main.build"


def _extract_worker_module_names(main_py_path: Optional[Path] = None) -> List[str]:
    """从 main.py 的 _STANDALONE_SUBPROCESS_SPECS 中提取 worker 模块路径。"""
    source_path = main_py_path or (PROJECT_ROOT / "main.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "_STANDALONE_SUBPROCESS_SPECS":
                module_names = []
                for call in ast.walk(node.value):
                    if not isinstance(call, ast.Call):
                        continue
                    for keyword in call.keywords:
                        if keyword.arg == "module_name" and isinstance(keyword.value, ast.Constant):
                            module_names.append(str(keyword.value.value))
                if not module_names:
                    raise RuntimeError(
                        "_STANDALONE_SUBPROCESS_SPECS 中未解析到任何 module_name"
                    )
                return sorted(set(module_names))

    raise RuntimeError(f"未在 {source_path} 中找到 _STANDALONE_SUBPROCESS_SPECS 定义")


def _verify_build_modules(
    build_dir: Path,
    module_paths: Optional[Iterable[str]] = None,
) -> List[str]:
    """返回未进入 Nuitka 构建产物的 worker 模块列表（空列表表示通过）。"""
    resolved_modules = sorted(set(module_paths)) if module_paths else _extract_worker_module_names()
    missing = []
    for module_path in resolved_modules:
        compiled_prefix = f"module.{module_path}"
        if not any(build_dir.glob(f"{compiled_prefix}.*")):
            missing.append(module_path)
    return missing


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="校验打包产物是否包含全部子进程 worker 模块")
    parser.add_argument(
        "--build-dir",
        default=str(DEFAULT_BUILD_DIR),
        help="Nuitka 构建目录，例如 build_assets/packaging/build_output/main.build",
    )
    args = parser.parse_args(argv)

    build_dir = Path(args.build_dir).resolve()
    if not build_dir.exists():
        print(f"构建目录不存在: {build_dir}", file=sys.stderr)
        return 1

    module_paths = _extract_worker_module_names()
    missing_modules = _verify_build_modules(build_dir, module_paths)
    if missing_modules:
        print("子进程 worker 模块打包校验失败，以下模块未进入构建产物：", file=sys.stderr)
        for module_name in missing_modules:
            print(f"  - {module_name}", file=sys.stderr)
        return 1

    print(f"子进程 worker 模块打包校验通过，共 {len(module_paths)} 个模块：")
    for module_name in module_paths:
        print(f"  - {module_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
