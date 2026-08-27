from .workflow_view_common import *

operation_logger = logging.getLogger("workflow.operations")
debug_print = lambda *args, **kwargs: None

class WorkflowViewClipboardUndoMixin:

    def _delete_selected_cards(self, selected_cards: List[TaskCard]):
        """删除选中的多个卡片"""
        if not selected_cards:
            return

        if self._block_edit_if_running("删除选中卡片"):
            return

        operation_logger.info("[批量删除] 请求删除卡片数量=%s", len(selected_cards))

        # 注释已清理（原注释编码损坏）
        deleted_count = self._delete_cards_batch(selected_cards)

        operation_logger.info("[批量删除] 完成，实际删除数量=%s", deleted_count)

    def _delete_cards_batch(self, selected_cards: List[TaskCard], selected_connections=None) -> int:
        """将选中的卡片和连线作为一个撤回事务删除。"""
        selected_connections = list(selected_connections or [])
        if not selected_cards and not selected_connections:
            return 0

        has_start_card = False
        candidate_ids: List[int] = []
        for card in selected_cards:
            if not isinstance(card, TaskCard):
                continue
            card_id = getattr(card, "card_id", None)
            if card_id is None or card_id not in self.cards:
                continue
            candidate_ids.append(card_id)
            if not has_start_card and self._is_start_task_type(getattr(card, "task_type", "")):
                has_start_card = True

        if not candidate_ids and not selected_connections:
            return 0

        deleted_count = 0
        unique_ids = sorted(set(candidate_ids), reverse=True)

        card_states = []
        connection_states = {}
        for card_id in unique_ids:
            card = self.cards[card_id]
            card_states.append({
                'card_id': card.card_id,
                'task_type': card.task_type,
                'parameters': copy.deepcopy(card.parameters),
                'custom_name': card.custom_name,
                'position': (card.pos().x(), card.pos().y()),
            })
            for connection in card.connections:
                key = id(connection)
                connection_states[key] = {
                    'start_card_id': connection.start_item.card_id,
                    'end_card_id': connection.end_item.card_id,
                    'line_type': connection.line_type,
                }

        standalone_connections = []
        selected_card_objects = {self.cards[card_id] for card_id in unique_ids}
        for connection in selected_connections:
            if (
                getattr(connection, 'start_item', None) in selected_card_objects
                or getattr(connection, 'end_item', None) in selected_card_objects
            ):
                continue
            self._validate_connection_contract(connection)
            standalone_connections.append(connection)
            connection_states[id(connection)] = {
                'start_card_id': connection.start_item.card_id,
                'end_card_id': connection.end_item.card_id,
                'line_type': connection.line_type,
            }

        updates_enabled = self.updatesEnabled()
        was_undoing = self._undoing_operation
        self.setUpdatesEnabled(False)
        self._undoing_operation = True
        try:
            for connection in standalone_connections:
                if not self.remove_connection(connection):
                    raise RuntimeError("批量删除中的连线删除失败")
            for card_id in unique_ids:
                if card_id not in self.cards:
                    continue
                self.delete_card(card_id, defer_view_refresh=True)
                if card_id in self.cards:
                    raise RuntimeError(f"批量删除卡片失败: {card_id}")
                deleted_count += 1
        finally:
            self._undoing_operation = was_undoing
            self.setUpdatesEnabled(updates_enabled)

        if deleted_count > 0 or standalone_connections:
            self._save_undo_state('delete_batch', {
                'card_states': card_states,
                'connections': list(connection_states.values()),
            })
            self.update_card_sequence_display()
            if has_start_card:
                self._refresh_thread_start_custom_names()
            self.viewport().update()

        return deleted_count

    def handle_copy_card(self, card_id: int, parameters: dict):
        """Stores the data of the card requested to be copied (单卡片复制，保持向后兼容)."""
        card = self.cards.get(card_id)
        if card:
            safe_parameters = copy.deepcopy(parameters if isinstance(parameters, dict) else card.parameters)
            type(self).copied_card_data = {
                'single_card': True,  # 标记为单卡片复制
                'task_type': card.task_type,
                'parameters': safe_parameters,
                'custom_name': card.custom_name  # 包含卡片备注
            }
            operation_logger.info("[复制] 已复制卡片 card_id=%s", card_id)
        else:
            operation_logger.warning("[复制] 卡片不存在 card_id=%s", card_id)

    def handle_copy_selected_cards(self):
        """复制当前选中的所有卡片"""
        if self._block_edit_if_running("复制选中卡片"):
            return

        selected_items = self.scene.selectedItems()
        selected_cards = [item for item in selected_items if isinstance(item, TaskCard)]
        selected_cards.sort(key=lambda card: card.card_id)

        if not selected_cards:
            operation_logger.info("[复制] 没有选中卡片")
            return

        # 注释已清理（原注释编码损坏）
        if len(selected_cards) == 1:
            single_card = selected_cards[0]
            self.handle_copy_card(single_card.card_id, single_card.parameters)
            return

        # 创建卡片ID到索引的映射
        selected_card_ids = {card.card_id for card in selected_cards}

        # 准备批量复制数据
        cards_data = []
        connections_data = []

        for card in selected_cards:
            card_data = {
                'task_type': card.task_type,
                'parameters': copy.deepcopy(card.parameters),
                'custom_name': card.custom_name,
                'original_pos': (card.pos().x(), card.pos().y()),  # 保存原始位置用于相对定位
                'original_card_id': card.card_id  # 保存原始卡片ID用于映射
            }
            cards_data.append(card_data)

            # 收集该卡片的连接信息（只保存选中卡片之间的连接）
            for conn in card.connections:
                if isinstance(conn, ConnectionLine):
                    start_id = conn.start_item.card_id if conn.start_item else None
                    end_id = conn.end_item.card_id if conn.end_item else None

                    # 只保存两端都在选中卡片中的连接，且只保存出向连接以避免重复
                    if (start_id in selected_card_ids and
                        end_id in selected_card_ids and
                        conn.start_item == card):
                        conn_data = {
                            'start_card_id': start_id,
                            'end_card_id': end_id,
                            'line_type': conn.line_type
                        }
                        connections_data.append(conn_data)

        type(self).copied_card_data = {
            'single_card': False,  # 标记为批量复制
            'cards': cards_data,
            'connections': connections_data  # 保存连接信息
        }

        operation_logger.info(
            "[复制] 已复制卡片数量=%s，连线数量=%s",
            len(selected_cards),
            len(connections_data),
        )

    def is_paste_available(self) -> bool:
        """Checks if there is card data in the clipboard to paste."""
        return type(self).copied_card_data is not None

    def handle_paste_card(self, scene_pos: QPointF):
        """Handles pasting card(s) from the internal clipboard at the given scene position."""
        # 检查是否正在运行，如果是则阻止粘贴
        if self._block_edit_if_running("粘贴卡片"):
            return

        debug_print(f"--- [DEBUG] WorkflowView: handle_paste_card START - Scene Pos: {scene_pos} ---")
        if not type(self).copied_card_data:
            debug_print("  [调试] 粘贴失败：剪贴板中没有卡片数据。")
            QMessageBox.warning(self, "粘贴失败", "剪贴板中没有可粘贴的卡片数据。")
            debug_print("--- [DEBUG] WorkflowView: handle_paste_card END (No data) ---")
            return

        # 注释已清理（原注释编码损坏）
        is_single_card = type(self).copied_card_data.get('single_card', True)

        if is_single_card:
            # 单卡片粘贴（保持原有逻辑）
            self._paste_single_card(scene_pos)
        else:
            # 批量卡片粘贴
            self._paste_multiple_cards(scene_pos)

        debug_print("--- [DEBUG] WorkflowView: handle_paste_card END ---")

    def _paste_single_card(self, scene_pos: QPointF):
        """粘贴单个卡片"""
        # Extract data from clipboard
        task_type = type(self).copied_card_data.get('task_type')
        parameters_to_paste = type(self).copied_card_data.get('parameters', {})

        if not task_type or not self.task_modules.get(task_type):
            debug_print(f"  [调试] 粘贴失败：剪贴板数据中的任务类型无效 '{task_type}'。")
            QMessageBox.critical(self, "粘贴失败", f"剪贴板中的卡片类型 '{task_type}' 无效。")
            return

        debug_print(f"  [DEBUG] Pasting single card: Type='{task_type}', Params={parameters_to_paste}")

        # 设置粘贴标志，防止add_task_card保存撤销状态
        self._pasting_card = True
        # Add the new card at the specified position
        try:
            new_card = self.add_task_card(scene_pos.x(), scene_pos.y(), task_type, card_id=None)
        finally:
            self._pasting_card = False
        # 重置粘贴标志

        if new_card:
            debug_print(f"  [DEBUG] New card created with ID: {new_card.card_id}")
            # Apply the copied parameters to the new card
            new_card.parameters.update(copy.deepcopy(parameters_to_paste))
            if new_card.task_type == '随机跳转':
                from tasks.random_jump import prune_branch_weights

                new_card.parameters['random_weights'] = prune_branch_weights(
                    new_card.parameters.get('random_weights'),
                    [],
                )
            debug_print(f"  [DEBUG] Copied parameters applied to new card {new_card.card_id}: {new_card.parameters}")

            # Apply the copied custom name (备注)
            custom_name = type(self).copied_card_data.get('custom_name')
            if custom_name and (not self._is_start_task_type(new_card.task_type)):
                new_card.set_custom_name(custom_name)
                debug_print(f"  [DEBUG] Copied custom name applied to new card {new_card.card_id}: '{custom_name}'")

            # 保存撤销状态
            self._save_undo_state('paste_cards', {
                'pasted_card_ids': [new_card.card_id],
                'paste_type': 'single'
            })

            self.update_card_sequence_display()
            if self._is_start_task_type(new_card.task_type):
                self._refresh_thread_start_custom_names()
            operation_logger.info("[粘贴] 单卡粘贴完成 card_id=%s", new_card.card_id)
            debug_print("  Single card pasted successfully.")
        else:
            debug_print("  [调试] 粘贴失败：add_task_card 返回了 None。")
            QMessageBox.critical(self, "粘贴失败", "创建新卡片时发生错误。")

    def _remap_pasted_card_selector_value(self, value: Any, old_to_new_card_map: Dict[int, TaskCard]):
        """将粘贴参数中的旧卡片ID映射为新卡片ID，支持单值与列表。"""
        if isinstance(value, bool):
            return value, False

        if isinstance(value, int):
            mapped_card = old_to_new_card_map.get(value)
            if mapped_card:
                return mapped_card.card_id, True
            return value, False

        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return value, False

            parsed_id = None
            match = re.search(r'\(ID:\s*(\d+)\)', stripped)
            if match:
                try:
                    parsed_id = int(match.group(1))
                except ValueError:
                    parsed_id = None
            else:
                try:
                    parsed_id = int(stripped)
                except (TypeError, ValueError):
                    parsed_id = None

            if parsed_id is not None:
                mapped_card = old_to_new_card_map.get(parsed_id)
                if mapped_card:
                    return mapped_card.card_id, True

            return value, False

        if isinstance(value, list):
            updated_values = []
            changed = False
            for item in value:
                updated_item, item_changed = self._remap_pasted_card_selector_value(item, old_to_new_card_map)
                updated_values.append(updated_item)
                changed = changed or item_changed
            if changed:
                return updated_values, True
            return value, False

        if isinstance(value, tuple):
            updated_values = []
            changed = False
            for item in value:
                updated_item, item_changed = self._remap_pasted_card_selector_value(item, old_to_new_card_map)
                updated_values.append(updated_item)
                changed = changed or item_changed
            if changed:
                return tuple(updated_values), True
            return value, False

        return value, False

    def _paste_multiple_cards(self, scene_pos: QPointF):
        """粘贴多个卡片"""
        cards_data = type(self).copied_card_data.get('cards', [])
        connections_data = type(self).copied_card_data.get('connections', [])

        if not cards_data:
            QMessageBox.warning(self, "粘贴失败", "剪贴板中没有有效的卡片数据。")
            return

        original_ids = set()
        for index, card_data in enumerate(cards_data):
            if not isinstance(card_data, dict):
                raise TypeError(f"剪贴板卡片数据第 {index + 1} 项必须是字典")
            task_type = card_data.get('task_type')
            original_card_id = card_data.get('original_card_id')
            original_pos = card_data.get('original_pos')
            if not isinstance(task_type, str) or task_type not in self.task_modules:
                raise ValueError(f"剪贴板包含无效任务类型: {task_type!r}")
            if isinstance(original_card_id, bool) or not isinstance(original_card_id, int):
                raise TypeError("剪贴板卡片原始 ID 必须是整数")
            if original_card_id in original_ids:
                raise ValueError(f"剪贴板卡片原始 ID 重复: {original_card_id}")
            if not isinstance(original_pos, (list, tuple)) or len(original_pos) != 2:
                raise TypeError(f"剪贴板卡片 {original_card_id} 的位置格式无效")
            original_ids.add(original_card_id)

        for index, connection_data in enumerate(connections_data):
            if not isinstance(connection_data, dict):
                raise TypeError(f"剪贴板连线数据第 {index + 1} 项必须是字典")
            start_id = connection_data.get('start_card_id')
            end_id = connection_data.get('end_card_id')
            line_type = connection_data.get('line_type')
            if start_id not in original_ids or end_id not in original_ids:
                raise ValueError(f"剪贴板连线端点无效: {start_id} -> {end_id}")
            if line_type not in self._VALID_CONNECTION_TYPES:
                raise ValueError(f"剪贴板包含无效连线类型: {line_type!r}")

        # 计算原始卡片的边界框，用于相对定位（即使只有1张卡片也使用真实最小值）
        min_x = min(card_data['original_pos'][0] for card_data in cards_data)
        min_y = min(card_data['original_pos'][1] for card_data in cards_data)

        new_cards = []
        failed_count = 0
        pasted_has_start_card = False
        # 注释已清理（原注释编码损坏）
        old_to_new_card_map = {}

        # 设置粘贴标志，防止add_task_card保存撤销状态
        self._pasting_card = True

        for i, card_data in enumerate(cards_data):
            task_type = card_data.get('task_type')
            parameters = card_data.get('parameters', {})
            custom_name = card_data.get('custom_name')
            original_pos = card_data.get('original_pos', (0, 0))
            original_card_id = card_data.get('original_card_id')

            if not task_type or not self.task_modules.get(task_type):
                debug_print(f"  [DEBUG] Skipping invalid task type: {task_type}")
                self._pasting_card = False
                raise ValueError(f"剪贴板包含无效任务类型: {task_type!r}")

            # 计算新位置（相对于点击位置）
            offset_x = original_pos[0] - min_x
            offset_y = original_pos[1] - min_y
            new_x = scene_pos.x() + offset_x
            new_y = scene_pos.y() + offset_y

            # 创建新卡片
            new_card = self.add_task_card(new_x, new_y, task_type, card_id=None)

            if new_card:
                # 应用参数
                new_card.parameters.update(copy.deepcopy(parameters))

                # 应用备注
                if custom_name and (not self._is_start_task_type(new_card.task_type)):
                    new_card.set_custom_name(custom_name)
                if self._is_start_task_type(new_card.task_type):
                    pasted_has_start_card = True

                new_cards.append(new_card)
                # 保存ID映射关系
                if original_card_id is not None:
                    old_to_new_card_map[original_card_id] = new_card
                debug_print(f"  [DEBUG] Created card {i+1}/{len(cards_data)}: ID {new_card.card_id} ({task_type}), mapped from old ID {original_card_id}")
            else:
                self._pasting_card = False
                raise RuntimeError(f"粘贴卡片创建失败: {task_type}")
                debug_print(f"  [调试] 创建卡片失败 {i+1}/{len(cards_data)}：{task_type}")

        # 注意：不在这里重置 _pasting_card 标志，等连接重建完成后再重置
        # 这样可以防止重建连接时保存单独的撤销状态

        # 重建连接
        connection_count = 0
        if connections_data and old_to_new_card_map:
            debug_print(f"  [DEBUG] Rebuilding {len(connections_data)} connections...")
            for conn_data in connections_data:
                old_start_id = conn_data.get('start_card_id')
                old_end_id = conn_data.get('end_card_id')
                line_type = conn_data.get('line_type')

                # 查找对应的新卡片
                new_start_card = old_to_new_card_map.get(old_start_id)
                new_end_card = old_to_new_card_map.get(old_end_id)

                if new_start_card and new_end_card and line_type:
                    # 使用 add_connection 方法创建连接
                    connection = self.add_connection(new_start_card, new_end_card, line_type)
                    if connection:
                        connection_count += 1
                        debug_print(f"  [DEBUG] Recreated connection: {new_start_card.card_id} -> {new_end_card.card_id} ({line_type})")
                    else:
                        self._pasting_card = False
                        raise RuntimeError(
                            f"粘贴连线创建失败: {new_start_card.card_id} -> "
                            f"{new_end_card.card_id} ({line_type})"
                        )
                else:
                    self._pasting_card = False
                    raise RuntimeError(f"粘贴连线缺少端点: {old_start_id} -> {old_end_id}")

        # 重置粘贴标志（在连接重建完成后）
        self._pasting_card = False

        # 更新参数中的卡片ID引用
        # 注释已清理（原注释编码损坏）
        if old_to_new_card_map:
            for new_card in new_cards:
                # 注释已清理（原注释编码损坏）
                task_module = self.task_modules.get(new_card.task_type)
                if not task_module:
                    continue

                # 获取参数定义字典
                param_definitions = {}
                if hasattr(task_module, 'get_params_definition'):
                    try:
                        param_definitions = task_module.get_params_definition()
                    except Exception as e:
                        debug_print(f"  [调试] 获取参数定义失败 {new_card.task_type}：{e}")
                        param_definitions = {}
                elif hasattr(task_module, 'get_parameters'):
                    try:
                        param_definitions = task_module.get_parameters()
                    except Exception as e:
                        debug_print(f"  [调试] 获取参数定义失败 {new_card.task_type}：{e}")
                        param_definitions = {}

                if isinstance(param_definitions, list):
                    converted_defs = {}
                    for item in param_definitions:
                        if isinstance(item, dict) and item.get('name'):
                            converted_defs[item['name']] = item
                    param_definitions = converted_defs

                if not isinstance(param_definitions, dict):
                    continue

                # 只更新 widget_hint 为 'card_selector' 的参数
                for param_name, param_value in new_card.parameters.items():
                    param_def = param_definitions.get(param_name, {})
                    widget_hint = param_def.get('widget_hint')

                    # 只有明确标记为 card_selector 的参数才更新
                    if widget_hint != 'card_selector':
                        continue

                    remapped_value, changed = self._remap_pasted_card_selector_value(param_value, old_to_new_card_map)
                    if changed:
                        new_card.parameters[param_name] = remapped_value
                        debug_print(
                            f"  [DEBUG] Updated card_selector parameter '{param_name}' in card {new_card.card_id}: "
                            f"{param_value} -> {remapped_value}"
                        )

                if new_card.task_type == '随机跳转':
                    from tasks.random_jump import normalize_branch_weights, prune_branch_weights

                    normalized_weights = normalize_branch_weights(new_card.parameters.get('random_weights'))
                    remapped_weights = {}
                    for target_key, branch_weight in normalized_weights.items():
                        mapped_card = old_to_new_card_map.get(int(target_key))
                        if mapped_card:
                            remapped_weights[str(mapped_card.card_id)] = branch_weight

                    valid_random_targets = []
                    for conn in getattr(new_card, 'connections', []):
                        if not isinstance(conn, ConnectionLine):
                            continue
                        if conn.start_item != new_card or conn.line_type != 'random' or not conn.end_item:
                            continue
                        valid_random_targets.append(conn.end_item.card_id)

                    new_card.parameters['random_weights'] = prune_branch_weights(remapped_weights, valid_random_targets)

        # 保存撤销状态（只有成功粘贴的卡片）
        if new_cards:
            pasted_card_ids = [card.card_id for card in new_cards]
            self._save_undo_state('paste_cards', {
                'pasted_card_ids': pasted_card_ids,
                'paste_type': 'multiple'
            })

            # 触发更新
            self.update_card_sequence_display()
            if pasted_has_start_card:
                self._refresh_thread_start_custom_names()

        # 记录结果日志（不再弹出提示框）
        success_count = len(new_cards)
        if success_count > 0:
            if failed_count > 0:
                logger.info(f"粘贴完成: 成功粘贴 {success_count} 个卡片和 {connection_count} 条连接，失败 {failed_count} 个卡片")
            else:
                logger.info(f"粘贴成功: 成功粘贴 {success_count} 个卡片和 {connection_count} 条连接")
        else:
            logger.error("粘贴失败: 所有卡片粘贴都失败了")

        if success_count > 0:
            operation_logger.info(
                "[粘贴] 批量粘贴完成，卡片数量=%s，连线数量=%s",
                success_count,
                connection_count,
            )

    def copy_selected_card(self):
        """复制当前选中的卡片到剪贴板（不自动粘贴）。"""
        # 检查是否正在运行，如果是则阻止复制
        if self._block_edit_if_running("复制选中卡片"):
            return
        self.handle_copy_selected_cards()

    _UNDO_OPERATION_FIELDS = {
        'paste_cards': {'pasted_card_ids', 'paste_type'},
        'delete_card': {'card_state'},
        'delete_batch': {'card_states', 'connections'},
        'delete_connection': {'connection_data'},
        'add_connection': {'connection_data'},
        'modify_connection': {'old_connection_data', 'new_connection_data'},
        'add_card': {'card_data'},
        'change_card_ids': {'id_mapping'},
    }

    def _save_undo_state(self, operation_type: str, operation_data: Dict[str, Any]):
        """保存撤销状态到历史栈。"""
        if self._block_edit_if_running("保存撤销状态"):
            return

        # 注释已清理（原注释编码损坏）
        if self._loading_workflow:
            debug_print(f"  [UNDO] Skipping undo save during workflow loading: {operation_type}")
            return

        if self._undoing_operation:
            debug_print(f"  [UNDO] Skipping undo save during undo operation: {operation_type}")
            logger.info(f"  [UNDO] Skipping undo save during undo operation: {operation_type}")
            return

        if operation_type not in self._UNDO_OPERATION_FIELDS:
            raise ValueError(f"未知撤回操作类型: {operation_type}")
        if not isinstance(operation_data, dict):
            raise TypeError("撤回操作数据必须是字典")
        expected_fields = self._UNDO_OPERATION_FIELDS[operation_type]
        if set(operation_data) != expected_fields:
            raise ValueError(
                f"撤回操作 {operation_type} 字段错误: "
                f"期望 {sorted(expected_fields)}，实际 {sorted(operation_data)}"
            )

        undo_state = {
            'operation_type': operation_type,
            'operation_data': copy.deepcopy(operation_data),
            'timestamp': time.time()
        }

        self.undo_stack.append(undo_state)

        # 限制撤销历史的大小
        if len(self.undo_stack) > self.max_undo_steps:
            self.undo_stack.pop(0)

        debug_print(f"  [UNDO] Saved undo state: {operation_type}, stack size: {len(self.undo_stack)}")

    def _save_card_state_for_undo(self, card: TaskCard):
        """保存卡片的完整状态用于撤销删除操作"""
        debug_print(f"  [UNDO] _save_card_state_for_undo called for card {card.card_id}")
        try:
            # 收集卡片的所有连接信息
            connections_data = []
            debug_print(f"  [UNDO] Card {card.card_id} has {len(card.connections)} connections")
            for conn in card.connections:
                if isinstance(conn, ConnectionLine):
                    conn_data = {
                        'start_card_id': conn.start_item.card_id if conn.start_item else None,
                        'end_card_id': conn.end_item.card_id if conn.end_item else None,
                        'line_type': conn.line_type,
                        'is_outgoing': conn.start_item == card  # 是否是从该卡片发出的连接
                    }
                    connections_data.append(conn_data)

            # 保存卡片的完整状态
            card_state = {
                'card_id': card.card_id,
                'task_type': card.task_type,
                'parameters': copy.deepcopy(card.parameters),
                'custom_name': card.custom_name,
                'position': (card.pos().x(), card.pos().y()),
                'connections': connections_data
            }

            # 注释已清理（原注释编码损坏）
            self._save_undo_state('delete_card', {
                'card_state': card_state
            })

            debug_print(f"  [UNDO] Saved card state for undo: {card.card_id} with {len(connections_data)} connections")

        except Exception as e:
            operation_logger.error("[撤回记录] 保存卡片删除状态失败: %s", e, exc_info=True)
            logger.error(f"保存卡片状态失败: {e}", exc_info=True)

    def _save_connection_state_for_undo(self, connection):
        """保存连接状态用于撤销删除操作"""
        try:
            if isinstance(connection, ConnectionLine):
                conn_data = {
                    'start_card_id': connection.start_item.card_id if connection.start_item else None,
                    'end_card_id': connection.end_item.card_id if connection.end_item else None,
                    'line_type': connection.line_type
                }

                # 注释已清理（原注释编码损坏）
                self._save_undo_state('delete_connection', {
                    'connection_data': conn_data
                })

                debug_print(f"  [UNDO] Saved connection state for undo: {conn_data['start_card_id']} -> {conn_data['end_card_id']} ({conn_data['line_type']})")

        except Exception as e:
            operation_logger.error("[撤回记录] 保存连线删除状态失败: %s", e, exc_info=True)
            logger.error(f"保存连接状态失败: {e}", exc_info=True)

    def _save_add_connection_state_for_undo(self, start_card, end_card, line_type):
        """保存添加连接的状态用于撤销"""
        try:
            conn_data = {
                'start_card_id': start_card.card_id if start_card else None,
                'end_card_id': end_card.card_id if end_card else None,
                'line_type': line_type
            }

            # 注释已清理（原注释编码损坏）
            self._save_undo_state('add_connection', {
                'connection_data': conn_data
            })

            debug_print(f"  [UNDO] Saved add connection state for undo: {conn_data['start_card_id']} -> {conn_data['end_card_id']} ({conn_data['line_type']})")

        except Exception as e:
            operation_logger.error("[撤回记录] 保存连线新增状态失败: %s", e, exc_info=True)
            logger.error(f"保存添加连接状态失败: {e}", exc_info=True)

    def _save_modify_connection_state_for_undo(self, old_connection, new_start_card, new_end_card, new_line_type):
        """保存修改连接的状态用于撤销（包含删除旧连接和添加新连接）。"""
        try:
            # 注释已清理（原注释编码损坏）
            old_conn_data = {
                'start_card_id': old_connection.start_item.card_id if old_connection.start_item else None,
                'end_card_id': old_connection.end_item.card_id if old_connection.end_item else None,
                'line_type': old_connection.line_type if hasattr(old_connection, 'line_type') else 'unknown'
            }

            # 新连接数据
            new_conn_data = {
                'start_card_id': new_start_card.card_id if new_start_card else None,
                'end_card_id': new_end_card.card_id if new_end_card else None,
                'line_type': new_line_type
            }

            # 保存复合撤销操作
            self._save_undo_state('modify_connection', {
                'old_connection_data': old_conn_data,
                'new_connection_data': new_conn_data
            })

            debug_print("  [UNDO] Saved modify connection state for undo:")
            debug_print(f"    Old: {old_conn_data['start_card_id']} -> {old_conn_data['end_card_id']} ({old_conn_data['line_type']})")
            debug_print(f"    New: {new_conn_data['start_card_id']} -> {new_conn_data['end_card_id']} ({new_conn_data['line_type']})")

        except Exception as e:
            operation_logger.error("[撤回记录] 保存连线修改状态失败: %s", e, exc_info=True)
            logger.error(f"保存修改连接状态失败: {e}", exc_info=True)

    def _save_add_card_state_for_undo(self, card_id: int, task_type: str, x: float, y: float, parameters: Optional[dict]):
        """保存添加卡片的状态用于撤销"""
        try:
            card_data = {
                'card_id': card_id,
                'task_type': task_type,
                'position': (x, y),
                'parameters': copy.deepcopy(parameters) if parameters else {}
            }

            # 注释已清理（原注释编码损坏）
            self._save_undo_state('add_card', {
                'card_data': card_data
            })

            debug_print(f"  [UNDO] Saved add card state for undo: ID={card_id}, type={task_type}, pos=({x}, {y})")

        except Exception as e:
            operation_logger.error("[撤回记录] 保存卡片新增状态失败: %s", e, exc_info=True)
            logger.error(f"保存添加卡片状态失败: {e}", exc_info=True)

    def can_undo(self) -> bool:
        """检查是否可以撤销"""
        can_undo = len(self.undo_stack) > 0 and not self._is_workflow_running()
        debug_print(f"  [UNDO] can_undo check: stack_size={len(self.undo_stack)}, is_running={self._is_workflow_running()}, result={can_undo}")
        if len(self.undo_stack) > 0:
            last_op = self.undo_stack[-1]
            debug_print(f"  [UNDO] Last operation in stack: {last_op.get('operation_type', 'unknown')}")
        return can_undo

    def undo_last_operation(self):
        """撤销最后一个操作。"""
        operation_logger.info("[撤回] 请求撤回，当前历史数量=%s", len(self.undo_stack))
        debug_print("  [UNDO] undo_last_operation called")

        if not self.can_undo():
            operation_logger.info("[撤回] 无可撤回操作")
            debug_print("  [UNDO] Cannot undo: no operations in stack or workflow is running")
            return

        if self._block_edit_if_running("撤销操作"):
            return

        # 设置撤销操作标志，防止撤销过程中的操作触发新的撤销保存
        self._undoing_operation = True
        debug_print("  [UNDO] Set undoing operation flag to True")

        # 【闪退修复】双重检查undo_stack，防止竞态条件导致IndexError
        if not self.undo_stack:
            operation_logger.error("[撤回] 撤销栈为空，无法执行")
            self._undoing_operation = False
            return

        last_operation = self.undo_stack.pop()
        operation_type = last_operation['operation_type']
        operation_data = last_operation['operation_data']

        debug_print(f"  [UNDO] Undoing operation: {operation_type}")
        debug_print(f"  [UNDO] Operation data: {operation_data}")

        try:
            if operation_type == 'paste_cards':
                self._undo_paste_cards(operation_data)
            elif operation_type == 'delete_card':
                self._undo_delete_card(operation_data)
            elif operation_type == 'delete_batch':
                self._undo_delete_batch(operation_data)
            elif operation_type == 'delete_connection':
                self._undo_delete_connection(operation_data)
            elif operation_type == 'add_connection':
                self._undo_add_connection(operation_data)
            elif operation_type == 'modify_connection':
                self._undo_modify_connection(operation_data)
            elif operation_type == 'add_card':
                self._undo_add_card(operation_data)
            elif operation_type == 'change_card_ids':
                self._undo_change_card_ids(operation_data)
            else:
                operation_logger.error("[撤回] 未知操作类型: %s", operation_type)
                debug_print(f"  [UNDO] Unknown operation type: {operation_type}")
                return

            # 更新显示
            self.update_card_sequence_display()
            operation_logger.info("[撤回] 完成 operation_type=%s，剩余历史数量=%s", operation_type, len(self.undo_stack))
            debug_print(f"  [UNDO] Successfully undone operation: {operation_type}")

        except Exception as e:
            operation_logger.error("[撤回] 失败 operation_type=%s: %s", operation_type, e, exc_info=True)
            debug_print(f"  [UNDO] Error undoing operation {operation_type}: {e}")

        finally:
            # 无论成功还是失败，都要清除撤销操作标志
            self._undoing_operation = False
            debug_print("  [UNDO] Cleared undoing operation flag")

    def _undo_paste_cards(self, operation_data: Dict[str, Any]):
        """撤销粘贴卡片操作"""
        pasted_card_ids = operation_data.get('pasted_card_ids', [])

        debug_print(f"  [UNDO] Undoing paste operation, removing {len(pasted_card_ids)} cards")

        for card_id in pasted_card_ids:
            if card_id in self.cards:
                card = self.cards[card_id]
                # 移除卡片的所有连接
                for conn in list(card.connections):
                    self.remove_connection(conn)

                # 注释已清理（原注释编码损坏）
                if card.scene() == self.scene:
                    self.scene.removeItem(card)
                del self.cards[card_id]

                debug_print(f"  [UNDO] Removed pasted card: {card_id}")

    def _undo_delete_card(self, operation_data: Dict[str, Any]):
        """撤销删除卡片操作"""
        card_state = operation_data.get('card_state')
        if not card_state:
            operation_logger.error("[撤回] 缺少卡片状态，无法恢复")
            debug_print("  [UNDO] No card state found for undo")
            return

        card_id = card_state['card_id']
        task_type = card_state['task_type']
        parameters = card_state['parameters']
        custom_name = card_state['custom_name']
        position = card_state['position']
        connections_data = card_state['connections']

        debug_print(f"  [UNDO] Restoring deleted card: {card_id} ({task_type})")
        debug_print("  [UNDO] Card state to restore:")
        debug_print(f"    - Position: {position}")
        debug_print(f"    - Parameters: {parameters}")
        debug_print(f"    - Custom name: {custom_name}")
        debug_print(f"    - Connections: {len(connections_data)} connections")

        # 注释已清理（原注释编码损坏）
        if card_id in self.cards:
            debug_print(f"  [撤销] 错误：卡片 ID {card_id} 已存在，当前卡片：{list(self.cards.keys())}")
            return

        # 重新创建卡片
        debug_print(f"  [UNDO] Calling add_task_card with: pos=({position[0]}, {position[1]}), type={task_type}, id={card_id}")
        restored_card = self.add_task_card(position[0], position[1], task_type, card_id, parameters)
        if not restored_card:
            operation_logger.error("[撤回] 恢复卡片失败 card_id=%s", card_id)
            debug_print(f"  [撤销] 错误：恢复卡片失败 {card_id}")
            return

        debug_print(f"  [UNDO] Card {card_id} created successfully")
        debug_print(f"  [UNDO] Restored card parameters: {restored_card.parameters}")

        # 恢复自定义名称
        if custom_name:
            debug_print(f"  [UNDO] Setting custom name: '{custom_name}'")
            restored_card.set_custom_name(custom_name)
        else:
            debug_print("  [UNDO] No custom name to restore")

        # 注释已清理（原注释编码损坏）
        debug_print(f"  [UNDO] Scheduling connection restoration for card {card_id} in 500ms")
        QTimer.singleShot(500, lambda: self._restore_card_connections(card_id, connections_data))

        debug_print(f"  [UNDO] Successfully restored card {card_id}")

    def _undo_delete_batch(self, operation_data: Dict[str, Any]):
        """一次恢复批量删除的全部卡片和连线。"""
        card_states = operation_data.get('card_states')
        connections_data = operation_data.get('connections')
        if not isinstance(card_states, list) or not isinstance(connections_data, list):
            raise TypeError("批量删除撤回数据格式无效")

        for card_state in sorted(card_states, key=lambda item: item['card_id']):
            card_id = card_state['card_id']
            if card_id in self.cards:
                raise RuntimeError(f"恢复批量删除失败，卡片已存在: {card_id}")
            restored_card = self.add_task_card(
                card_state['position'][0],
                card_state['position'][1],
                card_state['task_type'],
                card_id,
                card_state['parameters'],
            )
            if restored_card is None:
                raise RuntimeError(f"恢复批量删除卡片失败: {card_id}")
            custom_name = card_state.get('custom_name')
            if custom_name:
                restored_card.set_custom_name(custom_name)

        restored_keys = set()
        for connection_data in connections_data:
            key = (
                connection_data['start_card_id'],
                connection_data['end_card_id'],
                connection_data['line_type'],
            )
            if key in restored_keys:
                continue
            restored_keys.add(key)
            start_card = self.cards.get(key[0])
            end_card = self.cards.get(key[1])
            if start_card is None or end_card is None:
                raise RuntimeError(f"恢复批量删除连线失败，缺少端点: {key[0]} -> {key[1]}")
            if self.add_connection(start_card, end_card, key[2]) is None:
                raise RuntimeError(f"恢复批量删除连线失败: {key[0]} -> {key[1]} ({key[2]})")

    def _restore_card_connections(self, card_id: int, connections_data: List[Dict[str, Any]]):
        """恢复卡片的连接"""
        debug_print(f"  [UNDO] Starting connection restoration for card {card_id}")
        debug_print(f"  [UNDO] Current cards in workflow: {list(self.cards.keys())}")

        # 设置撤销操作标志，防止连接恢复过程中的操作触发新的撤销保存
        was_undoing = getattr(self, '_undoing_operation', False)
        self._undoing_operation = True
        debug_print("  [UNDO] Set undoing operation flag to True for connection restoration")

        restored_card = self.cards.get(card_id)
        if not restored_card:
            operation_logger.error("[撤回] 恢复连线失败，找不到卡片 card_id=%s", card_id)
            debug_print(f"  [撤销] 错误：无法恢复连线，未找到卡片 {card_id}")
            debug_print(f"  [UNDO] Available cards: {list(self.cards.keys())}")
            return

        debug_print(f"  [UNDO] Restoring {len(connections_data)} connections for card {card_id}")

        successful_restorations = 0
        failed_restorations = 0

        for i, conn_data in enumerate(connections_data):
            start_card_id = conn_data['start_card_id']
            end_card_id = conn_data['end_card_id']
            line_type = conn_data['line_type']

            debug_print(f"    [CONN {i+1}/{len(connections_data)}] Restoring: {start_card_id} -> {end_card_id} ({line_type})")

            start_card = self.cards.get(start_card_id)
            end_card = self.cards.get(end_card_id)

            if not start_card:
                debug_print(f"      错误：未找到起始卡片 {start_card_id}")
                failed_restorations += 1
                continue

            if not end_card:
                debug_print(f"      错误：未找到结束卡片 {end_card_id}")
                failed_restorations += 1
                continue

            # 检查连接是否已存在
            existing_conn = None
            for conn in self.connections:
                if (isinstance(conn, ConnectionLine) and
                    conn.start_item == start_card and
                    conn.end_item == end_card and
                    conn.line_type == line_type):
                    existing_conn = conn
                    break

            if existing_conn:
                debug_print("      Connection already exists, skipping")
                successful_restorations += 1
            else:
                new_conn = self.add_connection(start_card, end_card, line_type)
                if new_conn:
                    debug_print("      SUCCESS: Restored connection")
                    successful_restorations += 1
                else:
                    debug_print("      错误：创建连线失败")
                    failed_restorations += 1

        debug_print(f"  [UNDO] Connection restoration completed: {successful_restorations} success, {failed_restorations} failed")

        # 如果有连接恢复，触发更新
        if successful_restorations > 0:
            debug_print("  [UNDO] Triggering sequence update after connection restoration")
            self.update_card_sequence_display()

        # 恢复撤销操作标志状态
        self._undoing_operation = was_undoing
        debug_print(f"  [UNDO] Restored undoing operation flag to {was_undoing} after connection restoration")

    def _undo_delete_connection(self, operation_data: Dict[str, Any]):
        """撤销删除连接操作"""
        conn_data = operation_data.get('connection_data')
        if not conn_data:
            debug_print("  [UNDO] No connection data found for undo")
            return

        start_card_id = conn_data['start_card_id']
        end_card_id = conn_data['end_card_id']
        line_type = conn_data['line_type']

        start_card = self.cards.get(start_card_id)
        end_card = self.cards.get(end_card_id)

        if start_card and end_card:
            new_conn = self.add_connection(start_card, end_card, line_type)
            if new_conn:
                debug_print(f"  [UNDO] Restored connection: {start_card_id} -> {end_card_id} ({line_type})")
            else:
                debug_print(f"  [撤销] 恢复连线失败：{start_card_id} -> {end_card_id} ({line_type})")
        else:
            debug_print(f"  [UNDO] Cannot restore connection: missing cards {start_card_id} or {end_card_id}")

    def _undo_add_connection(self, operation_data: Dict[str, Any]):
        """撤销添加连接操作"""
        conn_data = operation_data.get('connection_data')
        if not conn_data:
            debug_print("  [UNDO] No connection data found for undo")
            return

        start_card_id = conn_data['start_card_id']
        end_card_id = conn_data['end_card_id']
        line_type = conn_data['line_type']

        debug_print(f"  [UNDO] Removing added connection: {start_card_id} -> {end_card_id} ({line_type})")

        # 查找并删除对应的连接
        connection_to_remove = None
        for conn in self.connections:
            if (hasattr(conn, 'start_item') and hasattr(conn, 'end_item') and
                conn.start_item and conn.end_item and
                conn.start_item.card_id == start_card_id and
                conn.end_item.card_id == end_card_id and
                conn.line_type == line_type):
                connection_to_remove = conn
                break

        if connection_to_remove:
            self.remove_connection(connection_to_remove)
            debug_print("  [UNDO] Added connection removed successfully")
        else:
            debug_print("  [撤销] 未找到要移除的连线")

    def _undo_modify_connection(self, operation_data: Dict[str, Any]):
        """撤销修改连接操作"""
        old_conn_data = operation_data.get('old_connection_data')
        new_conn_data = operation_data.get('new_connection_data')

        if not old_conn_data or not new_conn_data:
            debug_print("  [UNDO] Missing connection data for modify undo")
            return

        debug_print("  [UNDO] Undoing connection modification:")
        debug_print(f"    Removing new: {new_conn_data['start_card_id']} -> {new_conn_data['end_card_id']} ({new_conn_data['line_type']})")
        debug_print(f"    Restoring old: {old_conn_data['start_card_id']} -> {old_conn_data['end_card_id']} ({old_conn_data['line_type']})")

        # 1. 删除新连接
        new_connection_to_remove = None
        for conn in self.connections:
            if (hasattr(conn, 'start_item') and hasattr(conn, 'end_item') and
                conn.start_item and conn.end_item and
                conn.start_item.card_id == new_conn_data['start_card_id'] and
                conn.end_item.card_id == new_conn_data['end_card_id'] and
                conn.line_type == new_conn_data['line_type']):
                new_connection_to_remove = conn
                break

        if new_connection_to_remove:
            self.remove_connection(new_connection_to_remove)
            debug_print("  [UNDO] Removed new connection")
        else:
            debug_print("  [撤销] 未找到要移除的新连线")

        # 注释已清理（原注释编码损坏）
        old_start_card = self.cards.get(old_conn_data['start_card_id'])
        old_end_card = self.cards.get(old_conn_data['end_card_id'])

        if old_start_card and old_end_card:
            restored_conn = self.add_connection(old_start_card, old_end_card, old_conn_data['line_type'])
            if restored_conn:
                debug_print("  [UNDO] Successfully restored old connection")
            else:
                debug_print("  [撤销] 恢复旧连线失败")
        else:
            debug_print(f"  [UNDO] Cannot restore old connection: missing cards {old_conn_data['start_card_id']} or {old_conn_data['end_card_id']}")

    def _undo_add_card(self, operation_data: Dict[str, Any]):
        """撤销添加卡片操作"""
        card_data = operation_data.get('card_data')
        if not card_data:
            debug_print("  [UNDO] No card data found for undo")
            return

        card_id = card_data.get('card_id')
        if card_id in self.cards:
            self.delete_card(card_id)
            debug_print(f"  [UNDO] Removed added card: {card_id}")
        else:
            debug_print(f"  [撤销] 未找到要移除的卡片：{card_id}")

    def _undo_change_card_ids(self, operation_data: Dict[str, Any]):
        id_mapping = operation_data.get('id_mapping')
        if not isinstance(id_mapping, dict) or not id_mapping:
            raise TypeError("撤回卡片 ID 操作缺少有效映射")
        reverse_mapping = {new_id: old_id for old_id, new_id in id_mapping.items()}
        if len(reverse_mapping) != len(id_mapping):
            raise ValueError("撤回卡片 ID 映射存在目标冲突")
        self._apply_card_id_mapping(reverse_mapping)
