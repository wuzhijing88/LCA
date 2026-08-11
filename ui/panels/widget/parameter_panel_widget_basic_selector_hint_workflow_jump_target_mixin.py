from ..parameter_panel_support import *


class ParameterPanelWidgetBasicSelectorHintWorkflowJumpTargetMixin:
    def _create_jump_target_selector_widget(self, name: str, current_value: Any):
        widget = QComboBox(self)
        self._remove_combobox_shadow(widget)
        widget.addItem('无跳转', None)

        sorted_cards = sorted(self.workflow_cards_info.items())
        for _seq_id, (task_type, card_id) in sorted_cards:
            if card_id != self.current_card_id:
                widget.addItem(f'{task_type} (ID: {card_id})', card_id)

        actual_value = current_value
        if actual_value is None:
            real_time_params = self._get_real_time_card_parameters()
            if name in real_time_params and real_time_params[name] is not None:
                actual_value = real_time_params[name]
                logger.info(f'[CARD_SELECTOR] {name} 从实时参数获取值: {actual_value}')

        if actual_value is not None:
            index = widget.findData(actual_value)
            if index >= 0:
                widget.setCurrentIndex(index)
                logger.info(f'[CARD_SELECTOR] 设置 {name} 的初始值为: {actual_value}, 索引: {index}')
            else:
                logger.warning(f'[CARD_SELECTOR] 未找到 {name} 的值 {actual_value} 对应的选项')
        return widget
