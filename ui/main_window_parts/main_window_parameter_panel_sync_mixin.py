import logging
from typing import Any

logger = logging.getLogger(__name__)


class MainWindowParameterPanelSyncMixin:

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
