#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WGC GPU→CPU 读回：staging texture + Map。"""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import POINTER, HRESULT, byref, c_void_p, wintypes

import comtypes
import cv2
import numpy as np
from comtypes import GUID, STDMETHOD
from dxcam._libs.d3d11 import (
    D3D11_CPU_ACCESS_READ,
    D3D11_TEXTURE2D_DESC,
    D3D11_USAGE_STAGING,
    DXGI_FORMAT_B8G8R8A8_UNORM,
    ID3D11Device,
    ID3D11DeviceContext,
    ID3D11Resource,
    ID3D11Texture2D,
)

logger = logging.getLogger(__name__)

IID_DXGI_ACCESS = GUID("{A9B3D012-3DF2-4EE3-B8D1-8695F457D3C1}")
IID_ID3D11Device = GUID("{db6f6ddb-ac77-4e88-8253-819df9bbf140}")
IID_ID3D11Texture2D = GUID("{6f15aaf2-d208-4e89-9ab4-489535d34f9c}")
D3D11_MAP_READ = 1
# IUnknown(3) + ID3D11DeviceChild(4) + Map/Unmap 在 ID3D11DeviceContext 中的槽位
_D3D11_CONTEXT_MAP_SLOT = 14
_D3D11_CONTEXT_UNMAP_SLOT = 15


class D3D11_MAPPED_SUBRESOURCE(ctypes.Structure):
    _fields_ = [
        ("pData", c_void_p),
        ("RowPitch", wintypes.UINT),
        ("DepthPitch", wintypes.UINT),
    ]


_MapFn = ctypes.WINFUNCTYPE(
    HRESULT,
    c_void_p,
    c_void_p,
    ctypes.c_uint,
    ctypes.c_uint,
    ctypes.c_uint,
    POINTER(D3D11_MAPPED_SUBRESOURCE),
)
_UnmapFn = ctypes.WINFUNCTYPE(None, c_void_p, c_void_p, ctypes.c_uint)
# IUnknown(3)+DeviceChild(4)+VSSetConstantBuffers..CopySubresourceRegion 之后
_D3D11_CONTEXT_COPY_RESOURCE_SLOT = 47
_CopyResourceFn = ctypes.WINFUNCTYPE(None, c_void_p, c_void_p, c_void_p)


def _com_ptr_value(ptr) -> int:
    return int(ctypes.cast(ptr, c_void_p).value or 0)


def _context_vtbl(context) -> POINTER(c_void_p):
    this = _com_ptr_value(context)
    return ctypes.cast(c_void_p.from_address(this), POINTER(c_void_p))


class IDirect3DDxgiInterfaceAccess(comtypes.IUnknown):
    _iid_ = IID_DXGI_ACCESS
    _methods_ = [
        STDMETHOD(HRESULT, "GetInterface", [POINTER(GUID), POINTER(c_void_p)]),
    ]


def _query_dxgi_access(winrt_obj):
    """从 PyWinRT 对象 QueryInterface 出 IDirect3DDxgiInterfaceAccess。"""
    if winrt_obj is None:
        raise RuntimeError("WinRT 对象为空")
    addr = c_void_p.from_address(id(winrt_obj) + int(object.__basicsize__)).value
    if not addr:
        raise RuntimeError("WinRT 对象没有 COM 指针")
    unk = ctypes.cast(addr, POINTER(comtypes.IUnknown))
    # ctypes.cast 得到的 comtypes 指针在析构时会 Release；AddRef 用来抵消，避免偷走 PyWinRT 的引用。
    unk.AddRef()
    return unk.QueryInterface(IDirect3DDxgiInterfaceAccess)


def _get_native_interface(winrt_obj, iid: GUID):
    access = _query_dxgi_access(winrt_obj)
    out = c_void_p()
    hr = access.GetInterface(byref(iid), byref(out))
    if hr != 0 or not out.value:
        raise RuntimeError(f"GetInterface 失败 hr=0x{hr & 0xFFFFFFFF:08X}")
    return out.value


def _mapped_bgra_to_bgr(bits_addr: int, pitch: int, width: int, height: int) -> np.ndarray:
    row_bytes = int(width) * 4
    pitch = int(pitch)
    height = int(height)
    if bits_addr <= 0 or pitch < row_bytes or width <= 0 or height <= 0:
        raise RuntimeError("staging Map 结果无效")

    total = pitch * height
    raw = (ctypes.c_uint8 * total).from_address(bits_addr)
    if pitch == row_bytes:
        bgra = np.frombuffer(raw, dtype=np.uint8, count=total).reshape((height, width, 4))
    else:
        packed = np.empty((height, width, 4), dtype=np.uint8)
        src = np.frombuffer(raw, dtype=np.uint8, count=total).reshape((height, pitch))
        packed[:] = src[:, :row_bytes].reshape((height, width, 4))
        bgra = packed

    return cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)


class WGCStagingReadback:
    """共享 D3D11 设备上的 staging 读回。CopyResource/Map 必须加锁。"""

    def __init__(self, winrt_device):
        device_ptr = _get_native_interface(winrt_device, IID_ID3D11Device)
        self._device = ctypes.cast(device_ptr, POINTER(ID3D11Device))
        self._context = POINTER(ID3D11DeviceContext)()
        self._device.GetImmediateContext(byref(self._context))
        if not self._context:
            raise RuntimeError("GetImmediateContext 失败")
        vtbl = _context_vtbl(self._context)
        self._map = _MapFn(vtbl[_D3D11_CONTEXT_MAP_SLOT])
        self._unmap = _UnmapFn(vtbl[_D3D11_CONTEXT_UNMAP_SLOT])
        self._copy_resource = _CopyResourceFn(vtbl[_D3D11_CONTEXT_COPY_RESOURCE_SLOT])
        self._lock = threading.Lock()
        self._staging = None
        self._staging_w = 0
        self._staging_h = 0
        self._staging_format = 0

    def _ensure_staging(self, width: int, height: int, fmt: int) -> None:
        if (
            self._staging is not None
            and self._staging_w == width
            and self._staging_h == height
            and self._staging_format == fmt
        ):
            return

        desc = D3D11_TEXTURE2D_DESC()
        desc.Width = int(width)
        desc.Height = int(height)
        desc.MipLevels = 1
        desc.ArraySize = 1
        desc.Format = int(fmt)
        desc.SampleDesc.Count = 1
        desc.SampleDesc.Quality = 0
        desc.Usage = D3D11_USAGE_STAGING
        desc.BindFlags = 0
        desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ
        desc.MiscFlags = 0

        staging = POINTER(ID3D11Texture2D)()
        hr = self._device.CreateTexture2D(byref(desc), None, byref(staging))
        if (hr not in (0, None)) or (not _com_ptr_value(staging)):
            code = 0 if hr in (0, None) else int(hr)
            raise RuntimeError(f"CreateTexture2D staging 失败 hr=0x{code & 0xFFFFFFFF:08X}")

        self._staging = staging
        self._staging_w = int(width)
        self._staging_h = int(height)
        self._staging_format = int(fmt)

    def surface_to_bgr(self, winrt_surface) -> np.ndarray:
        src_ptr = _get_native_interface(winrt_surface, IID_ID3D11Texture2D)
        src = ctypes.cast(src_ptr, POINTER(ID3D11Texture2D))
        desc = D3D11_TEXTURE2D_DESC()
        src.GetDesc(byref(desc))
        width = int(desc.Width)
        height = int(desc.Height)
        fmt = int(desc.Format)
        if width <= 0 or height <= 0 or width > 65535 or height > 65535:
            raise RuntimeError(f"无效的帧尺寸: {width}x{height}")
        if fmt != DXGI_FORMAT_B8G8R8A8_UNORM:
            raise RuntimeError(f"不支持的像素格式: {fmt}")

        with self._lock:
            self._ensure_staging(width, height, fmt)
            ctx_ptr = _com_ptr_value(self._context)
            staging_ptr = _com_ptr_value(self._staging)
            if not ctx_ptr or not staging_ptr or not src_ptr:
                raise RuntimeError(
                    f"CopyResource 指针无效 context={ctx_ptr} staging={staging_ptr} src={src_ptr}"
                )
            # 走 vtable，避免 comtypes.cast 在 CopyResource 参数上再 Release 一次 staging。
            self._copy_resource(ctx_ptr, staging_ptr, int(src_ptr))
            mapped = D3D11_MAPPED_SUBRESOURCE()
            hr = self._map(
                ctx_ptr,
                staging_ptr,
                0,
                D3D11_MAP_READ,
                0,
                byref(mapped),
            )
            if hr != 0 or not mapped.pData:
                raise RuntimeError(f"ID3D11DeviceContext.Map 失败 hr=0x{hr & 0xFFFFFFFF:08X}")
            try:
                result = _mapped_bgra_to_bgr(int(mapped.pData), int(mapped.RowPitch), width, height)
                return np.ascontiguousarray(result)
            finally:
                self._unmap(ctx_ptr, staging_ptr, 0)

    def _drop_staging_locked(self) -> None:
        self._staging = None
        self._staging_w = 0
        self._staging_h = 0
        self._staging_format = 0

    def release_staging(self) -> None:
        with self._lock:
            self._drop_staging_locked()

    def flush(self) -> bool:
        return False

    def close(self) -> None:
        with self._lock:
            self._drop_staging_locked()
            self._context = None
            self._device = None
            self._map = None
            self._unmap = None
            self._copy_resource = None


def create_staging_readback(winrt_device) -> WGCStagingReadback:
    if winrt_device is None:
        raise RuntimeError("WinRT D3D 设备为空")
    return WGCStagingReadback(winrt_device)
