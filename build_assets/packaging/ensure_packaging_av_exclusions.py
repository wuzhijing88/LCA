#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Keep Windows Defender from eating plugin DLLs during packaging."""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT_FOR_IMPORTS = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT_FOR_IMPORTS) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_FOR_IMPORTS))

from build_assets.packaging.stage_packaged_runtime_assets import iter_plugin_pack_files


DEFENDER_FALSE_POSITIVE = "Trojan:Win32/Bearfoos.B!ml"


def packaging_av_exclusion_paths(project_root: Path) -> list[Path]:
    root = project_root.resolve()
    packaging = root / "build_assets" / "packaging"
    return [
        root / "tools" / "plugin",
        packaging / "build_output",
        packaging / "release_output",
    ]


def format_exclusion_help(paths: list[Path]) -> str:
    listed = "\n".join(f"  - {path}" for path in paths)
    return (
        "Windows Defender 会把 tools/plugin/dm.dll 及其打包副本误报为 "
        f"{DEFENDER_FALSE_POSITIVE}（!ml 为机器学习启发式）。\n"
        "请用管理员运行打包脚本，或在「Windows 安全中心 > 病毒和威胁防护 > 排除项」中加入：\n"
        f"{listed}"
    )


def _is_windows_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run_powershell(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def real_time_protection_enabled() -> bool | None:
    result = _run_powershell(
        "try { (Get-MpComputerStatus).RealTimeProtectionEnabled } catch { '' }"
    )
    value = (result.stdout or "").strip().lower()
    if value in {"true", "1"}:
        return True
    if value in {"false", "0"}:
        return False
    return None


def add_windows_defender_exclusions(paths: list[Path], *, elevate: bool) -> None:
    if not paths:
        return
    quoted = ",".join(f"'{path}'" for path in paths)
    command = f"Add-MpPreference -ExclusionPath @({quoted})"
    result = _run_powershell(command)
    if result.returncode == 0:
        return
    if elevate and not _is_windows_admin():
        with tempfile.NamedTemporaryFile(
            "w", suffix=".ps1", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(command + "\nexit $LASTEXITCODE\n")
            temp_ps1 = handle.name
        try:
            elevated = _run_powershell(
                "$p = Start-Process -FilePath powershell.exe -Verb RunAs -Wait -PassThru "
                "-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',"
                f"'{temp_ps1}'; if ($null -eq $p) {{ exit 1 }}; exit $p.ExitCode"
            )
        finally:
            Path(temp_ps1).unlink(missing_ok=True)
        if elevated.returncode == 0:
            return
        detail = (elevated.stderr or elevated.stdout or "").strip()
        raise RuntimeError(
            format_exclusion_help(paths)
            + (f"\n提升权限失败: {detail}" if detail else "")
        )
    detail = (result.stderr or result.stdout or "").strip()
    raise RuntimeError(
        format_exclusion_help(paths)
        + (f"\nAdd-MpPreference 失败: {detail}" if detail else "")
    )


def verify_plugin_files_readable(plugin_dir: Path, *, label: str) -> list[str]:
    if not plugin_dir.is_dir():
        return []
    verified: list[str] = []
    for name, item in iter_plugin_pack_files(plugin_dir):
        try:
            data = item.read_bytes()
        except OSError as exc:
            raise RuntimeError(
                f"{label} 无法读取 {item}（{exc}）。"
                "文件可能已被 Windows Defender 隔离。"
            ) from exc
        if name.lower() == "dm.dll" and len(data) < 1024:
            raise RuntimeError(f"{label} 中的 dm.dll 已损坏或被截断: {item}")
        verified.append(name)
    return verified


def verify_staged_plugin_runtime(project_root: Path, dist_root: Path) -> None:
    source = project_root / "tools" / "plugin"
    staged = dist_root / "tools" / "plugin"
    source_names = {name for name, _item in iter_plugin_pack_files(source)}
    if not source_names:
        return
    verify_plugin_files_readable(source, label="源插件目录")
    staged_names = set(verify_plugin_files_readable(staged, label="发行插件目录"))
    missing = sorted(source_names - staged_names)
    if missing:
        raise RuntimeError(
            "发行目录缺少插件文件: "
            + ", ".join(missing)
            + "。Windows Defender 可能已隔离副本。"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add Windows Defender exclusions required to package plugin DLLs"
    )
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--verify-dist", default="")
    parser.add_argument("--skip-add", action="store_true")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve(strict=False)
    paths = packaging_av_exclusion_paths(project_root)
    noninteractive = os.environ.get("LCA_NONINTERACTIVE") == "1"
    protection = real_time_protection_enabled()
    if args.skip_add:
        print("Skip adding Windows Defender exclusions")
    elif protection is False:
        print("Windows Defender real-time protection is off; skip exclusions")
    else:
        try:
            add_windows_defender_exclusions(paths, elevate=not noninteractive)
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print("Windows Defender packaging exclusions ensured:")
        for path in paths:
            print(f"  {path}")

    try:
        verify_plugin_files_readable(project_root / "tools" / "plugin", label="源插件目录")
        if args.verify_dist:
            verify_staged_plugin_runtime(project_root, Path(args.verify_dist).resolve())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(format_exclusion_help(paths), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
