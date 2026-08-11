#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify packaged dist has no Python source files")
    parser.add_argument("--dist", required=True, help="Packaged dist directory")
    args = parser.parse_args()

    dist_root = Path(args.dist).resolve(strict=False)
    if not dist_root.is_dir():
        raise FileNotFoundError(f"缺少打包输出目录: {dist_root}")

    source_files = sorted(path for path in dist_root.rglob("*.py") if path.is_file())
    if source_files:
        print("ERROR: 检测到 Python 源文件残留:", file=sys.stderr)
        for path in source_files:
            print(f"  - {path}", file=sys.stderr)
        return 1

    print("OK: packaged dist contains no Python source files")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        print(f"ERROR: {detail}", file=sys.stderr)
        raise SystemExit(1)
