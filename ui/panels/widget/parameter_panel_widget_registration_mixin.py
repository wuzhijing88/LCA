from ..parameter_panel_support import *


class ParameterPanelWidgetRegistrationMixin:

    def _register_created_widget(self, name: str, param_def: Dict[str, Any], widget: Optional[QWidget]):
        if widget and name not in self.widgets:
            self._register_widget(name, widget, stores_value=self._should_register_value_widget(param_def))

            # 确保所有输入控件都能接收焦点和输入事件
            if hasattr(widget, 'setFocusPolicy'):
                widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

            # 为可能响应滚轮的控件安装滚轮事件过滤器
            self._install_wheel_filter(widget, name)

            # 确保输入控件能正常工作
            if isinstance(widget, (QLineEdit, QSpinBox, QDoubleSpinBox)):
                # 设置基本属性确保输入功能
                widget.setEnabled(True)
                widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

                # 强制设置更多属性
                widget.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
                widget.setReadOnly(False) if hasattr(widget, 'setReadOnly') else None

                # 简化调试信息
                logger.debug(f"创建输入控件 {name}: 类型={type(widget).__name__}")

                # 为输入框添加文本变化监听（保持原有功能）
                if isinstance(widget, QLineEdit):
                    def on_text_changed(text, widget_name=name):
                        logger.debug(f"输入框 {widget_name} 文本变化: {text}")
                    widget.textChanged.connect(on_text_changed)

                    # 重写事件方法，添加焦点保护机制
                    original_focus_in = widget.focusInEvent
                    original_focus_out = widget.focusOutEvent

                    def new_focus_in(event, widget_name=name):
                        logger.debug(f"输入框 {widget_name} 获得焦点，启用焦点保护")
                        # 启用焦点保护，暂时禁用窗口激活同步
                        self._input_focus_protection_active = True
                        original_focus_in(event)

                    def new_focus_out(event, widget_name=name):
                        logger.debug(f"输入框 {widget_name} 失去焦点，延迟禁用焦点保护")
                        original_focus_out(event)
                        # 延迟禁用焦点保护，给用户切换到其他输入框的时间
                        QTimer.singleShot(500, lambda: setattr(self, '_input_focus_protection_active', False))

                    widget.focusInEvent = new_focus_in
                    widget.focusOutEvent = new_focus_out

            # 设置工具提示
            tooltip = param_def.get('tooltip', '')
            if tooltip:
                # 确保tooltip能正确显示，特别是包含换行符的长文本
                widget.setToolTip(tooltip)
                # 设置tooltip的显示时间更长一些，便于阅读
                widget.setToolTipDuration(10000)  # 10秒

            # 检查是否是影响条件显示的参数，如果是则连接信号
            self._connect_conditional_signals(name, widget)

            # 移除状态栏显示功能，避免重复多余的说明
            # self._setup_status_display(widget, name, param_def)

        # 添加widget到布局（在if块外面）

