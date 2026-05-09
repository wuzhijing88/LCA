from __future__ import annotations

from typing import Callable, Optional


def configure_runtime_security(
    *,
    guard_cb: Optional[Callable[[], None]] = None,
    validator_cb: Optional[Callable[[str, str], bool]] = None,
) -> None:
    return None


def set_runtime_guard(guard_cb: Optional[Callable[[], None]]) -> None:
    return None


def set_runtime_validator(validator_cb: Optional[Callable[[str, str], bool]]) -> None:
    return None


def run_runtime_guard() -> None:
    return None


def run_runtime_validator(hw_id: str, key: str) -> bool:
    return True
