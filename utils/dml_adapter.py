import logging
import os
import ctypes
from ctypes import wintypes

logger = logging.getLogger(__name__)

DXGI_ERROR_NOT_FOUND = 0x887A0002
DXGI_ADAPTER_FLAG_SOFTWARE = 0x00000002
DISCRETE_ADAPTER_MIN_DEDICATED_VIDEO = 512 * 1024 * 1024
DML_PROVIDER_NAME = "DmlExecutionProvider"
CUDA_PROVIDER_NAME = "CUDAExecutionProvider"
CPU_PROVIDER_NAME = "CPUExecutionProvider"
TENSORRT_PROVIDER_NAME = "TensorrtExecutionProvider"

GPU_PROVIDER_NAMES = frozenset(
    {
        DML_PROVIDER_NAME,
        CUDA_PROVIDER_NAME,
        TENSORRT_PROVIDER_NAME,
    }
)


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class DXGI_ADAPTER_DESC1(ctypes.Structure):
    _fields_ = [
        ("Description", wintypes.WCHAR * 128),
        ("VendorId", wintypes.UINT),
        ("DeviceId", wintypes.UINT),
        ("SubSysId", wintypes.UINT),
        ("Revision", wintypes.UINT),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", LUID),
        ("Flags", wintypes.UINT),
    ]


def _load_dxgi():
    try:
        return ctypes.windll.dxgi
    except Exception:
        return None


def _enum_dxgi_adapters():
    dxgi = _load_dxgi()
    if dxgi is None:
        return []

    try:
        import comtypes
        from comtypes import GUID, HRESULT, POINTER, COMMETHOD
        from comtypes import IUnknown
    except Exception as exc:
        logger.warning("DirectML adapter probe skipped: %s", exc)
        return []

    class IDXGIAdapter1(IUnknown):
        _iid_ = GUID("{29038f61-3839-4626-91fd-086879011a05}")
        _methods_ = [
            COMMETHOD([], HRESULT, "GetDesc1", (["out"], POINTER(DXGI_ADAPTER_DESC1), "pDesc")),
        ]

    class IDXGIFactory1(IUnknown):
        _iid_ = GUID("{770aae78-f26f-4dba-a829-253c83d1b387}")
        _methods_ = [
            COMMETHOD(
                [],
                HRESULT,
                "EnumAdapters1",
                (["in"], wintypes.UINT, "Adapter"),
                (["out"], POINTER(POINTER(IDXGIAdapter1)), "ppAdapter"),
            ),
        ]

    create_factory = dxgi.CreateDXGIFactory1
    create_factory.restype = ctypes.c_long  # HRESULT
    create_factory.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p]

    adapters = []
    comtypes.CoInitialize()
    try:
        factory_ptr = ctypes.c_void_p()
        hr = create_factory(ctypes.byref(IDXGIFactory1._iid_), ctypes.byref(factory_ptr))
        if hr != 0 or not factory_ptr.value:
            return adapters
        factory = ctypes.cast(factory_ptr, POINTER(IDXGIFactory1))
        idx = 0
        while True:
            try:
                adapter = factory.EnumAdapters1(idx)
            except comtypes.COMError as exc:
                if exc.hresult == DXGI_ERROR_NOT_FOUND:
                    break
                logger.debug("DXGI EnumAdapters1 调用失败：%s", exc)
                break
            if not adapter:
                break
            try:
                desc = adapter.GetDesc1()
            except comtypes.COMError as exc:
                logger.debug("DXGI GetDesc1 调用失败：%s", exc)
                break
            adapters.append(
                {
                    "index": idx,
                    "description": desc.Description.strip(),
                    "vendor_id": int(desc.VendorId),
                    "device_id": int(desc.DeviceId),
                    "dedicated_video": int(desc.DedicatedVideoMemory),
                    "shared_system": int(desc.SharedSystemMemory),
                    "flags": int(desc.Flags),
                }
            )
            idx += 1
    finally:
        try:
            comtypes.CoUninitialize()
        except Exception:
            pass

    return adapters


def _select_preferred_hardware_adapter(adapters):
    if not adapters:
        return None
    hardware_adapters = [
        a
        for a in adapters
        if (int(a.get("flags", 0)) & DXGI_ADAPTER_FLAG_SOFTWARE) == 0
    ]
    if not hardware_adapters:
        return None

    discrete = [
        a
        for a in hardware_adapters
        if int(a.get("dedicated_video", 0)) >= DISCRETE_ADAPTER_MIN_DEDICATED_VIDEO
    ]
    if discrete:
        return max(discrete, key=lambda a: int(a.get("dedicated_video", 0)))

    integrated = [
        a
        for a in hardware_adapters
        if int(a.get("shared_system", 0)) > 0 or int(a.get("dedicated_video", 0)) > 0
    ]
    if integrated:
        return max(
            integrated,
            key=lambda a: (
                int(a.get("dedicated_video", 0)),
                int(a.get("shared_system", 0)),
            ),
        )

    return hardware_adapters[0]


def select_dml_device_id():
    env_id = os.environ.get("LCA_DML_DEVICE_ID")
    if env_id is not None:
        try:
            device_id = int(env_id)
            return device_id, f"env:{device_id}"
        except ValueError:
            logger.warning("Invalid LCA_DML_DEVICE_ID: %s", env_id)

    adapters = _enum_dxgi_adapters()
    selected = _select_preferred_hardware_adapter(adapters)
    if not selected:
        # If DXGI probing is unavailable, let DirectML use its default adapter.
        return 0, "default"

    device_id = int(selected["index"])
    desc = selected.get("description") or f"adapter_{device_id}"
    return device_id, desc


def provider_name_from_entry(provider_entry):
    if isinstance(provider_entry, (tuple, list)) and provider_entry:
        return str(provider_entry[0])
    return str(provider_entry)


def is_gpu_onnx_provider(provider_name):
    return str(provider_name or "") in GPU_PROVIDER_NAMES


def build_onnxruntime_providers(available_providers):
    """Build the shared ONNX Runtime provider chain used by YOLO and map tracking.

    The app should not force a CPU/GPU mode here. Prefer DirectML when the runtime
    actually exposes it, then reuse the YOLO-style stable CPU fallback. CUDA and
    TensorRT may be listed by onnxruntime-gpu even when the matching native DLLs
    are not usable; initializing them can terminate the worker process before
    Python can catch an exception, so they are intentionally ignored.
    """
    normalized_providers = tuple(str(provider) for provider in (available_providers or ()) if provider)
    normalized_set = set(normalized_providers)
    providers = []
    device_desc = "auto"

    if DML_PROVIDER_NAME in normalized_set:
        device_id, device_desc = select_dml_device_id()
        providers.append((DML_PROVIDER_NAME, {"device_id": int(device_id)}))

    if CPU_PROVIDER_NAME in normalized_set:
        providers.append(CPU_PROVIDER_NAME)
        if device_desc == "auto":
            device_desc = CPU_PROVIDER_NAME

    if not providers:
        raise RuntimeError(
            f"No stable ONNX Runtime execution providers are available; "
            f"available providers: {list(normalized_providers)}"
        )

    return providers, device_desc
