from ..parameter_panel_support import *


class ParameterPanelWidgetNumericTypeCheckboxMixin:
    def _create_numeric_checkbox_widget(self, name: str, current_value: Any):
        widget = QCheckBox()
        widget.setChecked(bool(current_value))
        widget.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, False)
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        widget.stateChanged.connect(lambda state: self._handle_numeric_checkbox_state_changed(name, state))
        widget.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, False)
        widget.setMouseTracking(False)

        event_filter = self._create_numeric_checkbox_event_filter(widget, name)
        widget.installEventFilter(event_filter)
        if not hasattr(self, '_event_filters'):
            self._event_filters = []
        self._event_filters.append(event_filter)
        return widget

    def _handle_numeric_checkbox_state_changed(self, name: str, state):
        checked = state == 2
        changed_parameters = {name: checked}
        if name == 'search_region_enabled' and not checked:
            changed_parameters.update(
                {
                    'search_region_x': 0,
                    'search_region_y': 0,
                    'search_region_width': 0,
                    'search_region_height': 0,
                }
            )
            logger.info('已清除识别区域坐标参数')
        self._apply_live_parameter_changes(changed_parameters)

    @staticmethod
    def _create_numeric_checkbox_event_filter(widget, name: str):
        class CheckboxEventFilter(QObject):
            def __init__(self, checkbox_widget, checkbox_name):
                super().__init__()
                self.checkbox_widget = checkbox_widget
                self.checkbox_name = checkbox_name

            def eventFilter(self, obj, event):
                if event.type() == event.Type.MouseButtonPress:
                    logger.debug(f'复选框 {self.checkbox_name} 接收到鼠标按下事件')
                    current_state = self.checkbox_widget.isChecked()
                    new_state = not current_state
                    self.checkbox_widget.setChecked(new_state)
                    logger.debug(f'复选框 {self.checkbox_name} 状态从 {current_state} 切换到 {new_state}')
                    self.checkbox_widget.clicked.emit()
                    self.checkbox_widget.toggled.emit(new_state)
                    return True
                return False

        return CheckboxEventFilter(widget, name)
