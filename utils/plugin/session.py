# -*- coding: utf-8 -*-
"""按 HWND 隔离的插件会话：截图与 DX 键鼠共用一次 BindWindow/BindWindowEx。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Optional

from utils.capture.engine_ids import (
    is_plugin_screenshot_engine,
    normalize_screenshot_engine,
    to_dm_display_mode,
)
from utils.plugin.bind_errors import BindOutcome, describe_bind_failure
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
DEFAULT_PLUGIN_DISPLAY = "normal"
# 非挂钩 display：只用于显式开启 fallback 时的降级尝试顺序，不再影响正常绑定参数
INPUT_BIND_DISPLAYS = ("normal", "gdi", "gdi2")
SAFE_BIND_MODES = (0, 2)


def _client_key(hwnd: Optional[int] = None) -> int:
    try:
        value = int(hwnd or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else 0


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
    try:
        wait_seconds = max(0.0, float(timeout))
    except (TypeError, ValueError):
        wait_seconds = 2.0
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


PLUGIN_IME_PUBLIC_OPTION = "dx.public.input.ime"


def plugin_bind_extras(config=None) -> tuple[str, bool]:
    """从配置拼出 BindWindowEx 的 public 串与假激活开关，截图/键鼠绑定共用，保证宿主侧缓存键一致。"""
    if config is None:
        try:
            from utils.runtime_config import get_runtime_config

            config = get_runtime_config()
        except Exception:
            config = {}
    values = dict(config or {})
    options: list[str] = []
    if bool(values.get("plugin_text_ime", False)):
        options.append(PLUGIN_IME_PUBLIC_OPTION)
    return "|".join(options), bool(values.get("plugin_fake_active", False))


def _is_hook_display(display: object) -> bool:
    dm_display = to_dm_display_mode(display)
    return bool(dm_display) and dm_display not in INPUT_BIND_DISPLAYS


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
    dx / opengl 显示模式降成 normal，只在没有可用值时回退默认。
    """
    dm_display = to_dm_display_mode(preferred)
    if dm_display:
        return dm_display
    raw = normalize_screenshot_engine(preferred)
    return raw or DEFAULT_PLUGIN_DISPLAY


def _bind_modes_to_try(requested: int) -> list[int]:
    modes: list[int] = []
    for bind_mode in (int(requested),) + SAFE_BIND_MODES:
        if bind_mode not in modes:
            modes.append(bind_mode)
    return modes


def resolve_plugin_display_mode(preferred: Optional[str] = None) -> str:
    chosen = normalize_screenshot_engine(preferred)
    if is_plugin_screenshot_engine(chosen):
        return chosen
    try:
        from utils.capture.screenshot_helper import get_screenshot_engine

        current = normalize_screenshot_engine(get_screenshot_engine())
    except Exception:
        current = ""
    if is_plugin_screenshot_engine(current):
        return current
    return DEFAULT_PLUGIN_DISPLAY


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
        try:
            from utils.input_simulation.mode_utils import is_plugin_input_backend
            from utils.runtime_config import get_runtime_config

            cfg = get_runtime_config()
        except Exception:
            return "normal", "normal", 0
        if not is_plugin_input_backend(cfg):
            return "normal", "normal", 0
        mouse = str(cfg.get("plugin_mouse") or "normal").strip() or "normal"
        keypad = str(cfg.get("plugin_keypad") or "normal").strip() or "normal"
        try:
            mode = int(cfg.get("plugin_bind_mode") or 0)
        except (TypeError, ValueError):
            mode = 0
        return mouse, keypad, mode

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
        try:
            input_target = int(input_hwnd or 0)
        except (TypeError, ValueError):
            input_target = 0
        if input_target <= 0:
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

        if display_target != input_target:
            try:
                if _bind(input_target):
                    self._last_input_hwnd = input_target
                    return True
                reason = self.last_bind_failure_text()
            except Exception as exc:  # noqa: BLE001
                reason = f"{exc.__class__.__name__}: {exc}"
            logger.warning(
                "插件分离绑定失败，改用同一句柄重试: display_hwnd=%s input_hwnd=%s 原因=%s",
                display_target,
                input_target,
                reason,
            )
            input_target = display_target
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
        try:
            wait_seconds = max(0.05, float(timeout))
        except Exception:
            wait_seconds = 8.0
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

    @staticmethod
    def _log_fallback_used(
        kind: str,
        requested_display: str,
        requested_mode: int,
        used_display: str,
        used_mode: int,
        first_failure: str,
    ) -> None:
        if requested_display == used_display and int(requested_mode) == int(used_mode):
            return
        logger.warning(
            "插件%s绑定降级：配置 display=%s mode=%s 失败（%s），实际使用 display=%s mode=%s；请核对插件参数",
            kind,
            requested_display,
            requested_mode,
            first_failure or "原因未知",
            used_display,
            used_mode,
        )

    def capture_bgr(
        self,
        hwnd: int,
        display: str,
        input_hwnd: int = 0,
        timeout: float = 4.0,
        client_area_only: bool = True,
        fallback: bool = False,
        bind_extras: Optional[tuple[str, bool]] = None,
        bind_params: Optional[tuple[str, str, int]] = None,
    ):
        _ = client_area_only
        target = int(hwnd or 0)
        preferred = str(display or "").strip()
        if target <= 0 or not preferred:
            return None
        try:
            input_target = int(input_hwnd or 0)
        except (TypeError, ValueError):
            input_target = 0
        if input_target <= 0:
            input_target = target
        try:
            wait_seconds = max(0.05, float(timeout))
        except Exception:
            wait_seconds = 4.0
        if bind_params is None:
            mouse, keypad, requested_mode = self._capture_bind_params()
        else:
            mouse = str(bind_params[0] or "normal").strip() or "normal"
            keypad = str(bind_params[1] or "normal").strip() or "normal"
            try:
                requested_mode = int(bind_params[2] or 0)
            except (TypeError, ValueError):
                requested_mode = 0
        self._ensure_client()
        preferred_display = to_dm_display_mode(preferred)
        deadline = time.monotonic() + wait_seconds
        displays = [preferred_display]
        if fallback and _is_hook_display(preferred_display):
            for safe in INPUT_BIND_DISPLAYS:
                if safe not in displays:
                    displays.append(safe)
        first_failure = ""
        for dm_display in displays:
            modes = [requested_mode] if not fallback else _bind_modes_to_try(requested_mode)
            for bind_mode in modes:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                outcome = self._bind_with_timeout(
                    target,
                    input_target,
                    dm_display,
                    mouse,
                    keypad,
                    bind_mode,
                    remaining,
                    bind_extras=bind_extras,
                )
                if outcome is None:
                    return None
                if not outcome:
                    if not first_failure:
                        first_failure = self.last_bind_failure_text()
                    continue
                self._log_fallback_used("截图", preferred_display, requested_mode, dm_display, bind_mode, first_failure)
                grab_input = int(self._last_input_hwnd or input_target or target)
                client = self._ensure_client()
                # 大漠绑定后 GetClientSize + GetScreenData(0,0,w,h) 抓的就是它定义的客户区，
                # 坐标系也以此为准；不能再按系统标题栏/边框裁一次，否则内容被裁掉、坐标错位。
                frame = client.capture_bgr(target, dm_display, input_hwnd=grab_input)
                if frame is not None:
                    return frame
        return None

    def ensure_display_bound(
        self,
        hwnd: int,
        display: Optional[str] = None,
        input_hwnd: int = 0,
        timeout: float = 4.0,
        fallback: bool = False,
        bind_extras: Optional[tuple[str, bool]] = None,
    ) -> bool:
        target = int(hwnd or 0)
        preferred = str(display or "").strip() or resolve_plugin_display_mode()
        if target <= 0 or not preferred:
            return False
        try:
            input_target = int(input_hwnd or 0)
        except (TypeError, ValueError):
            input_target = 0
        if input_target <= 0:
            input_target = target
        try:
            wait_seconds = max(0.05, float(timeout))
        except Exception:
            wait_seconds = 4.0
        mouse, keypad, requested_mode = self._capture_bind_params()
        preferred_display = to_dm_display_mode(preferred)
        deadline = time.monotonic() + wait_seconds
        displays = [preferred_display]
        if fallback and _is_hook_display(preferred_display):
            for safe in INPUT_BIND_DISPLAYS:
                if safe not in displays:
                    displays.append(safe)
        first_failure = ""
        for dm_display in displays:
            modes = [requested_mode] if not fallback else _bind_modes_to_try(requested_mode)
            for bind_mode in modes:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                outcome = self._bind_with_timeout(
                    target,
                    input_target,
                    dm_display,
                    mouse,
                    keypad,
                    bind_mode,
                    remaining,
                    bind_extras=bind_extras,
                )
                if outcome is None:
                    return False
                if outcome:
                    self._log_fallback_used("显示", preferred_display, requested_mode, dm_display, bind_mode, first_failure)
                    return True
                if not first_failure:
                    first_failure = self.last_bind_failure_text()
        return False

    def ensure_input_bind(
        self,
        hwnd: int,
        display: str,
        mouse: str = "dx",
        keypad: str = "dx",
        mode: int = 0,
        input_hwnd: Optional[int] = None,
        timeout: float = 8.0,
        fallback: bool = False,
        bind_extras: Optional[tuple[str, bool]] = None,
    ) -> bool:
        preferred = str(display or "").strip() or DEFAULT_PLUGIN_DISPLAY
        dm_display = resolve_input_bind_display(preferred)
        wanted_mouse = str(mouse or "dx").strip() or "dx"
        wanted_keypad = str(keypad or "dx").strip() or "dx"
        try:
            wait_seconds = max(0.05, float(timeout))
        except Exception:
            wait_seconds = 8.0
        try:
            requested_mode = int(mode or 0)
        except (TypeError, ValueError):
            requested_mode = 0
        deadline = time.monotonic() + wait_seconds
        modes = [requested_mode] if not fallback else _bind_modes_to_try(requested_mode)
        first_failure = ""
        for bind_mode in modes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            outcome = self._bind_with_timeout(
                int(hwnd or 0),
                int(input_hwnd or 0),
                dm_display,
                wanted_mouse,
                wanted_keypad,
                bind_mode,
                remaining,
                bind_extras=bind_extras,
            )
            if outcome is None:
                return False
            if outcome:
                self._log_fallback_used("键鼠", dm_display, requested_mode, dm_display, bind_mode, first_failure)
                return True
            if not first_failure:
                first_failure = self.last_bind_failure_text()
        return False

    def last_error(self, hwnd: int = 0) -> int:
        try:
            return int(self._ensure_client().last_error(hwnd=int(hwnd or 0)) or 0)
        except Exception:
            return 0

    def is_window_bound(self, hwnd: int) -> bool:
        """向大漠核实该窗口是否仍在绑定中（窗口重建后宿主缓存可能已过期）。"""
        try:
            return bool(self._ensure_client().is_bind(int(hwnd or 0)))
        except Exception:
            return False
