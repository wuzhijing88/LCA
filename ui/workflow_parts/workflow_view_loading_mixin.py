from .workflow_view_common import *


class WorkflowViewLoadingMixin:

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
        for card_data in actual_workflow['cards']:
            card = self.add_task_card(
                x=card_data['pos_x'],
                y=card_data['pos_y'],
                task_type=card_data['task_type'],
                card_id=card_data['id'],
            )
            if card is None:
                raise RuntimeError(f"卡片创建失败: {card_data['id']}")
            card.parameters.update(sanitize_card_parameters(copy.deepcopy(card_data['parameters'])))
            custom_name = card_data.get('custom_name')
            if custom_name:
                card.set_custom_name(custom_name.strip())

        self._update_card_render_cache_policy()

        for connection_data in actual_workflow['connections']:
            start_id = connection_data['start_card_id']
            end_id = connection_data['end_card_id']
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
