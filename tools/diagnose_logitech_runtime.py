#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""罗技输入运行时诊断工具。

当 LCA 报告 "罗技输入驱动不可用" 时运行本脚本，收集虚拟输入设备、
总线驱动接口、G HUB 进程/服务的真实状态，用于定位是设备未挂载、
被禁用、驱动加载失败，还是 G HUB 版本更换了设备标识。

用法：
    venv\\Scripts\\python.exe tools\\diagnose_logitech_runtime.py

输出全部为 ASCII/数据形式，避免控制台编码问题。
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes

try:
    import winreg
except ImportError:  # pragma: no cover - Windows only
    winreg = None


# CM_Get_DevNode_Status 的 problem code 含义（节选常见项）。
CM_PROBLEM_TEXT = {
    0: "no problem",
    1: "CM_PROB_NOT_CONFIGURED (无驱动)",
    3: "CM_PROB_OUT_OF_MEMORY",
    10: "CM_PROB_FAILED_START (驱动启动失败)",
    12: "CM_PROB_NORMAL_CONFLICT",
    14: "CM_PROB_NEED_RESTART (需重启)",
    18: "CM_PROB_REINSTALL (需重装驱动)",
    19: "CM_PROB_REGISTRY (注册表损坏)",
    22: "CM_PROB_DISABLED (设备被禁用)",
    24: "CM_PROB_DEVICE_NOT_THERE (设备不存在)",
    28: "CM_PROB_FAILED_INSTALL (驱动未安装)",
    31: "CM_PROB_FAILED_POST_START",
    43: "CM_PROB_FAILED_POST_START (驱动报告失败)",
    45: "CM_PROB_PHANTOM (幽灵设备/当前未挂载)",
}

DN_STARTED = 0x00000008
CM_LOCATE_DEVNODE_PHANTOM = 0x00000004

_GHUB_BUS_INTERFACE_GUIDS = (
    ("GHub", "{1abc05c0-c378-41b9-9cef-df1aba82b015}"),
    ("GHub", "{dfbedcdb-2148-416d-9e4d-cecc2424128c}"),
    ("LGS", "{df31f106-d870-453d-8fa1-ec8ab43fa1d2}"),
    ("LGS", "{5bada891-842b-4296-a496-68ae931aa16c}"),
)

_ENUM_ROOTS = (
    r"SYSTEM\CurrentControlSet\Enum\LGHUBDevice",
    r"SYSTEM\CurrentControlSet\Enum\LogiDevice",
)


def _cfgmgr():
    lib = ctypes.WinDLL("cfgmgr32", use_last_error=True)
    locate = lib.CM_Locate_DevNodeW
    locate.argtypes = (ctypes.POINTER(wintypes.ULONG), wintypes.LPWSTR, wintypes.ULONG)
    locate.restype = wintypes.ULONG
    status = lib.CM_Get_DevNode_Status
    status.argtypes = (
        ctypes.POINTER(wintypes.ULONG),
        ctypes.POINTER(wintypes.ULONG),
        wintypes.ULONG,
        wintypes.ULONG,
    )
    status.restype = wintypes.ULONG
    return locate, status


def _describe_devnode(instance_id: str) -> str:
    locate, get_status = _cfgmgr()
    devinst = wintypes.ULONG()
    phantom = False
    rc = locate(ctypes.byref(devinst), instance_id, 0)
    if rc != 0:
        rc = locate(ctypes.byref(devinst), instance_id, CM_LOCATE_DEVNODE_PHANTOM)
        phantom = True
        if rc != 0:
            return f"locate failed (CR={rc})"
    status = wintypes.ULONG()
    problem = wintypes.ULONG()
    rc = get_status(ctypes.byref(status), ctypes.byref(problem), devinst, 0)
    if rc != 0:
        return f"get_status failed (CR={rc}){' [phantom]' if phantom else ''}"
    started = bool(status.value & DN_STARTED)
    problem_text = CM_PROBLEM_TEXT.get(problem.value, f"problem={problem.value}")
    tag = " [phantom]" if phantom else ""
    return f"status=0x{status.value:08X} started={started} problem={problem.value} ({problem_text}){tag}"


def _read_values(path: str, names):
    if winreg is None:
        return {}
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ)
    except OSError:
        return {}
    values = {}
    try:
        for name in names:
            try:
                values[name] = winreg.QueryValueEx(key, name)[0]
            except OSError:
                pass
    finally:
        winreg.CloseKey(key)
    return values


def _subkeys(path: str):
    if winreg is None:
        return []
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ)
    except OSError:
        return []
    result = []
    try:
        count = winreg.QueryInfoKey(key)[0]
        for i in range(count):
            result.append(winreg.EnumKey(key, i))
    finally:
        winreg.CloseKey(key)
    return result


def report_devices():
    print("=" * 70)
    print("[1] 虚拟输入设备节点 (LGHUBDevice / LogiDevice)")
    print("=" * 70)
    found_any = False
    for root in _ENUM_ROOTS:
        for hardware_id in _subkeys(root):
            device_path = f"{root}\\{hardware_id}"
            for instance in _subkeys(device_path):
                found_any = True
                instance_path = f"{device_path}\\{instance}"
                enum_root = root.rsplit("\\", 1)[-1]
                instance_id = f"{enum_root}\\{hardware_id}\\{instance}"
                info = _read_values(instance_path, ("DeviceDesc", "Service", "ConfigFlags"))
                desc = str(info.get("DeviceDesc", "")).split(";")[-1]
                config_flags = info.get("ConfigFlags", 0)
                disabled = bool(int(config_flags or 0) & 0x1)
                print(f"  {instance_id}")
                print(f"      desc={desc!r} service={info.get('Service')!r} "
                      f"ConfigFlags=0x{int(config_flags or 0):X} disabled={disabled}")
                print(f"      {_describe_devnode(instance_id)}")
    if not found_any:
        print("  (未发现任何罗技虚拟输入设备节点 —— G HUB 可能未创建虚拟设备)")


def report_interfaces():
    print("=" * 70)
    print("[2] 总线驱动设备接口 (IbInputSimulator 实际打开的对象)")
    print("=" * 70)
    base = r"SYSTEM\CurrentControlSet\Control\DeviceClasses"
    for label, guid in _GHUB_BUS_INTERFACE_GUIDS:
        class_path = f"{base}\\{guid}"
        interfaces = _subkeys(class_path)
        if not interfaces:
            print(f"  [{label}] {guid}: 不存在或无接口实例")
            continue
        print(f"  [{label}] {guid}: {len(interfaces)} 个接口实例")
        for name in interfaces:
            linked = 0
            for suffix in ("#\\Control", "Control"):
                vals = _read_values(f"{class_path}\\{name}\\{suffix}", ("Linked",))
                if "Linked" in vals:
                    linked = int(vals["Linked"] or 0)
                    break
            print(f"      linked={linked}  {name[:64]}")


def report_processes_and_services():
    print("=" * 70)
    print("[3] G HUB 进程与服务")
    print("=" * 70)
    try:
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15,
        ).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        out = ""
    for proc in ("lghub.exe", "lghub_agent.exe", "lghub_system_tray.exe", "lghub_updater.exe"):
        print(f"  process {proc}: {'RUNNING' if proc in out else 'not running'}")
    for svc in ("logi_joy_bus_enum", "LGHUBUpdaterService"):
        try:
            q = subprocess.run(["sc", "query", svc], capture_output=True, text=True, timeout=15).stdout
            state = next((l.split(":", 1)[-1].strip() for l in q.splitlines() if "STATE" in l), "unknown")
        except (OSError, subprocess.SubprocessError):
            state = "query failed"
        print(f"  service {svc}: {state}")


def report_drivers():
    print("=" * 70)
    print("[4] 内核驱动文件版本")
    print("=" * 70)
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
    from pathlib import Path
    import os
    from utils.logitech_runtime import _read_file_version, MIN_GHUB_DRIVER_VERSION

    driver_dir = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers"
    for name in ("logi_joy_bus_enum.x64.sys", "logi_joy_xlcore.x64.sys", "logi_joy_vir_hid.x64.sys"):
        version = _read_file_version(driver_dir / name)
        print(f"  {name}: {version or '不存在'}")
    print(f"  (最低要求 {MIN_GHUB_DRIVER_VERSION})")


def main():
    if sys.platform != "win32":
        print("本工具仅适用于 Windows。")
        return
    report_devices()
    print()
    report_interfaces()
    print()
    report_processes_and_services()
    print()
    report_drivers()


if __name__ == "__main__":
    main()
