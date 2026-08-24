"""Cooperative cancellation with an optional monotonic deadline."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional


class OperationCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class CancellationSnapshot:
    cancelled: bool
    reason: str
    deadline: Optional[float]
    remaining_seconds: Optional[float]


class CancelToken:
    def __init__(self, *, deadline: Optional[float] = None):
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason = ""
        self._deadline = float(deadline) if deadline is not None else None

    @classmethod
    def with_timeout(cls, timeout_seconds: float) -> "CancelToken":
        timeout = max(0.0, float(timeout_seconds))
        return cls(deadline=time.monotonic() + timeout)

    def cancel(self, reason: str = "cancelled") -> bool:
        with self._lock:
            if self._event.is_set():
                return False
            self._reason = str(reason or "cancelled")
            self._event.set()
            return True

    @property
    def deadline(self) -> Optional[float]:
        return self._deadline

    @property
    def reason(self) -> str:
        if self._deadline_expired() and not self._event.is_set():
            self.cancel("deadline_exceeded")
        with self._lock:
            return self._reason

    def _deadline_expired(self) -> bool:
        return self._deadline is not None and time.monotonic() >= self._deadline

    def is_cancelled(self) -> bool:
        if self._deadline_expired():
            self.cancel("deadline_exceeded")
        return self._event.is_set()

    def remaining_seconds(self) -> Optional[float]:
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - time.monotonic())

    def wait(self, timeout: Optional[float] = None) -> bool:
        remaining = self.remaining_seconds()
        wait_timeout = timeout
        if remaining is not None:
            wait_timeout = remaining if timeout is None else min(max(0.0, float(timeout)), remaining)
        triggered = self._event.wait(wait_timeout)
        return triggered or self.is_cancelled()

    def checkpoint(self) -> None:
        if self.is_cancelled():
            raise OperationCancelled(self.reason or "cancelled")

    def snapshot(self) -> CancellationSnapshot:
        return CancellationSnapshot(
            cancelled=self.is_cancelled(),
            reason=self.reason,
            deadline=self.deadline,
            remaining_seconds=self.remaining_seconds(),
        )
