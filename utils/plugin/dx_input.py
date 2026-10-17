# -*- coding: utf-8 -*-
"""插件 mouse=dx / keypad=dx：客户区坐标输入。"""

from __future__ import annotations

import logging
import math
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
        self._pressed_mouse_buttons = set()
        explicit_input = 0 if input_hwnd is None else int(input_hwnd)
        if explicit_input < 0:
            raise ValueError("插件输入窗口句柄无效")
        self._explicit_input_hwnd = explicit_input if explicit_input > 0 else 0

    def _resolved_input_hwnd(self) -> int:
        if self._explicit_input_hwnd > 0:
            return self._explicit_input_hwnd
        from utils.window.window_binding_utils import resolve_plugin_input_hwnd_for_display

        input_hwnd = int(resolve_plugin_input_hwnd_for_display(self.hwnd))
        if input_hwnd <= 0:
            raise RuntimeError("无法确定插件输入窗口")
        return input_hwnd

    def _session(self) -> PluginSession:
        if self._injected_client is None:
            return get_shared_plugin_client(self.hwnd)
        if isinstance(self._injected_client, PluginSession):
            return self._injected_client
        return PluginSession(client=self._injected_client)

    def _load_bind_params(self) -> tuple[str, str, str, int]:
        from utils.runtime_config import get_runtime_config

        cfg = get_runtime_config()
        from utils.plugin.bind_modes import (
            normalize_plugin_bind_mode,
            normalize_plugin_keypad,
            normalize_plugin_mouse,
        )

        mouse = normalize_plugin_mouse(cfg.get("plugin_mouse"))
        keypad = normalize_plugin_keypad(cfg.get("plugin_keypad"))
        mode = normalize_plugin_bind_mode(cfg.get("plugin_bind_mode"))
        display = resolve_plugin_display_mode(self.display or cfg.get("plugin_input_display"))
        return display, mouse, keypad, mode

    def _ready(self) -> bool:
        if self.hwnd <= 0:
            return False
        if self._injected_client is None and not is_plugin_runtime_available():
            logger.error("插件键鼠需要安装目录内的 tools/plugin 运行库（PluginHost.exe / dm.dll）")
            return False
        session = self._session()
        display, mouse, keypad, mode = self._load_bind_params()
        input_hwnd = as_hwnd(self._resolved_input_hwnd())
        if not session.ensure_input_bind(
            self.hwnd,
            display,
            mouse=mouse,
            keypad=keypad,
            mode=mode,
            input_hwnd=input_hwnd,
            timeout=8.0,
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

        enabled = get_runtime_config().get("plugin_text_ime", False)
        if not isinstance(enabled, bool):
            raise ValueError("插件文本输入法选项必须是布尔值")
        return enabled

    def send_text(self, text: str, stop_checker=None, delay: float = 0.0) -> bool:
        """文字按选项调用 SendString 或 SendStringIme；正间隔逐字发送。"""
        pause = float(delay)
        if not math.isfinite(pause) or pause < 0:
            raise ValueError("文字输入间隔必须是大于等于零的有限数字")
        if stop_checker and stop_checker():
            raise InterruptedError("插件文字输入已停止")
        value = str(text or "")
        if not value:
            return True
        use_ime = self._text_ime_enabled()
        if not self._ready():
            return False
        target = as_hwnd(self._resolved_input_hwnd())
        chunks = (value,) if pause == 0 else value
        for index, chunk in enumerate(chunks):
            if stop_checker and stop_checker():
                raise InterruptedError("插件文字输入已停止")
            if not self._client.send_string(self.hwnd, chunk, ime=use_ime, target=target):
                return False
            if pause > 0 and index + 1 < len(chunks):
                precise_sleep(pause)
        return True

    def move_to(self, x: int, y: int) -> bool:
        if not self._ready():
            return False
        return bool(self._client.move_to(int(x), int(y), hwnd=self.hwnd))

    def mouse_down(self, button: str = "left") -> bool:
        if not self._ready():
            return False
        self._pressed_mouse_buttons.add(button)
        return bool(self._client.mouse_down(button, hwnd=self.hwnd))

    def mouse_up(self, button: str = "left") -> bool:
        if not self._ready():
            return False
        released = bool(self._client.mouse_up(button, hwnd=self.hwnd))
        if released:
            self._pressed_mouse_buttons.discard(button)
        return released

    def close(self) -> bool:
        released = True
        for button in list(self._pressed_mouse_buttons):
            try:
                if not self.mouse_up(button):
                    released = False
            except Exception:
                released = False
        if released:
            self._client = None
            self._injected_client = None
        return released

    def mouse_click(self, button: str = "left") -> bool:
        if not self._ready():
            return False
        self._pressed_mouse_buttons.add(button)
        completed = False
        try:
            completed = bool(self._client.mouse_click(button, hwnd=self.hwnd))
            return completed
        finally:
            if completed:
                self._pressed_mouse_buttons.discard(button)
            else:
                self.mouse_up(button)

    def mouse_double_click(self, button: str = "left") -> bool:
        if not self._ready():
            return False
        self._pressed_mouse_buttons.add(button)
        completed = False
        try:
            completed = bool(self._client.mouse_double_click(button, hwnd=self.hwnd))
            return completed
        finally:
            if completed:
                self._pressed_mouse_buttons.discard(button)
            else:
                self.mouse_up(button)

    def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.1,
        duration: Optional[float] = None,
    ) -> bool:
        safe_clicks = int(clicks)
        safe_interval = float(interval)
        hold = DEFAULT_CLICK_HOLD_SECONDS if duration is None else float(duration)
        if safe_clicks <= 0 or safe_clicks != float(clicks) or not math.isfinite(safe_interval) or not math.isfinite(hold) or safe_interval < 0 or hold < 0:
            raise ValueError("点击次数或时间参数无效")
        if self._pressed_mouse_buttons or not self.move_to(x, y):
            return False
        for index in range(safe_clicks):
            if index > 0 and safe_interval > 0:
                precise_sleep(safe_interval)
            if hold > 0:
                try:
                    if not self.mouse_down(button):
                        return False
                    precise_sleep(hold)
                finally:
                    released = self.mouse_up(button)
                if not released:
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
        """插件原生双击仅支持左键，其他按钮直接失败。"""
        if button != "left":
            logger.error("插件不支持该鼠标按钮的原生双击：%s", button)
            return False
        if self._pressed_mouse_buttons or not self.move_to(x, y):
            return False
        return self.mouse_double_click("left")

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
