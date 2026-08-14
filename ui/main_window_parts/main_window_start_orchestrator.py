import logging

from PySide6.QtWidgets import QMessageBox

from ..workflow_parts.workflow_lifecycle import cancel_ocr_cleanup_timer
from .main_window_start_execution import execute_main_window_start
from .main_window_start_prepare import (
    prepare_main_window_runtime_environment,
    prepare_main_window_start,
    save_main_window_tasks_before_start,
)

logger = logging.getLogger(__name__)


MSG_START_FAIL_TITLE = "\u542f\u52a8\u5931\u8d25"
MSG_START_ERROR_TEXT = "\u542f\u52a8\u4efb\u52a1\u65f6\u53d1\u751f\u9519\u8bef"


def _has_runtime_that_blocks_start(ctx) -> bool:
    if bool(getattr(ctx, '_is_stopping_tasks', False)):
        return True

    task_state_manager = getattr(ctx, 'task_state_manager', None)
    if task_state_manager is not None:
        try:
            if str(task_state_manager.get_current_state()).strip().lower() in {
                'starting',
                'running',
                'stopping',
                'paused',
            }:
                return True
        except Exception:
            return True

    task_manager = getattr(ctx, 'task_manager', None)
    if task_manager is not None:
        try:
            tasks = task_manager.get_all_tasks()
        except Exception:
            return True
        for task in tasks:
            executor = getattr(task, 'executor', None)
            thread_ref = getattr(task, 'executor_thread', None)
            task_status = str(getattr(task, 'status', '') or '').strip().lower()
            if task_status in {'starting', 'running', 'paused', 'stopping'}:
                return True
            if executor is not None or thread_ref is not None:
                # 终态到资源清理完成之间仍属于旧运行周期，禁止新启动。
                return True

    for owner_name in ('multi_executor', 'executor'):
        runtime = getattr(ctx, owner_name, None)
        if runtime is None:
            continue
        try:
            if bool(getattr(runtime, '_paused', False)):
                return True
            state_getter = getattr(runtime, 'get_pause_state', None)
            if callable(state_getter):
                runtime_state = str(state_getter()).strip().lower()
                if runtime_state in {'running', 'paused'}:
                    return True
            running_getter = getattr(runtime, 'is_running', None)
            if callable(running_getter) and bool(running_getter()):
                return True
        except Exception:
            return True

    return False


def main_window_safe_start_tasks(ctx, reset_jump_cancel=True, interactive=True):
    self = ctx
    logger.info('received safe start request')

    if _has_runtime_that_blocks_start(self):
        logger.debug('start request rejected because a runtime is starting, running, paused, or stopping')
        return

    try:
        cancel_ocr_cleanup_timer(
            getattr(self, 'task_state_manager', None),
            success_log='[OCR cleanup] cancel delayed cleanup timer when start requested',
        )
    except Exception as exc:
        logger.warning('[OCR 清理] 取消延迟清理定时器失败：%s', exc)

    if hasattr(self, 'parameter_panel') and self.parameter_panel.is_panel_open():
        logger.warning('parameter panel is open before start; apply and close it')
        self.parameter_panel.apply_and_close()

    if not hasattr(self, '_is_starting_tasks'):
        self._is_starting_tasks = False

    if self._is_starting_tasks:
        logger.warning('start request ignored because start flow is already running')
        return

    self._is_starting_tasks = True
    task_state_manager = getattr(self, 'task_state_manager', None)
    start_state = {
        'task_state_claimed': False,
        'workflow_started': False,
    }

    def _claim_task_start_state() -> bool:
        if start_state['task_state_claimed']:
            return True
        if not task_state_manager:
            return True
        try:
            accepted = bool(task_state_manager.request_start())
        except Exception as claim_err:
            logger.warning('task_state_manager.request_start 失败：%s', claim_err)
            return False
        if not accepted:
            logger.warning('task_state_manager 拒绝了本次启动请求')
            return False
        start_state['task_state_claimed'] = True
        return True

    def _resolve_current_canvas_task_id():
        current_task_id = None
        if hasattr(self, 'workflow_tab_widget') and self.workflow_tab_widget:
            current_task_id = self.workflow_tab_widget.get_current_task_id()
            if current_task_id is None:
                try:
                    current_view = self.workflow_tab_widget.get_current_workflow_view()
                    if current_view is not None:
                        for mapped_task_id, view in self.workflow_tab_widget.task_views.items():
                            if view == current_view:
                                current_task_id = mapped_task_id
                                break
                except Exception:
                    pass
        return current_task_id

    try:
        prepare_result = prepare_main_window_start(
            self,
            reset_jump_cancel,
            _claim_task_start_state,
            _resolve_current_canvas_task_id,
            task_state_manager,
            start_state,
            interactive=interactive,
        )
        if prepare_result.get('should_return'):
            return

        all_tasks = prepare_result['all_tasks']
        executable_count = prepare_result['executable_count']

        save_main_window_tasks_before_start(self, all_tasks, _resolve_current_canvas_task_id)
        prepare_main_window_runtime_environment(self)
        execute_main_window_start(
            self,
            executable_count,
            _claim_task_start_state,
            _resolve_current_canvas_task_id,
            task_state_manager,
            start_state,
            interactive=interactive,
        )
    except Exception as exc:
        logger.error('安全启动流程失败：%s', exc)
        import traceback
        logger.error(traceback.format_exc())
        if interactive:
            QMessageBox.warning(self, MSG_START_FAIL_TITLE, f"{MSG_START_ERROR_TEXT}:\n{str(exc)}")
    finally:
        if start_state['task_state_claimed'] and (not start_state['workflow_started']) and task_state_manager:
            try:
                task_state_manager.confirm_stopped()
            except Exception:
                pass
        self._is_starting_tasks = False
        logger.debug('released start-in-progress flag')


def main_window_start_tasks(ctx):
    self = ctx
    logger.info('received legacy start request; redirect to safe_start_tasks')
    self.safe_start_tasks()
