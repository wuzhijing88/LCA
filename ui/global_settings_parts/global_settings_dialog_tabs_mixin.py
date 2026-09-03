from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app_core.app_config import (
    APP_EDITION,
    APP_LICENSE_NAME,
    APP_NAME,
    APP_SUMMARY,
    app_source_url,
)
from app_core.config_sections import DEFAULT_HOTKEYS
from ui.global_settings_parts.plugin_auth_probe import start_plugin_auth_probe
from ui.widgets.hotkey_capture_button import HotkeyCaptureButton
from utils.input_simulation.mode_utils import (
    parse_foreground_backends,
    parse_foreground_py_backend,
)
from ..main_window_parts.main_window_dropdown_helpers import NoWheelSpinBox
from ..main_window_parts.main_window_dropdown_widget import QComboBox
from ..main_window_parts.main_window_support import (
    get_secondary_text_color,
    get_theme_color,
)

def _about_label(text: str, *, color: str, size: int, weight: int = 400) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(
        f"color: {color}; font-size: {size}px; font-weight: {weight}; background: transparent;"
    )
    return label


class GlobalSettingsDialogTabsMixin:

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

    def _style_settings_combo(self, combo: QComboBox, *, compact: bool = False) -> None:
        combo.setMinimumWidth(140 if compact else 200)
        combo.setMaximumWidth(16777215)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _fill_value_combo(self, combo: QComboBox, items, label_fn) -> None:
        previous = combo.currentData()
        combo.clear()
        for value in items:
            combo.addItem(label_fn(value), value)
        index = combo.findData(previous)
        if index < 0 and combo.count() > 0:
            index = 0
        if index >= 0:
            combo.setCurrentIndex(index)

    def _create_execution_tab(self):
        """执行模式页：运行后端下拉切换原生 / 插件参数。"""
        from utils.capture.engine_ids import (
            SUPPORTED_SCREENSHOT_ENGINES,
            canonicalize_screenshot_engine,
            is_plugin_screenshot_engine,
            screenshot_engine_label as engine_label_text,
        )
        from utils.plugin.bind_modes import (
            PLUGIN_BIND_KIND_BASIC,
            PLUGIN_BIND_KINDS,
            infer_plugin_bind_kind,
            normalize_plugin_bind_kind,
            plugin_bind_kind_label,
        )

        page = QWidget()
        exec_layout = QVBoxLayout(page)
        exec_layout.setSpacing(10)
        exec_layout.setContentsMargins(8, 8, 8, 8)

        def _labeled_field(label_text: str, field: QWidget, label_width: int = 80) -> QWidget:
            wrap = QWidget()
            row = QHBoxLayout(wrap)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            label = QLabel(label_text)
            label.setFixedWidth(label_width)
            row.addWidget(label)
            row.addWidget(field, 1)
            return wrap

        try:
            configured_kind = normalize_plugin_bind_kind(
                self.current_config.get("plugin_bind_kind", PLUGIN_BIND_KIND_BASIC)
            )
        except ValueError:
            configured_kind = infer_plugin_bind_kind(
                display=self.current_config.get("plugin_input_display", "normal"),
                mouse=self.current_config.get("plugin_mouse", "normal"),
                keypad=self.current_config.get("plugin_keypad", "normal"),
                bind_mode=self.current_config.get("plugin_bind_mode", 0),
            )

        self.runtime_group = QGroupBox("执行模式")
        self.runtime_group.setObjectName("runtime_group")
        runtime_layout = QHBoxLayout(self.runtime_group)
        runtime_layout.setContentsMargins(12, 8, 12, 8)
        runtime_layout.setSpacing(12)

        self.runtime_backend_combo = QComboBox(self)
        self.runtime_backend_combo.setObjectName("runtime_backend_combo")
        self._style_settings_combo(self.runtime_backend_combo)
        self.runtime_backend_combo.addItem("原生", "native")
        self.runtime_backend_combo.addItem("插件", "plugin")
        configured_backend = str(
            self.current_config.get("input_backend", "native") or "native"
        ).strip().lower()
        initial_engine = canonicalize_screenshot_engine(
            self.current_config.get("screenshot_engine") or "wgc"
        )
        if configured_backend == "plugin" or is_plugin_screenshot_engine(initial_engine):
            initial_backend = "plugin"
        else:
            initial_backend = "native"
        backend_index = self.runtime_backend_combo.findData(initial_backend)
        if backend_index >= 0:
            self.runtime_backend_combo.setCurrentIndex(backend_index)
        self.runtime_backend_combo.setToolTip(
            "选择「原生」或「插件」后显示对应参数，并在保存时启用该模式。"
        )
        runtime_layout.addWidget(_labeled_field("执行模式:", self.runtime_backend_combo), 1)

        self.plugin_bind_kind_combo = QComboBox(self)
        self.plugin_bind_kind_combo.setObjectName("plugin_bind_kind_combo")
        self._style_settings_combo(self.plugin_bind_kind_combo)
        for kind in PLUGIN_BIND_KINDS:
            self.plugin_bind_kind_combo.addItem(plugin_bind_kind_label(kind), kind)
        kind_index = self.plugin_bind_kind_combo.findData(configured_kind)
        if kind_index >= 0:
            self.plugin_bind_kind_combo.setCurrentIndex(kind_index)
        self.plugin_bind_kind_combo.setToolTip(
            "基础绑定：大漠 BindWindow 缩写参数。\n"
            "高级绑定：大漠 BindWindowEx 明细参数。"
        )
        self.plugin_bind_kind_row = _labeled_field("绑定方式:", self.plugin_bind_kind_combo)
        self.plugin_bind_kind_row.setObjectName("plugin_bind_kind_row")
        runtime_layout.addWidget(self.plugin_bind_kind_row, 1)
        exec_layout.addWidget(self.runtime_group)

        self.native_mode_panel = QWidget()
        self.native_mode_panel.setObjectName("native_mode_panel")
        native_panel_layout = QVBoxLayout(self.native_mode_panel)
        native_panel_layout.setContentsMargins(0, 0, 0, 0)
        native_panel_layout.setSpacing(10)

        self.exec_mode_group = QGroupBox("运行参数")
        exec_mode_layout = QVBoxLayout(self.exec_mode_group)
        exec_mode_layout.setSpacing(4)
        exec_mode_layout.setContentsMargins(12, 8, 12, 8)

        self.mode_select_widget = QWidget()
        mode_select_layout = QHBoxLayout(self.mode_select_widget)
        mode_select_layout.setContentsMargins(0, 0, 0, 0)
        mode_select_layout.setSpacing(6)
        mode_label = QLabel("运行方式:")
        mode_label.setFixedWidth(80)
        self.mode_combo = QComboBox(self)
        self._style_settings_combo(self.mode_combo)
        self.mode_combo.clear()
        for internal_mode, display_mode in self.MODE_DISPLAY_MAP.items():
            self.mode_combo.addItem(display_mode, internal_mode)
        configured_native_mode = self.current_config.get(
            "native_execution_mode",
            self.current_config.get("execution_mode", "background_sendmessage"),
        )
        internal_mode = str(configured_native_mode or "background_sendmessage").strip().lower()
        index = self.mode_combo.findData(internal_mode)
        if index < 0:
            raise ValueError(f"未知的执行模式: {configured_native_mode!r}")
        self.mode_combo.setCurrentIndex(index)
        mode_select_layout.addWidget(mode_label)
        mode_select_layout.addWidget(self.mode_combo)
        exec_mode_layout.addWidget(self.mode_select_widget)

        self.native_input_panel = QWidget()
        self.input_backend_group = self.native_input_panel
        native_input_layout = QVBoxLayout(self.native_input_panel)
        native_input_layout.setContentsMargins(0, 0, 0, 0)
        native_input_layout.setSpacing(4)

        self.foreground_driver_widget = QWidget()
        foreground_driver_layout = QHBoxLayout(self.foreground_driver_widget)
        foreground_driver_layout.setContentsMargins(0, 0, 0, 0)
        foreground_driver_label = QLabel("鼠标驱动:")
        foreground_driver_label.setFixedWidth(80)
        self.foreground_driver_combo = QComboBox(self)
        self._style_settings_combo(self.foreground_driver_combo)
        for display_name, backend in self.FOREGROUND_DRIVER_BACKEND_MAP.items():
            self.foreground_driver_combo.addItem(display_name, backend)
        configured_mouse_backend, configured_keyboard_backend = parse_foreground_backends(
            self.current_config
        )
        backend_index = self.foreground_driver_combo.findData(configured_mouse_backend)
        if backend_index >= 0:
            self.foreground_driver_combo.setCurrentIndex(backend_index)
        foreground_driver_layout.addWidget(foreground_driver_label)
        foreground_driver_layout.addWidget(self.foreground_driver_combo)
        native_input_layout.addWidget(self.foreground_driver_widget)

        self.foreground_keyboard_driver_widget = QWidget()
        foreground_keyboard_driver_layout = QHBoxLayout(self.foreground_keyboard_driver_widget)
        foreground_keyboard_driver_layout.setContentsMargins(0, 0, 0, 0)
        foreground_keyboard_driver_label = QLabel("键盘驱动:")
        foreground_keyboard_driver_label.setFixedWidth(80)
        self.foreground_keyboard_driver_combo = QComboBox(self)
        self._style_settings_combo(self.foreground_keyboard_driver_combo)
        for display_name, backend in self.FOREGROUND_DRIVER_BACKEND_MAP.items():
            self.foreground_keyboard_driver_combo.addItem(display_name, backend)
        keyboard_backend_index = self.foreground_keyboard_driver_combo.findData(
            configured_keyboard_backend
        )
        if keyboard_backend_index >= 0:
            self.foreground_keyboard_driver_combo.setCurrentIndex(keyboard_backend_index)
        foreground_keyboard_driver_layout.addWidget(foreground_keyboard_driver_label)
        foreground_keyboard_driver_layout.addWidget(self.foreground_keyboard_driver_combo)
        native_input_layout.addWidget(self.foreground_keyboard_driver_widget)

        self.ib_driver_widget = QWidget()
        ib_driver_layout = QHBoxLayout(self.ib_driver_widget)
        ib_driver_layout.setContentsMargins(0, 0, 0, 0)
        ib_driver_label = QLabel("Ib驱动类型:")
        ib_driver_label.setFixedWidth(80)
        self.ib_driver_combo = QComboBox(self)
        self._style_settings_combo(self.ib_driver_combo)
        for display_name, ib_driver in self.IB_DRIVER_MAP.items():
            self.ib_driver_combo.addItem(display_name, ib_driver)
        configured_ib_driver = str(
            self.current_config.get("ibinputsimulator_driver", "Logitech") or "Logitech"
        ).strip()
        ib_driver_index = self.ib_driver_combo.findData(configured_ib_driver)
        if ib_driver_index < 0:
            ib_driver_index = self.ib_driver_combo.findData("Logitech")
        if ib_driver_index >= 0:
            self.ib_driver_combo.setCurrentIndex(ib_driver_index)
        ib_driver_layout.addWidget(ib_driver_label)
        ib_driver_layout.addWidget(self.ib_driver_combo)
        native_input_layout.addWidget(self.ib_driver_widget)

        self.foreground_py_backend_widget = QWidget()
        foreground_py_backend_layout = QHBoxLayout(self.foreground_py_backend_widget)
        foreground_py_backend_layout.setContentsMargins(0, 0, 0, 0)
        foreground_py_backend_label = QLabel("输入方式:")
        foreground_py_backend_label.setFixedWidth(80)
        self.foreground_py_backend_combo = QComboBox(self)
        self._style_settings_combo(self.foreground_py_backend_combo)
        for display_name, backend in self.FOREGROUND_PY_BACKEND_MAP.items():
            self.foreground_py_backend_combo.addItem(display_name, backend)
        configured_py_backend = parse_foreground_py_backend(self.current_config)
        py_backend_index = self.foreground_py_backend_combo.findData(configured_py_backend)
        if py_backend_index >= 0:
            self.foreground_py_backend_combo.setCurrentIndex(py_backend_index)
        self.foreground_py_backend_combo.setToolTip(
            "PyAutoGUI: 原前台二输入\n"
            "扫描码: SendInput 硬件扫描码（对应 normal.hd），不是驱动"
        )
        foreground_py_backend_layout.addWidget(foreground_py_backend_label)
        foreground_py_backend_layout.addWidget(self.foreground_py_backend_combo)
        native_input_layout.addWidget(self.foreground_py_backend_widget)
        exec_mode_layout.addWidget(self.native_input_panel)
        native_panel_layout.addWidget(self.exec_mode_group)

        self.screenshot_engine_group = QGroupBox("截图方式")
        screenshot_engine_layout = QVBoxLayout(self.screenshot_engine_group)
        screenshot_engine_layout.setSpacing(4)
        screenshot_engine_layout.setContentsMargins(12, 8, 12, 8)

        self.screenshot_engine_map = {
            engine_label_text(engine): engine for engine in SUPPORTED_SCREENSHOT_ENGINES
        }
        self.screenshot_engine_reverse_map = {
            engine: engine_label_text(engine) for engine in SUPPORTED_SCREENSHOT_ENGINES
        }

        screenshot_engine_row = QHBoxLayout()
        screenshot_engine_row.setSpacing(6)
        engine_label_widget = QLabel("截图引擎:")
        engine_label_widget.setFixedWidth(80)
        self.screenshot_engine_combo = QComboBox(self)
        self.screenshot_engine_combo.setObjectName("screenshot_engine_combo")
        self._style_settings_combo(self.screenshot_engine_combo)
        self.screenshot_engine_combo.setToolTip(
            "原生截图：WGC / PrintWindow（支持后台）；GDI / DXGI（仅前台）。"
        )
        screenshot_engine_row.addWidget(engine_label_widget)
        screenshot_engine_row.addWidget(self.screenshot_engine_combo, 1)
        screenshot_engine_layout.addLayout(screenshot_engine_row)
        native_panel_layout.addWidget(self.screenshot_engine_group)
        exec_layout.addWidget(self.native_mode_panel)

        self.plugin_mode_panel = QWidget()
        self.plugin_mode_panel.setObjectName("plugin_mode_panel")
        plugin_panel_layout = QVBoxLayout(self.plugin_mode_panel)
        plugin_panel_layout.setContentsMargins(0, 0, 0, 0)
        plugin_panel_layout.setSpacing(10)

        input_group = QGroupBox("键鼠")
        input_layout = QVBoxLayout(input_group)
        input_layout.setSpacing(8)
        input_layout.setContentsMargins(12, 8, 12, 8)

        self.plugin_input_panel = QWidget()
        plugin_input_grid = QGridLayout(self.plugin_input_panel)
        plugin_input_grid.setContentsMargins(0, 0, 0, 0)
        plugin_input_grid.setHorizontalSpacing(12)
        plugin_input_grid.setVerticalSpacing(8)
        plugin_input_grid.setColumnStretch(0, 1)
        plugin_input_grid.setColumnStretch(1, 1)

        self.plugin_mouse_combo = QComboBox(self)
        self.plugin_mouse_combo.setObjectName("plugin_mouse_combo")
        self._style_settings_combo(self.plugin_mouse_combo)
        self.plugin_mouse_combo.setMaxVisibleItems(16)
        plugin_input_grid.addWidget(_labeled_field("鼠标模式:", self.plugin_mouse_combo), 0, 0)

        self.plugin_keypad_combo = QComboBox(self)
        self.plugin_keypad_combo.setObjectName("plugin_keypad_combo")
        self._style_settings_combo(self.plugin_keypad_combo)
        self.plugin_keypad_combo.setMaxVisibleItems(12)
        plugin_input_grid.addWidget(_labeled_field("键盘模式:", self.plugin_keypad_combo), 0, 1)

        self.plugin_input_display_combo = QComboBox(self)
        self.plugin_input_display_combo.setObjectName("plugin_input_display_combo")
        self._style_settings_combo(self.plugin_input_display_combo)
        self.plugin_input_display_combo.setMaxVisibleItems(14)
        self.plugin_input_display_combo.setToolTip(
            "跟随截图开启时显示当前对齐值且不可改；关闭跟随后可手动选择。"
        )
        self.plugin_input_display_row = _labeled_field("绑定图显:", self.plugin_input_display_combo)
        self.plugin_input_display_row.setObjectName("plugin_input_display_row")
        plugin_input_grid.addWidget(self.plugin_input_display_row, 1, 0)

        self.plugin_bind_mode_combo = QComboBox(self)
        self.plugin_bind_mode_combo.setObjectName("plugin_bind_mode_combo")
        self.plugin_bind_mode_combo.setEditable(False)
        self._style_settings_combo(self.plugin_bind_mode_combo)
        self.plugin_bind_mode_combo.setMaxVisibleItems(14)
        self.plugin_bind_mode_combo.setToolTip(
            "大漠绑定 mode。基础绑定用 0/2（及兼容扩展）；\n"
            "高级绑定用 101/103 超级绑定。"
        )
        self.plugin_advanced_panel = _labeled_field("绑定模式:", self.plugin_bind_mode_combo)
        self.plugin_advanced_panel.setObjectName("plugin_advanced_panel")
        plugin_input_grid.addWidget(self.plugin_advanced_panel, 1, 1)

        self.plugin_input_display_follow_check = QCheckBox("绑定图显跟随截图", self)
        self.plugin_input_display_follow_check.setObjectName("plugin_input_display_follow_check")
        self.plugin_input_display_follow_check.setChecked(
            bool(self.current_config.get("plugin_input_display_follow", True))
        )
        self.plugin_input_display_follow_check.setToolTip(
            "开启后绑定图显自动对齐当前插件截图引擎（下方只读同步）。"
        )

        self.plugin_text_ime_check = QCheckBox("文本走输入法通道", self)
        self.plugin_text_ime_check.setObjectName("plugin_text_ime_check")
        self.plugin_text_ime_check.setChecked(bool(self.current_config.get("plugin_text_ime", False)))
        self.plugin_text_ime_check.setToolTip(
            "非 ASCII 文本优先用大漠 SendStringIme 输入，绑定时附带 dx.public.input.ime；\n"
            "游戏类窗口通常只认这条路。需要大漠付费功能。"
        )

        self.plugin_fake_active_check = QCheckBox("后台假激活", self)
        self.plugin_fake_active_check.setObjectName("plugin_fake_active_check")
        self.plugin_fake_active_check.setChecked(bool(self.current_config.get("plugin_fake_active", False)))
        self.plugin_fake_active_check.setToolTip(
            "绑定成功后调用 EnableFakeActive(1)，让窗口在非激活状态下也接受键鼠；\n"
            "部分对消息校验严格的窗口需要开启，可能让前台操作影响后台，默认关闭。"
        )

        plugin_option_row = QWidget(self)
        plugin_option_row.setObjectName("plugin_option_row")
        plugin_option_layout = QHBoxLayout(plugin_option_row)
        plugin_option_layout.setContentsMargins(0, 0, 0, 0)
        plugin_option_layout.setSpacing(16)
        plugin_option_layout.addWidget(self.plugin_input_display_follow_check)
        plugin_option_layout.addWidget(self.plugin_text_ime_check)
        plugin_option_layout.addWidget(self.plugin_fake_active_check)
        plugin_option_layout.addStretch(1)
        plugin_input_grid.addWidget(plugin_option_row, 2, 0, 1, 2)

        input_layout.addWidget(self.plugin_input_panel)
        plugin_panel_layout.addWidget(input_group)

        plugin_shot_group = QGroupBox("截图方式")
        plugin_shot_layout = QGridLayout(plugin_shot_group)
        plugin_shot_layout.setContentsMargins(12, 8, 12, 8)
        plugin_shot_layout.setHorizontalSpacing(12)
        plugin_shot_layout.setVerticalSpacing(8)
        plugin_shot_layout.setColumnStretch(0, 1)
        plugin_shot_layout.setColumnStretch(1, 1)

        self.plugin_screenshot_engine_combo = QComboBox(self)
        self.plugin_screenshot_engine_combo.setObjectName("plugin_screenshot_engine_combo")
        self._style_settings_combo(self.plugin_screenshot_engine_combo)
        self.plugin_screenshot_engine_combo.setMaxVisibleItems(14)
        self.plugin_screenshot_engine_combo.setToolTip(
            "随同组「绑定方式」切换：基础为缩写图色，高级为 D3D/OpenGL 明细。"
        )
        self.plugin_screenshot_panel = _labeled_field(
            "截图引擎:", self.plugin_screenshot_engine_combo
        )
        self.plugin_screenshot_panel.setObjectName("plugin_screenshot_panel")
        plugin_shot_layout.addWidget(self.plugin_screenshot_panel, 0, 0)
        # 边改参数边对绑定列表试绑，结果直接写在这里，不另加按钮
        self.plugin_bind_probe_status_label = QLabel("", self)
        self.plugin_bind_probe_status_label.setObjectName("plugin_bind_probe_status_label")
        self.plugin_bind_probe_status_label.setWordWrap(True)
        self.plugin_bind_probe_status_label.setStyleSheet(f"color: {get_secondary_text_color()};")
        self.plugin_bind_probe_status_label.setVisible(False)
        plugin_shot_layout.addWidget(self.plugin_bind_probe_status_label, 0, 1)
        plugin_panel_layout.addWidget(plugin_shot_group)
        exec_layout.addWidget(self.plugin_mode_panel)

        self._plugin_bind_kind_values = {}
        self._refresh_plugin_bind_param_combos(
            preferred_mouse=self.current_config.get("plugin_mouse", "normal"),
            preferred_keypad=self.current_config.get("plugin_keypad", "normal"),
            preferred_display=self.current_config.get("plugin_input_display", "normal"),
            preferred_mode=self.current_config.get("plugin_bind_mode", 0),
            preferred_shot=(
                initial_engine if is_plugin_screenshot_engine(initial_engine) else "normal"
            ),
        )
        self._plugin_bind_kind_active = self._current_plugin_bind_kind()
        self._remember_plugin_bind_kind_values(self._plugin_bind_kind_active)
        self.plugin_bind_kind_combo.currentIndexChanged.connect(self._on_plugin_bind_kind_changed)

        self.mode_combo.currentTextChanged.connect(self._update_screenshot_engine_visibility)
        self.mode_combo.currentTextChanged.connect(self._on_execution_driver_setting_changed)
        self.mode_combo.currentIndexChanged.connect(self._update_screenshot_engine_visibility)
        self.mode_combo.currentIndexChanged.connect(self._on_execution_driver_setting_changed)
        self.foreground_driver_combo.currentTextChanged.connect(self._on_execution_driver_setting_changed)
        self.foreground_driver_combo.currentIndexChanged.connect(self._on_execution_driver_setting_changed)
        self.foreground_keyboard_driver_combo.currentTextChanged.connect(
            self._on_execution_driver_setting_changed
        )
        self.foreground_keyboard_driver_combo.currentIndexChanged.connect(
            self._on_execution_driver_setting_changed
        )
        self.runtime_backend_combo.currentIndexChanged.connect(self._on_runtime_backend_changed)
        self.plugin_input_display_follow_check.toggled.connect(self._on_plugin_input_display_follow_toggled)
        self.plugin_screenshot_engine_combo.currentIndexChanged.connect(
            self._on_screenshot_engine_changed
        )

        self._screenshot_engine_combo_ready = False
        self._update_screenshot_engine_visibility()
        self._update_runtime_backend_panels()
        self._update_input_backend_visibility()
        self.screenshot_engine_combo.currentIndexChanged.connect(self._on_screenshot_engine_changed)
        self._screenshot_engine_combo_ready = True
        self._sync_plugin_input_display_follow()

        for combo in (
            self.runtime_backend_combo,
            self.plugin_bind_kind_combo,
            self.plugin_mouse_combo,
            self.plugin_keypad_combo,
            self.plugin_input_display_combo,
            self.plugin_bind_mode_combo,
            self.plugin_screenshot_engine_combo,
        ):
            combo.currentIndexChanged.connect(self._request_live_plugin_reprobe)
        self.plugin_input_display_follow_check.toggled.connect(self._request_live_plugin_reprobe)
        self.plugin_text_ime_check.toggled.connect(self._request_live_plugin_reprobe)
        self.plugin_fake_active_check.toggled.connect(self._request_live_plugin_reprobe)
        self._plugin_live_probe_ready = True

        exec_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("execution_mode_scroll")
        scroll.setWidgetResizable(True)
        scroll.setSizeAdjustPolicy(QScrollArea.SizeAdjustPolicy.AdjustToContents)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        self.exec_tab = scroll
        self.tab_widget.addTab(scroll, "执行模式")

    def _on_plugin_input_display_follow_toggled(self, _checked: bool = False) -> None:
        self._sync_plugin_input_display_follow()

    def _on_runtime_backend_changed(self, *_args) -> None:
        self._update_runtime_backend_panels(resize_dialog=True)
        self._update_input_backend_visibility(resize_dialog=False)
        if self._selected_input_backend() == "native":
            # 让插件模式下尚未完成的旧试绑回调立即失效；再次切回插件时重新试绑。
            self._plugin_live_probe_generation = int(getattr(self, "_plugin_live_probe_generation", 0)) + 1
            self._plugin_live_probe_key = None
        if hasattr(self, "_refresh_plugin_probe_feedback"):
            self._refresh_plugin_probe_feedback()

    def _uses_plugin_screenshot(self) -> bool:
        return self._selected_input_backend() == "plugin"

    def _update_runtime_backend_panels(self, *, resize_dialog: bool = False) -> None:
        """按运行后端下拉显示原生或插件参数面板。"""
        use_plugin = self._selected_input_backend() == "plugin"
        if hasattr(self, "native_mode_panel"):
            self.native_mode_panel.setVisible(not use_plugin)
        if hasattr(self, "plugin_mode_panel"):
            self.plugin_mode_panel.setVisible(use_plugin)
        if hasattr(self, "plugin_bind_kind_row"):
            self.plugin_bind_kind_row.setVisible(use_plugin)
        if use_plugin:
            if hasattr(self, "plugin_input_panel"):
                self.plugin_input_panel.setVisible(True)
            if hasattr(self, "plugin_screenshot_panel"):
                self.plugin_screenshot_panel.setVisible(True)
            if hasattr(self, "plugin_input_display_row"):
                self.plugin_input_display_row.setVisible(True)
            if hasattr(self, "plugin_advanced_panel"):
                self.plugin_advanced_panel.setVisible(True)
            if hasattr(self, "plugin_bind_mode_combo"):
                self.plugin_bind_mode_combo.setVisible(True)
            self._sync_plugin_input_display_follow()
        if resize_dialog and self.isVisible():
            QTimer.singleShot(0, self._adjust_dialog_height_only)

    def _update_plugin_mode_panels(self, *, resize_dialog: bool = False) -> None:
        """兼容旧调用名。"""
        self._update_runtime_backend_panels(resize_dialog=resize_dialog)

    def _current_plugin_bind_kind(self) -> str:
        from utils.plugin.bind_modes import PLUGIN_BIND_KIND_BASIC, normalize_plugin_bind_kind

        if hasattr(self, "plugin_bind_kind_combo"):
            try:
                return normalize_plugin_bind_kind(self.plugin_bind_kind_combo.currentData())
            except ValueError:
                pass
        return PLUGIN_BIND_KIND_BASIC

    def _on_plugin_bind_kind_changed(self, *_args) -> None:
        previous_kind = getattr(self, "_plugin_bind_kind_active", None)
        if previous_kind:
            self._remember_plugin_bind_kind_values(previous_kind)
        kind = self._current_plugin_bind_kind()
        preferred = getattr(self, "_plugin_bind_kind_values", {}).get(kind, {})
        self._refresh_plugin_bind_param_combos(
            preferred_mouse=preferred.get("mouse"),
            preferred_keypad=preferred.get("keypad"),
            preferred_display=preferred.get("display"),
            preferred_mode=preferred.get("mode"),
            preferred_shot=preferred.get("shot"),
        )
        self._plugin_bind_kind_active = kind
        self._remember_plugin_bind_kind_values(kind)
        self._sync_plugin_input_display_follow()

    def _remember_plugin_bind_kind_values(self, kind: str) -> None:
        """Remember each BindWindow flavor independently while its controls are hidden."""
        if not kind or not hasattr(self, "plugin_mouse_combo"):
            return
        values = getattr(self, "_plugin_bind_kind_values", None)
        if values is None:
            values = self._plugin_bind_kind_values = {}
        values[kind] = {
            "mouse": self.plugin_mouse_combo.currentData(),
            "keypad": self.plugin_keypad_combo.currentData(),
            "display": self.plugin_input_display_combo.currentData(),
            "mode": self.plugin_bind_mode_combo.currentData(),
            "shot": self.plugin_screenshot_engine_combo.currentData(),
        }

    def _refresh_plugin_bind_param_combos(
        self,
        *,
        preferred_mouse=None,
        preferred_keypad=None,
        preferred_display=None,
        preferred_mode=None,
        preferred_shot=None,
    ) -> None:
        from utils.plugin.bind_modes import (
            PLUGIN_BIND_KIND_ADVANCED,
            clamp_choice,
            plugin_bind_mode_label,
            plugin_bind_mode_options_for_kind,
            plugin_bind_mode_tooltip,
            plugin_display_options_for_kind,
            plugin_keypad_label,
            plugin_keypad_options_for_kind,
            plugin_mouse_label,
            plugin_mouse_options_for_kind,
        )
        from utils.capture.engine_ids import screenshot_engine_label

        kind = self._current_plugin_bind_kind()
        mouse_options = plugin_mouse_options_for_kind(kind)
        keypad_options = plugin_keypad_options_for_kind(kind)
        display_options = plugin_display_options_for_kind(kind)
        mode_options = plugin_bind_mode_options_for_kind(kind)
        default_mouse = "dx.mouse.api" if kind == PLUGIN_BIND_KIND_ADVANCED else "normal"
        default_keypad = "dx.keypad.api" if kind == PLUGIN_BIND_KIND_ADVANCED else "normal"
        default_display = "opengl" if kind == PLUGIN_BIND_KIND_ADVANCED else "normal"
        default_mode = 101 if kind == PLUGIN_BIND_KIND_ADVANCED else 0

        if preferred_mouse is None and hasattr(self, "plugin_mouse_combo"):
            preferred_mouse = self.plugin_mouse_combo.currentData()
        if preferred_keypad is None and hasattr(self, "plugin_keypad_combo"):
            preferred_keypad = self.plugin_keypad_combo.currentData()
        if preferred_display is None and hasattr(self, "plugin_input_display_combo"):
            preferred_display = self.plugin_input_display_combo.currentData()
        if preferred_mode is None and hasattr(self, "plugin_bind_mode_combo"):
            preferred_mode = self.plugin_bind_mode_combo.currentData()
        if preferred_shot is None and hasattr(self, "plugin_screenshot_engine_combo"):
            preferred_shot = self.plugin_screenshot_engine_combo.currentData()

        if hasattr(self, "plugin_mouse_combo"):
            self._fill_value_combo(self.plugin_mouse_combo, mouse_options, plugin_mouse_label)
            idx = self.plugin_mouse_combo.findData(
                clamp_choice(preferred_mouse, mouse_options, default_mouse)
            )
            if idx >= 0:
                self.plugin_mouse_combo.setCurrentIndex(idx)
        if hasattr(self, "plugin_keypad_combo"):
            self._fill_value_combo(self.plugin_keypad_combo, keypad_options, plugin_keypad_label)
            idx = self.plugin_keypad_combo.findData(
                clamp_choice(preferred_keypad, keypad_options, default_keypad)
            )
            if idx >= 0:
                self.plugin_keypad_combo.setCurrentIndex(idx)
        if hasattr(self, "plugin_input_display_combo"):
            self._fill_value_combo(
                self.plugin_input_display_combo, display_options, screenshot_engine_label
            )
            idx = self.plugin_input_display_combo.findData(
                clamp_choice(preferred_display, display_options, default_display)
            )
            if idx >= 0:
                self.plugin_input_display_combo.setCurrentIndex(idx)
        if hasattr(self, "plugin_bind_mode_combo"):
            self._fill_value_combo(
                self.plugin_bind_mode_combo, mode_options, plugin_bind_mode_label
            )
            idx = self.plugin_bind_mode_combo.findData(
                clamp_choice(preferred_mode, mode_options, default_mode)
            )
            if idx >= 0:
                self.plugin_bind_mode_combo.setCurrentIndex(idx)
            for i in range(self.plugin_bind_mode_combo.count()):
                mode_data = self.plugin_bind_mode_combo.itemData(i)
                try:
                    self.plugin_bind_mode_combo.setItemData(
                        i, plugin_bind_mode_tooltip(mode_data), Qt.ItemDataRole.ToolTipRole
                    )
                except (TypeError, ValueError):
                    pass
        if hasattr(self, "plugin_screenshot_engine_combo"):
            self._fill_value_combo(
                self.plugin_screenshot_engine_combo, display_options, screenshot_engine_label
            )
            idx = self.plugin_screenshot_engine_combo.findData(
                clamp_choice(preferred_shot, display_options, default_display)
            )
            if idx >= 0:
                self.plugin_screenshot_engine_combo.setCurrentIndex(idx)

    def _followed_plugin_input_display(self) -> str:
        from utils.capture.engine_ids import (
            canonicalize_screenshot_engine,
            is_plugin_screenshot_engine,
        )
        from utils.plugin.bind_modes import clamp_choice, plugin_display_options_for_kind

        engine = canonicalize_screenshot_engine(self._get_selected_screenshot_engine())
        if is_plugin_screenshot_engine(engine):
            options = plugin_display_options_for_kind(self._current_plugin_bind_kind())
            return str(clamp_choice(engine, options, options[0]))
        options = plugin_display_options_for_kind(self._current_plugin_bind_kind())
        return str(options[0] if options else "normal")

    def _sync_plugin_input_display_follow(self) -> None:
        if not hasattr(self, "plugin_input_display_combo"):
            return
        follow = True
        if hasattr(self, "plugin_input_display_follow_check"):
            follow = bool(self.plugin_input_display_follow_check.isChecked())
        if hasattr(self, "plugin_input_display_row"):
            self.plugin_input_display_row.setVisible(True)
        if follow:
            target = self._followed_plugin_input_display()
            index = self.plugin_input_display_combo.findData(target)
            if index >= 0 and self.plugin_input_display_combo.currentIndex() != index:
                self.plugin_input_display_combo.blockSignals(True)
                try:
                    self.plugin_input_display_combo.setCurrentIndex(index)
                finally:
                    self.plugin_input_display_combo.blockSignals(False)
        self.plugin_input_display_combo.setEnabled(not follow)

    def _update_screenshot_engine_visibility(self):
        """按前后台刷新原生截图引擎列表。"""
        previous_ready = getattr(self, "_screenshot_engine_combo_ready", False)
        self._screenshot_engine_combo_ready = False
        try:
            self._rebuild_screenshot_engine_options()
        finally:
            self._screenshot_engine_combo_ready = previous_ready

    def _is_foreground_execution_mode(self) -> bool:
        internal_mode = self.mode_combo.currentData()
        if not internal_mode:
            current_mode = self.mode_combo.currentText()
            internal_mode = self.MODE_INTERNAL_MAP.get(current_mode, "")
        return str(internal_mode or "").startswith("foreground")

    def _rebuild_screenshot_engine_options(self):
        from utils.capture.engine_ids import (
            canonicalize_screenshot_engine,
            engines_for_ui_group,
            is_native_screenshot_engine,
            screenshot_engine_label,
        )

        if not hasattr(self, "screenshot_engine_combo"):
            return
        background_only = not self._is_foreground_execution_mode()
        scope = "background" if background_only else "foreground"
        remembered_engines = getattr(self, "_native_screenshot_engine_values", None)
        if remembered_engines is None:
            remembered_engines = self._native_screenshot_engine_values = {}
        configured = canonicalize_screenshot_engine(
            (getattr(self, "current_config", {}) or {}).get("screenshot_engine") or "wgc"
        )
        current_engine = canonicalize_screenshot_engine(
            self.screenshot_engine_combo.currentData()
            or (configured if is_native_screenshot_engine(configured) else "wgc")
        )
        if not is_native_screenshot_engine(current_engine):
            current_engine = "wgc"

        engines = engines_for_ui_group("原生", background_only=background_only)
        previous_scope = getattr(self, "_native_screenshot_engine_scope", None)
        if previous_scope and is_native_screenshot_engine(current_engine):
            remembered_engines[previous_scope] = current_engine
        remembered = canonicalize_screenshot_engine(remembered_engines.get(scope))
        if remembered in engines:
            current_engine = remembered
        elif current_engine not in engines:
            configured_native = configured if configured in engines else ""
            current_engine = configured_native or (engines[0] if engines else "")
        self.screenshot_engine_combo.clear()
        for engine in engines:
            self.screenshot_engine_combo.addItem(screenshot_engine_label(engine), engine)

        index = self.screenshot_engine_combo.findData(current_engine)
        if index < 0 and self.screenshot_engine_combo.count() > 0:
            index = 0
        if index >= 0:
            self.screenshot_engine_combo.setCurrentIndex(index)
        item_count = self.screenshot_engine_combo.count()
        if item_count > 0:
            self.screenshot_engine_combo.setMaxVisibleItems(min(item_count, 12))
        self._native_screenshot_engine_scope = scope

    def _get_selected_screenshot_engine(self) -> str:
        if self._uses_plugin_screenshot() and hasattr(self, "plugin_screenshot_engine_combo"):
            engine = self.plugin_screenshot_engine_combo.currentData()
            if engine:
                return str(engine).strip().lower()
        if not hasattr(self, "screenshot_engine_combo"):
            return str(
                (getattr(self, "current_config", {}) or {}).get("screenshot_engine") or ""
            ).strip().lower()
        engine = self.screenshot_engine_combo.currentData()
        if engine:
            return str(engine).strip().lower()
        display_name = self.screenshot_engine_combo.currentText()
        mapped = self.screenshot_engine_map.get(display_name)
        return str(mapped or "").strip().lower()

    def _is_wgc_desktop_combination(self) -> bool:
        from utils.window.window_identity import is_wgc_with_desktop_target

        return is_wgc_with_desktop_target(
            self._get_selected_screenshot_engine(),
            getattr(self, "bound_windows", None),
        )

    def _warn_wgc_desktop_engine(self) -> None:
        from utils.window.window_identity import WGC_DESKTOP_ENGINE_MESSAGE

        QMessageBox.warning(self, "请修改截图引擎", WGC_DESKTOP_ENGINE_MESSAGE)

    def _schedule_wgc_desktop_engine_warning(self) -> None:
        """绑定流程里不能立刻弹窗，否则会挡住窗口选择遮罩的关闭。"""
        if not self._is_wgc_desktop_combination():
            return
        if getattr(self, "_wgc_desktop_warning_scheduled", False):
            return
        self._wgc_desktop_warning_scheduled = True
        QTimer.singleShot(0, self._flush_wgc_desktop_engine_warning)

    def _flush_wgc_desktop_engine_warning(self) -> None:
        overlay = getattr(self, "window_picker_overlay", None)
        try:
            overlay_blocking = overlay is not None and overlay.isVisible()
        except RuntimeError:
            overlay_blocking = False
        retries = int(getattr(self, "_wgc_desktop_warning_retries", 0) or 0)
        if overlay_blocking or not self.isVisible():
            if retries < 20:
                self._wgc_desktop_warning_retries = retries + 1
                QTimer.singleShot(50, self._flush_wgc_desktop_engine_warning)
                return
        self._wgc_desktop_warning_retries = 0
        self._wgc_desktop_warning_scheduled = False
        if self._is_wgc_desktop_combination():
            self._warn_wgc_desktop_engine()

    def _on_screenshot_engine_changed(self, _index: int = 0) -> None:
        if not getattr(self, "_screenshot_engine_combo_ready", False):
            return
        self._sync_plugin_input_display_follow()
        if self._is_wgc_desktop_combination():
            self._warn_wgc_desktop_engine()

    def _hotkey_capture_buttons(self):
        return [
            getattr(self, name)
            for name in (
                "start_task_hotkey",
                "stop_task_hotkey",
                "pause_workflow_hotkey",
                "record_hotkey",
                "replay_hotkey",
                "close_listen_hotkey",
            )
            if hasattr(self, name)
        ]

    def _stop_other_hotkey_captures(self, current=None):
        for button in self._hotkey_capture_buttons():
            if button is current:
                continue
            if hasattr(button, "stop_listening"):
                button.stop_listening(restore=True)

    def _sync_hotkey_except_key(self):
        except_key = self.close_listen_hotkey.key_value() if hasattr(self, "close_listen_hotkey") else ""
        for button in self._hotkey_capture_buttons():
            if button is getattr(self, "close_listen_hotkey", None):
                button.set_except_hotkey("")
            elif hasattr(button, "set_except_hotkey"):
                button.set_except_hotkey(except_key)

    def _make_hotkey_field(self, title: str, config_key: str, tooltip: str):
        cell = QWidget()
        container = QVBoxLayout(cell)
        container.setContentsMargins(0, 0, 0, 0)
        container.setSpacing(6)
        label = QLabel(title)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setObjectName("hotkey_label")
        button = HotkeyCaptureButton(
            self.current_config.get(config_key, DEFAULT_HOTKEYS[config_key]),
            self,
        )
        button.setToolTip(tooltip)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        container.addWidget(label)
        container.addWidget(button)
        return cell, button

    def _create_hotkey_tab(self):
        """创建快捷键设置标签页"""
        hotkey_tab = QWidget()
        hotkey_layout = QVBoxLayout(hotkey_tab)
        hotkey_layout.setSpacing(8)
        hotkey_layout.setContentsMargins(10, 8, 10, 10)
        self.hotkey_group = QGroupBox("快捷键配置")
        hotkey_main_layout = QVBoxLayout(self.hotkey_group)
        hotkey_main_layout.setSpacing(12)
        # 底边多留一点，避免说明文字贴着 GroupBox 圆角被裁
        hotkey_main_layout.setContentsMargins(15, 15, 15, 18)

        start_task_cell, self.start_task_hotkey = self._make_hotkey_field(
            "启动任务",
            "start_task_hotkey",
            "点击后按下任意键或组合键，绑定启动任务快捷键",
        )
        stop_task_cell, self.stop_task_hotkey = self._make_hotkey_field(
            "停止任务",
            "stop_task_hotkey",
            "点击后按下任意键或组合键，绑定停止任务快捷键",
        )
        pause_cell, self.pause_workflow_hotkey = self._make_hotkey_field(
            "暂停工作流",
            "pause_workflow_hotkey",
            "点击后按下任意键或组合键，绑定暂停/恢复工作流快捷键",
        )
        record_cell, self.record_hotkey = self._make_hotkey_field(
            "录制操作",
            "record_hotkey",
            "点击后按下任意键或组合键。仅在录制卡片参数面板打开时生效",
        )
        replay_cell, self.replay_hotkey = self._make_hotkey_field(
            "回放操作",
            "replay_hotkey",
            "点击后按下任意键或组合键。仅在录制回放卡片参数面板打开时生效",
        )
        close_cell, self.close_listen_hotkey = self._make_hotkey_field(
            "关闭监听",
            "close_listen_hotkey",
            "关闭全局快捷键监听。关闭后仅该快捷键仍有效，可再次开启",
        )
        self.close_listen_hotkey.changed.connect(lambda _value: self._sync_hotkey_except_key())
        self._sync_hotkey_except_key()

        hotkey_grid = QGridLayout()
        hotkey_grid.setHorizontalSpacing(16)
        hotkey_grid.setVerticalSpacing(12)
        hotkey_grid.addWidget(start_task_cell, 0, 0)
        hotkey_grid.addWidget(stop_task_cell, 0, 1)
        hotkey_grid.addWidget(pause_cell, 0, 2)
        hotkey_grid.addWidget(record_cell, 0, 3)
        hotkey_grid.addWidget(replay_cell, 1, 0)
        hotkey_grid.addWidget(close_cell, 1, 1)
        for column in range(4):
            hotkey_grid.setColumnStretch(column, 1)

        hint = QLabel("点击按键框后按下任意键或组合键即可绑定。Esc 关闭本次监听，且不能作为快捷键。关闭监听后仅该快捷键仍有效。")
        hint.setWordWrap(True)
        hint.setObjectName("hotkey_hint")

        hotkey_main_layout.addLayout(hotkey_grid)
        hotkey_main_layout.addWidget(hint)
        hotkey_layout.addWidget(self.hotkey_group)
        hotkey_layout.addStretch()
        self.tab_widget.addTab(hotkey_tab, "快捷键设置")

    def _create_other_tab(self):
        """创建其他设置标签页"""
        other_tab = QWidget()
        other_layout = QVBoxLayout(other_tab)
        other_layout.setSpacing(16)
        other_layout.setContentsMargins(12, 12, 12, 12)
        # --- Custom Resolution Group ---
        resolution_group = QGroupBox("自定义绑定窗口分辨率（宽高都为 0 = 禁用）")
        resolution_layout = QFormLayout(resolution_group)
        resolution_layout.setSpacing(10)
        resolution_layout.setContentsMargins(16, 14, 16, 14)
        resolution_layout.setVerticalSpacing(10)
        self.width_spinbox = NoWheelSpinBox()
        self.width_spinbox.setRange(0, 9999)
        # 修复：允许保存和显示0值（禁用状态）
        default_width = self.current_config.get('custom_width', 0)
        self.width_spinbox.setValue(default_width)
        self.height_spinbox = NoWheelSpinBox()
        self.height_spinbox.setRange(0, 9999)
        # 修复：允许保存和显示0值（禁用状态）
        default_height = self.current_config.get('custom_height', 0)
        self.height_spinbox.setValue(default_height)
        self.width_spinbox.setToolTip("绑定窗口内容区域宽度（像素）。需与高度一起设置，单边为 0 无效。")
        self.height_spinbox.setToolTip("绑定窗口内容区域高度（像素）。需与宽度一起设置，单边为 0 无效。")
        resolution_layout.addRow("宽度:", self.width_spinbox)
        resolution_layout.addRow("高度:", self.height_spinbox)
        other_layout.addWidget(resolution_group)
        # --- Screenshot Format Group ---
        screenshot_group = QGroupBox("截图设置")
        screenshot_layout = QFormLayout(screenshot_group)
        screenshot_layout.setSpacing(10)
        screenshot_layout.setContentsMargins(16, 14, 16, 14)
        screenshot_layout.setVerticalSpacing(10)
        self.screenshot_format_combo = QComboBox(self)
        self.screenshot_format_combo.addItem("BMP (无压缩，体积大)", "bmp")
        self.screenshot_format_combo.addItem("PNG (无损压缩)", "png")
        self.screenshot_format_combo.addItem("JPG (有损压缩，体积小)", "jpg")
        # 加载当前配置
        current_format = self.current_config.get('screenshot_format', 'bmp')
        index = self.screenshot_format_combo.findData(current_format)
        if index >= 0:
            self.screenshot_format_combo.setCurrentIndex(index)
        screenshot_layout.addRow("截图格式:", self.screenshot_format_combo)
        other_layout.addWidget(screenshot_group)

        other_layout.addStretch(1)
        self.tab_widget.addTab(other_tab, "其他设置")

    def _create_plugin_auth_tab(self):
        """插件授权独立标签页：注册码与附加码。"""
        auth_tab = QWidget()
        auth_tab.setObjectName("plugin_auth_tab")
        page_layout = QVBoxLayout(auth_tab)
        page_layout.setSpacing(16)
        page_layout.setContentsMargins(12, 12, 12, 12)

        auth_group = QGroupBox("插件授权")
        auth_layout = QFormLayout(auth_group)
        auth_layout.setContentsMargins(16, 18, 16, 16)
        auth_layout.setHorizontalSpacing(12)
        auth_layout.setVerticalSpacing(14)
        auth_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        plugin_hint = (
            "插件运行库使用安装目录内 tools/plugin（PluginHost.exe / dm.dll / RegDll.dll）。"
            "注册码与附加码仅本机保存。附加码对应大漠后台「您的附加码」，可空；"
            "若后台开了附加白名单则必须填写。"
        )
        auth_hint = QLabel(plugin_hint)
        auth_hint.setWordWrap(True)
        auth_hint.setToolTip("目录固定为安装内 tools/plugin。注册码/附加码不会进入导出包。")
        auth_hint.setStyleSheet(f"color: {get_secondary_text_color()}; font-weight: normal;")
        auth_hint.setMinimumHeight(40)
        auth_layout.addRow(auth_hint)

        self.plugin_reg_code_edit = QLineEdit(self)
        self.plugin_reg_code_edit.setObjectName("plugin_reg_code_edit")
        self.plugin_reg_code_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.plugin_reg_code_edit.setText(str(self.current_config.get("plugin_reg_code", "") or ""))
        self.plugin_reg_code_edit.setToolTip(plugin_hint)
        auth_layout.addRow("注册码:", self.plugin_reg_code_edit)

        self.plugin_extra_code_edit = QLineEdit(self)
        self.plugin_extra_code_edit.setObjectName("plugin_extra_code_edit")
        self.plugin_extra_code_edit.setText(
            str(self.current_config.get("plugin_extra_code", "") or "")
        )
        self.plugin_extra_code_edit.setPlaceholderText("大漠后台附加码，可空")
        self.plugin_extra_code_edit.setMaxLength(20)
        self.plugin_extra_code_edit.setToolTip(
            "传给 dm.Reg(注册码, 附加码)。仅字母/数字/小数点，最长 20；"
            "与后台「您的附加码」一致，或留空（未开白名单时）。"
        )
        auth_layout.addRow("附加码:", self.plugin_extra_code_edit)

        verify_row = QWidget(auth_group)
        verify_layout = QHBoxLayout(verify_row)
        verify_layout.setContentsMargins(0, 0, 0, 0)
        verify_layout.setSpacing(10)
        self.plugin_auth_verify_button = QPushButton("验证授权", verify_row)
        self.plugin_auth_verify_button.setObjectName("plugin_auth_verify_button")
        self.plugin_auth_verify_button.setToolTip(
            "用当前填写的注册码/附加码起一个临时插件进程做 Ver + Reg，直接显示大漠返回的结果。\n"
            "每次验证都会向大漠服务器注册一次，请勿频繁点击。"
        )
        self.plugin_auth_verify_button.clicked.connect(self._on_verify_plugin_auth_clicked)
        self.plugin_auth_result_label = QLabel("", verify_row)
        self.plugin_auth_result_label.setObjectName("plugin_auth_result_label")
        self.plugin_auth_result_label.setWordWrap(True)
        self.plugin_auth_result_label.setStyleSheet(f"color: {get_secondary_text_color()};")
        verify_layout.addWidget(self.plugin_auth_verify_button, 0, Qt.AlignmentFlag.AlignTop)
        verify_layout.addWidget(self.plugin_auth_result_label, 1)
        auth_layout.addRow("", verify_row)

        page_layout.addWidget(auth_group)
        page_layout.addStretch(1)
        self.tab_widget.addTab(auth_tab, "插件授权")

    def _on_verify_plugin_auth_clicked(self) -> None:
        reg_code = self.plugin_reg_code_edit.text().strip()
        extra_code = self.plugin_extra_code_edit.text().strip()
        if not reg_code:
            self.plugin_auth_result_label.setText("失败：请先填写注册码")
            return
        self.plugin_auth_verify_button.setEnabled(False)
        self.plugin_auth_result_label.setText("验证中，正在启动插件宿主…")

        def _finished(ok: bool, message: str) -> None:
            try:
                self.plugin_auth_verify_button.setEnabled(True)
                self.plugin_auth_result_label.setText(("通过：" if ok else "失败：") + (message or ""))
            except RuntimeError:
                pass

        start_plugin_auth_probe(self, reg_code, extra_code, _finished)

    def _create_about_tab(self):
        about_tab = QWidget()
        about_layout = QVBoxLayout(about_tab)
        about_layout.setSpacing(0)
        about_layout.setContentsMargins(20, 18, 20, 14)

        text = get_theme_color("text", "#333333")
        secondary = get_secondary_text_color()
        border = get_theme_color("border", "#e0e0e0")
        surface = get_theme_color("surface", "#f5f5f5")

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        self.about_name_label = _about_label(APP_NAME, color=text, size=22, weight=600)
        self.about_edition_label = _about_label(APP_EDITION, color=get_theme_color("accent", "#0078d4"), size=11)
        self.about_edition_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.about_edition_label.setStyleSheet(
            f"color: {get_theme_color('accent', '#0078d4')};"
            f"background-color: {surface};"
            f"border: 1px solid {border};"
            "border-radius: 3px;"
            "padding: 2px 8px;"
            "font-size: 11px;"
        )
        header.addWidget(self.about_name_label, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.about_edition_label, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()
        about_layout.addLayout(header)

        summary_label = _about_label(APP_SUMMARY, color=secondary, size=12)
        summary_label.setWordWrap(True)
        summary_label.setContentsMargins(0, 8, 0, 0)
        about_layout.addWidget(summary_label)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color: {border}; border: none;")
        about_layout.addSpacing(16)
        about_layout.addWidget(divider)
        about_layout.addSpacing(16)

        about_layout.addWidget(_about_label("开源仓库", color=secondary, size=11))
        about_layout.addSpacing(6)

        repo_field = QFrame()
        repo_field.setObjectName("aboutRepoField")
        repo_field.setStyleSheet(
            f"QFrame#aboutRepoField {{"
            f"background-color: {surface};"
            f"border: 1px solid {border};"
            "border-radius: 4px;"
            "}"
        )
        repo_layout = QHBoxLayout(repo_field)
        repo_layout.setContentsMargins(10, 6, 6, 6)
        repo_layout.setSpacing(8)
        self.about_source_label = QLabel(app_source_url())
        self.about_source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.about_source_label.setWordWrap(False)
        self.about_source_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.about_source_label.setToolTip("开源仓库地址，可选择复制")
        self.about_source_label.setStyleSheet(f"color: {text}; font-size: 12px; background: transparent; border: none;")
        self.about_open_source_button = QPushButton("打开仓库")
        self.about_open_source_button.setFixedWidth(80)
        self.about_open_source_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.about_open_source_button.setToolTip("使用系统浏览器打开开源仓库")
        self.about_open_source_button.setProperty("primary", True)
        self.about_open_source_button.style().unpolish(self.about_open_source_button)
        self.about_open_source_button.style().polish(self.about_open_source_button)
        self.about_open_source_button.clicked.connect(self._open_source_repository)
        self.about_copy_source_button = QPushButton("复制地址")
        self.about_copy_source_button.setFixedWidth(80)
        self.about_copy_source_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.about_copy_source_button.setToolTip("复制完整开源地址到剪贴板")
        self.about_copy_source_button.clicked.connect(self._copy_source_repository)
        repo_layout.addWidget(self.about_source_label, 1)
        repo_layout.addWidget(self.about_open_source_button)
        repo_layout.addWidget(self.about_copy_source_button)
        about_layout.addWidget(repo_field)

        about_layout.addSpacing(16)
        about_layout.addWidget(_about_label("许可证", color=secondary, size=11))
        about_layout.addSpacing(4)
        self.about_license_label = _about_label(APP_LICENSE_NAME, color=text, size=12)
        self.about_license_label.setWordWrap(True)
        about_layout.addWidget(self.about_license_label)

        license_note = _about_label("对应源码通过上述仓库提供。", color=secondary, size=11)
        license_note.setContentsMargins(0, 4, 0, 0)
        about_layout.addWidget(license_note)
        about_layout.addStretch()
        self.tab_widget.addTab(about_tab, "关于")

    def _open_source_repository(self):
        QDesktopServices.openUrl(QUrl(app_source_url()))

    def _copy_source_repository(self):
        QApplication.clipboard().setText(app_source_url())
        self.about_copy_source_button.setText("已复制")
        self.about_copy_source_button.setEnabled(False)

        def restore():
            try:
                self.about_copy_source_button.setText("复制地址")
                self.about_copy_source_button.setEnabled(True)
            except RuntimeError:
                return

        QTimer.singleShot(1500, restore)
