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
    COMPONENT_EXTS,
    IMAGE_EXTS,
    MODEL_EXTS,
    delete_resource_file,
    import_resource_file,
    is_managed_resource_file,
    list_script_resources,
    rename_resource_file,
    replace_resource_file,
    rewrite_resource_literal,
)
from ui.system_parts.menu_style import apply_unified_menu_style

_IMAGE_FILTER = "图片 (*.bmp *.png *.jpg *.jpeg *.webp)"
_MODEL_FILTER = "模型 (*.onnx)"
_AUDIO_FILTER = "音频 (*.wav *.mp3 *.wma *.m4a *.ogg *.flac)"
_REPLAY_FILTER = "回放 (*.replay.json)"
_COMPONENT_FILTER = "外部组件 (*.dll *.exe *.com *.py)"
_PROGRAM_FILTER = "程序 (*.exe *.com)"
_IMPORT_FILTER = f"{_IMAGE_FILTER};;{_MODEL_FILTER};;{_AUDIO_FILTER};;{_REPLAY_FILTER};;{_COMPONENT_FILTER};;所有文件 (*.*)"


def _detect_import_kind(path: str, selected_filter: str) -> str:
    """按所选过滤器和扩展名判定资源类型；无法识别时抛 ValueError。"""
    name = str(path or "").lower()
    selected = str(selected_filter or "")
    # 回放文件名是 *.replay.json，扩展名是 .json，必须先于图片/其它判定。
    if selected.startswith("回放") or name.endswith(".replay.json"):
        return "replay"
    ext = os.path.splitext(name)[1]
    if selected.startswith("模型") or ext in MODEL_EXTS:
        return "model"
    if selected.startswith("音频") or ext in AUDIO_EXTS:
        return "audio"
    if selected.startswith("外部组件") or ext in COMPONENT_EXTS:
        return "component"
    if selected.startswith("图片") or ext in IMAGE_EXTS:
        return "image"
    raise ValueError("不支持的资源类型")


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
        self._dicts_dir = ""
        self._yolo_dir = ""
        self._replays_dir = ""
        self._plugins_dir = ""
        self._card_id: Optional[int] = None
        self._workflow_token = ""
        self._items: List[Dict[str, Any]] = []
        self._source = ""
        self._binding_error = ""
        self._build_ui()

    def bind(
        self,
        images_dir: str = "",
        card_id: Optional[int] = None,
        workflow_token: str = "",
        sounds_dir: str = "",
        dicts_dir: str = "",
        yolo_dir: str = "",
        replays_dir: str = "",
        plugins_dir: str = "",
    ) -> None:
        self._images_dir = str(images_dir or "").strip()
        self._sounds_dir = str(sounds_dir or "").strip()
        self._dicts_dir = str(dicts_dir or "").strip()
        self._yolo_dir = str(yolo_dir or "").strip()
        self._replays_dir = str(replays_dir or "").strip()
        self._plugins_dir = str(plugins_dir or "").strip()
        self._card_id = card_id
        self._workflow_token = str(workflow_token or "")
        self._sync_buttons()

    def set_source(self, source: str) -> None:
        self._source = str(source or "")
        self.reload()

    def set_binding_error(self, message: str) -> None:
        self._binding_error = str(message)
        self._status.setText(f"资源绑定失败：{message}" if message else "")

    def reload(self) -> None:
        if not self._images_dir:
            self._items = []
            self._list.clear()
            self._list.hide()
            self._empty.setText("资源目录未绑定，绑定工程后可采集或导入资源。")
            self._empty.show()
            self._sync_buttons()
            return
        self._empty.setText("这张卡还没有资源。用上面的「截图」或「导入」。")
        selected = str((self.current_item() or {}).get("path") or "")
        self._items = list_script_resources(
            self._source,
            self._images_dir,
            self._card_id,
            self._workflow_token,
            self._sounds_dir,
            dicts_dir=self._dicts_dir,
            yolo_dir=self._yolo_dir,
            replays_dir=self._replays_dir,
            plugins_dir=self._plugins_dir,
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

    def _is_external_program(self, item: Dict[str, Any]) -> bool:
        return bool(item.get("kind") == "component" and os.path.splitext(str(item.get("path") or ""))[1].lower() in {".exe", ".com"})

    def _is_managed_item(self, item: Dict[str, Any]) -> bool:
        return is_managed_resource_file(
            item,
            images_dir=self._images_dir,
            sounds_dir=self._sounds_dir,
            dicts_dir=self._dicts_dir,
            yolo_dir=self._yolo_dir,
            replays_dir=self._replays_dir,
            plugins_dir=self._plugins_dir,
        )

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)
        title = QLabel("本卡资源")
        title.setObjectName("scriptResourceTitle")
        layout.addWidget(title)
        hint = QLabel("截图、导入的资源和程序路径都在这里。双击插入到当前行。")
        hint.setObjectName("scriptResourceHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        status = QLabel("")
        status.setObjectName("scriptResourceStatus")
        status.setWordWrap(True)
        layout.addWidget(status)
        self._status = status
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
            ("program", "程序路径", self._on_import_program),
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
        kind = {"model": "模型", "audio": "音频", "replay": "回放", "component": "组件"}.get(str(item.get("kind") or ""), "图片")
        if self._is_external_program(item):
            kind = "程序"
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
        if self._is_external_program(item):
            lines.append("外部程序只通过路径启动；资源栏不会修改或删除原文件。")
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
        self._buttons["import"].setEnabled(bool(self._images_dir))
        self._buttons["program"].setEnabled(True)
        item = self.current_item()
        has = item is not None
        exists = bool(item and item.get("exists"))
        used = bool(item and item.get("used"))
        managed = bool(item and self._is_managed_item(item))
        self._buttons["insert"].setEnabled(has)
        # 外部程序替换只更新脚本引用，不会覆盖原文件。
        self._buttons["replace"].setEnabled(has)
        self._buttons["rename"].setEnabled(exists and managed)
        self._buttons["delete"].setEnabled((exists or has) and managed)
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
        if item.get("exists") and self._is_managed_item(item):
            menu.addAction("重命名", self._on_rename)
        if self._is_managed_item(item):
            menu.addAction("删除", self._on_delete)
        menu.exec(self._list.mapToGlobal(pos))

    def _on_import(self) -> None:
        path, selected = QFileDialog.getOpenFileName(
            self,
            "导入资源",
            self._images_dir or self._sounds_dir or self._yolo_dir or self._plugins_dir or "",
            _IMPORT_FILTER,
        )
        if not path:
            return
        try:
            kind = _detect_import_kind(path, selected)
            is_external_program = kind == "component" and os.path.splitext(path)[1].lower() in {".exe", ".com"}
            directory = {"image": self._images_dir, "model": self._yolo_dir,
                         "audio": self._sounds_dir, "replay": self._replays_dir,
                         "component": self._plugins_dir}[kind]
            if not directory and not is_external_program:
                self._status.setText("导入失败：该类资源目录未绑定")
                return
        except ValueError as exc:
            self._status.setText(f"导入失败：{exc}")
            QMessageBox.warning(self, "导入", f"导入失败：{exc}")
            return
        try:
            imported = import_resource_file(
                path,
                self._images_dir,
                self._card_id,
                self._workflow_token,
                kind,
                self._sounds_dir,
                dicts_dir=self._dicts_dir,
                yolo_dir=self._yolo_dir,
                replays_dir=self._replays_dir,
                plugins_dir=self._plugins_dir,
            )
        except Exception as exc:
            self._status.setText(f"导入失败：{exc}")
            QMessageBox.warning(self, "导入", f"导入失败：{exc}")
            return
        self.reload()
        imported_path = str(imported.get("path") or "")
        if not self._select_path(imported_path):
            row = QListWidgetItem(self._item_label(imported))
            row.setData(Qt.ItemDataRole.UserRole, imported)
            row.setToolTip(self._item_tip(imported))
            icon = self._item_icon(imported)
            if icon is not None:
                row.setIcon(icon)
            self._list.addItem(row)
            self._items.append(imported)
            self._list.setCurrentItem(row)
            self._empty.setVisible(False)
            self._list.setVisible(True)
            self._sync_buttons()
        self._status.setText(f"已导入：{imported.get('name') or imported.get('path') or ''}。双击资源或点击“插入”写入当前行。")

    def _on_import_program(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "选择启动程序",
            "",
            _PROGRAM_FILTER,
        )
        if not path:
            return
        absolute = os.path.abspath(path)
        if os.path.splitext(absolute)[1].lower() not in {".exe", ".com"} or not os.path.isfile(absolute):
            self._status.setText("程序路径无效：请选择存在的 .exe 或 .com 文件。")
            return
        item = {
            "kind": "component",
            "path": absolute.replace("\\", "/"),
            "abs_path": absolute,
            "name": os.path.basename(absolute),
            "exists": True,
            "used": 0,
            "unused": True,
            "spans": [],
            "external_path": True,
        }
        row = QListWidgetItem(self._item_label(item))
        row.setData(Qt.ItemDataRole.UserRole, item)
        row.setToolTip(self._item_tip(item))
        self._list.addItem(row)
        self._items.append(item)
        self._list.setCurrentItem(row)
        self._empty.hide()
        self._list.show()
        self._sync_buttons()
        self.insert_requested.emit(item)
        self._status.setText(f"已插入程序路径：{absolute}")

    def _on_insert(self) -> None:
        item = self.current_item()
        if item:
            self.insert_requested.emit(item)
            self._status.setText(f"已插入：{item.get('name') or item.get('path') or ''}")

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
            start = self._yolo_dir
        elif item.get("kind") == "audio":
            filt = f"{_AUDIO_FILTER};;所有文件 (*.*)"
            start = self._sounds_dir or ""
        elif item.get("kind") == "replay":
            filt = f"{_REPLAY_FILTER};;所有文件 (*.*)"
            start = self._replays_dir
        elif item.get("kind") == "component":
            filt = f"{_COMPONENT_FILTER};;所有文件 (*.*)"
            current_path = str(item.get("path") or "")
            start = os.path.dirname(current_path) if current_path and os.path.isabs(current_path) else self._plugins_dir
        else:
            filt = f"{_IMAGE_FILTER};;所有文件 (*.*)"
            start = self._images_dir or ""
        path, _selected = QFileDialog.getOpenFileName(self, "替换资源", start, filt)
        if not path:
            return
        try:
            updated = replace_resource_file(
                item,
                path,
                self._images_dir,
                self._sounds_dir,
                dicts_dir=self._dicts_dir,
                yolo_dir=self._yolo_dir,
                replays_dir=self._replays_dir,
                plugins_dir=self._plugins_dir,
            )
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
        if not item or not self._is_managed_item(item):
            return
        name, ok = QInputDialog.getText(self, "重命名", "新文件名：", text=str(item.get("name") or ""))
        if not ok:
            return
        try:
            source, _updated = rename_resource_file(
                item,
                name,
                self._source,
                self._images_dir,
                self._sounds_dir,
                dicts_dir=self._dicts_dir,
                yolo_dir=self._yolo_dir,
                replays_dir=self._replays_dir,
                plugins_dir=self._plugins_dir,
            )
        except Exception as exc:
            QMessageBox.warning(self, "重命名", f"重命名失败：{exc}")
            return
        if source != self._source:
            self.source_rewrite_requested.emit(source)
        else:
            self.reload()

    def _on_delete(self) -> None:
        item = self.current_item()
        if not item or not self._is_managed_item(item):
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
            delete_resource_file(
                item,
                images_dir=self._images_dir,
                sounds_dir=self._sounds_dir,
                dicts_dir=self._dicts_dir,
                yolo_dir=self._yolo_dir,
                replays_dir=self._replays_dir,
                plugins_dir=self._plugins_dir,
            )
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
        dialog.deleteLater()

    def _select_path(self, path: str) -> bool:
        needle = str(path or "")
        for index in range(self._list.count()):
            row = self._list.item(index)
            payload = row.data(Qt.ItemDataRole.UserRole) if row is not None else None
            if isinstance(payload, dict) and payload.get("path") == needle:
                self._list.setCurrentRow(index)
                return True
        return False
