# -*- coding: utf-8 -*-
import re
from typing import List, Optional

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QDialogButtonBox,
    QMessageBox,
    QLabel,
    QFrame,
    QWidget,
    QScrollArea,
    QSizePolicy,
)
from PySide6.QtCore import Qt

from themes import get_theme_manager
from ..widgets.custom_widgets import CustomDropdown


class SuggestionComboBox(CustomDropdown):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaxVisibleItems(8)
        self.setMinimumWidth(170)


class VariableSourcesDialog(QDialog):
    def __init__(
        self,
        sources: Optional[List[str]] = None,
        parent=None,
        card_id: Optional[int] = None,
        workflow_id: Optional[object] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("目标来源")
        self.setMinimumSize(560, 320)
        self.resize(660, 360)

        self._card_id = self._normalize_card_id(card_id)
        self._workflow_id = self._normalize_workflow_id(workflow_id)
        self._count_label = QLabel()
        self._add_button = QPushButton("添加来源")
        self._rows_frame = QFrame()
        self._rows_area = QScrollArea()
        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows: List[dict] = []
        self._variable_suggestions = self._get_variable_suggestions()

        self._build_ui()
        self._apply_styles()
        self._load_initial_rows(sources or [])

    def _build_ui(self) -> None:
        title = QLabel("")
        title.setObjectName("sources_title")
        title.setVisible(False)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(title)
        header_layout.addStretch()

        self._rows_frame.setObjectName("sources_rows_frame")
        self._rows_layout.setContentsMargins(6, 6, 6, 6)
        self._rows_layout.setSpacing(6)
        self._rows_area.setWidget(self._rows_container)
        self._rows_area.setWidgetResizable(True)
        self._rows_area.setFrameShape(QFrame.Shape.NoFrame)
        self._rows_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rows_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._add_button.setProperty("primary", True)
        self._add_button.clicked.connect(self._on_add_clicked)

        actions_layout = QHBoxLayout()
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        actions_layout.addWidget(self._count_label)
        actions_layout.addStretch()
        actions_layout.addWidget(self._add_button)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_button:
            ok_button.setText("确定")
            ok_button.setProperty("primary", True)
        if cancel_button:
            cancel_button.setText("取消")

        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)

        rows_layout = QVBoxLayout(self._rows_frame)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.addWidget(self._rows_area)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(header_layout)
        layout.addLayout(actions_layout)
        layout.addWidget(self._rows_frame)
        layout.addWidget(button_box)

        self._refresh_count()

    def _apply_styles(self) -> None:
        theme_manager = get_theme_manager()
        background = theme_manager.get_color("background")
        surface = theme_manager.get_color("surface")
        card = theme_manager.get_color("card")
        border = theme_manager.get_color("border")
        border_light = theme_manager.get_color("border_light")
        text = theme_manager.get_color("text")
        text_secondary = theme_manager.get_color("text_secondary")

        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {background};
                color: {text};
            }}

            #sources_title {{
                font-size: 14px;
                font-weight: 600;
            }}

            #sources_count {{
                color: {text_secondary};
            }}

            #sources_rows_frame {{
                background-color: {card};
                border: 1px solid {border};
                border-radius: 12px;
            }}

            #sources_row_remove {{
                background-color: transparent;
                border: 1px solid {border};
                border-radius: 6px;
                padding: 4px 10px;
                min-height: 26px;
            }}

            #sources_row_remove:hover {{
                background-color: {surface};
                border-color: {border_light};
            }}

            QLineEdit#sources_row_input {{
                background-color: {surface};
                color: {text};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 6px 10px;
                min-height: 24px;
            }}

            QLineEdit#sources_row_input:hover {{
                border-color: {border_light};
            }}

            QLineEdit#sources_row_input:focus {{
                border-color: {border_light};
            }}

            QDialogButtonBox QPushButton {{
                min-width: 96px;
            }}
            """
        )

    def _load_initial_rows(self, sources: List[str]) -> None:
        if sources:
            for source in sources:
                if source:
                    self._add_row(str(source))
        else:
            self._add_row()

        self._refresh_count()

    def _on_add_clicked(self) -> None:
        self._add_row()
        self._refresh_count()

    def _add_row(self, value: Optional[str] = None) -> None:
        row_frame = QFrame()
        row_layout = QHBoxLayout(row_frame)
        row_layout.setContentsMargins(8, 6, 8, 6)
        row_layout.setSpacing(8)

        source_edit = QLineEdit()
        source_edit.setObjectName("sources_row_input")
        source_edit.setPlaceholderText("变量名")
        source_edit.setMinimumWidth(150)
        source_edit.setMaximumWidth(260)
        source_edit.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        if value:
            source_edit.setText(value)

        suggestion_combo = SuggestionComboBox()
        suggestion_combo.setToolTip("变量建议")
        suggestion_combo.setMinimumWidth(200)
        suggestion_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if self._variable_suggestions:
            suggestion_combo.addItems(self._variable_suggestions)
            if value and str(value).strip() in self._variable_suggestions:
                suggestion_combo.setCurrentText(str(value).strip())
        else:
            suggestion_combo.addItem("无可用建议")

        def _apply_selected_suggestion(text: str) -> None:
            selected = str(text or "").strip()
            if not selected or selected == "无可用建议":
                return
            source_edit.setText(selected)
            source_edit.setFocus()

        suggestion_combo.currentTextChanged.connect(_apply_selected_suggestion)

        remove_button = QPushButton("移除")
        remove_button.setObjectName("sources_row_remove")
        remove_button.setMinimumWidth(64)
        remove_button.clicked.connect(lambda: self._remove_row(row_frame))

        row_layout.addWidget(source_edit, 0)
        row_layout.addWidget(suggestion_combo, 1)
        row_layout.addWidget(remove_button)

        self._rows_layout.addWidget(row_frame)
        self._rows.append({
            "frame": row_frame,
            "source_edit": source_edit,
            "suggestion_combo": suggestion_combo,
        })

    def _remove_row(self, row_frame: QFrame) -> None:
        for index, row in enumerate(self._rows):
            if row.get("frame") is row_frame:
                self._rows_layout.removeWidget(row_frame)
                row_frame.deleteLater()
                self._rows.pop(index)
                break
        if not self._rows:
            self._add_row()
        self._refresh_count()

    def _refresh_count(self) -> None:
        self._count_label.setObjectName("sources_count")
        self._count_label.setText(f"来源行: {len(self._rows)}")

    def get_sources(self) -> List[str]:
        sources: List[str] = []
        seen = set()
        for row in self._rows:
            source_edit = row["source_edit"]
            value = source_edit.text().strip()
            for name in self._split_source_tokens(value):
                if name in seen:
                    continue
                seen.add(name)
                sources.append(name)
        return sources

    @staticmethod
    def _split_source_tokens(value: str) -> List[str]:
        text = str(value or "").strip()
        if not text:
            return []
        chunks = re.split(r"[,\n;|]+", text)
        return [str(chunk).strip() for chunk in chunks if str(chunk).strip()]

    def _validate_sources(self, sources: List[str]) -> Optional[str]:
        if not sources:
            return "请至少添加 1 个目标来源"
        return None

    def _on_accept(self) -> None:
        sources = self.get_sources()
        error = self._validate_sources(sources)
        if error:
            QMessageBox.warning(self, "目标来源错误", error)
            return
        self.accept()

    def _get_variable_suggestions(self) -> List[str]:
        suggestions = set()
        try:
            from task_workflow.workflow_context import get_workflow_context
            from task_workflow.workflow_vars import get_context_for_task

            if self._workflow_id is None:
                context = get_workflow_context()
            else:
                context = get_context_for_task(self._workflow_id)
            if context and hasattr(context, "global_vars"):
                if hasattr(context, "snapshot_variable_state"):
                    state = context.snapshot_variable_state()
                    global_vars = dict((state or {}).get("global_vars", {}) or {})
                    source_map = dict((state or {}).get("var_sources", {}) or {})
                else:
                    global_vars = getattr(context, "global_vars", {}) or {}
                    source_map = getattr(context, "var_sources", {}) or {}
                if self._workflow_id == "global":
                    for key in global_vars.keys():
                        if self._is_system_var(key):
                            continue
                        suggestions.add(str(key))
                    return sorted(suggestions, key=self._sort_key)
                for key in global_vars.keys():
                    if self._is_system_var(key):
                        continue
                    source_id = source_map.get(key)
                    if self._card_id is None:
                        if source_id is None:
                            continue
                    else:
                        if source_id != self._card_id:
                            continue
                    suggestions.add(str(key))
        except Exception:
            pass
        return sorted(suggestions, key=self._sort_key)

    @staticmethod
    def _normalize_workflow_id(value: Optional[object]) -> Optional[object]:
        if value in (None, "", "当前工作流"):
            return None
        if value in ("全局变量", "global"):
            return "global"
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_card_id(value: Optional[int]) -> Optional[int]:
        if value in (None, "", "全部"):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_system_var(name: str) -> bool:
        return str(name).startswith((
            "latest_ocr_",
            "latest_yolo_",
        ))

    @staticmethod
    def _sort_key(name: str) -> tuple:
        text = str(name)
        match = re.match(r'^卡片(\d+)结果(?:[\\._](.*))?$', text)
        if match:
            return (0, int(match.group(1)), match.group(2) or "")
        match = re.match(r'^card_(\d+)_result(?:[\\._](.*))?$', text, flags=re.IGNORECASE)
        if match:
            return (0, int(match.group(1)), match.group(2) or "")
        return (1, text)
