#!/usr/bin/env python3
"""Force PE Subsystem=WINDOWS (2) on PluginHost.exe so no console window appears."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

IMAGE_NT_OPTIONAL_HDR32_MAGIC = 0x10B
IMAGE_NT_OPTIONAL_HDR64_MAGIC = 0x20B
IMAGE_SUBSYSTEM_WINDOWS_GUI = 2


def set_windows_subsystem(path: Path) -> bool:
    data = bytearray(path.read_bytes())
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise ValueError(f"not a PE image: {path}")
    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_off + 24 + 2 > len(data) or data[pe_off : pe_off + 4] != b"PE\0\0":
        raise ValueError(f"invalid PE header: {path}")
    magic = struct.unpack_from("<H", data, pe_off + 24)[0]
    # OptionalHeader.Subsystem is at +68 for both PE32 and PE32+.
    sub_off = pe_off + 24 + 68
    if magic not in (IMAGE_NT_OPTIONAL_HDR32_MAGIC, IMAGE_NT_OPTIONAL_HDR64_MAGIC):
        raise ValueError(f"unsupported optional header magic {magic:#x}: {path}")
    if sub_off + 2 > len(data):
        raise ValueError(f"truncated optional header: {path}")
    current = struct.unpack_from("<H", data, sub_off)[0]
    if current == IMAGE_SUBSYSTEM_WINDOWS_GUI:
        return False
    struct.pack_into("<H", data, sub_off, IMAGE_SUBSYSTEM_WINDOWS_GUI)
    path.write_bytes(data)
    return True


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: set_windows_subsystem.py <exe> [<exe>...]", file=sys.stderr)
        return 2
    for raw in argv[1:]:
        path = Path(raw)
        changed = set_windows_subsystem(path)
        state = "patched" if changed else "already-windows"
        print(f"{path}: {state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
