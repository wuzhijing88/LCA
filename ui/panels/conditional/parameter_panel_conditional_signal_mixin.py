from ..parameter_panel_support import *


class ParameterPanelConditionalSignalMixin:

    def _connect_conditional_signals(self, param_name: str, widget: QWidget):
        """为影响条件显示的参数连接信号"""
        # 检查是否有其他参数依赖于这个参数
        is_conditional_param = False
        for other_param_def in self.param_definitions.values():
            condition = other_param_def.get('condition', other_param_def.get('conditions'))
            if condition:
                # 支持多条件和单条件
                if isinstance(condition, list):
                    # 多条件：检查是否有任何条件依赖于这个参数
                    for single_condition in condition:
                        if single_condition.get('param') == param_name:
                            is_conditional_param = True
                            break
                else:
                    # 单条件 - 检查主条件和AND条件
                    if condition.get('param') == param_name:
                        is_conditional_param = True
                    else:
                        # 检查AND条件
                        and_condition = condition.get('and')
                        if and_condition:
                            if isinstance(and_condition, list):
                                # 多个AND条件
                                for and_cond in and_condition:
                                    if and_cond.get('param') == param_name:
                                        is_conditional_param = True
                                        break
                            else:
                                # 单个AND条件
                                if and_condition.get('param') == param_name:
                                    is_conditional_param = True
            if is_conditional_param:
                break

        if not is_conditional_param:
            return

        # 根据控件类型连接相应的信号
        if isinstance(widget, QComboBox):
            widget.currentTextChanged.connect(self._on_conditional_param_changed)
        elif isinstance(widget, QCheckBox):
            widget.toggled.connect(self._on_conditional_param_changed)
        elif isinstance(widget, QSpinBox):
            widget.valueChanged.connect(self._on_conditional_param_changed)
        elif isinstance(widget, QDoubleSpinBox):
            widget.valueChanged.connect(self._on_conditional_param_changed)
        elif isinstance(widget, QLineEdit):
            widget.textChanged.connect(self._on_conditional_param_changed)
        elif isinstance(widget, QPlainTextEdit):
            widget.textChanged.connect(self._on_conditional_param_changed)
        elif hasattr(widget, 'button_group'):
            # 单选按钮组
            widget.button_group.buttonToggled.connect(self._on_conditional_param_changed)


    def _on_conditional_param_changed(self):
        """条件参数值发生变化时的处理"""
        logger.debug("条件参数变化，准备更新参数面板显示")

        # 延迟更新以避免频繁重建界面
        if not hasattr(self, '_update_timer'):
            from PySide6.QtCore import QTimer
            self._update_timer = QTimer(self)
            self._update_timer.setSingleShot(True)
            self._update_timer.timeout.connect(self._update_conditional_display)

        self._update_timer.start(100)  # 100ms延迟

