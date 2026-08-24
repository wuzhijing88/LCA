from ..parameter_panel_support import *
from utils.window_activation_utils import show_and_activate_overlay


class ParameterPanelSelectorPickerColorCoordinateDialogMixin:

    _COLOR_COORDINATE_INFO_TEXT = (
        "点击下方按钮后，在目标窗口上点击鼠标获取该位置的颜色。\n"
        "支持多点选择以构建多点定位字符串，提高找色精确度。\n\n"
        "- 第一个点为基准点\n"
        "- 后续点自动计算相对偏移\n"
        "- 可连续左键取色，点覆盖层“完成取色”再返回\n"
        "- 多点格式: 基准R,G,B|偏移X,偏移Y,R,G,B|..."
    )

    def _create_color_coordinate_dialog(self):
        from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout
        from ui.selectors.color_coordinate_picker import ColorCoordinatePickerWidget

        dialog = QDialog(self)
        dialog.setWindowTitle("选择颜色和坐标")
        dialog.setMinimumSize(520, 400)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        info_label = QLabel(self._COLOR_COORDINATE_INFO_TEXT)
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        color_picker = ColorCoordinatePickerWidget(dialog)
        self._configure_color_coordinate_picker(color_picker)
        layout.addWidget(color_picker)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        button_layout.setContentsMargins(0, 10, 0, 0)

        ok_button = QPushButton("确定")
        ok_button.setMinimumWidth(100)
        ok_button.setMinimumHeight(36)
        ok_button.setProperty("class", "primary")
        ok_button.clicked.connect(dialog.accept)

        cancel_button = QPushButton("取消")
        cancel_button.setMinimumWidth(100)
        cancel_button.setMinimumHeight(36)
        cancel_button.setProperty("class", "danger")
        cancel_button.clicked.connect(dialog.reject)

        button_layout.addStretch()
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        return dialog, color_picker

    def _configure_color_coordinate_picker(self, color_picker):
        target_hwnd = self._get_bound_window_hwnd()
        if target_hwnd:
            color_picker.set_target_hwnd(target_hwnd)

        if not self.current_parameters.get("search_region_enabled", False):
            return

        region_x = int(self.current_parameters.get("search_region_x", 0) or 0)
        region_y = int(self.current_parameters.get("search_region_y", 0) or 0)
        region_w = int(self.current_parameters.get("search_region_width", 0) or 0)
        region_h = int(self.current_parameters.get("search_region_height", 0) or 0)
        if region_w > 0 and region_h > 0:
            color_picker.set_search_region(region_x, region_y, region_w, region_h)
            logger.info(
                f"传递识别区域给颜色选择器: X={region_x}, Y={region_y}, W={region_w}, H={region_h}"
            )

    def _apply_initial_color_string_to_picker(self, color_picker, color_string):
        color_string = str(color_string or "").strip()
        if color_string:
            color_picker.set_color_string(color_string)

    def _emit_color_picker_updates(self, updates):
        if self.current_card_id is not None and updates:
            self.parameters_changed.emit(self.current_card_id, updates)

    def _store_color_picker_base_point(self, color_picker, updates):
        base_point = color_picker.get_base_point()
        if not base_point:
            return
        base_x, base_y = int(base_point[0]), int(base_point[1])
        self.current_parameters["color_picker_base_x"] = base_x
        self.current_parameters["color_picker_base_y"] = base_y
        updates["color_picker_base_x"] = base_x
        updates["color_picker_base_y"] = base_y

    def _show_color_coordinate_dialog(self, dialog):
        logger.info("显示颜色坐标选择对话框（非模态）")
        show_and_activate_overlay(dialog, log_prefix='颜色坐标对话框', focus=True)
