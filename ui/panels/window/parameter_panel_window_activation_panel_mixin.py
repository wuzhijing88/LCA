from ..parameter_panel_support import *
from utils.window_activation_utils import show_and_raise_widget


class ParameterPanelWindowActivationPanelMixin:
        def _smart_activate_parameter_panel(self):

            """智能激活参数面板，保护输入框焦点"""

            # 如果焦点保护处于激活状态，不进行激活同步

            if self._input_focus_protection_active:

                logger.debug("焦点保护激活中，跳过参数面板激活同步")

                return



            # 检查当前焦点控件

            focus_widget = QApplication.focusWidget()



            # 如果当前有输入控件获得焦点，不进行激活同步

            if focus_widget and isinstance(focus_widget, (QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit)):

                logger.debug(f"输入控件 {focus_widget} 获得焦点，跳过参数面板激活同步")

                return



            # 如果参数面板已经是激活状态，不需要重复激活

            if self.isActiveWindow():

                return



            # 防止循环激活

            if self._activation_in_progress:

                return



            self._activation_in_progress = True

            try:

                # 保存当前焦点控件

                saved_focus = QApplication.focusWidget()



                # 仅提升层级，不主动抢焦点
                show_and_raise_widget(self, log_prefix='参数面板激活同步')



                # 如果之前有焦点控件且仍然可用，尝试恢复焦点

                if saved_focus and saved_focus.isVisible() and saved_focus.isEnabled():

                    # 使用定时器延迟恢复焦点，避免立即被覆盖

                    QTimer.singleShot(50, lambda: self._restore_widget_focus(saved_focus))



                logger.debug("主窗口激活，智能同步参数面板（保护焦点）")

            finally:

                # 使用定时器重置标志

                QTimer.singleShot(200, lambda: setattr(self, '_activation_in_progress', False))
