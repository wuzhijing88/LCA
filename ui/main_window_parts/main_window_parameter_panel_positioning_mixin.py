import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTextEdit,
)

from utils.window_activation_utils import show_and_raise_widget

logger = logging.getLogger(__name__)


class MainWindowParameterPanelPositioningMixin:

    def _on_parameter_panel_closed(self):

        """处理参数面板关闭"""

        logger.info("参数面板已关闭")

        self._parameter_panel_visible = False

    def _schedule_parameter_panel_reposition(self, delay_ms: int = 16):

        """合并高频移动事件，避免重定位任务在事件队列中堆积。"""

        if not self._parameter_panel_visible or not hasattr(self, 'parameter_panel'):

            return

        if hasattr(self.parameter_panel, '_is_dragging') and self.parameter_panel._is_dragging:

            return

        self._parameter_panel_reposition_timer.start(max(0, int(delay_ms)))

    def _reposition_parameter_panel_if_needed(self):

        """定时触发参数面板重定位，统一入口便于防御性检查。"""

        if not self._parameter_panel_visible or not hasattr(self, 'parameter_panel'):

            return

        if hasattr(self.parameter_panel, '_is_dragging') and self.parameter_panel._is_dragging:

            return

        try:

            self.parameter_panel._position_panel()

        except Exception as e:

            logger.debug(f"参数面板重定位失败: {e}")

    def _smart_sync_parameter_panel_activation(self):

        """智能同步参数面板激活状态，保护输入框焦点"""

        # 关闭参数面板吸附时，不做主窗口/参数面板焦点联动，避免互相置顶

        if not self.config.get('enable_parameter_panel_snap', True):

            return

        if not self.isActiveWindow() or not self.parameter_panel.isVisible():

            return

        # 检查参数面板中是否有输入控件获得焦点

        focus_widget = QApplication.focusWidget()

        if focus_widget and isinstance(focus_widget, (QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit)):

            # 检查焦点控件是否属于参数面板

            widget_parent = focus_widget

            while widget_parent:

                if widget_parent == self.parameter_panel:

                    logger.debug(f"参数面板输入控件 {focus_widget} 获得焦点，跳过激活同步")

                    return

                widget_parent = widget_parent.parent()

        # 如果参数面板已经激活，不需要重复激活

        if self.parameter_panel.isActiveWindow():

            return

        # 保存当前焦点控件

        saved_focus = QApplication.focusWidget()

        # 重新定位参数面板

        self.parameter_panel._position_panel()

        # 仅提升层级，不主动抢焦点
        show_and_raise_widget(self.parameter_panel, log_prefix='参数面板同步')

        # 如果之前有焦点控件且仍然可用，尝试恢复焦点

        if saved_focus and saved_focus.isVisible() and saved_focus.isEnabled():

            # 使用定时器延迟恢复焦点

            QTimer.singleShot(50, lambda: self._restore_focus_to_widget(saved_focus))

        logger.debug("主窗口激活，智能同步参数面板（保护焦点）")

    def _restore_focus_to_widget(self, widget):

        """恢复焦点到指定控件"""

        try:

            if widget and widget.isVisible() and widget.isEnabled():

                widget.setFocus()

                logger.debug(f"恢复焦点到控件: {widget}")

        except Exception as e:

            logger.debug(f"恢复焦点失败: {e}")

    def resizeEvent(self, event):

        """主窗口大小改变时，重新定位参数面板"""

        super().resizeEvent(event)

        # 统一走合并调度，避免调整大小时多次排队重定位

        self._schedule_parameter_panel_reposition(33)

    def moveEvent(self, event):

        """主窗口移动时，重新定位参数面板"""

        super().moveEvent(event)

        self._schedule_parameter_panel_reposition(16)
