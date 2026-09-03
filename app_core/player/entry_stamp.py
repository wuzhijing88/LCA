# -*- coding: utf-8 -*-
"""离线双身份：把产品入口写进 exe 的 PE 资源。

v2 印记可携带 bind_id，与 package.lcap 配对防挪包（不防本地补丁）。
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# 自定义资源类型 / 名称（字符串资源，非系统 RT_*）
RESOURCE_TYPE = "LCA_ENTRY"
RESOURCE_NAME = "MODE"

ENTRY_PLAYER = "player"
ENTRY_EDITOR = "editor"
VALID_ENTRIES = frozenset({ENTRY_PLAYER, ENTRY_EDITOR})

_MAGIC = b"LCAE"
_VERSION_V1 = 1
_VERSION = 2  # + bind_id[16]
BIND_ID_SIZE = 16
_EMPTY_BIND_ID = bytes(BIND_ID_SIZE)

_ENTRY_CODES = {
    ENTRY_PLAYER: 1,
    ENTRY_EDITOR: 2,
}
_CODE_TO_ENTRY = {code: name for name, code in _ENTRY_CODES.items()}

# XOR 混淆的 HMAC 密钥（防随手改资源，不是防脱壳）
_KEY_OBF = bytes(
    (
        0x3C,
        0xA1,
        0x57,
        0xE2,
        0x19,
        0x8B,
        0x44,
        0xD0,
        0x6F,
        0x2C,
        0x91,
        0xB5,
        0x08,
        0x7E,
        0xC3,
        0x5A,
        0xF1,
        0x33,
        0x9D,
        0x16,
        0xA8,
        0x4B,
        0xE7,
        0x70,
        0x25,
        0xDC,
        0x62,
        0x0F,
        0x89,
        0xBE,
        0x41,
        0x96,
    )
)
_KEY_MASK = 0x5A


@dataclass(frozen=True)
class EntryStampInfo:
    entry: str
    bind_id: bytes = _EMPTY_BIND_ID

    @property
    def has_package_bind(self) -> bool:
        return bool(self.bind_id) and self.bind_id != _EMPTY_BIND_ID


def _hmac_key() -> bytes:
    return bytes(b ^ _KEY_MASK for b in _KEY_OBF)


def _sign(payload_without_mac: bytes) -> bytes:
    return hmac.new(_hmac_key(), payload_without_mac, hashlib.sha256).digest()


def _normalize_bind_id(bind_id: bytes | bytearray | memoryview | None) -> bytes:
    if bind_id is None:
        return _EMPTY_BIND_ID
    raw = bytes(bind_id)
    if len(raw) != BIND_ID_SIZE:
        raise ValueError(f"bind_id 长度必须为 {BIND_ID_SIZE} 字节")
    return raw


def build_entry_stamp_blob(
    entry: str,
    *,
    bind_id: bytes | bytearray | memoryview | None = None,
) -> bytes:
    entry_key = str(entry or "").strip().lower()
    if entry_key not in _ENTRY_CODES:
        raise ValueError(f"不支持的入口类型: {entry}")
    bind = _normalize_bind_id(bind_id)
    # 编辑器印记不绑定数据包
    if entry_key == ENTRY_EDITOR:
        bind = _EMPTY_BIND_ID
    body = _MAGIC + bytes((_VERSION, _ENTRY_CODES[entry_key])) + bind
    return body + _sign(body)


def parse_entry_stamp_info(data: bytes) -> Optional[EntryStampInfo]:
    if not data or len(data) < 4 + 1 + 1 + 32:
        return None
    if data[:4] != _MAGIC:
        return None
    version = data[4]
    if version == _VERSION_V1:
        if len(data) < 6 + 32:
            return None
        code = data[5]
        body = data[:6]
        mac = data[6:38]
        if not hmac.compare_digest(_sign(body), mac):
            return None
        entry = _CODE_TO_ENTRY.get(code)
        if not entry:
            return None
        return EntryStampInfo(entry=entry, bind_id=_EMPTY_BIND_ID)
    if version != _VERSION:
        return None
    if len(data) < 6 + BIND_ID_SIZE + 32:
        return None
    code = data[5]
    bind = data[6 : 6 + BIND_ID_SIZE]
    body = data[: 6 + BIND_ID_SIZE]
    mac = data[6 + BIND_ID_SIZE : 6 + BIND_ID_SIZE + 32]
    if not hmac.compare_digest(_sign(body), mac):
        return None
    entry = _CODE_TO_ENTRY.get(code)
    if not entry:
        return None
    return EntryStampInfo(entry=entry, bind_id=bytes(bind))


def parse_entry_stamp_blob(data: bytes) -> Optional[str]:
    info = parse_entry_stamp_info(data)
    return info.entry if info else None


def _kernel32() -> ctypes.WinDLL:
    return ctypes.WinDLL("kernel32", use_last_error=True)


def write_entry_stamp(
    exe_path: Path | str,
    entry: str,
    *,
    bind_id: bytes | bytearray | memoryview | None = None,
) -> None:
    """向已有 exe 写入入口印记（UpdateResource）。"""
    entry_key = str(entry or "").strip().lower()
    if entry_key not in VALID_ENTRIES:
        raise ValueError(f"不支持的入口类型: {entry}")

    exe = Path(exe_path)
    if not exe.is_file():
        raise FileNotFoundError(exe)
    blob = build_entry_stamp_blob(entry_key, bind_id=bind_id)
    k32 = _kernel32()
    k32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    k32.BeginUpdateResourceW.restype = wintypes.HANDLE
    k32.UpdateResourceW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.WORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    k32.UpdateResourceW.restype = wintypes.BOOL
    k32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    k32.EndUpdateResourceW.restype = wintypes.BOOL

    update_handle = k32.BeginUpdateResourceW(str(exe), False)
    if not update_handle:
        raise OSError(ctypes.get_last_error(), f"BeginUpdateResourceW 失败: {exe}")

    committed = False
    try:
        buffer = ctypes.create_string_buffer(blob)
        if not k32.UpdateResourceW(
            update_handle,
            RESOURCE_TYPE,
            RESOURCE_NAME,
            0,
            ctypes.cast(buffer, wintypes.LPVOID),
            len(blob),
        ):
            raise OSError(ctypes.get_last_error(), "写入入口印记资源失败")
        if not k32.EndUpdateResourceW(update_handle, False):
            raise OSError(ctypes.get_last_error(), f"EndUpdateResourceW 提交失败: {exe}")
        committed = True
    finally:
        if not committed:
            k32.EndUpdateResourceW(update_handle, True)


def _load_resource_bytes(module_handle: wintypes.HMODULE) -> Optional[bytes]:
    k32 = _kernel32()
    k32.FindResourceW.argtypes = [wintypes.HMODULE, wintypes.LPCWSTR, wintypes.LPCWSTR]
    k32.FindResourceW.restype = wintypes.HRSRC
    k32.LoadResource.argtypes = [wintypes.HMODULE, wintypes.HRSRC]
    k32.LoadResource.restype = wintypes.HGLOBAL
    k32.LockResource.argtypes = [wintypes.HGLOBAL]
    k32.LockResource.restype = ctypes.c_void_p
    k32.SizeofResource.argtypes = [wintypes.HMODULE, wintypes.HRSRC]
    k32.SizeofResource.restype = wintypes.DWORD

    hrsrc = k32.FindResourceW(module_handle, RESOURCE_NAME, RESOURCE_TYPE)
    if not hrsrc:
        return None
    size = int(k32.SizeofResource(module_handle, hrsrc) or 0)
    if size <= 0:
        return None
    hglobal = k32.LoadResource(module_handle, hrsrc)
    if not hglobal:
        return None
    ptr = k32.LockResource(hglobal)
    if not ptr:
        return None
    return ctypes.string_at(ptr, size)


def read_entry_stamp_info_from_exe(exe_path: Path | str) -> Optional[EntryStampInfo]:
    exe = Path(exe_path)
    if not exe.is_file():
        return None

    LOAD_LIBRARY_AS_DATAFILE = 0x00000002
    k32 = _kernel32()
    k32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    k32.LoadLibraryExW.restype = wintypes.HMODULE
    k32.FreeLibrary.argtypes = [wintypes.HMODULE]
    k32.FreeLibrary.restype = wintypes.BOOL

    module = k32.LoadLibraryExW(str(exe), None, LOAD_LIBRARY_AS_DATAFILE)
    if not module:
        return None
    try:
        raw = _load_resource_bytes(module)
    finally:
        k32.FreeLibrary(module)
    if not raw:
        return None
    return parse_entry_stamp_info(raw)


def read_entry_stamp_from_exe(exe_path: Path | str) -> Optional[str]:
    info = read_entry_stamp_info_from_exe(exe_path)
    return info.entry if info else None


def read_own_entry_stamp_info() -> Optional[EntryStampInfo]:
    k32 = _kernel32()
    k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    k32.GetModuleHandleW.restype = wintypes.HMODULE
    module = k32.GetModuleHandleW(None)
    if module:
        raw = _load_resource_bytes(module)
        if raw:
            parsed = parse_entry_stamp_info(raw)
            if parsed:
                return parsed

    from utils.app_paths import resolve_running_executable

    exe = resolve_running_executable()
    if exe:
        return read_entry_stamp_info_from_exe(exe)
    return None


def read_own_entry_stamp() -> Optional[str]:
    info = read_own_entry_stamp_info()
    return info.entry if info else None


def apply_entry_stamp(
    exe_path: Path | str,
    entry: str,
    *,
    bind_id: bytes | bytearray | memoryview | None = None,
) -> EntryStampInfo:
    """写入并回读校验；成功返回印记信息。"""
    entry_key = str(entry or "").strip().lower()
    if entry_key not in VALID_ENTRIES:
        raise ValueError(f"不支持的入口类型: {entry}")
    expected_bind = _normalize_bind_id(bind_id)
    if entry_key == ENTRY_EDITOR:
        expected_bind = _EMPTY_BIND_ID
    write_entry_stamp(exe_path, entry_key, bind_id=expected_bind)
    got = read_entry_stamp_info_from_exe(exe_path)
    if got is None or got.entry != entry_key:
        raise RuntimeError(
            f"入口印记校验失败: 期望 {entry_key}，实际 {got!r}（{exe_path}）"
        )
    if got.bind_id != expected_bind:
        raise RuntimeError(
            f"入口绑定校验失败: 期望 bind_id={expected_bind.hex()}，"
            f"实际 {got.bind_id.hex()}（{exe_path}）"
        )
    return got


def is_embedded_player_entry() -> bool:
    return read_own_entry_stamp() == ENTRY_PLAYER


def is_embedded_editor_entry() -> bool:
    return read_own_entry_stamp() == ENTRY_EDITOR
