import logging
from typing import Any, Dict
from utils.window.window_binding_utils import get_active_bound_window_hwnd, get_active_target_window_title
from typing import Any
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTextEdit,
)
from utils.window.window_activation_utils import show_and_raise_widget

logger = logging.getLogger(__name__)

class MainWindowParameterPanelMixin:

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
        if card.task_type == "自定义脚本":
            self._show_script_editor(card)
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

    def _show_script_editor(self, card) -> None:
        """自定义脚本走独立编辑窗，不打开通用参数面板。"""
        if hasattr(self, "parameter_panel") and self.parameter_panel and self.parameter_panel.isVisible():
            self.parameter_panel.hide_panel()
        self._parameter_panel_visible = False

        from PySide6.QtCore import Qt

        from ui.dialogs.script_editor_dialog import ScriptEditorDialog

        editors = getattr(self, "_script_editors", None)
        if editors is None:
            self._script_editors = {}
            editors = self._script_editors
        existing = editors.get(card.card_id)
        if existing is not None:
            try:
                source = str((card.parameters or {}).get("script_source") or "")
                if hasattr(existing, "reload_source"):
                    existing.reload_source(source)
                existing.raise_()
                existing.activateWindow()
                return
            except RuntimeError:
                editors.pop(card.card_id, None)

        dialog = ScriptEditorDialog(
            card_id=card.card_id,
            source=str((card.parameters or {}).get("script_source") or ""),
            custom_name=getattr(card, "custom_name", None),
            on_applied=lambda source: self._persist_script_source(card, source),
            parent=self,
        )
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        def _forget(_result=0, card_id=card.card_id, editor=dialog) -> None:
            current = self._script_editors.get(card_id)
            if current is editor:
                self._script_editors.pop(card_id, None)

        dialog.finished.connect(_forget)
        self._script_editors[card.card_id] = dialog
        dialog.show()

    def _persist_script_source(self, card, source: str) -> None:
        """直接写回打开编辑器时的那张卡，不依赖 exec() 是否还活着。"""
        if card is None:
            logger.error("自定义脚本写入失败：卡片已失效")
            return
        if not isinstance(getattr(card, "parameters", None), dict):
            card.parameters = {}
        card.parameters["script_source"] = str(source or "")
        if hasattr(card, "_tooltip_needs_update"):
            card._tooltip_needs_update = True
        if hasattr(card, "_cached_tooltip"):
            delattr(card, "_cached_tooltip")
        if hasattr(card, "update"):
            card.update()
        self._mark_unsaved_changes()
        logger.info(
            "自定义脚本已写入卡片 %s，长度 %s",
            getattr(card, "card_id", "?"),
            len(str(source or "")),
        )

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
            from ui.panels.parameter_compare import collect_changed_parameters

            old_parameters = dict(card.parameters or {})
            pending_parameters = dict(new_parameters or {})
            # 【修复】清理无效的跳转参数
            # 如果 on_success/on_failure 不是跳转相关的值，则应该清除对应的跳转目标参数
            # 注意：不同任务的跳转选项值可能不同，可能是"跳转到步骤"或"跳转到指定步骤"等
            if 'on_success' in pending_parameters:
                on_success_value = pending_parameters['on_success']
                # 检查是否是跳转相关的选项（包含"跳转"关键词）
                is_jump_option = '跳转' in str(on_success_value)
                if not is_jump_option and pending_parameters.get('success_jump_target_id') is not None:
                    logger.debug("[参数清理] on_success=%r，清除 success_jump_target_id", on_success_value)
                    pending_parameters['success_jump_target_id'] = None
            if 'on_failure' in pending_parameters:
                on_failure_value = pending_parameters['on_failure']
                # 检查是否是跳转相关的选项（包含"跳转"关键词）
                is_jump_option = '跳转' in str(on_failure_value)
                if not is_jump_option and pending_parameters.get('failure_jump_target_id') is not None:
                    logger.debug("[参数清理] on_failure=%r，清除 failure_jump_target_id", on_failure_value)
                    pending_parameters['failure_jump_target_id'] = None
            changed_parameters = collect_changed_parameters(old_parameters, pending_parameters)
            if not changed_parameters:
                logger.debug("卡片 %s 参数未变化，跳过回写", card_id)
                return
            card.parameters.update(pending_parameters)
            # 清除工具提示缓存，强制重新生成
            if hasattr(card, '_tooltip_needs_update'):
                card._tooltip_needs_update = True
            if hasattr(card, '_cached_tooltip'):
                delattr(card, '_cached_tooltip')
            # BUG FIX: 检查是否影响端口限制的参数
            port_affecting_params = ['on_success', 'on_failure', 'on_image_found', 'on_image_not_found']
            connection_affecting_params = ['success_jump_target_id', 'failure_jump_target_id']
            needs_port_update = any(param in changed_parameters for param in port_affecting_params)
            needs_connection_update = any(param in changed_parameters for param in connection_affecting_params)
            if needs_port_update:
                logger.info(f"检测到影响端口限制的参数更改: {[p for p in port_affecting_params if p in changed_parameters]}")
                # 先更新端口限制，这会影响连线的显示
                if hasattr(card, 'update_port_restrictions'):
                    card.update_port_restrictions()
                    logger.info(f"卡片 {card_id} 端口限制已更新")
            # 【修复】检查参数是否是设置为跳转（而不是清除跳转）
            # 只有在设置跳转目标时才需要重建连线，清除跳转时不应该重建
            is_setting_jump = False
            if needs_connection_update:
                for param in connection_affecting_params:
                    if param in changed_parameters:
                        # 如果参数值不是None，说明是设置跳转目标
                        if changed_parameters[param] is not None:
                            # 但还要检查对应的 on_success/on_failure 是否是跳转相关选项
                            if param == 'success_jump_target_id':
                                on_success = pending_parameters.get('on_success') or card.parameters.get('on_success', '')
                                if '跳转' in str(on_success):
                                    is_setting_jump = True
                                    break
                            elif param == 'failure_jump_target_id':
                                on_failure = pending_parameters.get('on_failure') or card.parameters.get('on_failure', '')
                                if '跳转' in str(on_failure):
                                    is_setting_jump = True
                                    break
                            else:
                                is_setting_jump = True
                                break
            if (is_setting_jump or needs_port_update):
                logger.info(f"检测到影响连线的参数更改，触发连线更新: {[p for p in (connection_affecting_params + port_affecting_params) if p in changed_parameters]}")
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

    def _on_card_custom_name_changed(self, card_id: int, custom_name: str):
        """处理卡片备注名称更改"""
        # 获取当前活动的workflow_view
        current_workflow_view = None
        if hasattr(self, 'workflow_tab_widget') and self.workflow_tab_widget:
            current_task_id = self.workflow_tab_widget.get_current_task_id()
            if current_task_id is not None and current_task_id in self.workflow_tab_widget.task_views:
                current_workflow_view = self.workflow_tab_widget.task_views[current_task_id]
        if current_workflow_view is None:
            current_workflow_view = self.workflow_view
        if not current_workflow_view or not hasattr(current_workflow_view, 'cards'):
            return
        card = current_workflow_view.cards.get(card_id)
        if card:
            # 设置卡片备注名称（空字符串转为None）
            card.set_custom_name(custom_name if custom_name else None)
            if card_id == 0:
                self._update_favorites_workflow_name(custom_name)

    def _update_favorites_workflow_name(self, custom_name: str):
        """将起点卡片备注同步到收藏工作流名称"""
        if not hasattr(self, 'workflow_tab_widget') or not self.workflow_tab_widget:
            return
        if not hasattr(self, 'parameter_panel') or not self.parameter_panel:
            return
        current_task_id = self.workflow_tab_widget.get_current_task_id()
        if current_task_id is None:
            return
        task_manager = getattr(self.workflow_tab_widget, 'task_manager', None)
        if not task_manager:
            return
        task = task_manager.get_task(current_task_id)
        if not task or not getattr(task, 'filepath', None):
            return
        self.parameter_panel.update_favorite_name(task.filepath, custom_name)

    def _on_workflow_renamed(self, task_id: int, old_filepath: str, new_filepath: str, new_name: str):
        """处理工作流重命名并同步收藏名称"""
        if not old_filepath:
            return
        if not hasattr(self, 'parameter_panel') or not self.parameter_panel:
            return
        self.parameter_panel.update_favorite_entry(old_filepath, new_filepath, new_name)

    def _refresh_all_ocr_region_selectors(self):
        """刷新所有 OCRRegionSelectorWidget 的绑定窗口显示"""
        try:
            from ui.selectors.ocr_region_selector import OCRRegionSelectorWidget
            # 遍历所有子控件，查找 OCRRegionSelectorWidget 实例
            ocr_selectors = self.findChildren(OCRRegionSelectorWidget)
            if ocr_selectors:
                logger.info(f"找到 {len(ocr_selectors)} 个 OCRRegionSelectorWidget，正在刷新绑定窗口显示...")
                for selector in ocr_selectors:
                    try:
                        selector.refresh_bound_window_display()
                    except Exception as e:
                        logger.error(f"刷新 OCRRegionSelectorWidget 失败: {e}")
                logger.info("所有 OCRRegionSelectorWidget 已刷新")
            else:
                logger.debug("未找到 OCRRegionSelectorWidget 实例")
        except ImportError:
            logger.warning("无法导入 OCRRegionSelectorWidget，跳过刷新")
        except Exception as e:
            logger.error(f"刷新 OCRRegionSelectorWidget 时出错: {e}")

    def _handle_param_updated(self, card_id: int, param_name: str, new_value: Any):
        """Updates a parameter display value without persisting to workflow."""
        if self._is_stale_executor_signal():
            return
        logger.info(f"UI: Received param_updated for Card {card_id}, Param '{param_name}'")
        try:
            if self.parameter_panel:
                self.parameter_panel.cache_runtime_parameter(card_id, param_name, new_value)
            if self.parameter_panel and self.parameter_panel.current_card_id == card_id:
                self.parameter_panel.update_parameter_value(param_name, new_value)
        except Exception as exc:
            logger.warning(f"参数面板更新失败: {exc}")

    def _connect_card_parameter_signals(self, card):
        """连接卡片参数面板相关信号"""
        # 防止重复连接导致信号累积
        try:
            if not card.property("_mw_param_signal_connected"):
                from PySide6.QtCore import Qt
                card.edit_settings_requested.connect(self._show_parameter_panel, Qt.ConnectionType.UniqueConnection)
                card.setProperty("_mw_param_signal_connected", True)
        except Exception:
            pass

    def _connect_parameter_panel_signals(self):
        """连接参数面板相关信号"""
        # 检查是否有当前工作流
        if not self.workflow_view or not hasattr(self.workflow_view, 'cards'):
            return
        # 连接工作流视图中卡片的参数编辑请求
        for card in self.workflow_view.cards.values():
            self._connect_card_parameter_signals(card)

    def load_workflow(self):
        """加载工作流 - 在参数面板中显示收藏列表"""
        if hasattr(self, 'parameter_panel') and self.parameter_panel:
            self.parameter_panel.show_favorites()
            self._parameter_panel_visible = True

    def _on_card_added(self, card):
        """处理新卡片添加事件"""
        logger.info(f"新卡片添加: {card.card_id}")
        self._connect_card_parameter_signals(card)

    def _on_parameter_panel_closed(self):
        """处理参数面板关闭"""
        logger.info("参数面板已关闭")
        self._parameter_panel_visible = False

    def _schedule_parameter_panel_reposition(self, delay_ms: int = 16):
        """合并高频移动事件，避免重定位任务在事件队列中堆积。"""
        if not self._parameter_panel_visible or not hasattr(self, 'parameter_panel'):
            return
        if hasattr(self.parameter_panel, '_is_dragging') and self.parameter_panel._is_dragging:
            return
        self._parameter_panel_reposition_timer.start(max(0, int(delay_ms)))

    def _reposition_parameter_panel_if_needed(self):
        """定时触发参数面板重定位，统一入口便于防御性检查。"""
        if not self._parameter_panel_visible or not hasattr(self, 'parameter_panel'):
            return
        if hasattr(self.parameter_panel, '_is_dragging') and self.parameter_panel._is_dragging:
            return
        try:
            self.parameter_panel._position_panel()
        except Exception as e:
            logger.debug(f"参数面板重定位失败: {e}")

    def _smart_sync_parameter_panel_activation(self):
        """智能同步参数面板激活状态，保护输入框焦点"""
        # 关闭参数面板吸附时，不做主窗口/参数面板焦点联动，避免互相置顶
        if not self.config.get('enable_parameter_panel_snap', True):
            return
        if not self.isActiveWindow() or not self.parameter_panel.isVisible():
            return
        # 检查参数面板中是否有输入控件获得焦点
        focus_widget = QApplication.focusWidget()
        if focus_widget and isinstance(focus_widget, (QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit)):
            # 检查焦点控件是否属于参数面板
            widget_parent = focus_widget
            while widget_parent:
                if widget_parent == self.parameter_panel:
                    logger.debug(f"参数面板输入控件 {focus_widget} 获得焦点，跳过激活同步")
                    return
                widget_parent = widget_parent.parent()
        # 如果参数面板已经激活，不需要重复激活
        if self.parameter_panel.isActiveWindow():
            return
        # 保存当前焦点控件
        saved_focus = QApplication.focusWidget()
        # 重新定位参数面板
        self.parameter_panel._position_panel()
        # 仅提升层级，不主动抢焦点
        show_and_raise_widget(self.parameter_panel, log_prefix='参数面板同步')
        # 如果之前有焦点控件且仍然可用，尝试恢复焦点
        if saved_focus and saved_focus.isVisible() and saved_focus.isEnabled():
            # 使用定时器延迟恢复焦点
            QTimer.singleShot(50, lambda: self._restore_focus_to_widget(saved_focus))
        logger.debug("主窗口激活，智能同步参数面板（保护焦点）")

    def _restore_focus_to_widget(self, widget):
        """恢复焦点到指定控件"""
        try:
            if widget and widget.isVisible() and widget.isEnabled():
                widget.setFocus()
                logger.debug(f"恢复焦点到控件: {widget}")
        except Exception as e:
            logger.debug(f"恢复焦点失败: {e}")

    def resizeEvent(self, event):
        """主窗口大小改变时，重新定位参数面板"""
        super().resizeEvent(event)
        # 统一走合并调度，避免调整大小时多次排队重定位
        self._schedule_parameter_panel_reposition(33)

    def moveEvent(self, event):
        """主窗口移动时，重新定位参数面板"""
        super().moveEvent(event)
        self._schedule_parameter_panel_reposition(16)
