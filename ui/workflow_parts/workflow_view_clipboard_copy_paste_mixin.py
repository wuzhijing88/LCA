from .workflow_view_common import *


class WorkflowViewClipboardCopyPasteMixin:

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
            logger.info(f"已复制卡片 {card_id} ({card.task_type}) 的数据，包含备注: {card.custom_name}")
        else:
            logger.warning(f"尝试复制不存在的卡片 ID: {card_id}")

    def handle_copy_selected_cards(self):
        """复制当前选中的所有卡片"""
        if self._block_edit_if_running("复制选中卡片"):
            return

        selected_items = self.scene.selectedItems()
        selected_cards = [item for item in selected_items if isinstance(item, TaskCard)]
        selected_cards.sort(key=lambda card: card.card_id)

        if not selected_cards:
            logger.warning("没有选中的卡片可以复制")
            return

        # 注释已清理（原注释编码损坏）
        if len(selected_cards) == 1:
            single_card = selected_cards[0]
            self.handle_copy_card(single_card.card_id, single_card.parameters)
            logger.info(f"已按单卡模式复制卡片 {single_card.card_id}")
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

        logger.info(f"已复制 {len(selected_cards)} 个卡片和 {len(connections_data)} 条连接到剪贴板")

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
            debug_print(f"--- [DEBUG] WorkflowView: handle_paste_card END (No data) ---")
            return

        # 注释已清理（原注释编码损坏）
        is_single_card = type(self).copied_card_data.get('single_card', True)

        if is_single_card:
            # 单卡片粘贴（保持原有逻辑）
            self._paste_single_card(scene_pos)
        else:
            # 批量卡片粘贴
            self._paste_multiple_cards(scene_pos)

        debug_print(f"--- [DEBUG] WorkflowView: handle_paste_card END ---")

    def _paste_single_card(self, scene_pos: QPointF):
        """粘贴单个卡片"""
        # Extract data from clipboard
        task_type = type(self).copied_card_data.get('task_type')
        parameters_to_paste = type(self).copied_card_data.get('parameters', {})

        if not task_type or not self.task_modules.get(task_type):
            debug_print(f"  [调试] 粘贴失败：剪贴板数据中的任务类型无效 '{task_type}'。")
            QMessageBox.critical(self, "粘贴失败", f"剪贴板中的卡片类型 '{task_type}' 无效。")
            type(self).copied_card_data = None # Clear invalid data
            return

        debug_print(f"  [DEBUG] Pasting single card: Type='{task_type}', Params={parameters_to_paste}")

        # 设置粘贴标志，防止add_task_card保存撤销状态
        self._pasting_card = True
        # Add the new card at the specified position
        new_card = self.add_task_card(scene_pos.x(), scene_pos.y(), task_type, card_id=None)
        # 重置粘贴标志
        self._pasting_card = False

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

            # Trigger update after pasting
            affected_container_ids = set()
            target_container = self._find_drop_container_for_card(new_card)
            if target_container:
                if new_card.container_id != target_container.card_id:
                    if new_card.container_id is not None:
                        old_container_id = self._remove_card_from_container(new_card)
                        if old_container_id is not None:
                            affected_container_ids.add(old_container_id)
                    self._assign_card_to_container(new_card, target_container)
                affected_container_ids.add(target_container.card_id)
            else:
                if new_card.container_id is not None:
                    old_container_id = self._remove_card_from_container(new_card)
                    if old_container_id is not None:
                        affected_container_ids.add(old_container_id)

            for container_id in affected_container_ids:
                container = self.cards.get(container_id)
                if container and getattr(container, "is_container_card", False):
                    self._layout_container_children(container)

            self.update_card_sequence_display()
            if self._is_start_task_type(new_card.task_type):
                self._refresh_thread_start_custom_names()
            debug_print(f"  Single card pasted successfully.")
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

        debug_print(f"  [DEBUG] Pasting {len(cards_data)} cards and {len(connections_data)} connections...")

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
                failed_count += 1
                continue

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
                failed_count += 1
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
                        debug_print(f"  [调试] 创建连线失败：{new_start_card.card_id} -> {new_end_card.card_id} ({line_type})")
                else:
                    debug_print(f"  [DEBUG] Skipping connection - missing cards or type: old_start={old_start_id}, old_end={old_end_id}")

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

        debug_print(f"  [DEBUG] Multiple cards paste completed: {success_count} cards, {connection_count} connections, {failed_count} failed")

    def copy_selected_card(self):
        """复制当前选中的卡片到剪贴板（不自动粘贴）。"""
        # 检查是否正在运行，如果是则阻止复制
        if self._block_edit_if_running("复制选中卡片"):
            return
        self.handle_copy_selected_cards()
