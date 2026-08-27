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

COL_TITLE = 0
COL_WORKFLOW = 1
COL_STATUS = 2
COL_STEP = 3
WINDOW_TABLE_HEADERS = ("窗口", "工作流", "状态", "步骤")

from app_core.control_plane import (
    JobState,
    ensure_bind_id,
    parse_job_state,
    pick_leading_runner_step,
    resolve_target_job_id,
)
from ui.system_parts.menu_style import apply_unified_menu_style

logger = logging.getLogger(__name__)


def format_bound_window_display_title(original_title, row_index, windows) -> str:
    title = str(original_title or "").strip() or "未知窗口"
    if not isinstance(windows, list):
        return title
    same_indexes = []
    for index, item in enumerate(windows):
        item_title = str((item or {}).get("title") or "").strip() or "未知窗口"
        if item_title == title:
            same_indexes.append(index)
    if len(same_indexes) <= 1:
        return title
    try:
        occurrence = same_indexes.index(int(row_index)) + 1
    except (TypeError, ValueError):
        occurrence = int(row_index) + 1 if str(row_index).isdigit() else 1
    return f"{title}-{occurrence}"


def resolve_control_center_window_id(window_info: Optional[Dict[str, Any]], row: Optional[int] = None) -> str:
    return resolve_target_job_id(window_info, row)


class ControlCenterWindowTableMixin:
    def _get_selected_rows(self) -> List[int]:
        if not hasattr(self, "window_table") or self.window_table is None:
            return []
        selection_model = self.window_table.selectionModel()
        if selection_model is None:
            return []
        rows = sorted({index.row() for index in selection_model.selectedRows()})
        if rows:
            return rows
        return sorted({index.row() for index in selection_model.selectedIndexes()})

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
        return self._window_runtime_id(self.sorted_windows[row_index], row_index)

    def _window_runtime_id(self, window_info: Optional[Dict[str, Any]], row: Optional[int] = None) -> Optional[str]:
        scheduler = getattr(self, "scheduler", None)
        if scheduler is not None and isinstance(window_info, dict):
            return scheduler.ensure_job(window_info, row).job_id
        job_id = resolve_target_job_id(window_info, row)
        return job_id or None

    def _ensure_window_bind_id(self, window_info: Optional[Dict[str, Any]]) -> str:
        return ensure_bind_id(window_info)

    def _canonicalize_window_id_set(self, window_ids) -> set:
        normalized = self._normalize_window_id_list(window_ids) if hasattr(self, "_normalize_window_id_list") else [
            str(item).strip() for item in (window_ids or []) if str(item).strip()
        ]
        scheduler = getattr(self, "scheduler", None)
        if scheduler is not None:
            return set(scheduler.canonicalize_ids(normalized))
        return set(normalized)

    def _job_id_in_filter(self, job_id: str, filter_ids, window_info: Optional[Dict[str, Any]] = None) -> bool:
        scheduler = getattr(self, "scheduler", None)
        hwnd = (window_info or {}).get("hwnd") if isinstance(window_info, dict) else None
        if scheduler is not None:
            return scheduler.matches_filter(job_id, filter_ids, hwnd=hwnd)
        if filter_ids is None:
            return True
        tokens = {str(item).strip() for item in filter_ids if str(item).strip()}
        return not tokens or str(job_id or "").strip() in tokens

    def _migrate_window_runtime_key(self, old_id: str, new_id: str) -> None:
        old_key = str(old_id or "").strip()
        new_key = str(new_id or "").strip()
        if not old_key or not new_key or old_key == new_key:
            return
        for store_name in ("window_workflows", "window_runners", "_window_workflow_results"):
            store = getattr(self, store_name, None)
            if isinstance(store, dict) and old_key in store and new_key not in store:
                store[new_key] = store.pop(old_key)

    def _refresh_bound_window_handles(self) -> bool:
        from utils.window.hwnd_utils import as_hwnd
        from utils.window.window_identity import refresh_bound_windows

        old_ids = {
            id(window_info): self._window_runtime_id(window_info, row)
            for row, window_info in enumerate(self.sorted_windows)
        }
        changed = bool(refresh_bound_windows(self.bound_windows))
        scheduler = getattr(self, "scheduler", None)
        if scheduler is not None:
            scheduler.sync_targets(self.sorted_windows or self.bound_windows)
        for row, window_info in enumerate(self.sorted_windows):
            self._ensure_window_bind_id(window_info)
            new_id = self._window_runtime_id(window_info, row)
            old_id = old_ids.get(id(window_info))
            if old_id and new_id and old_id != new_id:
                self._migrate_window_runtime_key(old_id, new_id)
                changed = True
            if scheduler is not None:
                scheduler.refresh_hwnd(new_id, window_info.get("hwnd"))
            if hasattr(self, "window_table") and self.window_table is not None:
                title_item = self.window_table.item(row, COL_TITLE)
                if title_item is not None:
                    title_item.setToolTip(self._window_row_tooltip(window_info, new_id))
        return changed

    def _refresh_all_window_workflow_cells(self) -> None:
        if not hasattr(self, "window_table") or self.window_table is None:
            return
        for row in range(self.window_table.rowCount()):
            self._refresh_window_workflow_cell(row)
        self.on_selection_changed()

    def _get_row_window_info(self, row: int) -> Dict[str, Any]:
        if row < 0 or row >= len(self.sorted_windows):
            return {}
        return self.sorted_windows[row]

    def _get_window_status_text(self, row: int) -> str:
        item = self.window_table.item(row, COL_STATUS)
        return item.text().strip() if item else ""

    def _get_window_step_text(self, row: int) -> str:
        item = self.window_table.item(row, COL_STEP)
        return item.text().strip() if item else ""

    def _apply_status_style(self, item: Optional[QTableWidgetItem], status_text: str):
        if item is None:
            return
        from themes import theme_color

        status_colors = {
            "未分配": QColor(theme_color("text_disabled", "#999999")),
            "就绪": QColor(theme_color("info", "#0078d4")),
            "等待开始": QColor(theme_color("info", "#0078d4")),
            "正在启动": QColor(theme_color("info", "#0078d4")),
            "正在运行": QColor(theme_color("success", "#107c10")),
            "暂停中": QColor(theme_color("warning", "#ff8c00")),
            "已暂停": QColor(theme_color("warning", "#ff8c00")),
            "正在停止": QColor(theme_color("warning", "#ff8c00")),
            "已中断": QColor(theme_color("text_disabled", "#666666")),
            "已完成": QColor(theme_color("success", "#107c10")),
            "完成": QColor(theme_color("success", "#107c10")),
            "失败": QColor(theme_color("error", "#e81123")),
            "执行失败": QColor(theme_color("error", "#e81123")),
        }
        item.setForeground(status_colors.get(status_text, QColor(theme_color("text", "#333333"))))

    def _set_status_cell(self, row: int, status_text: str):
        item = self.window_table.item(row, COL_STATUS)
        if item is None:
            item = QTableWidgetItem()
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.window_table.setItem(row, COL_STATUS, item)
        item.setText(status_text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._apply_status_style(item, status_text)

    def _set_step_cell(self, row: int, step_text: str):
        item = self.window_table.item(row, COL_STEP)
        if item is None:
            item = QTableWidgetItem()
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.window_table.setItem(row, COL_STEP, item)
        item.setText(step_text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

    def _window_row_tooltip(self, window_info: Optional[Dict[str, Any]], window_id: str = "") -> str:
        from utils.window.hwnd_utils import as_hwnd

        title = str((window_info or {}).get("title") or "未知窗口")
        hwnd = as_hwnd((window_info or {}).get("hwnd"))
        job_id = str(window_id or (window_info or {}).get("bind_id") or "").strip()
        return f"{title}\n句柄：{hwnd}\n作业：{job_id}"

    def _set_row_workflow_cell(self, row: int, text: str, tooltip: str = ""):
        self.window_table.removeCellWidget(row, COL_WORKFLOW)
        item = self.window_table.item(row, COL_WORKFLOW)
        if item is None:
            item = QTableWidgetItem()
            self.window_table.setItem(row, COL_WORKFLOW, item)
        item.setText(text)
        item.setToolTip(tooltip)
        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

    def _update_single_window_table_status(self, window_id, status_text: str, step_text: Optional[str] = None):
        self._update_window_table_status([window_id], status_text, step_text)

    def _paint_job_snapshot(self, job_id, snapshot=None, step_text: Optional[str] = None):
        scheduler = getattr(self, "scheduler", None)
        if snapshot is None and scheduler is not None:
            snapshot = scheduler.snapshot(str(job_id))
        row = self.find_window_row(str(job_id))
        if row < 0:
            return snapshot
        if snapshot is not None:
            self._set_status_cell(row, snapshot.state.value)
            self._set_step_cell(row, step_text if step_text is not None else snapshot.step)
        elif step_text is not None:
            self._set_step_cell(row, step_text)
        self._refresh_overview_metrics()
        return snapshot

    def _collect_runner_job_states(self, window_id) -> List:
        states = []
        get_runners = getattr(self, "_get_window_runner_list", None)
        if not callable(get_runners):
            return states
        for runner in get_runners(window_id):
            parsed = parse_job_state(self._get_runner_state_value(runner))
            if parsed is not None:
                states.append(parsed)
        return states

    def _collect_runner_step_entries(self, window_id) -> List:
        entries = []
        get_runners = getattr(self, "_get_window_runner_list", None)
        if not callable(get_runners):
            return entries
        for runner in get_runners(window_id):
            state = self._get_runner_state_value(runner)
            step = str(getattr(runner, "_last_status_message", "") or "").strip()
            entries.append((state, step))
        return entries

    def _leading_runner_step(self, window_id) -> Optional[str]:
        return pick_leading_runner_step(self._collect_runner_step_entries(window_id))

    def _sync_job_from_runners(self, window_id, step_text: Optional[str] = None):
        scheduler = getattr(self, "scheduler", None)
        job_id = str(window_id or "")
        states = self._collect_runner_job_states(job_id)
        if step_text is None:
            step_text = self._leading_runner_step(job_id)
        snapshot = None
        if scheduler is not None:
            if states:
                snapshot = scheduler.apply_runner_states(job_id, states, step=str(step_text or ""))
            else:
                job = scheduler.get_job(job_id)
                if job is not None and job.state in {
                    JobState.STARTING,
                    JobState.RUNNING,
                    JobState.PAUSED,
                    JobState.STOPPING,
                }:
                    snapshot = scheduler.finalize_orphaned_stop(job_id)
                else:
                    snapshot = scheduler.snapshot(job_id)
        return self._paint_job_snapshot(job_id, snapshot, step_text)

    def _update_window_table_status(self, window_ids, status_text: str, step_text: Optional[str] = None):
        """按状态机回写表格；非法跳转会被拒绝，界面保持当前作业快照。"""
        if not window_ids:
            return
        scheduler = getattr(self, "scheduler", None)
        for window_id in window_ids:
            snapshot = None
            if scheduler is not None:
                snapshot = scheduler.apply_status_text(str(window_id), status_text, step_text, force=False)
            else:
                row = self.find_window_row(str(window_id))
                if row >= 0:
                    self._set_status_cell(row, status_text)
                    if step_text is not None:
                        self._set_step_cell(row, step_text)
                continue
            self._paint_job_snapshot(str(window_id), snapshot, step_text)

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
        self._set_row_workflow_cell(
            row,
            self._format_workflow_summary(workflows),
            self._build_workflow_tooltip(workflows),
        )

        scheduler = getattr(self, "scheduler", None)
        if scheduler is not None:
            scheduler.sync_assignment_state(resolved_window_id)
            snapshot = scheduler.snapshot(resolved_window_id)
            if snapshot is not None and not snapshot.is_active:
                self._set_status_cell(row, snapshot.state.value)
                self._set_step_cell(row, snapshot.step)
            return

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
            self.selection_label.setText("未选择")
            self.start_all_btn.setToolTip("启动所有已分配工作流的窗口")
            self.stop_all_btn.setToolTip("通过主程序停止所有正在运行的工作流")
            self.pause_all_btn.setToolTip("暂停/恢复所有正在运行的工作流 (F11)")

        self._sync_pause_all_button_text()

    def _show_window_detail(self, row: int):
        window_info = self._get_row_window_info(row)
        if not window_info:
            return

        window_title = self.format_window_title(window_info.get("title", "未知窗口"), row)
        window_id = self._window_runtime_id(window_info, row)
        workflows = self._get_window_workflows(window_id)

        dialog = QDialog(self)
        dialog.setWindowTitle(f"窗口详情 - {window_title}")
        dialog.resize(680, 480)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        from utils.window.hwnd_utils import as_hwnd

        hwnd = as_hwnd(window_info.get("hwnd"))
        header_label = QLabel(
            f"句柄：{hwnd}\n作业：{window_id}\n状态：{self._get_window_status_text(row)}\n当前步骤：{self._get_window_step_text(row)}"
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
        scheduler = getattr(self, "scheduler", None)
        if scheduler is not None:
            scheduler.sync_targets(self.sorted_windows)

        logger.info(f"开始填充窗口表格，共有 {len(self.sorted_windows)} 个窗口")
        self.window_table.setRowCount(len(self.sorted_windows))

        for row, window_info in enumerate(self.sorted_windows):
            self._ensure_window_bind_id(window_info)
            original_title = window_info.get("title", "未知窗口")
            display_title = self.format_window_title(original_title, row)
            window_id = self._window_runtime_id(window_info, row)
            snapshot = scheduler.snapshot(window_id) if scheduler is not None else None
            workflows = list(snapshot.assignments) if snapshot is not None else self._get_window_workflows(window_id)
            workflow_text = self._format_workflow_summary(workflows)
            if snapshot is not None:
                status_text = snapshot.state.value
                step_text = snapshot.step or ("等待开始" if workflows else "请先分配工作流")
            else:
                status_text = "就绪" if workflows else "未分配"
                step_text = "等待开始" if workflows else "请先分配工作流"

            title_item = QTableWidgetItem(display_title)
            title_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            title_item.setToolTip(self._window_row_tooltip(window_info, window_id))
            self.window_table.setItem(row, COL_TITLE, title_item)

            self._set_row_workflow_cell(row, workflow_text, self._build_workflow_tooltip(workflows))

            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.window_table.setItem(row, COL_STATUS, status_item)
            self._apply_status_style(status_item, status_text)

            step_item = QTableWidgetItem(step_text)
            step_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.window_table.setItem(row, COL_STEP, step_item)

        logger.info("窗口表格填充完成")
        self.window_table.clearSelection()
        from PySide6.QtCore import QModelIndex

        self.window_table.setCurrentIndex(QModelIndex())
        self.window_table.viewport().update()
        self.window_table.repaint()
        self.on_selection_changed()

    def find_window_row(self, window_id):
        """Return table row index by window id."""
        target = str(window_id or "").strip()
        if not target:
            return -1
        for row, window_info in enumerate(self.sorted_windows):
            if self._window_runtime_id(window_info, row) == target:
                return row
            if str(window_info.get("bind_id") or "").strip() == target:
                return row
        return -1

    def _on_window_table_cell_clicked(self, row: int, _column: int):
        if row not in self._get_selected_rows():
            self.window_table.selectRow(row)
        self.on_selection_changed()

