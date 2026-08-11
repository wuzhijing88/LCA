from ..parameter_panel_support import *


class ParameterPanelFavoritesViewPageToolbarMixin:

    def _create_favorites_toolbar_button(self, text, tooltip, slot, width=None):
        button = QPushButton(text)
        if tooltip:
            button.setToolTip(tooltip)
        if width is not None:
            button.setFixedWidth(width)
        button.clicked.connect(slot)
        return button

    def _create_favorites_toolbar(self, parent_layout):
        toolbar_layout = QHBoxLayout()

        action_buttons = [
            ("添加工作区", "添加工作流工作区目录", self._on_favorites_add, None),
            ("移除工作区", "移除当前选中行所属的工作区；左侧勾选仅用于启动", self._on_favorites_remove, None),
        ]
        for text, tooltip, slot, width in action_buttons:
            toolbar_layout.addWidget(
                self._create_favorites_toolbar_button(text, tooltip, slot, width)
            )

        toolbar_layout.addStretch()

        toggle_buttons = [
            ("全选", None, self._on_favorites_select_all, 50),
            ("取消", None, self._on_favorites_deselect_all, 50),
        ]
        for text, tooltip, slot, width in toggle_buttons:
            toolbar_layout.addWidget(
                self._create_favorites_toolbar_button(text, tooltip, slot, width)
            )

        parent_layout.addLayout(toolbar_layout)
