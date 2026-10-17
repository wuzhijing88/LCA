# -*- coding: utf-8 -*-
"""按 HWND 隔离的插件会话：截图与 DX 键鼠共用一次 BindWindow/BindWindowEx。"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Dict, Optional

from utils.capture.engine_ids import (
    is_plugin_screenshot_engine,
    normalize_screenshot_engine,
    to_dm_display_mode,
)
from utils.plugin.bind_errors import BindOutcome, describe_bind_failure
from utils.plugin.bind_modes import (
    PLUGIN_IME_PUBLIC_OPTION,
    normalize_plugin_keypad,
    normalize_plugin_mouse,
    normalize_plugin_public,
)
from utils.plugin.runtime import (
    PluginClient,
    PluginTransportError,
    ensure_plugin_rpc,
    invalidate_plugin_rpc_connection,
    owns_plugin_host,
    terminate_plugin_host,
    unbind_plugin_host,
)

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_BIND_EXECUTION_LOCK = threading.Lock()
_HOST_CLEANUP_LOCK = threading.Lock()
_HOST_CLEANUP_PENDING = False
_HOST_CLEANUP_GENERATION = 0
_CLIENTS: Dict[int, PluginClient] = {}
# 非挂钩 display：桌面试绑提示用，判断 dx/opengl 是否会注入目标进程
INPUT_BIND_DISPLAYS = ("normal", "gdi", "gdi2")


def _client_key(hwnd: Optional[int] = None) -> int:
    value = 0 if hwnd is None else int(hwnd)
    if value < 0:
        raise ValueError("插件窗口句柄无效")
    return value


def _create_plugin_client() -> PluginClient:
    with _HOST_CLEANUP_LOCK:
        if _HOST_CLEANUP_PENDING:
            raise RuntimeError("插件宿主正在清理，暂时不能创建客户端")
        creation_generation = _HOST_CLEANUP_GENERATION
    rpc = ensure_plugin_rpc()
    with _HOST_CLEANUP_LOCK:
        if (
            _HOST_CLEANUP_PENDING
            or creation_generation != _HOST_CLEANUP_GENERATION
        ):
            raise RuntimeError("插件宿主清理已开始，放弃新建客户端")
    return PluginClient(rpc=rpc)


def get_shared_plugin_client(hwnd: Optional[int] = None) -> "PluginSession":
    key = _client_key(hwnd)
    with _HOST_CLEANUP_LOCK:
        if _HOST_CLEANUP_PENDING:
            raise RuntimeError("插件宿主正在清理，暂时不能获取共享客户端")
        with _LOCK:
            client = _CLIENTS.get(key)
        creation_generation = _HOST_CLEANUP_GENERATION
    if client is not None:
        return PluginSession(client=client)

    candidate = _create_plugin_client()
    with _HOST_CLEANUP_LOCK:
        if (
            _HOST_CLEANUP_PENDING
            or creation_generation != _HOST_CLEANUP_GENERATION
        ):
            raise RuntimeError("插件宿主清理已开始，放弃发布新建客户端")
        with _LOCK:
            client = _CLIENTS.get(key)
            if client is None:
                client = candidate
                _CLIENTS[key] = client
    return PluginSession(client=client)


def wait_for_plugin_host_cleanup(timeout: float = 2.0) -> bool:
    """等待超时恢复中的插件宿主清理完成，避免紧接着的重绑收到瞬时失败。"""
    wait_seconds = float(timeout)
    if not math.isfinite(wait_seconds) or wait_seconds < 0:
        raise ValueError("插件清理等待时间必须是大于等于零的有限数字")
    deadline = time.monotonic() + wait_seconds
    while True:
        with _HOST_CLEANUP_LOCK:
            pending = bool(_HOST_CLEANUP_PENDING)
        if not pending:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.02, remaining))


def close_shared_plugin_client(hwnd: Optional[int] = None) -> None:
    with _LOCK:
        if hwnd is None:
            clients = list(_CLIENTS.values())
            _CLIENTS.clear()
        else:
            client = _CLIENTS.pop(_client_key(hwnd), None)
            clients = [client] if client is not None else []
    for client in clients:
        try:
            client.close()
        except Exception:
            logger.debug("关闭共享插件客户端失败", exc_info=True)


def abandon_shared_plugin_client(hwnd: Optional[int] = None) -> None:
    """丢弃共享客户端但不 close。绑定卡住时避免与工作线程死锁。"""
    with _LOCK:
        if hwnd is None:
            _CLIENTS.clear()
        else:
            _CLIENTS.pop(_client_key(hwnd), None)


def _claim_plugin_host_cleanup() -> bool:
    """短锁声明宿主清理；并发请求仅允许一个声明成功。"""
    global _HOST_CLEANUP_GENERATION, _HOST_CLEANUP_PENDING
    with _HOST_CLEANUP_LOCK:
        if _HOST_CLEANUP_PENDING:
            return False
        _HOST_CLEANUP_PENDING = True
        _HOST_CLEANUP_GENERATION += 1
        return True


def _start_claimed_plugin_host_cleanup(*restore_hwnds: int) -> None:
    """为已声明的清理启动 daemon 终止线程。"""
    global _HOST_CLEANUP_PENDING

    def _worker() -> None:
        global _HOST_CLEANUP_PENDING
        try:
            terminate_plugin_host()
        except Exception:
            logger.debug("terminate_plugin_host 失败", exc_info=True)
        finally:
            try:
                restore_plugin_bind_windows(*restore_hwnds)
            except Exception:
                logger.debug("恢复插件绑定窗口失败", exc_info=True)
            try:
                abandon_shared_plugin_client()
            except Exception:
                logger.debug("插件宿主清理后放弃共享客户端失败", exc_info=True)
            finally:
                with _HOST_CLEANUP_LOCK:
                    _HOST_CLEANUP_PENDING = False

    worker = threading.Thread(target=_worker, name="plugin-host-cleanup", daemon=True)
    try:
        worker.start()
    except Exception:
        with _HOST_CLEANUP_LOCK:
            _HOST_CLEANUP_PENDING = False
        logger.debug("启动插件宿主清理线程失败", exc_info=True)


def _schedule_plugin_host_cleanup() -> None:
    """声明并异步清理插件宿主。"""
    if _claim_plugin_host_cleanup():
        _start_claimed_plugin_host_cleanup()


def unbind_shared_plugin_windows(hwnd: int = 0) -> bool:
    """停止任务 / 全局停止时显式 UnBindWindow，不再让目标窗口一直挂着大漠钩子。hwnd=0 解绑全部。"""
    with _HOST_CLEANUP_LOCK:
        if _HOST_CLEANUP_PENDING:
            return False
    return unbind_plugin_host(hwnd=int(hwnd or 0))


def plugin_bind_extras(config=None) -> tuple[str, bool]:
    """从配置拼出 BindWindowEx 的 public 串与假激活开关，截图/键鼠绑定共用，保证宿主侧缓存键一致。"""
    if config is None:
        from utils.runtime_config import get_runtime_config

        config = get_runtime_config()
    values = dict(config or {})
    ime = values.get("plugin_text_ime", False)
    fake_active = values.get("plugin_fake_active", False)
    if not isinstance(ime, bool) or not isinstance(fake_active, bool):
        raise ValueError("插件输入法和后台假激活配置必须是布尔值")
    options = list(normalize_plugin_public(values.get("plugin_public")))
    if ime:
        options.append(PLUGIN_IME_PUBLIC_OPTION)
    return "|".join(options), fake_active


def _binding_timeout_seconds(timeout: float) -> float:
    try:
        seconds = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("插件绑定超时必须是大于零的有限数字") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("插件绑定超时必须是大于零的有限数字")
    return seconds


def restore_plugin_bind_windows(*hwnds: int) -> None:
    """超时杀宿主后把大漠可能藏掉的目标窗重新显示，不抢前台。"""
    try:
        import win32con
        import win32gui
    except Exception:
        return
    from utils.window.hwnd_utils import as_hwnd

    seen: set[int] = set()
    for raw in hwnds:
        handle = as_hwnd(raw)
        if handle <= 0:
            continue
        targets = [handle]
        try:
            root = int(win32gui.GetAncestor(handle, 2) or 0)
            if root > 0:
                targets.append(root)
            owner = int(win32gui.GetWindow(handle, 4) or 0)
            if owner > 0:
                targets.append(owner)
        except Exception:
            logger.debug("枚举插件绑定窗口祖先失败", exc_info=True)
        for target in targets:
            if target in seen:
                continue
            seen.add(target)
            try:
                if not win32gui.IsWindow(target):
                    continue
                if win32gui.IsIconic(target):
                    win32gui.ShowWindow(target, win32con.SW_RESTORE)
                if not win32gui.IsWindowVisible(target):
                    win32gui.ShowWindow(target, win32con.SW_SHOW)
                else:
                    win32gui.ShowWindow(target, win32con.SW_SHOWNA)
            except Exception:
                logger.debug("恢复插件绑定窗口失败 hwnd=%s", target, exc_info=True)


def resolve_input_bind_display(preferred: Optional[str] = None) -> str:
    """键鼠绑定用的 display，与截图绑定走同一套换算。

    大漠一次 BindWindow(Ex) 同时决定图色和键鼠；同一窗口若截图用 dx.graphic.* 而键鼠改成 normal，
    两边绑定键不同，每次截图↔键鼠交替都会解绑重绑（dx 绑定耗时且可能闪窗）。所以这里不再把
    dx / opengl 显示模式改成 normal。
    """
    dm_display = to_dm_display_mode(preferred)
    if not dm_display:
        raise ValueError("插件绑定缺少图显")
    return dm_display


def resolve_plugin_display_mode(preferred: Optional[str] = None) -> str:
    chosen = normalize_screenshot_engine(preferred)
    if not is_plugin_screenshot_engine(chosen):
        raise ValueError(f"不是插件截图引擎: {preferred!r}")
    return chosen


class PluginSession:
    """包装 PluginClient：同一窗口的截图与键鼠共用一次绑定（display / mouse / keypad / mode 完全一致）。"""

    def __init__(self, client=None):
        self._client = client
        self._last_input_hwnd = 0
        # 最近一次 bind 的宿主返回（含 GetLastError / 异常文本），供试绑提示与日志翻译原因
        self.last_bind_outcome: Optional[BindOutcome] = None
        self.last_bind_params: tuple[str, str, str, int] = ("", "", "", 0)

    def last_bind_failure_text(self) -> str:
        display, mouse, keypad, mode = self.last_bind_params
        return describe_bind_failure(
            self.last_bind_outcome,
            display=display,
            mouse=mouse,
            keypad=keypad,
            mode=mode,
        )

    def _ensure_client(self):
        if self._client is None:
            self._client = _create_plugin_client()
        return self._client

    def _capture_bind_params(self) -> tuple[str, str, int]:
        from utils.input_simulation.mode_utils import is_plugin_input_backend
        from utils.plugin.bind_modes import normalize_plugin_bind_mode
        from utils.runtime_config import get_runtime_config

        cfg = get_runtime_config()
        if not is_plugin_input_backend(cfg):
            raise ValueError("插件截图只能在执行模式为插件时绑定，不能改用原生键鼠参数")
        return (
            normalize_plugin_mouse(cfg.get("plugin_mouse")),
            normalize_plugin_keypad(cfg.get("plugin_keypad")),
            normalize_plugin_bind_mode(cfg.get("plugin_bind_mode")),
        )

    def _try_bind(
        self,
        display_hwnd: int,
        input_hwnd: int,
        display: str,
        mouse: str,
        keypad: str,
        mode: int,
        bind_extras: Optional[tuple[str, bool]] = None,
    ) -> bool:
        display_target = int(display_hwnd or 0)
        input_target = int(input_hwnd or 0)
        if input_target < 0:
            raise ValueError("插件输入窗口句柄无效")
        if input_target == 0:
            input_target = display_target
        client = self._ensure_client()
        transport_retried = False
        self.last_bind_params = (str(display), str(mouse), str(keypad), int(mode))
        self.last_bind_outcome = None
        public, fake_active = bind_extras if bind_extras is not None else plugin_bind_extras()
        # 只在用户开了输入法通道 / 假激活时才附带可选项，默认绑定请求与宿主默认值一致
        extras: dict = {}
        if public:
            extras["public"] = public
        if fake_active:
            extras["fake_active"] = True

        def _call_bind(target_client, current_input_target: int) -> BindOutcome:
            return BindOutcome.from_rpc(
                target_client.bind(display_target, current_input_target, display, mouse, keypad, mode, **extras)
            )

        def _bind(current_input_target: int) -> BindOutcome:
            nonlocal client, transport_retried
            try:
                outcome = _call_bind(client, current_input_target)
            except PluginTransportError:
                if transport_retried:
                    raise
                transport_retried = True
                if not owns_plugin_host():
                    invalidate_plugin_rpc_connection()
                abandon_shared_plugin_client()
                self._client = None
                client = get_shared_plugin_client(display_target)._client
                self._client = client
                outcome = _call_bind(client, current_input_target)
            self.last_bind_outcome = outcome
            if outcome.registered:
                # 每个窗口第一次绑定才会新建 dm 对象并 Reg；这条日志用来核对注册次数没有异常增长
                logger.info(
                    "插件为窗口 %s 新建 dm 对象并注册（本宿主累计 %d 次）",
                    display_target,
                    outcome.registrations,
                )
            return outcome

        ok = bool(_bind(input_target))
        if ok:
            self._last_input_hwnd = input_target
        return ok

    def _bind_with_timeout(
        self,
        display_hwnd: int,
        input_hwnd: int,
        display: str,
        mouse: str,
        keypad: str,
        mode: int,
        timeout: float,
        bind_extras: Optional[tuple[str, bool]] = None,
    ) -> Optional[bool]:
        wait_seconds = _binding_timeout_seconds(timeout)
        deadline = time.monotonic() + wait_seconds
        box: dict = {}

        with _HOST_CLEANUP_LOCK:
            if _HOST_CLEANUP_PENDING:
                logger.warning("插件宿主正在清理，跳过绑定")
                return None

        remaining = deadline - time.monotonic()
        if remaining <= 0 or not _BIND_EXECUTION_LOCK.acquire(timeout=remaining):
            logger.warning("等待插件绑定执行槽位超时")
            return None

        def _worker() -> None:
            try:
                box["ok"] = bool(
                    self._try_bind(
                        display_hwnd,
                        input_hwnd,
                        display,
                        mouse,
                        keypad,
                        mode,
                        bind_extras=bind_extras,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                box["err"] = exc
                box["ok"] = False
            finally:
                _BIND_EXECUTION_LOCK.release()

        worker = threading.Thread(target=_worker, name="plugin-bind", daemon=True)
        with _HOST_CLEANUP_LOCK:
            if _HOST_CLEANUP_PENDING:
                _BIND_EXECUTION_LOCK.release()
                logger.warning("插件宿主清理已开始，取消绑定")
                return None
            if time.monotonic() >= deadline:
                _BIND_EXECUTION_LOCK.release()
                logger.warning("等待插件绑定执行槽位超时")
                return None
            try:
                worker.start()
            except Exception:
                _BIND_EXECUTION_LOCK.release()
                logger.debug("启动插件绑定线程失败", exc_info=True)
                return False
        worker.join(max(0.0, deadline - time.monotonic()))
        if worker.is_alive():
            logger.error(
                "插件绑定超时(%.1fs): display_hwnd=%s input_hwnd=%s display=%s mode=%s",
                wait_seconds,
                display_hwnd,
                int(input_hwnd or 0) or display_hwnd,
                display,
                mode,
            )
            cleanup_claimed = _claim_plugin_host_cleanup()
            abandon_shared_plugin_client()
            if cleanup_claimed:
                _start_claimed_plugin_host_cleanup(display_hwnd, input_hwnd)
            return None
        if box.get("err") is not None:
            err = box["err"]
            self.last_bind_outcome = BindOutcome(ok=False, error=f"{err.__class__.__name__}: {err}")
            logger.warning("插件绑定异常: %s", err)
        return bool(box.get("ok"))

    def capture_bgr(
        self,
        hwnd: int,
        display: str,
        input_hwnd: int = 0,
        timeout: float = 4.0,
        client_area_only: bool = True,
        bind_extras: Optional[tuple[str, bool]] = None,
        bind_params: Optional[tuple[str, str, int]] = None,
    ):
        _ = client_area_only
        target = int(hwnd or 0)
        preferred = str(display or "").strip()
        if target <= 0 or not preferred:
            return None
        input_target = int(input_hwnd or 0)
        if input_target < 0:
            raise ValueError("插件输入窗口句柄无效")
        if input_target == 0:
            input_target = target
        wait_seconds = _binding_timeout_seconds(timeout)
        if bind_params is None:
            mouse, keypad, requested_mode = self._capture_bind_params()
        else:
            from utils.plugin.bind_modes import normalize_plugin_bind_mode

            mouse = normalize_plugin_mouse(bind_params[0])
            keypad = normalize_plugin_keypad(bind_params[1])
            requested_mode = normalize_plugin_bind_mode(bind_params[2])
        self._ensure_client()
        preferred_display = to_dm_display_mode(preferred)
        outcome = self._bind_with_timeout(
            target,
            input_target,
            preferred_display,
            mouse,
            keypad,
            requested_mode,
            wait_seconds,
            bind_extras=bind_extras,
        )
        if not outcome:
            return None
        grab_input = int(self._last_input_hwnd or input_target or target)
        client = self._ensure_client()
        # 大漠绑定后 GetClientSize + GetScreenDataBmp(0,0,w,h) 抓的就是它定义的客户区，
        # 坐标系也以此为准；不能再按系统标题栏/边框裁一次，否则内容被裁掉、坐标错位。
        return client.capture_bgr(target, preferred_display, input_hwnd=grab_input)

    def ensure_display_bound(
        self,
        hwnd: int,
        display: Optional[str] = None,
        input_hwnd: int = 0,
        timeout: float = 4.0,
        bind_extras: Optional[tuple[str, bool]] = None,
    ) -> bool:
        target = int(hwnd or 0)
        preferred = str(display or "").strip()
        if target <= 0 or not preferred:
            return False
        input_target = int(input_hwnd or 0)
        if input_target < 0:
            raise ValueError("插件输入窗口句柄无效")
        if input_target == 0:
            input_target = target
        wait_seconds = _binding_timeout_seconds(timeout)
        mouse, keypad, requested_mode = self._capture_bind_params()
        preferred_display = to_dm_display_mode(preferred)
        return bool(
            self._bind_with_timeout(
                target,
                input_target,
                preferred_display,
                mouse,
                keypad,
                requested_mode,
                wait_seconds,
                bind_extras=bind_extras,
            )
        )

    def ensure_input_bind(
        self,
        hwnd: int,
        display: str,
        mouse: str = "dx",
        keypad: str = "dx",
        mode: int = 0,
        input_hwnd: Optional[int] = None,
        timeout: float = 8.0,
        bind_extras: Optional[tuple[str, bool]] = None,
    ) -> bool:
        from utils.plugin.bind_modes import normalize_plugin_bind_mode

        preferred = str(display or "").strip()
        if not preferred:
            return False
        dm_display = resolve_input_bind_display(preferred)
        wanted_mouse = normalize_plugin_mouse(mouse)
        wanted_keypad = normalize_plugin_keypad(keypad)
        requested_mode = normalize_plugin_bind_mode(mode)
        return bool(
            self._bind_with_timeout(
                int(hwnd or 0),
                int(input_hwnd or 0),
                dm_display,
                wanted_mouse,
                wanted_keypad,
                requested_mode,
                timeout,
                bind_extras=bind_extras,
            )
        )

    def last_error(self, hwnd: int = 0) -> int:
        return int(self._ensure_client().last_error(hwnd=_client_key(hwnd)))

    def is_window_bound(self, hwnd: int) -> bool:
        """向大漠核实该窗口是否仍在绑定中（窗口重建后宿主缓存可能已过期）。"""
        return self._ensure_client().is_bind(_client_key(hwnd))
