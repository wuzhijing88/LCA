import copy
import json
import logging
import os
from typing import Any, Dict, List

from PySide6.QtWidgets import QFileDialog, QMessageBox

from utils.app_paths import get_workflows_dir

logger = logging.getLogger(__name__)


class ControlCenterWorkflowAssignmentMixin:
    def _select_workflow_files(self, title: str):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            title,
            get_workflows_dir(),
            "JSON 文件 (*.json);;所有文件 (*)"
        )
        return file_paths

    def _load_workflow_entries(self, file_paths: List[str]):
        workflow_entries: List[Dict[str, Any]] = []
        error_files: List[str] = []
        for file_path in file_paths:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    workflow_data = json.load(f)
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
            window_id = str(window_info.get('hwnd', row))
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

    def _assign_workflow_files_to_rows(self, rows: List[int], title: str, scope_desc: str):
        if not rows:
            QMessageBox.information(self, "提示", "请先选择目标窗口")
            return False

        file_paths = self._select_workflow_files(title)
        if not file_paths:
            return False

        if len(rows) > 1:
            reply = QMessageBox.question(
                self,
                "确认批量分配",
                f"是否向 {len(rows)} 个窗口追加 {len(file_paths)} 个工作流？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False

        workflow_entries, error_files = self._load_workflow_entries(file_paths)
        if not workflow_entries:
            QMessageBox.warning(self, "错误", "所有工作流导入失败")
            self.log_message("工作流导入失败")
            return False

        success_count, failed_rows = self._apply_workflow_entries_to_rows(rows, workflow_entries)
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




    def _save_workflow_config(self):
        """保存工作流配置到临时文件"""
        try:
            # 准备保存的数据
            config_data = {}
            for window_id, workflows in self.window_workflows.items():
                if isinstance(workflows, list):
                    # 只保存文件路径，不保存完整的工作流数据（减少文件大小）
                    config_data[window_id] = [
                        {
                            'file_path': wf.get('file_path', ''),
                            'name': wf.get('name', '')
                        }
                        for wf in workflows
                    ]
                else:
                    # 向后兼容旧格式
                    config_data[window_id] = {
                        'file_path': workflows.get('file_path', ''),
                        'name': workflows.get('name', '')
                    }

            # 保存到临时文件
            with open(self.temp_workflow_config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)

            logger.info(f"工作流配置已保存到: {self.temp_workflow_config_file}")

        except Exception as e:
            logger.error(f"保存工作流配置失败: {e}")

    def _load_workflow_config(self):
        """从临时文件加载工作流配置"""
        try:
            if not os.path.exists(self.temp_workflow_config_file):
                logger.info("未找到之前保存的工作流配置")
                return

            with open(self.temp_workflow_config_file, 'r', encoding='utf-8') as f:
                config_data = json.load(f)

            # 加载工作流数据
            loaded_count = 0
            for window_id, workflows_info in config_data.items():
                try:
                    # 处理列表格式
                    if isinstance(workflows_info, list):
                        self.window_workflows[window_id] = []
                        for wf_info in workflows_info:
                            file_path = wf_info.get('file_path', '')
                            if file_path and os.path.exists(file_path):
                                # 重新读取工作流文件
                                with open(file_path, 'r', encoding='utf-8') as wf:
                                    workflow_data = json.load(wf)

                                self.window_workflows[window_id].append({
                                    'file_path': file_path,
                                    'data': copy.deepcopy(workflow_data),
                                    'name': wf_info.get('name', os.path.basename(file_path))
                                })
                                loaded_count += 1
                            else:
                                logger.warning(f"工作流文件不存在: {file_path}")

                    # 处理旧的字典格式
                    elif isinstance(workflows_info, dict):
                        file_path = workflows_info.get('file_path', '')
                        if file_path and os.path.exists(file_path):
                            with open(file_path, 'r', encoding='utf-8') as wf:
                                workflow_data = json.load(wf)

                            self.window_workflows[window_id] = [{
                                'file_path': file_path,
                                'data': copy.deepcopy(workflow_data),
                                'name': workflows_info.get('name', os.path.basename(file_path))
                            }]
                            loaded_count += 1

                except Exception as e:
                    logger.error(f"加载窗口{window_id}的工作流失败: {e}")

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

    @staticmethod
    def _workflow_contains_yolo_task(workflow_data: Any) -> bool:
        """判断工作流是否包含 YOLO 任务。"""
        if not isinstance(workflow_data, dict):
            return False
        cards = workflow_data.get("cards")
        if not isinstance(cards, list):
            return False
        for card in cards:
            if not isinstance(card, dict):
                continue
            task_type = str(card.get("task_type") or "").strip()
            if not task_type:
                continue
            if "YOLO" in task_type.upper():
                return True
        return False

    def _collect_yolo_workflow_names(self, workflows: Any) -> List[str]:
        """收集窗口工作流中包含 YOLO 的工作流名称。"""
        if isinstance(workflows, dict):
            workflows = [workflows]
        if not isinstance(workflows, list):
            return []

        blocked_names: List[str] = []
        for idx, workflow_info in enumerate(workflows):
            if not isinstance(workflow_info, dict):
                continue
            workflow_data = workflow_info.get("data")
            if not self._workflow_contains_yolo_task(workflow_data):
                continue
            workflow_name = str(workflow_info.get("name") or f"工作流{idx + 1}").strip()
            blocked_names.append(workflow_name or f"工作流{idx + 1}")
        return blocked_names

    def _collect_yolo_blocked_windows(self, target_window_ids=None) -> Dict[str, Dict[str, Any]]:
        """收集指定窗口范围内包含 YOLO 的窗口信息。"""
        target_filter = set(self._normalize_window_id_list(target_window_ids)) if target_window_ids else None
        blocked: Dict[str, Dict[str, Any]] = {}

        for row, window_info in enumerate(self.sorted_windows):
            window_id = str(window_info.get("hwnd", row))
            if target_filter is not None and window_id not in target_filter:
                continue

            workflows = self.window_workflows.get(window_id)
            blocked_names = self._collect_yolo_workflow_names(workflows)
            if not blocked_names:
                continue

            blocked[window_id] = {
                "title": str(window_info.get("title", "未知窗口")),
                "workflow_names": blocked_names,
            }

        return blocked
