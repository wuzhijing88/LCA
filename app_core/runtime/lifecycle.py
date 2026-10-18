"""Idempotent teardown registry shared by stop and application exit."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable, Optional


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TeardownResult:
    name: str
    ok: bool
    error: str = ""


@dataclass
class _TeardownEntry:
    name: str
    callback: Callable[[], object]
    priority: int
    once: bool
    executed: bool = False


class RuntimeLifecycle:
    def __init__(self):
        self._lock = threading.RLock()
        self._entries: dict[str, _TeardownEntry] = {}
        self._closing = False

    @property
    def closing(self) -> bool:
        with self._lock:
            return self._closing

    def register(
        self,
        name: str,
        callback: Callable[[], object],
        *,
        priority: int = 100,
        once: bool = True,
    ) -> None:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise ValueError("teardown name cannot be empty")
        if not callable(callback):
            raise TypeError("teardown callback must be callable")
        with self._lock:
            self._entries[normalized_name] = _TeardownEntry(
                name=normalized_name,
                callback=callback,
                priority=int(priority),
                once=bool(once),
            )

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self._entries.pop(str(name or "").strip(), None) is not None

    def teardown(self, *, final: bool = False) -> list[TeardownResult]:
        with self._lock:
            if final:
                self._closing = True
            entries = sorted(
                self._entries.values(),
                key=lambda item: (item.priority, item.name),
            )

        results: list[TeardownResult] = []
        for entry in entries:
            with self._lock:
                if entry.once and entry.executed:
                    continue
                entry.executed = True
            try:
                entry.callback()
            except Exception as exc:
                logger.warning("runtime teardown failed: %s: %s", entry.name, exc, exc_info=True)
                results.append(TeardownResult(entry.name, False, str(exc)))
            else:
                results.append(TeardownResult(entry.name, True))
        return results

    def reset_nonfinal(self) -> None:
        with self._lock:
            if self._closing:
                return
            for entry in self._entries.values():
                if not entry.once:
                    entry.executed = False


_GLOBAL_LIFECYCLE: Optional[RuntimeLifecycle] = None
_GLOBAL_LOCK = threading.Lock()


def get_runtime_lifecycle() -> RuntimeLifecycle:
    global _GLOBAL_LIFECYCLE
    with _GLOBAL_LOCK:
        if _GLOBAL_LIFECYCLE is None:
            _GLOBAL_LIFECYCLE = RuntimeLifecycle()
        return _GLOBAL_LIFECYCLE
