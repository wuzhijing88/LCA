from ..workflow_parts import workflow_lifecycle as _wl

from .main_window_stop_controller import force_stop_main_window_workflow

release_input_drivers = _wl.release_input_drivers
logger = _wl.logger
def main_window_safe_stop_tasks(ctx):







    """安全停止任务 - 精简版"""







    self = ctx







    logger.warning("=== safe_stop_tasks 被调用 ===")















    # 停止运行时窗口监控







    self._stop_window_monitor()















    # 防止重复停止







    if not hasattr(self, '_is_stopping_tasks'):







        self._is_stopping_tasks = False















    if self._is_stopping_tasks:







        logger.warning("任务正在停止中,拒绝重复停止请求")







        return















    self._is_stopping_tasks = True















    try:







        if hasattr(self, 'task_state_manager') and self.task_state_manager:







            try:







                self.task_state_manager.request_stop()







            except Exception as state_err:







                logger.warning(f"任务状态更新为 stopping 失败: {state_err}")















        # 第一步：设置停止标志







        self._jump_cancelled = True







        self._is_jumping = False







        if hasattr(self, 'task_manager') and hasattr(self.task_manager, '_current_jump_depth'):







            self.task_manager._current_jump_depth = 0















        # 第二步：取消跳转定时器







        if hasattr(self, '_active_jump_timers'):







            for timer in list(self._active_jump_timers):







                if timer and timer.isActive():







                    timer.stop()







            self._active_jump_timers.clear()















        # 第三步：统一走公共强制停止链路







        stop_requested = force_stop_main_window_workflow(self, source="manual", force=True)















        if not stop_requested:







            logger.warning("公共强制停止链路未成功命中活动运行时")














        release_input_drivers()















        # 清理批量执行状态







        if hasattr(self, '_batch_execute_queue'):







            self._batch_execute_queue = []







            self._batch_execute_index = 0







            logger.info("已清理批量执行队列")







        if hasattr(self, '_batch_task_ids'):







            self._batch_task_ids = []







        if hasattr(self, '_parallel_task_ids'):







            self._parallel_task_ids = []







        if hasattr(self, '_parallel_finished_count'):







            self._parallel_finished_count = 0















        # 内存泄漏修复：清理executor的持久计数器







        try:







            if hasattr(self, 'executor') and self.executor:







                if hasattr(self.executor, '_persistent_counters'):







                    counter_count = len(self.executor._persistent_counters)







                    self.executor._persistent_counters.clear()







                    logger.info(f"已清理executor持久计数器 ({counter_count}个)")







                if hasattr(self.executor, '_counters'):







                    counter_count = len(self.executor._counters)







                    self.executor._counters.clear()







                    logger.info(f"已清理executor计数器 ({counter_count}个)")







        except Exception as e:







            logger.debug(f"清理executor计数器失败: {e}")















        # 第四步：停止定时器







        if hasattr(self, '_random_pause_timer') and self._random_pause_timer.isActive():







            self._random_pause_timer.stop()







            logger.info("[随机暂停] 定时器被 safe_stop_tasks 停止")







        if hasattr(self, '_timed_pause_timer') and self._timed_pause_timer.isActive():







            self._timed_pause_timer.stop()







            logger.info("[定时暂停] 检查定时器被 safe_stop_tasks 停止")







        if hasattr(self, '_timed_pause_resume_timer') and self._timed_pause_resume_timer.isActive():







            self._timed_pause_resume_timer.stop()







            logger.info("[定时暂停] 恢复定时器被 safe_stop_tasks 停止")







        # 重置暂停状态







        self._is_paused = False







        self._auto_pause_source = None

        self._runtime_stop_owner = None

        self._runtime_pause_owner = None















        if hasattr(self, '_global_timer') and self._global_timer.isActive():







            self._global_timer.stop()







            self._global_timer_enabled = False















        # 第五步：重置按钮







        self._reset_run_button()















        # 立即回收YOLO运行时资源（含遗留子进程兜底）







        try:







            from utils.runtime_image_cleanup import cleanup_yolo_runtime_on_stop







            cleanup_yolo_runtime_on_stop(







                release_engine=True,







                compact_memory=True,







            )







        except Exception:







            pass















        # 立即清理截图资源（保留当前引擎实例，避免下次启动重复初始化）







        try:







            from utils.screenshot_helper import cleanup_screenshot_engines_on_stop







            cleanup_screenshot_engines_on_stop(keep_current_engine=True)







        except Exception as e:







            logger.warning(f"停止任务时清理截图子进程失败: {e}")















        # 立即清理OCR子进程







        try:







            from services.multiprocess_ocr_pool import cleanup_ocr_services_on_stop







            cleanup_ocr_services_on_stop(deep_cleanup=True)







        except Exception as e:







            logger.warning(f"停止任务时清理OCR子进程失败: {e}")















        # 统一清理主进程图片缓存引用







        try:







            from utils.runtime_image_cleanup import cleanup_runtime_image_memory







            cleanup_runtime_image_memory(







                reason="main_window_safe_stop_tasks",







                cleanup_screenshot_engines=False,







                cleanup_template_cache=True,







            )







        except Exception as e:







            logger.warning(f"停止任务时清理图片缓存失败: {e}")















        if hasattr(self, 'task_state_manager') and self.task_state_manager:







            try:







                self.task_state_manager.confirm_stopped()







            except Exception as state_err:







                logger.warning(f"任务状态更新为 stopped 失败: {state_err}")















        logger.warning("=== 停止完成 ===")















    except Exception as e:







        logger.error(f"停止任务时出错: {e}")







        import traceback







        logger.error(traceback.format_exc())







        self._reset_run_button()







    finally:







        self._is_stopping_tasks = False


def main_window_stop_tasks(ctx):







    """传统停止方法，现在调用安全停止"""







    self = ctx







    logger.info("接收到停止热键信号，调用安全停止方法...")







    self.safe_stop_tasks()
