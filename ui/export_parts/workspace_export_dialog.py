"""导出前选择要打包的工作区工作流（可剔除）。"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Set

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)


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
        self._list.itemChanged.connect(lambda *_: self._refresh_ok())
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
        self._ok_btn.setText("继续")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate()
        self._refresh_ok()

    def _populate(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for entry in self._catalog:
            sid = str(entry.get("id") or "").strip()
            if not sid:
                continue
            title = str(entry.get("title") or sid).strip() or sid
            path = str(entry.get("filepath") or "").strip()
            label = title if not path else f"{title}\n{path}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, sid)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            if self._preselected is None:
                checked = True
            else:
                checked = sid in self._preselected
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self._list.addItem(item)
        self._list.blockSignals(False)

    def _select_all(self) -> None:
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.CheckState.Checked)
        self._list.blockSignals(False)
        self._refresh_ok()

    def _select_none(self) -> None:
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.CheckState.Unchecked)
        self._list.blockSignals(False)
        self._refresh_ok()

    def _checked_ids(self) -> List[str]:
        ids: List[str] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item is None or item.checkState() != Qt.CheckState.Checked:
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
