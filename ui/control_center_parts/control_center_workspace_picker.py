"""中控从主窗口的工作区列表选择工作流。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


class WorkspaceWorkflowPickDialog(QDialog):
    def __init__(self, favorites: list[dict], *, parent=None, title: str):
        super().__init__(parent)
        self.setObjectName("ControlCenterWorkspacePicker")
        self.setWindowTitle(f"工作区 · {title}")
        self.resize(640, 440)

        layout = QVBoxLayout(self)
        hint = QLabel("从工作区选择要分配的工作流，按住 Ctrl 或 Shift 可多选。", self)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("搜索工作流名称或路径")
        layout.addWidget(self._search)
        self._list = QListWidget(self)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for favorite in favorites:
            path = favorite["filepath"]
            item = QListWidgetItem(f"{favorite['name']}\n{path}", self._list)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
        layout.addWidget(self._list, 1)
        self._empty_hint = QLabel("工作区暂无工作流，请先在主窗口的工作区添加工作流。", self)
        self._empty_hint.setWordWrap(True)
        self._empty_hint.setVisible(self._list.count() == 0)
        layout.addWidget(self._empty_hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok.setText("分配")
        self._ok.setProperty("primary", True)
        self._ok.setEnabled(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._list.itemSelectionChanged.connect(self._refresh_selection)
        self._list.itemDoubleClicked.connect(self._accept_item)
        self._search.textChanged.connect(self._filter_items)
        layout.addWidget(buttons)

    def selected_paths(self) -> list[str]:
        return [
            self._list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self._list.count())
            if self._list.item(row).isSelected() and not self._list.item(row).isHidden()
        ]

    def _refresh_selection(self):
        self._ok.setEnabled(bool(self.selected_paths()))

    def _filter_items(self, text: str):
        query = text.strip().casefold()
        visible_count = 0
        for row in range(self._list.count()):
            item = self._list.item(row)
            visible = query in item.text().casefold()
            if not visible:
                item.setSelected(False)
            item.setHidden(not visible)
            visible_count += int(visible)
        self._empty_hint.setText(
            "没有匹配的工作流。" if self._list.count()
            else "工作区暂无工作流，请先在主窗口的工作区添加工作流。"
        )
        self._empty_hint.setVisible(visible_count == 0)
        self._refresh_selection()

    def _accept_item(self, _item):
        if self.selected_paths():
            self.accept()


def pick_workspace_workflow_files(host, title: str, favorites: list[dict]) -> list[str]:
    dialog = WorkspaceWorkflowPickDialog(favorites, parent=host, title=title)
    try:
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selected_paths()
        return []
    finally:
        dialog.close()
        dialog.deleteLater()
