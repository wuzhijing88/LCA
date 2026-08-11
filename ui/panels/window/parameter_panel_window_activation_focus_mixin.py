from ..parameter_panel_support import *


class ParameterPanelWindowActivationFocusMixin:
        def _restore_widget_focus(self, widget):

            """恢复焦点到指定控件（用于窗口激活同步）"""

            try:

                if widget and widget.isVisible() and widget.isEnabled():

                    widget.setFocus()

                    logger.debug(f"恢复焦点到控件: {widget}")

            except Exception as e:

                logger.debug(f"恢复焦点失败: {e}")
