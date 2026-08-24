from ..parameter_panel_support import *


class ParameterPanelWorkflowSelectorPruneMixin:
    def _prune_obsolete_params_in_workflow(self, obsolete_params: list) -> None:
        if not obsolete_params or self.current_card_id is None:
            return

        current_workflow_view = None
        try:
            if self.main_window and hasattr(self.main_window, "workflow_tab_widget") and self.main_window.workflow_tab_widget:
                current_task_id = self.main_window.workflow_tab_widget.get_current_task_id()
                if current_task_id is not None and current_task_id in self.main_window.workflow_tab_widget.task_views:
                    current_workflow_view = self.main_window.workflow_tab_widget.task_views[current_task_id]
            if current_workflow_view is None and self.main_window and hasattr(self.main_window, "workflow_view"):
                current_workflow_view = self.main_window.workflow_view
        except Exception as exc:
            logger.debug(f"[废弃参数] 解析 workflow_view 失败：{exc}")
            return

        if not current_workflow_view or not hasattr(current_workflow_view, "cards"):
            return

        card = current_workflow_view.cards.get(self.current_card_id)
        if not card or not hasattr(card, "parameters"):
            return

        removed = []
        for name in obsolete_params:
            if name in card.parameters:
                removed.append(name)
                card.parameters.pop(name, None)

        if not removed:
            return

        try:
            card.parameters = card.parameters.copy()
        except Exception:
            pass
        try:
            card.update()
        except Exception:
            pass
        if self.main_window and hasattr(self.main_window, "_mark_unsaved_changes"):
            self.main_window._mark_unsaved_changes()
        logger.debug(f"[obsolete params] removed from workflow: {removed}")
