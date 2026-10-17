import logging

from PySide6.QtWidgets import QMessageBox
from shiboken6 import isValid

from ui.dialogs.dialog_manager import exec_dialog, get_dialog_manager
from ui.system_parts.message_box_translator import show_warning_box

from utils.window.window_coordinate_common import center_window_on_widget_screen
from utils.window.window_activation_utils import show_and_activate_overlay

logger = logging.getLogger(__name__)


class MainWindowDialogMixin:
    def open_child_session(self):
        from utils.child_session.runtime import is_child_session_instance

        if is_child_session_instance():
            show_warning_box(self, "无法打开桌面分身", "当前已经在桌面分身会话中，不能再套一层。")
            return
        from ui.dialogs.child_session_window import ChildSessionWindow

        def create_window():
            window = ChildSessionWindow(self.config, self.save_config_func, parent=self)
            window.destroyed.connect(self._on_child_session_window_closed)
            self.child_session_window = window
            return window

        get_dialog_manager(self).show(
            "child_session", create_window, present=lambda window: window.present(self),
        )

    def _on_child_session_window_closed(self, *_args):
        self.child_session_window = None

    def open_ai_workflow_assistant(self):
        """打开独立的 AI 助手窗口。"""
        from ui.dialogs.ai_assistant_dialog import open_ai_assistant_dialog

        open_ai_assistant_dialog(self)

    def open_export_standalone_dialog(self):
        from ui.export_parts.export_dialog import StandaloneExportDialog

        dialog = StandaloneExportDialog(self)
        exec_dialog(dialog)

    def open_control_center(self):
        """打开中控软件窗口"""
        try:
            from ui.control_center_parts.control_center_policy import (
                CONTROL_CENTER_FOREGROUND_BLOCK_MESSAGE,
                control_center_allows_execution_mode,
                resolve_control_center_execution_mode,
            )

            execution_mode = resolve_control_center_execution_mode(self)
            if not control_center_allows_execution_mode(execution_mode):
                logger.warning("前台模式禁止打开中控: mode=%s", execution_mode)
                show_warning_box(self, "无法打开中控", CONTROL_CENTER_FOREGROUND_BLOCK_MESSAGE)
                return
            from ui.control_center_parts.control_center_shutdown import (
                CONTROL_CENTER_SHUTDOWN_BLOCK_MESSAGE,
                shutdown_blocks_execution,
            )

            if shutdown_blocks_execution(getattr(self, "_control_center_shutdown", None)):
                logger.warning("拒绝打开中控: 关闭收尾尚未完成")
                show_warning_box(self, "无法打开中控", CONTROL_CENTER_SHUTDOWN_BLOCK_MESSAGE)
                return
            manager = get_dialog_manager(self)
            existing = manager.find("control_center")
            if existing is not None:
                center_window_on_widget_screen(existing, self)
                show_and_activate_overlay(existing, log_prefix="中控窗口", focus=True)
                return
            # 工具 关键修复：打开中控前验证窗口句柄是否仍然有效
            logger.info("准备打开中控，开始验证窗口句柄...")
            from utils.window.window_identity import refresh_bound_windows

            refresh_bound_windows(self.bound_windows)
            valid_windows = []
            invalid_windows = []
            import win32gui
            for window_info in self.bound_windows:
                window_title = window_info.get('title', '未知窗口')
                hwnd = window_info.get('hwnd')
                # 验证窗口句柄是否仍然有效
                try:
                    if hwnd and win32gui.IsWindow(hwnd):
                        # 窗口存在，只验证IsWindow，不验证MuMu Manager列表
                        class_name = win32gui.GetClassName(hwnd)
                        logger.info(f"验证窗口: {window_title} (HWND: {hwnd} = 0x{hwnd:08X}, 类名: {class_name})")
                        # 窗口有效
                        valid_windows.append(window_title)
                        logger.debug(f"窗口句柄有效: {window_title} (HWND: {hwnd})")
                    else:
                        # 窗口句柄无效（窗口已关闭）
                        invalid_windows.append(window_title)
                        logger.warning(f"窗口句柄无效: {window_title} (HWND: {hwnd}) - 窗口已关闭")
                except Exception as e:
                    logger.error(f"验证窗口句柄失败: {window_title} - {e}")
                    invalid_windows.append(window_title)
            # 显示验证结果
            logger.info(f"窗口句柄验证完成: 有效 {len(valid_windows)} 个, 无效 {len(invalid_windows)} 个")
            if invalid_windows:
                # 弹出警告
                reply = show_warning_box(
                    self,
                    "窗口句柄验证警告",
                    "以下窗口句柄已失效：\n\n" + "\n".join(f"  • {w}" for w in invalid_windows) +
                    "\n\n请在全局设置中重新绑定这些窗口后再打开中控。\n\n" +
                    "是否仍要打开中控？（可能导致操作失败）",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    logger.info("用户取消打开中控")
                    return
            # 导入中控窗口类
            from ui.control_center_parts.control_center import ControlCenterWindow
            # 创建中控窗口
            def create_window():
                self.control_center = ControlCenterWindow(
                    bound_windows=self.bound_windows,
                    task_modules=self.task_modules,
                    parent=self,
                )
                return self.control_center

            def present_window(window):
                center_window_on_widget_screen(window, self)
                show_and_activate_overlay(window, log_prefix='中控窗口', focus=True)

            manager.show("control_center", create_window, present=present_window)
            # 禁用主窗口的快捷键
            self._disable_main_window_hotkeys()
            logging.info("中控软件已启动")
        except Exception as e:
            logging.error(f"启动中控软件失败: {e}")
            import traceback
            logging.error(traceback.format_exc())
            show_warning_box(self, "错误", f"启动中控软件失败: {e}")

    def _on_control_center_closed(self):
        """中控窗口关闭时的回调"""
        try:
            logger.info("中控窗口已关闭，恢复主窗口快捷键")
            self.control_center = None
            # 重新注册主窗口的快捷键
            self._update_hotkeys()
            self._sync_control_center_action_enabled()
        except Exception as e:
            logger.error(f"恢复主窗口快捷键失败: {e}")

    def _begin_control_center_shutdown(self, session):
        from ui.control_center_parts.control_center_shutdown import CONTROL_CENTER_SHUTDOWN_POLL_MS

        previous = getattr(self, "_control_center_shutdown", None)
        if previous is not None and getattr(previous, "active", False):
            session.orphans = list(getattr(previous, "orphans", []) or []) + list(session.orphans)
        self._control_center_shutdown = session
        timer = getattr(self, "_control_center_shutdown_timer", None)
        if timer is None:
            from PySide6.QtCore import QTimer

            timer = QTimer(self)
            timer.setInterval(CONTROL_CENTER_SHUTDOWN_POLL_MS)
            timer.timeout.connect(self._poll_control_center_shutdown)
            self._control_center_shutdown_timer = timer
        if not timer.isActive():
            timer.start()
        self._sync_control_center_action_enabled()
        self._poll_control_center_shutdown()

    def _is_control_center_runner_alive(self, runner) -> bool:
        if not isValid(runner):
            return False
        return bool(runner.isRunning())

    def _poll_control_center_shutdown(self):
        from ui.control_center_parts.control_center_shutdown import (
            cleanup_control_center_shared_runtime,
            decide_shutdown_completion,
            filter_alive_runners,
        )

        session = getattr(self, "_control_center_shutdown", None)
        if session is None or not getattr(session, "active", False):
            timer = getattr(self, "_control_center_shutdown_timer", None)
            if timer is not None and timer.isActive():
                timer.stop()
            return

        session.orphans = filter_alive_runners(session.orphans, self._is_control_center_runner_alive)
        decision = decide_shutdown_completion(len(session.orphans), session.elapsed_ms)
        if decision == "wait":
            return

        timer = getattr(self, "_control_center_shutdown_timer", None)
        if timer is not None:
            timer.stop()

        if decision == "finished_clean":
            cleanup_control_center_shared_runtime()
            logger.info("中控关闭收尾完成，共享运行时已清理")
        else:
            leftovers = list(session.orphans)
            existing = list(getattr(self, "_orphaned_control_center_threads", []) or [])
            self._orphaned_control_center_threads = existing + leftovers
            logger.error("中控关闭超时，仍有 %s 个线程未退出，已保留引用", len(leftovers))

        session.mark_finished()
        self._sync_control_center_action_enabled()

    def _sync_control_center_action_enabled(self):
        action = getattr(self, "debug_run_action", None)
        if action is None:
            return
        from ui.control_center_parts.control_center_policy import (
            CONTROL_CENTER_FOREGROUND_BLOCK_MESSAGE,
            control_center_allows_execution_mode,
            resolve_control_center_execution_mode,
        )

        from ui.control_center_parts.control_center_shutdown import (
            CONTROL_CENTER_SHUTDOWN_BLOCK_MESSAGE,
            shutdown_blocks_execution,
        )

        if shutdown_blocks_execution(getattr(self, "_control_center_shutdown", None)):
            action.setEnabled(False)
            action.setToolTip(CONTROL_CENTER_SHUTDOWN_BLOCK_MESSAGE.replace("\n\n", " "))
            return

        allowed = control_center_allows_execution_mode(resolve_control_center_execution_mode(self))
        action.setEnabled(allowed)
        if allowed:
            action.setToolTip("启动中控软件进行调试运行")
        else:
            action.setToolTip(CONTROL_CENTER_FOREGROUND_BLOCK_MESSAGE.replace("\n\n", " "))
