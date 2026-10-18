#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from build_assets.packaging.stage_packaged_runtime_assets import SCRIPT_RUNTIME_FILES


def main() -> int:
    parser = argparse.ArgumentParser(description="校验发行目录只包含必需的独立脚本运行时源码")
    parser.add_argument("--dist", required=True, help="打包输出目录")
    args = parser.parse_args()

    dist_root = Path(args.dist).resolve(strict=False)
    if not dist_root.is_dir():
        raise FileNotFoundError(f"缺少打包输出目录: {dist_root}")

    # 与暂存共用清单；只允许精确目标路径，且内容必须与本次构建的源码一致。
    allowed_sources = {
        dist_root / "resources" / "script_runtime" / destination:
        PROJECT_ROOT / "task_workflow" / source
        for source, destination in SCRIPT_RUNTIME_FILES
    }
    unexpected_sources = []
    changed_sources = []
    verified_count = 0
    for path in sorted(path for path in dist_root.rglob("*.py") if path.is_file()):
        source = allowed_sources.get(path)
        if source is None:
            unexpected_sources.append(path)
        elif path.read_bytes() != source.read_bytes():
            changed_sources.append(path)
        else:
            verified_count += 1

    if unexpected_sources:
        print("ERROR: 检测到 Python 源文件残留:", file=sys.stderr)
        for path in unexpected_sources:
            print(f"  - {path}", file=sys.stderr)
    if changed_sources:
        print("ERROR: 独立脚本运行时源码内容与本次构建不一致:", file=sys.stderr)
        for path in changed_sources:
            print(f"  - {path}", file=sys.stderr)
    if unexpected_sources or changed_sources:
        return 1

    print(f"校验通过：无额外 Python 源码，已核对 {verified_count} 个独立脚本运行时文件")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        print(f"ERROR: {detail}", file=sys.stderr)
        raise SystemExit(1)
