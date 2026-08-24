from ..parameter_panel_support import *


class ParameterPanelWorkflowSelectorContextMixin:
    def _get_active_workflow_view(self):
        """获取当前活动的 workflow_view。"""
        try:
            if self.main_window and hasattr(self.main_window, "workflow_tab_widget") and self.main_window.workflow_tab_widget:
                current_task_id = self.main_window.workflow_tab_widget.get_current_task_id()
                if (
                    current_task_id is not None
                    and current_task_id in self.main_window.workflow_tab_widget.task_views
                ):
                    return self.main_window.workflow_tab_widget.task_views[current_task_id]
            if self.main_window and hasattr(self.main_window, "workflow_view"):
                return self.main_window.workflow_view
        except Exception:
            pass
        return None

    @staticmethod
    def _sanitize_workflow_name_token(value: Optional[object], max_len: int = 64) -> str:
        """将工作流名称转换为可用于文件名的安全 token。"""
        raw = str(value or "").strip()
        if not raw:
            return ""

        invalid_chars = set('<>:"/\\|?*')
        chars = []
        for ch in raw:
            if ch in invalid_chars or ord(ch) < 32:
                chars.append("_")
            elif ch.isspace():
                chars.append("_")
            else:
                chars.append(ch)

        token = "".join(chars).strip("._ ")
        while "__" in token:
            token = token.replace("__", "_")
        return token[:max_len]

    def _extract_workflow_name_token_from_task(self, task_obj: Optional[object]) -> str:
        """优先从工作流文件名提取 token，失败时回退任务显示名。"""
        if task_obj is None:
            return ""

        try:
            filepath = str(getattr(task_obj, "filepath", "") or "").strip()
            if filepath:
                stem = os.path.splitext(os.path.basename(filepath))[0]
                token = self._sanitize_workflow_name_token(stem)
                if token:
                    return token
        except Exception:
            pass

        try:
            task_name = str(getattr(task_obj, "name", "") or "").strip()
            token = self._sanitize_workflow_name_token(task_name)
            if token:
                return token
        except Exception:
            pass

        return ""

    def _get_active_workflow_file_token(self) -> Optional[str]:
        """获取当前工作流名称标识，用于截图命名。"""
        tab_widget = None
        try:
            if self.main_window and hasattr(self.main_window, "workflow_tab_widget"):
                tab_widget = self.main_window.workflow_tab_widget
        except Exception:
            tab_widget = None

        if tab_widget:
            current_task_id = None
            try:
                current_task_id = tab_widget.get_current_task_id()
            except Exception:
                current_task_id = None

            if current_task_id is not None:
                try:
                    task_manager = getattr(tab_widget, "task_manager", None)
                    task_obj = task_manager.get_task(current_task_id) if task_manager else None
                except Exception:
                    task_obj = None

                token = self._extract_workflow_name_token_from_task(task_obj)
                if token:
                    return token

                try:
                    if hasattr(tab_widget, "_get_current_workflow_filepath"):
                        workflow_path = tab_widget._get_current_workflow_filepath()
                        path_token = self._sanitize_workflow_name_token(
                            os.path.splitext(os.path.basename(str(workflow_path or "").strip()))[0]
                        )
                        if path_token:
                            return path_token
                except Exception:
                    pass

                fallback_token = self._sanitize_workflow_name_token(f"workflow_{int(current_task_id)}")
                if fallback_token:
                    return fallback_token

        workflow_view = self._get_active_workflow_view()
        if workflow_view is None:
            return None

        try:
            fallback_task_id = getattr(workflow_view, "task_id", None)
            if fallback_task_id is None:
                return None
            return self._sanitize_workflow_name_token(f"workflow_{int(fallback_task_id)}") or None
        except Exception:
            return None
