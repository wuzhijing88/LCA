import logging

from PySide6.QtWidgets import QMessageBox

from utils.window_coordinate_common import center_window_on_widget_screen
from utils.window_activation_utils import show_and_activate_overlay

logger = logging.getLogger(__name__)


class MainWindowDialogMixin:
    def open_control_center(self):

        """打开中控软件窗口"""

        try:

            # 工具 关键修复：打开中控前验证窗口句柄是否仍然有效

            logger.info("准备打开中控，开始验证窗口句柄...")

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

                reply = QMessageBox.warning(

                    self,

                    "窗口句柄验证警告",

                    f"以下窗口句柄已失效：\n\n" + "\n".join(f"  • {w}" for w in invalid_windows) +

                    f"\n\n请在全局设置中重新绑定这些窗口后再打开中控。\n\n" +

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

            self.control_center = ControlCenterWindow(

                bound_windows=self.bound_windows,

                task_modules=self.task_modules,

                parent=self

            )

            # 显示中控窗口
            center_window_on_widget_screen(self.control_center, self)
            show_and_activate_overlay(self.control_center, log_prefix='中控窗口', focus=True)

            # 禁用主窗口的快捷键

            self._disable_main_window_hotkeys()

            # 监听中控窗口关闭事件

            self.control_center.destroyed.connect(self._on_control_center_closed)

            logging.info("中控软件已启动")

        except Exception as e:

            logging.error(f"启动中控软件失败: {e}")

            import traceback

            logging.error(traceback.format_exc())

            QMessageBox.warning(self, "错误", f"启动中控软件失败: {e}")

    def open_variable_pool(self):

        """打开变量池管理对话框"""

        try:

            from ui.dialogs.variable_pool_dialog import VariablePoolDialog

            current_task_id = getattr(self, "_active_execution_task_id", None)

            if current_task_id is None:

                current_task_id = getattr(self, "_last_finished_task_id", None)

            if current_task_id is None and hasattr(self, "workflow_tab_widget") and self.workflow_tab_widget:

                try:

                    current_task_id = self.workflow_tab_widget.get_current_task_id()

                except Exception:

                    current_task_id = None

            dialog = VariablePoolDialog(

                self,

                parameter_panel=getattr(self, "parameter_panel", None),

                workflow_task_id=current_task_id,

            )

            center_window_on_widget_screen(dialog, self)

            dialog.exec()

        except Exception as e:

            logging.error(f"打开变量池对话框时出错: {e}")

            try:

                from ui.dialogs.custom_dialogs import ErrorWrapper

                ErrorWrapper.show_exception(

                    parent=self,

                    error=e,

                    title="变量池错误",

                    context="打开变量池"

                )

            except Exception as dialog_error:

                logging.error(f"显示错误对话框失败: {dialog_error}")

                try:

                    from PySide6.QtWidgets import QMessageBox

                    QMessageBox.critical(self, "错误", f"打开变量池失败: {e}\n\n{dialog_error}")

                except Exception:

                    pass

    def _on_control_center_closed(self):

        """中控窗口关闭时的回调"""

        try:

            logger.info("中控窗口已关闭，恢复主窗口快捷键")

            # 重新注册主窗口的快捷键

            self._update_hotkeys()

        except Exception as e:

            logger.error(f"恢复主窗口快捷键失败: {e}")
