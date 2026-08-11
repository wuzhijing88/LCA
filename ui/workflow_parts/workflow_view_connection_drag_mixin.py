from .workflow_view_common import *


class WorkflowViewConnectionDragMixin:

    def start_drag_line(self, start_card: TaskCard, port_type: str):
        """Called by TaskCard when a drag starts from an output port."""
        # 检查是否正在运行，如果是则阻止拖拽连接
        if self._block_edit_if_running("拖拽连接"):
            return
            
        debug_print(f"  [DRAG_DEBUG] WorkflowView.start_drag_line called. Card: {start_card.card_id}, Port: {port_type}") # <-- ADD LOG
        
        # <<< ENHANCED: 拖拽前验证连接状态 >>>
        logger.debug("验证连接状态（拖拽开始前）...")
        invalid_count = self.validate_connections()
        if invalid_count > 0:
            logger.info(f"拖拽开始前清理了 {invalid_count} 个无效连接")
        # <<< END ENHANCED >>>
        
        self.is_dragging_line = True
        self.drag_start_card = start_card
        self.drag_start_port_type = port_type
        
        # Get the starting position in scene coordinates
        start_pos = start_card.get_output_port_scene_pos(port_type)
        
        # Create and add the temporary line
        self.temp_line = TempConnectionLine(start_pos.x(), start_pos.y(), start_pos.x(), start_pos.y())
        self.temp_line.setPen(self.temp_line_pen)
        self.temp_line.setZValue(6)
        self.scene.addItem(self.temp_line)
        debug_print(f"  [DRAG_DEBUG] Temp line created and added to scene.") # <-- ADD LOG
        
        # Temporarily disable scene panning while dragging line
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def update_drag_line(self, end_pos_scene: QPointF):
        """Updates the end position of the temporary drag line, implementing snapping."""
        if not self.temp_line or not self.is_dragging_line or not self.drag_start_card or not self.drag_start_port_type:
            return

        target_pos = end_pos_scene # Default to mouse position
        snapped = False
        snap_distance_sq = SNAP_DISTANCE ** 2
        self.snapped_target_card = None # Reset snapped card initially

        # Only check for snapping when the cursor is near a card.
        snap_rect = QRectF(
            end_pos_scene.x() - SNAP_DISTANCE,
            end_pos_scene.y() - SNAP_DISTANCE,
            SNAP_DISTANCE * 2,
            SNAP_DISTANCE * 2
        )
        candidates = self.scene.items(
            snap_rect,
            Qt.ItemSelectionMode.IntersectsItemBoundingRect
        ) if self.scene else []

        # Check for snapping candidates within the nearby rect
        for item in candidates:
            card = item if isinstance(item, TaskCard) else item.parentItem()
            if not isinstance(card, TaskCard):
                continue
            # 跳过没有输入端口的卡片（如附加条件）
            if hasattr(card, 'no_input_ports') and card.no_input_ports:
                continue
            if self.drag_start_card and self._validate_special_connection_rule(self.drag_start_card, card, self.drag_start_port_type):
                continue

            # Get the potential target input port position in scene coordinates
            potential_snap_target = card.get_input_port_scene_pos(self.drag_start_port_type)

            # Calculate distance squared for efficiency
            delta = end_pos_scene - potential_snap_target
            dist_sq = delta.x()**2 + delta.y()**2

            if dist_sq <= snap_distance_sq:
                target_pos = potential_snap_target # Snap to the port center
                snapped = True
                self.snapped_target_card = card # Store the card we snapped to
                break # Snap to the first valid port found

        self.is_snapped = snapped # Update overall snapping status

        # Update line end position
        line = self.temp_line.line()
        line.setP2(target_pos)
        self.temp_line.setLine(line)
        
        # Update line style based on snapping state
        if snapped:
            self.temp_line.setPen(self.temp_line_snap_pen)
        else:
            self.temp_line.setPen(self.temp_line_pen)

    def end_drag_line(self, end_pos: QPointF):
        """Finalizes line dragging: creates connection if valid, removes temp line."""
        logger.debug(f"  [DRAG_DEBUG] WorkflowView.end_drag_line called. End pos (scene): {end_pos}")
        self.is_dragging_line = False

        if self.temp_line:
            self.scene.removeItem(self.temp_line)
            self.temp_line = None
            logger.debug(f"  [DRAG_DEBUG] Temp line removed from scene.")

        needs_update = False
        if self.is_snapped and self.snapped_target_card and self.drag_start_card:
            start_card = self.drag_start_card
            end_card = self.snapped_target_card
            port_type = self.drag_start_port_type

            # <<< ENHANCED: 连接创建前的全面验证 >>>
            logger.debug(f"  [DRAG_VALIDATION] Validating connection before creation...")

            # 验证起始卡片仍然有效
            if start_card.card_id not in self.cards:
                logger.warning(f"  [DRAG_VALIDATION] Start card {start_card.card_id} no longer exists in workflow. Aborting connection.")
                self._cleanup_drag_state()
                return

            # 验证目标卡片仍然有效
            if end_card.card_id not in self.cards:
                logger.warning(f"  [DRAG_VALIDATION] End card {end_card.card_id} no longer exists in workflow. Aborting connection.")
                self._cleanup_drag_state()
                return

            # 验证卡片仍在场景中
            if start_card.scene() != self.scene:
                logger.warning(f"  [DRAG_VALIDATION] Start card {start_card.card_id} is no longer in scene. Aborting connection.")
                self._cleanup_drag_state()
                return

            if end_card.scene() != self.scene:
                logger.warning(f"  [DRAG_VALIDATION] End card {end_card.card_id} is no longer in scene. Aborting connection.")
                self._cleanup_drag_state()
                return

            # 验证 random 端口只能连接到 sequential 输入
            if port_type == 'random':
                # random 端口只能连接到目标卡片的 sequential 输入端口
                logger.debug(f"  [DRAG_VALIDATION] Random port detected, validating target port type...")
                # 目前的实现是隐式连接到sequential端口，这里只做检查
                # 实际的端口位置获取在ConnectionLine中通过get_end_pos实现
                logger.debug(f"  [DRAG_VALIDATION] Random port will connect to sequential input port of card {end_card.card_id}")

            special_rule_error = self._validate_special_connection_rule(start_card, end_card, port_type)
            if special_rule_error:
                logger.warning(
                    "  [DRAG_VALIDATION] Connection rejected: %s -> %s (%s), reason: %s",
                    start_card.card_id,
                    end_card.card_id,
                    port_type,
                    special_rule_error,
                )
                self._cleanup_drag_state()
                return

            logger.debug(f"  [DRAG_VALIDATION] All validations passed. Proceeding with connection creation.")
            # <<< END ENHANCED >>>

            if any(conn for conn in start_card.connections
                     if isinstance(conn, ConnectionLine) and conn.end_item == end_card and conn.line_type == port_type):
                logger.debug(f"  [DRAG_DEBUG] Duplicate connection detected ({start_card.card_id} -> {end_card.card_id}, type: {port_type}). Not created.")
                # --- ADDED: Force cleanup when duplicate detected during manual connection ---
                logger.debug(f"  [DRAG_DEBUG] Force cleaning up duplicate connection during manual drag...")
                self._cleanup_duplicate_connections(start_card, end_card, port_type)
                # Try to create connection again after cleanup
                logger.debug(f"  [DRAG_DEBUG] Attempting to create connection after cleanup...")
                connection = self.add_connection(start_card, end_card, port_type)
                if connection:
                    logger.debug(f"  [DRAG_DEBUG] Successfully created connection after cleanup: {connection}")
                    # 注释已清理（原注释编码损坏）
                    needs_update = True
                else:
                    logger.debug("  [拖拽调试] 清理后仍然创建连线失败")
                # --- END ADDED ---
            else:
                logger.debug(f"  [SYNC_DEBUG] Checking for existing output connection from card {start_card.card_id}, port type '{port_type}'.")
                existing_connection_to_remove = None

                # random 端口允许多个连接，跳过移除旧连接的逻辑
                if port_type != 'random':
                    for conn in list(start_card.connections):
                        if isinstance(conn, ConnectionLine) and conn.start_item == start_card and conn.line_type == port_type:
                            existing_connection_to_remove = conn
                            break
                    if existing_connection_to_remove:
                        logger.debug(f"  [SYNC_DEBUG] Removing existing connection from port '{port_type}' of card {start_card.card_id} before adding new one.")
                        # 【关键修复】设置修改连线标志，防止删除旧连线时清除参数
                        self._modifying_connection = True
                        self.remove_connection(existing_connection_to_remove)
                        # 注意：_modifying_connection 会在 add_connection 完成后重置
                else:
                    logger.debug(f"  [RANDOM_PORT] random 端口允许多个连接，不移除已有连接")

                if port_type == ConnectionType.SUCCESS.value or port_type == ConnectionType.FAILURE.value:
                    param_name = 'success_jump_target_id' if port_type == ConnectionType.SUCCESS.value else 'failure_jump_target_id'
                    action_param = 'on_success' if port_type == ConnectionType.SUCCESS.value else 'on_failure'
                    
                    logger.debug(f"  [DRAG_DEBUG] Jump connection ({port_type}). Updating parameters for card {start_card.card_id}.")
                    if action_param in start_card.parameters and start_card.parameters[action_param] != '跳转到步骤':
                        logger.info(f"  Updating card {start_card.card_id} parameter '{action_param}' to '跳转到步骤' due to new connection drag.")
                        start_card.parameters[action_param] = '跳转到步骤'
                    
                    if param_name in start_card.parameters:
                        logger.info(f"  Updating card {start_card.card_id} parameter '{param_name}' to {end_card.card_id}")
                        start_card.parameters[param_name] = end_card.card_id
                    else:
                        logger.warning(f"  Skipping parameter update: Card {start_card.card_id} ({start_card.task_type}) does not have parameter '{param_name}'.")
                    
                    # <<< ENHANCED: 创建跳转连接时使用增强的add_connection >>>
                    logger.debug(f"  [DRAG_DEBUG] Creating jump connection via add_connection...")
                    connection = self.add_connection(start_card, end_card, port_type)
                    if connection:
                        logger.debug(f"  [DRAG_DEBUG] Jump connection created successfully: {connection}")
                    else:
                        logger.warning("  [拖拽调试] 创建跳转连线失败")
                    # <<< END ENHANCED >>>
                    needs_update = True # Parameter change means an update is needed

                elif port_type == "random":
                    # random 类型连接：直接创建，不更新参数
                    logger.debug(f"  [DRAG_DEBUG] Random connection. Creating connection {start_card.card_id} -> {end_card.card_id}...")
                    connection = self.add_connection(start_card, end_card, port_type)
                    if connection:
                        logger.debug(f"  [DRAG_DEBUG] Random connection created successfully: {connection}")
                    else:
                        logger.warning("  [拖拽调试] 创建随机连线失败")
                    needs_update = True

                elif port_type == "sequential": # Check against the actual string value
                    logger.debug(f"  [DRAG_DEBUG] Sequential connection. Creating connection {start_card.card_id} -> {end_card.card_id}...")

                    connection = self.add_connection(start_card, end_card, port_type)
                    if connection:
                        logger.debug(f"  [DRAG_DEBUG] Sequential connection created: {connection}")
                    else:
                        logger.warning("  [拖拽调试] 创建顺序连线失败")
                    needs_update = True

                if needs_update:
                    logger.debug(f"  [DRAG_DEBUG] Triggering sequence/jump update after drag operation for port type '{port_type}'.")
                    # 重置修改连线标志
                    self._modifying_connection = False
                    self.update_card_sequence_display()

                    # 注释已清理（原注释编码损坏）
                    if hasattr(self, 'main_window') and self.main_window:
                        if hasattr(self.main_window, 'parameter_panel') and self.main_window.parameter_panel:
                            panel = self.main_window.parameter_panel
                            if panel.is_panel_open() and panel.current_card_id == start_card.card_id:
                                logger.warning(f"  [DRAG_DEBUG] 刷新参数面板，卡片 {start_card.card_id}")
                                workflow_info = {}
                                for seq_id, card_obj in enumerate(self.cards.values()):
                                    workflow_info[seq_id] = (card_obj.task_type, card_obj.card_id)

                                # 为随机跳转卡片收集连接数据
                                updated_parameters = start_card.parameters.copy()
                                if start_card.task_type == '随机跳转':
                                    random_jump_connections = []
                                    for conn in self.connections:
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
                                    updated_parameters['_random_connections'] = random_jump_connections
                                    logger.info(f"  [DRAG_DEBUG] 随机跳转连接数据: {random_jump_connections}")

                                panel.show_parameters(
                                    card_id=start_card.card_id,
                                    task_type=start_card.task_type,
                                    param_definitions=start_card.param_definitions,
                                    current_parameters=updated_parameters,
                                    workflow_cards_info=workflow_info,
                                    custom_name=getattr(start_card, 'custom_name', None)
                                )
        else:
            logger.debug(f"  [DRAG_DEBUG] Drag ended without snapping to a valid target.")

        # <<< ENHANCED: 使用清理方法统一清理状态 >>>
        self._cleanup_drag_state()

    def _cleanup_drag_state(self):
        """Clean up drag state and restore view mode."""
        logger.debug(f"  [DRAG_CLEANUP] Cleaning up drag state...")
        
        self.drag_start_card = None
        self.drag_start_port_type = None
        self.is_snapped = False
        self.snapped_target_card = None
        
        # 注释已清理（原注释编码损坏）
        if self.temp_line and self.temp_line.scene() == self.scene:
            self.scene.removeItem(self.temp_line)
            self.temp_line = None

        restore_mode = self._original_drag_mode if self._original_drag_mode is not None else QGraphicsView.DragMode.ScrollHandDrag
        self.setDragMode(restore_mode)
        logger.debug(f"  [DRAG_CLEANUP] Restored drag mode to {restore_mode} after line drag.")

    def mousePressEvent(self, event: QMouseEvent):
        """Override mouse press to handle multi-selection, background clicks, and drag operations."""
        self._hide_card_tooltip_overlay()
        item_at_pos = self.itemAt(event.pos())
        modifiers = event.modifiers()

        # Handle Ctrl+Left click for multi-selection
        if (event.button() == Qt.MouseButton.LeftButton and
            modifiers == Qt.KeyboardModifier.ControlModifier):

            if isinstance(item_at_pos, TaskCard):
                # 注释已清理（原注释编码损坏）
                if item_at_pos.isSelected():
                    item_at_pos.setSelected(False)
                    debug_print(f"  [MULTI_SELECT] Ctrl+Click: Deselected card {item_at_pos.card_id}")
                else:
                    item_at_pos.setSelected(True)
                    debug_print(f"  [MULTI_SELECT] Ctrl+Click: Selected card {item_at_pos.card_id}")
                event.accept()
                return
            elif item_at_pos is None:
                # 注释已清理（原注释编码损坏）
                debug_print("  [MULTI_SELECT] Ctrl+Drag: Enabling rubber band selection")
                self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
                super().mousePressEvent(event)
                return

        # 手动实现画布平移
        if event.button() == Qt.MouseButton.LeftButton and item_at_pos is None:
            debug_print("  [DEBUG] WorkflowView: Background left-clicked. Starting pan.")
            self._stop_all_flashing()

            # 确保视图获得焦点
            if not self.hasFocus():
                self.setFocus()

            if modifiers != Qt.KeyboardModifier.ControlModifier:
                self.scene.clearSelection()
                self._is_panning = True
                self._set_drag_preview_mode(True)
                self._last_pan_step_ms = 0.0
                self._pan_start_x = event.pos().x()
                self._pan_start_y = event.pos().y()
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self._clear_all_card_tooltips()
                event.accept()
            return

        # Handle right-click for context menu (ignores press)
        if event.button() == Qt.MouseButton.RightButton:
            self._last_right_click_view_pos_f = event.position()
            debug_print("  [DEBUG] WorkflowView: Right mouse button pressed. Storing pos. NOT calling super() initially.")
            event.accept()
            return

        # Handle left-click on a card
        debug_print("  [DEBUG] WorkflowView: Left/Other mouse button pressed on item or starting drag. Calling super().")

        # 确保视图获得焦点
        if not self.hasFocus():
            self.setFocus()
            debug_print("  [FOCUS] Set focus to WorkflowView on item click")

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move events for line dragging and view panning."""
        # 手动平移
        if self._is_panning:
            self._hide_card_tooltip_overlay()
            now_ms = time.perf_counter() * 1000.0
            if (self._pan_frame_interval_ms > 0 and
                self._last_pan_step_ms > 0.0 and
                (now_ms - self._last_pan_step_ms) < float(self._pan_frame_interval_ms)):
                event.accept()
                return
            self._last_pan_step_ms = now_ms
            delta_x = event.pos().x() - self._pan_start_x
            delta_y = event.pos().y() - self._pan_start_y
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta_x)
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta_y)
            self._pan_start_x = event.pos().x()
            self._pan_start_y = event.pos().y()
            event.accept()
            return

        if self.is_dragging_line:
            scene_pos = self.mapToScene(event.pos())
            self.update_drag_line(scene_pos)
        else:
            super().mouseMoveEvent(event)  # Handle item dragging

    def mouseReleaseEvent(self, event: QMouseEvent):
        # 结束手动平移
        if self._is_panning:
            self._is_panning = False
            self._last_pan_step_ms = 0.0
            self._set_drag_preview_mode(False)
            try:
                self._handle_scroll_change(0)
            except Exception:
                pass
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._hide_card_tooltip_overlay()
            event.accept()
            return

        if self.is_dragging_line:
            scene_pos = self.mapToScene(event.pos())
            self.end_drag_line(scene_pos)
        else:
            # Handle normal release (e.g., end panning or rubber band selection)
            super().mouseReleaseEvent(event)

            # 注释已清理（原注释编码损坏）
            if self.dragMode() == QGraphicsView.DragMode.RubberBandDrag:
                self.setDragMode(QGraphicsView.DragMode.NoDrag)
                debug_print("  [MULTI_SELECT] Restored drag mode to NoDrag after rubber band selection")

    def leaveEvent(self, event):
        """当鼠标离开视图时，清理所有卡片的拖拽状态和辅助线。"""
        if self._drag_preview_mode:
            self._is_panning = False
            self._last_pan_step_ms = 0.0
            self._set_drag_preview_mode(False)
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self._clear_all_snap_guide_lines()
        super().leaveEvent(event)

    def focusOutEvent(self, event):
        """当视图失去焦点时（如截图工具激活），清理所有卡片的拖拽状态和辅助线。"""

        if self._drag_preview_mode:
            self._is_panning = False
            self._last_pan_step_ms = 0.0
            self._set_drag_preview_mode(False)
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self._clear_all_snap_guide_lines()
        super().focusOutEvent(event)

    def _clear_all_snap_guide_lines(self):
        """清理所有卡片的拖拽状态和辅助线。"""
        for card in self.cards.values():
            if hasattr(card, '_cancel_drag_state'):
                card._cancel_drag_state()
