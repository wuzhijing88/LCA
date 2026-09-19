"""导出前选择要打包的工作区工作流（可剔除）。"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Set

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QMouseEvent, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class _CatalogCheckRow(QWidget):
    def __init__(self, title: str, path: str, *, checked: bool, parent=None):
        super().__init__(parent)
        self.check = QCheckBox(self)
        self.check.setChecked(bool(checked))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        text = str(title or "").strip() or "工作流"
        if str(path or "").strip():
            text = f"{text}\n{path}"
        self._label = QLabel(text, self)
        self._label.setWordWrap(False)
        self._label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        fm = self._label.fontMetrics()
        lines = [line for line in text.split("\n") if line] or [""]
        self._label.setMinimumHeight(fm.height() * len(lines) + fm.leading() * max(0, len(lines) - 1))
        layout.addWidget(self.check, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._label, 1)

    def sizeHint(self) -> QSize:
        fm = self._label.fontMetrics()
        lines = [line for line in str(self._label.text() or "").split("\n") if line] or [""]
        text_h = fm.height() * len(lines) + fm.leading() * max(0, len(lines) - 1)
        margins = self.layout().contentsMargins() if self.layout() is not None else None
        extra = (margins.top() + margins.bottom()) if margins else 16
        check_h = self.check.sizeHint().height()
        width = super().sizeHint().width()
        return QSize(max(width, 200), max(text_h, check_h) + extra)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            local = self.check.mapFrom(self, pos)
            if not self.check.rect().contains(local):
                self.check.toggle()
                event.accept()
                return
        super().mousePressEvent(event)


class WorkspaceExportPickerDialog(QDialog):
    """勾选要打进独立程序的工作流；至少保留一项。"""

    def __init__(
        self,
        catalog: List[Mapping[str, Any]],
        *,
        preselected_ids: Optional[Set[str]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("选择要打包的工作流")
        self.setMinimumSize(480, 420)
        self._catalog = [dict(item) for item in (catalog or []) if isinstance(item, Mapping)]
        self._preselected = set(preselected_ids) if preselected_ids else None

        layout = QVBoxLayout(self)
        hint = QLabel("可取消勾选不需要的工作流以减小安装包。至少保留一个。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._list = QListWidget(self)
        self._list.setObjectName("WorkspaceExportPickerList")
        self._list.setUniformItemSizes(False)
        self._list.setSpacing(2)
        layout.addWidget(self._list, 1)

        row = QHBoxLayout()
        all_btn = QPushButton("全选", self)
        none_btn = QPushButton("全不选", self)
        all_btn.clicked.connect(self._select_all)
        none_btn.clicked.connect(self._select_none)
        row.addWidget(all_btn)
        row.addWidget(none_btn)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self._ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_btn.setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate()
        self._refresh_ok()

    def _populate(self) -> None:
        self._list.clear()
        for entry in self._catalog:
            sid = str(entry.get("id") or "").strip()
            if not sid:
                continue
            title = str(entry.get("title") or sid).strip() or sid
            path = str(entry.get("filepath") or "").strip()
            if self._preselected is None:
                checked = True
            else:
                checked = sid in self._preselected
            item = QListWidgetItem()
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            item.setData(Qt.ItemDataRole.UserRole, sid)
            row = _CatalogCheckRow(title, path, checked=checked, parent=self._list)
            row.check.toggled.connect(lambda *_: self._refresh_ok())
            self._list.addItem(item)
            self._list.setItemWidget(item, row)
            item.setSizeHint(row.sizeHint())
        self._sync_row_heights()

    def _sync_row_heights(self) -> None:
        for i in range(self._list.count()):
            item = self._list.item(i)
            row = self._row_at(i)
            if item is None or row is None:
                continue
            item.setSizeHint(row.sizeHint())

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._sync_row_heights()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_row_heights()

    def _row_at(self, index: int) -> Optional[_CatalogCheckRow]:
        item = self._list.item(index)
        widget = self._list.itemWidget(item) if item is not None else None
        return widget if isinstance(widget, _CatalogCheckRow) else None

    def _select_all(self) -> None:
        for i in range(self._list.count()):
            row = self._row_at(i)
            if row is not None:
                row.check.setChecked(True)
        self._refresh_ok()

    def _select_none(self) -> None:
        for i in range(self._list.count()):
            row = self._row_at(i)
            if row is not None:
                row.check.setChecked(False)
        self._refresh_ok()

    def _checked_ids(self) -> List[str]:
        ids: List[str] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            row = self._row_at(i)
            if item is None or row is None or not row.check.isChecked():
                continue
            sid = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if sid:
                ids.append(sid)
        return ids

    def _can_accept(self) -> bool:
        return bool(self._checked_ids())

    def _refresh_ok(self) -> None:
        if self._ok_btn is not None:
            self._ok_btn.setEnabled(self._can_accept())

    def selected_catalog(self) -> List[Dict[str, Any]]:
        wanted = set(self._checked_ids())
        return [dict(item) for item in self._catalog if str(item.get("id") or "") in wanted]


def filter_catalog_by_ids(
    catalog: List[Mapping[str, Any]],
    ids: Optional[Set[str]],
) -> List[Dict[str, Any]]:
    """按 id 集合过滤目录；ids 为 None 时返回全部副本。"""
    ordered = [dict(item) for item in (catalog or []) if isinstance(item, Mapping)]
    if ids is None:
        return ordered
    wanted = {str(x).strip() for x in ids if str(x).strip()}
    return [item for item in ordered if str(item.get("id") or "") in wanted]
