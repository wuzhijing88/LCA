#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


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
    print("[5/6] Restore required OCR runtime DLLs...")
    fastdeploy_libs = _resolve_existing_path(
        project_root,
        [
            "venv/Lib/site-packages/fastdeploy/libs",
            "venv/lib/site-packages/fastdeploy/libs",
        ],
        label="fastdeploy libs",
        expect_dir=True,
    )
    fastdeploy_mklml = fastdeploy_libs / "third_libs" / "paddle_inference" / "third_party" / "install" / "mklml" / "lib"
    fastdeploy_openvino_bin = fastdeploy_libs / "third_libs" / "openvino" / "runtime" / "bin"

    _copy_required_file(
        fastdeploy_libs / "onnxruntime_providers_shared.dll",
        dist_root / "onnxruntime_providers_shared.dll",
        label="onnxruntime_providers_shared.dll",
    )
    for filename in ("mklml.dll", "libiomp5md.dll"):
        _copy_required_file(
            fastdeploy_mklml / filename,
            dist_root / filename,
            label=filename,
        )
    _copy_required_file(
        fastdeploy_openvino_bin / "plugins.xml",
        dist_root / "plugins.xml",
        label="plugins.xml",
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


def _stage_extra_tools(project_root: Path, dist_root: Path) -> None:
    print("[5.6/6] Copy extra tool...")
    _copy_required_file(
        project_root / "tools" / "大漠综合工具.exe",
        dist_root / "tools" / "大漠综合工具.exe",
        label="大漠综合工具.exe",
    )


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
    _stage_extra_tools(project_root, dist_root)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        print(f"ERROR: {detail}", file=sys.stderr)
        raise SystemExit(1)
