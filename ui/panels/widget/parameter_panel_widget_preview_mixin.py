from ..parameter_panel_support import *


class ParameterPanelWidgetPreviewMixin:

    IMAGE_PREVIEW_PARAM_NAMES = {
        'image_path',
        'target_image_path',
        'drag_start_image_path',
        'drag_end_image_path',
    }
    IMAGE_PREVIEW_TASK_TYPES = {'\u6a21\u62df\u9f20\u6807\u64cd\u4f5c'}

    def _should_append_image_preview(self, name: str, param_type: str) -> bool:
        return (
            param_type == 'file'
            and name in self.IMAGE_PREVIEW_PARAM_NAMES
            and self.current_task_type in self.IMAGE_PREVIEW_TASK_TYPES
        )

    def _append_image_preview_row(
        self,
        name: str,
        param_type: str,
        layout: QVBoxLayout,
        current_value: Any,
    ) -> None:
        if not self._should_append_image_preview(name, param_type):
            return

        logger.debug(
            f"Create image preview for task '{self.current_task_type}' param '{name}'"
        )

        preview_row_widget = QWidget()
        preview_row_layout = QHBoxLayout(preview_row_widget)
        preview_row_layout.setContentsMargins(0, 0, 0, 0)
        preview_row_layout.setSpacing(8)

        preview_text_label = QLabel('图片预览：')
        preview_text_label.setFixedWidth(140)
        preview_text_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        preview_row_layout.addWidget(preview_text_label)

        preview_label = QLabel()
        preview_label.setObjectName(f"{name}_preview")
        preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_label.setFixedHeight(80)
        preview_label.setMinimumWidth(150)
        preview_label.setStyleSheet('QLabel { border: 1px solid #cccccc; }')
        preview_label.setText('未选择图片')
        preview_label.setWordWrap(True)
        preview_label.setMouseTracking(True)
        preview_label.setProperty('image_path', '')
        preview_row_layout.addWidget(preview_label, 1)
        layout.addWidget(preview_row_widget)

        preview_key = f"{name}_preview"
        self._register_widget(preview_key, preview_label, stores_value=False)

        def on_double_click(event, path_getter=lambda: preview_label.property('image_path')):
            image_path = path_getter()
            if image_path and os.path.exists(image_path):
                self._show_image_viewer(image_path)

        preview_label.mouseDoubleClickEvent = on_double_click

        file_input = self._get_value_widget(name)
        if isinstance(file_input, QLineEdit):
            file_input.setProperty('preview_key', preview_key)

            def update_preview_handler(text, input_widget=file_input):
                current_preview_key = input_widget.property('preview_key')
                if current_preview_key and current_preview_key in self.widgets:
                    self._update_image_preview(text, self.widgets[current_preview_key])

            file_input.textChanged.connect(update_preview_handler)

            if current_value:
                self._update_image_preview(str(current_value), preview_label)

    def _append_help_text(self, param_def: Dict[str, Any], layout: QVBoxLayout) -> None:
        help_text = param_def.get('help', '')
        if not help_text:
            return

        help_label = QLabel(help_text)
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
