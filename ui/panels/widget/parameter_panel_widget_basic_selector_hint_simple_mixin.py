from ..parameter_panel_support import *


class ParameterPanelWidgetBasicSelectorHintSimpleMixin:
    def _create_package_selector_widget(self, name: str, current_value: Any):
        package_widget = QWidget()
        package_layout = QHBoxLayout(package_widget)
        package_layout.setContentsMargins(0, 0, 0, 0)

        package_combo = QComboBox(package_widget)
        self._remove_combobox_shadow(package_combo)
        if current_value:
            package_combo.addItem(str(current_value))
            package_combo.setCurrentText(str(current_value))

        refresh_button = ResponsiveButton("刷新")
        refresh_button.setMinimumWidth(60)
        refresh_button.setProperty("class", "primary")
        refresh_button.clicked.connect(lambda: self._refresh_package_list(package_combo))

        package_layout.addWidget(package_combo, 1)
        package_layout.addWidget(refresh_button)

        self._register_widget(name, package_combo)
        self._install_wheel_filter(package_combo, name)
        return package_widget

    def _create_pc_app_selector_widget(self, name: str, current_value: Any):
        pc_app_combo = QComboBox(self)
        self._remove_combobox_shadow(pc_app_combo)
        pc_app_combo.setMaximumWidth(260)

        try:
            from tasks import pc_app_manager
            apps = pc_app_manager.refresh_apps_list()
            for app in apps:
                pc_app_combo.addItem(app)
        except Exception as e:
            logger.error(f"加载电脑应用列表失败: {e}")
            pc_app_combo.addItem("请先添加应用")

        if current_value:
            pc_app_combo.setCurrentText(str(current_value))

        self._register_widget(name, pc_app_combo)
        self._install_wheel_filter(pc_app_combo, name)
        return pc_app_combo

    def _create_file_selector_widget(self, name: str, param_def: Dict[str, Any], current_value: Any):
        file_widget = QWidget()
        file_layout = QHBoxLayout(file_widget)
        file_layout.setContentsMargins(0, 0, 0, 0)

        file_edit = QLineEdit(str(current_value) if current_value else "")
        file_button = QPushButton("浏览...")
        file_button.clicked.connect(lambda: self._select_file(file_edit, param_def))

        file_layout.addWidget(file_edit)
        file_layout.addWidget(file_button)
        self._register_widget(name, file_edit)
        return file_widget

    def _create_color_selector_widget(self, name: str, current_value: Any):
        color_widget = QWidget()
        color_layout = QHBoxLayout(color_widget)
        color_layout.setContentsMargins(0, 0, 0, 0)

        color_edit = QLineEdit(str(current_value) if current_value else "#000000")
        color_button = QPushButton("选择颜色")
        color_button.clicked.connect(lambda: self._select_color(color_edit))

        color_layout.addWidget(color_edit)
        color_layout.addWidget(color_button)
        self._register_widget(name, color_edit)
        return color_widget
