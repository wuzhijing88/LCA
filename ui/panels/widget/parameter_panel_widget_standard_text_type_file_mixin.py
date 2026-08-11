from ..parameter_panel_support import *


class ParameterPanelWidgetStandardTextTypeFileMixin:
    def _create_standard_text_file_widget(self, name: str, param_def: Dict[str, Any], current_value: Any):
        # 文件选择器类型
        file_widget = QWidget()
        file_layout = QHBoxLayout(file_widget)
        file_layout.setContentsMargins(0, 0, 0, 0)

        file_edit = QLineEdit(str(current_value) if current_value else "")
        file_edit.setPlaceholderText("点击选择文件或手动输入路径...")

        # 为子工作流任务添加"编辑子流程"按钮
        if self.current_task_type == '子工作流' and name == 'workflow_file':
            # 浏览按钮
            browse_button = QPushButton("浏览...")
            browse_button.clicked.connect(lambda: self._select_file(file_edit, param_def))

            # 编辑子流程按钮
            edit_button = QPushButton("编辑子流程")
            edit_button.setProperty("class", "primary")
            edit_button.setToolTip("在新标签页中打开并编辑子工作流")
            edit_button.clicked.connect(lambda: self._open_sub_workflow_for_edit(file_edit))

            file_layout.addWidget(file_edit)
            file_layout.addWidget(browse_button)
            file_layout.addWidget(edit_button)

        # 为找图功能和拖拽图片参数添加截图工具按钮
        # 判断是否需要截图工具：
        # 1. 模拟鼠标操作任务的操作模式为找图功能时的 image_path
        # 2. 模拟鼠标操作任务的操作模式为鼠标拖拽时的 drag_start_image_path 和 drag_end_image_path
        elif name == 'image_path' or name in ['drag_start_image_path', 'drag_end_image_path']:
            should_show_screenshot = False
            if name == 'image_path':
                if self.current_task_type == '模拟鼠标操作':
                    # 检查操作模式是否为找图功能（兼容历史值）
                    operation_mode = self._normalize_operation_mode_value(
                        self.current_parameters.get('operation_mode', ''),
                        fallback_task_type=self.current_task_type or "",
                    )
                    if operation_mode == '找图功能':
                        should_show_screenshot = True
            elif name in ['drag_start_image_path', 'drag_end_image_path']:
                if self.current_task_type == '模拟鼠标操作':
                    operation_mode = self.current_parameters.get('operation_mode', '')
                    if operation_mode == '鼠标拖拽':
                        should_show_screenshot = True

            if should_show_screenshot:
                # 添加浏览按钮
                browse_button = QPushButton("浏览...")
                browse_button.clicked.connect(lambda: self._select_file(file_edit, param_def))

                # 创建截图工具按钮
                screenshot_button = QPushButton("截图工具")
                screenshot_button.setProperty("class", "primary")
                screenshot_button.setToolTip("点击后拖动鼠标选择区域截图\n截图将自动保存并填充路径")
                # 修复闭包问题：使用默认参数捕获当前的file_edit引用
                screenshot_button.clicked.connect(lambda checked=False, edit=file_edit: self._start_screenshot_for_param(edit))

                file_layout.addWidget(file_edit)
                file_layout.addWidget(browse_button)
                file_layout.addWidget(screenshot_button)
            else:
                # 其他文件类型只使用浏览按钮
                file_button = QPushButton("浏览...")
                file_button.clicked.connect(lambda: self._select_file(file_edit, param_def))

                file_layout.addWidget(file_edit)
                file_layout.addWidget(file_button)
        else:
            # 其他文件类型只使用浏览按钮
            file_button = QPushButton("浏览...")
            file_button.clicked.connect(lambda: self._select_file(file_edit, param_def))

            file_layout.addWidget(file_edit)
            file_layout.addWidget(file_button)

        widget = file_widget
        self._register_widget(name, file_edit)  # 存储编辑框用于获取值
        return widget
