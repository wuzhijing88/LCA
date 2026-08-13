from .workflow_view_common import *


class WorkflowViewSerializationMixin:

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
                parameters = copy.deepcopy(card.parameters)
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
