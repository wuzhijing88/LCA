# -*- coding: utf-8 -*-
"""插件 mouse=dx / keypad=dx：客户区坐标输入。"""

from __future__ import annotations

import logging
from typing import Optional

from utils.input.input_timing import DEFAULT_CLICK_HOLD_SECONDS, DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS
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

    def _load_bind_params(self) -> tuple[str, str, str, int]:
        from utils.runtime_config import get_runtime_config

        cfg = get_runtime_config()
        mouse = str(cfg.get("plugin_mouse") or "dx").strip() or "dx"
        keypad = str(cfg.get("plugin_keypad") or "dx").strip() or "dx"
        try:
            mode = int(cfg.get("plugin_bind_mode") or 0)
        except (TypeError, ValueError):
            mode = 0
        display = self.display or cfg.get("plugin_input_display") or None
        display = resolve_plugin_display_mode(display)
        return display, mouse, keypad, mode

    def _ready(self) -> bool:
        if self.hwnd <= 0:
            return False
        if self._injected_client is None and not is_plugin_runtime_available():
            logger.error("插件键鼠需要安装目录内的 tools/plugin 运行库（PluginHost.exe / dm.dll / RegDll.dll）")
            return False
        session = self._session()
        display, mouse, keypad, mode = self._load_bind_params()
        input_hwnd = as_hwnd(self._resolved_input_hwnd()) or self.hwnd
        if not session.ensure_input_bind(
            self.hwnd,
            display,
            mouse=mouse,
            keypad=keypad,
            mode=mode,
            input_hwnd=input_hwnd,
            timeout=8.0,
            fallback=False,
        ):
            logger.error(
                "插件键鼠绑定失败: display_hwnd=%s input_hwnd=%s %s；"
                "若一直超时多半是注入被安全软件拦截或句柄不对，可试管理员运行、换绑定模式或改用原生后台",
                self.hwnd,
                input_hwnd,
                session.last_bind_failure_text(),
            )
            self._client = None
            return False
        self._client = session._client
        return True

    def _text_ime_enabled(self) -> bool:
        from utils.runtime_config import get_runtime_config

        try:
            return bool(get_runtime_config().get("plugin_text_ime", False))
        except Exception:
            return False

    def send_text(self, text: str) -> bool:
        """ASCII 走 KeyPressStr（按键序列）；含中文等非 ASCII 字符时走 SendString（消息注入），
        开启「插件文本走输入法」时优先 SendStringIme（游戏类窗口通常只认这条路）。"""
        value = str(text or "")
        if not value:
            return True
        if not self._ready():
            return False
        if value.isascii():
            return bool(self._client.key_press_str(value, hwnd=self.hwnd))
        target = as_hwnd(self._resolved_input_hwnd()) or self.hwnd
        return bool(self._client.send_string(self.hwnd, value, ime=self._text_ime_enabled(), target=target))

    def move_to(self, x: int, y: int) -> bool:
        if not self._ready():
            return False
        return bool(self._client.move_to(int(x), int(y), hwnd=self.hwnd))

    def mouse_down(self, button: str = "left") -> bool:
        if not self._ready():
            return False
        return bool(self._client.mouse_down(button, hwnd=self.hwnd))

    def mouse_up(self, button: str = "left") -> bool:
        if not self._ready():
            return False
        return bool(self._client.mouse_up(button, hwnd=self.hwnd))

    def mouse_click(self, button: str = "left") -> bool:
        if not self._ready():
            return False
        return bool(self._client.mouse_click(button, hwnd=self.hwnd))

    def mouse_double_click(self, button: str = "left") -> bool:
        if not self._ready():
            return False
        return bool(self._client.mouse_double_click(button, hwnd=self.hwnd))

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

    def double_click(
        self,
        x: int,
        y: int,
        button: str = "left",
        interval: Optional[float] = None,
        hold_duration: Optional[float] = None,
    ) -> bool:
        """左键走大漠 LeftDoubleClick（消息注入模式下两次单击不会被识别为双击）；
        大漠没有 Right/MiddleDoubleClick，非左键用两次按下/松开凑出双击时序。"""
        if not self.move_to(x, y):
            return False
        normalized = str(button or "left").strip().lower()
        if normalized == "left":
            return self.mouse_double_click("left")
        try:
            gap = DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS if interval is None else max(0.0, float(interval))
        except Exception:
            gap = DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS
        try:
            hold = DEFAULT_CLICK_HOLD_SECONDS if hold_duration is None else max(0.0, float(hold_duration))
        except Exception:
            hold = DEFAULT_CLICK_HOLD_SECONDS
        for index in range(2):
            if index > 0 and gap > 0:
                precise_sleep(gap)
            if not self.mouse_down(normalized):
                return False
            if hold > 0:
                precise_sleep(hold)
            if not self.mouse_up(normalized):
                return False
        return True

    def wheel(self, x: int, y: int, delta: int) -> bool:
        """delta 既可能是格数（±3）也可能是 WHEEL_DELTA 单位（±120 的倍数），统一换算成格数交给宿主。"""
        if not self.move_to(x, y):
            return False
        raw = int(delta)
        if raw == 0:
            return False
        magnitude = abs(raw)
        notches = max(1, magnitude // 120) if magnitude >= 120 else magnitude
        return bool(self._client.wheel(notches if raw > 0 else -notches, hwnd=self.hwnd))

    def key_down(self, vk_code: int) -> bool:
        if not self._ready():
            return False
        return bool(self._client.key_down(int(vk_code), hwnd=self.hwnd))

    def key_up(self, vk_code: int) -> bool:
        if not self._ready():
            return False
        return bool(self._client.key_up(int(vk_code), hwnd=self.hwnd))

    def key_press(self, vk_code: int) -> bool:
        if not self._ready():
            return False
        return bool(self._client.key_press(int(vk_code), hwnd=self.hwnd))

    def key_press_str(self, text: str, delay: int = 30) -> bool:
        if not self._ready():
            return False
        return bool(self._client.key_press_str(str(text or ""), int(delay), hwnd=self.hwnd))
