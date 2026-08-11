import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from ui.system_parts.menu_style import apply_unified_menu_style

logger = logging.getLogger(__name__)


class ControlCenterWindowTableMixin:
    def _get_selected_rows(self) -> List[int]:
        if not hasattr(self, "window_table") or self.window_table is None:
            return []
        selection_model = self.window_table.selectionModel()
        if selection_model is None:
            return []
        return sorted({index.row() for index in selection_model.selectedRows()})

    def _get_selected_window_ids(self) -> List[str]:
        window_ids: List[str] = []
        for row in self._get_selected_rows():
            window_id = self._resolve_window_id_by_row(row)
            if window_id:
                window_ids.append(window_id)
        return window_ids

    def _get_all_rows(self) -> List[int]:
        return list(range(len(self.sorted_windows)))

    def _resolve_window_id_by_row(self, row: int) -> Optional[str]:
        try:
            row_index = int(row)
        except Exception:
            return None
        if row_index < 0 or row_index >= len(self.sorted_windows):
            return None
        window_info = self.sorted_windows[row_index]
        return str(window_info.get("hwnd", row_index))

    def _get_row_window_info(self, row: int) -> Dict[str, Any]:
        if row < 0 or row >= len(self.sorted_windows):
            return {}
        return self.sorted_windows[row]

    def _get_window_status_text(self, row: int) -> str:
        item = self.window_table.item(row, 3)
        return item.text().strip() if item else ""

    def _get_window_step_text(self, row: int) -> str:
        item = self.window_table.item(row, 4)
        return item.text().strip() if item else ""

    def _apply_status_style(self, item: Optional[QTableWidgetItem], status_text: str):
        if item is None:
            return
        status_colors = {
            "未分配": QColor("#999999"),
            "就绪": QColor("#4f86f7"),
            "等待开始": QColor("#4f86f7"),
            "正在启动": QColor("#4f86f7"),
            "正在运行": QColor("#1a7f37"),
            "暂停中": QColor("#b26a00"),
            "已暂停": QColor("#b26a00"),
            "正在停止": QColor("#b26a00"),
            "已中断": QColor("#666666"),
            "已完成": QColor("#1a7f37"),
            "完成": QColor("#1a7f37"),
            "失败": QColor("#c62828"),
            "执行失败": QColor("#c62828"),
        }
        item.setForeground(status_colors.get(status_text, QColor("#333333")))

    def _set_status_cell(self, row: int, status_text: str):
        item = self.window_table.item(row, 3)
        if item is None:
            item = QTableWidgetItem()
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.window_table.setItem(row, 3, item)
        item.setText(status_text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._apply_status_style(item, status_text)

    def _set_step_cell(self, row: int, step_text: str):
        item = self.window_table.item(row, 4)
        if item is None:
            item = QTableWidgetItem()
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.window_table.setItem(row, 4, item)
        item.setText(step_text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

    def _update_single_window_table_status(self, window_id, status_text: str, step_text: Optional[str] = None):
        self._update_window_table_status([window_id], status_text, step_text)

    def _update_window_table_status(self, window_ids, status_text: str, step_text: Optional[str] = None):
        """批量更新表格状态和步骤文本。"""
        if not window_ids:
            return
        for window_id in window_ids:
            row = self.find_window_row(str(window_id))
            if row < 0:
                continue
            self._set_status_cell(row, status_text)
            if step_text is not None:
                self._set_step_cell(row, step_text)
        self._refresh_overview_metrics()

    def _ensure_window_workflow_list(self, window_id: str) -> List[Dict[str, Any]]:
        workflows = self.window_workflows.get(window_id)
        if workflows is None:
            workflows = []
            self.window_workflows[window_id] = workflows
        elif isinstance(workflows, dict):
            workflows = [workflows]
            self.window_workflows[window_id] = workflows
        return workflows

    def _get_window_workflows(self, window_id: str) -> List[Dict[str, Any]]:
        if not window_id:
            return []
        return list(self._ensure_window_workflow_list(window_id))

    def _format_workflow_summary(self, workflows: List[Dict[str, Any]]) -> str:
        if not workflows:
            return "未分配"
        first_name = str(workflows[0].get("name") or "工作流").strip() or "工作流"
        if len(workflows) == 1:
            return first_name
        return f"{first_name} +{len(workflows) - 1}"

    def _build_workflow_tooltip(self, workflows: List[Dict[str, Any]]) -> str:
        if not workflows:
            return "当前未分配工作流"
        lines = []
        for index, workflow_info in enumerate(workflows, start=1):
            name = str(workflow_info.get("name") or f"工作流{index}").strip() or f"工作流{index}"
            file_path = str(workflow_info.get("file_path") or "").strip()
            if file_path:
                lines.append(f"{index}. {name}\n{file_path}")
            else:
                lines.append(f"{index}. {name}")
        return "\n\n".join(lines)

    def _refresh_window_workflow_cell(self, row: int, window_id: Optional[str] = None):
        if row < 0 or row >= self.window_table.rowCount():
            return
        resolved_window_id = window_id or self._resolve_window_id_by_row(row)
        if not resolved_window_id:
            return
        workflows = self._get_window_workflows(resolved_window_id)
        workflow_item = self.window_table.item(row, 2)
        if workflow_item is None:
            workflow_item = QTableWidgetItem()
            workflow_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.window_table.setItem(row, 2, workflow_item)
        workflow_item.setText(self._format_workflow_summary(workflows))
        workflow_item.setToolTip(self._build_workflow_tooltip(workflows))

        current_status = self._get_window_status_text(row)
        if workflows and current_status == "未分配":
            self._set_status_cell(row, "就绪")
            self._set_step_cell(row, "等待开始")
        elif (not workflows) and current_status in {"", "未分配", "就绪"}:
            self._set_status_cell(row, "未分配")
            self._set_step_cell(row, "请先分配工作流")

    def _refresh_overview_metrics(self):
        return

    def _refresh_batch_operation_hints(self):
        selected_rows = self._get_selected_rows()
        has_selection = len(selected_rows) > 0
        self.assign_btn.setEnabled(has_selection)

        if has_selection:
            selected_titles = []
            for row in selected_rows[:2]:
                title_item = self.window_table.item(row, 0)
                if title_item:
                    selected_titles.append(title_item.text())
            preview = "、".join(selected_titles)
            if len(selected_rows) == 1 and preview:
                self.selection_label.setText(f"已选择: {preview}")
            elif preview:
                suffix = f" 等{len(selected_rows)}个窗口" if len(selected_rows) > 2 else ""
                self.selection_label.setText(f"已选择 {len(selected_rows)} 个窗口：{preview}{suffix}")
            else:
                self.selection_label.setText(f"已选择 {len(selected_rows)} 个窗口")
            self.start_all_btn.setToolTip("启动已选窗口中已分配工作流的任务；未选择时启动全部")
            self.stop_all_btn.setToolTip("停止已选窗口中正在运行的任务；未选择时停止全部")
            self.pause_all_btn.setToolTip("暂停/恢复已选窗口中正在运行的任务；未选择时作用于全部 (F11)")
        else:
            self.selection_label.setText("未选择窗口时，批量操作将作用于全部窗口")
            self.start_all_btn.setToolTip("启动所有已分配工作流的窗口")
            self.stop_all_btn.setToolTip("通过主程序停止所有正在运行的工作流")
            self.pause_all_btn.setToolTip("暂停/恢复所有正在运行的工作流 (F11)")

        self._sync_pause_all_button_text()

    def _show_window_detail(self, row: int):
        window_info = self._get_row_window_info(row)
        if not window_info:
            return

        window_title = self.format_window_title(window_info.get("title", "未知窗口"), row)
        window_id = str(window_info.get("hwnd", row))
        workflows = self._get_window_workflows(window_id)

        dialog = QDialog(self)
        dialog.setWindowTitle(f"窗口详情 - {window_title}")
        dialog.resize(680, 480)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header_label = QLabel(
            f"句柄：{window_id}\n状态：{self._get_window_status_text(row)}\n当前步骤：{self._get_window_step_text(row)}"
        )
        header_label.setWordWrap(True)
        layout.addWidget(header_label)

        workflow_view = QTextEdit(dialog)
        workflow_view.setReadOnly(True)
        if workflows:
            workflow_lines = []
            for index, workflow_info in enumerate(workflows, start=1):
                name = str(workflow_info.get("name") or f"工作流{index}").strip() or f"工作流{index}"
                file_path = str(workflow_info.get("file_path") or "").strip()
                workflow_lines.append(f"{index}. {name}")
                if file_path:
                    workflow_lines.append(file_path)
                workflow_lines.append("")
            workflow_view.setPlainText("\n".join(workflow_lines).strip())
        else:
            workflow_view.setPlainText("当前未分配工作流")
        layout.addWidget(workflow_view, 1)

        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setMinimumHeight(30)
        close_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)
        dialog.exec()

    def _on_window_table_double_clicked(self, row: int, _column: int):
        self._show_window_detail(row)

    def _show_window_table_context_menu(self, pos):
        item = self.window_table.itemAt(pos)
        if item is None:
            return

        row = item.row()
        if row not in self._get_selected_rows():
            self.window_table.clearSelection()
            self.window_table.selectRow(row)

        menu = apply_unified_menu_style(QMenu(self), frameless=True)
        menu.addAction("分配工作流", lambda row=row: self.assign_workflow_to_window(row))
        menu.addAction("启动任务", lambda row=row: self.start_window_task(row))
        menu.addAction("停止任务", lambda row=row: self.stop_window_task(row))
        menu.addSeparator()
        menu.addAction("查看详情", lambda row=row: self._show_window_detail(row))
        menu.exec(self.window_table.viewport().mapToGlobal(pos))

    def on_selection_changed(self):
        """表格选择变化时的处理"""
        self._refresh_batch_operation_hints()

    def populate_window_table(self):
        """填充窗口表格数据"""
        self.sorted_windows = self.sort_windows_by_title(self.bound_windows)

        logger.info(f"开始填充窗口表格，共有 {len(self.sorted_windows)} 个窗口")
        self.window_table.setRowCount(len(self.sorted_windows))

        for row, window_info in enumerate(self.sorted_windows):
            original_title = window_info.get("title", "未知窗口")
            display_title = self.format_window_title(original_title, row)
            hwnd = window_info.get("hwnd", 0)
            window_id = str(hwnd)
            workflows = self._get_window_workflows(window_id)
            workflow_text = self._format_workflow_summary(workflows)
            status_text = "就绪" if workflows else "未分配"
            step_text = "等待开始" if workflows else "请先分配工作流"

            title_item = QTableWidgetItem(display_title)
            title_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.window_table.setItem(row, 0, title_item)

            hwnd_item = QTableWidgetItem(str(hwnd))
            hwnd_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.window_table.setItem(row, 1, hwnd_item)

            workflow_item = QTableWidgetItem(workflow_text)
            workflow_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            workflow_item.setToolTip(self._build_workflow_tooltip(workflows))
            self.window_table.setItem(row, 2, workflow_item)

            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.window_table.setItem(row, 3, status_item)
            self._apply_status_style(status_item, status_text)

            step_item = QTableWidgetItem(step_text)
            step_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.window_table.setItem(row, 4, step_item)

        logger.info("窗口表格填充完成")
        self.window_table.viewport().update()
        self.window_table.repaint()
        self.on_selection_changed()

    def find_window_row(self, window_id):
        """Return table row index by window id."""
        for row in range(self.window_table.rowCount()):
            hwnd_item = self.window_table.item(row, 1)
            if hwnd_item and hwnd_item.text() == window_id:
                return row
        return -1

