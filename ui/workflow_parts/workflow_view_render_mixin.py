from .workflow_view_common import *

operation_logger = logging.getLogger("workflow.operations")


class WorkflowViewRenderMixin:

    def set_grid_enabled(self, enabled: bool):
        """设置网格显示开关。"""

        self._grid_enabled = enabled
        self.viewport().update()

    def is_grid_enabled(self) -> bool:
        """返回网格显示开关状态。"""

        return self._grid_enabled

    def is_card_tooltip_suppressed(self) -> bool:
        """判断是否应抑制卡片 Tooltip 显示。"""
        try:
            return bool(self._is_panning or QApplication.mouseButtons() != Qt.MouseButton.NoButton)
        except Exception:
            return bool(self._is_panning)

    def _hide_card_tooltip_overlay(self):
        """隐藏当前卡片 Tooltip 叠层。"""
        try:
            from ui.widgets.custom_tooltip import get_tooltip_manager
            get_tooltip_manager().hide()
        except Exception:
            pass

    def _clear_all_card_tooltips(self):
        """清理所有卡片 Tooltip。"""
        try:
            for card in self.cards.values():
                card.setToolTip("")
        except Exception:
            pass
        self._hide_card_tooltip_overlay()

    def set_card_snap_enabled(self, enabled: bool):
        """设置卡片吸附开关。"""

        self._card_snap_enabled = enabled

    def is_card_snap_enabled(self) -> bool:
        """返回卡片吸附开关状态。"""

        return self._card_snap_enabled

    def _get_card_cache_disable_threshold(self) -> int:
        """读取卡片缓存关闭阈值。"""

        raw_value = os.getenv("LCA_CARD_CACHE_DISABLE_THRESHOLD", "").strip()
        if not raw_value:
            return 96
        try:
            threshold = int(raw_value)
        except Exception:
            return 96
        return max(20, min(5000, threshold))

    def _get_card_shadow_disable_threshold(self) -> int:
        """读取卡片阴影渲染关闭阈值（超大工作流禁用阴影以降低图形缓存占用）。"""


        raw_value = os.getenv("LCA_CARD_SHADOW_DISABLE_THRESHOLD", "").strip()
        if not raw_value:
            return 96
        try:
            threshold = int(raw_value)
        except Exception:
            return 96
        return max(20, min(5000, threshold))

    def _has_active_connection_animation(self) -> bool:
        try:
            from ..workflow_parts.connection_line import get_line_animation_stats

            stats = get_line_animation_stats() or {}
            return bool(stats.get("timer_active")) and int(stats.get("registered_lines") or 0) > 0
        except Exception:
            return False

    def _has_active_card_animation(self) -> bool:
        try:
            stats = TaskCard.get_gradient_animation_stats() or {}
            return bool(stats.get("timer_active")) and int(stats.get("registered_cards") or 0) > 0
        except Exception:
            return False

    def _has_active_ui_animation(self) -> bool:
        return self._has_active_connection_animation() or self._has_active_card_animation()

    def _set_drag_preview_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._drag_preview_mode == enabled:
            return

        self._drag_preview_mode = enabled
        if enabled:
            self._drag_preview_saved_state = {
                "grid_enabled": bool(getattr(self, "_grid_enabled", False)),
                "viewport_update_mode": self.viewportUpdateMode(),
                "text_antialiasing": bool(self.renderHints() & QPainter.RenderHint.TextAntialiasing),
            }
            if getattr(self, "_grid_enabled", False):
                self._grid_enabled = False
            self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
            self.setRenderHint(QPainter.RenderHint.TextAntialiasing, False)
            self._last_pan_step_ms = 0.0
            try:
                TaskCard.set_force_overview_mode(True)
            except Exception:
                pass
            try:
                from ..workflow_parts.connection_line import set_force_overview_mode as _set_line_overview_mode
                _set_line_overview_mode(True)
            except Exception:
                pass
        else:
            saved = dict(self._drag_preview_saved_state or {})
            if "grid_enabled" in saved:
                self._grid_enabled = bool(saved.get("grid_enabled"))
            saved_update_mode = saved.get("viewport_update_mode")
            if saved_update_mode is not None:
                try:
                    self.setViewportUpdateMode(saved_update_mode)
                except Exception:
                    pass
            if "text_antialiasing" in saved:
                self.setRenderHint(
                    QPainter.RenderHint.TextAntialiasing,
                    bool(saved.get("text_antialiasing")),
                )
            try:
                TaskCard.set_force_overview_mode(False)
            except Exception:
                pass
            try:
                from ..workflow_parts.connection_line import set_force_overview_mode as _set_line_overview_mode
                _set_line_overview_mode(False)
            except Exception:
                pass
            self._drag_preview_saved_state = {}
            self._update_card_render_cache_policy()

        try:
            self.viewport().update()
        except Exception:
            pass

    def _on_render_cache_guard_tick(self) -> None:
        try:
            self._update_card_render_cache_policy()
            if self._has_active_ui_animation():
                QPixmapCache.clear()
        except Exception:
            pass

    def _update_card_render_cache_policy(self) -> None:
        """
        根据卡片数量动态调整渲染缓存策略，平衡性能与内存占用。
        """
        try:
            card_count = len(self.cards)
        except Exception:
            return

        disable_cache = card_count >= self._get_card_cache_disable_threshold()
        if self._has_active_ui_animation():
            disable_cache = True
        disable_shadow = card_count >= self._get_card_shadow_disable_threshold()
        target_mode = (
            QGraphicsItem.CacheMode.NoCache
            if disable_cache
            else QGraphicsItem.CacheMode.DeviceCoordinateCache
        )

        for card in list(self.cards.values()):
            try:
                if card.cacheMode() != target_mode:
                    card.setCacheMode(target_mode)
            except Exception:
                continue

            try:
                target_shadow_enabled = not disable_shadow
                if hasattr(card, "set_shadow_rendering_enabled"):
                    current_shadow_enabled = bool(getattr(card, "_shadow_rendering_enabled", True))
                    if current_shadow_enabled != target_shadow_enabled:
                        card.set_shadow_rendering_enabled(target_shadow_enabled)
                elif hasattr(card, "shadow") and card.shadow is not None:
                    if bool(card.shadow.isEnabled()) != target_shadow_enabled:
                        card.shadow.setEnabled(target_shadow_enabled)
            except Exception:
                continue

        should_clear_pixmap_cache = (
            (self._cache_policy_cache_disabled is False and disable_cache is True)
            or (self._cache_policy_shadow_disabled is False and disable_shadow is True)
        )
        self._cache_policy_cache_disabled = disable_cache
        self._cache_policy_shadow_disabled = disable_shadow
        if should_clear_pixmap_cache:
            try:
                QPixmapCache.clear()
            except Exception:
                pass
        try:
            viewport_mode = QGraphicsView.ViewportUpdateMode.FullViewportUpdate
            if self.viewportUpdateMode() != viewport_mode:
                self.setViewportUpdateMode(viewport_mode)
        except Exception:
            pass

    def drawBackground(self, painter: QPainter, rect: QRectF):
        """绘制背景网格。"""
        super().drawBackground(painter, rect)

        if not self._grid_enabled:
            return

        # Skip grid dots when zoomed out too far.
        transform = self.transform()
        zoom_level = transform.m11()
        if zoom_level < 0.6:
            return

        # Pick grid-dot color based on current theme.
        try:
            from themes import get_theme_manager
            theme_manager = get_theme_manager()
            is_dark = theme_manager.is_dark_mode()
            if is_dark:
                dot_color = QColor(90, 90, 90, 110)
            else:
                dot_color = QColor(170, 170, 170, 120)
        except Exception:
            dot_color = QColor(170, 170, 170, 120)

        spacing = self._grid_spacing
        dot_radius = self._grid_dot_size / 2.0

        left = int(rect.left()) - (int(rect.left()) % spacing)
        top = int(rect.top()) - (int(rect.top()) % spacing)

        # Guard against expensive drawing over huge areas.
        max_width = rect.width()
        max_height = rect.height()
        if max_width * max_height > 2000000:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(dot_color))

        x = left
        while x < rect.right():
            y = top
            while y < rect.bottom():
                painter.drawEllipse(QPointF(x, y), dot_radius, dot_radius)
                y += spacing
            x += spacing

        painter.restore()

    def _is_workflow_running(self) -> bool:
        """从主窗口任务状态管理器读取工作流运行状态。"""
        main_window = self.main_window
        if main_window is None:
            raise RuntimeError("工作流视图未绑定主窗口")

        state_manager = getattr(main_window, "task_state_manager", None)
        if state_manager is None:
            raise RuntimeError("主窗口未配置任务状态管理器")

        state = state_manager.get_current_state()
        if state not in {"starting", "running", "stopping", "stopped"}:
            raise RuntimeError(f"未知的任务运行状态: {state}")
        return state != "stopped"

    def _block_edit_if_running(self, operation_name: str) -> bool:
        """工作流非停止状态时拒绝编辑操作。"""
        if not isinstance(operation_name, str) or not operation_name.strip():
            raise TypeError("编辑操作名称必须是非空字符串")
        if not self._is_workflow_running():
            return False

        operation_logger.warning("[编辑拦截] 工作流运行中，已拒绝：%s", operation_name)
        return True

    def _refresh_thread_start_custom_names(self):
        """按当前起点数量统一命名：线程起点/2/3..."""
        try:
            start_cards = [
                card for card in self.cards.values()
                if self._is_start_task_type(getattr(card, "task_type", ""))
            ]
            start_cards.sort(key=lambda c: c.card_id)
            for idx, card in enumerate(start_cards, 1):
                desired_name = f"线程起点{idx}"
                if getattr(card, "custom_name", None) != desired_name:
                    card.set_custom_name(desired_name)
        except Exception as e:
            logger.warning(f"刷新线程起点名称失败: {e}")

    @staticmethod
    def _is_start_task_type(task_type: Any) -> bool:
        return is_thread_start_task_type(task_type)

    @staticmethod
    def _validate_special_connection_rule(start_card: TaskCard, end_card: TaskCard, line_type: str) -> Optional[str]:
        start_task_type = getattr(start_card, "task_type", "")
        end_task_type = getattr(end_card, "task_type", "")
        if is_valid_thread_window_limit_connection(start_task_type, end_task_type, line_type):
            return None
        if is_thread_window_limit_task_type(start_task_type):
            return "线程窗口限制只能用顺序连线连接到线程起点"
        return None

    def wheelEvent(self, event: QWheelEvent):
        """Handles mouse wheel events for zooming."""
        delta = event.angleDelta().y()

        if delta > 0:
            # Zoom in
            scale_factor = self.zoom_factor_base
        elif delta < 0:
            # Zoom out
            scale_factor = 1.0 / self.zoom_factor_base
        else:
            # No vertical scroll
            super().wheelEvent(event) # Pass to base class if no zoom
            return

        # 【性能优化】手动处理缩放锚点，保持鼠标位置不变
        old_pos = self.mapToScene(event.position().toPoint())
        self.scale(scale_factor, scale_factor)
        new_pos = self.mapToScene(event.position().toPoint())
        delta_pos = new_pos - old_pos
        self.translate(delta_pos.x(), delta_pos.y())

        event.accept()

        # 【性能优化】通知连线动画系统当前缩放级别
        self._notify_zoom_level_changed()

    def fit_view_to_items(self):
        """Adjusts the view to fit all items in the scene with padding."""
        if self.scene.items(): # Only fit if there are items
            items_rect = self.scene.itemsBoundingRect()
            # Add padding
            padded_rect = items_rect.adjusted(-FIT_VIEW_PADDING, -FIT_VIEW_PADDING, 
                                                FIT_VIEW_PADDING, FIT_VIEW_PADDING)
            self.fitInView(padded_rect, Qt.AspectRatioMode.KeepAspectRatio)
        else:
            # 注释已清理（原注释编码损坏）
            self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio) # Fit to initial rect or default

    def _deferred_center_view(self, center_point: QPointF):
        """Deferred function to center the view."""
        debug_print(f"  [LOAD_DEBUG] Entering DEFERRED center function. Target: {center_point}.") # Log entry
        # --- Log BEFORE centerOn --- 
        try:
            pre_center_vp_center = self.viewport().rect().center()
            pre_center_scene_center = self.mapToScene(pre_center_vp_center)
            debug_print(f"  [LOAD_DEBUG] Center BEFORE centerOn call: {pre_center_scene_center}")
        except Exception as pre_e:
            debug_print(f"  [LOAD_DEBUG] Error getting center BEFORE call: {pre_e}")
        # --- END Log BEFORE ---

        try:
            # --- ADDED: Force scene update before centering ---
            debug_print("  [LOAD_DEBUG] Calling self.scene.update() before centerOn.")
            self.scene.update()
            QApplication.processEvents() # Also process events after update, before centerOn
            debug_print("  [LOAD_DEBUG] Finished scene update and processEvents.")
            # --- END ADDED ---

            self.centerOn(center_point)
            # --- Log IMMEDIATELY AFTER centerOn (BEFORE processEvents) ---
            try:
                post_center_vp_center = self.viewport().rect().center()
                post_center_scene_center = self.mapToScene(post_center_vp_center)
                debug_print(f"  [LOAD_DEBUG] Center IMMEDIATELY AFTER centerOn call: {post_center_scene_center}")
            except Exception as post_e:
                debug_print(f"  [LOAD_DEBUG] Error getting center IMMEDIATELY AFTER call: {post_e}")
            # --- END Log AFTER ---

            # --- Verify actual center point AFTER deferred centerOn AND processEvents --- 
            debug_print("  [LOAD_DEBUG] Calling processEvents...")
            QApplication.processEvents() # Try processing pending events again
            debug_print("  [LOAD_DEBUG] Finished processEvents.")
            current_viewport_center_view = self.viewport().rect().center()
            actual_scene_center = self.mapToScene(current_viewport_center_view)
            debug_print(f"  [LOAD_DEBUG] VERIFY (Deferred - AFTER processEvents): Actual scene center: {actual_scene_center}")
        except Exception as deferred_center_e:
             logger.error(f"Error during deferred centerOn or verification: {deferred_center_e}", exc_info=True)

    def resizeEvent(self, event: QResizeEvent):
        """Logs the view center when the view is resized."""
        super().resizeEvent(event) # Call base implementation first
        try:
            center_point = self.mapToScene(self.viewport().rect().center())
            debug_print(f"  [VIEW_DEBUG] resizeEvent: Current scene center = {center_point}")
        except Exception as e:
            debug_print(f"  [VIEW_DEBUG] resizeEvent: Error getting center point: {e}")

    def showEvent(self, event: QShowEvent):
        """Logs the view center when the view is shown."""
        super().showEvent(event) # Call base implementation first
        try:
            center_point = self.mapToScene(self.viewport().rect().center())
            debug_print(f"  [VIEW_DEBUG] showEvent: Current scene center = {center_point}")
        except Exception as e:
            debug_print(f"  [VIEW_DEBUG] showEvent: Error getting center point: {e}")
        from ..workflow_parts.connection_line import refresh_line_animation_state
        refresh_line_animation_state()
        try:
            self._update_card_render_cache_policy()
        except Exception:
            pass

    def zoomIn(self):
        self.scale(self.zoom_factor_base, self.zoom_factor_base)
        # 【性能优化】通知连线动画系统当前缩放级别
        self._notify_zoom_level_changed()

    def zoomOut(self):
        self.scale(1 / self.zoom_factor_base, 1 / self.zoom_factor_base)
        # 【性能优化】通知连线动画系统当前缩放级别
        self._notify_zoom_level_changed()

    def _notify_zoom_level_changed(self):
        """通知连线动画系统当前缩放级别。"""
        from ..workflow_parts.connection_line import update_zoom_level
        update_zoom_level(self.transform().m11())

    def refresh_all_cards_theme(self):
        """刷新所有卡片的主题颜色"""
        import logging
        try:
            logging.info(f"[THEME_REFRESH] 开始刷新 {len(self.cards)} 个卡片的主题")
            for card_id, card in self.cards.items():
                if hasattr(card, 'refresh_theme'):
                    card.refresh_theme()
                    logging.debug(f"[THEME_REFRESH] 已刷新卡片 {card_id}")
            logging.info("[THEME_REFRESH] 完成刷新所有卡片的主题")
        except Exception as e:
            logging.error(f"[THEME_REFRESH] 刷新卡片主题时出错: {e}", exc_info=True)

    def _handle_scroll_change(self, value: int):
        """Called when scroll bars change. Checks if view is near scene edge and expands if needed."""
        if self._is_panning or self._drag_preview_mode:
            return
        # 注释已清理（原注释编码损坏）
        margin = 50.0

        # Get visible rect in scene coordinates
        visible_rect_scene = self.mapToScene(self.viewport().rect()).boundingRect()
        current_scene_rect = self.sceneRect()

        new_scene_rect = QRectF(current_scene_rect)
        expanded = False

        # 注释已清理（原注释编码损坏）
        # Check and expand left boundary
        overflow_left = (current_scene_rect.left() + margin) - visible_rect_scene.left()
        if overflow_left > 0:
            new_scene_rect.setLeft(current_scene_rect.left() - overflow_left - margin)
            expanded = True

        # Check and expand top boundary
        overflow_top = (current_scene_rect.top() + margin) - visible_rect_scene.top()
        if overflow_top > 0:
            new_scene_rect.setTop(current_scene_rect.top() - overflow_top - margin)
            expanded = True

        # Check and expand right boundary
        overflow_right = visible_rect_scene.right() - (current_scene_rect.right() - margin)
        if overflow_right > 0:
            new_scene_rect.setRight(current_scene_rect.right() + overflow_right + margin)
            expanded = True

        # Check and expand bottom boundary
        overflow_bottom = visible_rect_scene.bottom() - (current_scene_rect.bottom() - margin)
        if overflow_bottom > 0:
            new_scene_rect.setBottom(current_scene_rect.bottom() + overflow_bottom + margin)
            expanded = True

        if expanded:
            self.scene.setSceneRect(new_scene_rect)

    def _handle_card_clicked(self, clicked_card_id: int):
        """点击卡片后仅闪烁与其直接相连的卡片。"""
        if isinstance(clicked_card_id, bool) or not isinstance(clicked_card_id, int) or clicked_card_id < 0:
            raise TypeError("被点击的卡片 ID 必须是非负整数")

        self._stop_all_flashing()
        clicked_card = self.cards.get(clicked_card_id)
        if clicked_card is None:
            operation_logger.warning("[卡片关系] 点击被拒绝，卡片不存在 card_id=%s", clicked_card_id)
            return False
        if clicked_card.scene() is not self.scene:
            raise RuntimeError(f"卡片 {clicked_card_id} 不属于当前工作流场景")

        connected_card_ids = set()
        for conn in self.connections:
            if not isinstance(conn, ConnectionLine):
                raise TypeError("工作流连线清单包含无效对象")
            if conn.start_item == clicked_card:
                target_card = conn.end_item
            elif conn.end_item == clicked_card:
                target_card = conn.start_item
            else:
                continue
            if target_card is None or target_card.card_id == clicked_card_id:
                continue
            if target_card.scene() is not self.scene:
                raise RuntimeError(f"连线目标卡片 {target_card.card_id} 不属于当前工作流场景")
            if target_card.card_id not in self.cards or self.cards[target_card.card_id] is not target_card:
                raise RuntimeError(f"连线目标卡片 {target_card.card_id} 未登记在当前工作流视图")
            connected_card_ids.add(target_card.card_id)

        for card_id in sorted(connected_card_ids):
            card = self.cards[card_id]
            card.flash()
            self.flashing_card_ids.add(card_id)

        if connected_card_ids:
            operation_logger.info(
                "[卡片关系] 已闪烁相连卡片，起点=%s，数量=%s",
                clicked_card_id,
                len(connected_card_ids),
            )
        return True

    def _stop_all_flashing(self):
        """停止所有已登记的关系闪烁卡片。"""
        if not self.flashing_card_ids:
            return 0

        ids_to_stop = sorted(self.flashing_card_ids)
        cards_to_stop = []
        for card_id in ids_to_stop:
            card = self.cards.get(card_id)
            if card is None:
                raise RuntimeError(f"闪烁卡片 {card_id} 未登记在当前工作流视图")
            if card.scene() is not self.scene:
                raise RuntimeError(f"闪烁卡片 {card_id} 不属于当前工作流场景")
            cards_to_stop.append(card)

        self.flashing_card_ids.clear()
        for card in cards_to_stop:
            card.stop_flash()

        operation_logger.info("[卡片关系] 已停止闪烁，数量=%s", len(ids_to_stop))
        return len(ids_to_stop)

    def _handle_open_sub_workflow(self, workflow_file: str):
        """处理子工作流打开请求 - 转发信号给上层处理。"""
        logger.info(f"[子工作流] 请求打开: {workflow_file}")
        if workflow_file:
            self.open_sub_workflow_requested.emit(workflow_file)
        else:
            logger.warning(f"[子工作流] 子工作流路径为空: {workflow_file}")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "无法打开子工作流",
                "未配置子工作流文件路径。"
            )
