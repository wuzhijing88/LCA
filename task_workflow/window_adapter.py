"""Configurable window capability boundary for the execution core."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from utils.window.hwnd_utils import as_hwnd
from utils.window.window_identity import is_window_alive, resolve_bound_window_hwnd


@dataclass(frozen=True)
class WindowBinding:
    hwnd: int = 0
    title: str = ""
    bind_id: str = ""
    class_name: str = ""
    process_name: str = ""

    @classmethod
    def from_mapping(cls, value: Optional[Mapping[str, Any]]) -> "WindowBinding":
        source = value or {}
        return cls(
            hwnd=as_hwnd(source.get("hwnd")),
            title=str(source.get("title") or ""),
            bind_id=str(source.get("bind_id") or ""),
            class_name=str(source.get("class_name") or ""),
            process_name=str(source.get("process_name") or ""),
        )

    def as_mapping(self) -> dict[str, Any]:
        return {
            "hwnd": self.hwnd,
            "title": self.title,
            "bind_id": self.bind_id,
            "class_name": self.class_name,
            "process_name": self.process_name,
        }


class WindowAdapter:
    name = "default"

    def resolve(self, binding: WindowBinding) -> WindowBinding:
        hwnd = resolve_bound_window_hwnd(binding.as_mapping())
        if not hwnd:
            return WindowBinding(
                title=binding.title,
                bind_id=binding.bind_id,
                class_name=binding.class_name,
                process_name=binding.process_name,
            )
        resolved = binding.as_mapping()
        resolved["hwnd"] = hwnd
        return WindowBinding.from_mapping(resolved)

    def is_alive(self, hwnd: Any) -> bool:
        return is_window_alive(hwnd)

    def activate_foreground(self, hwnd: Any) -> bool:
        handle = as_hwnd(hwnd)
        if not self.is_alive(handle):
            return False
        try:
            import win32con
            import win32gui

            from utils.window.virtual_desktop import skip_cross_desktop_activation

            if skip_cross_desktop_activation(handle, log_prefix="WindowAdapter"):
                return True
            if win32gui.IsIconic(handle):
                win32gui.ShowWindow(handle, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(handle)
            return True
        except Exception:
            return False

    def client_rect(self, hwnd: Any) -> tuple[int, int, int, int]:
        handle = as_hwnd(hwnd)
        if not self.is_alive(handle):
            raise ValueError(f"invalid window handle: {hwnd!r}")
        import win32gui

        left, top, right, bottom = win32gui.GetClientRect(handle)
        return int(left), int(top), int(right), int(bottom)


_ADAPTERS: dict[str, WindowAdapter] = {WindowAdapter.name: WindowAdapter()}


def register_window_adapter(adapter: WindowAdapter) -> None:
    name = str(getattr(adapter, "name", "") or "").strip().lower()
    if not name:
        raise ValueError("window adapter name cannot be empty")
    _ADAPTERS[name] = adapter


def get_window_adapter(name: str = "default") -> WindowAdapter:
    normalized = str(name or "default").strip().lower()
    try:
        return _ADAPTERS[normalized]
    except KeyError as exc:
        raise KeyError(f"unknown window adapter: {normalized}") from exc


__all__ = [
    "WindowAdapter",
    "WindowBinding",
    "get_window_adapter",
    "register_window_adapter",
]
