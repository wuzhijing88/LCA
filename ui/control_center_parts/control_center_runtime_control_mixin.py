import logging

from PySide6.QtCore import QTimer

from .control_center_runtime_types import TaskState

logger = logging.getLogger(__name__)


class WindowTaskRunnerControlMixin:

    def _cleanup_thread(self):
        """清理执行器线程和相关资源"""
        if self._is_cleaned:
            return  # 防止重复清理

        try:
            if self.isRunning():
                self._defer_cleanup_until_thread_finished()
                logger.warning(f"窗口{self.window_id}线程仍在运行，延后资源清理到线程退出后执行")
                return
        except Exception:
            pass

        self._is_cleaned = True
        self._cleanup_deferred_until_finish = False
        logger.info(f"开始清理窗口{self.window_id}的资源")
        try:
            # 【内存泄漏修复】断开所有信号连接，避免内存泄漏
            # 注意：blockSignals 只是阻止信号发送，不会清理内存引用
            if hasattr(self, 'executor') and self.executor:
                try:
                    # 断开所有信号连接
                    for signal_name in ['execution_started', 'execution_finished', 'step_details',
                                       'card_executing', 'card_finished', 'error_occurred',
                                       'show_warning', 'path_updated', 'path_resolution_failed',
                                       ]:
                        if hasattr(self.executor, signal_name):
                            try:
                                getattr(self.executor, signal_name).disconnect()
                            except (RuntimeError, TypeError):
                                pass  # 信号可能已断开或从未连接
                    logger.debug(f"已断开执行器信号连接: {self.window_id}")
                except Exception as e:
                    logger.debug(f"断开执行器信号失败: {e}")

            # 【注意】不在这里释放OLA实例，因为：
            # 1. 停止时鼠标操作可能还在进行中，立即释放会导致问题
            # 2. OLA实例会在下次启动前被清理（在start_window_task中）
            # 3. 程序退出时会统一释放所有OLA实例

            hwnd_int = 0
            try:
                from utils.window.hwnd_utils import as_hwnd

                hwnd_int = as_hwnd(getattr(self, "hwnd", 0) or self.window_info.get("hwnd"))
            except Exception:
                hwnd_int = 0

            if hwnd_int:
                try:
                    from services.multiprocess_ocr_pool import get_multiprocess_ocr_pool
                    ocr_pool = get_multiprocess_ocr_pool()
                    ocr_pool.unregister_window(hwnd_int)
                    logger.info(f"[资源清理] 已注销窗口{self.window_id}的OCR服务 (HWND: {hwnd_int})")
                except Exception as e:
                    logger.debug(f"清理OCR服务失败: {e}")

                try:
                    from utils.capture.screenshot_helper import cleanup_screenshot_engine
                    cleanup_screenshot_engine(hwnd_int)
                    logger.info(f"[资源清理] 已清理窗口{self.window_id}的截图引擎资源 (HWND: {hwnd_int})")
                except Exception as e:
                    logger.debug(f"清理WGC捕获器失败: {e}")

            # 清理执行器对象
            if hasattr(self, 'executor') and self.executor:
                try:
                    self.executor = None
                except Exception:
                    pass
            if hasattr(self, 'executor_thread') and self.executor_thread:
                try:
                    thread_handle = self.executor_thread
                    self.executor_thread = None
                    if hasattr(thread_handle, 'deleteLater'):
                        thread_handle.deleteLater()
                except Exception:
                    self.executor_thread = None

            # 【重要】不清理 MULTI_WINDOW_MODE，因为其他窗口可能还在运行
            # 只有在所有窗口都停止后才清理，由 ControlCenterWindow 统一管理
            # 清理已废弃的环境变量（如果存在）
            import os
            deprecated_vars = ['TARGET_WINDOW_HWND', 'TARGET_WINDOW_TITLE']
            for var in deprecated_vars:
                if var in os.environ:
                    try:
                        del os.environ[var]
                    except Exception:
                        pass

        except Exception as e:
            logger.warning(f"清理线程时发生错误: {e}")
        finally:
            self.executor = None
            self.executor_thread = None
            self._is_running = False
            self._queued_for_start = False
            logger.info(f"窗口{self.window_id}工作流资源清理完成")

    def stop(self):
        """停止工作流执行"""
        logger.info(f"收到停止请求，当前状态: {self._current_state.value}")

        # 无论当前状态如何，先记录停止意图，供 run() 启动阶段检查。
        self._should_stop = True

        # 检查是否可以停止
        if not self.can_stop:
            if self._current_state == TaskState.IDLE:
                logger.info(f"窗口{self.window_id}启动前收到停止请求，已标记取消")
                self._queued_for_start = False
                self._set_state(TaskState.STOPPED, "工作流已中断", force=True)
                self._emit_task_completed_once(False)
            else:
                logger.warning(f"窗口{self.window_id}当前状态{self._current_state.value}不允许停止")
            return

        # 立即设置停止状态
        self._set_state(TaskState.STOPPING, "正在停止工作流")

        # 停止执行器（使用强制停止模式）
        if hasattr(self, 'executor') and self.executor:
            try:
                # 这里不能用QueuedConnection：
                # WindowTaskRunner.run()没有启动Qt事件循环，排队信号不会被处理。
                self.executor.request_stop(force=True)
                logger.info(f"窗口{self.window_id}工作流强制停止请求已发送")
            except Exception as e:
                logger.warning(f"停止执行器时发生错误: {e}")

        # 缩短超时时间到1秒（原2秒）
        QTimer.singleShot(1000, self._force_stop_completion)

    def pause(self) -> bool:
        """暂停当前工作流。"""
        if not self._can_transition_to(TaskState.PAUSED):
            return False
        executor = getattr(self, "executor", None)
        if executor is None or not hasattr(executor, "pause"):
            return False
        if getattr(executor, "_paused", False) or self.current_state == TaskState.PAUSED:
            return False
        if not self.is_running:
            return False

        executor.pause()
        self._set_state(TaskState.PAUSED, "工作流已暂停")
        return True

    def resume(self) -> bool:
        """恢复当前工作流。"""
        if self.current_state != TaskState.PAUSED:
            return False
        executor = getattr(self, "executor", None)
        if executor is None or not hasattr(executor, "resume"):
            return False
        if not getattr(executor, "_paused", False) and self.current_state != TaskState.PAUSED:
            return False

        executor.resume()
        self._set_state(TaskState.RUNNING, "工作流已恢复")
        return True

    def _force_stop_completion(self):
        """强制完成停止操作（防止卡住）"""
        if self._current_state == TaskState.STOPPING:
            try:
                if self.isRunning():
                    self._defer_cleanup_until_thread_finished()
                    logger.warning(f"窗口{self.window_id}停止超时，但线程仍在运行，等待线程退出后再清理资源")
                    return
            except Exception:
                pass
            logger.warning(f"窗口{self.window_id}停止超时，强制设置为已停止状态")
            self._set_state(TaskState.STOPPED, "工作流已强制停止", force=True)
            self._emit_task_completed_once(False)
            self._cleanup_thread()

