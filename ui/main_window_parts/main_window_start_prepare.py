from ..workflow_parts import workflow_lifecycle as _wl

QMessageBox = _wl.QMessageBox
clear_stale_task_executor_refs = _wl.clear_stale_task_executor_refs
normalize_task_manager_before_start = _wl.normalize_task_manager_before_start
task_executor_thread_is_running = _wl.task_executor_thread_is_running
get_favorites_path = _wl.get_favorites_path
logger = _wl.logger
os = _wl.os


MSG_NO_EXEC_TITLE = "\u65e0\u6cd5\u6267\u884c"
MSG_NO_EXEC_TEXT = "\u6ca1\u6709\u53ef\u6267\u884c\u7684\u4efb\u52a1\uff0c\u8bf7\u5148\u5bfc\u5165\u5de5\u4f5c\u6d41"
MSG_CONFLICT_TITLE = "\u64cd\u4f5c\u51b2\u7a81"
MSG_CONFLICT_TEXT = "\u6709\u4efb\u52a1\u6b63\u5728\u6e05\u7406\u4e2d\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5\u3002"


def _resume_paused_tasks_if_needed(ctx) -> bool:
    self = ctx
    resumable_tasks = []

    for task in self.task_manager.get_executable_tasks():
        thread_ref = getattr(task, 'executor_thread', None)
        if thread_ref is None:
            continue

        if not task_executor_thread_is_running(task):
            clear_stale_task_executor_refs(task)
            if getattr(task, 'status', None) == 'paused':
                try:
                    logger.warning(
                        "task %s is marked paused but executor thread is not running; normalize to stopped before start",
                        task.task_id,
                    )
                    task.stop_reason = 'stopped'
                    task.status = 'stopped'
                except Exception as normalize_err:
                    logger.warning(
                        "failed to normalize stale paused task before start: task_id=%s, error=%s",
                        getattr(task, 'task_id', None),
                        normalize_err,
                    )
            continue

        if getattr(task, 'status', None) == 'paused':
            resumable_tasks.append(task)
            continue

        logger.warning(
            "task %s still has a live executor thread reference: status=%s",
            task.task_id,
            getattr(task, 'status', None),
        )
        QMessageBox.warning(self, MSG_CONFLICT_TITLE, MSG_CONFLICT_TEXT)
        return True

    if not resumable_tasks:
        return False

    logger.info(
        "detected paused tasks with live threads, resume instead of starting: ids=%s",
        [task.task_id for task in resumable_tasks],
    )
    self._resume_workflow()
    return True


def prepare_main_window_start(
    ctx,
    reset_jump_cancel,
    claim_task_start_state,
    resolve_current_canvas_task_id,
    task_state_manager,
    start_state,
):
    self = ctx

    if reset_jump_cancel:
        self._jump_cancelled = False
        logger.info('manual start: reset jump-cancel flag')
    else:
        logger.info('auto jump start: keep jump-cancel flag')

    normalize_task_manager_before_start(self.task_manager)

    if _resume_paused_tasks_if_needed(self):
        return {'should_return': True}

    current_canvas_task_id = resolve_current_canvas_task_id()
    current_canvas_task = self.task_manager.get_task(current_canvas_task_id) if current_canvas_task_id is not None else None

    if current_canvas_task is None:
        favorites_config_path = get_favorites_path()
        if os.path.exists(favorites_config_path):
            try:
                import json

                with open(favorites_config_path, 'r', encoding='utf-8') as handle:
                    favorites_data = json.load(handle)

                checked_favorites = [item for item in favorites_data.get('favorites', []) if item.get('checked', True)]
                if checked_favorites:
                    logger.info('start checked favorites because canvas has no task: count=%s', len(checked_favorites))
                    filepaths = [item['filepath'] for item in checked_favorites]

                    if not claim_task_start_state():
                        return {'should_return': True}

                    if task_state_manager:
                        try:
                            task_state_manager.confirm_started()
                            start_state['workflow_started'] = True
                        except Exception as state_err:
                            logger.warning('failed to confirm running state for batch start: %s', state_err)

                    self._on_batch_workflow_execute(filepaths)
                    return {'should_return': True}
            except Exception as exc:
                logger.error('failed to load favorites and batch start: %s', exc, exc_info=True)

    logger.info('fallback to executable task start flow')

    executable_count = len(self.task_manager.get_executable_tasks())
    if executable_count == 0:
        logger.warning('no executable task found before start')
        QMessageBox.warning(self, MSG_NO_EXEC_TITLE, MSG_NO_EXEC_TEXT)
        return {'should_return': True}

    if not self._check_window_binding():
        return {'should_return': True}

    logger.info('=' * 80)
    logger.info('prepare to start tasks: executable_count=%s', executable_count)
    all_tasks = self.task_manager.get_all_tasks()
    logger.info('all task count=%s', len(all_tasks))
    for index, task in enumerate(all_tasks, 1):
        logger.info(
            "  task%s: id=%s, name='%s', enabled=%s, status='%s', can_execute=%s",
            index,
            task.task_id,
            task.name,
            task.enabled,
            task.status,
            task.can_execute(),
        )
    logger.info('=' * 80)

    return {
        'should_return': False,
        'all_tasks': all_tasks,
        'executable_count': executable_count,
    }


def save_main_window_tasks_before_start(ctx, all_tasks, resolve_current_canvas_task_id):
    self = ctx

    logger.info('save and backup tasks before start: total=%s', len(all_tasks))
    saved_count = 0
    backup_failed_tasks = []
    current_task_id = resolve_current_canvas_task_id()

    from task_workflow.workflow_vars import pick_variables_override

    for task in all_tasks:
        workflow_view = self.workflow_tab_widget.task_views.get(task.task_id)
        latest_workflow_data = None

        if workflow_view:
            logger.info('serialize latest workflow data from canvas: %s', task.name)
            variables_override = pick_variables_override(
                target_task_id=task.task_id,
                current_task_id=current_task_id,
                task_workflow_data=task.workflow_data,
            )
            latest_workflow_data = workflow_view.serialize_workflow(variables_override=variables_override)

            if latest_workflow_data:
                task.workflow_data = latest_workflow_data
                logger.info("task '%s' workflow_data refreshed before start", task.name)
        else:
            logger.warning("workflow view missing for task '%s'; keep existing workflow data", task.name)

        if task.save_and_backup(workflow_data=latest_workflow_data):
            saved_count += 1
            self.workflow_tab_widget._update_tab_status(task.task_id)
        else:
            backup_failed_tasks.append(task.name)
            logger.warning("任务 '%s' 保存或备份失败", task.name)

    logger.info('saved and backed up tasks: %s/%s', saved_count, len(all_tasks))
    if backup_failed_tasks:
        logger.warning('部分任务保存或备份失败，但执行将继续：%s', ', '.join(backup_failed_tasks))


def prepare_main_window_runtime_environment(ctx):
    self = ctx

    for task in self.task_manager.get_executable_tasks():
        logger.info(
            "pre-start binding check for task '%s': target_hwnd=%s, target_window_title='%s'",
            task.name,
            task.target_hwnd,
            task.target_window_title,
        )
        self._update_task_window_binding(task)

    try:
        from utils.input_simulation import global_input_simulator_manager

        global_input_simulator_manager.clear_cache()
        logger.debug('cleared input simulator cache before start')

        from utils.foreground_input_manager import get_foreground_input_manager

        foreground_input = get_foreground_input_manager()
        foreground_input._initialization_attempted = False
        logger.debug('reset foreground input manager init flag before start')
    except Exception as exc:
        logger.warning('failed to clear pre-start runtime state: %s', exc)
