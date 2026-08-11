from .workflow_view_common import *


class WorkflowViewConnectionCoreMixin:

    def add_connection(self, start_card: TaskCard, end_card: TaskCard, line_type: str, skip_duplicate_check: bool = False):
        """Adds a connection line between two cards.

        Args:
            skip_duplicate_check: 【性能优化】跳过重复检查和场景验证，用于批量载入时提高性能
        """
        # 检查是否正在运行，如果是则阻止添加连接
        if self._block_edit_if_running("添加连接"):
            return None

        # 注释已清理（原注释编码损坏）
        debug_print(f"    [ADD_CONN_DEBUG] Validating connection: Start={start_card.card_id if start_card else 'None'}, End={end_card.card_id if end_card else 'None'}, Type='{line_type}'")

        # 验证卡片对象有效性
        if not start_card or not end_card:
            debug_print("错误：无法连接无效的卡片对象")
            return None

        # 验证卡片是否在字典中
        if start_card.card_id not in self.cards:
            debug_print(f"错误：起始卡片 ID {start_card.card_id} 不在当前工作流中")
            return None

        if end_card.card_id not in self.cards:
            debug_print(f"错误：目标卡片 ID {end_card.card_id} 不在当前工作流中")
            return None

        # 注释已清理（原注释编码损坏）
        if not skip_duplicate_check:
            # 验证卡片是否在场景中
            if start_card.scene() != self.scene:
                debug_print(f"错误：起始卡片 ID {start_card.card_id} 不在当前场景中")
                return None

            if end_card.scene() != self.scene:
                debug_print(f"错误：目标卡片 ID {end_card.card_id} 不在当前场景中")
                return None

        # 注释已清理（原注释编码损坏）
        if (hasattr(start_card, 'restricted_outputs') and start_card.restricted_outputs and
            line_type in ['success', 'failure']):
            debug_print(f"错误：起始卡片 ID {start_card.card_id} 的 {line_type} 输出端口被限制")
            return None

        # 注释已清理（原注释编码损坏）
        if hasattr(end_card, 'no_input_ports') and end_card.no_input_ports:
            debug_print(f"错误：目标卡片 ID {end_card.card_id} ({end_card.task_type}) 没有输入端口，不允许连接")
            return None

        special_rule_error = self._validate_special_connection_rule(start_card, end_card, line_type)
        if special_rule_error:
            debug_print(f"错误：{special_rule_error}")
            logger.warning(
                "连接校验失败: %s -> %s (%s), 原因: %s",
                getattr(start_card, 'card_id', None),
                getattr(end_card, 'card_id', None),
                line_type,
                special_rule_error,
            )
            return None

        # 注释已清理（原注释编码损坏）
        old_connection_for_modify = None
        if not skip_duplicate_check:
            # --- ADDED: Check for connections in card connection lists ---
            debug_print(f"  [CONN_DEBUG] Checking for existing connections in card lists...")

            # Check start card's connections
            if hasattr(start_card, 'connections'):
                for card_conn in start_card.connections:
                    if (hasattr(card_conn, 'start_item') and hasattr(card_conn, 'end_item') and hasattr(card_conn, 'line_type') and
                        card_conn.start_item == start_card and card_conn.end_item == end_card and card_conn.line_type == line_type):
                        debug_print(f"  [CONN_DEBUG] Found connection in start card's list: {start_card.card_id} -> {end_card.card_id} ({line_type})")
                        debug_print(f"  [CONN_DEBUG] Connection in view list: {card_conn in self.connections}")
                        if card_conn not in self.connections:
                            debug_print(f"  [CONN_DEBUG] Connection not in view list, adding it for proper handling")
                            self.connections.append(card_conn)

            # Check end card's connections
            if hasattr(end_card, 'connections'):
                for card_conn in end_card.connections:
                    if (hasattr(card_conn, 'start_item') and hasattr(card_conn, 'end_item') and hasattr(card_conn, 'line_type') and
                        card_conn.start_item == start_card and card_conn.end_item == end_card and card_conn.line_type == line_type):
                        debug_print(f"  [CONN_DEBUG] Found connection in end card's list: {start_card.card_id} -> {end_card.card_id} ({line_type})")
                        debug_print(f"  [CONN_DEBUG] Connection in view list: {card_conn in self.connections}")
                        if card_conn not in self.connections:
                            debug_print(f"  [CONN_DEBUG] Connection not in view list, adding it for proper handling")
                            self.connections.append(card_conn)
            # --- END ADDED ---

            # 首先检查起始端口是否已有连接（一个端口只能有一个输出连接）
            # 特例：只有随机跳转卡片的 random 端口允许多个输出连接
            debug_print(f"  [PORT_CHECK] Checking if start port {line_type} on card {start_card.card_id} already has a connection...")
            existing_output_connection = None

            # 注释已清理（原注释编码损坏）
            is_random_jump_random_port = (line_type == 'random' and
                                          hasattr(start_card, 'task_type') and
                                          start_card.task_type == '随机跳转')
            if not is_random_jump_random_port:
                for existing_conn in self.connections:
                    if (isinstance(existing_conn, ConnectionLine) and
                        existing_conn.start_item == start_card and
                        existing_conn.line_type == line_type):
                        existing_output_connection = existing_conn
                        debug_print(f"    Found existing output connection: {start_card.card_id} -> {existing_conn.end_item.card_id if existing_conn.end_item else 'None'} ({line_type})")
                        break
            else:
                debug_print("    [RANDOM_PORT] random port allows multiple output connections; skipping existing-connection check")

            # 注释已清理（原注释编码损坏）
            if existing_output_connection:
                debug_print(f"  [MODIFY_CONN_DEBUG] Detected existing connection, this is a MODIFY operation")
                debug_print(f"  [MODIFY_CONN_DEBUG] Old connection: {existing_output_connection.start_item.card_id if existing_output_connection.start_item else 'None'} -> {existing_output_connection.end_item.card_id if existing_output_connection.end_item else 'None'} ({existing_output_connection.line_type if hasattr(existing_output_connection, 'line_type') else 'unknown'})")
                debug_print(f"  [MODIFY_CONN_DEBUG] New connection will be: {start_card.card_id} -> {end_card.card_id} ({line_type})")
                # 保存鏃ц繛鎺ヤ俊鎭敤浜庝慨鏀硅繛鎺ョ殑撤销
                old_connection_for_modify = existing_output_connection
                # 注释已清理（原注释编码损坏）
                self._modifying_connection = True
                debug_print(f"  [MODIFY_CONN_DEBUG] Set _modifying_connection = True")
                self.remove_connection(existing_output_connection)
                debug_print(f"  [MODIFY_CONN_DEBUG] Old connection removed")
                # 注意：不在这里重置 _modifying_connection，要等到新连接添加完成后

            # 验证是否已存在相同连接
            debug_print(f"  [DUPLICATE_CHECK] Checking {len(self.connections)} connections in view list...")
            for i, existing_conn in enumerate(self.connections):
                debug_print(f"    Connection {i+1}: {existing_conn.start_item.card_id if hasattr(existing_conn, 'start_item') and existing_conn.start_item else 'N/A'} -> {existing_conn.end_item.card_id if hasattr(existing_conn, 'end_item') and existing_conn.end_item else 'N/A'} ({existing_conn.line_type if hasattr(existing_conn, 'line_type') else 'N/A'})")

                if (isinstance(existing_conn, ConnectionLine) and
                    existing_conn.start_item == start_card and
                    existing_conn.end_item == end_card and
                    existing_conn.line_type == line_type):
                    # --- ADDED: Enhanced duplicate connection debugging and validation ---
                    in_scene = existing_conn.scene() == self.scene
                    path_empty = existing_conn.path().isEmpty() if hasattr(existing_conn, 'path') else True
                    debug_print(f"警告：相同类型的连接已存在 ({start_card.card_id} -> {end_card.card_id}, {line_type})")
                    debug_print(f"  现有连接状态: 在场景中={in_scene}, 路径为空={path_empty}")
                    debug_print(f"  连接对象: {existing_conn}")

                    # --- ADDED: Enhanced connection validity check ---
                    # 检查连接是否真的可见（除了路径检查，还要检查端口限制）
                    start_restricted = (hasattr(existing_conn.start_item, 'restricted_outputs') and
                                      existing_conn.start_item.restricted_outputs and
                                      existing_conn.line_type in ['success', 'failure'])

                    debug_print(f"  连接有效性检查: 在场景中={in_scene}, 路径为空={path_empty}, 起始端口限制={start_restricted}")

                    # 如果现有连接无效，则移除它并创建新连接
                    if not in_scene or path_empty or start_restricted:
                        debug_print("  Existing connection invalid; removing and recreating")
                        self._force_remove_connection(existing_conn)
                        # --- ADDED: Also clean up any other connections of the same type between these cards ---
                        self._cleanup_duplicate_connections(start_card, end_card, line_type)
                        # --- END ADDED ---
                        break  # 跳出循环，继续创建新连接
                    else:
                        debug_print(f"  现有连接有效，但强制更新路径")
                        # 注释已清理（原注释编码损坏）
                        existing_conn.update_path()
                        return existing_conn
                    # --- END ADDED ---
                    # --- END ADDED ---

            debug_print(f"    [ADD_CONN_DEBUG] Validation passed. Creating ConnectionLine...")
            # <<< END ENHANCED >>>

            # --- ADDED: Force cleanup any remaining duplicate connections before creating new one ---
            debug_print(f"    [ADD_CONN_DEBUG] Force cleaning up any remaining duplicate connections...")
            self._cleanup_duplicate_connections(start_card, end_card, line_type)
            # --- END ADDED ---

        # --- ADDED: Detailed logging for connection creation ---
        debug_print(f"    [ADD_CONN_DEBUG] Attempting to create ConnectionLine: Start={start_card.card_id}, End={end_card.card_id}, Type='{line_type}'")
        try:
            connection = ConnectionLine(start_card, end_card, line_type)
            debug_print(f"      [ADD_CONN_DEBUG] ConnectionLine object created: {connection}")
        except Exception as e:
            debug_print(f"      [添加连线错误] 创建 ConnectionLine 对象失败：{e}")
            logger.exception(f"创建连接对象失败: {e}")
            return None
        
        debug_print(f"      [ADD_CONN_DEBUG] Attempting self.scene.addItem({connection})")
        try:
            self.scene.addItem(connection)
            try:
                from ..workflow_parts.connection_line import ensure_line_animation_registered
                ensure_line_animation_registered(connection)
            except Exception:
                pass
            # Verify if item is in scene
            is_in_scene = connection.scene() == self.scene
            debug_print(f"      [ADD_CONN_DEBUG] self.scene.addItem finished. Item in scene? {is_in_scene}")
            if not is_in_scene:
                 debug_print(f"      [ADD_CONN_WARN] Item {connection} was NOT added to the scene successfully!")
                 # <<< ENHANCED: 创建失败时的清理 >>>
                 if hasattr(connection, 'start_item'):
                     connection.start_item = None
                 if hasattr(connection, 'end_item'):
                     connection.end_item = None
                 # ConnectionLine继承自QGraphicsPathItem，不是QObject，所以没有deleteLater()
                 # 注释已清理（原注释编码损坏）
                 del connection
                 return None
                 # <<< END ENHANCED >>>
        except Exception as e:
            debug_print(f"      [添加连线错误] self.scene.addItem 执行失败：{e}")
            logger.exception(f"连接加入场景失败: {e}")
            # Attempt cleanup if possible
            if connection in self.connections: 
                self.connections.remove(connection)
            # <<< ENHANCED: 更彻底的清理 >>>
            if hasattr(connection, 'start_item'):
                connection.start_item = None
            if hasattr(connection, 'end_item'):
                connection.end_item = None
            # ConnectionLine继承自QGraphicsPathItem，不是QObject，所以没有deleteLater()
            # 注释已清理（原注释编码损坏）
            del connection
            # <<< END ENHANCED >>>
            return None
        # --------------------------------------------------------

        # Register the connection with both cards (assuming add_connection still exists)
        if hasattr(start_card, 'add_connection'):
            start_card.add_connection(connection)
            debug_print(f"      [ADD_CONN_DEBUG] Added to start card connections list. Count: {len(start_card.connections)}")
        if hasattr(end_card, 'add_connection'):
            end_card.add_connection(connection)
            debug_print(f"      [ADD_CONN_DEBUG] Added to end card connections list. Count: {len(end_card.connections)}")
        
        # --- ADDED: Add connection to view's tracking list --- 
        self.connections.append(connection)
        debug_print(f"      [ADD_CONN_DEBUG] Added to view connections list. Total count: {len(self.connections)}")
        # -----------------------------------------------------
        
        # <<< ENHANCED: 发出连接添加信号 >>>
        self.connection_added.emit(start_card, end_card, line_type)
        debug_print(f"      [ADD_CONN_DEBUG] Connection added signal emitted")
        # <<< END ENHANCED >>>
        
        # --- REMOVED: No longer update sequence or path here. Done by final update in load/other actions ---
        # if line_type == 'sequential':
        #     debug_print("  [CONN_DEBUG] Sequential connection added, triggering sequence update.")
        #     self.update_card_sequence_display() # <<< REMOVED
        # else:
        #     # For jump lines, just ensure they are visually updated if needed (already handled by update_card_sequence_display called elsewhere)
        #     connection.update_path() # Was: connection.update_positions() # <<< REMOVED
        # --- END REMOVAL ---

        # --- ADDED: Update card parameters when connection is created ---
        self._update_card_parameters_on_connection_create(start_card, end_card, line_type)
        # --- END ADDED ---

        # 保存连接状态用于撤销（除非正在加载工作流、更新序列显示、执行撤销操作或修改连线）
        debug_print(f"  [UNDO_SAVE_DEBUG] Checking undo save conditions:")
        debug_print(f"    _loading_workflow: {self._loading_workflow}")
        debug_print(f"    _updating_sequence: {self._updating_sequence}")
        debug_print(f"    _undoing_operation: {self._undoing_operation}")
        debug_print(f"    _modifying_connection: {getattr(self, '_modifying_connection', False)}")
        debug_print(f"    _pasting_card: {getattr(self, '_pasting_card', False)}")
        debug_print(f"    old_connection_for_modify: {old_connection_for_modify is not None}")

        if (not self._loading_workflow and not self._updating_sequence and not self._undoing_operation and
            not getattr(self, '_modifying_connection', False) and not getattr(self, '_pasting_card', False)):
            # 这是纯添加新连接操作，保存添加连接的撤销状态
            debug_print(f"  [UNDO_SAVE_DEBUG] PURE ADD: Saving add_connection undo state")
            self._save_add_connection_state_for_undo(start_card, end_card, line_type)
        elif old_connection_for_modify and not self._loading_workflow and not self._updating_sequence and not self._undoing_operation:
            # 这是修改连接操作，保存修改连接的撤销状态
            debug_print(f"  [UNDO_SAVE_DEBUG] MODIFY: Saving modify_connection undo state")
            self._save_modify_connection_state_for_undo(old_connection_for_modify, start_card, end_card, line_type)
            # 重置修改连线标志
            self._modifying_connection = False
            debug_print(f"  [UNDO_SAVE_DEBUG] MODIFY: Reset _modifying_connection flag")
        else:
            debug_print(f"  [UNDO_SAVE_DEBUG] SKIPPING undo save due to conditions:")
            if self._loading_workflow:
                debug_print(f"    - loading workflow")
            if self._updating_sequence:
                debug_print(f"    - updating sequence")
            if self._undoing_operation:
                debug_print(f"    - undoing operation")
            if getattr(self, '_modifying_connection', False):
                debug_print(f"    - modifying connection")
                # 如果是修改连线但在其他条件下跳过，也要重置标志
                if old_connection_for_modify:
                    self._modifying_connection = False
                    debug_print(f"    - reset _modifying_connection flag")
            if getattr(self, '_pasting_card', False):
                debug_print(f"    - pasting card")

        debug_print(f"      [ADD_CONN_DEBUG] Connection creation completed successfully")
        return connection

    def _clear_jump_parameters_for_connection(self, connection):
        """
        清除连线对应的跳转参数
        在删除或重连连线前，清理对应跳转参数，避免保留失效引用。
        """
        logger.warning(f"[参数清理] _clear_jump_parameters_for_connection 被调用")

        # 注释已清理（原注释编码损坏）
        # 因为修改连线时会先删除旧连线再创建新连线，参数应该由新连线设置
        if getattr(self, '_modifying_connection', False):
            logger.warning(f"[参数清理] 正在修改连线，跳过参数清理")
            return

        logger.warning(f"[参数清理] connection = {connection}")
        logger.warning(f"[参数清理] type(connection) = {type(connection)}")

        if not isinstance(connection, ConnectionLine):
            logger.warning(f"[参数清理] 不是ConnectionLine实例，退出")
            return

        logger.warning(f"[参数清理] 检查 start_item 属性")
        if not hasattr(connection, 'start_item'):
            logger.warning(f"[参数清理] 没有 start_item 属性，退出")
            return

        logger.warning(f"[参数清理] start_item = {connection.start_item}")
        logger.warning(f"[参数清理] type(start_item) = {type(connection.start_item)}")

        if not isinstance(connection.start_item, TaskCard):
            logger.warning(f"[参数清理] start_item 不是 TaskCard 实例，退出")
            return

        if not hasattr(connection.start_item, 'parameters'):
            logger.warning(f"[参数清理] start_item 没有 parameters 属性，退出")
            return

        start_card = connection.start_item
        logger.warning(f"[参数清理] start_card.card_id = {start_card.card_id}")

        line_type = getattr(connection, 'line_type', None)
        logger.warning(f"[参数清理] line_type = {line_type}")

        if not line_type:
            logger.warning(f"[参数清理] line_type 为空，退出")
            return

        # 注释已清理（原注释编码损坏）
        if hasattr(connection, 'end_item'):
            logger.warning(f"[参数清理] end_item = {connection.end_item}")
            if hasattr(connection.end_item, 'card_id'):
                logger.warning(f"[参数清理] end_item.card_id = {connection.end_item.card_id}")

        logger.info(f"[参数清理] 开始清理连线参数: 卡片{start_card.card_id}, 类型{line_type}")

        param_to_clear = None
        if line_type == ConnectionType.SUCCESS.value:
            param_to_clear = 'success_jump_target_id'
            logger.warning(f"[参数清理] 成功连线，将清除参数: {param_to_clear}")
        elif line_type == ConnectionType.FAILURE.value:
            param_to_clear = 'failure_jump_target_id'
            logger.warning(f"[参数清理] 失败连线，将清除参数: {param_to_clear}")

        logger.warning(f"[参数清理] param_to_clear = {param_to_clear}")
        logger.warning(f"[参数清理] start_card.parameters = {start_card.parameters}")

        # 注释已清理（原注释编码损坏）
        if line_type == 'random' and start_card.task_type == '随机跳转':
            logger.warning(f"[参数清理] 随机跳转连线被删除，刷新参数面板")
            from tasks.random_jump import prune_branch_weights

            valid_target_ids = []
            for conn in self.connections:
                if conn == connection:
                    continue
                if (hasattr(conn, 'start_item') and hasattr(conn, 'end_item') and
                    hasattr(conn, 'line_type') and conn.start_item and
                    conn.start_item.card_id == start_card.card_id and
                    conn.line_type == 'random' and conn.end_item):
                    valid_target_ids.append(conn.end_item.card_id)

            start_card.parameters['random_weights'] = prune_branch_weights(
                start_card.parameters.get('random_weights'),
                valid_target_ids,
            )

            # 刷新参数面板以更新随机跳转目标列表
            if hasattr(self, 'main_window') and self.main_window:
                if hasattr(self.main_window, 'parameter_panel') and self.main_window.parameter_panel:
                    panel = self.main_window.parameter_panel
                    if panel.is_panel_open() and panel.current_card_id == start_card.card_id:
                        logger.info(f"[参数清理] 刷新随机跳转参数面板，卡片 {start_card.card_id}")
                        workflow_info = {}
                        for seq_id, card_obj in enumerate(self.cards.values()):
                            workflow_info[seq_id] = (card_obj.task_type, card_obj.card_id)

                        # 收集剩余的随机跳转连接（排除当前正在删除的连接）
                        random_jump_connections = []
                        for conn in self.connections:
                            if conn == connection:
                                continue  # 跳过当前正在删除的连接
                            if (hasattr(conn, 'start_item') and hasattr(conn, 'end_item') and
                                hasattr(conn, 'line_type') and conn.start_item and
                                conn.start_item.card_id == start_card.card_id and
                                conn.line_type == 'random'):
                                target_card = conn.end_item
                                if target_card:
                                    random_jump_connections.append({
                                        'card_id': target_card.card_id,
                                        'task_type': target_card.task_type
                                    })

                        updated_parameters = start_card.parameters.copy()
                        updated_parameters['_random_connections'] = random_jump_connections
                        logger.info(f"[参数清理] 更新后的随机跳转连接: {random_jump_connections}")

                        panel.show_parameters(
                            card_id=start_card.card_id,
                            task_type=start_card.task_type,
                            param_definitions=start_card.param_definitions,
                            current_parameters=updated_parameters,
                            workflow_cards_info=workflow_info,
                            custom_name=getattr(start_card, 'custom_name', None)
                        )
                        logger.info(f"[参数清理] 随机跳转参数面板已刷新")
            return  # 随机跳转不需要清理其他参数

        if not param_to_clear or param_to_clear not in start_card.parameters:
            logger.warning(f"[参数清理] param_to_clear 为空或不在参数中，退出")
            return

        current_value = start_card.parameters[param_to_clear]
        logger.warning(f"[参数清理] 当前参数值: {param_to_clear} = {current_value}")

        if start_card.parameters[param_to_clear] is None:
            logger.warning(f"[参数清理] 参数已经是 None，无需清除")
            return

        # Check if there are other connections of the same type
        has_other_same_type_connection = False
        logger.warning(f"[参数清理] 检查是否有其他同类型连线，当前连线数: {len(start_card.connections)}")
        for other_conn in start_card.connections:
            logger.warning(f"[参数清理]   检查连线: {other_conn}, 是否是当前连线: {other_conn == connection}")
            logger.warning(f"[参数清理]     连线详情: start={other_conn.start_item.card_id if hasattr(other_conn, 'start_item') and hasattr(other_conn.start_item, 'card_id') else 'N/A'} -> end={other_conn.end_item.card_id if hasattr(other_conn, 'end_item') and hasattr(other_conn.end_item, 'card_id') else 'N/A'}, type={other_conn.line_type if hasattr(other_conn, 'line_type') else 'N/A'}")
            if other_conn == connection:
                logger.warning(f"[参数清理]     跳过当前连线")
                continue
            if (isinstance(other_conn, ConnectionLine) and
                hasattr(other_conn, 'line_type') and
                other_conn.line_type == line_type):
                # Ignore virtual start connections
                if hasattr(other_conn, 'start_item') and other_conn.start_item:
                    if hasattr(other_conn.start_item, 'card_id') and other_conn.start_item.card_id == -9999:
                        logger.warning(f"[参数清理]     忽略虚拟起点连线")
                        continue
                # 注释已清理（原注释编码损坏）
                # 如果是其他卡片连到当前卡片（输入连线），不应该影响当前卡片的输出参数
                if hasattr(other_conn, 'start_item') and other_conn.start_item == start_card:
                    logger.warning(f"[参数清理]     找到其他同类型【输出】连线！")
                    has_other_same_type_connection = True
                    break
                else:
                    logger.warning(f"[参数清理]     这是输入连线，忽略")

        logger.warning(f"[参数清理] 是否有其他同类型输出连线: {has_other_same_type_connection}")
        if not has_other_same_type_connection:
            logger.info(f"[参数清理] 清除参数 {param_to_clear} = {start_card.parameters[param_to_clear]}")
            start_card.parameters[param_to_clear] = None

            # Reset action parameters
            if line_type == ConnectionType.SUCCESS.value and start_card.parameters.get('on_success') == '跳转到步骤':
                start_card.parameters['on_success'] = '执行下一步'
                logger.info(f"[参数清理] 重置 on_success -> '执行下一步'")
            elif line_type == ConnectionType.FAILURE.value and start_card.parameters.get('on_failure') == '跳转到步骤':
                start_card.parameters['on_failure'] = '执行下一步'
                logger.info(f"[参数清理] 重置 on_failure -> '执行下一步'")

            start_card.parameters = start_card.parameters.copy()
            start_card.update()

            # 【性能优化】移除每次清理参数都序列化和保存的逻辑
            # 注释已清理（原注释编码损坏）
            # 此处只需要标记为未保存状态即可
            if hasattr(self, 'main_window') and self.main_window:
                try:
                    # 标记为未保存
                    if hasattr(self.main_window, '_mark_unsaved_changes'):
                        self.main_window._mark_unsaved_changes()

                    # 注释已清理（原注释编码损坏）
                    if hasattr(self.main_window, 'parameter_panel') and self.main_window.parameter_panel:
                        if (self.main_window.parameter_panel.is_panel_open() and
                            self.main_window.parameter_panel.current_card_id == start_card.card_id):
                            logger.info(f"[参数清理] 刷新参数面板显示，卡片 {start_card.card_id}")
                            # 重新显示参数面板，使用更新后的参数
                            workflow_info = {}
                            for seq_id, card_obj in enumerate(self.cards.values()):
                                workflow_info[seq_id] = (card_obj.task_type, card_obj.card_id)

                            self.main_window.parameter_panel.show_parameters(
                                card_id=start_card.card_id,
                                task_type=start_card.task_type,
                                param_definitions=start_card.param_definitions,
                                current_parameters=start_card.parameters,
                                workflow_cards_info=workflow_info,
                                images_dir=self.images_dir,
                                target_window_hwnd=self.main_window.parameter_panel.target_window_hwnd,
                                task_module=self.main_window.parameter_panel.task_module,
                                main_window=self.main_window
                            )
                            logger.info(f"[参数清理] 参数面板已刷新")
                except Exception as e:
                    logger.warning(f"[参数清理] 刷新参数面板失败: {e}")

            logger.info(f"[参数清理] 完成参数清理")

    def remove_connection(self, connection):
        """Removes a connection from the scene and internal tracking - 增强安全版本"""
        logger.warning(f"========== remove_connection 被调用 ==========")
        logger.warning(f"connection 对象: {connection}")
        logger.warning(f"connection 类型: {type(connection)}")

        try:
            # 直接使用传统删除方法
            logger.info(f"删除连接")

            # 注释已清理（原注释编码损坏）
            if not self.editing_enabled:
                logger.info("删除连接被阻止 - 编辑已禁用（工作流运行中）")
                return

            # 检查是否正在运行，如果是则阻止删除连接
            if self._block_edit_if_running("删除连接"):
                return

            # 验证连接对象的有效性
            if not connection:
                logger.warning("尝试删除空连接对象")
                return

            # 注释已清理（原注释编码损坏）
            if not hasattr(connection, 'start_item') or not hasattr(connection, 'end_item'):
                logger.warning("连接对象缺少必要属性，可能已损坏")
                return

            # 检查连接是否还在连接列表中
            if connection not in self.connections:
                logger.debug("连接已不在连接列表中，可能已被删除")
                return

            # 保存连接状态用于撤销（除非正在删除卡片、加载工作流、更新序列显示、执行撤销操作或修改连线）
            if (not self._deleting_card and not self._loading_workflow and not self._updating_sequence and
                not self._undoing_operation and not getattr(self, '_modifying_connection', False)):
                try:
                    self._save_connection_state_for_undo(connection)
                except Exception as e:
                    logger.warning(f"保存连接撤销状态失败: {e}")
            else:
                if self._deleting_card:
                    debug_print(f"  [UNDO] Skipping connection undo save (deleting card)")
                if self._loading_workflow:
                    debug_print(f"  [UNDO] Skipping connection undo save (loading workflow)")
                if self._updating_sequence:
                    debug_print(f"  [UNDO] Skipping connection undo save (updating sequence)")
                if self._undoing_operation:
                    debug_print(f"  [UNDO] Skipping connection undo save (undoing operation)")
                if getattr(self, '_modifying_connection', False):
                    debug_print(f"  [UNDO] Skipping connection undo save (modifying connection)")

            logger.info(f"--- [DEBUG] WorkflowView: Attempting to remove connection: {connection} ---")
            was_sequential = False

        except Exception as e:
            logger.error(f"删除连接预处理失败: {e}", exc_info=True)
            return

        if isinstance(connection, ConnectionLine) and hasattr(connection, 'line_type') and connection.line_type == 'sequential':
             was_sequential = True

        try:
            # 【修复】先从卡片连接列表中移除，然后再清除参数
            # 注释已清理（原注释编码损坏）
            if hasattr(connection, 'start_item') and connection.start_item:
                try:
                    if hasattr(connection.start_item, 'remove_connection'):
                        connection.start_item.remove_connection(connection)
                        logger.debug(f"  [DEBUG] Removed connection from start item: {connection.start_item.title if hasattr(connection.start_item, 'title') else 'Unknown'}")
                except Exception as e:
                    logger.warning(f"从起始卡片移除连接失败: {e}")

            if hasattr(connection, 'end_item') and connection.end_item:
                try:
                    if hasattr(connection.end_item, 'remove_connection'):
                        connection.end_item.remove_connection(connection)
                        logger.debug(f"  [DEBUG] Removed connection from end item: {connection.end_item.title if hasattr(connection.end_item, 'title') else 'Unknown'}")
                except Exception as e:
                    logger.warning(f"从目标卡片移除连接失败: {e}")

            # 注释已清理（原注释编码损坏）
            # 注释已清理（原注释编码损坏）
            self._clear_jump_parameters_for_connection(connection)

            # Remove from view's connection list
            try:
                if connection in self.connections:
                    self.connections.remove(connection)
                    logger.debug(f"  [DEBUG] Removed connection from view's list.")
            except Exception as e:
                logger.warning(f"从视图连接列表移除连接失败: {e}")

            # Remove from scene
            try:
                if hasattr(connection, 'scene') and connection.scene() == self.scene:
                    self.scene.removeItem(connection)
                    logger.debug(f"  [DEBUG] Removed connection from scene.")
                else:
                    logger.debug(f"  [DEBUG] Connection was not in the scene or already removed.")
            except Exception as e:
                logger.warning(f"从场景移除连接失败: {e}")

            # 清理连接对象引用，防止内存泄漏
            try:
                try:
                    from ..workflow_parts.connection_line import _unregister_animated_line
                    _unregister_animated_line(connection)
                except Exception as anim_e:
                    logger.debug(f"  [DEBUG] 从动画列表移除连接时出错: {anim_e}")

                if hasattr(connection, 'start_item'):
                    connection.start_item = None
                if hasattr(connection, 'end_item'):
                    connection.end_item = None
                logger.debug(f"  [DEBUG] Cleared connection object references.")
            except Exception as e:
                logger.warning(f"清理连接对象引用失败: {e}")

            logger.info(f"--- [DEBUG] WorkflowView: Connection removal finished for: {connection} ---")

            # 更新序列显示（如果是顺序连接）
            if was_sequential:
                try:
                    logger.info("  [CONN_DEBUG] Manual sequential connection removed, triggering sequence update.")
                    self.update_card_sequence_display()
                    logger.debug(f"  Direct sequence update called after sequential connection removal.")
                except Exception as e:
                    logger.error(f"更新序列显示失败: {e}")

            # 【修复】发送 connection_deleted 信号，触发 workflow_data 更新
            # 这样删除的连线可以立即生效，无需保存工作流
            try:
                self.connection_deleted.emit(connection)
                logger.debug(f"  [SIGNAL] Emitted connection_deleted signal for connection: {connection}")
            except Exception as e:
                logger.warning(f"发送connection_deleted信号失败: {e}")

        except Exception as e:
            logger.error(f"连接删除过程中发生严重错误: {e}", exc_info=True)
            # 即使出错也要尝试基本清理
            try:
                try:
                    from ..workflow_parts.connection_line import _unregister_animated_line
                    _unregister_animated_line(connection)
                except Exception:
                    pass
                if connection in self.connections:
                    self.connections.remove(connection)
                if hasattr(connection, 'scene') and connection.scene():
                    connection.scene().removeItem(connection)
            except:
                pass

    def _cleanup_duplicate_connections(self, start_card, end_card, line_type):
        """清理指定卡片之间的所有重复连接"""
        debug_print(f"  [CLEANUP_DUPLICATES] Cleaning up duplicate connections: {start_card.card_id} -> {end_card.card_id} ({line_type})")

        # BUG FIX #6: 优先从卡片和视图列表查找，避免遍历整个场景
        connections_to_remove = []

        # 1. 从起始卡片的连接列表查找
        if hasattr(start_card, 'connections'):
            for conn in start_card.connections[:]:
                if (hasattr(conn, 'start_item') and hasattr(conn, 'end_item') and hasattr(conn, 'line_type') and
                    conn.start_item == start_card and conn.end_item == end_card and conn.line_type == line_type):
                    if conn not in connections_to_remove:
                        connections_to_remove.append(conn)
                        debug_print(f"    Found duplicate connection in start card list: {conn}")

        # 2. 从终点卡片的连接列表查找（补充检查）
        if hasattr(end_card, 'connections'):
            for conn in end_card.connections[:]:
                if (hasattr(conn, 'start_item') and hasattr(conn, 'end_item') and hasattr(conn, 'line_type') and
                    conn.start_item == start_card and conn.end_item == end_card and conn.line_type == line_type):
                    if conn not in connections_to_remove:
                        connections_to_remove.append(conn)
                        debug_print(f"    Found duplicate connection in end card list: {conn}")

        # 注释已清理（原注释编码损坏）
        for conn in self.connections[:]:
            if (isinstance(conn, ConnectionLine) and
                hasattr(conn, 'start_item') and hasattr(conn, 'end_item') and hasattr(conn, 'line_type') and
                conn.start_item == start_card and conn.end_item == end_card and conn.line_type == line_type):
                if conn not in connections_to_remove:
                    connections_to_remove.append(conn)
                    debug_print(f"    Found duplicate connection in view list: {conn}")

        # BUG FIX #6 补充：添加场景遍历作为兜底方案（只在必要时）
        if not connections_to_remove:
            debug_print(f"    [WARNING] No duplicate connections found in card/view lists, falling back to scene scan")
            try:
                for item in self.scene.items():
                    if (isinstance(item, ConnectionLine) and
                        hasattr(item, 'start_item') and hasattr(item, 'end_item') and hasattr(item, 'line_type') and
                        item.start_item == start_card and item.end_item == end_card and item.line_type == line_type):
                        connections_to_remove.append(item)
                        debug_print(f"    Found duplicate connection from scene fallback: {item}")
            except Exception as e:
                debug_print(f"    [WARNING] Error in scene fallback scan: {e}")
                logger.warning(f"场景扫描失败: {e}")

        # 强制移除所有找到的重复连接
        for conn in connections_to_remove:
            debug_print(f"    Forcefully removing duplicate connection: {conn}")
            self._force_remove_connection(conn)

        debug_print(f"  [CLEANUP_DUPLICATES] Removed {len(connections_to_remove)} duplicate connections")

    def _update_card_parameters_on_connection_create(self, start_card, end_card, line_type):
        """当创建连接时更新卡片参数"""
        debug_print(f"  [PARAM_UPDATE] ===== UPDATING PARAMETERS FOR CONNECTION CREATION =====")
        debug_print(f"  [PARAM_UPDATE] Connection: {start_card.card_id} -> {end_card.card_id} ({line_type})")
        debug_print(f"  [PARAM_UPDATE] Start card current parameters: {start_card.parameters}")

        # 只处理成功/失败连接，其他sequential连接不需要更新参数
        if line_type not in ['success', 'failure']:
            return

        # 确定要更新的参数名称
        if line_type == 'success':
            action_param = 'on_success'
            target_param = 'success_jump_target_id'
        else:  # failure
            action_param = 'on_failure'
            target_param = 'failure_jump_target_id'

        # 检查起始卡片是否有这些参数
        if not hasattr(start_card, 'parameters'):
            debug_print(f"    [PARAM_UPDATE] Start card {start_card.card_id} has no parameters attribute")
            return

        # 更新参数
        parameter_changed = False

        # 注释已清理（原注释编码损坏）
        if start_card.parameters.get(action_param) != '跳转到步骤':
            start_card.parameters[action_param] = '跳转到步骤'
            parameter_changed = True
            debug_print(f"    [PARAM_UPDATE] Set {action_param} to '跳转到步骤' for card {start_card.card_id}")

        # 设置目标ID
        if start_card.parameters.get(target_param) != end_card.card_id:
            start_card.parameters[target_param] = end_card.card_id
            parameter_changed = True
            debug_print(f"    [PARAM_UPDATE] Set {target_param} to {end_card.card_id} for card {start_card.card_id}")

        # 更新端口限制和卡片显示（无论参数是否变化都要更新显示）
        debug_print(f"    [PARAM_UPDATE] Updating display for card {start_card.card_id} (parameter_changed: {parameter_changed})")
        start_card.update_port_restrictions()

        # --- ADDED: Always update parameter preview display ---
        # 注释已清理（原注释编码损坏）
        start_card._tooltip_needs_update = True
        # 注释已清理（原注释编码损坏）
        start_card.update()
        # --- END ADDED ---

        if parameter_changed:
            debug_print(f"    [PARAM_UPDATE] Card {start_card.card_id} parameters changed and display updated due to connection creation")
        else:
            debug_print(f"    [PARAM_UPDATE] Card {start_card.card_id} parameters unchanged but display refreshed due to connection creation")
