from ..parameter_panel_support import *


class ParameterPanelWidgetStandardTextTypeDefaultMixin:
    def _create_standard_text_default_widget(self, name: str, param_def: Dict[str, Any], current_value: Any):
        # 检查是否为多图片路径参数
        if name in ['image_paths'] and param_def.get('multiline', False):
            # 多图片路径选择器 - 使用缩略图网格显示
            multi_file_widget = QWidget()
            multi_file_layout = QVBoxLayout(multi_file_widget)
            multi_file_layout.setContentsMargins(0, 0, 0, 0)
            multi_file_layout.setSpacing(4)

            # 隐藏的文本编辑区域（用于存储路径数据）
            text_edit = QTextEdit()
            text_edit.setVisible(False)  # 隐藏文本编辑框

            # 格式化显示当前值
            if current_value:
                display_text = self._format_existing_paths_display(str(current_value))
                text_edit.setPlainText(display_text)
            else:
                text_edit.setPlainText("")

            # 缩略图网格容器
            thumbnail_scroll = QScrollArea()
            thumbnail_scroll.setWidgetResizable(True)
            thumbnail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            thumbnail_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            # 固定高度，避免重建控件时高度变化
            thumbnail_scroll.setFixedHeight(160)
            # 添加边框样式
            thumbnail_scroll.setStyleSheet("QScrollArea { border: 1px solid #cccccc; }")

            # 缩略图网格内容
            thumbnail_container = QWidget()
            thumbnail_container.setObjectName(f"{name}_thumbnail_container")
            thumbnail_grid = FlowLayout(thumbnail_container)  # 使用流式布局
            thumbnail_grid.setSpacing(20)
            thumbnail_grid.setContentsMargins(8, 8, 8, 8)

            thumbnail_scroll.setWidget(thumbnail_container)

            # 保存缩略图容器引用
            self.widgets[f"{name}_thumbnail_container"] = thumbnail_container

            # 初始化缩略图显示
            self._update_thumbnail_grid(name, text_edit.toPlainText())

            # 按钮区域
            button_layout = QHBoxLayout()
            button_layout.setContentsMargins(0, 0, 0, 0)

            select_button = QPushButton("选择多个图片...")
            select_button.setToolTip("打开文件选择对话框，选择多个图片文件")
            select_button.setProperty("class", "primary")
            select_button.clicked.connect(lambda: self._select_multiple_files_with_thumbnails(name, text_edit, param_def))

            clear_button = QPushButton("清空")
            clear_button.setToolTip("清空所有图片路径")
            clear_button.setProperty("class", "danger")
            clear_button.clicked.connect(lambda: self._clear_thumbnails(name, text_edit))

            # 统计信息标签
            count_label = QLabel()
            count_label.setObjectName(f"{name}_count_label")
            count_label
            self._update_path_count_label(count_label, text_edit.toPlainText())

            # 连接文本变化事件以更新统计和缩略图
            text_edit.textChanged.connect(lambda: self._update_path_count_label(count_label, text_edit.toPlainText()))
            text_edit.textChanged.connect(lambda: self._update_thumbnail_grid(name, text_edit.toPlainText()))

            button_layout.addWidget(select_button)
            button_layout.addWidget(clear_button)
            button_layout.addWidget(count_label)
            button_layout.addStretch()

            multi_file_layout.addWidget(thumbnail_scroll)
            multi_file_layout.addLayout(button_layout)
            multi_file_layout.addWidget(text_edit)  # 隐藏的文本编辑框

            widget = multi_file_widget
            self._register_widget(name, text_edit)  # 存储文本编辑框用于获取值

        elif param_def.get('multiline', False):
            # 多行文本输入
            widget = QTextEdit()
            widget.setPlainText(str(current_value) if current_value is not None else "")
            widget.setMaximumHeight(100)  # 限制高度

        else:
            # 默认单行文本输入
            widget = QLineEdit(str(current_value) if current_value is not None else "")
            # 设置基本属性确保输入功能
            widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            widget.setCursorPosition(0)

            # 设置占位符文本
            placeholder = param_def.get('placeholder', '')
            if placeholder:
                widget.setPlaceholderText(placeholder)

            # 检查是否为只读
            if param_def.get('readonly', False):
                widget.setReadOnly(True)
                # 只读样式由全局主题管理器控制

        return widget
