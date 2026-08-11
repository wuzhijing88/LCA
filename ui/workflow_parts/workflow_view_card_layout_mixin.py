from .workflow_view_common import *


class WorkflowViewCardLayoutMixin:

    def add_task_card(self, x: float, y: float, task_type: str = "未知", card_id: Optional[int] = None, parameters: Optional[dict] = None) -> Optional[TaskCard]:
        """Adds a new task card to the scene."""
        # --- ADDED: Debugging ---
        logger.debug(f"DEBUG [add_task_card]: Received task_type='{task_type}', card_id={card_id}")
        logger.debug(f"DEBUG [add_task_card]: Available task module keys: {list(self.task_modules.keys())}")
        # --- END ADDED ---

        # <<< MODIFIED: Lookup Task Class from task_modules >>>
        try:
            task_info = self.task_modules.get(task_type)
        except Exception as module_err:
            logger.warning(f"加载任务模块失败: task_type={task_type}, error={module_err}", exc_info=True)
            return None
        if task_info is None:
            debug_print(f"错误：未知的任务类型或模块 '{task_type}'")
            return None

        # Determine the card ID
        if card_id is None: # Generating new card ID
            # Ensure the generated ID is higher than any loaded ID
            current_id = max(self._next_card_id, self._max_loaded_id + 1)
            self._next_card_id = current_id + 1
        else: # Using provided card ID during loading
            current_id = card_id
            # Update the maximum loaded ID seen so far
            self._max_loaded_id = max(self._max_loaded_id, current_id)
            # Ensure next generated ID starts after the max loaded ID
            self._next_card_id = max(self._next_card_id, self._max_loaded_id + 1)

        # Check for ID collision (should not happen with proper loading logic)
        if current_id in self.cards:
             debug_print(f"警告：尝试添加已存在的卡片 ID {current_id}。跳过。")
             # Potentially update _next_card_id again if collision occurred due to manual generation
             if card_id is None:
                  self._next_card_id = max(self._next_card_id, current_id + 1)
             return self.cards[current_id] # Return existing card

        # 新建卡片时应用网格吸附（加载工作流时不吸附，保持原位置）
        # 注意：网格吸附只受网格开关控制，不受卡片间吸附开关影响
        if card_id is None and self._grid_enabled:
            x = round(x / self._grid_spacing) * self._grid_spacing
            y = round(y / self._grid_spacing) * self._grid_spacing

        # Create and add the card
        card = TaskCard(self, x, y, task_type=task_type, card_id=current_id, task_module=task_info) 
        card.set_display_id(None) # Set the display ID
        debug_print(f"--- [DEBUG] TaskCard __init__ END (SIMPLIFIED) - ID: {current_id} ---")

        # --- ADD ITEM BACK HERE --- 
        self.scene.addItem(card)
        # --------------------------
        self.cards[current_id] = card 
        self._update_card_render_cache_policy()
        debug_print(f"添加卡片实例到场景: 类型='{task_type}', ID={current_id} at ({x}, {y})") # Updated log message
        
        # --- REMOVED: Instance-level signal check --- 
        # debug_print(f"DEBUG [WorkflowView]: Inspecting card {current_id} before connect:")
        # ... (removed debug prints) ...
        # debug_print(f"  - hasattr(card.delete_requested, 'connect'): {hasattr(card.delete_requested, 'connect')}")
        # -------------------------------------------
        
        # --- Restore Signal Connections/Emit --- 
        # Note: Connection should still work via instance -> class -> module lookup
        debug_print(f"DEBUG [WorkflowView]: Attempting to connect delete_requested for card {current_id}")
        card.delete_requested.connect(self.delete_card) 
        debug_print(f"DEBUG [WorkflowView]: Attempting to connect copy_requested for card {current_id}")
        card.copy_requested.connect(self.handle_copy_card)
        # 修复：不再连接edit_settings_requested到workflow_view，由main_window处理
        # debug_print(f"DEBUG [WorkflowView]: Attempting to connect edit_settings_requested for card {current_id}")
        # card.edit_settings_requested.connect(self.edit_card_settings)

        debug_print(f"DEBUG [WorkflowView]: Attempting to emit card_added for card {current_id}")
        self.card_added.emit(card) # <<< RESTORED
        # ------------------------------------------------------
        debug_print(f"--- [DEBUG] WorkflowView: Finished signal connections/emit for card {current_id}. Current cards: {list(self.cards.keys())} ---") # RESTORED final print

        # --- ADDED: Connect to the new jump target signal ---
        card.jump_target_parameter_changed.connect(self._handle_jump_target_change)
        # --- ADDED: Connect to the card click signal ---
        card.card_clicked.connect(self._handle_card_clicked)
        # --- ADDED: Connect to sub-workflow open signal ---
        card.open_sub_workflow_requested.connect(self._handle_open_sub_workflow)
        # ---------------------------------------------

        # 应用传入的参数（用于撤销恢复等场景）
        if parameters:
            debug_print(f"  [DEBUG] Applying provided parameters to card {current_id}: {parameters}")
            debug_print(f"  [DEBUG] Card {current_id} parameters before update: {card.parameters}")
            card.parameters.update(parameters)
            debug_print(f"  [DEBUG] Card {current_id} parameters after update: {card.parameters}")

            # 验证参数是否正确应用
            for key, value in parameters.items():
                if key in card.parameters and card.parameters[key] == value:
                    debug_print(f"    ✓ Parameter {key} correctly applied: {value}")
                else:
                    debug_print(f"    ✗ Parameter {key} failed to apply: expected {value}, got {card.parameters.get(key)}")
        else:
            debug_print(f"  [DEBUG] No parameters provided for card {current_id}")

        # 注释已清理（原注释编码损坏）
        if hasattr(task_info, 'get_parameters'):
            try:
                param_defs = task_info.get_parameters()
                for param_name, param_def in param_defs.items():
                    if param_name not in card.parameters and 'default' in param_def:
                        default_value = param_def['default']
                        card.parameters[param_name] = default_value
                        debug_print(f"  [DEBUG] Card {current_id}: 填充默认值 {param_name}={default_value}")
            except Exception as e:
                debug_print(f"  [DEBUG] Card {current_id}: 获取参数定义失败: {e}")


        # 保存添加卡片状态用于撤销（除非正在加载工作流、执行撤销操作或粘贴卡片）
        if (not self._loading_workflow and not self._undoing_operation and card_id is None and
            not getattr(self, '_pasting_card', False)):
            # 注释已清理（原注释编码损坏）
            self._save_add_card_state_for_undo(current_id, task_type, x, y, parameters)
        else:
            if self._loading_workflow:
                debug_print(f"  [UNDO] Skipping add card undo save (loading workflow)")
            if self._undoing_operation:
                debug_print(f"  [UNDO] Skipping add card undo save (undoing operation)")
            if card_id is not None:
                debug_print(f"  [UNDO] Skipping add card undo save (loading existing card)")

        # --- REMOVED: Update sequence display after adding a card (moved to load_workflow end) ---
        # self.update_card_sequence_display()  # <<< REMOVED THIS LINE
        # -------------------------------------------------------------------------------------
        if self._is_start_task_type(task_type):
            self._refresh_thread_start_custom_names()
        return card

    def _get_container_children(self, container_id: int) -> List[TaskCard]:
        return [
            card for card in self.cards.values()
            if getattr(card, "container_id", None) == container_id
        ]

    def _get_container_cards(self) -> List[TaskCard]:
        return [
            card for card in self.cards.values()
            if getattr(card, "is_container_card", False)
        ]

    def _find_drop_container_for_card(self, card: TaskCard) -> Optional[TaskCard]:
        if not card or getattr(card, "is_container_card", False):
            return None
        if self._is_start_task_type(getattr(card, "task_type", "")):
            return None

        try:
            card_rect = card.sceneBoundingRect()
        except RuntimeError:
            return None
        card_center = card_rect.center()

        candidates: List[TaskCard] = []
        for container in self._get_container_cards():
            if container == card:
                continue
            if getattr(container, "container_id", None) is not None:
                continue
            try:
                if container.scene() != self.scene:
                    continue
                container_rect = container.sceneBoundingRect()
            except RuntimeError:
                continue

            if card_rect.left() < container_rect.left():
                continue
            if card_rect.top() < container_rect.top():
                continue
            if not container_rect.contains(card_center):
                continue

            candidates.append(container)

        if not candidates:
            return None

        def _candidate_key(item: TaskCard) -> tuple:
            rect = item.sceneBoundingRect()
            area = rect.width() * rect.height()
            return (item.zValue(), -area)

        return max(candidates, key=_candidate_key)

    def _remove_card_connections(self, card: TaskCard):
        for conn in list(getattr(card, "connections", [])):
            try:
                self.remove_connection(conn)
            except Exception:
                pass

    def _assign_card_to_container(self, card: TaskCard, container: TaskCard):
        if not card or not container:
            return
        if card.container_id == container.card_id:
            return
        self._remove_card_connections(card)
        card.set_container_id(container.card_id)
        try:
            card.setZValue(max(card.zValue(), container.zValue() + 1))
        except RuntimeError:
            pass

    def _remove_card_from_container(self, card: TaskCard) -> Optional[int]:
        if not card:
            return None
        old_container_id = getattr(card, "container_id", None)
        card.set_container_id(None)
        try:
            if card.zValue() < 0:
                card.setZValue(0)
        except RuntimeError:
            pass
        return old_container_id

    def _update_container_size(self, container: TaskCard):
        if not container or not getattr(container, "is_container_card", False):
            return

        children = self._get_container_children(container.card_id)
        min_w, min_h = getattr(container, "_container_min_size", (240, 140))
        if not children:
            container.set_size(min_w, min_h)
            return

        try:
            container_rect = container.sceneBoundingRect()
        except RuntimeError:
            return
        left = container_rect.left()
        top = container_rect.top()
        padding = getattr(container, "_container_padding", 0)

        child_rects = []
        for child in children:
            try:
                child_rects.append(child.sceneBoundingRect())
            except RuntimeError:
                continue
        if not child_rects:
            container.set_size(min_w, min_h)
            return

        max_right = max(rect.right() for rect in child_rects) + padding
        max_bottom = max(rect.bottom() for rect in child_rects) + padding
        new_width = max(min_w, max_right - left)
        new_height = max(min_h, max_bottom - top)
        container.set_size(new_width, new_height)

    def _layout_container_children(self, container: TaskCard):
        if not container or not getattr(container, "is_container_card", False):
            return

        children = self._get_container_children(container.card_id)
        min_w, min_h = getattr(container, "_container_min_size", (240, 140))
        padding = getattr(container, "_container_padding", 0)

        if not children:
            container.set_size(min_w, min_h)
            return

        children = sorted(children, key=lambda c: getattr(c, "card_id", 0))
        max_w = 0.0
        max_h = 0.0
        for child in children:
            try:
                rect = child.boundingRect()
            except RuntimeError:
                continue
            max_w = max(max_w, rect.width())
            max_h = max(max_h, rect.height())

        if max_w <= 0 or max_h <= 0:
            container.set_size(min_w, min_h)
            return

        spacing_x = 20
        spacing_y = 20
        container_w = container.boundingRect().width()
        content_w = max(container_w - padding * 2, max_w)
        cols = max(1, int((content_w + spacing_x) // (max_w + spacing_x)))
        cols = min(cols, len(children))
        rows = int(math.ceil(len(children) / float(cols)))

        grid_w = cols * max_w + (cols - 1) * spacing_x
        grid_h = rows * max_h + (rows - 1) * spacing_y

        new_w = max(min_w, grid_w + padding * 2)
        new_h = max(min_h, grid_h + padding * 2)
        container.set_size(new_w, new_h)

        content_w = new_w - padding * 2
        content_h = new_h - padding * 2
        offset_x = max(0.0, (content_w - grid_w) / 2.0)
        offset_y = max(0.0, (content_h - grid_h) / 2.0)

        try:
            container_rect = container.sceneBoundingRect()
        except RuntimeError:
            return

        left = container_rect.left()
        top = container_rect.top()

        for idx, child in enumerate(children):
            row = idx // cols
            col = idx % cols
            x = left + padding + offset_x + col * (max_w + spacing_x)
            y = top + padding + offset_y + row * (max_h + spacing_y)
            try:
                child.setPos(QPointF(x, y))
            except RuntimeError:
                continue

    def _refresh_container_layouts(self):
        for container in self._get_container_cards():
            self._update_container_size(container)

    def handle_cards_dropped(self, cards: List[TaskCard]):
        if not cards:
            return

        affected_container_ids = set()
        for card in cards:
            if not isinstance(card, TaskCard):
                continue
            if getattr(card, "is_container_card", False):
                continue
            if card.task_type == "\u8d77\u70b9":
                if card.container_id is not None:
                    old_container_id = self._remove_card_from_container(card)
                    if old_container_id is not None:
                        affected_container_ids.add(old_container_id)
                continue

            target_container = self._find_drop_container_for_card(card)
            if target_container:
                if card.container_id != target_container.card_id:
                    if card.container_id is not None:
                        affected_container_ids.add(card.container_id)
                    self._assign_card_to_container(card, target_container)
                affected_container_ids.add(target_container.card_id)
            else:
                if card.container_id is not None:
                    old_container_id = self._remove_card_from_container(card)
                    if old_container_id is not None:
                        affected_container_ids.add(old_container_id)

        for container_id in affected_container_ids:
            container = self.cards.get(container_id)
            if container and getattr(container, "is_container_card", False):
                self._layout_container_children(container)

    def move_container_children(self, container_card: TaskCard, delta: QPointF):
        if not container_card or delta is None:
            return
        if not delta.x() and not delta.y():
            return
        for child in self._get_container_children(container_card.card_id):
            try:
                child.setPos(child.pos() + delta)
            except RuntimeError:
                continue

    def clear_workflow(self):
        """Removes all cards and connections from the scene using scene.clear()."""
        # 注释已清理（原注释编码损坏）
        try:
            main_window = None
            # 从父级查找MainWindow
            try:
                parent = self.parent()
                # 工具 用户要求：删除无限循环限制，但保留合理的查找限制防止真正的死循环
                loop_count = 0
                max_loops = 100  # 增加查找层数限制，从50增加到100
                while parent and not hasattr(parent, 'executor') and loop_count < max_loops:
                    parent = parent.parent()
                    loop_count += 1
                if loop_count >= max_loops:
                    logger.warning("查找MainWindow时达到最大循环次数限制")
                    parent = None
                main_window = parent
            except Exception as e:
                logger.debug(f"从父级查找MainWindow失败: {e}")
            
            # 如果没找到，从QApplication查找
            if not main_window:
                try:
                    from PySide6.QtWidgets import QApplication
                    app = QApplication.instance()
                    if app:
                        for widget in app.allWidgets():
                            if hasattr(widget, 'executor') and hasattr(widget, 'executor_thread'):
                                main_window = widget
                                break
                except Exception as e:
                    logger.debug(f"从QApplication查找MainWindow失败: {e}")
            
            # 检查是否有任务正在运行
            if main_window and hasattr(main_window, 'executor') and hasattr(main_window, 'executor_thread'):
                if (main_window.executor is not None and 
                    main_window.executor_thread is not None and 
                    main_window.executor_thread.isRunning()):
                    
                    logger.warning("尝试在任务运行期间清空工作流")
                    from PySide6.QtWidgets import QMessageBox
                    reply = QMessageBox.question(
                        self, 
                        "任务正在运行", 
                        "检测到任务正在运行。\n\n选择“是”将先发送停止请求，任务停止后再清空工作流。\n选择“否”将直接强制清空（可能导致状态不一致）。\n选择“取消”放弃本次操作。",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.Yes
                    )
                    
                    if reply == QMessageBox.StandardButton.Yes:
                        # 用户选择先停止任务
                        logger.info("用户选择先停止任务再清空工作流")


                        if hasattr(main_window, 'request_stop_workflow'):
                            main_window.request_stop_workflow()
                        QMessageBox.information(
                            self, 
                            "操作说明", 
                            "已发送停止请求。请等待任务停止后再尝试清空工作流。"
                        )
                        return
                    elif reply == QMessageBox.StandardButton.No:
                        # 用户选择强制清空
                        logger.warning("用户选择在任务运行期间强制清空工作流")
                        pass  # 继续执行清空操作
                    else:
                        # 用户取消操作
                        logger.info("用户取消了清空工作流操作")
                        return
                        
        except Exception as e:
            logger.error(f"检查任务运行状态时发生错误: {e}")
            # 出错时允许继续，但记录警告
            logger.warning("由于检查失败，按传统方式执行清空操作")
        # 注释已清理（原注释编码损坏）
        
        # <<< ENHANCED: 清理前验证连接状态 >>>
        logger.debug("清理工作流前验证连接状态...")
        self.validate_connections()
        self.cleanup_orphaned_connections()
        # <<< END ENHANCED >>>

        # 清理全局连线动画索引，确保列表与 ID 集合同步回收
        try:
            from ..workflow_parts.connection_line import _unregister_animated_line
            connections_to_clear = list(self.connections)  # 创建副本
            for conn in connections_to_clear:
                _unregister_animated_line(conn)
            logger.debug(f"清理了全局动画列表中的 {len(connections_to_clear)} 个连接")
        except Exception as e:
            logger.debug(f"清理动画列表失败: {e}")

        # Use scene.clear() for a more robust way to remove all items
        self.scene.clear() 
        
        # Reset internal state
        self.cards.clear()
        self.connections.clear()
        self._next_card_id = 0
        self._max_loaded_id = -1
        self._update_card_render_cache_policy()

        # 注释已清理（原注释编码损坏）
        old_undo_size = len(self.undo_stack)
        self.undo_stack.clear()
        if old_undo_size > 0:
            debug_print(f"  [UNDO] Cleared undo stack during workflow clear (had {old_undo_size} operations)")
            logger.info(f"  [UNDO] Cleared undo stack during workflow clear (had {old_undo_size} operations)")

        # 只在非加载状态下重置加载工作流标志
        # 注释已清理（原注释编码损坏）
        if not self._loading_workflow:
            debug_print(f"  [UNDO] Not loading workflow, keeping flag as False")
            logger.info(f"  [UNDO] Not loading workflow, keeping flag as False")
        else:
            debug_print(f"  [UNDO] Loading workflow in progress, keeping flag as True")
            logger.info(f"  [UNDO] Loading workflow in progress, keeping flag as True")

        logger.info("Workflow cleared.")

    def set_card_state(self, card_id: int, state: str):
        """Sets the visual state of a card (e.g., 'idle', 'executing', 'success', 'failure')."""
        try:
            logger.debug(f"[UI接收] 设置卡片状态: card_id={card_id}, state={state}")
            card = self.cards.get(card_id)
            if card and hasattr(card, 'set_execution_state'): # Check if method exists on TaskCard
                try:
                    # 检查卡片是否仍在场景中
                    card_scene = card.scene()
                    if card_scene != self.scene:
                        logger.warning(f"卡片 {card_id} 场景不匹配！card.scene()={card_scene}, self.scene={self.scene}")
                        logger.warning(f"  跳过状态设置，state={state}")
                        return

                    card.set_execution_state(state)
                    # 强制触发对应区域刷新，避免高负载下状态变化延迟到任务结束后才可见
                    try:
                        self.scene.update(card.sceneBoundingRect())
                    except Exception:
                        pass
                    try:
                        self.viewport().update()
                    except Exception:
                        pass
                    logger.debug(f"[UI接收] 成功设置卡片 {card_id} 状态为 {state}")
                except RuntimeError as re:
                    # 处理Qt对象已删除的情况
                    logger.debug(f"卡片 {card_id} 对象已删除，无法设置状态: {re}")
                    # 注释已清理（原注释编码损坏）
                    if card_id in self.cards:
                        del self.cards[card_id]
                except Exception as e:
                    logger.warning(f"设置卡片 {card_id} 状态时发生错误: {e}")
            else:
                # 注释已清理（原注释编码损坏）
                logger.debug(f"尝试设置状态时找不到卡片 {card_id} 或卡片缺少 set_execution_state 方法。")
                # 注释已清理（原注释编码损坏）
        except Exception as e:
            logger.error(f"设置卡片 {card_id} 状态时发生严重错误: {e}")

    def reset_card_states(self):
        """Resets all cards to their idle visual state."""
        debug_print("重置所有卡片状态为 idle")
        # 【修复闪退】创建字典快照避免迭代时修改
        cards_snapshot = list(self.cards.keys())
        for card_id in cards_snapshot:
             self.set_card_state(card_id, 'idle')

        # 工具 停止所有卡片的闪烁效果
        try:
            # 【修复闪退】创建字典快照避免迭代时修改
            cards_snapshot = dict(self.cards)
            for card_id, card in cards_snapshot.items():
                if card and hasattr(card, 'stop_flash'):
                    try:
                        card.stop_flash()
                    except (RuntimeError, AttributeError):
                        # 卡片可能已被删除，忽略错误
                        pass
            debug_print("停止 已停止所有卡片的闪烁效果")
        except Exception as e:
            debug_print(f"错误 停止所有卡片闪烁效果失败: {e}")

    def renumber_cards_display_by_sequence(self):
        """Placeholder or potentially deprecated renumbering logic."""
        logger.warning("renumber_cards_display_by_sequence called - likely deprecated. Use update_card_sequence_display.")
        # If this is truly needed, it should call update_card_sequence_display
        self.update_card_sequence_display()
