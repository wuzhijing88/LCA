from .workflow_view_common import *


class WorkflowViewConnectionValidationMixin:
    """只校验连线登记状态；发现错误时报告，不扫描或自动修复。"""

    _STRICT_CONNECTION_TYPES = frozenset(("sequential", "success", "failure", "random"))

    def _validate_registered_connection(self, connection):
        if not isinstance(connection, ConnectionLine):
            raise TypeError("连接列表中存在非 ConnectionLine 对象")

        start_card = connection.start_item
        end_card = connection.end_item
        line_type = connection.line_type
        if start_card is None or end_card is None:
            raise ValueError("连接缺少起点或终点卡片")
        if line_type not in self._STRICT_CONNECTION_TYPES:
            raise ValueError(f"不支持的连线类型: {line_type!r}")
        if self.cards.get(start_card.card_id) is not start_card:
            raise ValueError(f"连线起点不属于当前工作流: {start_card.card_id!r}")
        if self.cards.get(end_card.card_id) is not end_card:
            raise ValueError(f"连线终点不属于当前工作流: {end_card.card_id!r}")
        if connection.scene() is not self.scene:
            raise ValueError("连接未挂载到当前场景")
        if start_card.scene() is not self.scene or end_card.scene() is not self.scene:
            raise ValueError("连接端点未挂载到当前场景")
        if not isinstance(start_card.connections, list) or not isinstance(end_card.connections, list):
            raise TypeError("卡片连接容器必须是列表")
        if start_card.connections.count(connection) != 1:
            raise ValueError("起点卡片的连接登记次数必须为 1")
        if end_card is not start_card and end_card.connections.count(connection) != 1:
            raise ValueError("终点卡片的连接登记次数必须为 1")
        return start_card, end_card, line_type

    def _connection_state_errors(self):
        """返回登记状态错误；只检查已登记对象，不检查场景未知对象。"""
        errors = []
        seen_objects = set()
        seen_keys = set()

        for index, connection in enumerate(self.connections):
            object_id = id(connection)
            if object_id in seen_objects:
                errors.append(f"视图连接列表第 {index + 1} 项重复登记同一对象")
                continue
            seen_objects.add(object_id)
            try:
                start_card, end_card, line_type = self._validate_registered_connection(connection)
            except (TypeError, ValueError, RuntimeError) as exc:
                errors.append(f"视图连接列表第 {index + 1} 项无效: {exc}")
                continue

            key = (start_card.card_id, end_card.card_id, line_type)
            if key in seen_keys:
                errors.append(f"存在重复连线: {start_card.card_id} -> {end_card.card_id} ({line_type})")
            seen_keys.add(key)

        registered_objects = set(self.connections)
        for card_id, card in self.cards.items():
            card_connections = getattr(card, "connections", None)
            if not isinstance(card_connections, list):
                errors.append(f"卡片 {card_id} 的连接容器不是列表")
                continue
            for connection in card_connections:
                if connection not in registered_objects:
                    errors.append(f"卡片 {card_id} 登记了视图连接列表中不存在的连接")

        return errors

    def _sync_connections_with_scene(self):
        """严格断言登记状态；名称保留给序列化/加载调用方，但不会同步或修复。"""
        errors = self._connection_state_errors()
        if errors:
            raise RuntimeError("；".join(errors))
        return True

    def validate_connections(self):
        """返回当前连线登记错误数量，不修改状态、不输出重复日志。"""
        return len(self._connection_state_errors())
