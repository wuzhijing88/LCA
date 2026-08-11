from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ..main_window_parts.main_window_dropdown_helpers import NoWheelSpinBox
from ..main_window_parts.main_window_dropdown_widget import CustomDropdown, QComboBox
from ..main_window_parts.main_window_support import get_secondary_text_color, normalize_execution_mode_setting


class GlobalSettingsDialogOtherTabMixin:
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

