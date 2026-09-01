# -*- coding: utf-8 -*-
"""按 HWND 隔离的插件会话：截图与 DX 键鼠共用一次 BindWindow。"""

from __future__ import annotations

import logging
import threading
from typing import Dict, Optional

from utils.capture.engine_ids import (
    is_plugin_screenshot_engine,
    normalize_screenshot_engine,
    to_dm_display_mode,
)
from utils.plugin.runtime import PluginClient, ensure_plugin_rpc, terminate_plugin_host

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_CLIENTS: Dict[int, PluginClient] = {}
DEFAULT_PLUGIN_DISPLAY = "normal"
# DX 键鼠只用非挂钩 display；不含 dx* / opengl*
INPUT_BIND_DISPLAYS = ("normal", "gdi", "gdi2")


def _client_key(hwnd: Optional[int] = None) -> int:
    try:
        value = int(hwnd or 0)
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else 0


def _create_plugin_client() -> PluginClient:
    return PluginClient(rpc=ensure_plugin_rpc())


def get_shared_plugin_client(hwnd: Optional[int] = None) -> "PluginSession":
    key = _client_key(hwnd)
    with _LOCK:
        client = _CLIENTS.get(key)
        if client is None:
            client = _create_plugin_client()
            _CLIENTS[key] = client
        return PluginSession(client=client)


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
    """包装 PluginClient：截图绑 normal 键鼠，DX 键鼠只试 INPUT_BIND_DISPLAYS。"""

    def __init__(self, client=None):
        self._client = client
        self._last_input_hwnd = 0

    def _ensure_client(self):
        if self._client is None:
            self._client = _create_plugin_client()
        return self._client

    def _try_bind(
        self,
        display_hwnd: int,
        input_hwnd: int,
        display: str,
        mouse: str,
        keypad: str,
        mode: int,
    ) -> bool:
        display_target = int(display_hwnd or 0)
        try:
            input_target = int(input_hwnd or 0)
        except (TypeError, ValueError):
            input_target = 0
        if input_target <= 0:
            input_target = display_target
        client = self._ensure_client()
        if display_target != input_target:
            try:
                if client.bind(display_target, input_target, display, mouse, keypad, mode):
                    self._last_input_hwnd = input_target
                    return True
            except Exception:
                pass
            logger.warning(
                "插件分离绑定失败，改用同一句柄重试: display_hwnd=%s input_hwnd=%s display=%s",
                display_target,
                input_target,
                display,
            )
            input_target = display_target
        ok = bool(client.bind(display_target, input_target, display, mouse, keypad, mode))
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
    ) -> Optional[bool]:
        try:
            wait_seconds = max(0.05, float(timeout))
        except Exception:
            wait_seconds = 8.0
        box: dict = {}

        def _worker() -> None:
            try:
                box["ok"] = bool(
                    self._try_bind(display_hwnd, input_hwnd, display, mouse, keypad, mode)
                )
            except Exception as exc:  # noqa: BLE001
                box["err"] = exc
                box["ok"] = False

        worker = threading.Thread(target=_worker, name="plugin-bind", daemon=True)
        worker.start()
        worker.join(wait_seconds)
        if worker.is_alive():
            logger.error(
                "插件绑定超时(%.1fs): display_hwnd=%s input_hwnd=%s display=%s mode=%s",
                wait_seconds,
                display_hwnd,
                int(input_hwnd or 0) or display_hwnd,
                display,
                mode,
            )
            try:
                terminate_plugin_host()
            except Exception:
                logger.debug("terminate_plugin_host 失败", exc_info=True)
            abandon_shared_plugin_client()
            return None
        if box.get("err") is not None:
            logger.debug("插件绑定异常: %s", box["err"], exc_info=True)
        return bool(box.get("ok"))

    def capture_bgr(
        self,
        hwnd: int,
        display: str,
        input_hwnd: int = 0,
        timeout: float = 4.0,
        client_area_only: bool = True,
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
        from utils.capture.engine_ids import iter_plugin_capture_display_candidates

        candidates = iter_plugin_capture_display_candidates(preferred) or (preferred,)
        client = self._ensure_client()
        for display_mode in candidates:
            dm_display = to_dm_display_mode(display_mode)
            for bind_mode in (0, 1):
                outcome = self._bind_with_timeout(
                    target,
                    input_target,
                    dm_display,
                    "normal",
                    "normal",
                    bind_mode,
                    wait_seconds,
                )
                if outcome is None:
                    return None
                if not outcome:
                    continue
                grab_input = int(self._last_input_hwnd or input_target or target)
                frame = client.capture_bgr(target, dm_display, input_hwnd=grab_input)
                if frame is not None:
                    return frame
        return None

    def ensure_input_bind(
        self,
        hwnd: int,
        display: str,
        mouse: str = "dx",
        keypad: str = "dx",
        mode: int = 0,
        input_hwnd: Optional[int] = None,
        timeout: float = 8.0,
    ) -> bool:
        preferred = str(display or "").strip() or DEFAULT_PLUGIN_DISPLAY
        dm_display = to_dm_display_mode(preferred)
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
        modes: list[int] = []
        for bind_mode in (requested_mode, 0, 1):
            if bind_mode not in modes:
                modes.append(bind_mode)
        for bind_mode in modes:
            outcome = self._bind_with_timeout(
                int(hwnd or 0),
                int(input_hwnd or 0),
                dm_display,
                wanted_mouse,
                wanted_keypad,
                bind_mode,
                wait_seconds,
            )
            if outcome is None:
                return False
            if outcome:
                return True
        return False

    def last_error(self) -> int:
        try:
            return int(self._ensure_client().last_error() or 0)
        except Exception:
            return 0
