from .workflow_view_common import *

class WorkflowViewIoMixin:

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
            card.open_parameter_panel()
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

    @staticmethod
    def _require_finite_number(value, field_name: str):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise TypeError(f"{field_name} 必须是有限数字")
        return value

    def serialize_workflow(self) -> Dict[str, Any]:
        """按当前格式生成一份与界面运行状态隔离的工作流数据。"""
        if not isinstance(self.cards, dict):
            raise TypeError("工作流卡片容器必须是字典")
        if not isinstance(self.connections, list):
            raise TypeError("工作流连接容器必须是列表")
        if not isinstance(self.workflow_metadata, dict):
            raise TypeError("工作流 metadata 必须是字典")

        self._sync_connections_with_scene()
        self._validate_card_references()

        for card_id in self.cards:
            if isinstance(card_id, bool) or not isinstance(card_id, int) or card_id < 0:
                raise TypeError("卡片字典键必须是非负整数")

        cards = []
        for card_id in sorted(self.cards):
            card = self.cards[card_id]
            if not isinstance(card, TaskCard):
                raise TypeError(f"卡片 {card_id} 不是 TaskCard 对象")
            if card.card_id != card_id:
                raise ValueError(f"卡片字典键 {card_id} 与卡片 ID {card.card_id!r} 不一致")
            if card.scene() is not self.scene:
                raise ValueError(f"卡片 {card_id} 未挂载到当前场景")
            if not isinstance(card.task_type, str) or not card.task_type.strip():
                raise TypeError(f"卡片 {card_id} 的 task_type 必须是非空字符串")
            if not isinstance(card.parameters, dict):
                raise TypeError(f"卡片 {card_id} 的 parameters 必须是字典")
            if card.custom_name is not None and not isinstance(card.custom_name, str):
                raise TypeError(f"卡片 {card_id} 的 custom_name 必须是字符串或 None")

            pos_x = self._require_finite_number(card.x(), f"卡片 {card_id} 的 pos_x")
            pos_y = self._require_finite_number(card.y(), f"卡片 {card_id} 的 pos_y")
            try:
                from task_workflow.workflow_sanitize import sanitize_card_parameters

                parameters = sanitize_card_parameters(
                    copy.deepcopy(card.parameters),
                    card.task_type,
                )
            except Exception as exc:
                raise TypeError(f"卡片 {card_id} 的 parameters 无法复制: {exc}") from exc

            cards.append({
                "id": card_id,
                "task_type": card.task_type,
                "pos_x": pos_x,
                "pos_y": pos_y,
                "parameters": parameters,
                "custom_name": card.custom_name,
            })

        for item in self.scene.items():
            if isinstance(item, TaskCard) and self.cards.get(item.card_id) is not item:
                raise ValueError(f"场景中存在未登记卡片: {item.card_id!r}")
            if isinstance(item, ConnectionLine) and item not in self.connections:
                raise ValueError("场景中存在未登记连接")

        connections = []
        for connection in self.connections:
            start_card, end_card, line_type = self._validate_registered_connection(connection)
            connections.append({
                "start_card_id": start_card.card_id,
                "end_card_id": end_card.card_id,
                "type": line_type,
            })
        connections.sort(key=lambda item: (
            item["start_card_id"],
            item["end_card_id"],
            item["type"],
        ))

        transform = self.transform()
        view_transform = [
            transform.m11(), transform.m12(), transform.m13(),
            transform.m21(), transform.m22(), transform.m23(),
            transform.m31(), transform.m32(), transform.m33(),
        ]
        for index, value in enumerate(view_transform):
            self._require_finite_number(value, f"view_transform 第 {index + 1} 项")

        viewport_center = self.viewport().rect().center()
        scene_center = self.mapToScene(viewport_center)
        view_center = [scene_center.x(), scene_center.y()]
        for index, value in enumerate(view_center):
            self._require_finite_number(value, f"view_center 第 {index + 1} 项")

        try:
            metadata = copy.deepcopy(self.workflow_metadata)
        except Exception as exc:
            raise TypeError(f"工作流 metadata 无法复制: {exc}") from exc

        workflow_data = {
            "cards": cards,
            "connections": connections,
            "view_transform": view_transform,
            "metadata": metadata,
            "view_center": view_center,
        }
        try:
            json.dumps(workflow_data, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"工作流包含无法保存为 JSON 的数据: {exc}") from exc
        return workflow_data

    def load_workflow(self, workflow_data: Dict[str, Any]):
        """严格加载当前工作流数据格式。"""
        self._loading_workflow = True
        try:
            return self._load_current_workflow(workflow_data)
        finally:
            self._loading_workflow = False

    @staticmethod
    def _validate_current_workflow_data(workflow_data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(workflow_data, dict):
            raise TypeError("工作流数据必须是字典")

        if 'workflow' in workflow_data and 'cards' not in workflow_data:
            actual_workflow = workflow_data['workflow']
        else:
            actual_workflow = workflow_data
        if not isinstance(actual_workflow, dict):
            raise TypeError("工作流主体必须是字典")

        cards = actual_workflow.get('cards')
        connections = actual_workflow.get('connections')
        if not isinstance(cards, list):
            raise TypeError("工作流 cards 必须是列表")
        if not isinstance(connections, list):
            raise TypeError("工作流 connections 必须是列表")

        card_ids = set()
        required_card_fields = {'id', 'task_type', 'pos_x', 'pos_y', 'parameters'}
        for index, card_data in enumerate(cards):
            if not isinstance(card_data, dict):
                raise TypeError(f"第 {index + 1} 张卡片必须是字典")
            missing_fields = required_card_fields.difference(card_data)
            if missing_fields:
                raise ValueError(f"第 {index + 1} 张卡片缺少字段: {sorted(missing_fields)}")
            card_id = card_data['id']
            if isinstance(card_id, bool) or not isinstance(card_id, int) or card_id < 0:
                raise TypeError(f"第 {index + 1} 张卡片 ID 必须是非负整数")
            if card_id in card_ids:
                raise ValueError(f"工作流存在重复卡片 ID: {card_id}")
            card_ids.add(card_id)
            task_type = card_data['task_type']
            if not isinstance(task_type, str) or not task_type.strip():
                raise TypeError(f"卡片 {card_id} 的 task_type 必须是非空字符串")
            for coordinate_name in ('pos_x', 'pos_y'):
                coordinate = card_data[coordinate_name]
                if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)) or not math.isfinite(coordinate):
                    raise TypeError(f"卡片 {card_id} 的 {coordinate_name} 必须是有限数字")
            if not isinstance(card_data['parameters'], dict):
                raise TypeError(f"卡片 {card_id} 的 parameters 必须是字典")
            custom_name = card_data.get('custom_name')
            if custom_name is not None and not isinstance(custom_name, str):
                raise TypeError(f"卡片 {card_id} 的 custom_name 必须是字符串或 None")

        valid_line_types = {'sequential', 'success', 'failure', 'random'}
        connection_keys = set()
        for index, connection_data in enumerate(connections):
            if not isinstance(connection_data, dict):
                raise TypeError(f"第 {index + 1} 条连线必须是字典")
            required_fields = {'start_card_id', 'end_card_id', 'type'}
            missing_fields = required_fields.difference(connection_data)
            if missing_fields:
                raise ValueError(f"第 {index + 1} 条连线缺少字段: {sorted(missing_fields)}")
            start_id = connection_data['start_card_id']
            end_id = connection_data['end_card_id']
            line_type = connection_data['type']
            if isinstance(start_id, bool) or not isinstance(start_id, int):
                raise TypeError(f"第 {index + 1} 条连线的 start_card_id 必须是整数")
            if isinstance(end_id, bool) or not isinstance(end_id, int):
                raise TypeError(f"第 {index + 1} 条连线的 end_card_id 必须是整数")
            if start_id not in card_ids or end_id not in card_ids:
                raise ValueError(f"第 {index + 1} 条连线指向不存在的卡片: {start_id} -> {end_id}")
            if line_type not in valid_line_types:
                raise ValueError(f"第 {index + 1} 条连线类型无效: {line_type!r}")
            connection_key = (start_id, end_id, line_type)
            if connection_key in connection_keys:
                raise ValueError(f"工作流存在重复连线: {start_id} -> {end_id} ({line_type})")
            connection_keys.add(connection_key)
        return actual_workflow

    def _load_current_workflow(self, workflow_data: Dict[str, Any]):
        actual_workflow = self._validate_current_workflow_data(workflow_data)
        logger.info("[工作流加载] 开始")

        metadata = actual_workflow.get("metadata", {})
        if not isinstance(metadata, dict):
            raise TypeError("工作流 metadata 必须是字典")
        self.workflow_metadata = copy.deepcopy(metadata)

        from task_workflow.workflow_sanitize import sanitize_card_parameters

        self.clear_workflow()
        dropped_card_ids = set()
        for card_data in actual_workflow['cards']:
            task_type = str(card_data['task_type'] or "").strip()
            if self.task_modules.get(task_type) is None:
                logger.warning("[工作流加载] 已清除未知卡片: ID=%s, 类型=%s", card_data['id'], task_type)
                dropped_card_ids.add(card_data['id'])
                continue
            card = self.add_task_card(
                x=card_data['pos_x'],
                y=card_data['pos_y'],
                task_type=task_type,
                card_id=card_data['id'],
            )
            if card is None:
                raise RuntimeError(f"卡片创建失败: {card_data['id']}")
            card.parameters.update(
                sanitize_card_parameters(copy.deepcopy(card_data['parameters']), task_type)
            )
            custom_name = card_data.get('custom_name')
            if custom_name:
                card.set_custom_name(custom_name.strip())

        if dropped_card_ids:
            self._clear_dropped_card_references(dropped_card_ids)

        self._update_card_render_cache_policy()

        for connection_data in actual_workflow['connections']:
            start_id = connection_data['start_card_id']
            end_id = connection_data['end_card_id']
            if start_id not in self.cards or end_id not in self.cards:
                logger.warning("[工作流加载] 已清除无效连线: %s -> %s", start_id, end_id)
                continue
            restored_connection = self.add_connection(
                self.cards[start_id],
                self.cards[end_id],
                connection_data['type'],
                skip_duplicate_check=True,
            )
            if restored_connection is None:
                raise RuntimeError(
                    f"连线创建失败: {start_id} -> {end_id} ({connection_data['type']})"
                )

        self._validate_card_references()
        self.update_card_sequence_display()
        self._refresh_thread_start_custom_names()
        self._sync_connections_with_scene()

        if self.scene.items():
            items_rect = self.scene.itemsBoundingRect()
            self.scene.setSceneRect(
                items_rect.adjusted(
                    -FIT_VIEW_PADDING * 2,
                    -FIT_VIEW_PADDING * 2,
                    FIT_VIEW_PADDING * 2,
                    FIT_VIEW_PADDING * 2,
                )
            )

        view_transform_data = actual_workflow.get('view_transform')
        view_center_data = actual_workflow.get('view_center')
        if view_transform_data is not None:
            if not isinstance(view_transform_data, list) or len(view_transform_data) != 9:
                raise TypeError("工作流 view_transform 必须是包含 9 个数字的列表")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in view_transform_data
            ):
                raise TypeError("工作流 view_transform 必须是包含 9 个有限数字的列表")
            saved_transform = QTransform(
                view_transform_data[0], view_transform_data[1], view_transform_data[2],
                view_transform_data[3], view_transform_data[4], view_transform_data[5],
                view_transform_data[6], view_transform_data[7], view_transform_data[8],
            )
            self.setTransform(saved_transform)
            self._notify_zoom_level_changed()

        if view_center_data is not None:
            if not isinstance(view_center_data, list) or len(view_center_data) != 2:
                raise TypeError("工作流 view_center 必须是包含 2 个数字的列表")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in view_center_data
            ):
                raise TypeError("工作流 view_center 必须是包含 2 个有限数字的列表")
            saved_center_point = QPointF(view_center_data[0], view_center_data[1])
            QTimer.singleShot(100, lambda point=saved_center_point: self._deferred_center_view(point))

        logger.info("[工作流加载] 完成，卡片数量=%s，连线数量=%s", len(self.cards), len(self.connections))

    def _clear_dropped_card_references(self, dropped_card_ids: set) -> None:
        for card in self.cards.values():
            for parameter_name in self._reference_parameter_names(card):
                if card.parameters.get(parameter_name) in dropped_card_ids:
                    card.parameters[parameter_name] = None
            random_weights = card.parameters.get("random_weights")
            if isinstance(random_weights, dict):
                card.parameters["random_weights"] = {
                    target_id: weight
                    for target_id, weight in random_weights.items()
                    if not (isinstance(target_id, str) and target_id.isdigit() and int(target_id) in dropped_card_ids)
                }
            random_connections = card.parameters.get("_random_connections")
            if isinstance(random_connections, list):
                card.parameters["_random_connections"] = [
                    item
                    for item in random_connections
                    if not (isinstance(item, dict) and item.get("card_id") in dropped_card_ids)
                ]
