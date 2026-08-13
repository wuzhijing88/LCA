import logging
from typing import Any, Dict
from utils.window_binding_utils import get_active_bound_window_hwnd, get_active_target_window_title

logger = logging.getLogger(__name__)


class MainWindowParameterPanelDisplayMixin:

    def _show_parameter_panel(self, card_id: int):
        """显示参数面板"""
        logger.info(f"显示卡片 {card_id} 的参数面板")
        # 【修复闪退】检查workflow_view是否存在
        if not self.workflow_view or not hasattr(self.workflow_view, 'cards'):
            logger.warning("workflow_view不存在或没有cards属性，无法显示参数面板")
            return
        # 获取卡片信息
        card = self.workflow_view.cards.get(card_id)
        if not card:
            logger.warning(f"未找到卡片 {card_id}")
            return
        # 获取工作流卡片信息
        workflow_info = {}
        for seq_id, card_obj in enumerate(self.workflow_view.cards.values()):
            workflow_info[seq_id] = (card_obj.task_type, card_obj.card_id)
        # 获取随机跳转连接信息
        random_jump_connections = []
        if card.task_type == '随机跳转':
            # 查找所有random类型的输出连接
            for conn in getattr(self.workflow_view, 'connections', []):
                if (hasattr(conn, 'start_item') and hasattr(conn, 'end_item') and
                    hasattr(conn, 'line_type') and conn.start_item and
                    conn.start_item.card_id == card_id and
                    conn.line_type == 'random'):
                    target_card = conn.end_item
                    if target_card:
                        random_jump_connections.append({
                            'card_id': target_card.card_id,
                            'task_type': target_card.task_type
                        })
            logger.info(f"随机跳转卡片 {card_id} 的连接目标: {random_jump_connections}")
        # 【关键修改】优先获取当前标签页绑定的窗口句柄
        target_window_hwnd = None
        # 1. 优先从当前标签页的任务获取绑定的窗口句柄
        if hasattr(self, 'workflow_tab_widget') and self.workflow_tab_widget:
            current_task_id = self.workflow_tab_widget.get_current_task_id()
            if current_task_id is not None:
                task_manager = self.workflow_tab_widget.task_manager
                current_task = task_manager.get_task(current_task_id)
                if current_task and current_task.target_hwnd:
                    target_window_hwnd = current_task.target_hwnd
                    logger.info(f"使用当前标签页绑定的窗口句柄: {target_window_hwnd} (来自任务'{current_task.name}')")
        # 2. 如果标签页没有绑定,回退到全局配置
        if not target_window_hwnd and hasattr(self, 'config') and self.config:
            logger.info("当前标签页未绑定窗口,使用全局配置")
            target_window_hwnd = get_active_bound_window_hwnd(self.config)
            if target_window_hwnd:
                logger.info(f"从活动绑定窗口获取句柄: {target_window_hwnd}")
            # 单窗口模式：通过窗口标题查找句柄
            if not target_window_hwnd:
                target_window_title = get_active_target_window_title(self.config)
                if target_window_title:
                    target_window_hwnd = self._find_window_by_title(target_window_title)
                    if target_window_hwnd:
                        logger.info(f"单窗口模式通过标题找到句柄: {target_window_hwnd}")
        elif not target_window_hwnd and hasattr(self, 'runner') and self.runner:
            target_window_hwnd = getattr(self.runner, 'target_hwnd', None)
        # 显示参数面板
        # 获取任务模块
        task_module = self.task_modules.get(card.task_type) if hasattr(self, 'task_modules') else None
        # 为随机跳转任务动态更新参数
        updated_parameters = card.parameters.copy()
        if card.task_type == '随机跳转':
            from tasks.random_jump import prune_branch_weights
            updated_parameters['random_weights'] = prune_branch_weights(
                updated_parameters.get('random_weights'),
                [item.get('card_id') for item in random_jump_connections],
            )
            # 直接传入连接列表数据
            updated_parameters['_random_connections'] = random_jump_connections if random_jump_connections else []
        task_images_dir = self.images_dir
        if hasattr(self, 'workflow_tab_widget') and self.workflow_tab_widget:
            current_task_id = self.workflow_tab_widget.get_current_task_id()
            task_manager = getattr(self.workflow_tab_widget, 'task_manager', None)
            if task_manager:
                current_task = task_manager.get_task(current_task_id)
                if current_task and getattr(current_task, 'images_dir', None):
                    task_images_dir = current_task.images_dir
        self.parameter_panel.show_parameters(
            card_id=card_id,
            task_type=card.task_type,
            param_definitions=card.param_definitions,
            current_parameters=updated_parameters,
            workflow_cards_info=workflow_info,
            images_dir=task_images_dir,
            target_window_hwnd=target_window_hwnd,
            task_module=task_module,
            main_window=self,
            custom_name=card.custom_name
        )
        # 标记参数面板为可见状态
        self._parameter_panel_visible = True
    def _on_parameter_changed(self, card_id: int, new_parameters: Dict[str, Any]):
        """处理参数更改"""
        # 调试延迟模式相关参数
        if 'delay_mode' in new_parameters:
            logger.debug(f"主窗口参数更新: 卡片 {card_id}, delay_mode={new_parameters['delay_mode']}")
        # 【关键修复】获取当前活动的 workflow_view
        current_workflow_view = None
        if hasattr(self, 'workflow_tab_widget') and self.workflow_tab_widget:
            # 使用标签页系统
            current_task_id = self.workflow_tab_widget.get_current_task_id()
            if current_task_id is not None and current_task_id in self.workflow_tab_widget.task_views:
                current_workflow_view = self.workflow_tab_widget.task_views[current_task_id]
        # 回退到旧系统
        if current_workflow_view is None:
            current_workflow_view = self.workflow_view
        if not current_workflow_view:
            logger.error("[主窗口] 无法找到当前的 workflow_view！")
            return
        # 【修复闪退】检查cards属性是否存在
        if not hasattr(current_workflow_view, 'cards'):
            logger.error("[主窗口] workflow_view没有cards属性！")
            return
        card = current_workflow_view.cards.get(card_id)
        if card:
            card.parameters.update(new_parameters)
            try:
                card.register_result_variable_placeholders()
            except Exception:
                pass
            # 清除工具提示缓存，强制重新生成
            if hasattr(card, '_tooltip_needs_update'):
                card._tooltip_needs_update = True
            if hasattr(card, '_cached_tooltip'):
                delattr(card, '_cached_tooltip')
            # BUG FIX: 检查是否影响端口限制的参数
            port_affecting_params = ['on_success', 'on_failure', 'on_image_found', 'on_image_not_found']
            needs_port_update = any(param in new_parameters for param in port_affecting_params)
            if needs_port_update:
                logger.info(f"检测到影响端口限制的参数更改: {[p for p in port_affecting_params if p in new_parameters]}")
                # 先更新端口限制，这会影响连线的显示
                if hasattr(card, 'update_port_restrictions'):
                    card.update_port_restrictions()
                    logger.info(f"卡片 {card_id} 端口限制已更新")
            # 检查是否有影响连线的参数更改
            connection_affecting_params = ['success_jump_target_id', 'failure_jump_target_id']
            needs_connection_update = any(param in new_parameters for param in connection_affecting_params)
            # 【修复】清理无效的跳转参数
            # 如果 on_success/on_failure 不是跳转相关的值，则应该清除对应的跳转目标参数
            # 注意：不同任务的跳转选项值可能不同，可能是"跳转到步骤"或"跳转到指定步骤"等
            if 'on_success' in new_parameters:
                on_success_value = new_parameters['on_success']
                # 检查是否是跳转相关的选项（包含"跳转"关键词）
                is_jump_option = '跳转' in str(on_success_value)
                if not is_jump_option and new_parameters.get('success_jump_target_id') is not None:
                    logger.debug("[参数清理] on_success=%r，清除 success_jump_target_id", on_success_value)
                    new_parameters['success_jump_target_id'] = None
                    card.parameters['success_jump_target_id'] = None
            if 'on_failure' in new_parameters:
                on_failure_value = new_parameters['on_failure']
                # 检查是否是跳转相关的选项（包含"跳转"关键词）
                is_jump_option = '跳转' in str(on_failure_value)
                if not is_jump_option and new_parameters.get('failure_jump_target_id') is not None:
                    logger.debug("[参数清理] on_failure=%r，清除 failure_jump_target_id", on_failure_value)
                    new_parameters['failure_jump_target_id'] = None
                    card.parameters['failure_jump_target_id'] = None
            # 【修复】检查参数是否是设置为跳转（而不是清除跳转）
            # 只有在设置跳转目标时才需要重建连线，清除跳转时不应该重建
            is_setting_jump = False
            if needs_connection_update:
                for param in connection_affecting_params:
                    if param in new_parameters:
                        # 如果参数值不是None，说明是设置跳转目标
                        if new_parameters[param] is not None:
                            # 但还要检查对应的 on_success/on_failure 是否是跳转相关选项
                            if param == 'success_jump_target_id':
                                on_success = new_parameters.get('on_success') or card.parameters.get('on_success', '')
                                if '跳转' in str(on_success):
                                    is_setting_jump = True
                                    break
                            elif param == 'failure_jump_target_id':
                                on_failure = new_parameters.get('on_failure') or card.parameters.get('on_failure', '')
                                if '跳转' in str(on_failure):
                                    is_setting_jump = True
                                    break
                            else:
                                is_setting_jump = True
                                break
            if (is_setting_jump or needs_port_update):
                logger.info(f"检测到影响连线的参数更改，触发连线更新: {[p for p in (connection_affecting_params + port_affecting_params) if p in new_parameters]}")
                # 【性能优化】只更新单个卡片的跳转连线，而不是重建整个工作流
                if current_workflow_view:
                    current_workflow_view.update_single_card_jump_connections(card_id)
            else:
                # 即使不更新连线，也要刷新卡片显示
                card.update()
            # 【性能优化】移除每次参数更新都序列化的逻辑
            # 只需要标记为未保存状态，实际保存时再序列化
            # 标记为未保存
            self._mark_unsaved_changes()
            logger.info(f"卡片 {card_id} 参数已成功更新并标记为未保存")
        else:
            logger.error(f"未找到卡片 {card_id}，可用卡片: {list(self.workflow_view.cards.keys())}")
    def _on_delete_random_connection(self, source_card_id: int, target_card_id: int):
        """处理删除随机跳转连线的请求"""
        logger.info(f"[删除随机连线] 源卡片ID: {source_card_id}, 目标卡片ID: {target_card_id}")
        if not hasattr(self, 'workflow_view') or not self.workflow_view:
            logger.warning("[删除随机连线] workflow_view不存在")
            return
        # 查找并删除连线
        source_card = self.workflow_view.cards.get(source_card_id)
        if not source_card:
            logger.warning(f"[删除随机连线] 源卡片 {source_card_id} 不存在")
            return
        connection_to_delete = None
        for conn in list(source_card.connections):
            # 检查line_type是否为random，且end_item的card_id匹配
            if hasattr(conn, 'line_type') and conn.line_type == 'random':
                if hasattr(conn, 'end_item') and conn.end_item:
                    if hasattr(conn.end_item, 'card_id') and conn.end_item.card_id == target_card_id:
                        connection_to_delete = conn
                        break
        if connection_to_delete:
            logger.info("[删除随机连线] 找到连线，正在删除...")
            self.workflow_view.remove_connection(connection_to_delete)
            from tasks.random_jump import prune_branch_weights
            random_jump_connections = []
            for conn in source_card.connections:
                if hasattr(conn, 'line_type') and conn.line_type == 'random':
                    if hasattr(conn, 'end_item') and conn.end_item:
                        if hasattr(conn.end_item, 'card_id'):
                            random_jump_connections.append({
                                'task_type': getattr(conn.end_item, 'task_type', ''),
                                'card_id': conn.end_item.card_id
                            })
            pruned_weights = prune_branch_weights(
                source_card.parameters.get('random_weights'),
                [item.get('card_id') for item in random_jump_connections],
            )
            source_card.parameters['random_weights'] = pruned_weights
            # 刷新参数面板
            if hasattr(self, 'parameter_panel') and self.parameter_panel.current_card_id == source_card_id:
                self.parameter_panel.current_parameters['_random_connections'] = random_jump_connections
                self.parameter_panel.current_parameters['random_weights'] = pruned_weights
                self.parameter_panel._refresh_conditional_widgets()
        else:
            logger.warning("[删除随机连线] 未找到匹配的连线")
