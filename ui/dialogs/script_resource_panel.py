# -*- coding: utf-8 -*-
"""自定义脚本卡片的资源栏：本卡导入的图、模型和音频。"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.dialogs.script_resources import (
    AUDIO_EXTS,
    MODEL_EXTS,
    delete_resource_file,
    import_resource_file,
    list_script_resources,
    rename_resource_file,
    replace_resource_file,
    rewrite_resource_literal,
)
from ui.system_parts.menu_style import apply_unified_menu_style
from utils.app_paths import get_sounds_dir

_IMAGE_FILTER = "图片 (*.bmp *.png *.jpg *.jpeg *.webp)"
_MODEL_FILTER = "模型 (*.onnx)"
_AUDIO_FILTER = "音频 (*.wav *.mp3 *.wma *.m4a *.ogg *.flac)"
_REPLAY_FILTER = "回放 (*.replay.json)"
_IMPORT_FILTER = f"{_IMAGE_FILTER};;{_MODEL_FILTER};;{_AUDIO_FILTER};;{_REPLAY_FILTER};;所有文件 (*.*)"


class ScriptResourcePanel(QWidget):
    insert_requested = Signal(dict)
    locate_requested = Signal(dict)
    source_rewrite_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("scriptResourcePanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(168)
        self.setMaximumHeight(240)
        self._images_dir = ""
        self._sounds_dir = ""
        self._card_id: Optional[int] = None
        self._workflow_token = ""
        self._items: List[Dict[str, Any]] = []
        self._source = ""
        self._build_ui()

    def bind(
        self,
        images_dir: str = "",
        card_id: Optional[int] = None,
        workflow_token: str = "",
        sounds_dir: str = "",
    ) -> None:
        self._images_dir = str(images_dir or "")
        self._sounds_dir = str(sounds_dir or "").strip() or get_sounds_dir("LCA")
        self._card_id = card_id
        self._workflow_token = str(workflow_token or "")

    def set_source(self, source: str) -> None:
        self._source = str(source or "")
        self.reload()

    def reload(self) -> None:
        selected = str((self.current_item() or {}).get("path") or "")
        self._items = list_script_resources(
            self._source,
            self._images_dir,
            self._card_id,
            self._workflow_token,
            self._sounds_dir,
        )
        self._list.clear()
        current = None
        for item in self._items:
            row = QListWidgetItem(self._item_label(item))
            row.setData(Qt.ItemDataRole.UserRole, item)
            row.setToolTip(self._item_tip(item))
            icon = self._item_icon(item)
            if icon is not None:
                row.setIcon(icon)
            self._list.addItem(row)
            if item.get("path") == selected:
                current = row
        if current is not None:
            self._list.setCurrentItem(current)
        elif self._list.count():
            self._list.setCurrentRow(0)
        self._empty.setVisible(not self._items)
        self._list.setVisible(bool(self._items))
        self._sync_buttons()

    def current_item(self) -> Optional[Dict[str, Any]]:
        row = self._list.currentItem()
        payload = row.data(Qt.ItemDataRole.UserRole) if row is not None else None
        return payload if isinstance(payload, dict) else None

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)
        title = QLabel("本卡资源")
        title.setObjectName("scriptResourceTitle")
        layout.addWidget(title)
        hint = QLabel("截图、导入的图、模型和音频都在这里。双击插入到当前行。")
        hint.setObjectName("scriptResourceHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        empty = QLabel("这张卡还没有资源。用上面的「截图」或「导入」。")
        empty.setObjectName("scriptResourceEmpty")
        empty.setWordWrap(True)
        layout.addWidget(empty)
        self._empty = empty
        listing = QListWidget()
        listing.setObjectName("scriptResourceList")
        listing.setIconSize(QSize(48, 48))
        listing.setSpacing(2)
        listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        listing.itemSelectionChanged.connect(self._sync_buttons)
        listing.itemDoubleClicked.connect(self._on_double_clicked)
        listing.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        listing.customContextMenuRequested.connect(self._on_menu)
        layout.addWidget(listing, 1)
        self._list = listing
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._buttons = {}
        for name, label, handler in (
            ("import", "导入", self._on_import),
            ("insert", "插入", self._on_insert),
            ("replace", "替换", self._on_replace),
            ("rename", "重命名", self._on_rename),
            ("delete", "删除", self._on_delete),
            ("locate", "定位", self._on_locate),
        ):
            button = QPushButton(label)
            button.setObjectName("scriptCaptureButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(handler)
            row.addWidget(button)
            self._buttons[name] = button
        row.addStretch(1)
        layout.addLayout(row)

    def _item_label(self, item: Dict[str, Any]) -> str:
        kind = {"model": "模型", "audio": "音频", "replay": "回放"}.get(str(item.get("kind") or ""), "图片")
        name = str(item.get("name") or item.get("path") or "")
        if not item.get("exists"):
            state = "文件不在"
        elif item.get("unused") or not item.get("used"):
            state = "未使用"
        else:
            state = f"用了 {int(item.get('used') or 0)} 次"
        return f"{kind}  {name}\n{state}"

    def _item_tip(self, item: Dict[str, Any]) -> str:
        lines = [str(item.get("path") or ""), str(item.get("abs_path") or "")]
        if not item.get("exists"):
            lines.append("文件不在，插入后运行会找不到。")
        elif item.get("unused"):
            lines.append("这张卡截过/导入过，脚本里还没用。")
        return "\n".join(part for part in lines if part)

    def _item_icon(self, item: Dict[str, Any]) -> Optional[QIcon]:
        path = str(item.get("abs_path") or "")
        if item.get("kind") == "image" and path and os.path.isfile(path):
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                return QIcon(
                    pixmap.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                )
        return None

    def _sync_buttons(self) -> None:
        item = self.current_item()
        has = item is not None
        exists = bool(item and item.get("exists"))
        used = bool(item and item.get("used"))
        self._buttons["insert"].setEnabled(has)
        self._buttons["replace"].setEnabled(has)
        self._buttons["rename"].setEnabled(exists)
        self._buttons["delete"].setEnabled(exists or has)
        self._buttons["locate"].setEnabled(used)

    def _on_double_clicked(self, _item: QListWidgetItem) -> None:
        self._on_insert()

    def _on_menu(self, pos) -> None:
        item = self.current_item()
        if not item:
            return
        menu = apply_unified_menu_style(QMenu(self), frameless=True)
        menu.addAction("插入", self._on_insert)
        if item.get("used"):
            menu.addAction("定位", self._on_locate)
        if item.get("kind") == "image" and item.get("exists"):
            menu.addAction("预览", lambda: self._preview(item))
        menu.addAction("替换", self._on_replace)
        if item.get("exists"):
            menu.addAction("重命名", self._on_rename)
        menu.addAction("删除", self._on_delete)
        menu.exec(self._list.mapToGlobal(pos))

    def _on_import(self) -> None:
        path, selected = QFileDialog.getOpenFileName(
            self,
            "导入资源",
            self._images_dir or self._sounds_dir or "",
            _IMPORT_FILTER,
        )
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if selected.startswith("模型") or ext in MODEL_EXTS:
            kind = "model"
        elif selected.startswith("音频") or ext in AUDIO_EXTS:
            kind = "audio"
        else:
            kind = "image"
        try:
            imported = import_resource_file(
                path,
                self._images_dir,
                self._card_id,
                self._workflow_token,
                kind,
                self._sounds_dir,
            )
        except Exception as exc:
            QMessageBox.warning(self, "导入", f"导入失败：{exc}")
            return
        self.reload()
        self._select_path(str(imported.get("path") or ""))

    def _on_insert(self) -> None:
        item = self.current_item()
        if item:
            self.insert_requested.emit(item)

    def _on_locate(self) -> None:
        item = self.current_item()
        if item and item.get("spans"):
            self.locate_requested.emit(item)

    def _on_replace(self) -> None:
        item = self.current_item()
        if not item:
            return
        if item.get("kind") == "model":
            filt = f"{_MODEL_FILTER};;所有文件 (*.*)"
            start = self._images_dir or ""
        elif item.get("kind") == "audio":
            filt = f"{_AUDIO_FILTER};;所有文件 (*.*)"
            start = self._sounds_dir or ""
        elif item.get("kind") == "replay":
            filt = f"{_REPLAY_FILTER};;所有文件 (*.*)"
            start = self._images_dir or ""
        else:
            filt = f"{_IMAGE_FILTER};;所有文件 (*.*)"
            start = self._images_dir or ""
        path, _selected = QFileDialog.getOpenFileName(self, "替换资源", start, filt)
        if not path:
            return
        try:
            updated = replace_resource_file(item, path, self._images_dir, self._sounds_dir)
        except Exception as exc:
            QMessageBox.warning(self, "替换", f"替换失败：{exc}")
            return
        old_path = str(updated.get("old_path") or item.get("path") or "")
        new_path = str(updated.get("path") or "")
        if old_path and new_path and old_path != new_path and item.get("used"):
            self.source_rewrite_requested.emit(rewrite_resource_literal(self._source, old_path, new_path))
        else:
            self.reload()

    def _on_rename(self) -> None:
        item = self.current_item()
        if not item:
            return
        name, ok = QInputDialog.getText(self, "重命名", "新文件名：", text=str(item.get("name") or ""))
        if not ok:
            return
        try:
            source, _updated = rename_resource_file(item, name, self._source, self._images_dir, self._sounds_dir)
        except Exception as exc:
            QMessageBox.warning(self, "重命名", f"重命名失败：{exc}")
            return
        if source != self._source:
            self.source_rewrite_requested.emit(source)
        else:
            self.reload()

    def _on_delete(self) -> None:
        item = self.current_item()
        if not item:
            return
        used = int(item.get("used") or 0)
        name = str(item.get("name") or item.get("path") or "")
        if used:
            text = f"「{name}」脚本里还用了 {used} 次。只删文件，路径仍留在脚本里。"
        else:
            text = f"删除「{name}」？文件会从这张卡的资源里去掉。"
        choice = QMessageBox.question(
            self,
            "删除资源",
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_resource_file(item)
        except Exception as exc:
            QMessageBox.warning(self, "删除", f"删除失败：{exc}")
            return
        self.reload()

    def _preview(self, item: Dict[str, Any]) -> None:
        path = str(item.get("abs_path") or "")
        if not path or not os.path.isfile(path):
            QMessageBox.information(self, "预览", "文件不在。")
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.information(self, "预览", "打不开这张图。")
            return
        from PySide6.QtWidgets import QDialog

        dialog = QDialog(self)
        dialog.setWindowTitle(str(item.get("name") or "预览"))
        dialog.resize(min(720, max(320, pixmap.width() + 24)), min(560, max(240, pixmap.height() + 24)))
        label = QLabel(dialog)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setPixmap(
            pixmap.scaled(700, 520, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )
        box = QVBoxLayout(dialog)
        box.addWidget(label)
        dialog.exec()

    def _select_path(self, path: str) -> None:
        needle = str(path or "")
        for index in range(self._list.count()):
            row = self._list.item(index)
            payload = row.data(Qt.ItemDataRole.UserRole) if row is not None else None
            if isinstance(payload, dict) and payload.get("path") == needle:
                self._list.setCurrentRow(index)
                return
