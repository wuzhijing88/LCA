from .workflow_view_common import *


class WorkflowViewConnectionDragMixin:
    """工作流画布的连线拖拽、选择和平移交互。"""

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
