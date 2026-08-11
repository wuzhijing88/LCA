from .workflow_view_common import *


class WorkflowViewConnectionSequenceMixin:

    def update_card_sequence_display(self, skip_jump_rebuild: bool = False):
        """Calculates the sequence order based on blue connections using BFS,
           updates card sequence IDs, and redraws jump connections based on sequence IDs.

        Args:
            skip_jump_rebuild: 如果为True，跳过跳转连线的删除和重建步骤（用于批量操作时的性能优化）
        """
        # 注释已清理（原注释编码损坏）
        _debug_enabled = logger.isEnabledFor(logging.DEBUG)
        if _debug_enabled:
            logger.debug("--- [DEBUG] START update_card_sequence_display --- ")

        # 设置更新序列标志，防止连接重建时保存撤销状态
        self._updating_sequence = True
        debug_print(f"  [UNDO] Set updating sequence flag to True")

        # <<< ENHANCED: 序列更新前验证连接状态 >>>
        # 【性能优化】加载工作流时跳过验证连接（数据已经验证过）
        if not skip_jump_rebuild and not getattr(self, '_loading_workflow', False):
            if _debug_enabled:
                logger.debug("验证连接状态（序列更新前）...")
            invalid_count = self.validate_connections()
            if invalid_count > 0:
                logger.info(f"序列更新前清理了 {invalid_count} 个无效连接")
        # <<< END ENHANCED >>>
        
        if not self.cards:
            if _debug_enabled:
                logger.debug("  [DEBUG] No cards to update.")
            # 清除更新序列标志
            self._updating_sequence = False
            debug_print(f"  [UNDO] Cleared updating sequence flag (no cards)")
            if _debug_enabled:
                logger.debug("--- [DEBUG] END update_card_sequence_display (no cards) --- ")
            return

        # Reset all sequence IDs and build adjacency list for BLUE lines only
        adj: Dict[int, List[TaskCard]] = {}
        in_degree: Dict[int, int] = {}
        card_map: Dict[int, TaskCard] = self.cards.copy()

        for card_id, card in card_map.items():
            adj[card_id] = []
            in_degree[card_id] = 0
            # 【BUG修复】安全调用 set_display_id，防止访问已删除对象
            try:
                if card and card.scene() == self.scene:
                    card.set_display_id(None)
            except RuntimeError:
                # 对象已被Qt删除，跳过
                pass

        if _debug_enabled:
            logger.debug(f"  [SEQ_DEBUG] Building graph from {len(self.connections)} connections...")
        connections_copy = list(self.connections)
        for conn in connections_copy:
            # 【BUG修复】增加安全检查，防止访问已删除的连接或卡片
            try:
                if not isinstance(conn, ConnectionLine) or not conn.start_item or not conn.end_item or conn.line_type != 'sequential':
                    continue

                start_id = conn.start_item.card_id
                end_id = conn.end_item.card_id
            except RuntimeError:
                # 对象已被Qt删除，跳过这个连接
                continue

            start_card_obj = card_map.get(start_id)
            end_card_obj = card_map.get(end_id)

            if start_card_obj and end_card_obj and start_card_obj == conn.start_item and end_card_obj == conn.end_item:
                if start_id in adj:
                     adj[start_id].append(end_card_obj)
                if end_id in in_degree:
                     in_degree[end_id] += 1

        # 2. Find starting nodes (only Card ID 0)
        queue = collections.deque()
        start_card = card_map.get(0)
        if start_card:
            queue.append(start_card)
            if _debug_enabled and in_degree.get(0, 0) != 0:
                logger.warning(f"  [SEQ_DEBUG] WARNING: Card 0 exists but has in_degree {in_degree.get(0)}. Sequence numbering may be incomplete.")
        elif _debug_enabled:
            logger.warning("  [顺序调试] 未找到卡片 0，将不会从 0 自动执行顺序编号。")

        sequence_counter = 0
        visited_in_bfs = set()

        # 3. Perform BFS to assign sequence IDs along the main blue line paths
        processed_nodes_count = 0
        while queue:
            current_card = queue.popleft()
            processed_nodes_count += 1

            # 注释已清理（原注释编码损坏）
            try:
                current_card_id = current_card.card_id
                if current_card_id not in card_map or card_map[current_card_id] != current_card:
                    continue

                if current_card.card_id in visited_in_bfs:
                    continue
                visited_in_bfs.add(current_card.card_id)

                # 安全调用 set_display_id
                if current_card.scene() == self.scene:
                    current_card.set_display_id(sequence_counter)
                sequence_counter += 1

                if current_card_id not in adj:
                    continue
                successors = adj[current_card_id]

                successors.sort(key=lambda c: c.card_id)
                for next_card in successors:
                    try:
                        next_card_id = next_card.card_id
                        if next_card_id not in card_map or card_map[next_card_id] != next_card:
                            continue
                        if next_card_id in in_degree:
                            in_degree[next_card_id] -= 1
                            if in_degree[next_card_id] == 0:
                                if next_card.card_id not in visited_in_bfs:
                                    queue.append(next_card)
                    except RuntimeError:
                        # 对象已被Qt删除，跳过
                        continue
            except RuntimeError:
                # 对象已被Qt删除，跳过
                continue

        if _debug_enabled:
            logger.debug(f"  [SEQ_DEBUG] Finished assigning sequence IDs. Processed {processed_nodes_count} nodes.")

        # 4. Update all jump (green/red) connections based on parameters and current card IDs
        # 注释已清理（原注释编码损坏）
        if not skip_jump_rebuild:
            if _debug_enabled:
                logger.debug("  [JUMP_CONN_DEBUG] Updating jump connections (incremental)...")

            # 构建期望的跳转连接集合: {(start_card_id, end_card_id, line_type)}
            expected_connections = set()
            for card_id in card_map:
                source_card = card_map.get(card_id)
                if not source_card:
                    continue

                # 【BUG修复】安全访问卡片属性
                try:
                    if source_card.scene() != self.scene:
                        continue

                    source_restricted = getattr(source_card, 'restricted_outputs', False)
                    if source_restricted:
                        continue

                    # Check Success Jump
                    on_success = source_card.parameters.get('on_success')
                    success_target_id = source_card.parameters.get('success_jump_target_id')
                    if on_success == '跳转到步骤' and success_target_id is not None:
                        if success_target_id in card_map:
                            expected_connections.add((card_id, success_target_id, 'success'))

                    # Check Failure Jump
                    on_failure = source_card.parameters.get('on_failure')
                    failure_target_id = source_card.parameters.get('failure_jump_target_id')
                    if on_failure == '跳转到步骤' and failure_target_id is not None:
                        if failure_target_id in card_map:
                            expected_connections.add((card_id, failure_target_id, 'failure'))
                except RuntimeError:
                    # 对象已被Qt删除，跳过
                    continue

            # 构建当前存在的跳转连接集合
            existing_connections = {}  # key: (start_id, end_id, type), value: connection object
            connections_to_remove = []
            for conn in list(self.connections):
                try:
                    if isinstance(conn, ConnectionLine) and conn.start_item and conn.end_item:
                        if conn.line_type in ['success', 'failure']:
                            key = (conn.start_item.card_id, conn.end_item.card_id, conn.line_type)
                            if key in expected_connections:
                                existing_connections[key] = conn
                            else:
                                # 这个连接不在期望集合中，需要删除
                                connections_to_remove.append(conn)
                except RuntimeError:
                    # 对象已被Qt删除，添加到删除列表
                    connections_to_remove.append(conn)

            # 删除不需要的连接
            for conn in connections_to_remove:
                try:
                    try:
                        from ..workflow_parts.connection_line import _unregister_animated_line
                        _unregister_animated_line(conn)
                    except Exception:
                        pass
                    if conn in self.connections:
                        self.connections.remove(conn)
                    if conn.scene() == self.scene:
                        self.scene.removeItem(conn)
                except RuntimeError:
                    # 对象已被Qt删除，跳过
                    pass

            # 只添加缺失的连接
            added_jump_count = 0
            for (start_id, end_id, line_type) in expected_connections:
                if (start_id, end_id, line_type) not in existing_connections:
                    source_card = card_map.get(start_id)
                    target_card = card_map.get(end_id)
                    if source_card and target_card:
                        try:
                            # 确保两个卡片都在场景中
                            if source_card.scene() != self.scene or target_card.scene() != self.scene:
                                continue
                            conn_type = ConnectionType.SUCCESS.value if line_type == 'success' else ConnectionType.FAILURE.value
                            # 注释已清理（原注释编码损坏）
                            if self.add_connection(source_card, target_card, conn_type, skip_duplicate_check=True):
                                added_jump_count += 1
                        except RuntimeError:
                            # 对象已被Qt删除，跳过
                            continue

            if _debug_enabled:
                logger.debug(f"  [JUMP_CONN_DEBUG] Incremental update done. Removed {len(connections_to_remove)}, Added {added_jump_count}.")

            # 注释已清理（原注释编码损坏）
            # 加载时使用 skip_duplicate_check=True，不会产生重复连接
            if not getattr(self, '_loading_workflow', False):
                # 最后清理所有重复的端口连接
                self.cleanup_all_duplicate_connections()

        # 清除更新序列标志
        self._updating_sequence = False
        debug_print(f"  [UNDO] Cleared updating sequence flag")

        if _debug_enabled:
            logger.debug("--- [DEBUG] END update_card_sequence_display --- ")

    def _remove_duplicate_port_connections(self, card: TaskCard, port_type: str):
        """移除指定卡片指定端口的所有重复连接，只保留最新的一个。"""
        # 注释已清理（原注释编码损坏）
        pass

    def cleanup_all_duplicate_connections(self):
        """清理所有重复的端口连接 - 【性能优化】使用 O(m) 复杂度算法。"""
        # 使用字典记录每个 (card_id, port_type) 的连接
        # key: (start_card_id, line_type), value: list of connections
        port_connections = {}

        for conn in list(self.connections):
            if isinstance(conn, ConnectionLine) and conn.start_item:
                # 注释已清理（原注释编码损坏）
                is_random_jump_random_port = (conn.line_type == 'random' and
                                              hasattr(conn.start_item, 'task_type') and
                                              conn.start_item.task_type == '随机跳转')
                if is_random_jump_random_port:
                    continue
                # ---------------------------------------------------------------
                key = (conn.start_item.card_id, conn.line_type)
                if key not in port_connections:
                    port_connections[key] = []
                port_connections[key].append(conn)

        # 注释已清理（原注释编码损坏）
        for key, conns in port_connections.items():
            if len(conns) > 1:
                # 移除除最后一个外的所有连接
                for conn in conns[:-1]:
                    try:
                        from ..workflow_parts.connection_line import _unregister_animated_line
                        _unregister_animated_line(conn)
                    except Exception:
                        pass
                    if conn in self.connections:
                        self.connections.remove(conn)
                    if conn.scene() == self.scene:
                        self.scene.removeItem(conn)

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
            try:
                from ..workflow_parts.connection_line import _unregister_animated_line
                _unregister_animated_line(conn)
            except Exception:
                pass
            if conn in self.connections:
                self.connections.remove(conn)
            if conn.scene() == self.scene:
                self.scene.removeItem(conn)
            # 从卡片连接列表中移除
            if hasattr(card, 'connections') and conn in card.connections:
                card.connections.remove(conn)
            if hasattr(conn, 'end_item') and conn.end_item:
                end_card = conn.end_item
                if hasattr(end_card, 'connections') and conn in end_card.connections:
                    end_card.connections.remove(conn)

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
