from __future__ import annotations

from typing import Any, Iterable, Optional

CANCEL_HOTKEY = "ESC"
MOUSE_SIDE_BUTTONS = ("XBUTTON1", "XBUTTON2")
MODIFIER_ORDER = ("CTRL", "ALT", "SHIFT")

_MODIFIER_ALIASES = {
    "CTRL": "CTRL",
    "CONTROL": "CTRL",
    "LEFT CTRL": "CTRL",
    "RIGHT CTRL": "CTRL",
    "ALT": "ALT",
    "LEFT ALT": "ALT",
    "RIGHT ALT": "ALT",
    "ALT GR": "ALT",
    "SHIFT": "SHIFT",
    "LEFT SHIFT": "SHIFT",
    "RIGHT SHIFT": "SHIFT",
}

_KEY_ALIASES = {
    "ESC": "ESC",
    "ESCAPE": "ESC",
    "ENTER": "ENTER",
    "RETURN": "ENTER",
    "SPACE": "SPACE",
    "SPACEBAR": "SPACE",
    "TAB": "TAB",
    "BACKSPACE": "BACKSPACE",
    "BKSP": "BACKSPACE",
    "DELETE": "DELETE",
    "DEL": "DELETE",
    "INSERT": "INSERT",
    "INS": "INSERT",
    "HOME": "HOME",
    "END": "END",
    "PAGEUP": "PAGE UP",
    "PAGE UP": "PAGE UP",
    "PGUP": "PAGE UP",
    "PAGEDOWN": "PAGE DOWN",
    "PAGE DOWN": "PAGE DOWN",
    "PGDN": "PAGE DOWN",
    "PRINTSCREEN": "PRINT SCREEN",
    "PRINT SCREEN": "PRINT SCREEN",
    "PRTSC": "PRINT SCREEN",
    "SCROLLLOCK": "SCROLL LOCK",
    "SCROLL LOCK": "SCROLL LOCK",
    "PAUSE": "PAUSE",
    "BREAK": "PAUSE",
    "CAPSLOCK": "CAPS LOCK",
    "CAPS LOCK": "CAPS LOCK",
    "NUMLOCK": "NUM LOCK",
    "NUM LOCK": "NUM LOCK",
    "LEFT": "LEFT",
    "RIGHT": "RIGHT",
    "UP": "UP",
    "DOWN": "DOWN",
    "XBUTTON1": "XBUTTON1",
    "XBUTTON2": "XBUTTON2",
    "鼠标侧键1(后退)": "XBUTTON1",
    "鼠标侧键2(前进)": "XBUTTON2",
    "NUMMULTIPLY": "NUM *",
    "NUMADD": "NUM +",
    "NUMSUBTRACT": "NUM -",
    "NUMDIVIDE": "NUM /",
    "NUMDECIMAL": "NUM .",
    "NUM *": "NUM *",
    "NUM +": "NUM +",
    "NUM -": "NUM -",
    "NUM /": "NUM /",
    "NUM .": "NUM .",
}

_KEYBOARD_LIB_NAMES = {
    "ESC": "esc",
    "ENTER": "enter",
    "SPACE": "space",
    "TAB": "tab",
    "BACKSPACE": "backspace",
    "DELETE": "delete",
    "INSERT": "insert",
    "HOME": "home",
    "END": "end",
    "PAGE UP": "page up",
    "PAGE DOWN": "page down",
    "PRINT SCREEN": "print screen",
    "SCROLL LOCK": "scroll lock",
    "PAUSE": "pause",
    "CAPS LOCK": "caps lock",
    "NUM LOCK": "num lock",
    "LEFT": "left",
    "RIGHT": "right",
    "UP": "up",
    "DOWN": "down",
    "NUM *": "num *",
    "NUM +": "num +",
    "NUM -": "num -",
    "NUM /": "num /",
    "NUM .": "num .",
}

_DISPLAY_NAMES = {
    "ESC": "Esc",
    "ENTER": "Enter",
    "SPACE": "Space",
    "PAGE UP": "PageUp",
    "PAGE DOWN": "PageDown",
    "PRINT SCREEN": "PrintScreen",
    "SCROLL LOCK": "ScrollLock",
    "CAPS LOCK": "CapsLock",
    "NUM LOCK": "NumLock",
    "XBUTTON1": "鼠标侧键1(后退)",
    "XBUTTON2": "鼠标侧键2(前进)",
    "CTRL": "Ctrl",
    "ALT": "Alt",
    "SHIFT": "Shift",
}

_MODIFIER_EVENT_NAMES = {
    "ctrl",
    "left ctrl",
    "right ctrl",
    "control",
    "alt",
    "left alt",
    "right alt",
    "alt gr",
    "shift",
    "left shift",
    "right shift",
    "windows",
    "left windows",
    "right windows",
    "cmd",
    "win",
}

_KEYPAD_NAV = {
    "end": "NUM 1",
    "down": "NUM 2",
    "page down": "NUM 3",
    "pagedown": "NUM 3",
    "left": "NUM 4",
    "clear": "NUM 5",
    "right": "NUM 6",
    "home": "NUM 7",
    "up": "NUM 8",
    "page up": "NUM 9",
    "pageup": "NUM 9",
    "insert": "NUM 0",
    "delete": "NUM .",
}

_capture_active = False


def set_hotkey_capture_active(active: bool) -> None:
    global _capture_active
    _capture_active = bool(active)


def is_hotkey_capture_active() -> bool:
    return _capture_active


def _alias_token(token: str) -> str:
    text = " ".join(str(token or "").strip().upper().split())
    if not text:
        return ""
    if text in _MODIFIER_ALIASES:
        return _MODIFIER_ALIASES[text]
    if text in _KEY_ALIASES:
        return _KEY_ALIASES[text]
    compact = text.replace(" ", "")
    if compact in _KEY_ALIASES:
        return _KEY_ALIASES[compact]
    if compact.startswith("NUM") and len(compact) > 3:
        rest = compact[3:]
        if rest.isdigit() or rest in {"*", "+", "-", "/", "."}:
            return f"NUM {rest}"
    if text.startswith("F") and text[1:].isdigit():
        return f"F{int(text[1:])}"
    if len(text) == 1:
        return text
    return text


def normalize_hotkey(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text in _KEY_ALIASES:
        return _KEY_ALIASES[text]
    parts = [_alias_token(part) for part in text.replace("-", "+").split("+")]
    parts = [part for part in parts if part]
    if not parts:
        return ""
    modifiers = [name for name in MODIFIER_ORDER if name in parts]
    keys = [part for part in parts if part not in _MODIFIER_ALIASES.values()]
    if not keys:
        return modifiers[-1] if modifiers else ""
    return "+".join(modifiers + [keys[-1]])


def display_hotkey(value: Any) -> str:
    spec = normalize_hotkey(value)
    if not spec:
        return "未设置"
    labels = [_DISPLAY_NAMES.get(part, part.title() if len(part) > 1 else part) for part in spec.split("+")]
    return "+".join(labels)


def is_mouse_hotkey(value: Any) -> bool:
    return normalize_hotkey(value) in MOUSE_SIDE_BUTTONS


def is_cancel_hotkey(value: Any) -> bool:
    return normalize_hotkey(value) == CANCEL_HOTKEY


def mouse_hook_button(value: Any) -> Optional[str]:
    spec = normalize_hotkey(value)
    if spec == "XBUTTON1":
        return "x"
    if spec == "XBUTTON2":
        return "x2"
    return None


def to_keyboard_lib(value: Any) -> str:
    spec = normalize_hotkey(value)
    if not spec or spec in MOUSE_SIDE_BUTTONS:
        return ""
    pieces = []
    for part in spec.split("+"):
        if part in MODIFIER_ORDER:
            pieces.append(part.lower())
        else:
            pieces.append(_KEYBOARD_LIB_NAMES.get(part, part.lower()))
    return "+".join(pieces)


def spec_from_keyboard_event(event: Any) -> str:
    raw = str(getattr(event, "name", "") or "").strip().lower()
    if not raw or raw in _MODIFIER_EVENT_NAMES:
        return ""
    if getattr(event, "is_keypad", False):
        if raw in _KEYPAD_NAV:
            base = _KEYPAD_NAV[raw]
        elif len(raw) == 1 and raw.isdigit():
            base = f"NUM {raw}"
        elif raw in {"+", "-", "*", "/", "decimal", ".", "separator"}:
            base = "NUM ." if raw in {"decimal", ".", "separator"} else f"NUM {raw}"
        else:
            base = _alias_token(raw)
    else:
        base = _alias_token(raw)
    if not base or base in MODIFIER_ORDER:
        return ""
    modifiers = []
    try:
        import keyboard

        if keyboard.is_pressed("ctrl"):
            modifiers.append("CTRL")
        if keyboard.is_pressed("alt"):
            modifiers.append("ALT")
        if keyboard.is_pressed("shift"):
            modifiers.append("SHIFT")
    except Exception:
        pass
    return "+".join(modifiers + [base])


def spec_from_qt_key(event: Any) -> str:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeySequence
    except Exception:
        return ""

    key = int(event.key())
    if key in {
        int(Qt.Key.Key_Control),
        int(Qt.Key.Key_Shift),
        int(Qt.Key.Key_Alt),
        int(Qt.Key.Key_Meta),
        int(Qt.Key.Key_unknown),
    }:
        return ""

    raw = QKeySequence(key).toString()
    mods = event.modifiers()
    if mods & Qt.KeyboardModifier.KeypadModifier:
        keypad = _qt_keypad_name(key, raw)
        if keypad:
            raw = keypad
    base = _alias_token(raw)
    if not base or base in MODIFIER_ORDER:
        return ""

    modifiers = []
    if mods & Qt.KeyboardModifier.ControlModifier:
        modifiers.append("CTRL")
    if mods & Qt.KeyboardModifier.AltModifier:
        modifiers.append("ALT")
    if mods & Qt.KeyboardModifier.ShiftModifier:
        modifiers.append("SHIFT")
    return "+".join(modifiers + [base])


def spec_from_qt_mouse(event: Any) -> str:
    try:
        from PySide6.QtCore import Qt
    except Exception:
        return ""
    button = event.button()
    if button == Qt.MouseButton.XButton1:
        return "XBUTTON1"
    if button == Qt.MouseButton.XButton2:
        return "XBUTTON2"
    return ""


def _qt_keypad_name(key: int, fallback: str) -> str:
    try:
        from PySide6.QtCore import Qt
    except Exception:
        return fallback
    mapping = {
        int(Qt.Key.Key_0): "NUM 0",
        int(Qt.Key.Key_1): "NUM 1",
        int(Qt.Key.Key_2): "NUM 2",
        int(Qt.Key.Key_3): "NUM 3",
        int(Qt.Key.Key_4): "NUM 4",
        int(Qt.Key.Key_5): "NUM 5",
        int(Qt.Key.Key_6): "NUM 6",
        int(Qt.Key.Key_7): "NUM 7",
        int(Qt.Key.Key_8): "NUM 8",
        int(Qt.Key.Key_9): "NUM 9",
        int(Qt.Key.Key_Asterisk): "NUM *",
        int(Qt.Key.Key_Plus): "NUM +",
        int(Qt.Key.Key_Minus): "NUM -",
        int(Qt.Key.Key_Slash): "NUM /",
        int(Qt.Key.Key_Period): "NUM .",
        int(Qt.Key.Key_Enter): "ENTER",
    }
    return mapping.get(key, fallback)


def first_conflict(action_keys: dict[str, str], action_names: dict[str, str], preferred: Iterable[str]) -> tuple[dict[str, str], list[str]]:
    resolved = {}
    seen = {}
    conflicts = []
    ordered = list(preferred) + [key for key in action_keys if key not in preferred]
    for action in ordered:
        key = normalize_hotkey(action_keys.get(action))
        if not key:
            continue
        if key in seen:
            conflicts.append(
                f"{display_hotkey(key)}: "
                f"{action_names.get(seen[key], seen[key])} / "
                f"{action_names.get(action, action)}"
            )
            continue
        seen[key] = action
        resolved[action] = key
    return resolved, conflicts
