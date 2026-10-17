from .workflow_view_common import *

operation_logger = logging.getLogger("workflow.operations")

# 卡片布局模块不输出构造步骤、参数全文和信号连接等调试信息。
debug_print = lambda *args, **kwargs: None
class WorkflowViewCardLayoutMixin:

    def _discard_uncommitted_card(self, card: Optional[TaskCard]) -> None:
        """撤销一张尚未完成登记的卡片，避免失败后留下半挂载对象。"""
        if card is None:
            return
        card_id = getattr(card, "card_id", None)
        if isinstance(getattr(self, "cards", None), dict) and card_id in self.cards:
            self.cards.pop(card_id, None)
        try:
            card._unregister_gradient_animation()
        except Exception:
            pass
        for attr_name, slot in (
            ("flash_toggle_timer", card._toggle_flash_border),
            ("_drag_check_timer", card._check_drag_state),
        ):
            try:
                card._cleanup_timer_attr(attr_name, slot)
            except Exception:
                pass
        try:
            card._release_shadow_effect()
        except Exception:
            pass
        try:
            if card.scene() is self.scene:
                self.scene.removeItem(card)
        except (RuntimeError, TypeError):
            pass
        try:
            card.view = None
        except RuntimeError:
            pass
        try:
            card.deleteLater()
        except RuntimeError:
            pass

    def _notify_cards_moved(self, cards) -> None:
        """用户拖动卡片后标记工作流未保存。"""
        if getattr(self, "_loading_workflow", False) or getattr(self, "_undoing_operation", False):
            return
        notified = False
        for card in cards or ():
            card_id = getattr(card, "card_id", None)
            if card_id is None:
                continue
            self.card_moved.emit(card_id, card.pos())
            notified = True
        if notified and hasattr(self, "_mark_workflow_dirty"):
            self._mark_workflow_dirty()

    def _resolve_card_id(self, requested_card_id: Optional[int]) -> int:
        """返回明确指定的 ID，或根据当前卡片集合生成下一个 ID。"""
        if not isinstance(self.cards, dict):
            raise TypeError("卡片容器必须是字典")
        for existing_id in self.cards:
            if isinstance(existing_id, bool) or not isinstance(existing_id, int) or existing_id < 0:
                raise RuntimeError(f"卡片容器中存在无效 ID: {existing_id!r}")

        resolved_id = max(self.cards, default=-1) + 1 if requested_card_id is None else requested_card_id
        if resolved_id in self.cards:
            raise ValueError(f"卡片 ID 已存在: {resolved_id}")
        return resolved_id

    def add_task_card(self, x: float, y: float, task_type: str = "未知", card_id: Optional[int] = None, parameters: Optional[dict] = None) -> Optional[TaskCard]:
        """Adds a new task card to the scene."""
        if not isinstance(task_type, str) or not task_type.strip():
            raise TypeError("卡片任务类型必须是非空字符串")
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise TypeError("卡片横坐标必须是数字")
        if isinstance(y, bool) or not isinstance(y, (int, float)):
            raise TypeError("卡片纵坐标必须是数字")
        if card_id is not None and (isinstance(card_id, bool) or not isinstance(card_id, int) or card_id < 0):
            raise TypeError("卡片 ID 必须是非负整数或 None")
        if parameters is not None and not isinstance(parameters, dict):
            raise TypeError("卡片参数必须是字典或 None")
        if not isinstance(self.task_modules, dict):
            raise TypeError("任务模块清单必须是字典")

        task_info = self.task_modules.get(task_type)
        if task_info is None:
            raise ValueError(f"未知任务类型: {task_type}")
        current_id = self._resolve_card_id(card_id)

        # 新建卡片时应用网格吸附（加载工作流时不吸附，保持原位置）
        # 注意：网格吸附只受网格开关控制，不受卡片间吸附开关影响
        if card_id is None and self._grid_enabled:
            x = round(x / self._grid_spacing) * self._grid_spacing
            y = round(y / self._grid_spacing) * self._grid_spacing

        # Create and add the card
        card = TaskCard(self, x, y, task_type=task_type, card_id=current_id, task_module=task_info) 
        try:
            card.set_display_id(None) # Set the display ID
        except Exception:
            self._discard_uncommitted_card(card)
            raise
        debug_print(f"--- [DEBUG] TaskCard __init__ END (SIMPLIFIED) - ID: {current_id} ---")

        try:
            self.scene.addItem(card)
            self.cards[current_id] = card
            self._update_card_render_cache_policy()
            if not getattr(self, "_loading_workflow", False):
                self._refresh_viewport_animations()

            card.delete_requested.connect(self.delete_card)
            card.copy_requested.connect(self.handle_copy_card)
            card.jump_target_parameter_changed.connect(self._handle_jump_target_change)
            card.card_clicked.connect(self._handle_card_clicked)
            card.open_sub_workflow_requested.connect(self._handle_open_sub_workflow)

            if parameters:
                card.parameters.update(parameters)

            param_defs = task_info.get_params_definition()
            if not isinstance(param_defs, dict):
                raise TypeError(f"任务 {task_type} 的参数定义必须是字典")
            for param_name, param_def in param_defs.items():
                if not isinstance(param_name, str) or not param_name:
                    raise TypeError(f"任务 {task_type} 的参数名必须是非空字符串")
                if not isinstance(param_def, dict):
                    raise TypeError(f"任务 {task_type} 的参数定义 {param_name} 必须是字典")
                if param_name not in card.parameters and 'default' in param_def:
                    card.parameters[param_name] = copy.deepcopy(param_def['default'])

            self.card_added.emit(card)

            is_user_add = (
                not self._loading_workflow
                and not self._undoing_operation
                and card_id is None
                and not getattr(self, '_pasting_card', False)
            )
            if is_user_add:
                self._save_add_card_state_for_undo(current_id, task_type, x, y, parameters)

            if self._is_start_task_type(task_type):
                self._refresh_thread_start_custom_names()
            if is_user_add:
                operation_logger.info("[卡片新增] 完成 card_id=%s，任务类型=%s", current_id, task_type)
            return card
        except Exception:
            self._discard_uncommitted_card(card)
            raise

    def clear_workflow(self):
        """在工作流空闲时清空画布和编辑历史。"""
        if not self._loading_workflow and self._is_workflow_running():
            operation_logger.warning("[工作流清空] 已拒绝：工作流正在运行")
            return False

        self._sync_connections_with_scene()
        card_count = len(self.cards)
        connection_count = len(self.connections)

        # 先逐项卸载动画、定时器和连线引用，再让 QGraphicsScene 清空 C++ 对象。
        # 这样清空/重载与关闭标签页都不会留下全局动画集合中的失效包装对象。
        for connection in list(self.connections):
            # 连线留在场景内，由 scene.clear() 销毁；移出场景会失去销毁入口。
            connection.cleanup()

        for card in list(self.cards.values()):
            card._unregister_gradient_animation()
            for attr_name, slot in (
                ("flash_toggle_timer", card._toggle_flash_border),
                ("_drag_check_timer", card._check_drag_state),
            ):
                card._cleanup_timer_attr(attr_name, slot)
            card.stop_flash()
            card._release_shadow_effect()
            card.connections.clear()
            card.view = None

        self.scene.clear()
        self.cards.clear()
        self.connections.clear()
        self.undo_stack.clear()
        self._update_card_render_cache_policy()

        if not self._loading_workflow:
            operation_logger.info(
                "[工作流清空] 完成，卡片数量=%s，连线数量=%s",
                card_count,
                connection_count,
            )
        return True

    def set_card_state(self, card_id: int, state: str):
        """更新当前场景中的卡片执行状态。"""
        if isinstance(card_id, bool) or not isinstance(card_id, int):
            operation_logger.warning(
                "[卡片状态] 更新被跳过，卡片 ID 无效 card_id=%r，state=%s",
                card_id,
                state,
            )
            return False
        if not isinstance(state, str):
            raise TypeError("卡片执行状态必须是字符串")
        if state not in TaskCard.VALID_EXECUTION_STATES:
            raise ValueError(f"无效的卡片执行状态: {state}")

        card = self.cards.get(card_id)
        if card is None:
            operation_logger.warning(
                "[卡片状态] 更新被拒绝，卡片不存在 card_id=%s，state=%s",
                card_id,
                state,
            )
            return False
        if card.scene() is not self.scene:
            raise RuntimeError(f"卡片 {card_id} 不属于当前工作流场景")

        card.set_execution_state(state)
        self.scene.update(card.sceneBoundingRect())
        self.viewport().update()
        return True

    def reset_card_states(self):
        """将当前场景中的全部卡片恢复为空闲状态并停止闪烁。"""
        cards_snapshot = list(self.cards.items())
        for card_id, card in cards_snapshot:
            self.set_card_state(card_id, "idle")
            card.stop_flash()
