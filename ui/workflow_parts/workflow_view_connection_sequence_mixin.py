from .workflow_view_common import *


class WorkflowViewConnectionSequenceMixin:

    def update_card_sequence_display(self):
        """根据已登记的顺序连线，为所有线程分支分配显示序号。"""
        if self._updating_sequence:
            raise RuntimeError("卡片序列正在更新，拒绝重复进入")
        if not isinstance(self.cards, dict):
            raise TypeError("卡片容器必须是字典")
        if not isinstance(self.connections, list):
            raise TypeError("连线容器必须是列表")

        self._updating_sequence = True
        try:
            invalid_count = self.validate_connections()
            if invalid_count:
                raise RuntimeError(f"连线状态存在 {invalid_count} 项错误，拒绝更新卡片序列")

            card_map = dict(self.cards)
            adjacency = {card_id: [] for card_id in card_map}
            for card_id, card in card_map.items():
                if not isinstance(card, TaskCard):
                    raise TypeError(f"卡片 {card_id} 不是 TaskCard")
                if card.card_id != card_id:
                    raise RuntimeError(f"卡片字典键与卡片 ID 不一致: key={card_id}, card_id={card.card_id}")
                if card.scene() is not self.scene:
                    raise RuntimeError(f"卡片 {card_id} 不属于当前工作流场景")
                card.set_display_id(None)

            for connection in self.connections:
                if not isinstance(connection, ConnectionLine):
                    raise TypeError("连接列表中存在非 ConnectionLine 对象")
                if connection.line_type != "sequential":
                    continue
                start_card = connection.start_item
                end_card = connection.end_item
                if card_map.get(start_card.card_id) is not start_card:
                    raise RuntimeError("顺序连线起点未登记")
                if card_map.get(end_card.card_id) is not end_card:
                    raise RuntimeError("顺序连线终点未登记")
                adjacency[start_card.card_id].append(end_card)

            start_cards = sorted(
                (card for card in card_map.values() if self._is_start_task_type(card.task_type)),
                key=lambda card: card.card_id,
            )
            queue = collections.deque(start_cards)
            visited = set()
            sequence_id = 0
            while queue:
                card = queue.popleft()
                if card.card_id in visited:
                    continue
                visited.add(card.card_id)
                card.set_display_id(sequence_id)
                sequence_id += 1
                for next_card in sorted(adjacency[card.card_id], key=lambda item: item.card_id):
                    if next_card.card_id not in visited:
                        queue.append(next_card)
            return len(visited)

        finally:
            self._updating_sequence = False

    def cleanup_all_duplicate_connections(self):
        """校验重复输出连接；禁止自动选择并删除其中一条。"""
        port_connections = {}
        for connection in self.connections:
            if not isinstance(connection, ConnectionLine):
                raise TypeError("连接列表中存在非 ConnectionLine 对象")
            if connection.start_item is None:
                raise ValueError("连接缺少起点卡片")
            if connection.line_type == 'random':
                continue
            key = (connection.start_item.card_id, connection.line_type)
            port_connections.setdefault(key, []).append(connection)
        for (card_id, line_type), connections in port_connections.items():
            if len(connections) > 1:
                raise RuntimeError(
                    f"卡片 {card_id} 的 {line_type} 输出端存在 {len(connections)} 条连接；拒绝自动清理"
                )
        return 0

    def update_single_card_jump_connections(self, card_id: int):
        """
        更新单个卡片的跳转连线，避免每次参数变更都触发全量重建。
        这用于修改单个卡片的跳转参数时，避免 O(n) 的全量重建
        """
        card = self.cards.get(card_id)
        if not card:
            return

        # 1. 删除该卡片现有的跳转连线（success/failure 输出）
        connections_to_remove = []
        for conn in list(self.connections):
            if isinstance(conn, ConnectionLine) and conn.start_item == card:
                if conn.line_type in ['success', 'failure']:
                    connections_to_remove.append(conn)

        for conn in connections_to_remove:
            self._unmount_connection(conn)

        # 2. 根据参数重建该卡片的跳转连线
        source_restricted = getattr(card, 'restricted_outputs', False)
        if source_restricted:
            return  # 端口被限制，不创建连线

        # 注释已清理（原注释编码损坏）
        on_success = card.parameters.get('on_success')
        success_target_id = card.parameters.get('success_jump_target_id')
        if on_success == '跳转到步骤' and success_target_id is not None:
            target_card = self.cards.get(success_target_id)
            if target_card:
                self.add_connection(card, target_card, ConnectionType.SUCCESS.value)

        # 注释已清理（原注释编码损坏）
        on_failure = card.parameters.get('on_failure')
        failure_target_id = card.parameters.get('failure_jump_target_id')
        if on_failure == '跳转到步骤' and failure_target_id is not None:
            target_card = self.cards.get(failure_target_id)
            if target_card:
                self.add_connection(card, target_card, ConnectionType.FAILURE.value)
