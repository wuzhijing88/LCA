import logging

from .main_window_support import create_media_control_icon

logger = logging.getLogger(__name__)


class MainWindowExecutionToolbarMixin:

    def _reset_run_button(self):

        """Resets the run button to its initial 'Run' state and connects its signal."""

        # --- MODIFIED: Check button text and ensure signal is correct ---

        logging.debug("_reset_run_button: Attempting to reset button to 'Run' state.")

        # 设置为停止状态

        self._set_button_to_stopped_state()

        # 性能优化：检查当前状态，避免重复更新

        if (self.run_action.text() == "启动所有任务" and

            self.run_action.isEnabled() and

            hasattr(self, '_signal_connected_to_start') and

            self._signal_connected_to_start):

            logging.debug("_reset_run_button: 按钮已处于启动状态且信号已连接，跳过重复更新")

            return

        # Ensure correct signal connection

        try:

            self.run_action.triggered.disconnect() # Disconnect all first

            logging.debug("_reset_run_button: Disconnected existing signals.")

        except (TypeError, RuntimeError): # Handle case where no signals are connected or object deleted

            logging.debug("_reset_run_button: No signals to disconnect or error disconnecting.")

            pass

        try:

            # 修复：统一使用 _on_run_stop_button_clicked 处理按钮点击

            # 该方法会根据按钮文本判断执行启动/停止/恢复操作

            self.run_action.triggered.connect(self._on_run_stop_button_clicked)

            self._signal_connected_to_start = True  # 标记信号已连接

            logging.debug("_reset_run_button: Reconnected triggered signal to _on_run_stop_button_clicked.")

        except Exception as e:

            logging.error(f"_reset_run_button: Error connecting signal: {e}")

    def _set_line_animation_paused(self, reason: str, paused: bool):

        """统一管理连线动画暂停状态，避免并发执行路径下误恢复。"""

        if not reason:

            return

        pause_reasons = getattr(self, "_line_animation_pause_reasons", None)

        if pause_reasons is None or not isinstance(pause_reasons, set):

            pause_reasons = set()

            self._line_animation_pause_reasons = pause_reasons

        if paused:

            pause_reasons.add(reason)

        else:

            pause_reasons.discard(reason)

        should_pause = bool(pause_reasons)

        last_paused_state = bool(getattr(self, "_line_animation_is_paused", False))

        if should_pause == last_paused_state:

            return

        try:

            if should_pause:

                from ..workflow_parts.connection_line import pause_line_animation

                pause_line_animation()

            else:

                from ..workflow_parts.connection_line import resume_line_animation

                resume_line_animation()

            self._line_animation_is_paused = should_pause

        except Exception as e:

            logging.warning(f"切换连线动画暂停状态失败: {e}")

    def _clear_runtime_line_animation_pauses(self):

        """统一清理运行态产生的连线动画暂停原因。"""

        self._set_line_animation_paused("executor", False)
        self._set_line_animation_paused("task_runtime", False)

    def _setup_multi_window_stop_button(self):

        """设置多窗口执行时的停止按钮"""

        try:

            self.run_action.triggered.disconnect()

        except (TypeError, RuntimeError) as e:

            logger.debug(f"断开 run_action 信号时出现可忽略异常: {e}")

        self.run_action.setEnabled(True)

        self.run_action.setText("停止多窗口执行")

        self.run_action.setIcon(create_media_control_icon('stop', 20))

        self.run_action.setToolTip("停止所有窗口的执行 (F10)")

        self.run_action.triggered.connect(self.safe_stop_tasks)

    def _set_button_to_paused_state(self):

        """设置按钮为暂停状态：显示⏸恢复按钮"""

        logging.debug("设置按钮为暂停状态")

        self.run_action.setEnabled(True)

        self.run_action.setText("恢复")

        self.run_action.setToolTip("恢复工作流执行")

        self.run_action.setIcon(create_media_control_icon('pause', 20))

    def _set_button_to_stopped_state(self):
        """设置按钮为停止状态：显示▶运行按钮"""

        logging.debug("设置按钮为停止状态")

        self.run_action.setEnabled(True)

        self.run_action.setText("运行所有任务")

        self.run_action.setToolTip("开始执行所有工作流 (F9)")

        self.run_action.setIcon(create_media_control_icon('play', 20))

    def _set_button_to_running_state(self):
        """设置按钮为运行状态：显示■停止按钮"""

        logging.debug("设置按钮为运行状态")

        self.run_action.setEnabled(True)

        self.run_action.setText("停止")

        self.run_action.setToolTip("停止所有任务执行 (F10)")

        self.run_action.setIcon(create_media_control_icon('stop', 20))

    def _set_toolbar_to_stop_state(self):

        """兼容旧代码：设置为运行状态"""

        self._set_button_to_running_state()
