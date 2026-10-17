import copy
import json
import logging
import os
from typing import Any, Dict, List

from PySide6.QtWidgets import QMessageBox

from app_core.control_plane import unwrap_assignment_record, wrap_assignment_record
from task_workflow.workflow_payload import load_workflow_file

logger = logging.getLogger(__name__)


def drop_assigned_workflow(workflows: List[Dict[str, Any]], index: int) -> List[Dict[str, Any]]:
    items = [item for item in (workflows or []) if isinstance(item, dict)]
    if index < 0 or index >= len(items):
        raise ValueError("工作流序号无效")
    remaining = list(items)
    remaining.pop(index)
    return remaining


class ControlCenterWorkflowAssignmentMixin:
    def _select_workflow_files(self, title: str):
        from task_workflow.workspace import load_workspace_favorites_snapshot
        from .control_center_workspace_picker import pick_workspace_workflow_files

        try:
            config_path = self.parent_window.parameter_panel._favorites_config_path
            _, favorites, _, _, _ = load_workspace_favorites_snapshot(config_path)
            return pick_workspace_workflow_files(self, title, favorites)
        except Exception as exc:
            logger.error("读取工作区失败: %s", exc, exc_info=True)
            QMessageBox.warning(self, "无法选择工作流", f"读取工作区失败：{exc}")
            return []

    def _load_workflow_entries(self, file_paths: List[str]):
        workflow_entries: List[Dict[str, Any]] = []
        error_files: List[str] = []
        for file_path in file_paths:
            try:
                workflow_data = load_workflow_file(file_path)
                if isinstance(workflow_data, dict):
                    from task_workflow.workflow_sanitize import sanitize_workflow_data

                    sanitize_workflow_data(workflow_data)
                workflow_entries.append({
                    'file_path': file_path,
                    'data': copy.deepcopy(workflow_data),
                    'name': os.path.basename(file_path)
                })
            except Exception as e:
                logger.error(f"工作流导入失败: {file_path}, 错误={e}")
                error_files.append(os.path.basename(file_path))
        return workflow_entries, error_files

    def _apply_workflow_entries_to_rows(self, rows: List[int], workflow_entries: List[Dict[str, Any]]):
        success_rows = 0
        failed_rows: List[str] = []
        for row in rows:
            window_info = self._get_row_window_info(row)
            if not window_info:
                continue
            window_id = self._window_runtime_id(window_info, row)
            window_title = str(window_info.get('title', '\u672a\u77e5\u7a97\u53e3'))
            try:
                workflows = self._ensure_window_workflow_list(window_id)
                for workflow_entry in workflow_entries:
                    workflows.append({
                        'file_path': workflow_entry['file_path'],
                        'data': copy.deepcopy(workflow_entry['data']),
                        'name': workflow_entry['name']
                    })
                self._refresh_window_workflow_cell(row, window_id)
                success_rows += 1
            except Exception as e:
                logger.error(f"工作流分配失败 {window_title}：{e}")
                failed_rows.append(window_title)
        self._refresh_overview_metrics()
        return success_rows, failed_rows

    def _collect_workflow_entries_for_assign(self, title: str):
        parent = getattr(self, "parent_window", None)
        picker = getattr(parent, "pick_control_center_workflow_entries", None) if parent else None
        if callable(picker):
            entries = picker(self, title)
            if not entries:
                return None
            return list(entries), []
        file_paths = self._select_workflow_files(title)
        if not file_paths:
            return None
        return self._load_workflow_entries(file_paths)

    def _assign_workflow_files_to_rows(self, rows: List[int], title: str, scope_desc: str):
        if not rows:
            QMessageBox.information(self, "提示", "请先选择目标窗口")
            return False

        collected = self._collect_workflow_entries_for_assign(title)
        if collected is None:
            return False
        workflow_entries, error_files = collected
        if not workflow_entries:
            QMessageBox.warning(self, "错误", "所有工作流导入失败")
            self.log_message("工作流导入失败")
            return False

        if len(rows) > 1:
            reply = QMessageBox.question(
                self,
                "确认批量分配",
                f"是否向 {len(rows)} 个窗口追加 {len(workflow_entries)} 个工作流？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False

        success_count, failed_rows = self._apply_workflow_entries_to_rows(rows, workflow_entries)
        if success_count > 0:
            self._save_workflow_config()
        self.on_selection_changed()

        detail_parts = [f"成功={success_count}"]
        if failed_rows:
            detail_parts.append(f"窗口失败={len(failed_rows)}")
        if error_files:
            detail_parts.append(f"文件失败={len(error_files)}")
        self.log_message(f"工作流分配完成：范围={scope_desc}，" + "，".join(detail_parts))

        if success_count > 0:
            QMessageBox.information(
                self,
                "分配完成",
                f"范围：{scope_desc}\n成功：{success_count}\n窗口失败：{len(failed_rows)}\n文件失败：{len(error_files)}"
            )
        else:
            QMessageBox.warning(self, "错误", "所有目标窗口的工作流分配均失败")

        if error_files:
            QMessageBox.warning(
                self,
                "导入错误",
                "以下工作流文件加载失败：\n" + "\n".join(error_files[:12])
            )
        return success_count > 0

    def assign_workflow_to_selected(self):
        """Assign workflows to selected windows."""
        rows = self._get_selected_rows()
        self._assign_workflow_files_to_rows(rows, "\u4e3a\u5df2\u9009\u7a97\u53e3\u9009\u62e9\u5de5\u4f5c\u6d41", "\u5df2\u9009\u7a97\u53e3")

    def assign_workflow_to_all(self):
        """Assign workflows to all windows."""
        self._assign_workflow_files_to_rows(self._get_all_rows(), "\u4e3a\u6240\u6709\u7a97\u53e3\u9009\u62e9\u5de5\u4f5c\u6d41", "\u5168\u90e8\u7a97\u53e3")

    def assign_workflow_to_window(self, row):
        """Assign workflows to one window."""
        window_info = self._get_row_window_info(row)
        if not window_info:
            return
        window_title = str(window_info.get('title', '未知窗口'))
        self._assign_workflow_files_to_rows([row], f"为窗口 '{window_title}' 选择工作流", f"窗口 {window_title}")

    def remove_workflow_from_window(self, row):
        """Remove all workflows assigned to one window and persist the change."""
        return self._remove_workflow_assignments([row], "该窗口")

    def remove_window_workflow_at(self, row: int, index: int) -> bool:
        window_info = self._get_row_window_info(row)
        if not window_info:
            return False
        window_id = self._window_runtime_id(window_info, row)
        if not window_id:
            return False
        scheduler = getattr(self, "scheduler", None)
        snapshot = scheduler.snapshot(window_id) if scheduler is not None else None
        if snapshot is not None and snapshot.is_active:
            QMessageBox.warning(self, "无法移除", "该窗口的工作流正在运行，请先停止任务")
            return False
        workflows = self._get_window_workflows(window_id)
        try:
            remaining = drop_assigned_workflow(workflows, index)
        except ValueError as exc:
            QMessageBox.warning(self, "无法移除", str(exc))
            return False
        removed = workflows[index]
        removed_name = str(removed.get("name") or os.path.basename(str(removed.get("file_path") or "")) or "工作流")
        reply = QMessageBox.question(
            self,
            "移除工作流",
            f"确定移除「{removed_name}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False
        self.window_workflows[window_id] = remaining
        self._refresh_window_workflow_cell(row, window_id)
        self._save_workflow_config()
        self.on_selection_changed()
        self.log_message(f"已移除窗口工作流：{removed_name}")
        return True

    def remove_workflows_from_selected(self):
        """Remove all workflows assigned to the selected windows."""
        return self._remove_workflow_assignments(self._get_selected_rows(), "选中窗口")

    def remove_workflows_from_all(self):
        """Remove all workflows assigned to every window."""
        return self._remove_workflow_assignments(self._get_all_rows(), "全部窗口")

    def _remove_workflow_assignments(self, rows: List[int], scope_label: str):
        if not rows:
            QMessageBox.information(self, "提示", "请先选择目标窗口")
            return False
        targets = []
        active_titles = []
        total_workflows = 0
        scheduler = getattr(self, "scheduler", None)
        for row in rows:
            window_info = self._get_row_window_info(row)
            if not window_info:
                continue
            window_id = self._window_runtime_id(window_info, row)
            if not window_id:
                continue
            workflows = self._get_window_workflows(window_id)
            if not workflows:
                continue
            snapshot = scheduler.snapshot(window_id) if scheduler is not None else None
            window_title = str(window_info.get("title") or "未知窗口")
            if snapshot is not None and snapshot.is_active:
                active_titles.append(window_title)
                continue
            targets.append((row, window_id, window_title, len(workflows)))
            total_workflows += len(workflows)

        if active_titles:
            QMessageBox.warning(
                self,
                "无法移除",
                "以下窗口的工作流正在运行，请先停止任务：\n" + "、".join(active_titles[:8]),
            )
            return False
        if not targets:
            QMessageBox.information(self, "提示", "选中的窗口当前没有可移除的工作流")
            return False

        reply = QMessageBox.question(
            self,
            "移除工作流",
            f"确定移除{scope_label}的 {total_workflows} 个已分配工作流吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False

        for row, window_id, _window_title, _count in targets:
            # AssignmentMap returns a copy from _get_window_workflows; assign
            # through the mapping so scheduler state is updated as well.
            self.window_workflows[window_id] = []
            self._refresh_window_workflow_cell(row, window_id)
        self._save_workflow_config()
        self.on_selection_changed()
        self.log_message(f"已移除 {len(targets)} 个窗口的 {total_workflows} 个工作流")
        return True




    def _match_saved_window_id(self, saved_key: str) -> str:
        return self.scheduler.match_saved_key(saved_key)

    def _persist_bound_window_identities(self):
        parent = getattr(self, "parent_window", None)
        if parent is None:
            return
        try:
            parent._store_runtime_bound_windows_to_config()
            parent.save_config_func(parent.config)
        except Exception as e:
            logger.warning("保存绑定窗口身份失败: %s", e)

    def _save_workflow_config(self):
        """保存工作流配置到临时文件"""
        try:
            config_data = {}
            for row, window_info in enumerate(self.sorted_windows):
                runtime_id = self._window_runtime_id(window_info, row)
                workflows = self.window_workflows.get(runtime_id)
                if not workflows:
                    continue
                persist_key = self._ensure_window_bind_id(window_info)
                if not persist_key:
                    raise ValueError("窗口缺少绑定标识，无法保存工作流分配")
                config_data[persist_key] = wrap_assignment_record(window_info, workflows)

            with open(self.temp_workflow_config_file, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)

            self._persist_bound_window_identities()
            logger.info(f"工作流配置已保存到: {self.temp_workflow_config_file}")

        except Exception as e:
            logger.error(f"保存工作流配置失败: {e}")

    def _load_workflow_entries_from_saved(self, workflows_info):
        loaded = []
        if not isinstance(workflows_info, list):
            return loaded
        parent = getattr(self, "parent_window", None)
        loader = getattr(parent, "load_control_center_workflow_entry", None) if parent else None
        for wf_info in workflows_info:
            if not isinstance(wf_info, dict):
                continue
            file_path = wf_info.get("file_path", "")
            if callable(loader):
                entry = loader(file_path, name=wf_info.get("name", ""))
                if entry:
                    loaded.append(entry)
                else:
                    logger.warning("工作流不可用: %s", file_path)
                continue
            if not file_path or not os.path.exists(file_path):
                if file_path:
                    logger.warning(f"工作流文件不存在: {file_path}")
                continue
            workflow_data = load_workflow_file(file_path)
            if isinstance(workflow_data, dict):
                from task_workflow.workflow_sanitize import sanitize_workflow_data

                sanitize_workflow_data(workflow_data)
            loaded.append({
                "file_path": file_path,
                "data": copy.deepcopy(workflow_data),
                "name": wf_info.get("name", os.path.basename(file_path)),
            })
        return loaded

    def _load_workflow_config(self):
        """从临时文件加载工作流配置"""
        try:
            if not os.path.exists(self.temp_workflow_config_file):
                logger.info("未找到之前保存的工作流配置")
                return

            with open(self.temp_workflow_config_file, "r", encoding="utf-8") as f:
                config_data = json.load(f)
            if not isinstance(config_data, dict):
                return

            loaded_count = 0
            for saved_key, workflows_info in config_data.items():
                try:
                    saved = unwrap_assignment_record(workflows_info)
                    if not saved.get("workflows"):
                        continue
                    window_id = self._match_saved_window_id(saved_key)
                    if not window_id:
                        continue
                    entries = self._load_workflow_entries_from_saved(saved.get("workflows"))
                    if not entries:
                        continue
                    self.window_workflows[window_id] = entries
                    loaded_count += len(entries)
                except Exception as e:
                    logger.error(f"加载窗口{saved_key}的工作流失败: {e}")

            if loaded_count > 0:
                logger.info(f"成功加载 {loaded_count} 个工作流配置")
                self.log_message(f"已恢复 {loaded_count} 个工作流配置")
            else:
                logger.info("没有有效的工作流配置可加载")

        except Exception as e:
            logger.error(f"加载工作流配置失败: {e}")

    def _clear_workflow_config(self):
        """清除临时工作流配置文件"""
        try:
            if os.path.exists(self.temp_workflow_config_file):
                os.remove(self.temp_workflow_config_file)
                logger.info(f"已清除临时工作流配置文件: {self.temp_workflow_config_file}")
        except Exception as e:
            logger.error(f"清除临时工作流配置文件失败: {e}")
