from __future__ import annotations

import copy
from typing import Any, Dict, List, Mapping, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app_core.player.package import PlayerPackage

PLAYER_WORKFLOW_URI_PREFIX = "player://script/"
ENTRY_SCRIPT_ID = "__entry__"


def workflow_uri_for_script(script_id: str) -> str:
    return PLAYER_WORKFLOW_URI_PREFIX + str(script_id or "").strip()


def script_id_from_workflow_uri(path: str) -> str:
    text = str(path or "").strip()
    if text.startswith(PLAYER_WORKFLOW_URI_PREFIX):
        return text[len(PLAYER_WORKFLOW_URI_PREFIX) :].strip()
    return ""


def catalog_player_workflows(package: PlayerPackage) -> List[Dict[str, Any]]:
    titles: Dict[str, str] = {}
    for meta in (package.manifest or {}).get("scripts") or []:
        if not isinstance(meta, Mapping):
            continue
        sid = str(meta.get("id") or "").strip()
        if not sid:
            continue
        titles[sid] = str(meta.get("title") or sid).strip() or sid
    items: List[Dict[str, Any]] = []
    for sid, data in dict(package.scripts or {}).items():
        key = str(sid or "").strip()
        if not key or not isinstance(data, Mapping) or not data:
            continue
        items.append(
            {
                "file_path": workflow_uri_for_script(key),
                "data": dict(data),
                "name": titles.get(key, key),
            }
        )
    if items:
        return items
    data = package.workflow_data
    if isinstance(data, Mapping) and data:
        name = str((package.manifest or {}).get("app_name") or "").strip() or "主工作流"
        return [
            {
                "file_path": workflow_uri_for_script(ENTRY_SCRIPT_ID),
                "data": dict(data),
                "name": name,
            }
        ]
    return []


def load_player_workflow_entry(
    package: PlayerPackage,
    file_path: str,
    name: str = "",
) -> Optional[Dict[str, Any]]:
    sid = script_id_from_workflow_uri(file_path)
    if not sid:
        return None
    data: Any = None
    if sid == ENTRY_SCRIPT_ID:
        data = package.workflow_data
    else:
        data = (package.scripts or {}).get(sid)
        if not isinstance(data, Mapping):
            entry_id = str((package.manifest or {}).get("entry_script_id") or "").strip()
            if sid == entry_id:
                data = package.workflow_data
    if not isinstance(data, Mapping) or not data:
        return None
    title = str(name or "").strip()
    if not title:
        for item in catalog_player_workflows(package):
            if str(item.get("file_path") or "") == workflow_uri_for_script(sid):
                title = str(item.get("name") or "")
                break
        if not title:
            title = str((package.manifest or {}).get("app_name") or "").strip() or sid
    return {
        "file_path": workflow_uri_for_script(sid),
        "data": copy.deepcopy(dict(data)),
        "name": title,
    }


class PlayerWorkflowPickDialog(QDialog):
    """从独立程序包里选择要分配给中控的工作流。"""

    def __init__(self, catalog: List[Dict[str, Any]], parent=None, title: str = ""):
        super().__init__(parent)
        self.setObjectName("PlayerWorkflowPickDialog")
        self.setWindowTitle(str(title or "").strip() or "选择工作流")
        self.setModal(True)
        self.resize(420, 360)
        self._catalog = [item for item in catalog if isinstance(item, dict)]
        self._selected: List[Dict[str, Any]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)
        hint = QLabel("选择要分配的工作流，可多选。")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self._list = QListWidget(self)
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        for index, item in enumerate(self._catalog):
            row = QListWidgetItem(str(item.get("name") or f"工作流{index + 1}"))
            row.setData(Qt.ItemDataRole.UserRole, index)
            self._list.addItem(row)
        if self._list.count() > 0:
            self._list.selectAll()
        self._list.itemDoubleClicked.connect(self._accept_current)
        root.addWidget(self._list, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消", self)
        cancel.clicked.connect(self.reject)
        ok = QPushButton("确定", self)
        ok.setProperty("primary", True)
        ok.clicked.connect(self._accept_current)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        root.addLayout(buttons)

    def selected_entries(self) -> List[Dict[str, Any]]:
        return list(self._selected)

    def _accept_current(self, *_args) -> None:
        rows = self._list.selectedItems()
        if not rows:
            QMessageBox.warning(self, "无法分配", "请先选择工作流")
            return
        selected: List[Dict[str, Any]] = []
        for row in rows:
            index = row.data(Qt.ItemDataRole.UserRole)
            try:
                item = self._catalog[int(index)]
            except (TypeError, ValueError, IndexError):
                continue
            if isinstance(item, dict):
                selected.append(item)
        if not selected:
            QMessageBox.warning(self, "无法分配", "请先选择工作流")
            return
        self._selected = selected
        self.accept()


def pick_player_workflow_entries(host, package: PlayerPackage, title: str) -> List[Dict[str, Any]]:
    catalog = catalog_player_workflows(package)
    if not catalog:
        QMessageBox.warning(host, "无法分配", "当前独立程序没有可分配的工作流")
        return []
    dialog = PlayerWorkflowPickDialog(catalog, parent=host, title=title)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return []
    return dialog.selected_entries()
