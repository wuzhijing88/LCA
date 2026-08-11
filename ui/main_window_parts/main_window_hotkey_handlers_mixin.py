import logging

from PySide6.QtCore import QThread, QTimer

logger = logging.getLogger(__name__)


class MainWindowHotkeyHandlersMixin:

    def _on_record_hotkey(self):

        """录制快捷键回调"""

        try:

            if QThread.currentThread() != self.thread():

                QTimer.singleShot(0, self, self._on_record_hotkey)

                return

            # 防抖：检查是否在短时间内重复触发

            import time

            current_time = time.time()

            if hasattr(self, '_last_record_hotkey_time'):

                if current_time - self._last_record_hotkey_time < 0.5:  # 500ms 防抖

                    logger.debug(f"录制快捷键防抖：忽略重复触发（距上次 {current_time - self._last_record_hotkey_time:.3f}s）")

                    return

            self._last_record_hotkey_time = current_time

            record_hotkey = self.config.get('record_hotkey', 'F11').upper()

            logger.info(f"✓ 检测到录制快捷键: {record_hotkey}")

            # 查找参数面板中的录制功能

            try:

                # 获取当前活动的参数面板

                param_panel = getattr(self, 'param_panel', None)

                if param_panel is None:

                    param_panel = getattr(self, 'parameter_panel', None)

                if param_panel and hasattr(param_panel, '_is_recording_panel_active'):

                    # 组合键可编辑序列录制时，屏蔽主窗口全局录制快捷键，避免干扰录制按键内容

                    if bool(getattr(param_panel, '_combo_seq_block_global_record_hotkey', False)):

                        logger.info("组合键录制进行中，忽略全局录制快捷键触发")

                        return

                    if param_panel._is_recording_panel_active:

                        # 触发参数面板的录制功能

                        if hasattr(param_panel, '_on_record_hotkey'):

                            param_panel._on_record_hotkey()

                            logger.info("✓ 已触发参数面板的录制功能")

                        else:

                            logger.warning("参数面板未实现录制功能")

                    else:

                        logger.info("提示：请先打开录制回放参数面板才能使用录制功能")

                else:

                    logger.info("提示：录制功能需要在参数面板中使用")

            except Exception as e:

                logger.error(f"触发录制功能失败: {e}")

                import traceback

                logger.error(traceback.format_exc())

        except Exception as e:

            logger.error(f"录制快捷键处理失败: {e}")

            import traceback

            logger.error(traceback.format_exc())

    def _on_replay_hotkey(self):

        """回放快捷键回调"""

        try:

            if QThread.currentThread() != self.thread():

                QTimer.singleShot(0, self, self._on_replay_hotkey)

                return

            # 防抖：检查是否在短时间内重复触发

            import time

            current_time = time.time()

            if hasattr(self, '_last_replay_hotkey_time'):

                if current_time - self._last_replay_hotkey_time < 0.5:  # 500ms 防抖

                    logger.debug(f"回放快捷键防抖：忽略重复触发（距上次 {current_time - self._last_replay_hotkey_time:.3f}s）")

                    return

            self._last_replay_hotkey_time = current_time

            replay_hotkey = self.config.get('replay_hotkey', 'F12').upper()

            logger.info(f"✓ 检测到回放快捷键: {replay_hotkey}")

            # 查找参数面板中的回放功能

            try:

                # 获取当前活动的参数面板

                param_panel = getattr(self, 'param_panel', None)

                if param_panel and hasattr(param_panel, '_is_recording_panel_active'):

                    if param_panel._is_recording_panel_active:

                        # 触发参数面板的回放功能

                        if hasattr(param_panel, '_on_replay_hotkey'):

                            param_panel._on_replay_hotkey()

                            logger.info("✓ 已触发参数面板的回放功能")

                        else:

                            logger.warning("参数面板未实现回放功能")

                    else:

                        logger.info("提示：请先打开录制回放参数面板才能使用回放功能")

                else:

                    logger.info("提示：回放功能需要在参数面板中使用")

            except Exception as e:

                logger.error(f"触发回放功能失败: {e}")

                import traceback

                logger.error(traceback.format_exc())

        except Exception as e:

            logger.error(f"回放快捷键处理失败: {e}")

            import traceback

            logger.error(traceback.format_exc())

    def _on_start_task_hotkey(self):

        """启动任务快捷键回调 - 通过信号确保线程安全"""

        try:

            # 防抖：检查是否在短时间内重复触发

            import time

            current_time = time.time()

            if hasattr(self, '_last_start_hotkey_time'):

                if current_time - self._last_start_hotkey_time < 0.5:  # 500ms 防抖

                    logger.debug(f"快捷键防抖：忽略重复触发（距上次 {current_time - self._last_start_hotkey_time:.3f}s）")

                    return

            self._last_start_hotkey_time = current_time

            # 获取当前热键值

            hotkey_value = self._get_hotkey_value('start')

            logger.info(f"检测到启动任务快捷键: {hotkey_value}")

            # 直接启动任务

            self.hotkey_start_signal.emit()

            logger.info("快捷键回调：已发射 hotkey_start_signal 信号")

        except Exception as e:

            logger.error(f"启动任务快捷键处理失败: {e}")

            import traceback

            logger.error(traceback.format_exc())

    def _on_stop_task_hotkey(self):

        """停止任务快捷键回调 - 通过信号确保线程安全"""

        try:

            # 防抖：检查是否在短时间内重复触发

            import time

            current_time = time.time()

            if hasattr(self, '_last_stop_hotkey_time'):

                if current_time - self._last_stop_hotkey_time < 0.5:  # 500ms 防抖

                    logger.debug(f"快捷键防抖：忽略重复触发（距上次 {current_time - self._last_stop_hotkey_time:.3f}s）")

                    return

            self._last_stop_hotkey_time = current_time

            # 获取当前热键值

            hotkey_value = self._get_hotkey_value('stop')

            logger.info(f"检测到停止任务快捷键: {hotkey_value}")

            logger.info("=" * 50)

            logger.info("强制停止：开始执行停止操作")

            # 直接调用停止方法

            logger.info("✓ 强制停止：调用 safe_stop_tasks()")

            self.safe_stop_tasks()

            logger.info("=" * 50)

        except Exception as e:

            logger.error(f"停止任务快捷键处理失败: {e}")

            import traceback

            logger.error(traceback.format_exc())

    def _on_pause_workflow_hotkey(self):

        """暂停/恢复工作流快捷键回调"""

        try:

            # 防抖：检查是否在短时间内重复触发

            import time

            current_time = time.time()

            if hasattr(self, '_last_pause_hotkey_time'):

                if current_time - self._last_pause_hotkey_time < 0.5:  # 500ms 防抖

                    logger.debug(f"暂停快捷键防抖：忽略重复触发（距上次 {current_time - self._last_pause_hotkey_time:.3f}s）")

                    return

            self._last_pause_hotkey_time = current_time

            hotkey_value = self._get_hotkey_value('pause')

            logger.info(f"检测到暂停工作流快捷键: {hotkey_value}")

            # 切换暂停/恢复状态

            self.toggle_pause_workflow()

        except Exception as e:

            logger.error(f"暂停工作流快捷键处理失败: {e}")

            import traceback

            logger.error(traceback.format_exc())

    def _safe_start_from_hotkey(self):

        """在主线程中安全启动任务（供快捷键调用）"""

        try:

            logger.info("快捷键触发：在主线程中启动任务")

            self.safe_start_tasks()

        except Exception as e:

            logger.error(f"快捷键启动任务失败: {e}")

    def _safe_stop_from_hotkey(self):

        """在主线程中安全停止任务（供快捷键调用）"""

        try:

            logger.info("快捷键触发：在主线程中停止任务")

            self.safe_stop_tasks()

        except Exception as e:

            logger.error(f"快捷键停止任务失败: {e}")
