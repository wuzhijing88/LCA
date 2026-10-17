import logging
import os
import time
from typing import List

from PySide6.QtCore import QTimer

from task_workflow.workspace import (
    apply_updated_workflow_resource_dir,
    extract_workflow_resource_path,
    favorite_path_key,
    load_workspace_favorites_snapshot,
    resolve_existing_workflow_path,
    resource_runtime_kwargs,
    save_workspace_favorites_snapshot,
)

logger = logging.getLogger(__name__)
startup_logger = logging.getLogger("workflow.startup")


class MainWindowFavoritesMixin:
    def _sync_favorite_path_after_save(self, old_filepath: str, task) -> None:
        """JSON 转 LCA 后同步工作区收藏路径。"""
        new_filepath = str(getattr(task, "filepath", "") or "")
        if not old_filepath or not new_filepath:
            return
        if favorite_path_key(old_filepath) == favorite_path_key(new_filepath):
            return
        panel = getattr(self, "parameter_panel", None)
        if panel is not None and hasattr(panel, "update_favorite_entry"):
            panel.update_favorite_entry(old_filepath, new_filepath, getattr(task, "name", None))

    def _on_favorite_workflow_check_changed(self, filepath: str, checked: bool):
        """处理收藏勾选状态变化。

        取消勾选等于关闭该工作流标签：有未保存更改时同样要问用户（保存 / 放弃 / 取消），
        不能因为是从收藏列表关的就静默丢掉正在编辑的步骤。用户取消时标签保留，勾选状态恢复。
        """
        try:
            if checked:
                self._open_workflow_reference(filepath)
                return
            task = self.task_manager.find_task_by_filepath(filepath)
            if task is None:
                return
            tab_index = self.workflow_tab_widget.task_to_tab.get(task.task_id)
            if tab_index is None:
                return
            if not self.workflow_tab_widget.close_tab(tab_index):
                logger.info("收藏取消勾选时用户保留了工作流标签，恢复勾选: %s", filepath)
                self._restore_favorite_checked(filepath)
        except Exception:
            logger.exception("同步收藏工作流勾选状态失败: %s", filepath)

    def _restore_favorite_checked(self, filepath: str) -> None:
        panel = getattr(self, "parameter_panel", None)
        if panel is not None and hasattr(panel, "set_favorite_checked"):
            panel.set_favorite_checked(filepath, True)
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
                self._start_startup_workflow_load(favorite_filepaths, favorites=True)
                return
            else:
                recent_filepaths = self.workflow_tab_widget.load_recent_workflows()
                self._start_startup_workflow_load(recent_filepaths, favorites=False)
        except Exception as e:
            logger.error(f"自动加载工作流时出错: {e}")
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(self, "自动加载失败", str(e))

    def _start_startup_workflow_load(self, filepaths: List[str], *, favorites: bool) -> None:
        """把启动工作流加载拆成多个事件循环片段，避免资源解包阻塞窗口消息。"""
        queue = [str(filepath).strip() for filepath in filepaths if str(filepath).strip()]
        if not queue:
            self._finish_startup_workflow_load()
            return

        self._startup_workflow_load_queue = queue
        self._startup_workflow_load_favorites = bool(favorites)
        self._startup_workflow_load_total = len(queue)
        self._startup_workflow_load_completed = 0
        self._startup_workflow_load_first_task_id = None
        self._startup_workflow_load_failed = []
        self.workflow_tab_widget._is_auto_loading = True

        timer = getattr(self, "_startup_workflow_load_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._load_next_startup_workflow)
            self._startup_workflow_load_timer = timer
        elif timer.isActive():
            timer.stop()
        startup_logger.info(
            "启动工作流加载已分帧：数量=%s，来源=%s",
            len(queue),
            "收藏" if favorites else "最近记录",
        )
        timer.start(0)

    def _load_next_startup_workflow(self) -> None:
        queue = getattr(self, "_startup_workflow_load_queue", None)
        if not queue:
            self._finish_startup_workflow_load()
            return

        filepath = queue.pop(0)
        index = getattr(self, "_startup_workflow_load_total", 0) - len(queue)
        started_at = time.perf_counter()
        task_id = None
        try:
            if getattr(self, "_startup_workflow_load_favorites", False):
                task_id = self._open_workflow_reference(filepath, switch_to_tab=False)
            else:
                task_id = self.workflow_tab_widget.import_workflow(filepath, activate_tab=True)
            if task_id is None:
                self._startup_workflow_load_failed.append(filepath)
            elif (
                getattr(self, "_startup_workflow_load_favorites", False)
                and getattr(self, "_startup_workflow_load_first_task_id", None) is None
            ):
                self._startup_workflow_load_first_task_id = task_id
        except Exception as exc:
            self._startup_workflow_load_failed.append(filepath)
            logger.error("启动加载工作流失败: %s", filepath, exc_info=True)
            self._startup_workflow_load_error = exc
        finally:
            self._startup_workflow_load_completed = index
            elapsed = time.perf_counter() - started_at
            startup_logger.info(
                "启动工作流加载进度：%s/%s，耗时 %.3f 秒，文件=%s",
                index,
                getattr(self, "_startup_workflow_load_total", index),
                elapsed,
                filepath,
            )

        timer = getattr(self, "_startup_workflow_load_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
        if queue:
            if timer is not None:
                timer.start(0)
        else:
            self._finish_startup_workflow_load()

    def _finish_startup_workflow_load(self) -> None:
        timer = getattr(self, "_startup_workflow_load_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()

        workflow_tab_widget = getattr(self, "workflow_tab_widget", None)
        if workflow_tab_widget is not None:
            workflow_tab_widget._is_auto_loading = False

        first_task_id = getattr(self, "_startup_workflow_load_first_task_id", None)
        if first_task_id is not None and workflow_tab_widget is not None:
            tab_index = workflow_tab_widget.task_to_tab.get(first_task_id)
            if tab_index is not None:
                workflow_tab_widget.setCurrentIndex(tab_index)

        failed = list(getattr(self, "_startup_workflow_load_failed", []))
        if failed:
            logger.warning("启动工作流加载完成，但有 %s 个文件失败: %s", len(failed), failed)

        # 应用画布网格设置
        if workflow_tab_widget is not None:
            workflow_tab_widget.set_all_grid_enabled(self.config.get('enable_canvas_grid', True))
            workflow_tab_widget.set_all_card_snap_enabled(self.config.get('enable_card_snap', True))
        if hasattr(self, 'parameter_panel') and self.parameter_panel:
            self.parameter_panel.set_snap_to_parent_enabled(
                self.config.get('enable_parameter_panel_snap', True)
            )
        self._offer_workspace_if_missing()
        self._startup_workflow_load_queue = []

    def _cancel_startup_workflow_load(self) -> None:
        """关闭主窗口时停止尚未执行的启动加载计时器。"""
        timer = getattr(self, "_startup_workflow_load_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                pass
        workflow_tab_widget = getattr(self, "workflow_tab_widget", None)
        if workflow_tab_widget is not None:
            workflow_tab_widget._is_auto_loading = False
        self._startup_workflow_load_queue = []

    def _load_checked_favorite_workflow_paths(self) -> List[str]:
        """读取收藏配置中勾选的工作流标识（去重后保持原顺序）。"""
        try:
            from utils.app_paths import get_favorites_path
            favorites_path = get_favorites_path()
            if not os.path.exists(favorites_path):
                return []
            workspaces, favorites, excluded_paths, extra_paths, changed = load_workspace_favorites_snapshot(
                favorites_path,
                rebuild=False,
            )
            if changed:
                save_workspace_favorites_snapshot(
                    favorites_path,
                    workspaces,
                    favorites,
                    excluded_paths=excluded_paths,
                    extra_paths=extra_paths,
                )
            checked_paths: List[str] = []
            for item in favorites:
                if not isinstance(item, dict):
                    continue
                if not bool(item.get('checked', False)):
                    continue
                raw_path = str(item.get('filepath') or '').strip()
                if not raw_path:
                    continue
                resolved = resolve_existing_workflow_path(raw_path)
                if resolved and os.path.exists(resolved):
                    checked_paths.append(resolved)
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
                    from themes import theme_color

                    self._set_step_detail_style(text_color=theme_color("error", "#e81123"))
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
            workspaces, favorites, excluded_paths, extra_paths, changed = load_workspace_favorites_snapshot(
                favorites_path,
                rebuild=False,
            )
            if changed:
                save_workspace_favorites_snapshot(
                    favorites_path,
                    workspaces,
                    favorites,
                    excluded_paths=excluded_paths,
                    extra_paths=extra_paths,
                )
            return bool(workspaces or favorites or extra_paths)
        except Exception:
            return False
    def _refresh_open_workflow_resource_dir(self, filepath: str, resource_dir: str, workflow_data: dict | None = None) -> None:
        """按文件路径同步已打开工作流的资源目录。"""
        task = self.task_manager.find_task_by_filepath(filepath)
        if not task:
            return
        self._sync_open_task_resource_state(task, resource_dir, workflow_data)

    def _sync_saved_task_resources(self, task, workflow_data: dict | None = None) -> None:
        data = workflow_data if isinstance(workflow_data, dict) else getattr(task, "workflow_data", None)
        resource_dir = extract_workflow_resource_path(data) if isinstance(data, dict) else ""
        self._sync_open_task_resource_state(
            task,
            resource_dir,
            data if isinstance(data, dict) else None,
        )

    def _sync_open_task_resource_state(self, task, resource_dir: str = "", workflow_data: dict | None = None) -> None:
        """把打开中的任务切到当前工程资源目录：目录、会话、缓存、面板、脚本资源栏。"""
        resource_dirs = apply_updated_workflow_resource_dir(
            task,
            resource_dir,
            workflow_data,
            getattr(self, "images_dir", "") or "",
        )
        self._reload_open_task_lca_session(task, str(getattr(task, "filepath", "") or ""))
        try:
            from utils.image_paths import get_image_path_resolver

            get_image_path_resolver().clear_cache()
        except Exception:
            logger.debug("清除图片路径缓存失败", exc_info=True)
        workflow_view = None
        if getattr(self, "workflow_tab_widget", None):
            workflow_view = self.workflow_tab_widget.task_views.get(task.task_id)
        if workflow_view is not None:
            workflow_view.images_dir = task.images_dir
            metadata = task.workflow_data.get("metadata") if isinstance(task.workflow_data, dict) else {}
            workflow_view.workflow_metadata = dict(metadata) if isinstance(metadata, dict) else {}
        self._rebind_script_editors_for_task(task, resource_dirs)
        current_task_id = None
        if getattr(self, "workflow_tab_widget", None):
            current_task_id = self.workflow_tab_widget.get_current_task_id()
        if current_task_id == task.task_id:
            self._bind_current_workflow_resource_dirs(task)
        else:
            self._bind_current_workflow_resource_dirs()

    def _reload_open_task_lca_session(self, task, filepath: str) -> None:
        from app_core.lca_format.project_io import is_lca_path, load_lca_project
        from app_core.lca_format.session import (
            activate,
            clear_path,
            deactivate,
            get_active,
            get_active_path,
            get_for_path,
            register,
        )

        old_path = str(getattr(task, "lca_session_path", "") or "").strip()
        was_active = False
        try:
            active = get_active()
            was_active = active is getattr(task, "lca_session", None)
            if not was_active and old_path:
                active_path = get_active_path()
                was_active = bool(active_path) and os.path.normcase(
                    os.path.abspath(old_path)
                ) == os.path.normcase(os.path.abspath(active_path))
        except Exception:
            was_active = False
        current_id = None
        if getattr(self, "workflow_tab_widget", None):
            current_id = self.workflow_tab_widget.get_current_task_id()
        should_activate = was_active or current_id == getattr(task, "task_id", None)
        if str(filepath).startswith("memory://"):
            session = get_for_path(old_path) if old_path else None
            if session is None:
                raise RuntimeError("子工作流工程会话未注册，无法刷新资源")
            task.lca_session = session
            tabs = getattr(self, "workflow_tab_widget", None)
            if tabs is not None:
                tabs._sync_host_package_session(task)
            if should_activate:
                activate(old_path)
            return
        if is_lca_path(filepath) and os.path.isfile(filepath):
            try:
                session = get_for_path(filepath)
                if session is None or not session.matches_source(filepath):
                    if session is not None:
                        clear_path(filepath)
                    _payload, session = load_lca_project(filepath)
                    register(filepath, session)
                task.lca_session = session
                task.lca_session_path = os.path.abspath(filepath)
                if should_activate:
                    activate(filepath)
            except Exception:
                logger.warning("重新加载工作流工程会话失败: %s", filepath, exc_info=True)
            if (
                old_path
                and os.path.normcase(os.path.abspath(old_path))
                != os.path.normcase(os.path.abspath(filepath))
            ):
                clear_path(old_path)
            return
        task.lca_session = None
        task.lca_session_path = ""
        if old_path:
            clear_path(old_path)
            if should_activate:
                deactivate()

    def _rebind_script_editors_for_task(self, task, dirs) -> None:
        editors = getattr(self, "_script_editors", None)
        if not editors:
            return
        card_ids = set()
        data = getattr(task, "workflow_data", None)
        if isinstance(data, dict):
            for card in data.get("cards") or []:
                if isinstance(card, dict) and isinstance(card.get("id"), int):
                    card_ids.add(card["id"])
        if getattr(self, "workflow_tab_widget", None):
            view = self.workflow_tab_widget.task_views.get(task.task_id)
            if view is not None:
                card_ids.update(getattr(view, "cards", {}).keys())
        kwargs = resource_runtime_kwargs(dirs)
        for card_id, editor in list(editors.items()):
            if card_id not in card_ids:
                continue
            panel = getattr(editor, "_resource_panel", None)
            if panel is None or not hasattr(panel, "bind"):
                continue
            token = ""
            try:
                from ui.dialogs.script_capture import _workflow_token_of

                token = _workflow_token_of(editor)
            except Exception:
                token = ""
            try:
                panel.bind(
                    kwargs.get("images_dir") or "",
                    card_id,
                    token,
                    kwargs.get("sounds_dir") or "",
                    dicts_dir=kwargs.get("dicts_dir") or "",
                    yolo_dir=kwargs.get("yolo_dir") or "",
                    replays_dir=kwargs.get("replays_dir") or "",
                    plugins_dir=kwargs.get("plugins_dir") or "",
                )
                source = ""
                if hasattr(editor, "editor"):
                    source = str(editor.editor.toPlainText() or "")
                panel.set_source(source)
            except Exception:
                logger.debug("刷新脚本资源栏失败: card_id=%s", card_id, exc_info=True)
