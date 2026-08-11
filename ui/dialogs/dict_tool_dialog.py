# -*- coding: utf-8 -*-
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from themes import get_theme_manager


class DictToolDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        list_dict_names: Callable[[], List[str]],
        preview_payload_loader: Callable[[str], Dict[str, object]],
        open_tool_callback: Callable[[], None],
        import_dm_callback: Callable[[], None],
        import_bmp_callback: Callable[[], None],
        delete_dict_callback: Callable[[str], None],
        export_dict_callback: Callable[[str], None],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("字库工具")
        self.setMinimumSize(860, 520)
        self.resize(980, 620)

        self._list_dict_names = list_dict_names
        self._preview_payload_loader = preview_payload_loader
        self._open_tool_callback = open_tool_callback
        self._import_dm_callback = import_dm_callback
        self._import_bmp_callback = import_bmp_callback
        self._delete_dict_callback = delete_dict_callback
        self._export_dict_callback = export_dict_callback

        self._count_label = QLabel()
        self._dict_list = QListWidget()
        self._preview_count_label = QLabel()
        self._preview_hint_label = QLabel()
        self._preview_list = QListWidget()
        self._refresh_button = QPushButton("刷新列表")
        self._delete_button = QPushButton("删除选中")
        self._export_button = QPushButton("导出选中")
        self._close_button = QPushButton("关闭")

        self._build_ui()
        self._apply_styles()
        self._refresh_dict_list()

    def _build_ui(self) -> None:
        self._dict_list.setObjectName("dict_tool_list")
        self._dict_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._dict_list.itemSelectionChanged.connect(self._handle_dict_selection_changed)
        self._dict_list.itemDoubleClicked.connect(lambda _item: self._handle_export_selected())

        self._preview_list.setObjectName("dict_tool_preview_list")
        self._preview_list.setViewMode(QListView.ViewMode.IconMode)
        self._preview_list.setResizeMode(QListView.ResizeMode.Adjust)
        self._preview_list.setMovement(QListView.Movement.Static)
        self._preview_list.setWrapping(True)
        self._preview_list.setSpacing(10)
        self._preview_list.setIconSize(QSize(56, 56))
        self._preview_list.setGridSize(QSize(92, 100))
        self._preview_list.setWordWrap(True)
        self._preview_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._preview_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)

        self._preview_hint_label.setObjectName("dict_tool_desc")
        self._preview_hint_label.setWordWrap(True)

        desc_label = QLabel("导入字库后，可在这里直接查看已生成的字符预览并管理已有字库。")
        desc_label.setObjectName("dict_tool_desc")
        desc_label.setWordWrap(True)

        open_tool_button = QPushButton("打开大漠综合工具")
        open_tool_button.setProperty("class", "primary")
        open_tool_button.clicked.connect(self._handle_open_tool)

        import_dm_button = QPushButton("导入大漠字库文件")
        import_dm_button.setProperty("class", "primary")
        import_dm_button.clicked.connect(self._handle_import_dm)

        import_bmp_button = QPushButton("从图片文件夹导入")
        import_bmp_button.clicked.connect(self._handle_import_bmp)

        top_actions_layout = QHBoxLayout()
        top_actions_layout.setContentsMargins(0, 0, 0, 0)
        top_actions_layout.setSpacing(8)
        top_actions_layout.addWidget(open_tool_button)
        top_actions_layout.addWidget(import_dm_button)
        top_actions_layout.addWidget(import_bmp_button)
        top_actions_layout.addStretch()

        list_header_layout = QHBoxLayout()
        list_header_layout.setContentsMargins(0, 0, 0, 0)
        list_header_layout.setSpacing(8)
        list_title = QLabel("已有字库")
        list_title.setObjectName("dict_tool_section_title")
        list_header_layout.addWidget(list_title)
        list_header_layout.addStretch()
        list_header_layout.addWidget(self._count_label)

        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        left_layout.addLayout(list_header_layout)
        left_layout.addWidget(self._dict_list, 1)

        left_frame = QFrame()
        left_frame.setObjectName("dict_tool_left_frame")
        left_frame.setLayout(left_layout)
        left_frame.setFixedWidth(220)
        left_frame.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        preview_header_layout = QHBoxLayout()
        preview_header_layout.setContentsMargins(0, 0, 0, 0)
        preview_header_layout.setSpacing(8)
        preview_title = QLabel("字符预览")
        preview_title.setObjectName("dict_tool_section_title")
        preview_header_layout.addWidget(preview_title)
        preview_header_layout.addStretch()
        preview_header_layout.addWidget(self._preview_count_label)

        preview_layout = QVBoxLayout()
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)
        preview_layout.addLayout(preview_header_layout)
        preview_layout.addWidget(self._preview_hint_label)
        preview_layout.addWidget(self._preview_list, 1)

        preview_frame = QFrame()
        preview_frame.setObjectName("dict_tool_left_frame")
        preview_frame.setLayout(preview_layout)

        manage_title = QLabel("管理操作")
        manage_title.setObjectName("dict_tool_section_title")

        manage_desc = QLabel("删除和导出都针对左侧当前选中的字库。")
        manage_desc.setObjectName("dict_tool_desc")
        manage_desc.setWordWrap(True)

        self._refresh_button.clicked.connect(self._refresh_dict_list)
        self._delete_button.clicked.connect(self._handle_delete_selected)
        self._delete_button.setProperty("class", "danger")
        self._export_button.clicked.connect(self._handle_export_selected)
        self._close_button.clicked.connect(self.accept)

        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        right_layout.addWidget(manage_title)
        right_layout.addWidget(manage_desc)
        right_layout.addSpacing(4)
        right_layout.addWidget(self._refresh_button)
        right_layout.addWidget(self._delete_button)
        right_layout.addWidget(self._export_button)
        right_layout.addStretch()
        right_layout.addWidget(self._close_button)

        right_frame = QFrame()
        right_frame.setObjectName("dict_tool_right_frame")
        right_frame.setLayout(right_layout)
        right_frame.setFixedWidth(210)
        right_frame.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        content_layout.addWidget(left_frame, 0)
        content_layout.addWidget(preview_frame, 1)
        content_layout.addWidget(right_frame, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(desc_label)
        layout.addLayout(top_actions_layout)
        layout.addLayout(content_layout, 1)

    def _apply_styles(self) -> None:
        theme_manager = get_theme_manager()
        background = theme_manager.get_color("background")
        card = theme_manager.get_color("card")
        surface = theme_manager.get_color("surface")
        border = theme_manager.get_color("border")
        border_light = theme_manager.get_color("border_light")
        text = theme_manager.get_color("text")
        text_secondary = theme_manager.get_color("text_secondary")
        hover = theme_manager.get_color("hover")

        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {background};
                color: {text};
            }}
            QLabel#dict_tool_section_title {{
                font-size: 13px;
                font-weight: 600;
            }}
            QLabel#dict_tool_desc {{
                color: {text_secondary};
            }}
            QFrame#dict_tool_left_frame, QFrame#dict_tool_right_frame {{
                background-color: {card};
                border: 1px solid {border};
                border-radius: 12px;
            }}
            QListWidget#dict_tool_list, QListWidget#dict_tool_preview_list {{
                background-color: {surface};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 6px;
            }}
            QListWidget#dict_tool_list::item {{
                border-radius: 6px;
                padding: 8px 10px;
                margin: 2px 0;
            }}
            QListWidget#dict_tool_list::item:selected {{
                background-color: {hover};
                color: {text};
            }}
            QListWidget#dict_tool_list::item:hover {{
                background-color: {hover};
            }}
            QListWidget#dict_tool_preview_list::item {{
                border-radius: 8px;
                padding: 6px;
                margin: 2px;
            }}
            QPushButton {{
                min-height: 34px;
                border-radius: 6px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                border-color: {border_light};
            }}
            """
        )

    def _current_dict_name(self) -> str:
        current_item = self._dict_list.currentItem()
        if current_item is None:
            return ""
        return str(current_item.text() or "").strip()

    def _update_action_state(self) -> None:
        has_selection = bool(self._current_dict_name())
        self._delete_button.setEnabled(has_selection)
        self._export_button.setEnabled(has_selection)

    def _handle_dict_selection_changed(self) -> None:
        self._update_action_state()
        self._refresh_preview()

    def _refresh_dict_list(self) -> None:
        current_name = self._current_dict_name()
        dict_names = list(self._list_dict_names() or [])

        self._dict_list.clear()
        for dict_name in dict_names:
            self._dict_list.addItem(QListWidgetItem(str(dict_name)))

        self._count_label.setText(f"共 {len(dict_names)} 个")

        if dict_names:
            target_name = current_name if current_name in dict_names else dict_names[0]
            for index in range(self._dict_list.count()):
                item = self._dict_list.item(index)
                if item and item.text() == target_name:
                    self._dict_list.setCurrentItem(item)
                    break
        else:
            self._handle_dict_selection_changed()

    @staticmethod
    def _build_preview_icon(image_path: str) -> QIcon:
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            return QIcon()
        scaled = pixmap.scaled(
            56,
            56,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        return QIcon(scaled)

    def _refresh_preview(self) -> None:
        dict_name = self._current_dict_name()
        self._preview_list.clear()

        if not dict_name:
            self._preview_count_label.setText("未选择")
            self._preview_hint_label.setText("先在左侧选择字库，这里会显示已生成的字符预览。")
            return

        payload = self._preview_payload_loader(dict_name) or {}
        preview_items = list(payload.get("items") or [])
        preview_count = int(payload.get("preview_count", len(preview_items)) or 0)
        entry_count = int(payload.get("entry_count", preview_count) or 0)
        preview_dir = str(payload.get("preview_dir", "") or "").strip()

        self._preview_count_label.setText(f"预览 {preview_count} / {entry_count}")

        if not preview_items:
            if preview_dir:
                self._preview_hint_label.setText(
                    f"字库 '{dict_name}' 暂无可预览的字符图片。\n缓存目录: {preview_dir}"
                )
            else:
                self._preview_hint_label.setText(f"字库 '{dict_name}' 暂无可预览的字符图片。")
            return

        self._preview_hint_label.setText(f"当前字库: {dict_name}\n缓存目录: {preview_dir}")

        for item_data in preview_items:
            char_text = str(item_data.get("text", "") or "").strip()
            image_path = str(item_data.get("path", "") or "").strip()
            list_item = QListWidgetItem(self._build_preview_icon(image_path), char_text)
            list_item.setToolTip(image_path)
            list_item.setTextAlignment(
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            )
            list_item.setSizeHint(QSize(84, 92))
            self._preview_list.addItem(list_item)

    def _handle_open_tool(self) -> None:
        self._open_tool_callback()

    def _handle_import_dm(self) -> None:
        self._import_dm_callback()
        self._refresh_dict_list()

    def _handle_import_bmp(self) -> None:
        self._import_bmp_callback()
        self._refresh_dict_list()

    def _require_selected_dict(self, action_name: str) -> Optional[str]:
        dict_name = self._current_dict_name()
        if dict_name:
            return dict_name
        QMessageBox.information(self, action_name, "请先在左侧选择一个字库")
        return None

    def _handle_delete_selected(self) -> None:
        dict_name = self._require_selected_dict("删除字库")
        if not dict_name:
            return
        self._delete_dict_callback(dict_name)
        self._refresh_dict_list()

    def _handle_export_selected(self) -> None:
        dict_name = self._require_selected_dict("导出字库")
        if not dict_name:
            return
        self._export_dict_callback(dict_name)
