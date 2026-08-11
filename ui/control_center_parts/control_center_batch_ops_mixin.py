from ..control_center_parts.control_center_pause_all_orchestrator import control_center_toggle_pause_all_tasks
from ..control_center_parts.control_center_start_all_orchestrator import control_center_start_all_tasks
from ..control_center_parts.control_center_stop_all_orchestrator import control_center_stop_all_tasks


class ControlCenterBatchOpsMixin:
    def _resolve_batch_window_ids(self, window_ids=None):
        if window_ids is not None:
            normalized_ids = self._normalize_window_id_list(window_ids)
            if normalized_ids:
                return normalized_ids, f"指定窗口 {len(normalized_ids)} 个"
            if isinstance(window_ids, (list, tuple, set)) and len(window_ids) == 0:
                return [], "全部窗口"
            return None, "无有效窗口"

        selected_ids = self._get_selected_window_ids()
        if selected_ids:
            return selected_ids, f"已选窗口 {len(selected_ids)} 个"
        return [], "全部窗口"

    def start_all_tasks(self, window_ids=None):
        """Start workflows for all or selected windows."""
        resolved_ids, scope_desc = self._resolve_batch_window_ids(window_ids)
        if resolved_ids is None:
            self.log_message(f"批量启动已取消：{scope_desc}")
            return False

        active_filter = set(resolved_ids) if resolved_ids else None
        self._cc_active_start_window_filter = active_filter
        self.log_message(f"批量启动：{scope_desc}")
        try:
            result = control_center_start_all_tasks(self)
        finally:
            self._cc_active_start_window_filter = None
        return result

    def stop_all_tasks(self, window_ids=None):
        """Stop workflows for all or selected windows."""
        resolved_ids, scope_desc = self._resolve_batch_window_ids(window_ids)
        if resolved_ids is None:
            self.log_message(f"批量停止已取消：{scope_desc}")
            return False

        self._release_timed_pause_targets(resolved_ids)

        self._clear_random_pause_runtime(
            resume=False,
            target_window_ids=resolved_ids,
        )

        active_filter = set(resolved_ids) if resolved_ids else None
        self._cc_active_stop_window_filter = active_filter
        self.log_message(f"批量停止：{scope_desc}")
        try:
            return control_center_stop_all_tasks(self)
        finally:
            self._cc_active_stop_window_filter = None

    def toggle_pause_all_tasks(self, window_ids=None):
        """Pause or resume workflows for all or selected windows."""
        resolved_ids, scope_desc = self._resolve_batch_window_ids(window_ids)
        if resolved_ids is None:
            self.log_message(f"批量暂停/恢复已取消：{scope_desc}")
            return False

        self._release_timed_pause_targets(resolved_ids)

        active_filter = set(resolved_ids) if resolved_ids else None
        self._cc_active_pause_window_filter = active_filter
        self.log_message(f"批量暂停/恢复：{scope_desc}")
        try:
            result = control_center_toggle_pause_all_tasks(self)
        finally:
            self._cc_active_pause_window_filter = None

        self._clear_random_pause_runtime(
            resume=False,
            reason="手动暂停/恢复已接管",
            target_window_ids=resolved_ids,
        )
        self._sync_pause_all_button_text()
        return result

