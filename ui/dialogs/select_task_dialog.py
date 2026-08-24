from typing import List, Optional
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QSpacerItem, QSizePolicy, QButtonGroup, QFrame, QScrollArea
)
from PySide6.QtCore import Qt


class SelectTaskDialog(QDialog):
    """A custom dialog for selecting a task type with grid button layout."""
    def __init__(self, task_types: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择任务类型")
        self.setMinimumWidth(400)
        self.resize(420, 460)

        self._selected_task_type: Optional[str] = None
        self.task_buttons = {}

        # --- Main Layout ---
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(15)
        self.main_layout.setContentsMargins(20, 20, 20, 20)

        # --- Info Label ---
        self.info_label = QLabel("请选择要添加的任务类型:")
        self.info_label.setObjectName("infoLabel")
        self.main_layout.addWidget(self.info_label)

        # --- Task Grid (2 columns) ---
        grid_frame = QFrame()
        grid_layout = QGridLayout(grid_frame)
        grid_layout.setSpacing(8)
        grid_layout.setContentsMargins(0, 0, 0, 0)

        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)

        # 分成两列排列
        num_cols = 2
        for i, task_type in enumerate(task_types):
            row = i // num_cols
            col = i % num_cols

            display_text = task_type
            btn = QPushButton(display_text)
            btn.setCheckable(True)
            btn.setMinimumHeight(36)
            btn.setMinimumWidth(150)
            btn.setObjectName("taskButton")

            self.button_group.addButton(btn)
            self.task_buttons[task_type] = btn
            grid_layout.addWidget(btn, row, col)

            # 点击按钮时记录选择
            btn.clicked.connect(lambda checked, t=task_type: self._on_task_selected(t))

        # 默认选中第一个
        if task_types:
            first_btn = self.task_buttons[task_types[0]]
            first_btn.setChecked(True)
            self._selected_task_type = task_types[0]

        grid_scroll = QScrollArea()
        grid_scroll.setObjectName("taskGridScroll")
        grid_scroll.setWidgetResizable(True)
        grid_scroll.setFrameShape(QFrame.NoFrame)
        grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        grid_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        grid_scroll.setWidget(grid_frame)
        grid_scroll.setFixedHeight(300)

        self.main_layout.addWidget(grid_scroll)

        # --- Spacer ---
        self.main_layout.addSpacerItem(QSpacerItem(20, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # --- Bottom Buttons ---
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        self.ok_button = QPushButton("确定")
        self.ok_button.setObjectName("okButton")
        self.ok_button.setDefault(True)
        self.ok_button.setMinimumHeight(32)

        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.setMinimumHeight(32)

        button_layout.addStretch(1)
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        button_layout.addStretch(1)
        self.main_layout.addLayout(button_layout)

        # --- Style ---
        # 仅设置布局相关样式，颜色由全局主题控制
        self.setStyleSheet("""
            QLabel#infoLabel {
                font-size: 14px;
                margin-bottom: 5px;
            }
            QPushButton#taskButton {
                font-size: 13px;
                border-radius: 5px;
                padding: 8px 15px;
                text-align: center;
            }
            QPushButton#okButton {
                font-size: 13px;
                font-weight: bold;
                border-radius: 5px;
                padding: 8px 25px;
            }
            QPushButton#cancelButton {
                font-size: 13px;
                border-radius: 5px;
                padding: 8px 20px;
            }
        """)

        # --- Connections ---
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

    def _on_task_selected(self, task_type: str):
        """记录用户选择的任务类型"""
        self._selected_task_type = task_type

    def selected_task_type(self) -> Optional[str]:
        """Returns the currently selected task type."""
        return self._selected_task_type
