#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


PROJECT_ROOT_FOR_IMPORTS = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT_FOR_IMPORTS) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_IMPORTS))

from services.ocr_runtime_contract import OCR_REQUIRED_RUNTIME_DLLS


def _resolve_existing_path(project_root: Path, candidates: list[str], *, label: str, expect_dir: bool = False) -> Path:
    for relative_path in candidates:
        candidate = (project_root / relative_path).resolve(strict=False)
        if expect_dir and candidate.is_dir():
            return candidate
        if not expect_dir and candidate.is_file():
            return candidate
    expected = " / ".join(candidates)
    raise FileNotFoundError(f"缺少源{'目录' if expect_dir else '文件'}: {label} ({expected})")


def _copy_required_file(source_path: Path, target_path: Path, *, label: str) -> None:
    source = source_path.resolve(strict=False)
    target = target_path.resolve(strict=False)
    if not source.is_file():
        raise FileNotFoundError(f"缺少源文件: {label} -> {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if not target.is_file():
        raise FileNotFoundError(f"复制后缺少目标文件: {label} -> {target}")


def _stage_qt_platform_plugin(project_root: Path, dist_root: Path) -> None:
    print("[4/6] Copy Qt platform plugin...")
    source = _resolve_existing_path(
        project_root,
        [
            "venv/Lib/site-packages/PySide6/plugins/platforms/qwindows.dll",
            "venv/lib/site-packages/PySide6/plugins/platforms/qwindows.dll",
        ],
        label="qwindows.dll",
    )
    _copy_required_file(
        source,
        dist_root / "PySide6" / "plugins" / "platforms" / "qwindows.dll",
        label="qwindows.dll",
    )


def _stage_ocr_runtime(project_root: Path, dist_root: Path) -> None:
    print("[5/6] Restore required ONNX Runtime DLLs...")
    onnxruntime_capi = _resolve_existing_path(
        project_root,
        [
            "venv/Lib/site-packages/onnxruntime/capi",
            "venv/lib/site-packages/onnxruntime/capi",
        ],
        label="onnxruntime capi",
        expect_dir=True,
    )

    for filename in OCR_REQUIRED_RUNTIME_DLLS:
        _copy_required_file(
            onnxruntime_capi / filename,
            dist_root / filename,
            label=filename,
        )


def _stage_interception_files(project_root: Path, dist_root: Path) -> None:
    print("[5.5/6] Copy Interception driver files...")
    for arch in ("x64", "x86"):
        _copy_required_file(
            project_root / "Interception" / "library" / arch / "interception.dll",
            dist_root / "Interception" / "library" / arch / "interception.dll",
            label=f"Interception {arch} interception.dll",
        )
    _copy_required_file(
        project_root / "Interception" / "command line installer" / "install-interception.exe",
        dist_root / "Interception" / "command line installer" / "install-interception.exe",
        label="install-interception.exe",
    )


def _remove_unused_bundled_tools(dist_root: Path) -> None:
    leftover = dist_root / "tools" / "大漠综合工具.exe"
    if leftover.is_file():
        leftover.unlink()
        print("[5.6/6] Removed leftover 大漠综合工具.exe")


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage packaged runtime assets for release build")
    parser.add_argument("--project-root", required=True, help="Project root directory")
    parser.add_argument("--dist", required=True, help="Packaged dist directory")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve(strict=False)
    dist_root = Path(args.dist).resolve(strict=False)

    if not dist_root.is_dir():
        raise FileNotFoundError(f"缺少打包输出目录: {dist_root}")

    _stage_qt_platform_plugin(project_root, dist_root)
    _stage_ocr_runtime(project_root, dist_root)
    _stage_interception_files(project_root, dist_root)
    _remove_unused_bundled_tools(dist_root)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        print(f"ERROR: {detail}", file=sys.stderr)
        raise SystemExit(1)
