class MainWindowWorkflowSwitchTabsMixin:
    def _on_current_workflow_changed(self, task_id: int):
        """切换画布到当前工作流标签。"""
        old_view = self.workflow_view
        if not self._is_qobject_alive(old_view):
            old_view = None
            self.workflow_view = None

        current_view = None
        if getattr(self, "workflow_tab_widget", None):
            current_view = self.workflow_tab_widget.get_current_workflow_view()
        self.workflow_view = current_view if self._is_qobject_alive(current_view) else None

        self._finish_current_workflow_view_switch(old_view)

    def _finish_current_workflow_view_switch(self, old_view):
        if self.workflow_view is None:
            return
        if old_view is not None and old_view is not self.workflow_view:
            self._disconnect_workflow_selection_signal(old_view)
        self.workflow_view.setEnabled(True)
        self.workflow_view.setVisible(True)

        from PySide6.QtWidgets import QGraphicsView
        self.workflow_view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        if self.workflow_view.scene.items():
            items_rect = self.workflow_view.scene.itemsBoundingRect()
            self.workflow_view.scene.setSceneRect(items_rect.adjusted(-500, -500, 500, 500))
            self.workflow_view.viewport().update()
        try:
            self.workflow_view.scene.selectionChanged.connect(self.update_status_bar_for_selection)
        except (TypeError, RuntimeError):
            pass
        # 新增卡片必须接上参数面板信号，否则双击卡片无法打开参数界面
        if not self.workflow_view.property("_mw_card_added_connected"):
            self.workflow_view.card_added.connect(self._on_card_added)
            self.workflow_view.setProperty("_mw_card_added_connected", True)
        self._connect_parameter_panel_signals()

    def _disconnect_workflow_selection_signal(self, workflow_view) -> None:
        if not self._is_qobject_alive(workflow_view):
            return
        try:
            scene = workflow_view.scene
            if callable(scene):
                scene = scene()
            if self._is_qobject_alive(scene):
                scene.selectionChanged.disconnect(self.update_status_bar_for_selection)
        except (TypeError, RuntimeError):
            pass
        if workflow_view.property("_mw_card_added_connected"):
            try:
                workflow_view.card_added.disconnect(self._on_card_added)
            except (TypeError, RuntimeError):
                pass
            workflow_view.setProperty("_mw_card_added_connected", False)

    def _show_welcome_hint(self):
        if self.task_manager.get_task_count() == 0:
            self.step_detail_label.setText("")

    def _is_qobject_alive(self, obj) -> bool:
        if obj is None:
            return False
        try:
            from shiboken6 import isValid
            return bool(isValid(obj))
        except ImportError:
            try:
                obj.metaObject()
                return True
            except RuntimeError:
                return False

    def _on_task_count_changed(self, task_id: int = None):
        if self.task_manager.get_task_count() == 0 and self.workflow_view is not None:
            self._disconnect_workflow_selection_signal(self.workflow_view)
            self.workflow_view = None
        if getattr(self, "executor", None) is None:
            self._update_status_bar()
