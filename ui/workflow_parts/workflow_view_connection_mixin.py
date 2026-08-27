from .workflow_view_common import *

class WorkflowViewConnectionMixin:

    _VALID_CONNECTION_TYPES = frozenset(("sequential", "success", "failure", "random"))

    _JUMP_PARAMETER_KEYS = {
        "success": ("on_success", "success_jump_target_id"),
        "failure": ("on_failure", "failure_jump_target_id"),
    }

    def _validate_connection_endpoints(self, start_card, end_card, line_type):
        if not isinstance(start_card, TaskCard) or not isinstance(end_card, TaskCard):
            raise TypeError("连线两端必须是 TaskCard")
        if line_type not in self._VALID_CONNECTION_TYPES:
            raise ValueError(f"不支持的连线类型: {line_type!r}")
        if self.cards.get(start_card.card_id) is not start_card:
            raise ValueError("连线起点不属于当前工作流")
        if self.cards.get(end_card.card_id) is not end_card:
            raise ValueError("连线终点不属于当前工作流")
        if start_card.scene() is not self.scene or end_card.scene() is not self.scene:
            raise ValueError("连线两端必须挂载在当前场景")
        if not isinstance(start_card.connections, list) or not isinstance(end_card.connections, list):
            raise TypeError("卡片连接容器必须是列表")
        if line_type in ("success", "failure") and start_card.restricted_outputs:
            raise ValueError(f"卡片 {start_card.card_id} 的 {line_type} 输出端口不可用")
        if line_type == "random" and start_card.restricted_outputs != "random_only":
            raise ValueError(f"卡片 {start_card.card_id} 没有随机输出端口")
        if end_card.no_input_ports:
            raise ValueError(f"卡片 {end_card.card_id} 没有输入端口")
        rule_error = self._validate_special_connection_rule(start_card, end_card, line_type)
        if rule_error:
            raise ValueError(rule_error)

    def _validate_connection_contract(self, connection, *, require_scene=True):
        if not isinstance(connection, ConnectionLine):
            raise TypeError("连接对象必须是 ConnectionLine")
        start_card = connection.start_item
        end_card = connection.end_item
        line_type = connection.line_type
        if start_card is None or end_card is None:
            raise ValueError("连接必须同时包含起点和终点卡片")
        if line_type not in self._VALID_CONNECTION_TYPES:
            raise ValueError(f"不支持的连线类型: {line_type!r}")
        if self.cards.get(getattr(start_card, "card_id", None)) is not start_card:
            raise ValueError("连线起点不属于当前工作流")
        if self.cards.get(getattr(end_card, "card_id", None)) is not end_card:
            raise ValueError("连线终点不属于当前工作流")
        if self.connections.count(connection) != 1:
            raise ValueError("连接在视图列表中的登记次数必须为 1")
        if start_card.connections.count(connection) != 1:
            raise ValueError("连接在起点卡片中的登记次数必须为 1")
        if end_card.connections.count(connection) != 1:
            raise ValueError("连接在终点卡片中的登记次数必须为 1")
        if require_scene and connection.scene() is not self.scene:
            raise ValueError("连接未挂载在当前场景")
        return start_card, end_card, line_type

    def _registered_connections_for_port(self, start_card, line_type):
        matches = []
        for connection in self.connections:
            if not isinstance(connection, ConnectionLine):
                raise TypeError("视图连接列表中存在非 ConnectionLine 对象")
            if connection.start_item is start_card and connection.line_type == line_type:
                matches.append(connection)
        return matches

    def _mark_workflow_dirty(self) -> None:
        main_window = getattr(self, "main_window", None)
        tab_widget = getattr(main_window, "workflow_tab_widget", None) if main_window is not None else None
        task_id = getattr(self, "task_id", None)
        if tab_widget is not None and task_id is not None:
            tab_widget._mark_task_modified(task_id)
            return
        if main_window is not None and hasattr(main_window, "_mark_unsaved_changes"):
            main_window._mark_unsaved_changes()

    def _refresh_connection_parameter_display(self, start_card):
        start_card.update_port_restrictions()
        start_card._tooltip_needs_update = True
        start_card.update()

        main_window = getattr(self, "main_window", None)
        panel = getattr(main_window, "parameter_panel", None) if main_window is not None else None
        if panel is None or not panel.is_panel_open() or panel.current_card_id != start_card.card_id:
            return
        panel.current_parameters = start_card.parameters.copy()
        panel._opened_parameters_snapshot = dict(panel.current_parameters)
        was_loading = getattr(panel, "_loading_parameter_panel", False)
        panel._loading_parameter_panel = True
        try:
            panel._rebuild_parameter_widgets()
        finally:
            panel._loading_parameter_panel = was_loading

    def _update_card_parameters_on_connection_create(self, start_card, end_card, line_type):
        parameter_keys = self._JUMP_PARAMETER_KEYS.get(line_type)
        if parameter_keys is None:
            return False
        if not isinstance(start_card.parameters, dict):
            raise TypeError("起点卡片 parameters 必须是字典")

        action_key, target_key = parameter_keys
        updated_parameters = start_card.parameters.copy()
        updated_parameters[action_key] = "跳转到步骤"
        updated_parameters[target_key] = end_card.card_id
        if updated_parameters == start_card.parameters:
            return False

        start_card.parameters = updated_parameters
        self._refresh_connection_parameter_display(start_card)
        return True

    def _clear_jump_parameters_for_connection(self, connection):
        start_card = connection.start_item
        end_card = connection.end_item
        line_type = connection.line_type
        if not isinstance(start_card, TaskCard):
            raise TypeError("连线起点必须是 TaskCard")
        if not isinstance(end_card, TaskCard):
            raise TypeError("连线终点必须是 TaskCard")
        if not isinstance(start_card.parameters, dict):
            raise TypeError("起点卡片 parameters 必须是字典")

        parameter_keys = self._JUMP_PARAMETER_KEYS.get(line_type)
        if parameter_keys is not None:
            action_key, target_key = parameter_keys
            if not self._same_card_id(start_card.parameters.get(target_key), end_card.card_id):
                return False
            updated_parameters = start_card.parameters.copy()
            updated_parameters[target_key] = None
            if "跳转" in str(updated_parameters.get(action_key) or ""):
                updated_parameters[action_key] = "执行下一步"
            if updated_parameters == start_card.parameters:
                return False
            start_card.parameters = updated_parameters
            self._refresh_connection_parameter_display(start_card)
            return True

        if line_type == "random":
            from tasks.random_jump import prune_branch_weights

            valid_target_ids = []
            for other in self.connections:
                if other is connection:
                    continue
                if not isinstance(other, ConnectionLine):
                    raise TypeError("视图连接列表中存在非 ConnectionLine 对象")
                if (
                    other.start_item is start_card
                    and other.line_type == "random"
                    and isinstance(other.end_item, TaskCard)
                ):
                    valid_target_ids.append(other.end_item.card_id)
            updated_weights = prune_branch_weights(
                start_card.parameters.get("random_weights"),
                valid_target_ids,
            )
            if updated_weights == start_card.parameters.get("random_weights"):
                return False
            updated_parameters = start_card.parameters.copy()
            updated_parameters["random_weights"] = updated_weights
            start_card.parameters = updated_parameters
            self._refresh_connection_parameter_display(start_card)
            return True
        return False

    def _mount_connection(self, connection):
        start_card = connection.start_item
        end_card = connection.end_item
        self.scene.addItem(connection)
        if connection.scene() is not self.scene:
            raise RuntimeError("连接未能挂载到当前场景")
        start_card.connections.append(connection)
        if end_card is not start_card:
            end_card.connections.append(connection)
        self.connections.append(connection)

    def _unmount_connection(self, connection):
        start_card = connection.start_item
        end_card = connection.end_item
        start_card.connections.remove(connection)
        if end_card is not start_card:
            end_card.connections.remove(connection)
        self.connections.remove(connection)
        self.scene.removeItem(connection)
        connection.start_item = None
        connection.end_item = None

    def _create_registered_connection(self, start_card, end_card, line_type):
        connection = ConnectionLine(start_card, end_card, line_type)
        try:
            self._mount_connection(connection)
        except Exception:
            if connection.scene() is self.scene:
                self.scene.removeItem(connection)
            if connection in start_card.connections:
                start_card.connections.remove(connection)
            if end_card is not start_card and connection in end_card.connections:
                end_card.connections.remove(connection)
            if connection in self.connections:
                self.connections.remove(connection)
            connection.start_item = None
            connection.end_item = None
            raise
        return connection

    def add_connection(self, start_card: TaskCard, end_card: TaskCard, line_type: str, skip_duplicate_check: bool = False):
        """创建连线；已有输出线时显式替换，不扫描、不补登记、不重试。"""
        del skip_duplicate_check  # 所有入口使用同一套严格校验。
        if not self._loading_workflow and (
            not self.editing_enabled or self._block_edit_if_running("添加连线")
        ):
            return None

        try:
            self._validate_connection_endpoints(start_card, end_card, line_type)
            state_errors = self._connection_state_errors()
            if state_errors:
                raise RuntimeError("；".join(state_errors))

            existing_connections = self._registered_connections_for_port(start_card, line_type)
            allow_multiple = line_type == "random" and start_card.task_type == "随机跳转"
            if allow_multiple:
                for existing in existing_connections:
                    if existing.end_item is end_card:
                        return existing
                old_connection = None
            else:
                if len(existing_connections) > 1:
                    raise RuntimeError(
                        f"卡片 {start_card.card_id} 的 {line_type} 输出端存在多条连接"
                    )
                old_connection = existing_connections[0] if existing_connections else None
                if old_connection is not None and old_connection.end_item is end_card:
                    return old_connection

            old_connection_data = None
            if old_connection is not None:
                self._validate_connection_contract(old_connection)
                old_connection_data = (
                    old_connection.start_item,
                    old_connection.end_item,
                    old_connection.line_type,
                )

            new_connection = self._create_registered_connection(start_card, end_card, line_type)
            try:
                self._update_card_parameters_on_connection_create(start_card, end_card, line_type)
                if old_connection is not None:
                    self._unmount_connection(old_connection)
            except Exception:
                self._unmount_connection(new_connection)
                raise

            if old_connection_data is not None:
                self.connection_deleted.emit(old_connection)
            self.connection_added.emit(start_card, end_card, line_type)
            if not self._loading_workflow and not self._undoing_operation:
                self._mark_workflow_dirty()
            if not self._loading_workflow and not self._updating_sequence and not self._undoing_operation:
                if old_connection_data is None and not getattr(self, "_pasting_card", False):
                    self._save_add_connection_state_for_undo(start_card, end_card, line_type)
                elif old_connection_data is not None:
                    old_start, old_end, old_type = old_connection_data
                    old_connection.start_item = old_start
                    old_connection.end_item = old_end
                    self._save_modify_connection_state_for_undo(
                        old_connection,
                        start_card,
                        end_card,
                        line_type,
                    )
                    old_connection.start_item = None
                    old_connection.end_item = None
            return new_connection
        except (TypeError, ValueError, RuntimeError) as exc:
            logger.debug(
                "创建连线被拒绝: %s -> %s (%s): %s",
                getattr(start_card, "card_id", None),
                getattr(end_card, "card_id", None),
                line_type,
                exc,
            )
            return None

    def remove_connection(self, connection):
        """严格删除一条已完整登记的连线。"""
        if not self.editing_enabled or self._block_edit_if_running("删除连线"):
            return False
        try:
            start_card, _, line_type = self._validate_connection_contract(connection)
            if not self._deleting_card and not self._loading_workflow and not self._updating_sequence and not self._undoing_operation:
                self._save_connection_state_for_undo(connection)
            self._clear_jump_parameters_for_connection(connection)
            self._unmount_connection(connection)
            if line_type == "sequential":
                self.update_card_sequence_display()
            self.connection_deleted.emit(connection)
            if not self._loading_workflow and not self._undoing_operation:
                self._mark_workflow_dirty()
            return True
        except (TypeError, ValueError, RuntimeError) as exc:
            logger.error("删除连线失败：%s", exc)
            return False

    _DRAG_PORT_TYPES = frozenset(("sequential", "success", "failure", "random"))

    def start_drag_line(self, start_card: TaskCard, port_type: str):
        """开始一次连线拖拽。"""
        if self._block_edit_if_running("拖拽连线"):
            return False
        if self.is_dragging_line:
            logger.error("已有连线拖拽正在进行，拒绝重复开始")
            return False
        if not isinstance(start_card, TaskCard):
            logger.error("拖拽起点必须是 TaskCard")
            return False
        if self.cards.get(start_card.card_id) is not start_card or start_card.scene() is not self.scene:
            logger.error("拖拽起点不属于当前工作流")
            return False
        if port_type not in self._DRAG_PORT_TYPES:
            logger.error("不支持的拖拽端口类型: %r", port_type)
            return False
        if start_card.restricted_outputs and port_type in ("success", "failure"):
            logger.error("卡片 %s 不允许使用 %s 输出端", start_card.card_id, port_type)
            return False
        invalid_count = self.validate_connections()
        if invalid_count:
            logger.error("连线状态存在 %d 项错误，拒绝开始拖线", invalid_count)
            return False

        start_pos = start_card.get_output_port_scene_pos(port_type)
        temp_line = TempConnectionLine(
            start_pos.x(), start_pos.y(), start_pos.x(), start_pos.y()
        )
        temp_line.setPen(self.temp_line_pen)
        temp_line.setZValue(6)
        self.scene.addItem(temp_line)

        self.temp_line = temp_line
        self.is_dragging_line = True
        self.drag_start_card = start_card
        self.drag_start_port_type = port_type
        self.is_snapped = False
        self.snapped_target_card = None
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        return True

    def update_drag_line(self, end_pos_scene: QPointF):
        """更新临时连线，并吸附到距离最近的合法输入端。"""
        if not self.is_dragging_line:
            return False
        if self.temp_line is None or self.drag_start_card is None:
            raise RuntimeError("拖拽状态不完整")

        snap_rect = QRectF(
            end_pos_scene.x() - SNAP_DISTANCE,
            end_pos_scene.y() - SNAP_DISTANCE,
            SNAP_DISTANCE * 2,
            SNAP_DISTANCE * 2,
        )
        nearest = None
        nearest_distance = None
        seen_cards = set()
        candidates = self.scene.items(
            snap_rect,
            Qt.ItemSelectionMode.IntersectsItemBoundingRect,
        )
        for item in candidates:
            card = item if isinstance(item, TaskCard) else item.parentItem()
            if not isinstance(card, TaskCard) or id(card) in seen_cards:
                continue
            seen_cards.add(id(card))
            if card is self.drag_start_card:
                continue
            if self.cards.get(card.card_id) is not card or card.scene() is not self.scene:
                continue
            if card.no_input_ports:
                continue
            if self._validate_special_connection_rule(
                self.drag_start_card,
                card,
                self.drag_start_port_type,
            ):
                continue

            target = card.get_input_port_scene_pos(self.drag_start_port_type)
            delta = end_pos_scene - target
            distance = delta.x() ** 2 + delta.y() ** 2
            if distance > SNAP_DISTANCE ** 2:
                continue
            if nearest_distance is None or distance < nearest_distance:
                nearest = (card, target)
                nearest_distance = distance

        target_pos = end_pos_scene
        self.snapped_target_card = None
        self.is_snapped = nearest is not None
        if nearest is not None:
            self.snapped_target_card, target_pos = nearest

        line = self.temp_line.line()
        line.setP2(target_pos)
        self.temp_line.setLine(line)
        self.temp_line.setPen(self.temp_line_snap_pen if nearest else self.temp_line_pen)
        return self.is_snapped

    def end_drag_line(self, end_pos: QPointF):
        """结束拖拽；一次拖拽最多调用一次正式连线创建。"""
        if not self.is_dragging_line:
            return False
        start_card = self.drag_start_card
        end_card = self.snapped_target_card if self.is_snapped else None
        port_type = self.drag_start_port_type
        try:
            if end_card is None:
                return False
            if self.cards.get(start_card.card_id) is not start_card:
                raise RuntimeError("拖拽起点已不属于当前工作流")
            if self.cards.get(end_card.card_id) is not end_card:
                raise RuntimeError("拖拽终点已不属于当前工作流")
            if start_card.scene() is not self.scene or end_card.scene() is not self.scene:
                raise RuntimeError("拖拽端点已离开当前场景")

            rule_error = self._validate_special_connection_rule(start_card, end_card, port_type)
            if rule_error:
                raise ValueError(rule_error)

            for connection in self.connections:
                if (
                    connection.start_item is start_card
                    and connection.end_item is end_card
                    and connection.line_type == port_type
                ):
                    logger.debug(
                        "连线已存在，不重复创建: %s -> %s (%s)",
                        start_card.card_id,
                        end_card.card_id,
                        port_type,
                    )
                    return True

            connection = self.add_connection(start_card, end_card, port_type)
            if connection is None:
                logger.error(
                    "拖拽创建连线失败: %s -> %s (%s)；不会重试或恢复旧连线",
                    start_card.card_id,
                    end_card.card_id,
                    port_type,
                )
                return False
            self.update_card_sequence_display()
            return True
        except (TypeError, ValueError, RuntimeError) as exc:
            logger.error("结束连线拖拽失败：%s", exc)
            return False
        finally:
            self._modifying_connection = False
            self._cleanup_drag_state()

    def _cleanup_drag_state(self):
        """清除临时对象并恢复拖拽前的视图模式。"""
        temp_line = self.temp_line
        cleanup_error = None
        if temp_line is not None:
            current_scene = temp_line.scene()
            if current_scene is self.scene:
                self.scene.removeItem(temp_line)
            elif current_scene is not None:
                cleanup_error = RuntimeError("临时连线被挂载到了其他场景")
        self.temp_line = None
        self.is_dragging_line = False
        self.drag_start_card = None
        self.drag_start_port_type = None
        self.is_snapped = False
        self.snapped_target_card = None
        self.setDragMode(self._original_drag_mode)
        if cleanup_error is not None:
            raise cleanup_error

    def mousePressEvent(self, event: QMouseEvent):
        """处理多选、背景平移和普通卡片点击。"""
        self._hide_card_tooltip_overlay()
        item_at_pos = self.itemAt(event.pos())
        modifiers = event.modifiers()

        if (
            event.button() == Qt.MouseButton.LeftButton
            and modifiers == Qt.KeyboardModifier.ControlModifier
        ):
            if isinstance(item_at_pos, TaskCard):
                item_at_pos.setSelected(not item_at_pos.isSelected())
                event.accept()
                return
            if item_at_pos is None:
                self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
                super().mousePressEvent(event)
                return

        if event.button() == Qt.MouseButton.LeftButton and item_at_pos is None:
            self._stop_all_flashing()
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

        if event.button() == Qt.MouseButton.RightButton:
            self._last_right_click_view_pos_f = event.position()
            event.accept()
            return

        if not self.hasFocus():
            self.setFocus()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        """处理连线拖拽、卡片拖动和画布平移。"""
        if self._is_panning:
            self._hide_card_tooltip_overlay()
            now_ms = time.perf_counter() * 1000.0
            if (
                self._pan_frame_interval_ms > 0
                and self._last_pan_step_ms > 0.0
                and now_ms - self._last_pan_step_ms < float(self._pan_frame_interval_ms)
            ):
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
            self.update_drag_line(self.mapToScene(event.pos()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """结束画布平移、连线拖拽或普通 Qt 拖动。"""
        if self._is_panning:
            self._is_panning = False
            self._last_pan_step_ms = 0.0
            self._set_drag_preview_mode(False)
            self._handle_scroll_change(0)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._hide_card_tooltip_overlay()
            event.accept()
            return

        if self.is_dragging_line:
            self.end_drag_line(self.mapToScene(event.pos()))
            event.accept()
            return

        super().mouseReleaseEvent(event)
        if self.dragMode() == QGraphicsView.DragMode.RubberBandDrag:
            self.setDragMode(self._original_drag_mode)

    def leaveEvent(self, event):
        """指针离开视图时取消尚未完成的交互。"""
        if self.is_dragging_line:
            self._cleanup_drag_state()
        if self._drag_preview_mode:
            self._is_panning = False
            self._last_pan_step_ms = 0.0
            self._set_drag_preview_mode(False)
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self._clear_all_snap_guide_lines()
        super().leaveEvent(event)

    def focusOutEvent(self, event):
        """视图失焦时取消尚未完成的交互。"""
        if self.is_dragging_line:
            self._cleanup_drag_state()
        if self._drag_preview_mode:
            self._is_panning = False
            self._last_pan_step_ms = 0.0
            self._set_drag_preview_mode(False)
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self._clear_all_snap_guide_lines()
        super().focusOutEvent(event)

    def _clear_all_snap_guide_lines(self):
        """清除所有卡片拖动状态和吸附辅助线。"""
        for card in self.cards.values():
            card._cancel_drag_state()

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

    def _same_card_id(self, left, right) -> bool:
        if left == right:
            return True
        try:
            return int(left) == int(right)
        except (TypeError, ValueError):
            return False

    def _desired_jump_target_card(self, card, action_key: str, target_key: str):
        if getattr(card, "restricted_outputs", False):
            return None
        if "跳转" not in str(card.parameters.get(action_key) or ""):
            return None
        target_id = card.parameters.get(target_key)
        if target_id is None or target_id == "":
            return None
        if target_id in self.cards:
            return self.cards[target_id]
        try:
            return self.cards.get(int(target_id))
        except (TypeError, ValueError):
            return None

    def _existing_jump_end_items(self, card, line_type: str):
        ends = []
        for conn in list(self.connections):
            if isinstance(conn, ConnectionLine) and conn.start_item is card and conn.line_type == line_type:
                ends.append(conn.end_item)
        return ends

    def _jump_connections_already_match(self, card) -> bool:
        desired_success = self._desired_jump_target_card(card, "on_success", "success_jump_target_id")
        desired_failure = self._desired_jump_target_card(card, "on_failure", "failure_jump_target_id")
        existing_success = self._existing_jump_end_items(card, ConnectionType.SUCCESS.value)
        existing_failure = self._existing_jump_end_items(card, ConnectionType.FAILURE.value)
        success_matches = (
            (desired_success is None and not existing_success)
            or (desired_success is not None and existing_success == [desired_success])
        )
        failure_matches = (
            (desired_failure is None and not existing_failure)
            or (desired_failure is not None and existing_failure == [desired_failure])
        )
        return success_matches and failure_matches

    def update_single_card_jump_connections(self, card_id: int):
        """
        更新单个卡片的跳转连线，避免每次参数变更都触发全量重建。
        这用于修改单个卡片的跳转参数时，避免 O(n) 的全量重建
        """
        card = self.cards.get(card_id)
        if not card:
            return
        if self._jump_connections_already_match(card):
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
            if connections_to_remove and not self._loading_workflow and not self._undoing_operation:
                self._mark_workflow_dirty()
            return  # 端口被限制，不创建连线

        desired_success = self._desired_jump_target_card(card, "on_success", "success_jump_target_id")
        if desired_success is not None:
            self.add_connection(card, desired_success, ConnectionType.SUCCESS.value)

        desired_failure = self._desired_jump_target_card(card, "on_failure", "failure_jump_target_id")
        if desired_failure is not None:
            self.add_connection(card, desired_failure, ConnectionType.FAILURE.value)

        if connections_to_remove and desired_success is None and desired_failure is None:
            if not self._loading_workflow and not self._undoing_operation:
                self._mark_workflow_dirty()

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
