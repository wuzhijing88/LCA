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

    def _should_suppress_canvas_effects(self) -> bool:
        if getattr(self, "_loading_workflow", False):
            return True
        try:
            from ..workflow_parts.connection_line import get_line_animation_stats

            reasons = set((get_line_animation_stats() or {}).get("pause_reasons") or [])
        except Exception:
            return False
        return bool(reasons & {"workflow_load", "workflow_tab_insert"})

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
            self._refresh_viewport_animations()

        try:
            self.viewport().update()
        except Exception:
            pass

    def _on_render_cache_guard_tick(self) -> None:
        try:
            if not self.isVisible():
                return
            self._sync_scene_rect_to_content()
            self._refresh_viewport_animations()
        except Exception:
            pass

    def _update_card_render_cache_policy(self) -> None:
        """
        根据卡片数量和是否在视口内调整缓存与阴影，画面外的卡片卸掉图形资源。
        """
        try:
            card_count = len(self.cards)
        except Exception:
            return

        suppress_effects = self._should_suppress_canvas_effects()
        disable_cache = card_count >= self._get_card_cache_disable_threshold()
        if suppress_effects:
            disable_cache = True
        disable_shadow = card_count >= self._get_card_shadow_disable_threshold()
        if suppress_effects:
            disable_shadow = True

        try:
            zoom = float(self.transform().m11())
        except Exception:
            zoom = 1.0
        last_zoom = getattr(self, "_card_cache_zoom", None)
        rebuild_cache = last_zoom is not None and abs(zoom - last_zoom) > 1e-4
        self._card_cache_zoom = zoom

        viewport_rect_cache = {}
        scene_views_cache = {}
        for card in list(self.cards.values()):
            in_view = False
            try:
                in_view = TaskCard._is_card_in_viewport(card, viewport_rect_cache, scene_views_cache)
            except Exception:
                in_view = False
            card_disable_shadow = disable_shadow or not in_view
            # 设备坐标缓存按当前像素烘焙，视图缩放不会自动重建；再叠阴影会裁切或看起来像另一种缩放。
            card_disable_cache = disable_cache or not in_view or not card_disable_shadow
            target_mode = (
                QGraphicsItem.CacheMode.NoCache
                if card_disable_cache
                else QGraphicsItem.CacheMode.DeviceCoordinateCache
            )
            shadow_changed = False
            try:
                target_shadow_enabled = not card_disable_shadow
                current_shadow_enabled = bool(getattr(card, "_shadow_rendering_enabled", True))
                shadow_changed = current_shadow_enabled != target_shadow_enabled
                if shadow_changed:
                    card.set_shadow_rendering_enabled(target_shadow_enabled)
            except Exception:
                shadow_changed = False

            try:
                self._apply_card_cache_mode(
                    card,
                    target_mode,
                    rebuild=rebuild_cache or shadow_changed,
                )
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
        if getattr(self, "_drag_preview_mode", False):
            return
        try:
            viewport_mode = (
                QGraphicsView.ViewportUpdateMode.FullViewportUpdate
                if suppress_effects
                else QGraphicsView.ViewportUpdateMode.SmartViewportUpdate
            )
            if self.viewportUpdateMode() != viewport_mode:
                self.setViewportUpdateMode(viewport_mode)
        except Exception:
            pass

    def _apply_card_cache_mode(self, card, target_mode, *, rebuild: bool) -> None:
        no_cache = QGraphicsItem.CacheMode.NoCache
        current = card.cacheMode()
        if target_mode == no_cache:
            if current != no_cache:
                card.setCacheMode(no_cache)
            return
        if current != target_mode or rebuild:
            if current != no_cache:
                card.setCacheMode(no_cache)
            card.setCacheMode(target_mode)

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

    def _scene_alive_for_center(self):
        from shiboken6 import isValid

        try:
            if not isValid(self):
                return None
            scene = getattr(self, "scene", None)
            if scene is None or not isValid(scene):
                return None
            return scene
        except RuntimeError:
            return None

    def _place_start_card_at_viewport_top_left(self):
        from task_workflow.thread_start import is_thread_start_task_type

        scene = self._scene_alive_for_center()
        if scene is None:
            return
        starts = [
            card
            for card in self.cards.values()
            if is_thread_start_task_type(getattr(card, "task_type", ""))
        ]
        if len(starts) != 1:
            return
        viewport = self.viewport()
        if viewport is None or viewport.width() <= 0 or viewport.height() <= 0:
            return
        margin = FIT_VIEW_PADDING
        top_left = self.mapToScene(margin, margin)
        x = top_left.x()
        y = top_left.y()
        spacing = int(getattr(self, "_grid_spacing", 20) or 20)
        if getattr(self, "_grid_enabled", False) and spacing > 0:
            x = round(x / spacing) * spacing
            y = round(y / spacing) * spacing
        starts[0].setPos(x, y)
        padding = FIT_VIEW_PADDING * 2
        needed = starts[0].sceneBoundingRect().adjusted(-padding, -padding, padding, padding)
        scene.setSceneRect(scene.sceneRect().united(needed))
        self.workflow_metadata.pop("place_start_at_viewport", None)

    def _deferred_center_view(self, center_point: QPointF):
        """Deferred function to center the view."""
        scene = self._scene_alive_for_center()
        if scene is None:
            return
        debug_print(f"  [LOAD_DEBUG] Entering DEFERRED center function. Target: {center_point}.")
        try:
            pre_center_vp_center = self.viewport().rect().center()
            pre_center_scene_center = self.mapToScene(pre_center_vp_center)
            debug_print(f"  [LOAD_DEBUG] Center BEFORE centerOn call: {pre_center_scene_center}")
        except Exception as pre_e:
            debug_print(f"  [LOAD_DEBUG] Error getting center BEFORE call: {pre_e}")

        try:
            scene.update()
            self.centerOn(center_point)
            self._refresh_viewport_animations()
        except RuntimeError:
            if self._scene_alive_for_center() is None:
                return
            logger.error("延迟居中失败", exc_info=True)
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
        self._refresh_viewport_animations()

    def showEvent(self, event: QShowEvent):
        """Logs the view center when the view is shown."""
        super().showEvent(event) # Call base implementation first
        try:
            center_point = self.mapToScene(self.viewport().rect().center())
            debug_print(f"  [VIEW_DEBUG] showEvent: Current scene center = {center_point}")
        except Exception as e:
            debug_print(f"  [VIEW_DEBUG] showEvent: Error getting center point: {e}")
        self._refresh_viewport_animations()

    def hideEvent(self, event: QHideEvent):
        super().hideEvent(event)
        self._refresh_viewport_animations(force=True)

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
        self._refresh_viewport_animations()

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

    def _sync_scene_rect_to_content(self) -> None:
        """把场景矩形限制在卡片范围加两屏边距，避免长时间平移把场景撑得无限大。"""
        if self._is_panning or getattr(self, "_drag_preview_mode", False):
            return
        if getattr(self, "_loading_workflow", False) or getattr(self, "_rerouting_connections", False):
            return
        scene = getattr(self, "scene", None)
        if scene is None:
            return
        viewport = self.viewport()
        if viewport is None or viewport.width() <= 0 or viewport.height() <= 0:
            return
        visible = self.mapToScene(viewport.rect()).boundingRect()
        vw = max(float(visible.width()), 1.0)
        vh = max(float(visible.height()), 1.0)
        items = scene.itemsBoundingRect()
        if items.isNull() or not items.isValid() or items.width() <= 0 or items.height() <= 0:
            target = QRectF(
                visible.center().x() - vw,
                visible.center().y() - vh,
                vw * 2.0,
                vh * 2.0,
            )
        else:
            target = items.adjusted(-vw * 2.0, -vh * 2.0, vw * 2.0, vh * 2.0)
        current = scene.sceneRect()
        if (
            abs(current.x() - target.x()) < 1.0
            and abs(current.y() - target.y()) < 1.0
            and abs(current.width() - target.width()) < 1.0
            and abs(current.height() - target.height()) < 1.0
        ):
            return
        scene.setSceneRect(target)

    def _refresh_viewport_animations(self, *, force: bool = False) -> None:
        """按当前视口装入动画和图形资源：看得见的才动，看不见的卸掉。"""
        if not force and getattr(self, "_loading_workflow", False):
            return
        if not force and getattr(self, "_drag_preview_mode", False):
            return
        try:
            TaskCard.sync_viewport_animations(self)
        except Exception:
            pass
        from ..workflow_parts.connection_line import refresh_line_animation_state
        refresh_line_animation_state()
        try:
            self._update_card_render_cache_policy()
        except Exception:
            pass

    def _handle_scroll_change(self, value: int):
        """滚动后同步场景范围，并按可见区域开关动画。"""
        del value
        if self._is_panning or self._drag_preview_mode:
            return
        if getattr(self, "_loading_workflow", False) or getattr(self, "_rerouting_connections", False):
            return
        self._sync_scene_rect_to_content()
        self._refresh_viewport_animations()

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
