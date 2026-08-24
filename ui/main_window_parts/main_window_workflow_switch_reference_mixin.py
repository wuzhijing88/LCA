import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class MainWindowWorkflowSwitchReferenceMixin:

    def _open_workflow_reference(self, filepath: str, switch_to_tab: bool = True) -> Optional[int]:
        workflow_ref = str(filepath or '').strip()
        if not workflow_ref:
            return None
        return self._find_or_import_workflow(workflow_ref, switch_to_tab=switch_to_tab)
    def _find_or_import_workflow(self, filepath: str, switch_to_tab: bool = True) -> Optional[int]:
        """查找已打开的工作流或导入新工作流，返回task_id"""
        abs_filepath = os.path.abspath(filepath)
        # 检查是否已打开
        for task in self.task_manager.get_all_tasks():
            if task.filepath and os.path.abspath(task.filepath) == abs_filepath:
                # 已打开，切换到对应标签页
                tab_index = self.workflow_tab_widget.task_to_tab.get(task.task_id)
                if switch_to_tab and tab_index is not None:
                    self.workflow_tab_widget.setCurrentIndex(tab_index)
                logger.info(f"工作流已打开，复用: {task.name}, task_id={task.task_id}")
                return task.task_id
        # 未打开，导入新工作流
        return self.workflow_tab_widget.import_workflow(filepath, activate_tab=switch_to_tab)
