from .workflow_view_common import *


class WorkflowViewContextMenuMixin:

    @staticmethod
    def _set_edit_action_state(action, editing_blocked: bool, tooltip: str) -> None:
        action.setEnabled(not editing_blocked)
        if editing_blocked:
            action.setToolTip(tooltip)

    def show_context_menu(self, pos: QPointF):
        """显示卡片、连线或画布的统一右键菜单。"""
        scene_pos = self.mapToScene(pos)
        item = self.itemAt(pos)
        editing_blocked = not self.editing_enabled or self._is_workflow_running()

        menu = apply_unified_menu_style(QMenu(self), frameless=True)
        selected_cards = sorted(
            (
                selected_item
                for selected_item in self.scene.selectedItems()
                if isinstance(selected_item, TaskCard)
            ),
            key=lambda card: card.card_id,
        )

        if isinstance(item, TaskCard):
            if item in selected_cards and len(selected_cards) > 1:
                self._show_selected_cards_menu(menu, pos, selected_cards, editing_blocked)
            else:
                self._show_card_menu(menu, pos, item, editing_blocked)
            return

        if isinstance(item, ConnectionLine):
            self._show_connection_menu(menu, pos, item, editing_blocked)
            return

        if item is None:
            self._show_canvas_menu(menu, pos, scene_pos, editing_blocked)

    def _show_selected_cards_menu(self, menu, pos, selected_cards, editing_blocked: bool) -> None:
        copy_action = menu.addAction(f"复制选中卡片 ({len(selected_cards)}个)")
        self._set_edit_action_state(
            copy_action,
            editing_blocked,
            "工作流运行期间无法复制卡片",
        )
        menu.addSeparator()
        delete_action = menu.addAction(f"删除选中卡片 ({len(selected_cards)}个)")
        self._set_edit_action_state(
            delete_action,
            editing_blocked,
            "工作流运行期间无法删除卡片",
        )

        selected_action = menu.exec(self.mapToGlobal(pos))
        if selected_action == copy_action:
            self.handle_copy_selected_cards()
        elif selected_action == delete_action:
            self._delete_selected_cards(selected_cards)

    def _show_card_menu(self, menu, pos, card, editing_blocked: bool) -> None:
        settings_action = menu.addAction("参数设置")
        self._set_edit_action_state(settings_action, editing_blocked, "工作流运行期间无法修改参数")

        menu.addSeparator()
        rename_action = menu.addAction("备注卡片名称")
        self._set_edit_action_state(rename_action, editing_blocked, "工作流运行期间无法修改备注")
        change_id_action = menu.addAction("修改卡片ID")
        self._set_edit_action_state(change_id_action, editing_blocked, "工作流运行期间无法修改ID")

        menu.addSeparator()
        copy_action = menu.addAction("复制卡片")
        self._set_edit_action_state(copy_action, editing_blocked, "工作流运行期间无法复制卡片")

        menu.addSeparator()
        test_card_action = menu.addAction("测试卡片")
        self._set_edit_action_state(test_card_action, editing_blocked, "工作流运行期间无法测试卡片")
        test_flow_action = menu.addAction("测试流程")
        self._set_edit_action_state(test_flow_action, editing_blocked, "工作流运行期间无法测试流程")

        menu.addSeparator()
        delete_action = menu.addAction("删除卡片")
        self._set_edit_action_state(delete_action, editing_blocked, "工作流运行期间无法删除卡片")

        selected_action = menu.exec(self.mapToGlobal(pos))
        if selected_action == settings_action:
            card.open_parameter_dialog()
        elif selected_action == rename_action:
            self.handle_rename_card(card)
        elif selected_action == change_id_action:
            self.handle_change_card_id(card)
        elif selected_action == copy_action:
            self.handle_copy_card(card.card_id, card.parameters)
        elif selected_action == test_card_action:
            self._handle_test_card(card.card_id)
        elif selected_action == test_flow_action:
            self._handle_test_flow(card.card_id)
        elif selected_action == delete_action:
            self.delete_card(card.card_id)

    def _show_connection_menu(self, menu, pos, connection, editing_blocked: bool) -> None:
        delete_action = menu.addAction("删除连接")
        self._set_edit_action_state(delete_action, editing_blocked, "工作流运行期间无法删除连接")
        if menu.exec(self.mapToGlobal(pos)) == delete_action:
            self.remove_connection(connection)

    def _show_canvas_menu(self, menu, pos, scene_pos, editing_blocked: bool) -> None:
        add_action = menu.addAction("添加步骤")
        self._set_edit_action_state(add_action, editing_blocked, "工作流运行期间无法添加步骤")

        paste_action = menu.addAction("粘贴卡片")
        paste_available = self.is_paste_available()
        paste_action.setEnabled(paste_available and not editing_blocked)
        if editing_blocked:
            paste_action.setToolTip("工作流运行期间无法粘贴卡片")
        elif not paste_available:
            paste_action.setToolTip("剪贴板中没有可粘贴的卡片数据")

        undo_action = menu.addAction("撤销 (Ctrl+Z)")
        undo_available = bool(self.undo_stack)
        undo_action.setEnabled(undo_available and not editing_blocked)
        if editing_blocked:
            undo_action.setToolTip("工作流运行期间无法撤销")
        elif not undo_available:
            undo_action.setToolTip("没有可撤销的操作")

        menu.addSeparator()
        save_action = menu.addAction("保存工作流")
        menu.addSeparator()
        fit_action = menu.addAction("适应视图")

        selected_action = menu.exec(self.mapToGlobal(pos))
        if selected_action == add_action:
            self.prompt_and_add_card_at(scene_pos)
        elif selected_action == paste_action:
            self.handle_paste_card(scene_pos)
        elif selected_action == undo_action:
            self.undo_last_operation()
        elif selected_action == save_action:
            main_window = self.main_window
            if main_window is None or not callable(getattr(main_window, "_handle_save_action", None)):
                raise RuntimeError("右键保存未绑定主窗口保存入口")
            main_window._handle_save_action()
        elif selected_action == fit_action:
            self.fit_view_to_items()

    def prompt_and_add_card_at(self, scene_pos: QPointF):
        """选择任务类型并在指定场景位置新增卡片。"""
        from tasks import get_available_tasks

        task_types = get_available_tasks()
        if not isinstance(task_types, list):
            raise TypeError("可用任务类型必须是列表")
        if not task_types:
            QMessageBox.warning(self, "无法添加", "当前没有可用的任务类型")
            return
        if any(not isinstance(task_type, str) or not task_type.strip() for task_type in task_types):
            raise TypeError("可用任务类型必须全部是非空字符串")

        dialog = SelectTaskDialog(task_types, self)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            task_type = dialog.selected_task_type()
            if task_type not in task_types:
                raise ValueError("任务选择结果不属于当前可用任务类型")

            new_card = self.add_task_card(scene_pos.x(), scene_pos.y(), task_type=task_type)
            if new_card is None:
                raise RuntimeError(f"新增卡片失败: {task_type}")
            self.update_card_sequence_display()
        finally:
            dialog.deleteLater()
