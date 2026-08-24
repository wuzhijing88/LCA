from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..main_window_parts.main_window_dropdown_widget import QComboBox
from ..main_window_parts.main_window_support import get_secondary_text_color


class GlobalSettingsDialogWindowTabMixin:
    def _create_window_tab(self):
        """创建窗口设置标签页"""
        window_tab = QWidget()
        window_layout = QVBoxLayout(window_tab)
        window_layout.setSpacing(8)
        window_layout.setContentsMargins(10, 8, 10, 10)
        # --- Window Settings Group ---
        self.native_window_settings_group = QGroupBox("窗口绑定")
        window_settings_layout = QVBoxLayout(self.native_window_settings_group)
        window_settings_layout.setSpacing(8)
        window_settings_layout.setContentsMargins(15, 10, 15, 10)
        # 添加说明文字
        info_label = QLabel("绑定单个窗口且使用单个工作流时可选择执行模式\n绑定多个窗口或使用多个工作流将自动使用后台模式")
        info_label.setStyleSheet(f"color: {get_secondary_text_color()}; font-size: 9pt;")
        window_settings_layout.addWidget(info_label)
        window_settings_layout.addSpacing(5)
        # 窗口选择下拉框
        window_select_layout = QHBoxLayout()
        window_select_label = QLabel("选择窗口:")
        window_select_label.setFixedWidth(80)
        self.window_select_combo = QComboBox(self)
        self.window_select_combo.setMinimumWidth(200)
        self.window_select_combo.setMaximumWidth(500)
        self.window_select_combo.setToolTip("从列表中选择窗口，将自动绑定该单个窗口")
        self._window_list_loaded = False  # 标记窗口列表是否已加载
        # 窗口选择工具按钮
        self.batch_add_button = QPushButton("绑定工具")
        self.batch_add_button.setFixedWidth(100)
        self.batch_add_button.setToolTip("点击后移动鼠标到需要绑定的窗口上\n第一次点击锁定窗口（黄色边框）\n第二次点击确认绑定\n右键取消锁定或退出")
        window_select_layout.addWidget(window_select_label)
        window_select_layout.addWidget(self.window_select_combo, 1)
        window_select_layout.addWidget(self.batch_add_button)
        window_settings_layout.addLayout(window_select_layout)
        # 已绑定窗口下拉框
        bound_windows_layout = QHBoxLayout()
        bound_label = QLabel("已绑定窗口:")
        bound_label.setFixedWidth(80)
        self.bound_windows_combo = QComboBox(self)
        self.bound_windows_combo.setMinimumWidth(200)
        self.bound_windows_combo.setMaximumWidth(500)
        self.bound_windows_combo.setToolTip("已绑定的窗口列表")
        self.remove_window_button = QPushButton("移除选中")
        self.remove_window_button.setFixedWidth(100)
        bound_windows_layout.addWidget(bound_label)
        bound_windows_layout.addWidget(self.bound_windows_combo, 1)
        bound_windows_layout.addWidget(self.remove_window_button)
        window_settings_layout.addLayout(bound_windows_layout)
        window_layout.addWidget(self.native_window_settings_group)
        # --- Window Behavior Group ---
        window_behavior_group = QGroupBox("窗口行为")
        window_behavior_layout = QGridLayout(window_behavior_group)
        window_behavior_layout.setHorizontalSpacing(24)
        window_behavior_layout.setVerticalSpacing(8)
        window_behavior_layout.setContentsMargins(15, 12, 15, 12)
        self.card_snap_checkbox = QCheckBox("启用卡片吸附")
        self.card_snap_checkbox.setChecked(self.current_config.get('enable_card_snap', True))
        self.card_snap_checkbox.setToolTip("关闭后，仅关闭卡片与卡片之间的对齐吸附")
        self.parameter_panel_snap_checkbox = QCheckBox("启用参数面板吸附")
        self.parameter_panel_snap_checkbox.setChecked(self.current_config.get('enable_parameter_panel_snap', True))
        self.parameter_panel_snap_checkbox.setToolTip("关闭后，参数面板不再自动吸附到主窗口右侧")
        self.canvas_grid_checkbox = QCheckBox("启用画布网格")
        self.canvas_grid_checkbox.setChecked(self.current_config.get('enable_canvas_grid', True))
        self.canvas_grid_checkbox.setToolTip("关闭后不显示网格，且不应用网格吸附")
        self.floating_status_window_checkbox = QCheckBox("启用悬浮窗")
        self.floating_status_window_checkbox.setChecked(self.current_config.get('enable_floating_status_window', True))
        self.floating_status_window_checkbox.setToolTip("关闭后最小化主窗口时不再显示执行悬浮窗")
        self.connection_line_animation_checkbox = QCheckBox("启用连线动画")
        self.connection_line_animation_checkbox.setChecked(self.current_config.get('enable_connection_line_animation', True))
        self.connection_line_animation_checkbox.setToolTip("关闭后连线保持静态显示，不再播放流动动画")
        card_snap_hint = QLabel("仅影响卡片与卡片对齐吸附")
        card_snap_hint.setStyleSheet(f"color: {get_secondary_text_color()}; font-size: 9pt;")
        panel_snap_hint = QLabel("关闭后参数面板可独立拖动")
        panel_snap_hint.setStyleSheet(f"color: {get_secondary_text_color()}; font-size: 9pt;")
        canvas_grid_hint = QLabel("关闭后不显示网格且不走网格吸附")
        canvas_grid_hint.setStyleSheet(f"color: {get_secondary_text_color()}; font-size: 9pt;")
        floating_status_window_hint = QLabel("关闭后不显示执行悬浮窗")
        floating_status_window_hint.setStyleSheet(f"color: {get_secondary_text_color()}; font-size: 9pt;")
        connection_line_animation_hint = QLabel("关闭后连线静态显示，不再流动")
        connection_line_animation_hint.setStyleSheet(f"color: {get_secondary_text_color()}; font-size: 9pt;")
        window_behavior_layout.addWidget(self.card_snap_checkbox, 0, 0)
        window_behavior_layout.addWidget(self.parameter_panel_snap_checkbox, 0, 1)
        window_behavior_layout.addWidget(self.canvas_grid_checkbox, 0, 2)
        window_behavior_layout.addWidget(card_snap_hint, 1, 0)
        window_behavior_layout.addWidget(panel_snap_hint, 1, 1)
        window_behavior_layout.addWidget(canvas_grid_hint, 1, 2)
        window_behavior_layout.addWidget(self.floating_status_window_checkbox, 2, 0)
        window_behavior_layout.addWidget(self.connection_line_animation_checkbox, 2, 1)
        window_behavior_layout.addWidget(floating_status_window_hint, 3, 0)
        window_behavior_layout.addWidget(connection_line_animation_hint, 3, 1)
        window_behavior_layout.setColumnStretch(0, 1)
        window_behavior_layout.setColumnStretch(1, 1)
        window_behavior_layout.setColumnStretch(2, 1)
        window_layout.addWidget(window_behavior_group)
        window_layout.addStretch()
        self.tab_widget.addTab(window_tab, "窗口设置")
