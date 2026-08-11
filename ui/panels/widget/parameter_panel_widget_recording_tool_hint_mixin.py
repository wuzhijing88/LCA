from ..parameter_panel_support import *


class ParameterPanelWidgetRecordingToolHintMixin:

    def _create_recording_tool_widget_by_hint(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        widget_hint = param_def.get('widget_hint', '')
        widget = None
        if widget_hint == 'record_control':
            # 录制控制按钮 - 简单按钮设计，与其他工具按钮一致
            widget = ResponsiveButton("开始录制")
            widget.setProperty("class", "primary")
            widget.clicked.connect(lambda: self._toggle_recording())  # 修改为切换录制
            self._register_widget(name, widget, stores_value=False)

        elif widget_hint == 'replay_control':
            # 回放控制按钮 - 简单按钮设计，与其他工具按钮一致
            widget = ResponsiveButton("测试回放")

            # 如果有录制数据，显示操作数量
            recorded_data = self.current_parameters.get('recorded_actions', '')
            if recorded_data:
                try:
                    import json
                    data = json.loads(recorded_data)
                    # 兼容新旧格式
                    if isinstance(data, dict) and 'actions' in data:
                        actions = data['actions']
                    elif isinstance(data, list):
                        actions = data
                    else:
                        actions = []

                    if actions:
                        widget.setText(f"测试回放 ({len(actions)}个操作)")
                except:
                    pass

            widget.setProperty("class", "primary")
            widget.clicked.connect(lambda: self._toggle_replay())  # 修改为切换回放
            self._register_widget(name, widget, stores_value=False)

        elif widget_hint == 'action_editor':
            # 步骤编辑器按钮
            widget = ResponsiveButton("编辑步骤")

            # 如果有录制数据，显示步骤数量
            recorded_data = self.current_parameters.get('recorded_actions', '')
            if recorded_data:
                try:
                    import json
                    data = json.loads(recorded_data)
                    # 兼容新旧格式
                    if isinstance(data, dict) and 'actions' in data:
                        actions = data['actions']
                    elif isinstance(data, list):
                        actions = data
                    else:
                        actions = []

                    if actions:
                        widget.setText(f"编辑步骤 ({len(actions)}个)")
                except:
                    pass

            widget.setProperty("class", "secondary")
            widget.clicked.connect(lambda: self._open_action_editor())
            self._register_widget(name, widget, stores_value=False)

        return widget
        return widget
