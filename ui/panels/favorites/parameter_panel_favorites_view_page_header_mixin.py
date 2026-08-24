from ..parameter_panel_support import *


class ParameterPanelFavoritesViewPageHeaderMixin:

    def _init_favorites_column_metrics(self):
        self._favorites_col_metrics = {
            "item_outer_margin": 2,
            "header_left_margin": 6,
            "header_right_margin": 6,
            "item_left_margin": 4,
            "item_right_margin": 4,
            "spacing": 6,
            "check_width": 20,
        }

    def _create_favorites_header(self, parent_layout):
        self._init_favorites_column_metrics()
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(
            self._favorites_col_metrics["header_left_margin"],
            0,
            self._favorites_col_metrics["header_right_margin"],
            0,
        )
        header_layout.setSpacing(self._favorites_col_metrics["spacing"])
        self._favorites_header_layout = header_layout

        header_check = QLabel("")
        header_check.setFixedWidth(self._favorites_col_metrics["check_width"])
        header_layout.addWidget(header_check)

        header_name = QLabel("名称")
        header_layout.addWidget(header_name, 1)
        parent_layout.addLayout(header_layout)
