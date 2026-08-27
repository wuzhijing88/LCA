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
from PySide6.QtCore import QTimer
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
from utils.input_simulation.mode_utils import parse_foreground_backends
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from ..main_window_parts.main_window_dropdown_widget import CustomDropdown
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
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

    def _create_execution_tab(self):

        """创建执行模式设置标签页"""

        self.exec_tab = QWidget()

        exec_layout = QVBoxLayout(self.exec_tab)

        exec_layout.setSpacing(8)

        exec_layout.setContentsMargins(10, 8, 10, 10)

        # --- Execution Mode Group ---

        self.exec_mode_group = QGroupBox("执行模式")

        exec_mode_layout = QVBoxLayout(self.exec_mode_group)

        exec_mode_layout.setSpacing(8)

        exec_mode_layout.setContentsMargins(15, 10, 15, 10)

        # 前后台模式选择（包装在widget中以便单独隐藏）

        self.mode_select_widget = QWidget()

        mode_select_layout = QHBoxLayout(self.mode_select_widget)

        mode_select_layout.setContentsMargins(0, 0, 0, 0)

        mode_label = QLabel("执行模式:")

        mode_label.setFixedWidth(80)

        self.mode_combo = QComboBox(self)

        self.mode_combo.clear()

        for internal_mode, display_mode in self.MODE_DISPLAY_MAP.items():

            self.mode_combo.addItem(display_mode, internal_mode)

        internal_mode = normalize_execution_mode_setting(

            self.current_config.get('execution_mode', 'background_sendmessage')

        )

        index = self.mode_combo.findData(internal_mode)

        if index >= 0:

            self.mode_combo.setCurrentIndex(index)

        else:

            display_mode = self.MODE_DISPLAY_MAP.get(internal_mode, "前台一模式")

            self.mode_combo.setCurrentText(display_mode)

        mode_select_layout.addWidget(mode_label)

        mode_select_layout.addWidget(self.mode_combo)

        exec_mode_layout.addWidget(self.mode_select_widget)

        self.foreground_driver_widget = QWidget()

        foreground_driver_layout = QHBoxLayout(self.foreground_driver_widget)

        foreground_driver_layout.setContentsMargins(0, 0, 0, 0)

        foreground_driver_label = QLabel("鼠标驱动:")

        foreground_driver_label.setFixedWidth(80)

        self.foreground_driver_combo = QComboBox(self)

        for display_name, backend in self.FOREGROUND_DRIVER_BACKEND_MAP.items():

            self.foreground_driver_combo.addItem(display_name, backend)

        configured_mouse_backend, configured_keyboard_backend = parse_foreground_backends(self.current_config)

        backend_index = self.foreground_driver_combo.findData(configured_mouse_backend)

        if backend_index >= 0:

            self.foreground_driver_combo.setCurrentIndex(backend_index)

        foreground_driver_layout.addWidget(foreground_driver_label)

        foreground_driver_layout.addWidget(self.foreground_driver_combo)

        exec_mode_layout.addWidget(self.foreground_driver_widget)

        self.foreground_keyboard_driver_widget = QWidget()

        foreground_keyboard_driver_layout = QHBoxLayout(self.foreground_keyboard_driver_widget)

        foreground_keyboard_driver_layout.setContentsMargins(0, 0, 0, 0)

        foreground_keyboard_driver_label = QLabel("键盘驱动:")

        foreground_keyboard_driver_label.setFixedWidth(80)

        self.foreground_keyboard_driver_combo = QComboBox(self)

        for display_name, backend in self.FOREGROUND_DRIVER_BACKEND_MAP.items():

            self.foreground_keyboard_driver_combo.addItem(display_name, backend)

        keyboard_backend_index = self.foreground_keyboard_driver_combo.findData(configured_keyboard_backend)

        if keyboard_backend_index >= 0:

            self.foreground_keyboard_driver_combo.setCurrentIndex(keyboard_backend_index)

        foreground_keyboard_driver_layout.addWidget(foreground_keyboard_driver_label)

        foreground_keyboard_driver_layout.addWidget(self.foreground_keyboard_driver_combo)

        exec_mode_layout.addWidget(self.foreground_keyboard_driver_widget)

        self.ib_driver_widget = QWidget()

        ib_driver_layout = QHBoxLayout(self.ib_driver_widget)

        ib_driver_layout.setContentsMargins(0, 0, 0, 0)

        ib_driver_label = QLabel("Ib驱动类型:")

        ib_driver_label.setFixedWidth(80)

        self.ib_driver_combo = QComboBox(self)

        for display_name, ib_driver in self.IB_DRIVER_MAP.items():

            self.ib_driver_combo.addItem(display_name, ib_driver)

        configured_ib_driver = str(self.current_config.get('ibinputsimulator_driver', 'Logitech') or 'Logitech').strip()

        ib_driver_index = self.ib_driver_combo.findData(configured_ib_driver)

        if ib_driver_index < 0:

            ib_driver_index = self.ib_driver_combo.findData('Logitech')

        if ib_driver_index >= 0:

            self.ib_driver_combo.setCurrentIndex(ib_driver_index)

        ib_driver_layout.addWidget(ib_driver_label)

        ib_driver_layout.addWidget(self.ib_driver_combo)

        exec_mode_layout.addWidget(self.ib_driver_widget)

        exec_layout.addWidget(self.exec_mode_group)

        # --- 截图方式选择（原生模式）---

        self.screenshot_engine_group = QGroupBox("截图方式")

        screenshot_engine_layout = QVBoxLayout(self.screenshot_engine_group)

        screenshot_engine_layout.setSpacing(8)

        screenshot_engine_layout.setContentsMargins(15, 10, 15, 10)

        # 截图引擎选择

        screenshot_engine_row = QHBoxLayout()

        screenshot_engine_label = QLabel("截图引擎:")

        screenshot_engine_label.setFixedWidth(80)

        self.screenshot_engine_combo = QComboBox(self)

        self.screenshot_engine_combo.setMinimumWidth(200)

        # 截图引擎选项映射

        self.screenshot_engine_map = {

            "WGC (适用Win11)": "wgc",

            "PrintWindow (适用Win10)": "printwindow",

            "GDI (仅前台)": "gdi",

            "DXGI (仅前台)": "dxgi"

        }

        self.screenshot_engine_reverse_map = {v: k for k, v in self.screenshot_engine_map.items()}

        # 添加选项

        for display_name in self.screenshot_engine_map.keys():

            self.screenshot_engine_combo.addItem(display_name)

        # 从配置读取当前截图引擎

        current_engine = self.current_config.get('screenshot_engine', 'wgc')
        display_engine = self.screenshot_engine_reverse_map.get(current_engine)
        if display_engine:
            self.screenshot_engine_combo.setCurrentText(display_engine)

        # 设置工具提示

        self.screenshot_engine_combo.setToolTip(

            "WGC: Windows Graphics Capture，Win10 1903+/Win11，GPU加速，支持后台\n"

            "PrintWindow: Win32 API，适用Win10，支持后台窗口\n"

            "GDI: 传统截图方式，仅支持前台（可见区域）\n"

            "DXGI: Desktop Duplication API，高性能，仅支持前台"

        )

        screenshot_engine_row.addWidget(screenshot_engine_label)

        screenshot_engine_row.addWidget(self.screenshot_engine_combo)

        screenshot_engine_layout.addLayout(screenshot_engine_row)

        exec_layout.addWidget(self.screenshot_engine_group)

        # 连接执行模式变化信号，用于控制截图引擎选项可见性

        self.mode_combo.currentTextChanged.connect(self._update_screenshot_engine_visibility)

        self.mode_combo.currentTextChanged.connect(self._update_foreground_driver_visibility)

        self.mode_combo.currentIndexChanged.connect(self._update_screenshot_engine_visibility)

        self.mode_combo.currentIndexChanged.connect(self._update_foreground_driver_visibility)

        self.foreground_driver_combo.currentTextChanged.connect(self._update_foreground_driver_visibility)

        self.foreground_driver_combo.currentIndexChanged.connect(self._update_foreground_driver_visibility)

        self.foreground_keyboard_driver_combo.currentTextChanged.connect(self._update_foreground_driver_visibility)

        self.foreground_keyboard_driver_combo.currentIndexChanged.connect(self._update_foreground_driver_visibility)

        # 初始化时更新截图引擎可见性

        self._screenshot_engine_combo_ready = False

        self._update_screenshot_engine_visibility()

        self._update_foreground_driver_visibility()

        self.screenshot_engine_combo.currentIndexChanged.connect(self._on_screenshot_engine_changed)

        self._screenshot_engine_combo_ready = True

        exec_layout.addStretch(1)

        self.tab_widget.addTab(self.exec_tab, "执行模式")

    def _update_screenshot_engine_visibility(self):

        """

        更新截图引擎选择框的可见性

        - 前台一/二模式：显示所有截图引擎选项（全部）

        - 后台模式：仅显示支持后台的引擎（WGC / PrintWindow）

        """

        previous_ready = getattr(self, "_screenshot_engine_combo_ready", False)
        self._screenshot_engine_combo_ready = False
        try:
            self._rebuild_screenshot_engine_options()
        finally:
            self._screenshot_engine_combo_ready = previous_ready

    def _rebuild_screenshot_engine_options(self):
        internal_mode = self.mode_combo.currentData()

        if not internal_mode:

            current_mode = self.mode_combo.currentText()

            internal_mode = self.MODE_INTERNAL_MAP.get(current_mode, "")

        is_foreground = internal_mode.startswith("foreground")

        # 获取当前选择的引擎

        current_engine = self.screenshot_engine_combo.currentText()

        # 清空选项并重新添加

        self.screenshot_engine_combo.clear()

        if is_foreground:

            # 前台一/二模式：显示所有选项

            for display_name in self.screenshot_engine_map.keys():

                self.screenshot_engine_combo.addItem(display_name)

        else:

            # 后台模式：只显示支持后台的引擎

            for display_name, engine in self.screenshot_engine_map.items():

                if engine in ("wgc", "printwindow"):

                    self.screenshot_engine_combo.addItem(display_name)

        # 恢复之前的选择（如果仍然可用）

        index = self.screenshot_engine_combo.findText(current_engine)

        if index >= 0:

            self.screenshot_engine_combo.setCurrentIndex(index)

        # Limit popup height to item count to avoid empty space

        item_count = self.screenshot_engine_combo.count()

        if item_count > 0:

            self.screenshot_engine_combo.setMaxVisibleItems(item_count)

    def _get_selected_screenshot_engine(self) -> str:
        if not hasattr(self, "screenshot_engine_combo"):
            return str((getattr(self, "current_config", {}) or {}).get("screenshot_engine") or "").strip().lower()
        display_name = self.screenshot_engine_combo.currentText()
        engine = self.screenshot_engine_map.get(display_name)
        return str(engine or "").strip().lower()

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
        if self._is_wgc_desktop_combination():
            self._warn_wgc_desktop_engine()

    def _create_hotkey_tab(self):
        """创建快捷键设置标签页"""
        hotkey_tab = QWidget()
        hotkey_layout = QVBoxLayout(hotkey_tab)
        hotkey_layout.setSpacing(8)
        hotkey_layout.setContentsMargins(10, 8, 10, 10)
        # --- Hotkey Settings Group ---
        self.hotkey_group = QGroupBox("快捷键配置")
        hotkey_main_layout = QVBoxLayout(self.hotkey_group)
        hotkey_main_layout.setSpacing(15)
        hotkey_main_layout.setContentsMargins(15, 15, 15, 15)
        # 第一行：启动任务、停止任务、暂停工作流、录制操作
        hotkey_row1_layout = QHBoxLayout()
        hotkey_row1_layout.setSpacing(20)
        # 第二行：回放操作
        hotkey_row2_layout = QHBoxLayout()
        hotkey_row2_layout.setSpacing(20)
        # 启动任务快捷键
        start_task_container = QVBoxLayout()
        start_task_label = QLabel("启动任务")
        start_task_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        start_task_label.setObjectName("hotkey_label")
        # 使用下拉选择框代替输入框
        self.start_task_hotkey = CustomDropdown(self)
        # 快捷键选项：显示文本 -> 实际值的映射
        hotkey_display_map = {
            'F1': 'F1', 'F2': 'F2', 'F3': 'F3', 'F4': 'F4',
            'F5': 'F5', 'F6': 'F6', 'F7': 'F7', 'F8': 'F8',
            'F9': 'F9', 'F10': 'F10', 'F11': 'F11', 'F12': 'F12',
            'Home': 'Home', 'End': 'End',
            'Insert': 'Insert', 'Delete': 'Delete',
            'PageUp': 'PageUp', 'PageDown': 'PageDown',
            'PrintScreen': 'PrintScreen', 'ScrollLock': 'ScrollLock', 'Pause': 'Pause',
            'NumLock': 'NumLock',
            '小键盘0': 'Num0', '小键盘1': 'Num1', '小键盘2': 'Num2', '小键盘3': 'Num3',
            '小键盘4': 'Num4', '小键盘5': 'Num5', '小键盘6': 'Num6', '小键盘7': 'Num7',
            '小键盘8': 'Num8', '小键盘9': 'Num9',
            '小键盘*': 'NumMultiply', '小键盘+': 'NumAdd', '小键盘-': 'NumSubtract',
            '小键盘/': 'NumDivide', '小键盘.': 'NumDecimal',
            '鼠标侧键1(后退)': 'XButton1',
            '鼠标侧键2(前进)': 'XButton2'
        }
        for display_text, value in hotkey_display_map.items():
            self.start_task_hotkey.addItem(display_text, value)
        # 设置当前值
        current_start_key = self.current_config.get('start_task_hotkey', DEFAULT_HOTKEYS['start_task_hotkey'])
        # 兼容可能保存了中文名称的情况
        chinese_to_code = {
            '鼠标侧键1(后退)': 'XButton1',
            '鼠标侧键2(前进)': 'XButton2'
        }
        if current_start_key in chinese_to_code:
            current_start_key = chinese_to_code[current_start_key]
        # 只对F键进行大写转换，XButton保持原样
        if current_start_key.startswith('F') and len(current_start_key) <= 3:
            current_start_key = current_start_key.upper()
        for i in range(self.start_task_hotkey.count()):
            if self.start_task_hotkey.itemData(i) == current_start_key:
                self.start_task_hotkey.setCurrentIndex(i)
                break
        self.start_task_hotkey.setToolTip("设置启动任务的快捷键\n支持: F1-F12功能键、导航键(Home/End/Insert/Delete等)、小键盘、鼠标侧键")
        self.start_task_hotkey.setFixedWidth(130)
        start_task_container.addWidget(start_task_label)
        start_task_container.addWidget(self.start_task_hotkey)
        # 停止任务快捷键
        stop_task_container = QVBoxLayout()
        stop_task_label = QLabel("停止任务")
        stop_task_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stop_task_label.setObjectName("hotkey_label")
        # 使用下拉选择框代替输入框
        self.stop_task_hotkey = CustomDropdown(self)
        for display_text, value in hotkey_display_map.items():
            self.stop_task_hotkey.addItem(display_text, value)
        # 设置当前值
        current_stop_key = self.current_config.get('stop_task_hotkey', DEFAULT_HOTKEYS['stop_task_hotkey'])
        # 兼容可能保存了中文名称的情况
        if current_stop_key in chinese_to_code:
            current_stop_key = chinese_to_code[current_stop_key]
        # 只对F键进行大写转换，XButton保持原样
        if current_stop_key.startswith('F') and len(current_stop_key) <= 3:
            current_stop_key = current_stop_key.upper()
        for i in range(self.stop_task_hotkey.count()):
            if self.stop_task_hotkey.itemData(i) == current_stop_key:
                self.stop_task_hotkey.setCurrentIndex(i)
                break
        self.stop_task_hotkey.setToolTip("设置停止任务的快捷键\n支持: F1-F12功能键、导航键(Home/End/Insert/Delete等)、小键盘、鼠标侧键")
        self.stop_task_hotkey.setFixedWidth(130)
        stop_task_container.addWidget(stop_task_label)
        stop_task_container.addWidget(self.stop_task_hotkey)
        # 录制快捷键
        record_container = QVBoxLayout()
        record_label = QLabel("录制操作")
        record_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        record_label.setObjectName("hotkey_label")
        # 使用下拉选择框
        self.record_hotkey = CustomDropdown(self)
        for display_text, value in hotkey_display_map.items():
            self.record_hotkey.addItem(display_text, value)
        # 设置当前值
        current_record_key = self.current_config.get('record_hotkey', DEFAULT_HOTKEYS['record_hotkey'])
        # 兼容可能保存了中文名称的情况
        if current_record_key in chinese_to_code:
            current_record_key = chinese_to_code[current_record_key]
        # 只对F键进行大写转换，XButton保持原样
        if current_record_key.startswith('F') and len(current_record_key) <= 3:
            current_record_key = current_record_key.upper()
        for i in range(self.record_hotkey.count()):
            if self.record_hotkey.itemData(i) == current_record_key:
                self.record_hotkey.setCurrentIndex(i)
                break
        self.record_hotkey.setToolTip("设置录制操作的快捷键\n仅在录制卡片参数面板打开时生效\n支持: F1-F12功能键、导航键(Home/End/Insert/Delete等)、小键盘、鼠标侧键")
        self.record_hotkey.setFixedWidth(130)
        record_container.addWidget(record_label)
        record_container.addWidget(self.record_hotkey)
        # 回放快捷键
        replay_container = QVBoxLayout()
        replay_label = QLabel("回放操作")
        replay_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        replay_label.setObjectName("hotkey_label")
        # 使用下拉选择框
        self.replay_hotkey = CustomDropdown(self)
        for display_text, value in hotkey_display_map.items():
            self.replay_hotkey.addItem(display_text, value)
        # 设置当前值
        current_replay_key = self.current_config.get('replay_hotkey', DEFAULT_HOTKEYS['replay_hotkey'])
        # 兼容可能保存了中文名称的情况
        if current_replay_key in chinese_to_code:
            current_replay_key = chinese_to_code[current_replay_key]
        # 只对F键进行大写转换，XButton保持原样
        if current_replay_key.startswith('F') and len(current_replay_key) <= 3:
            current_replay_key = current_replay_key.upper()
        for i in range(self.replay_hotkey.count()):
            if self.replay_hotkey.itemData(i) == current_replay_key:
                self.replay_hotkey.setCurrentIndex(i)
                break
        self.replay_hotkey.setToolTip("设置回放操作的快捷键\n仅在录制回放卡片参数面板打开时生效\n支持: F1-F12功能键、导航键(Home/End/Insert/Delete等)、小键盘、鼠标侧键")
        self.replay_hotkey.setFixedWidth(130)
        replay_container.addWidget(replay_label)
        replay_container.addWidget(self.replay_hotkey)
        # 暂停工作流快捷键
        pause_container = QVBoxLayout()
        pause_label = QLabel("暂停工作流")
        pause_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pause_label.setObjectName("hotkey_label")
        # 使用下拉选择框
        self.pause_workflow_hotkey = CustomDropdown(self)
        for display_text, value in hotkey_display_map.items():
            self.pause_workflow_hotkey.addItem(display_text, value)
        # 设置当前值
        current_pause_key = self.current_config.get('pause_workflow_hotkey', DEFAULT_HOTKEYS['pause_workflow_hotkey'])
        # 兼容可能保存了中文名称的情况
        if current_pause_key in chinese_to_code:
            current_pause_key = chinese_to_code[current_pause_key]
        # 只对F键进行大写转换，XButton保持原样
        if current_pause_key.startswith('F') and len(current_pause_key) <= 3:
            current_pause_key = current_pause_key.upper()
        for i in range(self.pause_workflow_hotkey.count()):
            if self.pause_workflow_hotkey.itemData(i) == current_pause_key:
                self.pause_workflow_hotkey.setCurrentIndex(i)
                break
        self.pause_workflow_hotkey.setToolTip("设置暂停/恢复工作流的快捷键\n支持: F1-F12功能键、导航键(Home/End/Insert/Delete等)、小键盘、鼠标侧键")
        self.pause_workflow_hotkey.setFixedWidth(130)
        pause_container.addWidget(pause_label)
        pause_container.addWidget(self.pause_workflow_hotkey)
        # 第一行：启动任务、停止任务、暂停工作流、录制操作
        hotkey_row1_layout.addLayout(start_task_container)
        hotkey_row1_layout.addLayout(stop_task_container)
        hotkey_row1_layout.addLayout(pause_container)
        hotkey_row1_layout.addLayout(record_container)
        hotkey_row1_layout.addStretch()  # 添加弹性空间
        # 第二行：回放操作
        hotkey_row2_layout.addLayout(replay_container)
        hotkey_row2_layout.addStretch()  # 添加弹性空间
        # 添加两行到主布局
        hotkey_main_layout.addLayout(hotkey_row1_layout)
        hotkey_main_layout.addLayout(hotkey_row2_layout)
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
        resolution_group = QGroupBox("自定义分辨率 (0 = 禁用)")
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
