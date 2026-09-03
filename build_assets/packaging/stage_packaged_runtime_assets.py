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

# 发行包只带这四个；xx.dat 为大漠附属，缺则跳过。其它文件一律不进包。
PLUGIN_PACK_FILES = ("PluginHost.exe", "dm.dll", "RegDll.dll", "xx.dat")


def iter_plugin_pack_files(plugin_dir: Path):
    if not plugin_dir.is_dir():
        return
    for name in PLUGIN_PACK_FILES:
        item = plugin_dir / name
        if item.is_file():
            yield name, item


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


_QT_QWINDOWS_CANONICAL = Path("PySide6") / "qt-plugins" / "platforms" / "qwindows.dll"
_QT_QWINDOWS_DUPLICATE = Path("PySide6") / "plugins" / "platforms" / "qwindows.dll"
_DUPLICATE_RUNTIME_FILES = (
    (Path("onnxruntime.dll"), Path("onnxruntime") / "capi" / "onnxruntime.dll"),
    (
        Path("onnxruntime_providers_shared.dll"),
        Path("onnxruntime") / "capi" / "onnxruntime_providers_shared.dll",
    ),
    (_QT_QWINDOWS_DUPLICATE, _QT_QWINDOWS_CANONICAL),
)


def _unlink_empty_parents(path: Path, stop_at: Path) -> None:
    current = path.parent
    stop = stop_at.resolve(strict=False)
    while current.resolve(strict=False) != stop and current.is_dir():
        try:
            next(current.iterdir())
        except StopIteration:
            current.rmdir()
            current = current.parent
            continue
        break


def _remove_duplicate_runtime_files(dist_root: Path) -> list[tuple[Path, int]]:
    removed: list[tuple[Path, int]] = []
    for extra_relative, canonical_relative in _DUPLICATE_RUNTIME_FILES:
        extra = dist_root / extra_relative
        canonical = dist_root / canonical_relative
        if extra.is_file() and canonical.is_file():
            file_size = int(extra.stat().st_size)
            extra.unlink()
            _unlink_empty_parents(extra, dist_root)
            removed.append((extra_relative, file_size))
    return removed


def _stage_qt_platform_plugin(project_root: Path, dist_root: Path) -> None:
    print("[4/6] Copy Qt platform plugin...")
    canonical = dist_root / _QT_QWINDOWS_CANONICAL
    extra = dist_root / _QT_QWINDOWS_DUPLICATE
    if extra.is_file():
        extra.unlink()
        _unlink_empty_parents(extra, dist_root)
    if canonical.is_file():
        return
    source = _resolve_existing_path(
        project_root,
        [
            "venv/Lib/site-packages/PySide6/plugins/platforms/qwindows.dll",
            "venv/lib/site-packages/PySide6/plugins/platforms/qwindows.dll",
        ],
        label="qwindows.dll",
    )
    _copy_required_file(source, canonical, label="qwindows.dll")


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

    for relative in OCR_REQUIRED_RUNTIME_DLLS:
        filename = Path(relative).name
        _copy_required_file(
            onnxruntime_capi / filename,
            dist_root / relative,
            label=relative,
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


def _stage_plugin_runtime(project_root: Path, dist_root: Path) -> None:
    """拷贝 PluginHost 运行文件。缺目录则跳过，不中断打包。

    只拷 PLUGIN_PACK_FILES；发行目录里其它残留（含 .py、调试 dll）一律清掉。
    """
    source = project_root / "tools" / "plugin"
    target = dist_root / "tools" / "plugin"
    if not source.is_dir():
        print("[5.55/6] Skip plugin runtime: tools/plugin is missing")
        if target.is_dir():
            for leftover in target.rglob("*.py"):
                if leftover.is_file():
                    leftover.unlink()
        return
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    keep = set()
    for name, item in iter_plugin_pack_files(source):
        dest = target / name
        dest.write_bytes(item.read_bytes())
        if not dest.is_file() or dest.stat().st_size != item.stat().st_size:
            raise RuntimeError(
                f"复制后缺少或损坏: {dest}。"
                "Windows Defender 可能已隔离该文件，请先加入排除项后重试。"
            )
        keep.add(name)
        copied += 1
    removed = 0
    for leftover in list(target.iterdir()):
        if leftover.name in keep:
            continue
        if leftover.is_file():
            leftover.unlink()
            removed += 1
        elif leftover.is_dir():
            shutil.rmtree(leftover)
            removed += 1
    print(
        f"[5.55/6] Staged plugin runtime files: {copied} -> {target}"
        + (f" (removed {removed} extras)" if removed else "")
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
    _stage_plugin_runtime(project_root, dist_root)
    _remove_unused_bundled_tools(dist_root)
    removed_duplicates = _remove_duplicate_runtime_files(dist_root)
    if removed_duplicates:
        removed_size = sum(file_size for _relative_path, file_size in removed_duplicates)
        print(
            "[5.65/6] Removed duplicate runtime files: "
            f"{len(removed_duplicates)} files, {removed_size / 1024 / 1024:.2f} MB"
        )
        for relative_path, _file_size in removed_duplicates:
            print(f"  - {relative_path.as_posix()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        print(f"ERROR: {detail}", file=sys.stderr)
        raise SystemExit(1)
