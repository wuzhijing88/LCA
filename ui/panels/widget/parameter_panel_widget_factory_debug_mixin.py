from ..parameter_panel_support import *


class ParameterPanelWidgetFactoryDebugMixin:
    def _debug_input_widgets(self):
        logger.info("=== 调试输入控件状态 ===")
        for name, widget in self._iter_value_widgets():
            if isinstance(widget, (QLineEdit, QSpinBox, QDoubleSpinBox)):
                logger.info(f"控件 {name}:")
                logger.info(f"  类型: {type(widget).__name__}")
                logger.info(f"  是否启用: {widget.isEnabled()}")
                logger.info(f"  是否可见: {widget.isVisible()}")
                logger.info(f"  焦点策略: {widget.focusPolicy()}")
                logger.info(f"  是否只读: {getattr(widget, 'isReadOnly', lambda: False)()}")
                logger.info(f"  是否有焦点: {widget.hasFocus()}")
                logger.info(f"  父控件: {widget.parent()}")
                logger.info(f"  窗口: {widget.window()}")

    def _force_enable_input_widgets(self):
        logger.info("强制启用所有输入控件")
        for name, widget in self._iter_value_widgets():
            if isinstance(widget, (QLineEdit, QSpinBox, QDoubleSpinBox)):
                try:
                    widget.setEnabled(True)
                    if isinstance(widget, QLineEdit):
                        widget.setReadOnly(False)
                    logger.debug(f"强制启用控件 {name}: 成功")
                except Exception as e:
                    logger.error(f"强制启用控件 {name} 失败: {e}")
