from .workflow_view_common import *


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
        """检查工作流是否正在运行（基于运行按钮文本状态）。"""
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()

            # 注释已清理（原注释编码损坏）
            # 如果按钮显示"停止"或"停止多窗口执行"，说明工作流正在运行
            main_window = self.main_window
            if not main_window and app:
                # 查找主窗口
                for widget in app.allWidgets():
                    if hasattr(widget, 'run_action'):
                        main_window = widget
                        self.main_window = main_window
                        break

            if main_window and hasattr(main_window, 'run_action'):
                button_text = main_window.run_action.text()
                # 如果按钮显示"停止"相关文本，说明正在运行
                if "停止" in button_text:
                    return True
                # 如果按钮显示"运行"相关文本，说明已停止
                return False

            # 方法2: 备用方案 - 检查task_state_manager
            if app and hasattr(app, 'task_state_manager') and app.task_state_manager:
                state = app.task_state_manager.get_current_state()
                return state in ["starting", "running"]

        except Exception as e:
            logger.error(f"检查任务运行状态时发生错误: {e}")

        # 如果无法确定，默认允许操作（返回False）
        return False

    def _block_edit_if_running(self, operation_name: str) -> bool:
        """如果工作流正在运行，阻止编辑操作并显示提示 - 增强版本（带防重入保护）

        Args:
            operation_name: 操作名称，用于错误提示

        Returns:
            bool: True如果操作被阻止，False如果可以继续
        """
        # 防重入检查：如果正在显示对话框，立即返回True阻止操作
        if self._is_showing_block_dialog:
            logger.debug(f"检测到重入调用，阻止{operation_name}操作（防止循环弹窗）")
            return True

        try:
            # 注释已清理（原注释编码损坏）
            if self._is_workflow_running():
                logger.warning(f"尝试在任务运行期间执行{operation_name}操作")

                # 注释已清理（原注释编码损坏）
                if hasattr(self, 'main_window') and self.main_window:
                    if hasattr(self.main_window, 'step_detail_label'):
                        self.main_window.step_detail_label.setText(f"【警告】工作流正在执行中，无法进行{operation_name}操作")
                        self.main_window.step_detail_label.setStyleSheet("""
                            #stepDetailLabel {
                                background-color: rgba(180, 180, 180, 180);
                                color: #FF0000;
                                font-weight: bold;
                                border-radius: 5px;
                                padding: 8px;
                            }
                        """)
                        # 3秒后自动恢复
                        from PySide6.QtCore import QTimer
                        QTimer.singleShot(3000, lambda: self.main_window.step_detail_label.setText("任务执行中..."))

                return True

            # 注释已清理（原注释编码损坏）
            if hasattr(self, 'main_window') and self.main_window:
                if hasattr(self.main_window, 'task_state_manager'):
                    current_state = self.main_window.task_state_manager.get_current_state()
                    if current_state in ["starting", "running", "stopping"]:
                        logger.warning(f"任务状态为 {current_state}，阻止 {operation_name} 操作")

                        # 在底部状态栏显示警告
                        if hasattr(self.main_window, 'step_detail_label'):
                            self.main_window.step_detail_label.setText(f"【警告】任务{current_state}中，无法{operation_name}")
                            self.main_window.step_detail_label.setStyleSheet("""
                                #stepDetailLabel {
                                    background-color: rgba(180, 180, 180, 180);
                                    color: #FF0000;
                                    font-weight: bold;
                                    border-radius: 5px;
                                    padding: 8px;
                                }
                            """)
                            from PySide6.QtCore import QTimer
                            QTimer.singleShot(3000, lambda: self.main_window.step_detail_label.setText("任务执行中..."))

                        return True

                    # 注释已清理（原注释编码损坏）
                    if self.main_window.task_state_manager.is_state_changing():
                        logger.warning(f"任务状态正在改变，阻止 {operation_name} 操作")

                        # 在底部状态栏显示警告
                        if hasattr(self.main_window, 'step_detail_label'):
                            self.main_window.step_detail_label.setText(f"任务状态正在改变，无法{operation_name}")
                            self.main_window.step_detail_label.setStyleSheet("""
                                #stepDetailLabel {
                                    background-color: rgba(180, 180, 180, 180);
                                    color: #FF0000;
                                    font-weight: bold;
                                    border-radius: 5px;
                                    padding: 8px;
                                }
                            """)
                            from PySide6.QtCore import QTimer
                            QTimer.singleShot(3000, lambda: self.main_window.step_detail_label.setText("任务执行中..."))

                        return True

            # 注释已清理（原注释编码损坏）
            executing_cards = []
            for card_id, card in self.cards.items():
                if hasattr(card, 'execution_state') and card.execution_state in ['running', 'executing']:
                    executing_cards.append(card_id)
                    # 输出详细信息用于调试
                    logger.warning(f"卡片 {card_id} 状态异常：execution_state={card.execution_state}")

            if executing_cards:
                # 注释已清理（原注释编码损坏）
                is_really_running = False
                if hasattr(self, 'executor') and self.executor:
                    is_really_running = self.executor.isRunning()

                # 如果执行器没有在运行，说明卡片状态是脏数据，强制重置
                if not is_really_running:
                    logger.warning(f"检测到卡片状态异常（执行器未运行但卡片状态为执行中），强制重置卡片状态: {executing_cards}")
                    for card_id in executing_cards:
                        card = self.cards.get(card_id)
                        if card and hasattr(card, 'set_execution_state'):
                            try:
                                card.set_execution_state('idle')
                                logger.info(f"已强制重置卡片 {card_id} 状态为 idle")
                            except Exception as e:
                                logger.error(f"强制重置卡片 {card_id} 状态失败: {e}")
                    # 重置后不再阻止操作
                    return False

                # 注释已清理（原注释编码损坏）
                logger.warning(f"发现执行中的卡片 {executing_cards}，阻止 {operation_name} 操作")

                # 设置防重入标志
                self._is_showing_block_dialog = True
                try:
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(self, "操作被阻止",
                                      f"发现正在执行的卡片，请等待完成后再进行{operation_name}操作")
                finally:
                    # 确保对话框关闭后重置标志
                    self._is_showing_block_dialog = False
                return True

            return False

        except Exception as e:
            logger.error(f"检查运行状态时发生错误: {e}")
            # 出错时采用保守策略，阻止操作（但不弹窗，避免循环）
            logger.warning(f"由于检查失败，静默阻止{operation_name}操作（防止循环弹窗）")
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
            pass

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
            debug_print(f"  [LOAD_DEBUG] Calling self.scene.update() before centerOn.")
            self.scene.update()
            QApplication.processEvents() # Also process events after update, before centerOn
            debug_print(f"  [LOAD_DEBUG] Finished scene update and processEvents.")
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
            debug_print(f"  [LOAD_DEBUG] Calling processEvents...")
            QApplication.processEvents() # Try processing pending events again
            debug_print(f"  [LOAD_DEBUG] Finished processEvents.")
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
        try:
            from ..workflow_parts.connection_line import restart_animation_timer
            restart_animation_timer()
        except Exception:
            pass
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
        """通知连线动画系统当前缩放级别，用于性能优化"""
        try:
            # 注释已清理（原注释编码损坏）
            transform = self.transform()
            # m11() 是 x 方向的缩放比例
            zoom_level = transform.m11()
            # 通知连线动画系统
            from ..workflow_parts.connection_line import update_zoom_level
            update_zoom_level(zoom_level)
        except Exception as e:
            # 忽略错误，不影响正常功能
            pass

    def refresh_all_cards_theme(self):
        """刷新所有卡片的主题颜色"""
        import logging
        try:
            logging.info(f"[THEME_REFRESH] 开始刷新 {len(self.cards)} 个卡片的主题")
            for card_id, card in self.cards.items():
                if hasattr(card, 'refresh_theme'):
                    card.refresh_theme()
                    logging.debug(f"[THEME_REFRESH] 已刷新卡片 {card_id}")
            logging.info(f"[THEME_REFRESH] 完成刷新所有卡片的主题")
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
        """Handles card clicks: stops previous flashing, starts new flashing."""
        logger.debug(f"_handle_card_clicked: Received click from Card ID {clicked_card_id}")

        # 1. Stop any currently flashing cards
        self._stop_all_flashing()

        # 2. Find neighbors of the clicked card
        clicked_card = self.cards.get(clicked_card_id)
        if not clicked_card:
            logger.warning("  在视图中未找到被点击的卡片。")
            return

        connected_card_ids_to_flash = set()

        # Iterate through connections in the view to find connected cards
        for conn in self.connections:
            if isinstance(conn, ConnectionLine):
                target_card_to_flash = None
                if conn.start_item == clicked_card and conn.end_item:
                    target_card_to_flash = conn.end_item
                elif conn.end_item == clicked_card and conn.start_item:
                    target_card_to_flash = conn.start_item
                
                if target_card_to_flash and target_card_to_flash.card_id != clicked_card_id:
                    connected_card_ids_to_flash.add(target_card_to_flash.card_id)

        if not connected_card_ids_to_flash:
             logger.debug(f"  Card {clicked_card_id} has no connected cards to flash.")
             return

        # 3. Start flashing neighbors and track them
        logger.info(f"  Starting flash for {len(connected_card_ids_to_flash)} cards connected to Card {clicked_card_id}: {connected_card_ids_to_flash}")
        for card_id_to_flash in connected_card_ids_to_flash:
            card_to_flash = self.cards.get(card_id_to_flash)
            if card_to_flash and hasattr(card_to_flash, 'flash'):
                card_to_flash.flash() # Call the persistent flash start
                self.flashing_card_ids.add(card_id_to_flash) # Add to tracking set
            else:
                 logger.warning(f"    Could not find card {card_id_to_flash} or it has no flash method.")

    def _stop_all_flashing(self):
        """Stops flashing on all currently tracked flashing cards."""
        if not self.flashing_card_ids:
            return
        debug_print(f"  [FLASH_DEBUG] Stopping flash for cards: {self.flashing_card_ids}")
        ids_to_stop = list(self.flashing_card_ids) # Iterate a copy
        self.flashing_card_ids.clear() # Clear the set immediately
        for card_id in ids_to_stop:
            try:
                card = self.cards.get(card_id)
                if card and hasattr(card, 'stop_flash'):
                    card.stop_flash()
                    debug_print(f"    [FLASH_DEBUG] 成功停止卡片 {card_id} 的闪烁")
                elif card_id not in self.cards:
                    debug_print(f"    [FLASH_DEBUG] 卡片 {card_id} 已不存在，跳过停止闪烁")
                else:
                    debug_print(f"    [FLASH_DEBUG] 卡片 {card_id} 没有 stop_flash 方法")
            except Exception as e:
                debug_print(f"    [FLASH_DEBUG] 停止卡片 {card_id} 闪烁时出错: {e}")
                logger.warning(f"停止卡片 {card_id} 闪烁时出错: {e}")

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
