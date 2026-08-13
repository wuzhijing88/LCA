import logging

from PySide6.QtCore import QSettings, Qt, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
)

from utils.window_coordinate_common import center_window_on_widget_screen
from utils.window_activation_utils import show_and_activate_overlay

logger = logging.getLogger(__name__)


class MainWindowCloseMixin:
    @Slot()
    def restore_main_window(self) -> None:
        """统一恢复主窗口，兼容托盘和悬浮窗入口。"""
        try:
            current_state = self.windowState()
            if current_state & Qt.WindowState.WindowMinimized:
                self.setWindowState(current_state & ~Qt.WindowState.WindowMinimized)
            show_and_activate_overlay(self, log_prefix='主窗口恢复', focus=True)
        except Exception as exc:
            logger.error(f"恢复主窗口失败: {exc}", exc_info=True)
    def closeEvent(self, event: QCloseEvent) -> None:
        """处理窗口关闭事件 - 立即关闭UI，后台清理资源"""
        # 关闭行为选择：最小化到托盘 or 退出程序（可记住选择）
        try:
            config = getattr(self, "config", {}) or {}
        except Exception:
            config = {}
        remember_choice = getattr(self, "_close_behavior_remember", None)
        close_behavior = getattr(self, "_close_behavior", None)
        if remember_choice is None or close_behavior is None:
            try:
                remember_choice = bool(config.get("close_behavior_remember", False))
                close_behavior = str(config.get("close_behavior", "ask"))
            except Exception:
                remember_choice = False
                close_behavior = "ask"
        try:
            settings = QSettings("LCA", "LCA")
            qs_remember = settings.value("close_behavior_remember", None)
            qs_behavior = settings.value("close_behavior", None)
            if qs_remember is not None:
                remember_choice = bool(qs_remember in (True, "true", "1", 1))
                if qs_behavior is not None:
                    close_behavior = str(qs_behavior)
        except Exception:
            pass
        def _prepare_modal_popup(popup) -> None:
            try:
                popup.adjustSize()
            except Exception:
                pass
            center_window_on_widget_screen(popup, self)
        def _persist_close_choice(choice: str, remember: bool) -> None:
            if not hasattr(self, "config") or self.config is None:
                return
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
            if hasattr(self, "save_config_func") and callable(self.save_config_func):
                try:
                    self.save_config_func(self.config)
                except Exception as exc:
                    logger.debug("保存关闭行为失败: %s", exc)
            try:
                settings = QSettings("LCA", "LCA")
                settings.setValue("close_behavior", self.config.get("close_behavior", "ask"))
                settings.setValue("close_behavior_remember", bool(self.config.get("close_behavior_remember", False)))
            except Exception:
                pass
        def _minimize_to_tray() -> bool:
            if QSystemTrayIcon.isSystemTrayAvailable():
                self.hide()
                return True
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("系统托盘不可用")
            msg_box.setText("当前系统托盘不可用，将直接退出程序。")
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            _prepare_modal_popup(msg_box)
            msg_box.exec()
            return False
        if remember_choice and close_behavior in ("tray", "exit"):
            if close_behavior == "tray":
                if _minimize_to_tray():
                    event.ignore()
                    return
                # 托盘不可用则清除记住状态并继续退出流程
                _persist_close_choice("ask", False)
            else:
                pass
        else:
            dialog = QDialog(self)
            dialog.setWindowTitle("关闭程序")
            dialog.setModal(True)
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(16, 16, 16, 16)
            layout.setSpacing(10)
            title_label = QLabel("请选择关闭方式：", dialog)
            info_label = QLabel("最小化到托盘后程序仍在后台运行。", dialog)
            remember_check = QCheckBox("记住选择", dialog)
            layout.addWidget(title_label)
            layout.addWidget(info_label)
            layout.addWidget(remember_check)
            button_layout = QHBoxLayout()
            button_layout.addStretch()
            tray_button = QPushButton("最小化到托盘", dialog)
            exit_button = QPushButton("退出程序", dialog)
            cancel_button = QPushButton("取消", dialog)
            tray_button.clicked.connect(lambda: dialog.done(1))
            exit_button.clicked.connect(lambda: dialog.done(2))
            cancel_button.clicked.connect(lambda: dialog.done(0))
            button_layout.addWidget(tray_button)
            button_layout.addWidget(exit_button)
            button_layout.addWidget(cancel_button)
            layout.addLayout(button_layout)
            _prepare_modal_popup(dialog)
            result = dialog.exec()
            if result == 0:
                event.ignore()
                return
            if result == 1:
                if remember_check.isChecked():
                    _persist_close_choice("tray", True)
                if _minimize_to_tray():
                    event.ignore()
                    return
                # 托盘不可用则继续退出流程
            elif result == 2:
                if remember_check.isChecked():
                    _persist_close_choice("exit", True)
                else:
                    _persist_close_choice("ask", False)
            else:
                event.ignore()
                return
        # ========== 快速清理（不阻塞UI） ==========
        # 停止DPI监控
        self.stop_dpi_monitoring()
        # 停止定时启动检查定时器
        self._stop_schedule_timer()
        # 停止定时停止检查定时器
        if hasattr(self, '_stop_timer') and self._stop_timer.isActive():
            self._stop_timer.stop()
            logger.info("已停止定时停止检查定时器")
        # 停止定时暂停检查定时器
        if hasattr(self, '_timed_pause_timer') and self._timed_pause_timer.isActive():
            self._timed_pause_timer.stop()
            logger.info("已停止定时暂停检查定时器")
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
            reply = msg_box.exec()
            if reply == QMessageBox.StandardButton.Save:
                # 先同步所有工作流视图数据到任务对象
                for task_id, workflow_view in self.workflow_tab_widget.task_views.items():
                    task = self.task_manager.get_task(task_id)
                    if task and task.modified:
                        workflow_data = workflow_view.serialize_workflow()
                        task.update_workflow_data(workflow_data)
                        logger.info(f"已同步任务 '{task.name}' 的工作流数据")
                # 保存所有已修改的任务
                saved_count = self.task_manager.save_all_modified()
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
        if hasattr(self, '_timed_pause_timer') and self._timed_pause_timer.isActive():
            self._timed_pause_timer.stop()
            logger.info("已停止定时暂停定时器")
        if hasattr(self, '_timed_pause_resume_timer') and self._timed_pause_resume_timer.isActive():
            self._timed_pause_resume_timer.stop()
            logger.info("已停止定时暂停恢复定时器")
        if hasattr(self, '_global_timer') and self._global_timer.isActive():
            self._global_timer.stop()
            logger.info("已停止全局定时器")
        # ========== 关闭前确定性回收（阻塞上限3秒） ==========
        if not self._shutdown_executor_on_close(timeout_ms=3000):
            logger.warning("关闭窗口时执行线程未在超时内退出")
        logger.info("closeEvent: 接受关闭事件，UI立即退出，后台继续清理...")
        event.accept()
        # 显式调用 QApplication.quit()
        QApplication.instance().quit()
