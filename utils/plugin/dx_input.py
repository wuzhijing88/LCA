# -*- coding: utf-8 -*-
"""插件 mouse=dx / keypad=dx：客户区坐标输入。"""

from __future__ import annotations

import logging
from typing import Optional

from utils.input.input_timing import DEFAULT_CLICK_HOLD_SECONDS
from utils.plugin.runtime import is_plugin_runtime_available
from utils.plugin.session import PluginSession, get_shared_plugin_client, resolve_plugin_display_mode
from utils.precise_sleep import precise_sleep
from utils.window.hwnd_utils import as_hwnd

logger = logging.getLogger(__name__)


class PluginDxInput:
    """在已绑定窗口上调用插件键鼠 API。坐标一律是客户区。"""

    def __init__(
        self,
        hwnd: int,
        display: Optional[str] = None,
        client=None,
        input_hwnd: Optional[int] = None,
    ):
        self.hwnd = int(hwnd or 0)
        self.display = display
        self._injected_client = client
        self._client = client
        try:
            explicit_input = int(input_hwnd or 0)
        except (TypeError, ValueError):
            explicit_input = 0
        self._explicit_input_hwnd = explicit_input if explicit_input > 0 else 0

    def _resolved_input_hwnd(self) -> int:
        if self._explicit_input_hwnd > 0:
            return self._explicit_input_hwnd
        try:
            from utils.window.window_binding_utils import resolve_plugin_input_hwnd_for_display

            return int(resolve_plugin_input_hwnd_for_display(self.hwnd) or self.hwnd)
        except Exception:
            return self.hwnd

    def _session(self) -> PluginSession:
        if self._injected_client is None:
            return get_shared_plugin_client(self.hwnd)
        if isinstance(self._injected_client, PluginSession):
            return self._injected_client
        return PluginSession(client=self._injected_client)

    def _ready(self) -> bool:
        if self.hwnd <= 0:
            return False
        if self._injected_client is None and not is_plugin_runtime_available():
            logger.error("DX 模式需要插件运行库（tools/plugin 或 LCA_PLUGIN_DIR）")
            return False
        session = self._session()
        display = resolve_plugin_display_mode(self.display)
        input_hwnd = as_hwnd(self._resolved_input_hwnd()) or self.hwnd
        if not session.ensure_input_bind(
            self.hwnd,
            display,
            mouse="dx",
            keypad="dx",
            input_hwnd=input_hwnd,
            timeout=8.0,
        ):
            logger.error(
                "插件 DX 键鼠绑定失败: display_hwnd=%s input_hwnd=%s preferred_display=%s；"
                "32 位游戏若一直卡住/超时，多半是注入被拦或句柄不对。"
                "可试：管理员运行 LCA、核对 PluginHost.exe，或改后台一/二",
                self.hwnd,
                input_hwnd,
                display,
            )
            self._client = None
            return False
        self._client = session._client
        return True

    def move_to(self, x: int, y: int) -> bool:
        if not self._ready():
            return False
        return bool(self._client.move_to(int(x), int(y)))

    def mouse_down(self, button: str = "left") -> bool:
        if not self._ready():
            return False
        return bool(self._client.mouse_down(button))

    def mouse_up(self, button: str = "left") -> bool:
        if not self._ready():
            return False
        return bool(self._client.mouse_up(button))

    def mouse_click(self, button: str = "left") -> bool:
        if not self._ready():
            return False
        return bool(self._client.mouse_click(button))

    def mouse_double_click(self, button: str = "left") -> bool:
        if not self._ready():
            return False
        return bool(self._client.mouse_double_click(button))

    def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.1,
        duration: Optional[float] = None,
    ) -> bool:
        if not self.move_to(x, y):
            return False
        try:
            safe_clicks = max(1, int(clicks))
        except Exception:
            safe_clicks = 1
        try:
            safe_interval = max(0.0, float(interval))
        except Exception:
            safe_interval = 0.0
        try:
            hold = DEFAULT_CLICK_HOLD_SECONDS if duration is None else max(0.0, float(duration))
        except Exception:
            hold = DEFAULT_CLICK_HOLD_SECONDS
        for index in range(safe_clicks):
            if index > 0 and safe_interval > 0:
                precise_sleep(safe_interval)
            if hold > 0:
                if not self.mouse_down(button):
                    return False
                precise_sleep(hold)
                if not self.mouse_up(button):
                    return False
            elif not self.mouse_click(button):
                return False
        return True

    def double_click(self, x: int, y: int, button: str = "left") -> bool:
        if not self.move_to(x, y):
            return False
        return self.mouse_double_click(button)

    def wheel(self, x: int, y: int, delta: int) -> bool:
        if not self.move_to(x, y):
            return False
        return bool(self._client.wheel(int(delta)))

    def key_down(self, vk_code: int) -> bool:
        if not self._ready():
            return False
        return bool(self._client.key_down(int(vk_code)))

    def key_up(self, vk_code: int) -> bool:
        if not self._ready():
            return False
        return bool(self._client.key_up(int(vk_code)))

    def key_press(self, vk_code: int) -> bool:
        if not self._ready():
            return False
        return bool(self._client.key_press(int(vk_code)))

    def key_press_str(self, text: str, delay: int = 30) -> bool:
        if not self._ready():
            return False
        return bool(self._client.key_press_str(str(text or ""), int(delay)))
