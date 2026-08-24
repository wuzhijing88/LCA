import logging
import os
from typing import List

from utils.workflow_workspace_utils import (
    get_effective_workflow_images_dir,
    load_workspace_favorites_snapshot,
    save_workspace_favorites_snapshot,
)

logger = logging.getLogger(__name__)


class MainWindowFavoritesMixin:
    def _on_favorite_workflow_check_changed(self, filepath: str, checked: bool):
        """处理收藏勾选状态变化。"""
        try:
            if checked:
                self._open_workflow_reference(filepath)
                return
            task = self.task_manager.find_task_by_filepath(filepath)
            if task is None:
                return
            tab_index = self.workflow_tab_widget.task_to_tab.get(task.task_id)
            if tab_index is not None:
                self.workflow_tab_widget.close_tab_silent(tab_index)
        except Exception:
            logger.exception("同步收藏工作流勾选状态失败: %s", filepath)
    def _auto_load_recent_workflows(self):
        """自动加载最近打开的工作流"""
        try:
            if not hasattr(self, 'workflow_tab_widget') or not self.workflow_tab_widget:
                return
            favorite_filepaths = self._load_checked_favorite_workflow_paths()
            has_favorites_config = self._has_favorites_workflow_config()
            if favorite_filepaths or has_favorites_config:
                # 启动阶段强制与收藏勾选保持一致，避免混入最近工作流标签页
                for tab_index in range(self.workflow_tab_widget.count() - 2, -1, -1):
                    self.workflow_tab_widget.close_tab_silent(tab_index)
                first_task_id = None
                for filepath in favorite_filepaths:
                    task_id = self._open_workflow_reference(filepath, switch_to_tab=False)
                    task = self.task_manager.get_task(task_id) if task_id is not None else None
                    if (
                        first_task_id is None
                        and task is not None
                        and not getattr(task, 'read_only_mode', False)
                    ):
                        first_task_id = task_id
                if first_task_id is not None:
                    tab_index = self.workflow_tab_widget.task_to_tab.get(first_task_id)
                    if tab_index is not None:
                        self.workflow_tab_widget.setCurrentIndex(tab_index)
            else:
                self.workflow_tab_widget.auto_load_recent_workflows()
            # 应用画布网格设置
            grid_enabled = self.config.get('enable_canvas_grid', True)
            self.workflow_tab_widget.set_all_grid_enabled(grid_enabled)
            card_snap_enabled = self.config.get('enable_card_snap', True)
            self.workflow_tab_widget.set_all_card_snap_enabled(card_snap_enabled)
            if hasattr(self, 'parameter_panel') and self.parameter_panel:
                self.parameter_panel.set_snap_to_parent_enabled(self.config.get('enable_parameter_panel_snap', True))
        except Exception as e:
            logger.error(f"自动加载工作流时出错: {e}")
    def _load_checked_favorite_workflow_paths(self) -> List[str]:
        """读取收藏配置中勾选的工作流标识（去重后保持原顺序）。"""
        try:
            from utils.app_paths import get_favorites_path
            favorites_path = get_favorites_path()
            if not os.path.exists(favorites_path):
                return []
            workspaces, favorites, changed = load_workspace_favorites_snapshot(favorites_path)
            if changed:
                save_workspace_favorites_snapshot(favorites_path, workspaces, favorites)
            checked_paths: List[str] = []
            for item in favorites:
                if not isinstance(item, dict):
                    continue
                if not bool(item.get('checked', True)):
                    continue
                raw_path = str(item.get('filepath') or '').strip()
                if not raw_path:
                    continue
                abs_path = os.path.abspath(raw_path)
                if os.path.exists(abs_path):
                    checked_paths.append(abs_path)
            dedup_paths: List[str] = []
            seen = set()
            for path in checked_paths:
                dedup_key = os.path.normcase(path)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                dedup_paths.append(path)
            return dedup_paths
        except Exception as e:
            logger.error(f"读取收藏工作流配置失败: {e}")
            return []
    def _on_favorites_opened(self, filepaths: list):
        """分帧打开已勾选的收藏工作流。"""
        try:
            from PySide6.QtCore import QTimer
            ordered_paths = []
            seen_paths = set()
            for filepath in filepaths or []:
                raw_path = str(filepath or '').strip()
                if not raw_path:
                    continue
                dedup_key = os.path.normcase(os.path.abspath(raw_path))
                if dedup_key in seen_paths:
                    continue
                seen_paths.add(dedup_key)
                ordered_paths.append(raw_path)
            if not ordered_paths:
                return
            self._favorites_open_queue = ordered_paths
            self._favorites_open_success = 0
            self._favorites_open_failed = 0
            self._favorites_open_first_task_id = None
            QTimer.singleShot(0, self._process_favorites_open_queue)
        except Exception as e:
            logger.error(f"批量打开收藏工作流失败: {e}")
    def _on_favorite_workflow_open(self, filepath: str):
        """从收藏打开单个工作流。"""
        from PySide6.QtCore import QTimer
        try:
            logger.info(f"从收藏打开工作流: {filepath}")
            if self._is_any_workflow_running():
                if hasattr(self, 'step_detail_label'):
                    self.step_detail_label.setText("存在正在运行的工作流，不能打开新的收藏工作流")
                    self._set_step_detail_style(text_color="#FF0000")
                    QTimer.singleShot(3000, lambda: self.step_detail_label.setText("准备就绪..."))
                logger.warning("存在正在运行的工作流，跳过打开收藏工作流")
                return
            task_id = self._open_workflow_reference(filepath)
            if task_id is not None:
                logger.info(f"收藏工作流已打开，任务ID: {task_id}")
            else:
                logger.warning(f"收藏工作流打开失败: {filepath}")
        except Exception as e:
            logger.error(f"打开收藏工作流失败: {e}")
    def _on_favorite_workflow_execute(self, filepath: str):
        """执行收藏的单个工作流（快捷键触发，只执行这一个工作流）"""
        from PySide6.QtCore import QTimer
        try:
            logger.info(f"从收藏执行单个工作流: {filepath}")
            # 查找或导入工作流（避免重复打开）
            task_id = self._open_workflow_reference(filepath)
            if task_id is not None:
                logger.info(f"单个工作流准备执行，任务ID: {task_id}")
                # 只启动这一个任务，不启动其他任务
                QTimer.singleShot(100, lambda: self._execute_single_task(task_id))
            else:
                logger.warning(f"工作流打开失败: {filepath}")
        except Exception as e:
            logger.error(f"执行收藏工作流失败: {e}")
    def _has_favorites_workflow_config(self) -> bool:
        """是否存在收藏工作流配置（即使当前未勾选任何项）"""
        try:
            from utils.app_paths import get_favorites_path
            favorites_path = get_favorites_path()
            if not os.path.exists(favorites_path):
                return False
            workspaces, favorites, changed = load_workspace_favorites_snapshot(favorites_path)
            if changed:
                save_workspace_favorites_snapshot(favorites_path, workspaces, favorites)
            return bool(workspaces or favorites)
        except Exception:
            return False
    def _refresh_open_workflow_gallery_dir(self, filepath: str, gallery_dir: str, workflow_data: dict | None = None) -> None:
        """同步已打开工作流的图库目录与缓存元数据。"""
        task = self.task_manager.find_task_by_filepath(filepath)
        if not task:
            return
        if isinstance(workflow_data, dict):
            task.workflow_data = workflow_data
        task.images_dir = get_effective_workflow_images_dir(
            task.workflow_data,
            getattr(self, 'images_dir', ''),
        )
        workflow_view = self.workflow_tab_widget.task_views.get(task.task_id)
        if workflow_view is not None:
            workflow_view.images_dir = task.images_dir
            metadata = task.workflow_data.get('metadata') if isinstance(task.workflow_data, dict) else {}
            workflow_view.workflow_metadata = dict(metadata) if isinstance(metadata, dict) else {}
        current_task_id = self.workflow_tab_widget.get_current_task_id() if self.workflow_tab_widget else None
        if current_task_id != task.task_id:
            return
        if hasattr(self, 'parameter_panel') and self.parameter_panel:
            self.parameter_panel.images_dir = task.images_dir
