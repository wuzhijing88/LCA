from ..parameter_panel_support import *


class ParameterPanelWidgetStandardTextTypeCoordinateMixin:
    def _create_standard_text_coordinate_widget(self, name: str, current_value: Any):
        # 坐标输入类型 - 带坐标选择工具
        coord_widget = QWidget()
        coord_layout = QHBoxLayout(coord_widget)
        coord_layout.setContentsMargins(0, 0, 0, 0)

        coord_edit = QLineEdit(str(current_value) if current_value else "0,0")
        coord_edit.setPlaceholderText("X,Y")
        # 设置基本属性确保输入功能
        coord_edit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        coord_button = ResponsiveButton("选择坐标")
        coord_button.setProperty("class", "primary")
        coord_button.clicked.connect(lambda: self._select_coordinate(name))

        coord_layout.addWidget(coord_edit)
        coord_layout.addWidget(coord_button)

        widget = coord_widget
        self._register_widget(name, coord_edit)  # 存储编辑框用于获取值
        return widget
