# -*- coding: utf-8 -*-
"""绑定窗口后按当前插件参数试绑截图/键鼠。失败只提示，不撤销列表登记。"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional

from utils.capture.engine_ids import is_plugin_screenshot_engine, normalize_screenshot_engine
from utils.input_simulation.mode_utils import is_plugin_input_backend
from utils.plugin.capture import (
    capture_window_plugin,
    get_last_plugin_capture_failure_reason,
)
from utils.plugin.runtime import is_plugin_runtime_available
from utils.plugin.session import get_shared_plugin_client, wait_for_plugin_host_cleanup

logger = logging.getLogger(__name__)

DEFAULT_PLUGIN_BIND_PROBE_TIMEOUT = 2.0


@dataclass(frozen=True)
class PluginBindProbeResult:
    ok: bool
    capture_ok: bool
    input_ok: bool
    message: str = ""


DESKTOP_HOOK_HINT = (
    "目标是桌面：dx 键鼠 / 挂钩类截图要注入目标进程，桌面属于 explorer 注不进去；"
    "要在桌面上用插件，请把鼠标、键盘、截图都改成 normal（插件前台模式）"
)


def _uses_hook_params(display: str, mouse: str, keypad: str) -> bool:
    from utils.capture.engine_ids import to_dm_display_mode
    from utils.plugin.session import INPUT_BIND_DISPLAYS

    dm_display = str(to_dm_display_mode(display) or "").strip().lower() if display else ""
    if dm_display and dm_display not in INPUT_BIND_DISPLAYS:
        return True
    return any(str(value or "").strip().lower().startswith("dx") for value in (mouse, keypad))


def _desktop_hook_hint(hwnd: int, display: str, mouse: str, keypad: str) -> str:
    """桌面 + dx 参数绑定失败时给出针对性的提示，其余情况返回空串。"""
    if not _uses_hook_params(display, mouse, keypad):
        return ""
    try:
        from utils.window.window_identity import is_desktop_window

        if not is_desktop_window(hwnd):
            return ""
    except Exception:
        return ""
    return DESKTOP_HOOK_HINT


def should_probe_plugin_bind(config: Optional[Mapping] = None) -> bool:
    values = dict(config or {})
    if is_plugin_input_backend(values):
        return True
    return is_plugin_screenshot_engine(values.get("screenshot_engine"))


def resolve_plugin_probe_displays(config: Optional[Mapping] = None) -> tuple[str, str]:
    values = dict(config or {})
    screenshot = normalize_screenshot_engine(values.get("screenshot_engine"))
    follow = bool(values.get("plugin_input_display_follow", True))
    configured = normalize_screenshot_engine(values.get("plugin_input_display"))
    if follow and is_plugin_screenshot_engine(screenshot):
        input_display = screenshot
    elif is_plugin_screenshot_engine(configured):
        input_display = configured
    elif is_plugin_screenshot_engine(screenshot):
        input_display = screenshot
    else:
        input_display = configured or "normal"
    return screenshot, input_display


def plugin_bind_probe_warning_text(window_title: object, result: PluginBindProbeResult) -> str:
    title = str(window_title or "").strip() or "窗口"
    detail = str(result.message or "").strip() or "插件试绑失败"
    return (
        f"窗口「{title}」已加入绑定列表，但插件试绑未成功。\n"
        f"{detail}\n\n"
        "窗口仍会保留。可检查注册码、绑定方式（基础/高级）以及截图/键鼠参数后再试。"
    )


def stamp_plugin_bind_probe(window_info: Optional[dict], result: PluginBindProbeResult) -> Optional[dict]:
    if not isinstance(window_info, dict):
        return window_info
    window_info["plugin_bind_ok"] = bool(result.ok)
    window_info.pop("plugin_bind_skipped", None)
    if result.ok:
        window_info.pop("plugin_bind_error", None)
    else:
        window_info["plugin_bind_error"] = str(result.message or "").strip()
    return window_info


def _bind_params(config: Mapping) -> tuple[str, str, int]:
    mouse = str(config.get("plugin_mouse") or "normal").strip() or "normal"
    keypad = str(config.get("plugin_keypad") or "normal").strip() or "normal"
    try:
        mode = int(config.get("plugin_bind_mode") or 0)
    except (TypeError, ValueError):
        mode = 0
    return mouse, keypad, mode


def probe_plugin_window_bind(
    hwnd: int,
    config: Optional[Mapping] = None,
    *,
    timeout: float = DEFAULT_PLUGIN_BIND_PROBE_TIMEOUT,
) -> PluginBindProbeResult:
    values = dict(config or {})
    try:
        target = int(hwnd or 0)
    except (TypeError, ValueError):
        target = 0
    if target <= 0:
        return PluginBindProbeResult(False, False, False, "无效窗口句柄")
    if not is_plugin_runtime_available():
        return PluginBindProbeResult(False, False, False, "插件运行库不可用")

    screenshot, input_display = resolve_plugin_probe_displays(values)
    want_capture = is_plugin_screenshot_engine(screenshot)
    want_input = is_plugin_input_backend(values)
    if not want_capture and not want_input:
        return PluginBindProbeResult(True, True, True, "")

    try:
        wait_seconds = max(0.05, float(timeout))
    except (TypeError, ValueError):
        wait_seconds = DEFAULT_PLUGIN_BIND_PROBE_TIMEOUT

    if not wait_for_plugin_host_cleanup(wait_seconds):
        return PluginBindProbeResult(
            False,
            False if want_capture else True,
            False if want_input else True,
            "插件宿主仍在恢复，已跳过本轮试绑；稍后运行时会按新参数自动重绑",
        )

    capture_ok = True
    input_ok = True
    parts: list[str] = []
    # 试绑要按传入的（可能尚未保存的）配置来，包括输入法通道 / 假激活这两个可选绑定参数
    from utils.plugin.session import plugin_bind_extras

    bind_extras = plugin_bind_extras(values)
    probe_mouse, probe_keypad, probe_mode = (
        _bind_params(values) if want_input else ("normal", "normal", 0)
    )

    if want_capture:
        try:
            frame = capture_window_plugin(
                target,
                screenshot,
                timeout=wait_seconds,
                fallback=False,
                bind_extras=bind_extras,
                bind_params=(probe_mouse, probe_keypad, probe_mode),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("插件截图试绑异常: %s", exc, exc_info=True)
            frame = None
        capture_ok = frame is not None
        if not capture_ok:
            reason = get_last_plugin_capture_failure_reason() or "未知原因"
            parts.append(f"截图试绑失败：{reason}")

    if want_input:
        reason = ""
        try:
            session = get_shared_plugin_client(target)
            input_ok = bool(
                session.ensure_input_bind(
                    target,
                    input_display,
                    mouse=probe_mouse,
                    keypad=probe_keypad,
                    mode=probe_mode,
                    timeout=wait_seconds,
                    fallback=False,
                    bind_extras=bind_extras,
                )
            )
            if not input_ok:
                reason = session.last_bind_failure_text()
        except Exception as exc:  # noqa: BLE001
            logger.debug("插件键鼠试绑异常: %s", exc, exc_info=True)
            input_ok = False
            reason = f"{exc.__class__.__name__}: {exc}"
        if not input_ok:
            parts.append(f"键鼠试绑失败：{reason or '未知原因'}")

    ok = bool(capture_ok and input_ok)
    if not ok:
        mouse, keypad, _mode = _bind_params(values)
        hint = _desktop_hook_hint(target, screenshot if want_capture else "", mouse if want_input else "", keypad if want_input else "")
        if hint:
            parts.append(hint)
    return PluginBindProbeResult(ok, capture_ok, input_ok, "\n".join(parts))


def run_plugin_window_bind_probe(
    hwnd: int,
    config: Optional[Mapping] = None,
    *,
    window_info: Optional[dict] = None,
    window_title: object = "",
    on_failure: Optional[Callable[[str], None]] = None,
    timeout: float = DEFAULT_PLUGIN_BIND_PROBE_TIMEOUT,
) -> Optional[PluginBindProbeResult]:
    values = dict(config or {})
    if not should_probe_plugin_bind(values):
        return None
    result = probe_plugin_window_bind(hwnd, values, timeout=timeout)
    stamp_plugin_bind_probe(window_info, result)
    if result.ok:
        logger.info("插件试绑成功: hwnd=%s title=%s", hwnd, window_title)
        return result
    text = plugin_bind_probe_warning_text(
        window_title or (window_info or {}).get("title"),
        result,
    )
    logger.warning("插件试绑失败: hwnd=%s title=%s %s", hwnd, window_title, result.message)
    if on_failure is not None:
        try:
            on_failure(text)
        except Exception:
            logger.debug("插件试绑失败提示回调异常", exc_info=True)
    return result


def probe_bound_windows_plugin_bind(
    windows: Iterable[dict],
    config: Optional[Mapping] = None,
    *,
    timeout: float = DEFAULT_PLUGIN_BIND_PROBE_TIMEOUT,
    should_stop: Optional[Callable[[], bool]] = None,
) -> list[tuple[dict, PluginBindProbeResult]]:
    """按当前插件参数依次试绑列表里启用的窗口，并把结果盖到每个条目上。

    should_stop 返回 True（对话框已取消 / 参数又变了）时停止，且不再往条目上打戳，避免覆盖已还原或更新的状态。
    """
    values = dict(config or {})
    results: list[tuple[dict, PluginBindProbeResult]] = []

    def _cancelled() -> bool:
        try:
            return bool(should_stop is not None and should_stop())
        except Exception:
            return False

    for window_info in windows:
        if _cancelled():
            break
        if not isinstance(window_info, dict) or not window_info.get("enabled", True):
            continue
        try:
            hwnd = int(window_info.get("hwnd") or 0)
        except (TypeError, ValueError):
            hwnd = 0
        if hwnd <= 0:
            result = PluginBindProbeResult(False, False, False, "窗口未连接（没有有效句柄）")
        else:
            result = probe_plugin_window_bind(hwnd, values, timeout=timeout)
        if _cancelled():
            break
        stamp_plugin_bind_probe(window_info, result)
        results.append((window_info, result))
    return results


def plugin_bind_probe_summary_text(results: Iterable[tuple[dict, PluginBindProbeResult]]) -> str:
    """汇总多窗口试绑结果；全部通过返回空串。"""
    failures = [(info, result) for info, result in results if not result.ok]
    if not failures:
        return ""
    lines = ["插件参数已更新，但以下绑定窗口按新参数试绑未成功："]
    for info, result in failures:
        title = str((info or {}).get("title") or "窗口").strip()
        detail = str(result.message or "").strip() or "插件试绑失败"
        lines.append(f"• {title}：{detail}")
    lines.append("")
    lines.append("窗口仍保留在绑定列表。可检查注册码、绑定方式（基础/高级）以及截图/键鼠参数后重新保存。")
    return "\n".join(lines)


def start_bound_windows_plugin_bind_probe(
    windows: Iterable[dict],
    config: Optional[Mapping] = None,
    *,
    on_finished: Optional[Callable[[list[tuple[dict, PluginBindProbeResult]]], None]] = None,
    timeout: float = DEFAULT_PLUGIN_BIND_PROBE_TIMEOUT,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Optional[threading.Thread]:
    """后台批量试绑（切换到插件 / 修改插件参数后调用），完成后回调一次汇总结果；被取消时不回调。"""
    values = dict(config or {})
    targets = [info for info in windows if isinstance(info, dict)]
    if not targets or not should_probe_plugin_bind(values):
        return None

    def _worker() -> None:
        results: list[tuple[dict, PluginBindProbeResult]] = []
        try:
            results = probe_bound_windows_plugin_bind(targets, values, timeout=timeout, should_stop=should_stop)
        except Exception:
            logger.debug("批量插件试绑异常", exc_info=True)
        try:
            if should_stop is not None and should_stop():
                return
        except Exception:
            pass
        try:
            from utils.plugin.runtime import describe_plugin_host_stats, plugin_host_stats

            summary = describe_plugin_host_stats(plugin_host_stats())
            if summary:
                logger.info("批量试绑完成，%s", summary)
        except Exception:
            logger.debug("读取宿主统计失败", exc_info=True)
        if on_finished is None:
            return
        try:
            on_finished(results)
        except Exception:
            logger.debug("批量插件试绑完成回调异常", exc_info=True)

    worker = threading.Thread(target=_worker, name="plugin-bind-probe-batch", daemon=True)
    worker.start()
    return worker


def start_plugin_window_bind_probe(
    hwnd: int,
    config: Optional[Mapping] = None,
    *,
    window_info: Optional[dict] = None,
    window_title: object = "",
    on_finished: Optional[Callable[[Optional[PluginBindProbeResult]], None]] = None,
    timeout: float = DEFAULT_PLUGIN_BIND_PROBE_TIMEOUT,
) -> Optional[threading.Thread]:
    """后台试绑，避免卡住选窗后的 UI 线程。"""
    values = dict(config or {})
    if not should_probe_plugin_bind(values):
        return None

    def _worker() -> None:
        result = None
        try:
            result = run_plugin_window_bind_probe(
                hwnd,
                values,
                window_info=window_info,
                window_title=window_title,
                timeout=timeout,
            )
        except Exception:
            logger.debug("后台插件试绑异常", exc_info=True)
        if on_finished is None:
            return
        try:
            on_finished(result)
        except Exception:
            logger.debug("插件试绑完成回调异常", exc_info=True)

    worker = threading.Thread(target=_worker, name="plugin-bind-probe", daemon=True)
    worker.start()
    return worker
