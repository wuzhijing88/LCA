from __future__ import annotations

import ctypes
import struct
from ctypes import wintypes
from pathlib import Path
from typing import List, Tuple


RT_ICON = 3
RT_GROUP_ICON = 14
ICON_RESOURCE_ID = 1


def _make_int_resource(value: int) -> wintypes.LPCWSTR:
    return ctypes.cast(value, wintypes.LPCWSTR)


def _parse_ico(icon_path: Path) -> Tuple[bytes, List[bytes]]:
    data = icon_path.read_bytes()
    if len(data) < 6:
        raise ValueError(f"图标文件过小: {icon_path}")
    reserved, icon_type, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or icon_type != 1 or count < 1:
        raise ValueError(f"不是有效的 ICO 文件: {icon_path}")

    entries = []
    offset = 6
    for index in range(count):
        if offset + 16 > len(data):
            raise ValueError(f"ICO 目录损坏: {icon_path}")
        width, height, color_count, reserved_byte, planes, bit_count, bytes_in_res, image_offset = struct.unpack_from(
            "<BBBBHHII", data, offset
        )
        if image_offset + bytes_in_res > len(data):
            raise ValueError(f"ICO 图像数据越界: {icon_path}")
        image = data[image_offset:image_offset + bytes_in_res]
        entries.append((width, height, color_count, reserved_byte, planes, bit_count, image))
        offset += 16

    group = struct.pack("<HHH", 0, 1, len(entries))
    images: List[bytes] = []
    for index, (width, height, color_count, reserved_byte, planes, bit_count, image) in enumerate(entries, start=1):
        group += struct.pack(
            "<BBBBHHIH",
            width,
            height,
            color_count,
            reserved_byte,
            planes or 1,
            bit_count or 32,
            len(image),
            index,
        )
        images.append(image)
    return group, images


def inject_exe_icon(exe_path: Path | str, icon_path: Path | str) -> None:
    exe = Path(exe_path)
    icon = Path(icon_path)
    if not exe.is_file():
        raise FileNotFoundError(f"可执行文件不存在: {exe}")
    if not icon.is_file():
        raise FileNotFoundError(f"图标文件不存在: {icon}")

    group_bytes, images = _parse_ico(icon)
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

    update_handle = kernel32.BeginUpdateResourceW(str(exe), False)
    if not update_handle:
        raise OSError(ctypes.get_last_error(), f"BeginUpdateResourceW 失败: {exe}")

    committed = False
    try:
        for index, image in enumerate(images, start=1):
            buffer = ctypes.create_string_buffer(image)
            if not kernel32.UpdateResourceW(
                update_handle,
                _make_int_resource(RT_ICON),
                _make_int_resource(index),
                0,
                ctypes.cast(buffer, wintypes.LPVOID),
                len(image),
            ):
                raise OSError(ctypes.get_last_error(), f"写入 RT_ICON 失败: {index}")

        group_buffer = ctypes.create_string_buffer(group_bytes)
        if not kernel32.UpdateResourceW(
            update_handle,
            _make_int_resource(RT_GROUP_ICON),
            _make_int_resource(ICON_RESOURCE_ID),
            0,
            ctypes.cast(group_buffer, wintypes.LPVOID),
            len(group_bytes),
        ):
            raise OSError(ctypes.get_last_error(), "写入 RT_GROUP_ICON 失败")

        if not kernel32.EndUpdateResourceW(update_handle, False):
            raise OSError(ctypes.get_last_error(), f"EndUpdateResourceW 提交失败: {exe}")
        committed = True
    finally:
        if not committed:
            kernel32.EndUpdateResourceW(update_handle, True)
