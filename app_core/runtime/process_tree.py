"""Cross-module process tree termination policy."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class ProcessTerminationResult:
    pid: int
    already_stopped: bool
    forced: bool
    returncode: Optional[int]


class ProcessTerminationError(RuntimeError):
    def __init__(self, pid: int, message: str):
        self.pid = int(pid)
        super().__init__(f"failed to terminate process tree pid={self.pid}: {message}")


def terminate_process_tree(
    process: Any,
    *,
    wait_timeout: float = 3.0,
    force: bool = True,
) -> ProcessTerminationResult:
    if process is None:
        return ProcessTerminationResult(0, True, False, None)
    try:
        pid = int(process.pid or 0)
    except (AttributeError, TypeError, ValueError):
        pid = 0
    if pid <= 0:
        raise ProcessTerminationError(pid, "invalid process id")

    try:
        returncode = process.poll()
    except Exception as exc:
        raise ProcessTerminationError(pid, f"poll failed: {exc}") from exc
    if returncode is not None:
        return ProcessTerminationResult(pid, True, False, int(returncode))

    forced = False
    if os.name == "nt" and force:
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=max(0.1, float(wait_timeout)),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        forced = True
        if result.returncode not in (0, 128):
            # A racing natural exit is still success.
            if process.poll() is None:
                raise ProcessTerminationError(pid, f"taskkill exit code {result.returncode}")
    else:
        try:
            process.terminate()
        except Exception as exc:
            if process.poll() is None:
                raise ProcessTerminationError(pid, f"terminate failed: {exc}") from exc

    try:
        returncode = process.wait(timeout=max(0.1, float(wait_timeout)))
    except subprocess.TimeoutExpired:
        if not force:
            raise ProcessTerminationError(pid, "graceful termination timed out")
        try:
            process.kill()
            forced = True
            returncode = process.wait(timeout=max(0.1, float(wait_timeout)))
        except Exception as exc:
            raise ProcessTerminationError(pid, f"forced termination failed: {exc}") from exc

    return ProcessTerminationResult(pid, False, forced, int(returncode))


__all__ = [
    "ProcessTerminationError",
    "ProcessTerminationResult",
    "terminate_process_tree",
]
