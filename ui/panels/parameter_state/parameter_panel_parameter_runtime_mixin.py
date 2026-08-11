from ..parameter_panel_support import *


class ParameterPanelParameterRuntimeMixin:

    def _get_real_time_card_parameters(self) -> dict:
        """
        从卡片实时读取最新参数

        这个方法确保获取卡片的实时参数，而不是使用缓存的 current_parameters
        这样可以捕获在参数面板打开期间，通过其他方式（如删除连线）修改的参数

        Returns:
            dict: 卡片的实时参数，如果无法获取则返回缓存的参数
        """
        try:
            # 首先尝试从主窗口获取当前的workflow_view
            current_workflow_view = None
            if hasattr(self, 'main_window') and self.main_window:
                # 尝试从标签页系统获取
                if hasattr(self.main_window, 'workflow_tab_widget') and self.main_window.workflow_tab_widget:
                    current_task_id = self.main_window.workflow_tab_widget.get_current_task_id()
                    if current_task_id is not None and current_task_id in self.main_window.workflow_tab_widget.task_views:
                        current_workflow_view = self.main_window.workflow_tab_widget.task_views[current_task_id]
                        logger.debug(f"[实时参数] 从主窗口标签页获取workflow_view")

                # 回退到旧系统
                if current_workflow_view is None and hasattr(self.main_window, 'workflow_view'):
                    current_workflow_view = self.main_window.workflow_view
                    logger.debug(f"[实时参数] 从主窗口旧系统获取workflow_view")

            # 在获取的workflow_view中查找卡片
            if current_workflow_view and hasattr(current_workflow_view, 'cards'):
                if self.current_card_id in current_workflow_view.cards:
                    card = current_workflow_view.cards[self.current_card_id]
                    if hasattr(card, 'parameters'):
                        logger.debug(f"[实时参数] 从卡片 {self.current_card_id} 读取实时参数成功")
                        return card.parameters.copy()

            # 如果无法获取实时参数，回退到缓存参数
            logger.debug(f"[实时参数] 无法读取卡片 {self.current_card_id} 的实时参数，使用缓存参数")
            return self.current_parameters.copy()

        except Exception as e:
            logger.warning(f"[实时参数] 读取实时参数失败: {e}，使用缓存参数")
            return self.current_parameters.copy()


    def cache_runtime_parameter(self, card_id: int, param_name: str, value: Any) -> None:
        """缓存运行时参数值（仅用于显示，不写入工作流文件）。"""
        if not card_id or not param_name:
            return
        self.runtime_parameters[(card_id, param_name)] = value


    def _get_runtime_parameter(self, card_id: int, param_name: str) -> Any:
        """获取运行时参数值，优先使用任务模块，必要时回退到模块缓存。"""
        runtime_value = None
        if self.task_module and hasattr(self.task_module, 'get_runtime_parameter'):
            try:
                runtime_value = self.task_module.get_runtime_parameter(card_id, param_name)
            except Exception as exc:
                logger.debug(f"[运行时参数] 获取失败: {exc}")
        return runtime_value


    def update_parameter_value(self, param_name: str, value: Any) -> None:
        """更新指定参数的显示值（不写回工作流文件）。"""
        if not param_name:
            return
        text_value = "" if value is None else str(value)
        self.current_parameters[param_name] = value
        widget = self._get_value_widget(param_name)
        if not widget:
            return
        try:
            widget.blockSignals(True)
            if hasattr(widget, "setPlainText"):
                widget.setPlainText(text_value)
            elif hasattr(widget, "setText"):
                widget.setText(text_value)
        finally:
            widget.blockSignals(False)


    def refresh_runtime_parameters(self, card_id: Optional[int] = None) -> None:
        """从任务模块刷新运行时参数显示。"""
        if not self.task_module or not hasattr(self.task_module, 'get_runtime_parameter'):
            return
        if card_id is None:
            card_id = self.current_card_id
        if not card_id:
            return
        for param_name, param_def in self.param_definitions.items():
            if param_def.get('save_to_workflow', True):
                continue
            runtime_value = self._get_runtime_parameter(card_id, param_name)
            if runtime_value is None:
                continue
            self.cache_runtime_parameter(card_id, param_name, runtime_value)
            if self.current_card_id == card_id:
                self.update_parameter_value(param_name, runtime_value)

