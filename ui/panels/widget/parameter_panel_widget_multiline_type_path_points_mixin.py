from ..parameter_panel_support import *
from ...selectors.multi_coordinate_text import (
    MULTI_COORDINATE_BUTTON_TEXT,
    MULTI_COORDINATE_PLACEHOLDER,
)


class ParameterPanelWidgetMultilineTypePathPointsMixin:
    def _create_multiline_path_points_widget(self, name: str, current_value: Any):
        path_widget = QWidget()
        path_layout = QVBoxLayout(path_widget)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(4)

        text_edit = QPlainTextEdit()
        text_edit.setPlainText(str(current_value) if current_value is not None else '')
        text_edit.setMaximumHeight(100)
        text_edit.setPlaceholderText(MULTI_COORDINATE_PLACEHOLDER)

        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)

        coord_button = ResponsiveButton(MULTI_COORDINATE_BUTTON_TEXT)
        coord_button.setProperty('class', 'primary')
        coord_button.clicked.connect(lambda: self._select_multi_coordinates(name))

        clear_button = ResponsiveButton('清空')
        clear_button.setProperty('class', 'danger')
        clear_button.clicked.connect(text_edit.clear)

        button_layout.addWidget(coord_button)
        button_layout.addWidget(clear_button)
        button_layout.addStretch()

        path_layout.addWidget(text_edit)
        path_layout.addLayout(button_layout)

        self._register_widget(name, text_edit)
        return path_widget
