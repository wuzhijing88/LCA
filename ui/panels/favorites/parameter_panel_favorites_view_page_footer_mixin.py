from ..parameter_panel_support import *


class ParameterPanelFavoritesViewPageFooterMixin:

    def _create_favorites_start_button(self, parent_layout):
        self._favorites_start_btn = QPushButton("启动选中的工作流")
        self._favorites_start_btn.setMinimumHeight(36)
        self._favorites_start_btn.setStyleSheet("font-weight: bold;")
        self._favorites_start_btn.clicked.connect(self._on_favorites_start_batch)
        parent_layout.addWidget(self._favorites_start_btn)
