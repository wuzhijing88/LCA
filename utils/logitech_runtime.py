"""Select and validate the native Logitech input runtime on Windows."""

from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping, Optional, Tuple

try:
    import winreg
except ImportError:  # pragma: no cover - Windows-only application
    winreg = None


SUPPORTED_LGS_VERSION = "9.02.65"
SUPPORTED_GHUB_VERSION = "2026.4.919028"
SUPPORTED_GHUB_DRIVER_VERSION = "2026.0.0.0"

_UNINSTALL_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
_APP_PATHS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\LCore.exe"
_GHUB_MOUSE_ENUM_KEY = (
    r"SYSTEM\CurrentControlSet\Enum\LGHUBDevice\VID_046D&PID_C231"
)
_LGS_MOUSE_ENUM_KEY = (
    r"SYSTEM\CurrentControlSet\Enum\LogiDevice\VID_046D&PID_C231"
)
_GHUB_MOUSE_INSTANCE_PREFIX = r"LGHUBDevice\VID_046D&PID_C231"
_LGS_MOUSE_INSTANCE_PREFIX = r"LogiDevice\VID_046D&PID_C231"
_DN_STARTED = 0x00000008


@dataclass(frozen=True)
class LogitechRuntimeResult:
    compatible: bool
    send_type: str = ""
    detected_name: str = ""
    detected_version: str = ""
    source: str = ""
    reason: str = ""

    def user_message(self) -> str:
        if self.compatible:
            if self.send_type == "LogitechGHubNew":
                return (
                    f"已检测到 Logitech G HUB {self.detected_version}，"
                    "将使用 G HUB 新版输入驱动。"
                )
            return (
                f"已检测到 Logitech Gaming Software {self.detected_version}，"
                "将使用 LGS 输入驱动。"
            )

        if self.reason == "unsupported_ghub_version":
            return (
                f"当前检测到：{self.detected_name} {self.detected_version or '未知版本'}。\n"
                f"当前已实测支持 Logitech G HUB {SUPPORTED_GHUB_VERSION}。"
            )
        if self.reason in {"ghub_driver_missing", "unsupported_ghub_driver"}:
            return (
                f"当前检测到：{self.detected_name} {self.detected_version or '未知版本'}，"
                "但 G HUB 虚拟输入驱动不完整或版本不匹配。\n"
                "请完整重装 G HUB，并在安装时关闭“传输当前设置”。"
            )
        if self.reason == "ghub_virtual_mouse_not_started":
            return (
                f"当前检测到：{self.detected_name} {self.detected_version or '未知版本'}，"
                "但 Logitech G HUB Virtual Mouse 未启动。\n"
                "请重装 G HUB，关闭“传输当前设置”，然后重启系统。"
            )
        if self.reason in {"unsupported_lgs_version", "lgs_binary_not_found"}:
            return (
                f"当前检测到：{self.detected_name} {self.detected_version or '未知版本'}。\n"
                f"LGS 输入驱动仅支持 Logitech Gaming Software {SUPPORTED_LGS_VERSION}。"
            )
        if self.reason == "lgs_virtual_mouse_not_started":
            return (
                f"当前检测到 Logitech Gaming Software {self.detected_version or '未知版本'}，"
                "但 Logitech Gaming Virtual Mouse 未启动。"
            )
        return (
            "未检测到可用的 Logitech G HUB 或 Logitech Gaming Software 输入驱动。"
        )

    def driver_error(self) -> str:
        return (
            "LogitechRuntimeUnavailable: "
            f"detected={self.detected_name or 'not-installed'} "
            f"{self.detected_version or 'unknown'}, reason={self.reason or 'unknown'}"
        )


@dataclass(frozen=True)
class _InstalledProduct:
    name: str
    version: str
    install_location: str
    display_icon: str
    key_name: str
    publisher: str
    source: str


class _VSFixedFileInfo(ctypes.Structure):
    _fields_ = (
        ("dwSignature", wintypes.DWORD),
        ("dwStrucVersion", wintypes.DWORD),
        ("dwFileVersionMS", wintypes.DWORD),
        ("dwFileVersionLS", wintypes.DWORD),
        ("dwProductVersionMS", wintypes.DWORD),
        ("dwProductVersionLS", wintypes.DWORD),
        ("dwFileFlagsMask", wintypes.DWORD),
        ("dwFileFlags", wintypes.DWORD),
        ("dwFileOS", wintypes.DWORD),
        ("dwFileType", wintypes.DWORD),
        ("dwFileSubtype", wintypes.DWORD),
        ("dwFileDateMS", wintypes.DWORD),
        ("dwFileDateLS", wintypes.DWORD),
    )


def _parse_version(version: str) -> Tuple[int, ...]:
    match = re.search(r"(?<!\d)(\d+(?:[.,]\d+){1,})(?!\d)", str(version or ""))
    if not match:
        return ()
    return tuple(int(part) for part in re.split(r"[.,]", match.group(1)))


def _version_matches(version: str, required: str) -> bool:
    actual_parts = _parse_version(version)
    required_parts = _parse_version(required)
    if not actual_parts or not required_parts:
        return False
    length = max(len(actual_parts), len(required_parts))
    actual_parts += (0,) * (length - len(actual_parts))
    required_parts += (0,) * (length - len(required_parts))
    return actual_parts == required_parts


def _registry_views() -> Tuple[Tuple[str, int], ...]:
    if winreg is None:
        return ()
    result = []
    seen = set()
    for name, flag in (
        ("64", getattr(winreg, "KEY_WOW64_64KEY", 0)),
        ("32", getattr(winreg, "KEY_WOW64_32KEY", 0)),
    ):
        if flag not in seen:
            seen.add(flag)
            result.append((name, flag))
    return tuple(result)


def _read_registry_value(key, name: Optional[str]) -> str:
    try:
        value, _ = winreg.QueryValueEx(key, name)
        return str(value or "").strip()
    except OSError:
        return ""


def _iter_uninstall_products() -> Iterator[_InstalledProduct]:
    if winreg is None:
        return
    seen = set()
    for hive_name, hive in (
        ("HKLM", winreg.HKEY_LOCAL_MACHINE),
        ("HKCU", winreg.HKEY_CURRENT_USER),
    ):
        for view_name, view_flag in _registry_views():
            try:
                root = winreg.OpenKey(
                    hive,
                    _UNINSTALL_KEY,
                    0,
                    winreg.KEY_READ | view_flag,
                )
            except OSError:
                continue
            try:
                count = winreg.QueryInfoKey(root)[0]
                for index in range(count):
                    try:
                        key_name = winreg.EnumKey(root, index)
                        key = winreg.OpenKey(root, key_name, 0, winreg.KEY_READ)
                    except OSError:
                        continue
                    try:
                        product = _InstalledProduct(
                            name=_read_registry_value(key, "DisplayName") or key_name,
                            version=_read_registry_value(key, "DisplayVersion"),
                            install_location=_read_registry_value(key, "InstallLocation"),
                            display_icon=_read_registry_value(key, "DisplayIcon"),
                            key_name=key_name,
                            publisher=_read_registry_value(key, "Publisher"),
                            source=f"registry:{hive_name}:{view_name}",
                        )
                        identity = (
                            product.name.lower(),
                            product.version.lower(),
                            product.install_location.lower(),
                        )
                        if identity not in seen:
                            seen.add(identity)
                            yield product
                    finally:
                        winreg.CloseKey(key)
            finally:
                winreg.CloseKey(root)


def _compact_product_text(product: _InstalledProduct) -> str:
    return re.sub(
        r"[\s_\-]+",
        "",
        " ".join((product.name, product.key_name, product.publisher)).lower(),
    )


def _is_ghub_product(product: _InstalledProduct) -> bool:
    text = _compact_product_text(product)
    return "logitechghub" in text or text == "ghub"


def _is_lgs_product(product: _InstalledProduct) -> bool:
    text = _compact_product_text(product)
    if _is_ghub_product(product) or "logitech" not in text:
        return False
    return (
        "gamingsoftware" in text
        or "游戏软件" in text
        or product.version.startswith("9.02")
    )


def _clean_executable_path(value: str) -> str:
    text = os.path.expandvars(str(value or "").strip())
    if not text:
        return ""
    if text.startswith('"'):
        end = text.find('"', 1)
        if end > 1:
            return text[1:end]
    match = re.match(r"(?i)^(.+?\.exe)(?:\s|,|$)", text)
    if match:
        return match.group(1).strip().strip('"')
    return re.sub(r",\s*-?\d+\s*$", "", text).strip().strip('"')


def _read_file_version(path: Path) -> str:
    if os.name != "nt" or not path.is_file():
        return ""
    try:
        version_dll = ctypes.WinDLL("version", use_last_error=True)
        get_size = version_dll.GetFileVersionInfoSizeW
        get_size.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD))
        get_size.restype = wintypes.DWORD
        get_info = version_dll.GetFileVersionInfoW
        get_info.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
        )
        get_info.restype = wintypes.BOOL
        query = version_dll.VerQueryValueW
        query.argtypes = (
            wintypes.LPCVOID,
            wintypes.LPCWSTR,
            ctypes.POINTER(wintypes.LPVOID),
            ctypes.POINTER(wintypes.UINT),
        )
        query.restype = wintypes.BOOL

        ignored = wintypes.DWORD()
        size = get_size(str(path), ctypes.byref(ignored))
        if not size:
            return ""
        buffer = ctypes.create_string_buffer(size)
        if not get_info(str(path), 0, size, buffer):
            return ""
        pointer = wintypes.LPVOID()
        length = wintypes.UINT()
        if not query(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return ""
        if length.value < ctypes.sizeof(_VSFixedFileInfo):
            return ""
        info = ctypes.cast(pointer, ctypes.POINTER(_VSFixedFileInfo)).contents
        if info.dwSignature != 0xFEEF04BD:
            return ""
        parts = (
            (info.dwFileVersionMS >> 16) & 0xFFFF,
            info.dwFileVersionMS & 0xFFFF,
            (info.dwFileVersionLS >> 16) & 0xFFFF,
            info.dwFileVersionLS & 0xFFFF,
        )
        return ".".join(str(part) for part in parts)
    except (AttributeError, OSError, ValueError):
        return ""


def _iter_lcore_candidates(products: Tuple[_InstalledProduct, ...]) -> Iterator[Path]:
    seen = set()

    def emit(path: Path) -> Iterator[Path]:
        key = os.path.normcase(os.path.abspath(str(path)))
        if key not in seen:
            seen.add(key)
            yield path

    for product in products:
        location = _clean_executable_path(product.install_location)
        if location:
            path = Path(location)
            yield from emit(path if path.name.lower() == "lcore.exe" else path / "LCore.exe")
        icon = _clean_executable_path(product.display_icon)
        if icon and Path(icon).name.lower() == "lcore.exe":
            yield from emit(Path(icon))

    if winreg is not None:
        for _, hive in (("HKLM", winreg.HKEY_LOCAL_MACHINE), ("HKCU", winreg.HKEY_CURRENT_USER)):
            for _, view_flag in _registry_views():
                try:
                    key = winreg.OpenKey(
                        hive,
                        _APP_PATHS_KEY,
                        0,
                        winreg.KEY_READ | view_flag,
                    )
                except OSError:
                    continue
                try:
                    value = _clean_executable_path(
                        _read_registry_value(key, None) or _read_registry_value(key, "Path")
                    )
                    if value:
                        path = Path(value)
                        yield from emit(
                            path if path.name.lower() == "lcore.exe" else path / "LCore.exe"
                        )
                finally:
                    winreg.CloseKey(key)

    for env_name in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        root = str(os.environ.get(env_name, "") or "").strip()
        if root:
            yield from emit(Path(root) / "Logitech Gaming Software" / "LCore.exe")


def _device_started(instance_id: str) -> bool:
    if os.name != "nt":
        return False
    try:
        cfgmgr32 = ctypes.WinDLL("cfgmgr32", use_last_error=True)
        locate = cfgmgr32.CM_Locate_DevNodeW
        locate.argtypes = (
            ctypes.POINTER(wintypes.ULONG),
            wintypes.LPWSTR,
            wintypes.ULONG,
        )
        locate.restype = wintypes.ULONG
        get_status = cfgmgr32.CM_Get_DevNode_Status
        get_status.argtypes = (
            ctypes.POINTER(wintypes.ULONG),
            ctypes.POINTER(wintypes.ULONG),
            wintypes.ULONG,
            wintypes.ULONG,
        )
        get_status.restype = wintypes.ULONG

        devinst = wintypes.ULONG()
        if locate(ctypes.byref(devinst), str(instance_id), 0) != 0:
            return False
        status = wintypes.ULONG()
        problem = wintypes.ULONG()
        if get_status(ctypes.byref(status), ctypes.byref(problem), devinst, 0) != 0:
            return False
        return bool(status.value & _DN_STARTED) and problem.value == 0
    except (AttributeError, OSError, ValueError):
        return False


def _find_started_device(enum_key: str, instance_prefix: str) -> str:
    if winreg is None:
        return ""
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, enum_key, 0, winreg.KEY_READ)
    except OSError:
        return ""
    try:
        count = winreg.QueryInfoKey(root)[0]
        for index in range(count):
            try:
                suffix = winreg.EnumKey(root, index)
            except OSError:
                continue
            instance_id = f"{instance_prefix}\\{suffix}"
            if _device_started(instance_id):
                return instance_id
    finally:
        winreg.CloseKey(root)
    return ""


def _ghub_driver_versions() -> Tuple[Tuple[str, str], ...]:
    system_root = Path(str(os.environ.get("SystemRoot", r"C:\Windows")))
    driver_dir = system_root / "System32" / "drivers"
    names = (
        "logi_joy_bus_enum.x64.sys",
        "logi_joy_xlcore.x64.sys",
        "logi_joy_vir_hid.x64.sys",
    )
    return tuple((name, _read_file_version(driver_dir / name)) for name in names)


def detect_logitech_runtime() -> LogitechRuntimeResult:
    products = tuple(_iter_uninstall_products())
    ghub_products = tuple(product for product in products if _is_ghub_product(product))
    if ghub_products:
        product = ghub_products[0]
        if not _version_matches(product.version, SUPPORTED_GHUB_VERSION):
            return LogitechRuntimeResult(
                compatible=False,
                detected_name=product.name,
                detected_version=product.version,
                source=product.source,
                reason="unsupported_ghub_version",
            )

        driver_versions = _ghub_driver_versions()
        if any(not version for _, version in driver_versions):
            return LogitechRuntimeResult(
                compatible=False,
                detected_name=product.name,
                detected_version=product.version,
                source=product.source,
                reason="ghub_driver_missing",
            )
        if any(
            not _version_matches(version, SUPPORTED_GHUB_DRIVER_VERSION)
            for _, version in driver_versions
        ):
            versions = ", ".join(f"{name}={version}" for name, version in driver_versions)
            return LogitechRuntimeResult(
                compatible=False,
                detected_name=product.name,
                detected_version=product.version,
                source=versions,
                reason="unsupported_ghub_driver",
            )

        mouse_instance = _find_started_device(
            _GHUB_MOUSE_ENUM_KEY,
            _GHUB_MOUSE_INSTANCE_PREFIX,
        )
        if not mouse_instance:
            return LogitechRuntimeResult(
                compatible=False,
                detected_name=product.name,
                detected_version=product.version,
                source=product.source,
                reason="ghub_virtual_mouse_not_started",
            )
        return LogitechRuntimeResult(
            compatible=True,
            send_type="LogitechGHubNew",
            detected_name=product.name,
            detected_version=product.version,
            source=mouse_instance,
            reason="ghub_ready",
        )

    lgs_products = tuple(product for product in products if _is_lgs_product(product))
    detected_version = ""
    detected_source = ""
    for candidate in _iter_lcore_candidates(lgs_products):
        version = _read_file_version(candidate)
        if not version:
            continue
        if not detected_version:
            detected_version = version
            detected_source = str(candidate)
        if _version_matches(version, SUPPORTED_LGS_VERSION):
            mouse_instance = _find_started_device(
                _LGS_MOUSE_ENUM_KEY,
                _LGS_MOUSE_INSTANCE_PREFIX,
            )
            if not mouse_instance:
                return LogitechRuntimeResult(
                    compatible=False,
                    detected_name="Logitech Gaming Software",
                    detected_version=version,
                    source=str(candidate),
                    reason="lgs_virtual_mouse_not_started",
                )
            return LogitechRuntimeResult(
                compatible=True,
                send_type="Logitech",
                detected_name="Logitech Gaming Software",
                detected_version=version,
                source=mouse_instance,
                reason="lgs_ready",
            )

    if lgs_products or detected_version:
        product = lgs_products[0] if lgs_products else None
        return LogitechRuntimeResult(
            compatible=False,
            detected_name=(product.name if product else "Logitech Gaming Software"),
            detected_version=detected_version or (product.version if product else ""),
            source=detected_source or (product.source if product else ""),
            reason="unsupported_lgs_version" if detected_version else "lgs_binary_not_found",
        )

    return LogitechRuntimeResult(compatible=False, reason="not_installed")


def is_logitech_ibinputsimulator_configured(
    config: Optional[Mapping[str, object]],
) -> bool:
    values = dict(config or {})
    legacy_backend = str(
        values.get("foreground_driver_backend", "interception") or "interception"
    ).strip().lower()
    mouse_backend = str(
        values.get("foreground_mouse_driver_backend", legacy_backend) or legacy_backend
    ).strip().lower()
    keyboard_backend = str(
        values.get("foreground_keyboard_driver_backend", legacy_backend) or legacy_backend
    ).strip().lower()
    driver_name = re.sub(
        r"[\s_-]+",
        "",
        str(values.get("ibinputsimulator_driver", "Logitech") or "Logitech"),
    ).lower()
    return driver_name == "logitech" and "ibinputsimulator" in (
        mouse_backend,
        keyboard_backend,
    )


__all__ = [
    "SUPPORTED_GHUB_DRIVER_VERSION",
    "SUPPORTED_GHUB_VERSION",
    "SUPPORTED_LGS_VERSION",
    "LogitechRuntimeResult",
    "detect_logitech_runtime",
    "is_logitech_ibinputsimulator_configured",
]
