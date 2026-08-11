from ..parameter_panel_support import *


class ParameterPanelWidgetInteractiveToolHintActionMixin:
    def _create_interactive_element_picker_widget(self, param_def: Dict[str, Any]):
        picker_button = QPushButton(param_def.get('button_text', '拾取元素'))
        picker_button.setToolTip(
            param_def.get('tooltip', '点击后移动鼠标到目标元素，右键确认拾取')
        )
        picker_button.setStyleSheet(
            """
            QPushButton {
                background-color: #1890ff;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #40a9ff;
            }
            QPushButton:pressed {
                background-color: #096dd9;
            }
            QPushButton:disabled {
                background-color: #d9d9d9;
                color: #999;
            }
            """
        )
        picker_button.clicked.connect(self._start_element_picking)
        self._element_picker_button = picker_button
        return picker_button

    def _create_interactive_browser_accessibility_widget(self, param_def: Dict[str, Any]):
        acc_button = QPushButton(param_def.get('button_text', '启用浏览器辅助功能'))
        acc_button.setToolTip(param_def.get('tooltip', ''))
        acc_button.setStyleSheet(
            """
            QPushButton {
                background-color: #52c41a;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #73d13d;
            }
            QPushButton:pressed {
                background-color: #389e0d;
            }
            """
        )
        acc_button.clicked.connect(self._enable_browser_accessibility)
        return acc_button

    def _create_interactive_yolo_preview_widget(self, param_def: Dict[str, Any]):
        widget = ResponsiveButton(param_def.get('button_text', '启动实时预览'))
        widget.setProperty('class', 'primary')
        widget.clicked.connect(self._start_yolo_realtime_preview)
        return widget
