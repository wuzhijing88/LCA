import logging

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
    QSystemTrayIcon,
)

from themes import apply_rounded_popup
from ui.dialogs.close_behavior_dialog import CloseBehaviorDialog
from utils.window.window_coordinate_common import center_window_on_widget_screen
from utils.window.window_activation_utils import show_and_activate_overlay

logger = logging.getLogger(__name__)


class MainWindowCloseMixin:
    @Slot()
    def restore_main_window(self) -> None:
        """统一从托盘恢复主窗口。"""
        try:
            current_state = self.windowState()
            if current_state & Qt.WindowState.WindowMinimized:
                self.setWindowState(current_state & ~Qt.WindowState.WindowMinimized)
            show_and_activate_overlay(self, log_prefix='主窗口恢复', focus=True)
        except Exception as exc:
            logger.error(f"恢复主窗口失败: {exc}", exc_info=True)
    def closeEvent(self, event: QCloseEvent) -> None:
        """处理窗口关闭事件 - 立即关闭UI，后台清理资源"""
        cancel_startup_load = getattr(self, "_cancel_startup_workflow_load", None)
        if callable(cancel_startup_load):
            cancel_startup_load()
        # 关闭行为选择：最小化到托盘 or 退出程序（可记住选择）
        config = self.config
        remember_choice = getattr(self, "_close_behavior_remember", None)
        close_behavior = getattr(self, "_close_behavior", None)
        if remember_choice is None or close_behavior is None:
            remember_choice = config["close_behavior_remember"]
            close_behavior = config["close_behavior"]
        from utils.instance_runtime import create_app_settings

        settings = create_app_settings()
        qs_remember = settings.value("close_behavior_remember", None)
        qs_behavior = settings.value("close_behavior", None)
        if qs_remember is not None:
            # QSettings 跨进程读取布尔值时可能返回其原生字符串编码。
            # 只允许 Qt 写出的 true/false，再通过类型接口读取，拒绝任意真值转换。
            if type(qs_remember) is not bool and not (
                type(qs_remember) is str and qs_remember in ("true", "false")
            ):
                raise ValueError("记住关闭方式的设置必须是布尔值")
            remember_choice = settings.value("close_behavior_remember", type=bool)
            if qs_behavior is not None:
                close_behavior = qs_behavior
        if type(remember_choice) is not bool:
            raise ValueError("记住关闭方式的设置必须是布尔值")
        if close_behavior not in ("ask", "tray", "exit"):
            raise ValueError("关闭方式设置无效")
        if getattr(self, "_exiting_after_child_session_logoff", False):
            remember_choice = True
            close_behavior = "exit"
        def _prepare_modal_popup(popup) -> None:
            apply_rounded_popup(popup, frameless=False)
            popup.adjustSize()
            center_window_on_widget_screen(popup, self)
        def _persist_close_choice(choice: str, remember: bool) -> None:
            if remember:
                self._close_behavior = choice
                self._close_behavior_remember = True
                self.config["close_behavior"] = choice
                self.config["close_behavior_remember"] = True
            else:
                # 清除已记住选择
                self._close_behavior = "ask"
                self._close_behavior_remember = False
                self.config["close_behavior"] = "ask"
                self.config["close_behavior_remember"] = False
            self.save_config_func(self.config)
            settings.setValue("close_behavior", self.config["close_behavior"])
            settings.setValue("close_behavior_remember", self.config["close_behavior_remember"])
        def _minimize_to_tray() -> bool:
            if QSystemTrayIcon.isSystemTrayAvailable():
                self.hide()
                return True
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("系统托盘不可用")
            msg_box.setText("当前系统托盘不可用，无法最小化。请重新选择关闭方式。")
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            _prepare_modal_popup(msg_box)
            try:
                msg_box.exec()
            finally:
                msg_box.deleteLater()
            return False
        if remember_choice and close_behavior in ("tray", "exit"):
            if close_behavior == "tray":
                if _minimize_to_tray():
                    event.ignore()
                    return
                # 托盘不可用时明确失败，清除选择并保留主窗口。
                _persist_close_choice("ask", False)
                event.ignore()
                return
            else:
                pass
        else:
            dialog = CloseBehaviorDialog(self)
            _prepare_modal_popup(dialog)
            try:
                result = dialog.exec()
                remember = dialog.remember_check.isChecked()
            finally:
                dialog.deleteLater()
            if result == 0:
                event.ignore()
                return
            if result == 1:
                if remember:
                    _persist_close_choice("tray", True)
                if _minimize_to_tray():
                    event.ignore()
                    return
                _persist_close_choice("ask", False)
                event.ignore()
                return
            elif result == 2:
                if remember:
                    _persist_close_choice("exit", True)
                else:
                    _persist_close_choice("ask", False)
            else:
                event.ignore()
                return
        # ========== 快速清理（不阻塞UI） ==========
        # 停止DPI监控
        self.stop_dpi_monitoring()
        self._stop_main_schedule_clock()
        if hasattr(self, '_timed_pause_resume_timer') and self._timed_pause_resume_timer.isActive():
            self._timed_pause_resume_timer.stop()
            logger.info("已停止定时暂停恢复定时器")
        # 清理所有快捷键（快速操作）
        try:
            import keyboard
            keyboard.unhook_all()
            logger.info("已清理所有键盘快捷键")
        except Exception as e:
            logger.debug(f"清理键盘快捷键失败: {e}")
        try:
            import mouse
            mouse.unhook_all()
            logger.info("已清理所有鼠标快捷键")
        except Exception as e:
            logger.debug(f"清理鼠标快捷键失败: {e}")
        # 检查是否有未保存的任务（需要用户确认，必须同步）
        if hasattr(self, 'workflow_tab_widget') and self.workflow_tab_widget.has_unsaved_changes():
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("未保存的更改")
            msg_box.setText("有任务包含未保存的更改。是否保存所有更改？")
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Close)
            msg_box.setDefaultButton(QMessageBox.StandardButton.Save)
            msg_box.setEscapeButton(QMessageBox.StandardButton.Close)
            msg_box.button(QMessageBox.StandardButton.Close).hide()
            _prepare_modal_popup(msg_box)
            try:
                reply = msg_box.exec()
            finally:
                msg_box.deleteLater()
            if reply == QMessageBox.StandardButton.Save:
                # 先同步所有工作流视图数据到任务对象
                for task_id, workflow_view in self.workflow_tab_widget.task_views.items():
                    task = self.task_manager.get_task(task_id)
                    if task and task.modified:
                        workflow_data = workflow_view.serialize_workflow()
                        task.update_workflow_data(workflow_data)
                        logger.info(f"已同步任务 '{task.name}' 的工作流数据")
                saved_count = 0
                for task in self.task_manager.get_all_tasks():
                    if not task.modified:
                        continue
                    old_filepath = task.filepath
                    if task.save_and_backup():
                        saved_count += 1
                        self._sync_favorite_path_after_save(old_filepath, task)
                logger.info(f"已保存 {saved_count} 个任务")
            elif reply == QMessageBox.StandardButton.Discard:
                pass
            else:
                event.ignore()
                return
        # 无论是否保存任务文件，都持久化当前画布缩放/位置，保证重启可恢复
        try:
            if hasattr(self, "workflow_tab_widget") and self.workflow_tab_widget:
                self.workflow_tab_widget.persist_open_view_states()
        except Exception as persist_view_exc:
            logger.warning(f"关闭前持久化画布视图状态失败: {persist_view_exc}")
        # 停止所有正在运行的任务（快速发送停止信号，不等待）
        running_count = self.task_manager.get_running_count()
        if running_count > 0:
            logger.info(f"检测到 {running_count} 个正在运行的任务，发送停止请求（不等待）...")
            self.task_manager.stop_all()
        # 停止定时器（快速操作）
        if hasattr(self, '_random_pause_timer') and self._random_pause_timer.isActive():
            self._random_pause_timer.stop()
            logger.info("已停止随机暂停定时器")
        if hasattr(self, '_timed_pause_resume_timer') and self._timed_pause_resume_timer.isActive():
            self._timed_pause_resume_timer.stop()
            logger.info("已停止定时暂停恢复定时器")
        self._stop_main_schedule_clock()
        child_session_window = getattr(self, "child_session_window", None)
        if child_session_window is not None:
            try:
                waiting = child_session_window.request_close_after_logoff()
            except Exception as exc:
                logger.warning("关闭主窗口时注销桌面分身失败: %s", exc)
                waiting = False
            if waiting:
                if not getattr(self, "_exiting_after_child_session_logoff", False):
                    self._exiting_after_child_session_logoff = True
                    child_session_window.destroyed.connect(
                        lambda *_args: QTimer.singleShot(0, self.close)
                    )
                event.ignore()
                return
            try:
                child_session_window.shutdown()
            except Exception as exc:
                logger.warning("关闭主窗口时释放桌面分身失败: %s", exc)
            self.child_session_window = None
        # ========== 关闭前确定性回收（阻塞上限3秒） ==========
        if not self._shutdown_executor_on_close(timeout_ms=3000):
            logger.warning("关闭窗口时执行线程未在超时内退出")
        execution_log_panel = getattr(self, "_execution_log_panel", None)
        if execution_log_panel is not None:
            execution_log_panel.cleanup()
            execution_log_panel.deleteLater()
            self._execution_log_panel = None
        if getattr(self, "_window_monitor_timer", None) is not None:
            self._stop_window_monitor()
        logger.info("closeEvent: 接受关闭事件，UI立即退出，后台继续清理...")
        event.accept()
        # 显式调用 QApplication.quit()
        QApplication.instance().quit()
