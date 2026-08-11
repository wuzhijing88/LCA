import logging

from PySide6.QtCore import QTimer

logger = logging.getLogger(__name__)


class MainWindowFavoritesBatchMixin:
    def _process_favorites_open_queue(self):

        """分帧打开收藏工作流，避免阻塞UI。"""

        try:

            queue = getattr(self, '_favorites_open_queue', None)

            if not queue:

                total = getattr(self, '_favorites_open_success', 0) + getattr(self, '_favorites_open_failed', 0)

                first_task_id = getattr(self, '_favorites_open_first_task_id', None)

                if first_task_id is not None and hasattr(self, 'workflow_tab_widget') and self.workflow_tab_widget:

                    current_index = self.workflow_tab_widget.currentIndex()

                    plus_index = self.workflow_tab_widget.count() - 1

                    if current_index == plus_index or current_index not in self.workflow_tab_widget.tab_to_task:

                        tab_index = self.workflow_tab_widget.task_to_tab.get(first_task_id)

                        if tab_index is not None:

                            self.workflow_tab_widget.setCurrentIndex(tab_index)

                return

            filepath = queue.pop(0)

            task_id = self._open_workflow_reference(filepath, switch_to_tab=False)

            if task_id is not None:

                task = self.task_manager.get_task(task_id)

                if (

                    getattr(self, '_favorites_open_first_task_id', None) is None

                    and task is not None

                    and not getattr(task, 'read_only_mode', False)

                ):

                    self._favorites_open_first_task_id = task_id

                self._favorites_open_success = getattr(self, '_favorites_open_success', 0) + 1

            else:

                self._favorites_open_failed = getattr(self, '_favorites_open_failed', 0) + 1

            QTimer.singleShot(0, self._process_favorites_open_queue)

        except Exception as e:

            self._favorites_open_failed = getattr(self, '_favorites_open_failed', 0) + 1

            logger.error(f"分帧打开收藏工作流失败: {e}")

            QTimer.singleShot(0, self._process_favorites_open_queue)

    def _on_batch_workflow_execute(self, filepaths: list):

        """Run checked favorite workflows sequentially."""

        try:

            logger.info(f"Batch workflow execute: count={len(filepaths)}")

            if not filepaths:

                return

            self._reset_all_workflow_card_states("Reset card states before batch execute")

            logger.info("Auto-save and backup workflows before batch execute")

            all_tasks = self.task_manager.get_all_tasks()

            saved_count = 0

            current_task_id = None

            if hasattr(self, 'workflow_tab_widget') and self.workflow_tab_widget:

                current_task_id = self.workflow_tab_widget.get_current_task_id()

            for task in all_tasks:

                if getattr(task, 'read_only_mode', False):

                    continue

                workflow_view = self.workflow_tab_widget.task_views.get(task.task_id)

                latest_workflow_data = None

                if workflow_view:

                    logger.info(f"Fetch latest workflow data from canvas: {task.name}")

                    variables_override = self._resolve_variables_override(task, current_task_id)

                    latest_workflow_data = workflow_view.serialize_workflow(variables_override=variables_override)

                    if latest_workflow_data:

                        task.workflow_data = latest_workflow_data

                        logger.info(f"  Task '{task.name}' workflow_data refreshed")

                if task.save_and_backup(workflow_data=latest_workflow_data):

                    saved_count += 1

                    self.workflow_tab_widget._update_tab_status(task.task_id)

            logger.info(f"Saved and backed up {saved_count}/{len(all_tasks)} tasks before batch execute")

            resolved_queue = list(filepaths)

            self._batch_execute_queue = list(resolved_queue)

            self._batch_execute_index = 0

            self._is_jumping = False

            self._execute_next_batch_workflow()

            self._set_toolbar_to_stop_state()

            if self._random_pause_enabled:

                self._start_random_pause_cycle()

                logger.info("[random pause] started during batch execute")

            if hasattr(self, '_floating_controller') and self._floating_controller:

                self._floating_controller.on_workflow_started()

        except Exception as e:

            logger.error(f"批量工作流执行失败：{e}")

    def _finish_batch_execute(self, success: bool = True, message: str = "Batch execute completed"):

        """Finish favorites batch execute and restore UI state."""

        self._batch_execute_queue = []

        self._batch_execute_index = 0

        self._is_jumping = False

        self._reset_run_button()

        if hasattr(self, '_floating_controller') and self._floating_controller:

            self._floating_controller.on_workflow_finished(success, message)

    def _execute_next_batch_workflow(self):

        """Execute the next workflow in the batch queue."""

        if not hasattr(self, '_batch_execute_queue') or not self._batch_execute_queue:

            logger.info("Batch queue is empty, execution finished")

            self._finish_batch_execute(True, "Batch execute completed")

            return

        if self._batch_execute_index >= len(self._batch_execute_queue):

            logger.info("Batch execute completed")

            self._finish_batch_execute(True, "Batch execute completed")

            return

        filepath = self._batch_execute_queue[self._batch_execute_index]

        self._batch_execute_index += 1

        logger.info(f"Batch execute [{self._batch_execute_index}/{len(self._batch_execute_queue)}]: {filepath}")

        task = self.task_manager.find_task_by_filepath(filepath)

        if not task:

            logger.warning(f"未找到工作流任务：{filepath}")

            QTimer.singleShot(100, self._execute_next_batch_workflow)

            return

        def on_finished(success, msg, reason, t=task):

            try:

                t.execution_finished.disconnect(on_finished)

            except Exception:

                pass

            QTimer.singleShot(500, self._execute_next_batch_workflow)

        task.execution_finished.connect(on_finished)

        tab_index = self.workflow_tab_widget.task_to_tab.get(task.task_id)

        if tab_index is not None and not getattr(task, 'read_only_mode', False):

            self.workflow_tab_widget.setCurrentIndex(tab_index)

        QTimer.singleShot(100, lambda: task.execute_async())
