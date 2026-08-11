from ..workflow_parts import workflow_lifecycle as _wl

QMessageBox = _wl.QMessageBox
logger = _wl.logger


MSG_START_FAIL_TITLE = "\u542f\u52a8\u5931\u8d25"
MSG_START_FAIL_TEXT = "\u4efb\u52a1\u672a\u80fd\u542f\u52a8\uff0c\u8bf7\u91cd\u8bd5\u3002"


def execute_main_window_start(
    ctx,
    executable_count,
    claim_task_start_state,
    resolve_current_canvas_task_id,
    task_state_manager,
    start_state,
):
    self = ctx

    logger.info('start executable tasks: count=%s', executable_count)

    current_task_id = resolve_current_canvas_task_id()
    if current_task_id is not None:
        logger.info('current selected task id=%s', current_task_id)
    else:
        logger.warning('解析当前选中任务 ID 失败')

    self._reset_all_workflow_card_states("\u542f\u52a8\u4efb\u52a1\u524d\u6e05\u9664\u6240\u6709\u5361\u7247\u7684\u6267\u884c\u72b6\u6001\u989c\u8272")

    if not claim_task_start_state():
        self._reset_run_button()
        return

    started_ok = self.task_manager.execute_all(current_task_id)
    if not started_ok:
        self._reset_run_button()
        if task_state_manager:
            try:
                task_state_manager.confirm_stopped()
            except Exception:
                pass
        start_state['task_state_claimed'] = False
        error_message = MSG_START_FAIL_TEXT
        try:
            detailed_error = self.task_manager.get_last_execute_error_message()
            if detailed_error:
                error_message = detailed_error
        except Exception:
            pass
        QMessageBox.warning(self, MSG_START_FAIL_TITLE, error_message)
        return

    try:
        executing_ids = list(getattr(self.task_manager, '_executing_task_ids', []) or [])
        active_task_id = executing_ids[0] if executing_ids else current_task_id
        self._active_execution_task_id = active_task_id
        self._runtime_pause_owner = 'task_manager'
        self._runtime_stop_owner = 'task_manager'
        if active_task_id is not None:
            logger.info('active execution task id=%s', active_task_id)
    except Exception as active_task_err:
        logger.warning('设置当前执行任务 ID 失败：%s', active_task_err)

    if task_state_manager:
        task_state_manager.confirm_started()
        logger.info('task_state_manager confirmed running')

    start_state['workflow_started'] = True

    if self._random_pause_enabled:
        self._start_random_pause_cycle()
        logger.info('random pause timer started with workflow')

    if getattr(self, '_timed_pause_enabled', False):
        self._start_timed_pause_timer()
        logger.info('timed pause timer started with workflow')

    self._start_window_monitor()
    self._set_toolbar_to_stop_state()
