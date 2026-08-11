from ..parameter_panel_support import *


class ParameterPanelWidgetBasicSelectorHintWorkflowBoundWindowMixin:
    def _create_bound_window_selector_widget(self, current_value: Any):
        widget = QComboBox(self)
        self._remove_combobox_shadow(widget)
        widget.addItem('使用默认窗口', None)

        enabled_windows = self._get_enabled_bound_windows_for_selector()
        for idx, window_info in enumerate(enabled_windows, 1):
            window_title = str(window_info.get('title') or f'窗口{idx}').strip()
            widget.addItem(f'窗口{idx}: {window_title}', idx)

        selected_index = None
        try:
            if current_value not in (None, '', 'None', 'none', 0, '0'):
                selected_index = int(current_value)
        except Exception:
            selected_index = None
        if selected_index is not None and selected_index > 0:
            combo_index = widget.findData(selected_index)
            if combo_index >= 0:
                widget.setCurrentIndex(combo_index)
        return widget
