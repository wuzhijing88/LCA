# -*- coding: utf-8 -*-
"""全局设置保存后，让插件运行时跟上新配置。

- 绑定相关参数（后端、截图引擎、mouse/keypad/display/mode）变化：立即 UnBindWindow，
  避免切回原生后目标窗口仍挂着大漠钩子；下一次插件动作会按新参数重新绑定。
- 注册码 / 附加码变化：终止共享宿主，下一次使用用新码重起。
- 切到插件或绑定参数变化：调用方应对绑定列表里的窗口重新试绑（见 bind_probe）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping, Optional

from utils.capture.engine_ids import is_plugin_screenshot_engine
from utils.input_simulation.mode_utils import is_plugin_input_backend

logger = logging.getLogger(__name__)

PLUGIN_BIND_SETTING_KEYS = (
    "input_backend",
    "screenshot_engine",
    "plugin_mouse",
    "plugin_keypad",
    "plugin_input_display",
    "plugin_input_display_follow",
    "plugin_bind_kind",
    "plugin_bind_mode",
    "plugin_text_ime",
    "plugin_fake_active",
)
PLUGIN_AUTH_SETTING_KEYS = ("plugin_reg_code", "plugin_extra_code")
PLUGIN_SETTING_KEYS = PLUGIN_BIND_SETTING_KEYS + PLUGIN_AUTH_SETTING_KEYS


def plugin_settings_view(config: Optional[Mapping]) -> dict:
    values = dict(config or {})
    return {key: values.get(key) for key in PLUGIN_SETTING_KEYS}


def _uses_plugin(config: Mapping) -> bool:
    values = dict(config or {})
    return is_plugin_input_backend(values) or is_plugin_screenshot_engine(values.get("screenshot_engine"))


@dataclass(frozen=True)
class PluginSettingsDiff:
    bind_changed: bool
    auth_changed: bool
    uses_plugin_now: bool
    used_plugin_before: bool

    @property
    def needs_reprobe(self) -> bool:
        return self.uses_plugin_now and (self.bind_changed or not self.used_plugin_before)

    @property
    def changed(self) -> bool:
        return self.bind_changed or self.auth_changed


def _normalized(value) -> str:
    return str(value if value is not None else "").strip().lower()


def diff_plugin_settings(old: Optional[Mapping], new: Optional[Mapping]) -> PluginSettingsDiff:
    before = dict(old or {})
    after = dict(new or {})
    bind_changed = any(_normalized(before.get(key)) != _normalized(after.get(key)) for key in PLUGIN_BIND_SETTING_KEYS)
    auth_changed = any(str(before.get(key) or "") != str(after.get(key) or "") for key in PLUGIN_AUTH_SETTING_KEYS)
    return PluginSettingsDiff(
        bind_changed=bind_changed,
        auth_changed=auth_changed,
        uses_plugin_now=_uses_plugin(after),
        used_plugin_before=_uses_plugin(before),
    )


def sync_plugin_runtime_after_settings_change(diff: PluginSettingsDiff) -> str:
    """按差异动作，返回做了什么（"terminated" / "unbound" / ""），失败只记日志。"""
    if diff.auth_changed:
        try:
            from utils.plugin.runtime import schedule_plugin_host_prewarm, terminate_plugin_host

            terminate_plugin_host()
            logger.info("插件注册码/附加码已变更，共享宿主已终止")
            if diff.uses_plugin_now:
                # 立刻用新码预热：附着的子进程才能重连，注册码错了也能马上在日志里看到
                schedule_plugin_host_prewarm()
                logger.info("已用新注册码预热插件宿主")
            return "terminated"
        except Exception as exc:
            logger.warning("注册码变更后终止插件宿主失败: %s", exc)
            return ""
    if diff.bind_changed:
        try:
            from utils.plugin.session import unbind_shared_plugin_windows

            if unbind_shared_plugin_windows():
                logger.info("插件绑定参数已变更，已解除当前窗口绑定")
                return "unbound"
        except Exception as exc:
            logger.warning("绑定参数变更后解除插件绑定失败: %s", exc)
    return ""


__all__ = [
    "PLUGIN_AUTH_SETTING_KEYS",
    "PLUGIN_BIND_SETTING_KEYS",
    "PLUGIN_SETTING_KEYS",
    "PluginSettingsDiff",
    "diff_plugin_settings",
    "plugin_settings_view",
    "sync_plugin_runtime_after_settings_change",
]
