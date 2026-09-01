from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from ..main_window_parts.main_window_dropdown_widget import QComboBox
from ..main_window_parts.main_window_support import get_secondary_text_color
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)
from ..main_window_parts.main_window_support import normalize_execution_mode_setting
from app_core.config_sections import DEFAULT_HOTKEYS
from utils.input_simulation.mode_utils import (
    parse_foreground_backends,
    parse_foreground_py_backend,
)
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from ui.widgets.hotkey_capture_button import HotkeyCaptureButton
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from ..main_window_parts.main_window_dropdown_helpers import NoWheelSpinBox
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
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
from ..main_window_parts.main_window_support import get_secondary_text_color, get_theme_color

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

    def _create_execution_tab(self):
        """创建原生模式标签页：仅原生执行 / 键鼠 / 截图参数。"""
        self.exec_tab = QWidget()
        exec_layout = QVBoxLayout(self.exec_tab)
        exec_layout.setSpacing(6)
        exec_layout.setContentsMargins(8, 6, 8, 8)

        self.exec_mode_group = QGroupBox("执行模式")
        exec_mode_layout = QVBoxLayout(self.exec_mode_group)
        exec_mode_layout.setSpacing(4)
        exec_mode_layout.setContentsMargins(12, 8, 12, 8)

        self.mode_select_widget = QWidget()
        mode_select_layout = QHBoxLayout(self.mode_select_widget)
        mode_select_layout.setContentsMargins(0, 0, 0, 0)
        mode_label = QLabel("执行模式:")
        mode_label.setFixedWidth(80)
        self.mode_combo = QComboBox(self)
        self._style_settings_combo(self.mode_combo)
        self.mode_combo.clear()
        for internal_mode, display_mode in self.MODE_DISPLAY_MAP.items():
            self.mode_combo.addItem(display_mode, internal_mode)
        internal_mode = normalize_execution_mode_setting(
            self.current_config.get("execution_mode", "background_sendmessage")
        )
        if internal_mode in ("background_dx", "background_op_dx"):
            internal_mode = "background_sendmessage"
        index = self.mode_combo.findData(internal_mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
        else:
            display_mode = self.MODE_DISPLAY_MAP.get(internal_mode, "前台一模式")
            self.mode_combo.setCurrentText(display_mode)
        mode_select_layout.addWidget(mode_label)
        mode_select_layout.addWidget(self.mode_combo)
        exec_mode_layout.addWidget(self.mode_select_widget)
        exec_layout.addWidget(self.exec_mode_group)

        self.input_backend_group = QGroupBox("键鼠")
        input_backend_layout = QVBoxLayout(self.input_backend_group)
        input_backend_layout.setSpacing(4)
        input_backend_layout.setContentsMargins(12, 8, 12, 8)

        self.native_input_panel = QWidget()
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
        input_backend_layout.addWidget(self.native_input_panel)
        exec_layout.addWidget(self.input_backend_group)

        self.screenshot_engine_group = QGroupBox("截图方式")
        screenshot_engine_layout = QVBoxLayout(self.screenshot_engine_group)
        screenshot_engine_layout.setSpacing(4)
        screenshot_engine_layout.setContentsMargins(12, 8, 12, 8)

        from utils.capture.engine_ids import (
            SUPPORTED_SCREENSHOT_ENGINES,
            screenshot_engine_label as engine_label_text,
        )

        self.screenshot_engine_map = {
            engine_label_text(engine): engine for engine in SUPPORTED_SCREENSHOT_ENGINES
        }
        self.screenshot_engine_reverse_map = {
            engine: engine_label_text(engine) for engine in SUPPORTED_SCREENSHOT_ENGINES
        }

        screenshot_engine_row = QHBoxLayout()
        engine_label_widget = QLabel("截图引擎:")
        engine_label_widget.setFixedWidth(80)
        self.screenshot_engine_combo = QComboBox(self)
        self.screenshot_engine_combo.setObjectName("screenshot_engine_combo")
        self._style_settings_combo(self.screenshot_engine_combo)
        self.screenshot_engine_combo.setToolTip(
            "原生截图：WGC / PrintWindow（支持后台）；GDI / DXGI（仅前台）。\n"
            "插件截图请到「插件模式」页启用。"
        )
        screenshot_engine_row.addWidget(engine_label_widget)
        screenshot_engine_row.addWidget(self.screenshot_engine_combo)
        screenshot_engine_layout.addLayout(screenshot_engine_row)
        exec_layout.addWidget(self.screenshot_engine_group)

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

        self._screenshot_engine_combo_ready = False
        self._update_screenshot_engine_visibility()
        self._update_input_backend_visibility()
        self.screenshot_engine_combo.currentIndexChanged.connect(self._on_screenshot_engine_changed)
        self._screenshot_engine_combo_ready = True

        exec_layout.addStretch(1)
        self.tab_widget.addTab(self.exec_tab, "原生模式")

    def _create_plugin_tab(self):
        """创建插件模式标签页：授权、插件键鼠、插件截图。"""
        from utils.capture.engine_ids import (
            PLUGIN_SCREENSHOT_ENGINES,
            canonicalize_screenshot_engine,
            is_plugin_screenshot_engine,
            screenshot_engine_label as plugin_engine_label,
        )
        from utils.plugin.bind_modes import (
            PLUGIN_BIND_MODE_PRESETS,
            PLUGIN_INPUT_DISPLAYS,
            PLUGIN_KEYPAD_MODES,
            PLUGIN_MOUSE_MODES,
            plugin_bind_mode_label,
            plugin_keypad_label,
            plugin_mouse_label,
        )

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 6, 8, 8)

        auth_group = QGroupBox("插件授权")
        form = QVBoxLayout(auth_group)
        form.setSpacing(4)
        form.setContentsMargins(12, 8, 12, 8)
        plugin_hint = "需 PluginHost.exe / dm.dll / RegDll.dll；注册码仅本机保存。"
        hint = QLabel(plugin_hint)
        hint.setWordWrap(True)
        hint.setToolTip(
            "默认目录 tools/plugin。注册码不会进入导出包。"
        )
        form.addWidget(hint)
        reg_row = QHBoxLayout()
        reg_label = QLabel("注册码:")
        reg_label.setFixedWidth(72)
        self.plugin_reg_code_edit = QLineEdit(self)
        self.plugin_reg_code_edit.setObjectName("plugin_reg_code_edit")
        self.plugin_reg_code_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.plugin_reg_code_edit.setText(str(self.current_config.get("plugin_reg_code", "") or ""))
        self.plugin_reg_code_edit.setToolTip(plugin_hint)
        reg_row.addWidget(reg_label)
        reg_row.addWidget(self.plugin_reg_code_edit, 1)
        form.addLayout(reg_row)
        dir_row = QHBoxLayout()
        dir_label = QLabel("目录:")
        dir_label.setFixedWidth(72)
        self.plugin_dir_edit = QLineEdit(self)
        self.plugin_dir_edit.setObjectName("plugin_dir_edit")
        self.plugin_dir_edit.setText(str(self.current_config.get("plugin_dir", "") or "").strip())
        self.plugin_dir_edit.setToolTip(plugin_hint)
        browse_btn = QPushButton("浏览")
        browse_btn.clicked.connect(self._browse_plugin_dir)
        dir_row.addWidget(dir_label)
        dir_row.addWidget(self.plugin_dir_edit, 1)
        dir_row.addWidget(browse_btn)
        form.addLayout(dir_row)
        layout.addWidget(auth_group)

        input_group = QGroupBox("键鼠")
        input_layout = QVBoxLayout(input_group)
        input_layout.setSpacing(6)
        input_layout.setContentsMargins(12, 8, 12, 8)
        configured_input_backend = str(
            self.current_config.get("input_backend", "native") or "native"
        ).strip().lower()
        self.plugin_input_enable_check = QCheckBox("使用插件键鼠", self)
        self.plugin_input_enable_check.setObjectName("plugin_input_enable_check")
        self.plugin_input_enable_check.setChecked(configured_input_backend == "plugin")
        self.plugin_input_enable_check.setToolTip(
            "开启后键鼠经 PluginHost 绑定；关闭则使用「原生模式」页的键鼠参数。"
        )
        input_layout.addWidget(self.plugin_input_enable_check)

        self.plugin_input_panel = QWidget()
        plugin_input_layout = QVBoxLayout(self.plugin_input_panel)
        plugin_input_layout.setContentsMargins(0, 0, 0, 0)
        plugin_input_layout.setSpacing(6)

        mouse_row = QHBoxLayout()
        mouse_label = QLabel("鼠标模式:")
        mouse_label.setFixedWidth(72)
        self.plugin_mouse_combo = QComboBox(self)
        self.plugin_mouse_combo.setObjectName("plugin_mouse_combo")
        self._style_settings_combo(self.plugin_mouse_combo)
        for mode in PLUGIN_MOUSE_MODES:
            self.plugin_mouse_combo.addItem(plugin_mouse_label(mode), mode)
        configured_mouse = str(
            self.current_config.get("plugin_mouse", "normal") or "normal"
        ).strip().lower()
        mouse_index = self.plugin_mouse_combo.findData(configured_mouse)
        if mouse_index >= 0:
            self.plugin_mouse_combo.setCurrentIndex(mouse_index)
        mouse_row.addWidget(mouse_label)
        mouse_row.addWidget(self.plugin_mouse_combo, 1)
        plugin_input_layout.addLayout(mouse_row)

        keypad_row = QHBoxLayout()
        keypad_label = QLabel("键盘模式:")
        keypad_label.setFixedWidth(72)
        self.plugin_keypad_combo = QComboBox(self)
        self.plugin_keypad_combo.setObjectName("plugin_keypad_combo")
        self._style_settings_combo(self.plugin_keypad_combo)
        for mode in PLUGIN_KEYPAD_MODES:
            self.plugin_keypad_combo.addItem(plugin_keypad_label(mode), mode)
        configured_keypad = str(
            self.current_config.get("plugin_keypad", "normal") or "normal"
        ).strip().lower()
        keypad_index = self.plugin_keypad_combo.findData(configured_keypad)
        if keypad_index >= 0:
            self.plugin_keypad_combo.setCurrentIndex(keypad_index)
        keypad_row.addWidget(keypad_label)
        keypad_row.addWidget(self.plugin_keypad_combo, 1)
        plugin_input_layout.addLayout(keypad_row)

        self.plugin_input_display_follow_check = QCheckBox("绑定图显跟随截图", self)
        self.plugin_input_display_follow_check.setObjectName("plugin_input_display_follow_check")
        self.plugin_input_display_follow_check.setChecked(
            bool(self.current_config.get("plugin_input_display_follow", True))
        )
        self.plugin_input_display_follow_check.setToolTip(
            "开启后绑定图显自动对齐当前生效的截图引擎；截图为原生时用「正常」。"
        )
        plugin_input_layout.addWidget(self.plugin_input_display_follow_check)

        self.plugin_input_display_row = QWidget()
        display_row = QHBoxLayout(self.plugin_input_display_row)
        display_row.setContentsMargins(0, 0, 0, 0)
        display_label = QLabel("绑定图显:")
        display_label.setFixedWidth(72)
        self.plugin_input_display_combo = QComboBox(self)
        self.plugin_input_display_combo.setObjectName("plugin_input_display_combo")
        self._style_settings_combo(self.plugin_input_display_combo)
        for display in PLUGIN_INPUT_DISPLAYS:
            self.plugin_input_display_combo.addItem(plugin_engine_label(display), display)
        configured_display = str(
            self.current_config.get("plugin_input_display", "normal") or "normal"
        ).strip().lower()
        display_index = self.plugin_input_display_combo.findData(configured_display)
        if display_index >= 0:
            self.plugin_input_display_combo.setCurrentIndex(display_index)
        self.plugin_input_display_combo.setToolTip("仅在取消「绑定图显跟随截图」后可手动选择。")
        display_row.addWidget(display_label)
        display_row.addWidget(self.plugin_input_display_combo, 1)
        plugin_input_layout.addWidget(self.plugin_input_display_row)

        self.plugin_advanced_panel = QWidget()
        advanced_layout = QHBoxLayout(self.plugin_advanced_panel)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(8)
        self.plugin_advanced_toggle = QCheckBox("高级绑定模式", self)
        self.plugin_advanced_toggle.setObjectName("plugin_advanced_toggle")
        self.plugin_advanced_toggle.setChecked(False)
        self.plugin_bind_mode_combo = QComboBox(self)
        self.plugin_bind_mode_combo.setObjectName("plugin_bind_mode_combo")
        self.plugin_bind_mode_combo.setEditable(False)
        self._style_settings_combo(self.plugin_bind_mode_combo)
        for mode in PLUGIN_BIND_MODE_PRESETS:
            self.plugin_bind_mode_combo.addItem(plugin_bind_mode_label(mode), mode)
        try:
            configured_bind_mode = int(self.current_config.get("plugin_bind_mode", 0) or 0)
        except (TypeError, ValueError):
            configured_bind_mode = 0
        bind_mode_index = self.plugin_bind_mode_combo.findData(configured_bind_mode)
        if bind_mode_index < 0:
            self.plugin_bind_mode_combo.addItem(
                plugin_bind_mode_label(configured_bind_mode), configured_bind_mode
            )
            bind_mode_index = self.plugin_bind_mode_combo.findData(configured_bind_mode)
        if bind_mode_index >= 0:
            self.plugin_bind_mode_combo.setCurrentIndex(bind_mode_index)
        self.plugin_bind_mode_combo.setToolTip(
            "大漠 BindWindowEx 的 mode。不确定时保持「0 · 默认（推荐）」"
        )
        self.plugin_bind_mode_combo.setVisible(False)
        advanced_layout.addWidget(self.plugin_advanced_toggle)
        advanced_layout.addWidget(self.plugin_bind_mode_combo, 1)
        plugin_input_layout.addWidget(self.plugin_advanced_panel)
        input_layout.addWidget(self.plugin_input_panel)
        layout.addWidget(input_group)

        shot_group = QGroupBox("截图方式")
        shot_layout = QVBoxLayout(shot_group)
        shot_layout.setSpacing(6)
        shot_layout.setContentsMargins(12, 8, 12, 8)
        initial_engine = canonicalize_screenshot_engine(
            self.current_config.get("screenshot_engine") or "wgc"
        )
        use_plugin_shot = is_plugin_screenshot_engine(initial_engine)
        self.plugin_screenshot_enable_check = QCheckBox("使用插件截图", self)
        self.plugin_screenshot_enable_check.setObjectName("plugin_screenshot_enable_check")
        self.plugin_screenshot_enable_check.setChecked(use_plugin_shot)
        self.plugin_screenshot_enable_check.setToolTip(
            "开启后使用插件截图引擎；关闭则使用「原生模式」页的截图引擎。"
        )
        shot_layout.addWidget(self.plugin_screenshot_enable_check)
        self.plugin_screenshot_panel = QWidget()
        plugin_shot_row = QHBoxLayout(self.plugin_screenshot_panel)
        plugin_shot_row.setContentsMargins(0, 0, 0, 0)
        plugin_shot_row.setSpacing(8)
        plugin_shot_label = QLabel("截图引擎:")
        plugin_shot_label.setFixedWidth(72)
        self.plugin_screenshot_engine_combo = QComboBox(self)
        self.plugin_screenshot_engine_combo.setObjectName("plugin_screenshot_engine_combo")
        self._style_settings_combo(self.plugin_screenshot_engine_combo)
        for engine in PLUGIN_SCREENSHOT_ENGINES:
            self.plugin_screenshot_engine_combo.addItem(plugin_engine_label(engine), engine)
        plugin_engine = initial_engine if use_plugin_shot else "normal"
        plugin_engine_index = self.plugin_screenshot_engine_combo.findData(plugin_engine)
        if plugin_engine_index >= 0:
            self.plugin_screenshot_engine_combo.setCurrentIndex(plugin_engine_index)
        self.plugin_screenshot_engine_combo.setToolTip(
            "插件截图：正常 / GDI / GDI2（无需挂钩）；DX / OpenGL（需注入）"
        )
        plugin_shot_row.addWidget(plugin_shot_label)
        plugin_shot_row.addWidget(self.plugin_screenshot_engine_combo, 1)
        shot_layout.addWidget(self.plugin_screenshot_panel)
        layout.addWidget(shot_group)

        self.plugin_input_enable_check.toggled.connect(self._on_plugin_input_enable_toggled)
        self.plugin_screenshot_enable_check.toggled.connect(self._on_plugin_screenshot_enable_toggled)
        self.plugin_input_display_follow_check.toggled.connect(self._on_plugin_input_display_follow_toggled)
        self.plugin_advanced_toggle.toggled.connect(self._on_plugin_advanced_toggled)
        self.plugin_screenshot_engine_combo.currentIndexChanged.connect(
            self._on_screenshot_engine_changed
        )

        self._update_plugin_mode_panels()
        self._sync_plugin_input_display_follow()

        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("plugin_mode_scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        self.tab_widget.addTab(scroll, "插件模式")

    def _browse_plugin_dir(self):
        start = ""
        if hasattr(self, "plugin_dir_edit"):
            start = self.plugin_dir_edit.text().strip()
        chosen = QFileDialog.getExistingDirectory(self, "选择插件目录", start)
        if chosen:
            self.plugin_dir_edit.setText(chosen)

    def _on_plugin_advanced_toggled(self, checked: bool) -> None:
        if hasattr(self, "plugin_bind_mode_combo"):
            self.plugin_bind_mode_combo.setVisible(bool(checked))
            if self.isVisible():
                QTimer.singleShot(0, self._adjust_dialog_height_only)

    def _on_plugin_input_enable_toggled(self, _checked: bool = False) -> None:
        self._update_plugin_mode_panels(resize_dialog=True)

    def _on_plugin_screenshot_enable_toggled(self, _checked: bool = False) -> None:
        self._update_plugin_mode_panels(resize_dialog=True)
        self._sync_plugin_input_display_follow()

    def _on_plugin_input_display_follow_toggled(self, _checked: bool = False) -> None:
        self._sync_plugin_input_display_follow()

    def _update_plugin_mode_panels(self, *, resize_dialog: bool = False) -> None:
        use_plugin_input = False
        if hasattr(self, "plugin_input_enable_check"):
            use_plugin_input = bool(self.plugin_input_enable_check.isChecked())
        if hasattr(self, "plugin_input_panel"):
            self.plugin_input_panel.setVisible(use_plugin_input)
        use_plugin_shot = False
        if hasattr(self, "plugin_screenshot_enable_check"):
            use_plugin_shot = bool(self.plugin_screenshot_enable_check.isChecked())
        if hasattr(self, "plugin_screenshot_panel"):
            self.plugin_screenshot_panel.setVisible(use_plugin_shot)
        elif hasattr(self, "plugin_screenshot_engine_combo"):
            self.plugin_screenshot_engine_combo.setVisible(use_plugin_shot)
        if use_plugin_input:
            self._sync_plugin_input_display_follow()
            if hasattr(self, "plugin_bind_mode_combo") and hasattr(self, "plugin_advanced_toggle"):
                self.plugin_bind_mode_combo.setVisible(
                    bool(self.plugin_advanced_toggle.isChecked())
                )
        if resize_dialog and self.isVisible():
            QTimer.singleShot(0, self._adjust_dialog_height_only)

    def _followed_plugin_input_display(self) -> str:
        from utils.capture.engine_ids import (
            canonicalize_screenshot_engine,
            is_plugin_screenshot_engine,
        )

        engine = canonicalize_screenshot_engine(self._get_selected_screenshot_engine())
        if is_plugin_screenshot_engine(engine):
            return engine
        return "normal"

    def _sync_plugin_input_display_follow(self) -> None:
        if not hasattr(self, "plugin_input_display_combo"):
            return
        follow = True
        if hasattr(self, "plugin_input_display_follow_check"):
            follow = bool(self.plugin_input_display_follow_check.isChecked())
        if hasattr(self, "plugin_input_display_row"):
            self.plugin_input_display_row.setVisible(not follow)
        if follow:
            target = self._followed_plugin_input_display()
            index = self.plugin_input_display_combo.findData(target)
            if index >= 0 and self.plugin_input_display_combo.currentIndex() != index:
                self.plugin_input_display_combo.blockSignals(True)
                try:
                    self.plugin_input_display_combo.setCurrentIndex(index)
                finally:
                    self.plugin_input_display_combo.blockSignals(False)

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

    def _get_selected_screenshot_engine(self) -> str:
        if (
            hasattr(self, "plugin_screenshot_enable_check")
            and self.plugin_screenshot_enable_check.isChecked()
            and hasattr(self, "plugin_screenshot_engine_combo")
        ):
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
        other_layout.setSpacing(8)
        other_layout.setContentsMargins(10, 8, 10, 10)
        # --- Custom Resolution Group ---
        resolution_group = QGroupBox("自定义绑定窗口分辨率（宽高都为 0 = 禁用）")
        resolution_layout = QFormLayout(resolution_group)
        resolution_layout.setSpacing(8)
        resolution_layout.setContentsMargins(15, 10, 15, 10)
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
        screenshot_layout.setSpacing(8)
        screenshot_layout.setContentsMargins(15, 10, 15, 10)
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
        other_layout.addStretch()
        self.tab_widget.addTab(other_tab, "其他设置")

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
