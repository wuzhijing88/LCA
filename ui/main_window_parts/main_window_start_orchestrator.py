from ..workflow_parts import workflow_lifecycle as _wl
from .main_window_start_execution import execute_main_window_start
from .main_window_start_prepare import (
    prepare_main_window_runtime_environment,
    prepare_main_window_start,
    save_main_window_tasks_before_start,
)

QMessageBox = _wl.QMessageBox
cancel_ocr_cleanup_timer = _wl.cancel_ocr_cleanup_timer
logger = _wl.logger


MSG_START_FAIL_TITLE = "\u542f\u52a8\u5931\u8d25"
MSG_START_ERROR_TEXT = "\u542f\u52a8\u4efb\u52a1\u65f6\u53d1\u751f\u9519\u8bef"


def main_window_safe_start_tasks(ctx, reset_jump_cancel=True):
    self = ctx
    logger.info('received safe start request')

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
        )
    except Exception as exc:
        logger.error('安全启动流程失败：%s', exc)
        import traceback
        logger.error(traceback.format_exc())
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
