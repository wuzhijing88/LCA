from ..parameter_panel_support import *


class ParameterPanelWidgetRecordingToolHintMixin:

    def _create_recording_tool_widget_by_hint(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        widget_hint = param_def.get('widget_hint', '')
        widget = None
        if widget_hint == 'record_control':
            widget = ResponsiveButton("开始录制")
            widget.setProperty("class", "primary")
            widget.clicked.connect(lambda: self._toggle_recording())
            self._register_widget(name, widget, stores_value=False)

        elif widget_hint == 'replay_control':
            action_count = self._get_recorded_action_count()
            widget = ResponsiveButton(
                f"测试回放 ({action_count}个操作)" if action_count else "测试回放"
            )
            widget.setProperty("class", "primary")
            widget.clicked.connect(lambda: self._toggle_replay())
            self._register_widget(name, widget, stores_value=False)

        elif widget_hint == 'action_editor':
            action_count = self._get_recorded_action_count()
            widget = ResponsiveButton(
                f"编辑步骤 ({action_count}个)" if action_count else "编辑步骤"
            )
            widget.setProperty("class", "secondary")
            widget.clicked.connect(lambda: self._open_action_editor())
            self._register_widget(name, widget, stores_value=False)

        return widget
