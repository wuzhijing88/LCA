from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Optional

from app_core.player.package import PlayerPackage
from app_core.runtime.execution_coordinator import (
    ExecutionSource,
    create_coordinated_workflow_runtime,
)
from task_workflow.workflow_payload import (
    cards_dict_from_workflow,
    connections_from_workflow,
    require_start_card_ids,
)

logger = logging.getLogger(__name__)


class PlayerRuntimeController:
    def __init__(
        self,
        package: PlayerPackage,
        config: dict,
        parent=None,
    ):
        self._package = package
        self._config = dict(config or {})
        self._parent = parent
        self.executor = None
        self.executor_thread = None

    def is_running(self) -> bool:
        executor = self.executor
        if executor is None:
            return False
        getter = getattr(executor, "is_running", None)
        if callable(getter):
            try:
                return bool(getter())
            except Exception:
                return False
        return True

    def is_paused(self) -> bool:
        executor = self.executor
        if executor is None:
            return False
        getter = getattr(executor, "get_pause_state", None)
        if callable(getter):
            try:
                return str(getter() or "").strip().lower() == "paused"
            except Exception:
                return False
        return False

    def update_config(self, config: dict) -> None:
        self._config = dict(config or {})

    def _resolve_workflow_path(self, script_id: str = "") -> str:
        sid = str(script_id or "").strip()
        if not sid:
            return self._package.entry_workflow_path
        from pathlib import Path

        from app_core.player.memory_store import get_player_memory_file, memory_uri

        candidates: list[str] = []
        for meta in self._package.manifest.get("scripts") or []:
            if not isinstance(meta, Mapping):
                continue
            if str(meta.get("id") or "") != sid:
                continue
            rel = str(meta.get("path") or "").replace("\\", "/").lstrip("/")
            if rel:
                candidates.append(rel)
        candidates.append(f"workflows/scripts/{sid}.json")
        for rel in candidates:
            if get_player_memory_file(rel):
                return memory_uri(rel)
            package_dir = str(self._package.package_dir or "")
            if package_dir:
                disk = Path(package_dir) / rel
                if disk.is_file():
                    return str(disk)
        return self._package.entry_workflow_path

    def start(
        self,
        *,
        on_started: Optional[Callable[[], Any]] = None,
        on_finished: Optional[Callable[[bool, str], Any]] = None,
        on_step_log: Optional[Callable[[str, str, bool], Any]] = None,
        workflow_data: Optional[Mapping[str, Any]] = None,
        script_id: str = "",
    ) -> None:
        if self.is_running():
            return
        self.stop(force=True)
        from utils.window.hwnd_utils import as_hwnd
        from utils.window.window_identity import is_window_alive, refresh_bound_windows

        bound_windows = [
            dict(item)
            for item in (self._config.get("bound_windows") or [])
            if isinstance(item, dict)
        ]
        if not bound_windows:
            raise RuntimeError("请先绑定目标窗口后再开始执行。")
        refresh_bound_windows(bound_windows)
        alive_count = sum(
            1 for item in bound_windows if is_window_alive(as_hwnd(item.get("hwnd")))
        )
        if alive_count <= 0:
            raise RuntimeError(
                "已绑定窗口当前都不在线。请打开目标窗口后，在「绑定窗口」里刷新或重新绑定。"
            )
        self._config["bound_windows"] = bound_windows
        # 与编辑器一致：执行器需要显式 target_hwnd；仅传 bound_windows/标题不会写入句柄
        target_hwnd = 0
        target_title = ""
        for item in bound_windows:
            hwnd = as_hwnd(item.get("hwnd"))
            if hwnd and is_window_alive(hwnd):
                target_hwnd = hwnd
                target_title = str(item.get("title") or "").strip()
                break
        if not target_hwnd:
            raise RuntimeError(
                "已绑定窗口当前都不在线。请打开目标窗口后，在「绑定窗口」里刷新或重新绑定。"
            )
        from app_core.player.window_resolution import (
            assert_bound_windows_resolution,
            required_client_size,
        )

        required_width, required_height = required_client_size(
            package=self._package, config=self._config
        )
        assert_bound_windows_resolution(bound_windows, required_width, required_height)
        if len(bound_windows) == 1:
            self._config["target_window_title"] = target_title or bound_windows[0].get("title")
            self._config["window_binding_mode"] = "single"
        else:
            self._config["window_binding_mode"] = "multiple"
            if not self._config.get("target_window_title"):
                self._config["target_window_title"] = target_title or None

        payload = (
            workflow_data
            if isinstance(workflow_data, Mapping) and workflow_data
            else self._package.workflow_data
        )
        sid = str(script_id or "").strip()
        cards_data = cards_dict_from_workflow(payload)
        connections_data = connections_from_workflow(payload)
        start_card_ids, thread_labels = require_start_card_ids(cards_data)
        execution_mode = str(self._config.get("execution_mode") or "background_sendmessage").strip()
        from utils.window.virtual_desktop import should_block_execution_start

        block_message = should_block_execution_start(execution_mode, hwnds=[target_hwnd])
        if block_message:
            raise RuntimeError(block_message)
        screenshot_engine = str(self._config.get("screenshot_engine") or "wgc").strip().lower()
        workflow_filepath = self._resolve_workflow_path(sid)
        self.executor, self.executor_thread = create_coordinated_workflow_runtime(
            source=ExecutionSource.PLAYER,
            cards_data=cards_data,
            connections_data=connections_data,
            execution_mode=execution_mode,
            screenshot_engine=screenshot_engine,
            images_dir=self._package.assets_images_dir,
            workflow_id=f"player:{sid}" if sid else "player",
            workflow_filepath=workflow_filepath,
            prefer_memory_reference=str(workflow_filepath or "").startswith("memory://"),
            start_card_ids=start_card_ids,
            target_window_title=self._config.get("target_window_title") or target_title or None,
            target_hwnd=target_hwnd,
            thread_labels=thread_labels,
            bound_windows=bound_windows,
            custom_width=self._config.get("custom_width"),
            custom_height=self._config.get("custom_height"),
            parent=self._parent,
        )
        thread = self.executor_thread
        executor = self.executor
        if thread is None or executor is None:
            raise RuntimeError("未能创建播放器运行时")
        self.bind_signals(on_started=on_started, on_finished=on_finished, on_step_log=on_step_log)
        started = getattr(thread, "started", None)
        if started is not None and callable(getattr(started, "connect", None)):
            started.connect(executor.run)
        thread.start()
        logger.info(
            "独立程序已启动工作流: %s engine=%s mode=%s",
            sid or self._package.entry_workflow_path,
            screenshot_engine,
            execution_mode,
        )

    def stop(self, force: bool = True) -> None:
        executor = self.executor
        if executor is None:
            return
        request_stop = getattr(executor, "request_stop", None)
        if callable(request_stop):
            request_stop(force=force)
            return
        terminate = getattr(executor, "terminate", None)
        if callable(terminate):
            terminate()

    def toggle_pause(self) -> None:
        executor = self.executor
        if executor is None or not self.is_running():
            return
        if self.is_paused():
            resume = getattr(executor, "resume", None)
            if callable(resume):
                resume()
            return
        pause = getattr(executor, "pause", None)
        if callable(pause):
            pause()

    def bind_signals(
        self,
        *,
        on_started: Optional[Callable[[], Any]] = None,
        on_finished: Optional[Callable[[bool, str], Any]] = None,
        on_step_log: Optional[Callable[[str, str, bool], Any]] = None,
    ) -> None:
        executor = self.executor
        if executor is None:
            return
        if on_started is not None and hasattr(executor, "execution_started"):
            executor.execution_started.connect(on_started)
        if on_finished is not None and hasattr(executor, "execution_finished"):
            executor.execution_finished.connect(on_finished)
        if on_step_log is not None and hasattr(executor, "step_log"):
            executor.step_log.connect(on_step_log)

    def release(self) -> None:
        self.executor = None
        self.executor_thread = None
