"""关闭方式选择。"""

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from themes import apply_rounded_popup


class CloseBehaviorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("closeBehaviorDialog")
        self.setWindowTitle("关闭程序")
        self.setModal(True)
        apply_rounded_popup(self, frameless=False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(QLabel("请选择关闭方式：", self))
        layout.addWidget(QLabel("最小化到托盘后程序仍在后台运行。", self))
        self.remember_check = QCheckBox("记住选择", self)
        layout.addWidget(self.remember_check)
        buttons = QHBoxLayout()
        buttons.addStretch()
        for text, name, result in (
            ("最小化到托盘", "closeTrayButton", 1),
            ("退出程序", "closeExitButton", 2),
            ("取消", "closeCancelButton", 0),
        ):
            button = QPushButton(text, self)
            button.setObjectName(name)
            button.clicked.connect(lambda _checked=False, choice=result: self.done(choice))
            buttons.addWidget(button)
        layout.addLayout(buttons)
