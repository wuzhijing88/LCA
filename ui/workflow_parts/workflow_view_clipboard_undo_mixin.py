from .workflow_view_common import *
from weakref import ReferenceType, ref

from task_workflow.thread_start import validate_thread_target

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
            self._connection_controller.assert_registered(connection)
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
            if not self._loading_workflow:
                self.reroute_connections()
            self.viewport().update()

        return deleted_count

    def handle_copy_card(self, card_id: int, parameters: dict):
        """复制单张卡片的数据。"""
        card = self.cards.get(card_id)
        if card:
            if not isinstance(parameters, dict):
                raise TypeError("复制卡片参数必须是字典")
            safe_parameters = copy.deepcopy(parameters)
            type(self).copied_card_data = {
                'single_card': True,  # 标记为单卡片复制
                'source_images_dir': self.images_dir,
                'source_view': ref(self),
                'original_card_id': card.card_id,
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
            'source_images_dir': self.images_dir,
            'source_view': ref(self),
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

        from task_workflow.clipboard_resources import pasted_image_resources

        clipboard = type(self).copied_card_data
        old_ids = set(self.cards)
        old_undo_stack = list(self.undo_stack)
        try:
            if not isinstance(clipboard, dict) or not {'single_card', 'source_images_dir'} <= clipboard.keys():
                raise ValueError("剪贴板缺少卡片复制模式或来源图片目录，请重新复制卡片")
            if 'source_view' not in clipboard or not isinstance(clipboard['source_view'], ReferenceType):
                raise ValueError("剪贴板缺少来源画布身份，请重新复制卡片")
            same_source = clipboard['source_view']() is self
            is_single_card = clipboard['single_card']
            if not isinstance(is_single_card, bool):
                raise TypeError("剪贴板卡片复制模式必须是布尔值")
            required = {'task_type', 'parameters', 'custom_name', 'original_card_id'} if is_single_card else {'cards', 'connections'}
            if not required <= clipboard.keys():
                raise ValueError("剪贴板卡片数据不完整，请重新复制卡片")
            cards = [clipboard] if is_single_card else clipboard['cards']
            if not isinstance(cards, list) or any(
                not isinstance(item, dict) or not {'task_type', 'parameters', 'custom_name'} <= item.keys()
                for item in cards
            ):
                raise ValueError("剪贴板卡片数据格式无效，请重新复制卡片")
            with pasted_image_resources(
                cards, source_images_dir=clipboard['source_images_dir'], images_dir=self.images_dir,
            ) as prepared_cards:
                if is_single_card:
                    self._paste_single_card(scene_pos, prepared_cards[0], same_source, old_ids)
                else:
                    self._paste_multiple_cards(scene_pos, prepared_cards, clipboard['connections'], same_source, old_ids)
            return True
        except Exception as exc:
            was_undoing = self._undoing_operation
            self._undoing_operation = True
            try:
                for card_id in sorted(set(self.cards) - old_ids, reverse=True):
                    if not self.delete_card(card_id, defer_view_refresh=True):
                        raise RuntimeError(f"粘贴失败后无法释放卡片：{card_id}") from exc
                self.undo_stack[:] = old_undo_stack
                self.update_card_sequence_display()
                self._refresh_thread_start_custom_names()
                self._sync_scene_rect_to_content()
            finally:
                self._undoing_operation = was_undoing
            operation_logger.error("[粘贴] 失败：%s", exc, exc_info=True)
            QMessageBox.critical(self, "粘贴失败", str(exc) or f"具体原因未知（{type(exc).__name__}）")
            return False
        finally:
            self._pasting_card = False

    def _paste_single_card(self, scene_pos: QPointF, card_data: dict, same_source: bool, existing_ids: set):
        """粘贴单个卡片"""
        # Extract data from clipboard
        task_type = card_data['task_type']
        parameters_to_paste = card_data['parameters']
        original_card_id = card_data['original_card_id']
        if type(original_card_id) is not int or original_card_id < 0:
            raise TypeError("剪贴板卡片原始 ID 必须是非负整数")

        if not task_type or not self.task_modules.get(task_type):
            debug_print(f"  [调试] 粘贴失败：剪贴板数据中的任务类型无效 '{task_type}'。")
            raise ValueError(f"剪贴板中的卡片类型 '{task_type}' 无效。")

        debug_print(f"  [DEBUG] Pasting single card: Type='{task_type}', Params={parameters_to_paste}")

        # 设置粘贴标志，防止add_task_card保存撤销状态
        self._pasting_card = True
        # Add the new card at the specified position
        try:
            new_card = self.add_task_card(scene_pos.x(), scene_pos.y(), task_type, card_id=None, parameters=copy.deepcopy(parameters_to_paste))
        finally:
            self._pasting_card = False
        # 重置粘贴标志

        if new_card:
            debug_print(f"  [DEBUG] New card created with ID: {new_card.card_id}")
            # Apply the copied parameters to the new card
            new_card.parameters.update(copy.deepcopy(parameters_to_paste))
            self._remap_pasted_card_parameters(
                new_card, {original_card_id: new_card}, same_source, existing_ids, set(),
            )
            debug_print(f"  [DEBUG] Copied parameters applied to new card {new_card.card_id}: {new_card.parameters}")

            # Apply the copied custom name (备注)
            custom_name = card_data['custom_name']
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
            raise RuntimeError("创建新卡片时发生错误。")

    def _remap_pasted_card_parameters(self, card: TaskCard, mapping: Dict[int, TaskCard],
                                      same_source: bool, existing_ids: set, random_targets: set):
        """漏选分支跳转目标时初始化该分支；其他显式引用仍严格校验。"""
        updated = copy.deepcopy(card.parameters)

        def remap_target(target_id, parameter_name, active=True):
            if type(target_id) is not int or target_id < 0:
                raise TypeError(f"卡片 {card.card_id} 的引用参数 {parameter_name} 必须是非负整数或 None")
            if target_id in mapping:
                return mapping[target_id].card_id
            if same_source and target_id in existing_ids:
                return target_id
            if not active:
                return None
            raise ValueError(
                f"卡片 {card.card_id} 的引用参数 {parameter_name} 指向未复制的卡片 {target_id}。\n"
                f"请将目标卡片 {target_id} 一起复制，或在来源卡片中明确修改该引用后重新复制。"
            )

        # 复制边界内没有对应目标的成功／失败跳转，按粘贴规则初始化。
        # 这是显式编辑操作，不在保存或执行时为无效引用兜底。
        for branch in ('success', 'failure'):
            action_name = 'on_' + branch
            target_name = branch + '_jump_target_id'
            if updated.get(action_name) != '跳转到步骤':
                continue
            target_id = updated.get(target_name)
            if target_id is not None and (type(target_id) is not int or target_id < 0):
                raise TypeError(f"卡片 {card.card_id} 的引用参数 {target_name} 必须是非负整数或 None")
            if target_id not in mapping:
                updated[target_name] = None
                updated[action_name] = '执行下一步'

        for name in self._reference_parameter_names(card):
            if name in updated and updated[name] is not None:
                updated[name] = remap_target(updated[name], name, self._reference_is_active(card, name))

        for name, definition in card.param_definitions.items():
            if definition.get('widget_hint') != 'thread_target_selector' or name not in updated:
                continue
            value = updated[name]
            validate_thread_target(value)
            if isinstance(value, str) and value in {'当前线程', '全部线程'}:
                continue
            values = value if isinstance(value, list) else [value]
            targets = []
            for raw_target in values:
                target_id = remap_target(int(raw_target), name)
                target = self.cards[target_id]
                if not self._is_start_task_type(target.task_type):
                    raise ValueError(f"卡片 {card.card_id} 的目标线程 {raw_target} 不是线程起点")
                targets.append(str(target_id))
            updated[name] = targets if isinstance(value, list) else targets[0]

        weights = updated.get('random_weights')
        if weights is not None:
            if not isinstance(weights, dict):
                raise TypeError("随机跳转权重必须是字典")
            mapped_weights = {}
            for key, weight in weights.items():
                if not isinstance(key, str) or not key.isascii() or not key.isdecimal() or str(int(key)) != key:
                    raise TypeError("随机跳转目标 ID 必须是非负整数的数字字符串")
                if type(weight) is not int or weight <= 0:
                    raise TypeError("随机跳转权重必须是正整数")
                if int(key) in random_targets:
                    mapped_weights[str(mapping[int(key)].card_id)] = weight
            updated['random_weights'] = mapped_weights
        connections = updated.get('_random_connections')
        if connections is not None:
            if not isinstance(connections, list):
                raise TypeError("随机跳转目标清单必须是列表")
            mapped_connections = []
            for item in connections:
                if not isinstance(item, dict) or type(item.get('card_id')) is not int or item['card_id'] < 0:
                    raise TypeError("随机跳转目标项必须包含非负整数 card_id")
                if item['card_id'] in random_targets:
                    mapped_connections.append({**item, 'card_id': mapping[item['card_id']].card_id})
            updated['_random_connections'] = mapped_connections
        card.parameters = updated
        card.update()

    def _paste_multiple_cards(self, scene_pos: QPointF, cards_data: list, connections_data: list,
                              same_source: bool, existing_ids: set):
        """粘贴多个卡片"""

        if not cards_data:
            raise ValueError("剪贴板中没有有效的卡片数据。")

        original_ids = set()
        for index, card_data in enumerate(cards_data):
            if not isinstance(card_data, dict):
                raise TypeError(f"剪贴板卡片数据第 {index + 1} 项必须是字典")
            task_type = card_data.get('task_type')
            original_card_id = card_data.get('original_card_id')
            original_pos = card_data.get('original_pos')
            if not isinstance(task_type, str) or task_type not in self.task_modules:
                raise ValueError(f"剪贴板包含无效任务类型: {task_type!r}")
            if type(original_card_id) is not int or original_card_id < 0:
                raise TypeError("剪贴板卡片原始 ID 必须是非负整数")
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
            if line_type not in PORT_TYPES:
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
            parameters = card_data['parameters']
            custom_name = card_data.get('custom_name')
            original_pos = card_data['original_pos']
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
            new_card = self.add_task_card(new_x, new_y, task_type, card_id=None, parameters=copy.deepcopy(parameters))

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

        # 注意：不在这里重置 _pasting_card 标志，等连接重建完成后再重置
        # 这样可以防止重建连接时保存单独的撤销状态

        # 参数先按来源 ID 映射一次；重建连线随后写入新端点 ID，禁止二次映射。
        for card_data, new_card in zip(cards_data, new_cards):
            random_targets = {item['end_card_id'] for item in connections_data
                              if item['start_card_id'] == card_data['original_card_id']
                              and item['line_type'] == 'random'}
            self._remap_pasted_card_parameters(
                new_card, old_to_new_card_map, same_source, existing_ids, random_targets,
            )

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
        'switch_output_connections': {'connection_data', 'connection_added',
                                     'removed_connections', 'branch_parameters'},
        'add_card': {'card_data'},
        'change_card_ids': {'id_mapping'},
        'replace_workflow': {'workflow_data'},
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
            elif operation_type == 'switch_output_connections':
                self._connection_controller.restore_output_connections(operation_data)
            elif operation_type == 'add_card':
                self._undo_add_card(operation_data)
            elif operation_type == 'change_card_ids':
                self._undo_change_card_ids(operation_data)
            elif operation_type == 'replace_workflow':
                self._undo_replace_workflow(operation_data)
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
        """撤销粘贴时走完整卡片、连线及主题资源卸载。图片属于工程资源，予以保留。"""
        for card_id in reversed(operation_data['pasted_card_ids']):
            if card_id in self.cards:
                if not self.delete_card(card_id, defer_view_refresh=True):
                    raise RuntimeError(f"撤销粘贴时无法释放卡片：{card_id}")
        self._refresh_thread_start_custom_names()
        self._sync_scene_rect_to_content()

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
        self._restore_card_connections(card_id, connections_data)

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
        """在同一次撤回事务中恢复连线，失败时也恢复撤销标记。"""
        if card_id not in self.cards:
            raise RuntimeError(f"恢复连线失败，找不到卡片：{card_id}")
        was_undoing = self._undoing_operation
        self._undoing_operation = True
        try:
            for conn_data in connections_data:
                start_card_id = conn_data['start_card_id']
                end_card_id = conn_data['end_card_id']
                line_type = conn_data['line_type']
                start_card = self.cards.get(start_card_id)
                end_card = self.cards.get(end_card_id)
                if start_card is None or end_card is None:
                    raise RuntimeError(f"恢复连线失败，缺少端点：{start_card_id} -> {end_card_id}")
                if any(conn.start_item is start_card and conn.end_item is end_card
                       and conn.line_type == line_type for conn in self.connections):
                    continue
                if self.add_connection(start_card, end_card, line_type) is None:
                    raise RuntimeError(f"恢复连线失败：{start_card_id} -> {end_card_id}")
            if connections_data:
                self.update_card_sequence_display()
        finally:
            self._undoing_operation = was_undoing

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

    def _undo_replace_workflow(self, operation_data: Dict[str, Any]):
        workflow_data = operation_data.get("workflow_data")
        if not isinstance(workflow_data, dict):
            raise TypeError("撤回工作流数据必须是字典")
        self.load_workflow(workflow_data)
