"""Standalone player global hotkeys (same hook path as the editor)."""

from __future__ import annotations

import logging
from typing import Callable, Mapping

from PySide6.QtCore import QObject, QThread, QTimer

from app_core.hotkey_spec import (
    display_hotkey,
    is_hotkey_capture_active,
    is_mouse_hotkey,
    mouse_hook_button,
    normalize_hotkey,
    spec_from_keyboard_event,
)

logger = logging.getLogger(__name__)

PlayerHotkeyCallbacks = Mapping[str, Callable[[], None]]


class PlayerHotkeySession:
    def __init__(self) -> None:
        self._keyboard_hooks: list = []
        self._mouse_hooks: list = []
        self._pressed: dict[str, bool] = {}

    @property
    def keyboard_active(self) -> bool:
        return bool(self._keyboard_hooks)

    def release(self) -> None:
        try:
            import keyboard

            for hook in self._keyboard_hooks:
                try:
                    keyboard.unhook(hook)
                except Exception:
                    pass
        except Exception:
            pass
        self._keyboard_hooks = []
        try:
            import mouse

            for hook in self._mouse_hooks:
                try:
                    mouse.unhook(hook)
                except Exception:
                    pass
        except Exception:
            pass
        self._mouse_hooks = []
        self._pressed = {}


def _queue_on_owner(owner: QObject, callback: Callable[[], None]) -> None:
    if callback is None:
        return
    try:
        if QThread.currentThread() == owner.thread():
            callback()
            return
        QTimer.singleShot(0, owner, callback)
    except Exception:
        logger.debug("投递独立程序热键回调失败", exc_info=True)


def install_global_player_hotkeys(
    owner: QObject,
    hotkeys: Mapping[str, str],
    callbacks: PlayerHotkeyCallbacks,
) -> PlayerHotkeySession:
    session = PlayerHotkeySession()
    action_keys = {
        action: normalize_hotkey(hotkeys.get(action))
        for action in ("start", "stop", "pause")
    }
    action_keys = {action: spec for action, spec in action_keys.items() if spec}
    labels = {
        "start": "开始",
        "stop": "停止",
        "pause": "暂停",
    }
    mouse_keys = {action: spec for action, spec in action_keys.items() if is_mouse_hotkey(spec)}
    keyboard_keys = {
        action: spec for action, spec in action_keys.items() if spec and not is_mouse_hotkey(spec)
    }

    def on_action(action: str) -> None:
        callback = callbacks.get(action)
        if callback is None:
            return
        _queue_on_owner(owner, callback)

    if keyboard_keys:
        try:
            import keyboard

            key_to_action = {spec: action for action, spec in keyboard_keys.items()}

            def on_key_event(event) -> None:
                try:
                    if is_hotkey_capture_active():
                        return
                    if getattr(event, "event_type", "") == "up":
                        base = normalize_hotkey(getattr(event, "name", ""))
                        if base:
                            for spec in list(session._pressed):
                                if spec == base or spec.endswith("+" + base):
                                    session._pressed[spec] = False
                        return
                    spec = spec_from_keyboard_event(event)
                    action = key_to_action.get(spec or "")
                    if not action:
                        return
                    if session._pressed.get(spec, False):
                        return
                    session._pressed[spec] = True
                    on_action(action)
                except Exception:
                    logger.debug("独立程序热键事件处理失败", exc_info=True)

            session._keyboard_hooks.append(keyboard.hook(on_key_event, suppress=False))
            for action, spec in keyboard_keys.items():
                logger.info("独立程序%s快捷键已设置: %s (全局钩子)", labels[action], display_hotkey(spec))
        except Exception:
            logger.warning("独立程序全局键盘热键注册失败，将回退窗口内快捷键", exc_info=True)
            session._keyboard_hooks = []

    if mouse_keys:
        try:
            import mouse

            for action, spec in mouse_keys.items():
                button = mouse_hook_button(spec)
                if not button:
                    continue

                def make_handler(chosen: str):
                    def _handler(*_args, **_kwargs):
                        if is_hotkey_capture_active():
                            return
                        on_action(chosen)

                    return _handler

                session._mouse_hooks.append(
                    mouse.on_button(make_handler(action), buttons=(button,), types=("down",))
                )
                logger.info("独立程序%s快捷键已设置: %s (鼠标侧键)", labels[action], display_hotkey(spec))
        except Exception:
            logger.warning("独立程序鼠标侧键热键注册失败", exc_info=True)

    return session
