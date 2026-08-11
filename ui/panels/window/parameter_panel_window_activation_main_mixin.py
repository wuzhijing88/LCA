from ..parameter_panel_support import *
from utils.window_activation_utils import show_and_raise_widget


class ParameterPanelWindowActivationMainMixin:
        def _activate_main_window(self):

            """激活主窗口（仅在主窗口未被最小化时）"""

            # 暂时禁用自动激活主窗口功能，让用户能正常在参数面板中输入

            # if self.parent_window and not self.main_window_minimized:

            #     # 只在主窗口未被最小化时才激活

            #     self.parent_window.show()

            #     self.parent_window.raise_()

            #     self.parent_window.activateWindow()

            pass

        def _smart_activate_main_window(self):

            """智能激活主窗口，保护输入框焦点"""

            # 关闭参数面板吸附时，不进行主窗口焦点联动

            if not self._snap_to_parent_enabled:

                return



            # 如果焦点保护处于激活状态，不进行激活同步

            if self._input_focus_protection_active:

                logger.debug("焦点保护激活中，跳过主窗口激活同步")

                return



            # 检查当前焦点控件

            focus_widget = QApplication.focusWidget()



            # 如果当前有输入控件获得焦点，不进行激活同步

            if focus_widget and isinstance(focus_widget, (QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit)):

                logger.debug(f"输入控件 {focus_widget} 获得焦点，跳过主窗口激活同步")

                return



            # 如果主窗口已经是激活状态，不需要重复激活

            if self.parent_window.isActiveWindow():

                return



            # 防止循环激活

            if self._activation_in_progress:

                return



            self._activation_in_progress = True

            try:

                # 保存当前焦点控件

                saved_focus = QApplication.focusWidget()



                # 仅提升层级，不主动抢焦点
                show_and_raise_widget(self.parent_window, log_prefix='主窗口激活同步')



                # 如果之前有焦点控件且仍然可用，尝试恢复焦点

                if saved_focus and saved_focus.isVisible() and saved_focus.isEnabled():

                    # 使用定时器延迟恢复焦点，避免立即被覆盖

                    QTimer.singleShot(50, lambda: self._restore_widget_focus(saved_focus))



                logger.debug("参数面板激活，智能同步主窗口（保护焦点）")

            finally:

                # 使用定时器重置标志

                QTimer.singleShot(200, lambda: setattr(self, '_activation_in_progress', False))
