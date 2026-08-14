from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ..main_window_parts.main_window_dropdown_widget import QComboBox
from ..main_window_parts.main_window_support import normalize_execution_mode_setting
from utils.input_simulation.mode_utils import parse_foreground_backends

class GlobalSettingsDialogExecutionTabMixin:
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
        from utils.window_identity import is_wgc_with_desktop_target

        return is_wgc_with_desktop_target(
            self._get_selected_screenshot_engine(),
            getattr(self, "bound_windows", None),
        )

    def _warn_wgc_desktop_engine(self) -> None:
        from utils.window_identity import WGC_DESKTOP_ENGINE_MESSAGE

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

