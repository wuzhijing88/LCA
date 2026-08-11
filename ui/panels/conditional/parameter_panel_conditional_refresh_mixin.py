from ..parameter_panel_support import *


class ParameterPanelConditionalRefreshMixin:

    def _refresh_conditional_widgets(self):
        """刷新条件控件的显示/隐藏状态"""
        # 保存当前滚动位置
        scroll_pos = 0
        if hasattr(self, 'scroll_area') and self.scroll_area.verticalScrollBar():
            scroll_pos = self.scroll_area.verticalScrollBar().value()

        # 先从卡片实时读取最新参数，确保不丢失未显示的参数值（如跳转目标）
        real_time_params = self._get_real_time_card_parameters()

        # 收集当前控件的值
        collected_params = self._collect_current_parameters()

        # 合并参数到current_parameters
        # 优先级：控件值 > 实时参数 > 当前缓存
        # 但对于card_selector，优先使用实时参数，避免刚创建的控件覆盖正确值

        # 1. 先用实时参数更新current_parameters（保底，确保所有参数都有值）
        for name, value in real_time_params.items():
            if value is not None:
                self.current_parameters[name] = value
                if name in ['success_jump_target_id', 'failure_jump_target_id']:
                    logger.info(f"[REFRESH] 从实时参数更新 {name} = {value}")

        # 2. 再用控件值更新（用户在界面上的修改优先）
        for name, value in collected_params.items():
            param_def = self.param_definitions.get(name, {})
            widget_hint = param_def.get('widget_hint', '')
            # 对于card_selector，只在控件值非None时更新，避免覆盖实时参数
            if widget_hint in ['card_selector', 'jump_target_selector']:
                if value is not None:
                    self.current_parameters[name] = value
                    if name in ['success_jump_target_id', 'failure_jump_target_id']:
                        logger.info(f"[REFRESH] 从控件更新 {name} = {value}")
            else:
                # 其他类型的参数直接更新
                self.current_parameters[name] = value

        # 先清除现有的控件
        self._clear_content()

        # 重新创建参数控件
        self._create_parameter_widgets()

        # 恢复滚动位置
        if hasattr(self, 'scroll_area') and self.scroll_area.verticalScrollBar():
            QTimer.singleShot(10, lambda: self.scroll_area.verticalScrollBar().setValue(scroll_pos))


    def _rebuild_parameter_widgets(self, preserve_scroll: bool = True):
        """仅重建参数控件（不回收/合并参数值）"""
        scroll_pos = 0
        if preserve_scroll and hasattr(self, 'scroll_area') and self.scroll_area.verticalScrollBar():
            scroll_pos = self.scroll_area.verticalScrollBar().value()

        self._clear_content()
        self._create_parameter_widgets()

        if preserve_scroll and hasattr(self, 'scroll_area') and self.scroll_area.verticalScrollBar():
            QTimer.singleShot(10, lambda: self.scroll_area.verticalScrollBar().setValue(scroll_pos))

