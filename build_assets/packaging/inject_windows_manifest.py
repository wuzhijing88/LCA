# -*- coding: utf-8 -*-
"""Inject an explicit Windows manifest into the packaged executable."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from pathlib import Path

RT_MANIFEST = 24
MANIFEST_RESOURCE_ID = 1


def _make_int_resource(value: int) -> wintypes.LPCWSTR:
    return ctypes.cast(value, wintypes.LPCWSTR)


def _read_manifest(manifest_path: Path) -> bytes:
    data = manifest_path.read_bytes()
    if not data:
        raise ValueError(f"manifest 为空: {manifest_path}")
    if b"dpiAwareness" not in data and b"dpiAware" not in data:
        raise ValueError(f"manifest 缺少 DPI 声明: {manifest_path}")
    return data


def _inject_manifest(exe_path: Path, manifest_bytes: bytes) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    kernel32.BeginUpdateResourceW.restype = wintypes.HANDLE
    kernel32.UpdateResourceW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.WORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.UpdateResourceW.restype = wintypes.BOOL
    kernel32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    kernel32.EndUpdateResourceW.restype = wintypes.BOOL

    update_handle = kernel32.BeginUpdateResourceW(str(exe_path), False)
    if not update_handle:
        raise OSError(ctypes.get_last_error(), f"BeginUpdateResourceW 失败: {exe_path}")

    manifest_buffer = ctypes.create_string_buffer(manifest_bytes)
    committed = False
    try:
        ok = kernel32.UpdateResourceW(
            update_handle,
            _make_int_resource(RT_MANIFEST),
            _make_int_resource(MANIFEST_RESOURCE_ID),
            0,
            ctypes.cast(manifest_buffer, wintypes.LPVOID),
            len(manifest_bytes),
        )
        if not ok:
            raise OSError(ctypes.get_last_error(), f"UpdateResourceW 失败: {exe_path}")

        if not kernel32.EndUpdateResourceW(update_handle, False):
            raise OSError(ctypes.get_last_error(), f"EndUpdateResourceW 提交失败: {exe_path}")
        committed = True
    finally:
        if not committed:
            kernel32.EndUpdateResourceW(update_handle, True)


def _extract_manifest(exe_path: Path) -> str:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    load_library_as_datafile = 0x00000002
    kernel32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    kernel32.LoadLibraryExW.restype = wintypes.HMODULE
    kernel32.FindResourceW.argtypes = [wintypes.HMODULE, wintypes.LPCWSTR, wintypes.LPCWSTR]
    kernel32.FindResourceW.restype = wintypes.HRSRC
    kernel32.LoadResource.argtypes = [wintypes.HMODULE, wintypes.HRSRC]
    kernel32.LoadResource.restype = wintypes.HGLOBAL
    kernel32.SizeofResource.argtypes = [wintypes.HMODULE, wintypes.HRSRC]
    kernel32.SizeofResource.restype = wintypes.DWORD
    kernel32.LockResource.argtypes = [wintypes.HGLOBAL]
    kernel32.LockResource.restype = wintypes.LPVOID
    kernel32.FreeLibrary.argtypes = [wintypes.HMODULE]
    kernel32.FreeLibrary.restype = wintypes.BOOL

    module = kernel32.LoadLibraryExW(str(exe_path), None, load_library_as_datafile)
    if not module:
        raise OSError(ctypes.get_last_error(), f"LoadLibraryExW 失败: {exe_path}")

    try:
        resource = kernel32.FindResourceW(
            module,
            _make_int_resource(MANIFEST_RESOURCE_ID),
            _make_int_resource(RT_MANIFEST),
        )
        if not resource:
            raise OSError(ctypes.get_last_error(), f"FindResourceW 失败: {exe_path}")

        size = kernel32.SizeofResource(module, resource)
        loaded = kernel32.LoadResource(module, resource)
        locked = kernel32.LockResource(loaded)
        data = ctypes.string_at(locked, size)
        return data.decode("utf-8", errors="strict")
    finally:
        kernel32.FreeLibrary(module)


def _verify_manifest(exe_path: Path) -> None:
    text = _extract_manifest(exe_path)
    required_tokens = (
        "dpiAware",
        "dpiAwareness",
        "PerMonitorV2",
        "requireAdministrator",
        "longPathAware",
    )
    missing = [token for token in required_tokens if token not in text]
    if missing:
        raise ValueError(f"manifest 注入后仍缺少字段: {', '.join(missing)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inject Windows manifest into packaged exe.")
    parser.add_argument("--exe", required=True, help="目标 exe 路径")
    parser.add_argument("--manifest", required=True, help="manifest 文件路径")
    args = parser.parse_args()

    exe_path = Path(args.exe).resolve()
    manifest_path = Path(args.manifest).resolve()

    if not exe_path.is_file():
        raise FileNotFoundError(f"exe 不存在: {exe_path}")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest 不存在: {manifest_path}")

    manifest_bytes = _read_manifest(manifest_path)
    _inject_manifest(exe_path, manifest_bytes)
    _verify_manifest(exe_path)
    print(f"manifest 已注入: {exe_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
