import logging







import json







import os







from utils.app_paths import get_favorites_path







from PySide6.QtCore import QTimer







from PySide6.QtWidgets import QMessageBox















logger = logging.getLogger(__name__)















# Centralized task lifecycle helpers for main window and control center.























_OCR_TASK_TYPES = {







    "OCR文字识别",







    "字库识别",







    "ocr_region_recognition",







    "dict_ocr_task",







}























def _is_valid_window_handle(hwnd) -> bool:







    """校验窗口句柄是否真实可用。"""







    try:







        hwnd_int = int(hwnd)







    except (TypeError, ValueError):







        return False







    if hwnd_int <= 0:







        return False







    try:







        import win32gui







    except Exception:







        return False







    try:







        return bool(win32gui.IsWindow(hwnd_int))







    except Exception:







        return False























def is_valid_window_handle(hwnd) -> bool:
    return _is_valid_window_handle(hwnd)


def _workflow_uses_ocr(workflow_data) -> bool:







    """判断工作流是否包含 OCR 任务。"""







    if not isinstance(workflow_data, dict):







        return False







    cards = workflow_data.get("cards")







    if not isinstance(cards, list):







        return False







    for card in cards:







        if not isinstance(card, dict):







            continue







        task_type = str(card.get("task_type") or "").strip()







        if task_type in _OCR_TASK_TYPES:







            return True







    return False






































def workflow_uses_ocr(workflow_data) -> bool:
    return _workflow_uses_ocr(workflow_data)


def _get_main_window_task_state_manager():







    try:







        from PySide6.QtWidgets import QApplication







        app = QApplication.instance()







        if not app:







            return None







        for widget in app.topLevelWidgets():







            if hasattr(widget, 'task_state_manager') and widget.task_state_manager:







                return widget.task_state_manager







    except Exception as e:







        logger.warning(f"获取主窗口task_state_manager失败: {e}")







    return None























def get_main_window_task_state_manager():
    return _get_main_window_task_state_manager()


def _cancel_ocr_cleanup_timer(task_state_manager, success_log=None, log_message_cb=None):







    if not task_state_manager:







        return







    task_state_manager._ocr_cleanup_cancelled = True







    timer = getattr(task_state_manager, '_ocr_cleanup_timer', None)







    if timer is None:







        return







    try:







        if timer.isActive():







            timer.stop()







        try:







            timer.timeout.disconnect()







        except Exception:







            pass







        timer.deleteLater()







        if success_log:







            logger.info(success_log)







        if log_message_cb:







            log_message_cb("已取消OCR延迟清理")







    except Exception as timer_err:







        logger.warning(f"[OCR延迟清理] 清理定时器失败: {timer_err}")







    finally:







        task_state_manager._ocr_cleanup_timer = None























def cancel_ocr_cleanup_timer(task_state_manager, success_log=None, log_message_cb=None):
    return _cancel_ocr_cleanup_timer(
        task_state_manager,
        success_log=success_log,
        log_message_cb=log_message_cb,
    )


def _confirm_ocr_cleanup(task_state_manager, success_log=None, log_message_cb=None, suppress_errors=False):







    if not task_state_manager:







        return False







    try:







        task_state_manager.confirm_stopped()







    except Exception as e:







        if suppress_errors:







            logger.warning(f"启动OCR延迟清理失败: {e}")







            return False







        raise







    if success_log:







        logger.info(success_log)







    if log_message_cb:







        log_message_cb("已启动OCR延迟清理（30秒）")







    return True























def confirm_ocr_cleanup(task_state_manager, success_log=None, log_message_cb=None, suppress_errors=False):
    return _confirm_ocr_cleanup(
        task_state_manager,
        success_log=success_log,
        log_message_cb=log_message_cb,
        suppress_errors=suppress_errors,
    )


def _request_executor_stop(executor) -> bool:







    if not executor:







        return False







    request_stop = getattr(executor, "request_stop", None)







    if not callable(request_stop):







        return False







    try:







        request_stop(force=True)







    except TypeError:







        request_stop()







    return True























def _release_input_drivers() -> None:







    """停止时主动释放输入驱动，避免正在执行的驱动请求长时间阻塞。"""







    try:







        from utils.foreground_input_manager import get_foreground_input_manager







        manager = get_foreground_input_manager()







        if manager:







            release_fn = getattr(manager, "release_all_inputs", None)







            if callable(release_fn):







                try:







                    release_fn()







                except Exception:







                    pass







            manager.close()







    except Exception:







        pass















    try:







        from utils.input_simulation.factory import global_input_simulator_manager







        global_input_simulator_manager.clear_cache()







    except Exception:







        pass























def release_input_drivers() -> None:
    _release_input_drivers()


def _stop_legacy_executor(ctx) -> bool:







    """停止主窗口旧执行器链路（self.executor/self.executor_thread）。"""







    self = ctx







    stopped = False















    try:







        if _request_executor_stop(getattr(self, "executor", None)):







            stopped = True







    except Exception:







        pass















    thread = getattr(self, "executor_thread", None)







    if thread is not None:







        try:







            thread_running = bool(thread.isRunning())







        except Exception:







            thread_running = False















        if thread_running:







            try:







                if hasattr(thread, "requestInterruption"):







                    thread.requestInterruption()







            except Exception:







                pass







            try:







                thread.quit()







            except Exception:







                pass







            stopped = True















    return stopped























def _stop_multi_executor(ctx) -> bool:







    """停止多窗口执行器链路（self.multi_executor）。"""







    self = ctx







    multi_executor = getattr(self, "multi_executor", None)







    if not multi_executor:







        return False















    try:







        stop_all = getattr(multi_executor, "stop_all", None)







        if callable(stop_all):







            stop_all()







            return True















        request_stop = getattr(multi_executor, "request_stop", None)







        if callable(request_stop):







            try:
                request_stop(force=True)
            except TypeError:
                request_stop()







            return True







    except Exception:







        return False















    return False























def _task_executor_thread_is_running(task):







    """返回任务执行线程是否仍处于运行态。"""







    thread = getattr(task, "executor_thread", None)







    if thread is None:







        return False







    try:







        return bool(thread.isRunning())







    except Exception:







        return False







def task_executor_thread_is_running(task):
    return _task_executor_thread_is_running(task)


def _clear_stale_task_executor_refs(task):







    """清理已经停止但仍残留的执行器引用。"""







    if _task_executor_thread_is_running(task):







        return False







    try:







        if hasattr(task, "_force_cleanup_executor"):







            task._force_cleanup_executor()







        else:







            task.executor = None







            task.executor_thread = None







    except Exception:







        try:







            task.executor = None







            task.executor_thread = None







        except Exception:







            pass







    return True







def clear_stale_task_executor_refs(task):
    return _clear_stale_task_executor_refs(task)


def _normalize_task_manager_before_start(task_manager):







    """启动前清理残留执行状态与无效线程引用。"""







    if not task_manager:







        return















    try:







        if getattr(task_manager, "_is_executing", False):







            has_running_task = any(







                task.status in ("running", "paused")







                for task in task_manager.get_all_tasks()







            )

            has_active_runtime = False
            runtime_checker = getattr(task_manager, "has_active_runtime_tasks", None)
            if callable(runtime_checker):
                has_active_runtime = bool(runtime_checker())







            if not has_running_task and not has_active_runtime:







                task_manager._is_executing = False







                task_manager._executing_task_ids = []







    except Exception:







        pass















    try:







        for task in task_manager.get_executable_tasks():







            thread = getattr(task, "executor_thread", None)







            if thread is None:







                continue







            try:







                is_running = bool(thread.isRunning())







            except Exception:







                is_running = False







            try:







                task_status = str(getattr(task, "status", "") or "").strip().lower()







            except Exception:







                task_status = ""















            if is_running and task_status in ("completed", "failed", "stopped"):







                cleanup_ok = False







                try:







                    if hasattr(task, "_force_cleanup_executor"):







                        cleanup_ok = bool(task._force_cleanup_executor())







                except Exception:







                    cleanup_ok = False







                if cleanup_ok:







                    continue







            if not is_running:







                try:







                    if hasattr(task, "_force_cleanup_executor"):







                        task._force_cleanup_executor()







                    else:







                        task.executor = None







                        task.executor_thread = None







                except Exception:







                    try:







                        task.executor = None







                        task.executor_thread = None







                    except Exception:







                        pass







    except Exception:







        pass























def normalize_task_manager_before_start(task_manager):
    _normalize_task_manager_before_start(task_manager)


def _apply_pause_state(ctx, paused, error_context=None):
    from ..main_window_parts.main_window_pause_controller import set_main_window_pause_state

    return set_main_window_pause_state(
        ctx,
        paused=bool(paused),
        error_context=error_context,
        source="legacy",
    )







    self = ctx







    try:







        if paused:







            # 检查是否有多窗口执行器







            logger.info(f"检查多窗口执行器: hasattr={hasattr(self, 'multi_executor')}, exists={hasattr(self, 'multi_executor') and self.multi_executor is not None}")







            if hasattr(self, 'multi_executor') and self.multi_executor:







                logger.info(f"多窗口执行器存在，检查pause_all方法: {hasattr(self.multi_executor, 'pause_all')}")







                if hasattr(self.multi_executor, 'pause_all'):







                    self.multi_executor.pause_all()







                    logger.info("多窗口工作流已暂停")







                    self._set_button_to_paused_state()







                    if hasattr(self, '_set_line_animation_paused'):







                        self._set_line_animation_paused("task_runtime", True)







                    return True















            # 检查是否有单个executor







            logger.info(f"检查单个执行器: hasattr={hasattr(self, 'executor')}, exists={hasattr(self, 'executor') and self.executor is not None}")







            if hasattr(self, 'executor') and self.executor:







                logger.info(f"单个执行器存在，检查pause方法: {hasattr(self.executor, 'pause')}")







                if hasattr(self.executor, 'pause'):







                    self.executor.pause()







                    logger.info("单个工作流已暂停")







                    self._set_button_to_paused_state()







                    if hasattr(self, '_set_line_animation_paused'):







                        self._set_line_animation_paused("task_runtime", True)







                    return True















            # 尝试通过task_manager暂停







            logger.info(f"检查task_manager: {hasattr(self, 'task_manager')}")







            if hasattr(self, 'task_manager') and self.task_manager:







                logger.info("尝试通过task_manager暂停所有任务")







                if hasattr(self.task_manager, 'pause_all_tasks'):







                    self.task_manager.pause_all_tasks()







                    logger.info("通过task_manager暂停成功")







                    self._set_button_to_paused_state()







                    if hasattr(self, '_set_line_animation_paused'):







                        self._set_line_animation_paused("task_runtime", True)







                    return True















            logger.warning("没有运行中的工作流可以暂停")







            return False















        # 恢复流程







        if hasattr(self, 'multi_executor') and self.multi_executor:







            if hasattr(self.multi_executor, 'resume_all'):







                self.multi_executor.resume_all()







                logger.info("工作流已恢复执行")







                self._set_button_to_running_state()







                if hasattr(self, '_set_line_animation_paused'):







                    self._set_line_animation_paused("task_runtime", False)







                return True















        if hasattr(self, 'executor') and self.executor:







            if hasattr(self.executor, 'resume'):







                self.executor.resume()







                logger.info("工作流已恢复执行")







                self._set_button_to_running_state()







                if hasattr(self, '_set_line_animation_paused'):







                    self._set_line_animation_paused("task_runtime", False)







                return True















        if hasattr(self, 'task_manager') and self.task_manager:







            if hasattr(self.task_manager, 'resume_all_tasks'):







                self.task_manager.resume_all_tasks()







                logger.info("通过task_manager恢复成功")







                self._set_button_to_running_state()







                if hasattr(self, '_set_line_animation_paused'):







                    self._set_line_animation_paused("task_runtime", False)







                return True















        logger.warning("没有可恢复的工作流")







        return False







    except Exception as e:







        if error_context:







            logger.error(f"{error_context}失败: {e}")







        else:







            logger.error(f"切换暂停状态失败: {e}")







        import traceback







        logger.error(traceback.format_exc())







        return False















































































































































































# --- END ADDED ---





































































