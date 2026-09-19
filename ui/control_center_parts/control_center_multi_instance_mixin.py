# -*- coding: utf-8 -*-
import logging
from typing import Any, Dict, List

from utils.window.hwnd_utils import as_hwnd
from utils.window.multi_instance import MutexOccupancy
from utils.window.window_identity import apply_window_identity

logger = logging.getLogger(__name__)


class ControlCenterMultiInstanceMixin:
    def open_multi_instance_dialog(self):
        from ui.dialogs.multi_instance_dialog import MultiInstanceDialog

        holder = getattr(self, "_multi_instance_mutex_holder", None)
        if holder is None:
            holder = MutexOccupancy()
            self._multi_instance_mutex_holder = holder
        dialog = MultiInstanceDialog(parent=self, occupancy=holder)
        dialog.instances_ready.connect(self._add_multi_instance_windows)
        dialog.exec()

    def _add_multi_instance_windows(self, windows: List[Dict[str, Any]]) -> None:
        if not isinstance(windows, list) or not windows:
            return
        bound = self.bound_windows
        if not isinstance(bound, list):
            self.bound_windows = []
            bound = self.bound_windows
        existing = {as_hwnd(item.get("hwnd")) for item in bound if isinstance(item, dict)}
        added = 0
        for item in windows:
            if not isinstance(item, dict):
                continue
            hwnd = as_hwnd(item.get("hwnd"))
            if not hwnd or hwnd in existing:
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                title = str(item.get("class_name") or "").strip() or "未命名窗口"
            window_info = {"title": title, "enabled": True}
            apply_window_identity(window_info, hwnd)
            bound.append(window_info)
            existing.add(hwnd)
            added += 1
        if added <= 0:
            return
        parent = getattr(self, "parent_window", None)
        if parent is not None and hasattr(parent, "window_binding_mode"):
            parent.window_binding_mode = "multiple" if len(bound) > 1 else "single"
            if hasattr(parent, "_update_main_window_title"):
                try:
                    parent._update_main_window_title()
                except Exception:
                    logger.debug("多开后更新主窗口标题失败", exc_info=True)
        self.populate_window_table()
        persist = getattr(self, "_persist_bound_window_identities", None)
        if callable(persist):
            persist()
        logger.info("多开器已加入中控 %s 个窗口", added)
        log_message = getattr(self, "log_message", None)
        if callable(log_message):
            log_message(f"多开器已加入 {added} 个窗口")
