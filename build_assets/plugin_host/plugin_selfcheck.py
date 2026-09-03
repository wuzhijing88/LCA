# -*- coding: utf-8 -*-
"""大漠插件真机自检。

  python build_assets/plugin_host/plugin_selfcheck.py --no-auth
      只查运行库文件、架构、宿主拉起 / 管道协议 / 退出。不联网，不消耗注册次数。

  python build_assets/plugin_host/plugin_selfcheck.py --title "窗口标题" [--title ...] [--hwnd 123456 ...]
      用配置里的注册码起共享宿主（1 次 Reg），对每个窗口依次：按当前插件参数试绑 → IsBind 核实 →
      读客户区尺寸 → MoveTo(0,0)（只移动不点击）→ 解绑；最后打印宿主对象池统计。
      期望：累计注册次数 == 窗口数（每个窗口一个 dm 对象，解绑后回池不重复注册）。
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

OK = "[OK]  "
FAIL = "[FAIL]"


def _line(ok: bool, text: str) -> bool:
    print(f"{OK if ok else FAIL} {text}")
    return ok


def check_runtime_files() -> bool:
    from utils.plugin.runtime import check_plugin_runtime_arch, find_plugin_dir

    directory = find_plugin_dir()
    if directory is None:
        return _line(False, "运行库：tools/plugin 缺少 PluginHost.exe / dm.dll / RegDll.dll")
    _line(True, f"运行库目录：{directory}")
    problem = check_plugin_runtime_arch(directory)
    return _line(not problem, f"架构校验：{problem or 'PluginHost.exe 与 dm.dll 均为 x86'}")


def check_host_protocol() -> bool:
    """起一个私有管道的宿主，不发 init：验证进程、协议与关闭路径。"""
    from utils.plugin import runtime as r

    directory = r.find_plugin_dir()
    if directory is None:
        return False
    pipe = f"{r.pipe_name(os.getpid())}-selfcheck-{int(time.time() * 1000) % 100000}"
    proc = None
    pipe_file = None
    try:
        proc = subprocess.Popen(
            r.launch_host_command(directory / "PluginHost.exe", pipe),
            cwd=str(directory),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        pipe_file = r._connect_named_pipe(pipe, timeout=5.0)
        rpc = r.PluginRpc(r.NamedPipeTransport(pipe_file))
        _line(True, f"宿主进程拉起：pid={proc.pid}，管道已连接")
        rejected = False
        try:
            r._call_rpc_with_timeout(rpc, 3.0, "host_pid")
        except Exception as exc:
            rejected = "init" in str(exc)
        ok = _line(rejected, "协议：init 之前的命令被宿主拒绝")
        r._call_rpc_with_timeout(rpc, 3.0, "shutdown")
        code = proc.wait(timeout=5)
        return _line(code == 0, f"shutdown 后宿主退出码 {code}") and ok
    except Exception as exc:
        return _line(False, f"宿主协议检查异常：{exc}")
    finally:
        if pipe_file is not None:
            try:
                pipe_file.close()
            except Exception:
                pass
        if proc is not None and proc.poll() is None:
            proc.kill()


def _resolve_windows(titles: list[str], hwnds: list[int]) -> list[tuple[int, str]]:
    import win32gui

    found: list[tuple[int, str]] = [(int(h), win32gui.GetWindowText(int(h)) or str(h)) for h in hwnds]
    if titles:
        def _collect(hwnd, acc):
            if win32gui.IsWindowVisible(hwnd):
                text = win32gui.GetWindowText(hwnd) or ""
                for wanted in titles:
                    if text == wanted or (wanted and wanted in text):
                        acc.append((hwnd, text))
            return True

        matched: list[tuple[int, str]] = []
        win32gui.EnumWindows(_collect, matched)
        seen = {h for h, _ in found}
        for hwnd, text in matched:
            if hwnd not in seen:
                found.append((hwnd, text))
                seen.add(hwnd)
    return found


def check_windows(windows: list[tuple[int, str]]) -> bool:
    import app_core.config_store  # noqa: F401 — 注册运行时配置提供者
    from utils.plugin.bind_probe import probe_plugin_window_bind, should_probe_plugin_bind
    from utils.plugin.runtime import describe_plugin_host_stats, plugin_host_stats
    from utils.plugin.session import get_shared_plugin_client, unbind_shared_plugin_windows
    from utils.runtime_config import get_runtime_config
    from utils.input_simulation.mode_utils import is_plugin_input_backend

    config = get_runtime_config()
    if not should_probe_plugin_bind(config):
        return _line(False, "当前配置没有启用插件（键鼠后端或截图引擎都不是插件），先在全局设置里切到「插件」并保存")
    if not str(config.get("plugin_reg_code") or "").strip():
        return _line(False, "配置里没有插件注册码")
    _line(True, (
        f"当前插件参数：display={config.get('screenshot_engine')} mouse={config.get('plugin_mouse')} "
        f"keypad={config.get('plugin_keypad')} kind={config.get('plugin_bind_kind')} mode={config.get('plugin_bind_mode')} "
        f"ime={bool(config.get('plugin_text_ime'))} fake_active={bool(config.get('plugin_fake_active'))}"
    ))

    all_ok = True
    for hwnd, title in windows:
        print(f"--- 窗口 {hwnd} 「{title}」")
        started = time.perf_counter()
        result = probe_plugin_window_bind(hwnd, config, timeout=10.0)
        elapsed = time.perf_counter() - started
        all_ok &= _line(result.ok, f"试绑 {elapsed:.2f}s：截图={'通过' if result.capture_ok else '失败'} 键鼠={'通过' if result.input_ok else '失败'}"
                        + (f"；{result.message}" if result.message else ""))
        if not result.ok:
            continue
        session = get_shared_plugin_client(hwnd)
        all_ok &= _line(session.is_window_bound(hwnd), "IsBind：大漠确认窗口处于绑定状态")
        client = session._ensure_client()
        width, height = client.client_size(hwnd)
        all_ok &= _line(width > 0 and height > 0, f"客户区尺寸：{width}x{height}")
        if is_plugin_input_backend(config):
            all_ok &= _line(bool(client.move_to(0, 0, hwnd=hwnd)), "MoveTo(0,0)：键鼠通道可用（未点击）")

    stats = plugin_host_stats()
    print("---")
    _line(True, describe_plugin_host_stats(stats) or "宿主统计不可用")
    expected = len(windows)
    registrations = int(stats.get("registrations") or 0)
    if stats:
        all_ok &= _line(
            registrations <= max(1, expected),
            f"注册次数 {registrations}，窗口数 {expected}（应满足 注册次数 <= max(1, 窗口数)）",
        )
    unbind_shared_plugin_windows()
    after = plugin_host_stats()
    if after:
        all_ok &= _line(int(after.get("slots") or 0) == 0, f"解绑后：绑定中 {after.get('slots')}，空闲对象 {after.get('free')}（对象回池，再绑不再注册）")
    return all_ok


def main() -> int:
    parser = argparse.ArgumentParser(description="大漠插件真机自检")
    parser.add_argument("--no-auth", action="store_true", help="只查文件/架构/宿主协议，不注册")
    parser.add_argument("--title", action="append", default=[], help="目标窗口标题（可重复，子串匹配）")
    parser.add_argument("--hwnd", action="append", type=int, default=[], help="目标窗口句柄（可重复）")
    args = parser.parse_args()

    ok = check_runtime_files()
    ok &= check_host_protocol()
    if args.no_auth:
        print("==> 未注册模式结束（未消耗注册次数）")
        return 0 if ok else 1
    if not ok:
        print("==> 基础检查未通过，跳过绑定")
        return 1
    windows = _resolve_windows(args.title, args.hwnd)
    if not windows:
        print("==> 没有匹配到窗口；用 --title 或 --hwnd 指定，或加 --no-auth 只做基础检查")
        return 1
    ok &= check_windows(windows)
    print("==> 全部通过" if ok else "==> 有失败项，见上方 [FAIL]")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
