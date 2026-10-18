"""Cooperative debugger primitives for the custom script runtime.

The controller is deliberately independent from Qt. ``run_script`` can call
``before_line(lineno, locals)`` from its trace hook and expose ``stopped`` to
the runtime's stop checker. A GUI may drive it from another thread.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Iterable, Optional, Set


class ScriptDebugController:
    """Thread-safe run/pause/step controller used by the script trace hook."""

    def __init__(self, event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None) -> None:
        self._condition = threading.Condition()
        self._breakpoints: Set[int] = set()
        self._paused = False
        self._step_once = False
        self._stop = False
        self._running = False
        self._callback = event_callback
        self._started_at = 0.0
        self._finished = False
        self._variable_names: Optional[Set[str]] = None

    def set_callback(self, callback: Optional[Callable[[str, Dict[str, Any]], None]]) -> None:
        self._callback = callback

    def set_variable_names(self, names: Optional[Iterable[str]]) -> None:
        """设置脚本变量快照白名单。

        ``run_script`` 的执行命名空间还包含命令、视图和运行时辅助对象；这些
        对象不是用户变量，不能直接展示在调试面板中。未设置白名单时保留控制器
        的通用行为，便于独立调用 ``before_line``。
        """
        if names is None:
            normalized = None
        else:
            normalized = {str(name) for name in names if str(name) and not str(name).startswith("_")}
        with self._condition:
            self._variable_names = normalized

    def trace(self, frame, event, arg):
        """sys.settrace callback; safe to pass directly to ``sys.settrace``."""
        if event == "line" and not self.before_line(frame.f_lineno, frame.f_locals):
            return None
        return self.trace

    @property
    def breakpoints(self) -> Set[int]:
        with self._condition:
            return set(self._breakpoints)

    def set_breakpoint(self, lineno: int, enabled: bool = True) -> None:
        line = int(lineno)
        if line < 1:
            return
        with self._condition:
            (self._breakpoints.add(line) if enabled else self._breakpoints.discard(line))
        self._emit("breakpoint", {"line": line, "enabled": bool(enabled)})

    def toggle_breakpoint(self, lineno: int) -> bool:
        line = int(lineno)
        with self._condition:
            enabled = line not in self._breakpoints
            (self._breakpoints.add(line) if enabled else self._breakpoints.discard(line))
        self._emit("breakpoint", {"line": line, "enabled": enabled})
        return enabled

    def clear_breakpoints(self) -> None:
        with self._condition:
            self._breakpoints.clear()

    def replace_breakpoints(self, lines: Iterable[int]) -> None:
        """一次性用整份断点行号（1 基）覆盖旧集合，只加一次锁、只发一次事件。

        编辑器把块标记算出的断点行整体推过来时用它，避免“先清空再逐条添加”
        造成的中间态和多次 ``breakpoint`` 事件。
        """
        new_lines = {int(line) for line in lines if int(line) >= 1}
        with self._condition:
            self._breakpoints = set(new_lines)
        self._emit("breakpoints", {"lines": sorted(new_lines)})

    def start(self) -> None:
        with self._condition:
            self._running, self._paused, self._step_once, self._stop = True, False, False, False
            self._finished = False
            self._started_at = time.monotonic()
            self._condition.notify_all()
        self._emit("started", {})

    def pause(self) -> None:
        with self._condition:
            if not self._running:
                return
            self._paused = True
        self._emit("paused", {})

    def continue_run(self) -> None:
        with self._condition:
            if self._finished:
                return
            self._paused = False; self._step_once = False; self._condition.notify_all()
        self._emit("continued", {})

    def step(self) -> None:
        with self._condition:
            if self._finished:
                return
            self._step_once = True; self._paused = False; self._condition.notify_all()
        self._emit("step", {})

    def stop(self) -> None:
        with self._condition:
            was_active = self._running or self._paused
            if self._stop and not was_active:
                return
            self._stop = True; self._running = False; self._paused = False; self._condition.notify_all()
        if not was_active:
            return
        self._emit("stopped", {})

    def stopped(self) -> bool:
        with self._condition:
            return self._stop

    def before_line(self, lineno: int, locals_map: Optional[Dict[str, Any]] = None) -> bool:
        """Pause at a traced source line. Returns False when execution should stop.

        单步语义：暂停在第 N 行 → 单步 → 第 N 行执行 → 暂停在第 N+1 行。
        进入本行时若 ``_step_once`` 已置位，则在“本行”暂停并清除该标志，
        不再把暂停推迟到下一行。
        """
        line = int(lineno)
        with self._condition:
            if self._stop:
                return False
            hit_breakpoint = line in self._breakpoints
            if self._step_once:
                self._paused = True
                self._step_once = False
            elif hit_breakpoint:
                self._paused = True
            should_wait = self._paused
        self._emit("line", {"line": line})
        if should_wait:
            # 发出 "line" 后到这里之间可能已经 continue_run()/stop()：重新确认仍处于
            # 暂停，否则 "continued" 事件已经先发出，这里再补 "break" 会导致
            # “继续”早于“断点”的乱序；不再暂停时直接跳过 break 与等待。
            with self._condition:
                if self._stop:
                    return False
                if not self._paused:
                    return True
            # 变量快照只在真正暂停时计算，并且只放进 "break" 事件负载，
            # 避免每一行都携带快照拖慢逐行追踪。
            payload = {"line": line}
            if isinstance(locals_map, dict):
                payload["variables"] = self._snapshot_variables(locals_map)
            self._emit("break", payload)
            with self._condition:
                while self._paused and not self._stop:
                    self._condition.wait(timeout=0.25)
                if self._stop:
                    return False
        return True

    def _snapshot_variables(self, locals_map: Dict[str, Any]) -> Dict[str, str]:
        with self._condition:
            allowed = None if self._variable_names is None else set(self._variable_names)
        variables: Dict[str, str] = {}
        for name, value in locals_map.items():
            name_text = str(name)
            if name_text.startswith("_") or (allowed is not None and name_text not in allowed):
                continue
            try:
                text = repr(value)
            except Exception:
                text = f"<{type(value).__name__}>"
            variables[str(name)] = text[:512]
        return variables

    def finish(self, success: Optional[bool] = None, detail: str = "") -> None:
        with self._condition:
            if self._finished:
                return
            self._running = False
            self._paused = False
            self._step_once = False
            self._finished = True
            payload = {"success": success, "detail": str(detail), "elapsed": max(0.0, time.monotonic() - self._started_at)}
            self._condition.notify_all()
        self._emit("finished", payload)

    def is_running(self) -> bool:
        with self._condition:
            return self._running

    def _emit(self, event: str, payload: Dict[str, Any]) -> None:
        callback = self._callback
        if callback:
            try:
                callback(event, dict(payload))
            except Exception:
                pass


def trace_for(controller: ScriptDebugController):
    """Return a ``sys.settrace`` compatible callback for ``run_script``."""
    return controller.trace
