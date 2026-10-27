from functools import partial
from threading import Event
from shiboken6 import isValid
from .element_pick_job import pick_element

from ..parameter_panel_support import *
from utils.window.window_activation_utils import show_and_activate_overlay
from utils.input.uiautomation_runtime import import_uiautomation, uiautomation_thread_context
from .parameter_panel_picker_overlay import ParameterPanelPickerOverlay
from ..parameter_panel_support import logger
from PySide6.QtCore import QThread, Signal

class ParameterPanelSelectorMixin:

    _CONTROL_TYPE_EN_TO_CN = {
        "ButtonControl": "按钮",
        "EditControl": "编辑框",
        "TextControl": "文本",
        "CheckBoxControl": "复选框",
        "RadioButtonControl": "单选按钮",
        "ComboBoxControl": "下拉框",
        "ListControl": "列表",
        "ListItemControl": "列表项",
        "MenuControl": "菜单",
        "MenuItemControl": "菜单项",
        "TreeControl": "树",
        "TreeItemControl": "树节点",
        "TabControl": "选项卡",
        "TabItemControl": "选项卡项",
        "HyperlinkControl": "超链接",
        "WindowControl": "窗口",
        "PaneControl": "面板",
        "GroupControl": "分组",
        "DataGridControl": "数据表格",
        "TableControl": "表格",
    }

    @Slot()
    def _close_picker_overlay(self):
        overlay = getattr(self, '_picker_overlay', None)
        self._picker_overlay = None
        if overlay is not None and isValid(overlay):
            overlay.close()
            overlay.deleteLater()

    @Slot()
    def _on_picking_cancelled(self):
        """Handle picking cancelled."""
        self._close_picker_overlay()
        self._restore_picker_ui_state()

    @Slot()
    def _on_element_picked(self):
        """Handle element picked."""
        self._close_picker_overlay()
        self._restore_picker_ui_state()

        info = self._get_picked_info_or_warn()
        if info is None:
            return

        self._clear_picked_element_fields()
        control_type_cn = self._translate_control_type(info.control_type)
        element_fields = self._build_picked_element_fields(info, control_type_cn)
        filled_count = self._apply_picked_element_fields(element_fields)
        self._show_picked_element_result(info, control_type_cn, filled_count)

    def _restore_picker_ui_state(self) -> None:
        if hasattr(self, 'main_window') and self.main_window:
            self.main_window.showNormal()
            show_and_activate_overlay(self.main_window, log_prefix='元素拾取主窗口恢复', focus=True)
        self._set_element_picker_button_state(False)

    def _get_picked_info_or_warn(self):
        info = getattr(self, '_picked_info', None)
        if info is not None:
            return info
        QMessageBox.warning(
            self,
            "拾取失败",
            "未能获取到元素信息，请确保鼠标在目标元素上",
        )
        return None

    def _clear_picked_element_fields(self) -> None:
        for field_name in ['element_name', 'element_automation_id', 'element_class_name', 'element_control_type']:
            if field_name not in self.widgets:
                continue
            widget = self.widgets[field_name]
            if isinstance(widget, QLineEdit):
                widget.setText("")
                self.current_parameters[field_name] = ""
            elif isinstance(widget, QComboBox):
                widget.setCurrentIndex(0)
                self.current_parameters[field_name] = ""

    def _translate_control_type(self, control_type: str) -> str:
        if not control_type:
            return ""
        return self._CONTROL_TYPE_EN_TO_CN.get(control_type, control_type)

    def _build_picked_element_fields(self, info, control_type_cn: str) -> Dict[str, str]:
        return {
            'element_name': info.name,
            'element_automation_id': info.automation_id,
            'element_class_name': info.class_name,
            'element_control_type': control_type_cn,
        }

    def _apply_picked_element_fields(self, element_fields: Dict[str, str]) -> int:
        filled_count = 0
        for field_name, value in element_fields.items():
            if not value or field_name not in self.widgets:
                continue
            widget = self.widgets[field_name]
            if isinstance(widget, QLineEdit):
                widget.setText(value)
                self.current_parameters[field_name] = value
                filled_count += 1
            elif isinstance(widget, QComboBox):
                filled_count += self._apply_picked_combo_value(widget, field_name, value)
        return filled_count

    def _apply_picked_combo_value(self, widget: QComboBox, field_name: str, value: str) -> int:
        index = widget.findText(value)
        if index >= 0:
            widget.setCurrentIndex(index)
            self.current_parameters[field_name] = value
            return 1
        if value.endswith('Control'):
            return 0
        value_with_suffix = value + 'Control'
        index = widget.findText(value_with_suffix)
        if index < 0:
            return 0
        widget.setCurrentIndex(index)
        self.current_parameters[field_name] = value_with_suffix
        return 1

    def _show_picked_element_result(self, info, control_type_cn: str, filled_count: int) -> None:
        if filled_count <= 0:
            QMessageBox.warning(self, "拾取结果", "元素没有可用的属性信息")
            return

        msg = f"已填充 {filled_count} 个属性:\n"
        if info.name:
            msg += f"  名称: {info.name}\n"
        if info.automation_id:
            msg += f"  自动化标识: {info.automation_id}\n"
        if info.class_name:
            msg += f"  类名: {info.class_name}\n"
        if control_type_cn:
            msg += f"  控件类型: {control_type_cn}"
        QMessageBox.information(self, "拾取成功", msg)









    def _cancel_current_element_pick(self):
        if not self._picking_active:
            return
        self._picking_active = False
        self._background_jobs.cancel('element_picker')
        self._picked_info = None
        self._on_picking_cancelled()

    def _confirm_current_element_pick(self):
        if self._picking_active:
            self._picker_confirm.set()

    def _update_overlay_highlight(self, rect):
        if self._picker_overlay is not None:
            self._picker_overlay.highlight_rect = rect
            self._picker_overlay.update()

    def _update_highlight_border(self):
        """Update highlight border."""
        try:
            rect = getattr(self, '_highlight_rect', None)
            if not rect:
                return
            x, y, w, h = rect
            if w <= 0 or h <= 0:
                return
            if hasattr(self, '_highlight_border') and self._highlight_border:
                self._highlight_border.setGeometry(int(x), int(y), int(w), int(h))
                self._highlight_border.show()
                self._highlight_border.update()
        except Exception as e:
            logger.error(f"更新高亮边框失败: {e}")

    _ELEMENT_PICKER_BUTTON_TEXT = "拾取元素 (右键确认)"

    _ELEMENT_PICKING_BUTTON_TEXT = "拾取中... (右键确认, ESC取消)"

    def _start_element_picking(self):
        """Start picking UI element."""
        try:
            if not self._ensure_element_picker_available():
                return
            if self._picking_active:
                return
            self._initialize_picker_runtime_state()
            self._set_element_picker_button_state(True)
            self._minimize_picker_host_window()
            self._show_picker_overlay()
            self._start_element_pick_thread()
        except Exception as e:
            logger.error(f"启动元素拾取失败: {e}")
            self._cancel_current_element_pick()
            QMessageBox.warning(self, "拾取失败", f"启动元素拾取失败：{e}")

    def _ensure_element_picker_available(self) -> bool:
        from utils.window.element_picker import ElementPicker

        if ElementPicker.is_available():
            return True
        QMessageBox.warning(self, "错误", "UIAutomation模块不可用，无法拾取元素")
        return False

    def _set_element_picker_button_state(self, is_picking: bool) -> None:
        if hasattr(self, '_element_picker_button') and self._element_picker_button:
            self._element_picker_button.setText(
                self._ELEMENT_PICKING_BUTTON_TEXT if is_picking else self._ELEMENT_PICKER_BUTTON_TEXT
            )
            self._element_picker_button.setEnabled(not is_picking)

    def _minimize_picker_host_window(self) -> None:
        if hasattr(self, 'main_window') and self.main_window:
            self.main_window.showMinimized()

    def _show_picker_overlay(self) -> None:
        self._picker_overlay = self._own_parameter_tool(ParameterPanelPickerOverlay(self))
        logger.debug(
            f"[元素拾取] 创建PickerOverlay: geometry={self._picker_overlay.geometry()}, "
            f"DPI={self._picker_overlay.device_pixel_ratio}"
        )
        show_and_activate_overlay(self._picker_overlay, log_prefix='元素拾取覆盖层', focus=True)

    def _initialize_picker_runtime_state(self):
        self._picking_active = True
        self._picked_info = None
        self._picker_confirm = Event()

    def _start_element_pick_thread(self):
        def ready(info):
            self._picking_active = False
            self._picked_info = info
            self._on_element_picked() if info is not None else self._on_picking_cancelled()

        def failed(error):
            self._picking_active = False
            self._on_picking_cancelled()
            QMessageBox.warning(self, "拾取失败", f"无法读取元素：{error}")

        self._background_jobs.submit('element_picker', partial(pick_element, self._picker_confirm), ready, failed, self._update_overlay_highlight)

    def _select_color(self, line_edit: QLineEdit):

        """汉化的Qt颜色选择对话框"""

        current_color = QColor(line_edit.text())

        # 创建颜色对话框

        dialog = QColorDialog(self)

        dialog.setWindowTitle("选择颜色")

        dialog.setCurrentColor(current_color)

        dialog.setOption(QColorDialog.DontUseNativeDialog, True)

        # 手动汉化按钮文本

        def translate_color_dialog_buttons():

            for button in dialog.findChildren(QPushButton):

                button_text = button.text().lower()

                if 'ok' in button_text or button_text == '&ok':

                    button.setText("确定(&O)")

                elif 'cancel' in button_text or button_text == '&cancel':

                    button.setText("取消(&C)")

                elif 'pick screen color' in button_text or 'screen' in button_text:

                    button.setText("屏幕取色")

                elif 'add to custom colors' in button_text or 'custom' in button_text:

                    button.setText("添加到自定义颜色")

        from PySide6.QtCore import QTimer

        QTimer.singleShot(50, dialog, translate_color_dialog_buttons)

        from ui.dialogs.dialog_manager import exec_dialog
        color = exec_dialog(dialog, read_result=lambda result: dialog.selectedColor() if result == QDialog.DialogCode.Accepted else None)
        if color is not None:
            if self._get_registered_widget_name(line_edit) is None:
                return

            if color.isValid():

                line_edit.setText(color.name())

                # 同步更新current_parameters

                param_name = self._update_current_parameter_from_widget(line_edit, color.name())

                if param_name and self.current_card_id is not None:

                    self.parameters_changed.emit(self.current_card_id, {param_name: color.name()})

    def _select_color_rgb(self, line_edit: QLineEdit):
        try:
            from PySide6.QtWidgets import QMessageBox

            dialog, color_picker = self._create_color_coordinate_dialog()
            self._apply_initial_color_string_to_picker(color_picker, line_edit.text())

            def on_dialog_accepted():
                logger.info("确定按钮被点击（对话框accepted）")
                color_string = color_picker.get_color_string()
                logger.info(f"获取到颜色字符串: '{color_string}'")
                if not color_string:
                    logger.warning("颜色字符串为空")
                    QMessageBox.warning(self, "提示", "未选择任何颜色")
                    dialog.close()
                    return

                line_edit.setText(color_string)
                param_name = self._update_current_parameter_from_widget(line_edit, color_string)
                if param_name:
                    updates = {param_name: color_string}
                    self._emit_color_picker_updates(updates)
                logger.info(f"颜色选择完成: {color_string}")
                dialog.close()

            def on_dialog_rejected():
                logger.info("对话框被取消（rejected）")
                dialog.close()

            dialog.accepted.connect(on_dialog_accepted)
            dialog.rejected.connect(on_dialog_rejected)
            self._show_color_coordinate_dialog(dialog)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            import traceback

            logger.error(f"颜色选择器启动失败: {e}")
            logger.error(traceback.format_exc())
            QMessageBox.critical(self, "错误", f"颜色选择器启动失败: {e}")

    def _populate_color_list(self, color_list, color_string: str):

        """填充颜色列表，显示颜色块和坐标信息"""

        from PySide6.QtWidgets import QListWidgetItem

        from PySide6.QtGui import QPixmap, QIcon, QPainter, QBrush, QColor

        from PySide6.QtCore import Qt

        color_list.clear()

        if not color_string or not color_string.strip():

            return

        # 解析颜色字符串：格式为 "R,G,B|偏移X,偏移Y,R,G,B|..."

        parts = color_string.strip().split('|')

        for i, part in enumerate(parts):

            part = part.strip()

            if not part:

                continue

            try:

                values = [v.strip() for v in part.split(',')]

                if i == 0:

                    # 基准点：R,G,B

                    if len(values) >= 3:

                        r, g, b = int(values[0]), int(values[1]), int(values[2])

                        display_text = f"基准点  RGB({r},{g},{b})"

                        color = QColor(r, g, b)

                    else:

                        continue

                else:

                    # 偏移点：偏移X,偏移Y,R,G,B

                    if len(values) >= 5:

                        offset_x, offset_y = int(values[0]), int(values[1])

                        r, g, b = int(values[2]), int(values[3]), int(values[4])

                        display_text = f"偏移({offset_x:+d},{offset_y:+d})  RGB({r},{g},{b})"

                        color = QColor(r, g, b)

                    else:

                        continue

                # 创建颜色图标（16x16 的颜色块）

                pixmap = QPixmap(16, 16)

                pixmap.fill(Qt.GlobalColor.transparent)

                painter = QPainter(pixmap)

                painter.setRenderHint(QPainter.RenderHint.Antialiasing)

                painter.setBrush(QBrush(color))

                # 从主题管理器获取边框颜色

                from themes import get_theme_manager

                theme_mgr = get_theme_manager()

                border_color = QColor(theme_mgr.get_color('border'))

                painter.setPen(border_color)

                painter.drawRect(0, 0, 15, 15)

                painter.end()

                # 添加列表项

                item = QListWidgetItem(QIcon(pixmap), display_text)

                color_list.addItem(item)

            except (ValueError, IndexError) as e:

                logger.warning(f"解析颜色部分失败: {part}, 错误: {e}")

                continue

    def _restore_multi_color_raw_data(self, color_list, param_name: str):
        current_raw = color_list.property("raw_color_data")
        if current_raw:
            return current_raw
        current_raw = self.current_parameters.get(param_name, "")
        if current_raw and str(current_raw).strip():
            color_list.setProperty("raw_color_data", current_raw)
            logger.debug(f"[颜色选择器] 从 current_parameters 恢复颜色数据: {current_raw}")
        return current_raw

    def _apply_multi_color_string(self, color_list, param_name: str, color_string, color_picker):
        self._populate_color_list(color_list, color_string)
        item_count = color_list.count()
        color_list.setFixedHeight(min(150, max(60, item_count * 30 + 10)))
        color_list.setProperty("raw_color_data", color_string)

        updates = {param_name: color_string}
        self.current_parameters[param_name] = color_string
        self._emit_color_picker_updates(updates)
        if hasattr(self, "_refresh_arrow_preview"):
            self._refresh_arrow_preview(param_name)

    def _select_color_rgb_list(self, color_list, param_name: str):
        try:
            from PySide6.QtWidgets import QMessageBox

            dialog, color_picker = self._create_color_coordinate_dialog()
            current_raw = self._restore_multi_color_raw_data(color_list, param_name)
            self._apply_initial_color_string_to_picker(color_picker, current_raw)

            def on_dialog_accepted():
                color_string = color_picker.get_color_string()
                if not color_string:
                    QMessageBox.warning(self, "提示", "未选择任何颜色")
                    dialog.close()
                    return

                self._apply_multi_color_string(color_list, param_name, color_string, color_picker)
                logger.info(f"颜色选择完成: {color_string}")
                dialog.close()

            dialog.accepted.connect(on_dialog_accepted)
            dialog.rejected.connect(dialog.close)
            self._show_color_coordinate_dialog(dialog)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            import traceback

            logger.error(f"颜色选择器启动失败: {e}")
            logger.error(traceback.format_exc())
            QMessageBox.critical(self, "错误", f"颜色选择器启动失败: {e}")

    _COLOR_COORDINATE_INFO_TEXT = (
        "点击下方按钮后，在目标窗口上点击鼠标获取该位置的颜色。\n"
        "支持多点选择以构建多点定位字符串，提高找色精确度。\n\n"
        "- 第一个点为基准点\n"
        "- 后续点自动计算相对偏移\n"
        "- 可连续左键取色，点覆盖层“完成取色”再返回\n"
        "- 多点格式: 基准R,G,B|偏移X,偏移Y,R,G,B|..."
    )

    def _create_color_coordinate_dialog(self, *, target_hwnd=None):
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
        # 取色会临时隐藏参数页，沿用工具启动保护，避免 hideEvent 卸载本轮对话框。
        color_picker.select_button.clicked.disconnect(color_picker.start_selection)
        color_picker.select_button.clicked.connect(partial(self._start_parameter_tool, color_picker))
        dialog.finished.connect(lambda: dialog.setProperty("parameterDisposed", True))
        dialog.finished.connect(color_picker.cleanup)
        dialog.destroyed.connect(color_picker.cleanup)
        self._configure_color_coordinate_picker(color_picker, target_hwnd=target_hwnd)
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

    def _configure_color_coordinate_picker(self, color_picker, *, target_hwnd=None):
        if target_hwnd is None:
            target_hwnd = self._get_target_window_hwnd()
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



    def _show_color_coordinate_dialog(self, dialog):
        previous = getattr(self, '_color_dialog', None)
        if previous is not None and isValid(previous):
            previous.blockSignals(True)
            previous.close()
            previous.deleteLater()
        self._color_dialog = self._own_parameter_tool(dialog)
        dialog.destroyed.connect(lambda: setattr(self, '_color_dialog', None) if self._color_dialog is dialog else None)
        show_and_activate_overlay(dialog, log_prefix='颜色坐标对话框', focus=True)

    def _select_ocr_region(self, param_name: str):
        """启动OCR区域选择工具"""
        logger.info(f"OCR区域选择按钮被点击，参数名: {param_name}")

        try:
            from ui.selectors.ocr_region_selector import OCRRegionSelectorWidget

            # 获取绑定的窗口句柄
            target_window_hwnd = self._get_target_window_hwnd()

            if not target_window_hwnd:
                from PySide6.QtWidgets import QMessageBox
                logger.warning("未找到绑定的窗口")
                QMessageBox.warning(self, "警告", "未找到绑定的窗口，请先绑定目标窗口")
                return

            # 创建区域选择器，直接传递窗口句柄
            self.region_selector = self._create_ocr_region_selector("region_selector")

            self.region_selector.set_target_window_hwnd(target_window_hwnd)

            # 连接信号
            self.region_selector.region_selected.connect(
                lambda x, y, w, h: self._on_ocr_region_selected(param_name, x, y, w, h)
            )

            # 开始选择
            self._start_parameter_tool(self.region_selector)

        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            logger.error(f"启动区域选择工具失败: {str(e)}")
            import traceback
            logger.error(f"详细错误信息:\n{traceback.format_exc()}")
            QMessageBox.warning(self, "错误", f"启动区域选择工具失败: {str(e)}")

    def _get_enabled_bound_windows_for_selector(self) -> List[Dict[str, Any]]:
        candidates = []
        for host in (self.main_window, self.parent_window):
            if host is None:
                continue
            if hasattr(host, "bound_windows"):
                candidates = host.bound_windows
                break
            if hasattr(host, "config"):
                config = host.config
                if isinstance(config, dict):
                    candidates = config.get("bound_windows", [])
                else:
                    candidates = config.bound_windows
                break
        if not isinstance(candidates, list):
            raise TypeError("绑定窗口必须是列表")
        enabled_windows = []
        for window_info in candidates:
            if not isinstance(window_info, dict):
                raise TypeError("绑定窗口配置必须是字典")
            enabled = window_info.get("enabled", True)
            if not isinstance(enabled, bool):
                raise TypeError("绑定窗口启用状态必须是布尔值")
            if not enabled:
                continue
            enabled_windows.append(window_info)
        return enabled_windows



    def _on_ocr_region_selected(self, param_name: str, x: int, y: int, width: int, height: int):
        """处理OCR区域选择完成"""
        try:
            binding_info = {}
            selector = getattr(self, 'region_selector', None)
            if selector and hasattr(selector, 'get_region_binding_info'):
                try:
                    binding_info = selector.get_region_binding_info() or {}
                except Exception:
                    binding_info = {}

            # 更新相关参数 - 使用正确的方法设置值
            if 'region_x' in self.widgets:
                widget = self.widgets['region_x']
                if hasattr(widget, 'setValue'):
                    widget.setValue(x)
                elif hasattr(widget, 'setText'):
                    widget.setText(str(x))

            if 'region_y' in self.widgets:
                widget = self.widgets['region_y']
                if hasattr(widget, 'setValue'):
                    widget.setValue(y)
                elif hasattr(widget, 'setText'):
                    widget.setText(str(y))

            if 'region_width' in self.widgets:
                widget = self.widgets['region_width']
                if hasattr(widget, 'setValue'):
                    widget.setValue(width)
                elif hasattr(widget, 'setText'):
                    widget.setText(str(width))

            if 'region_height' in self.widgets:
                widget = self.widgets['region_height']
                if hasattr(widget, 'setValue'):
                    widget.setValue(height)
                elif hasattr(widget, 'setText'):
                    widget.setText(str(height))

            # 同步更新current_parameters
            self.current_parameters['region_x'] = x
            self.current_parameters['region_y'] = y
            self.current_parameters['region_width'] = width
            self.current_parameters['region_height'] = height

            binding_params = {
                'region_hwnd': binding_info.get('region_hwnd', 0),
                'region_window_title': binding_info.get('region_window_title', ''),
                'region_window_class': binding_info.get('region_window_class', ''),
                'region_client_width': binding_info.get('region_client_width', 0),
                'region_client_height': binding_info.get('region_client_height', 0),
            }

            for name, value in binding_params.items():
                self.current_parameters[name] = value
                if name in self.widgets:
                    widget = self.widgets[name]
                    if hasattr(widget, 'setValue'):
                        widget.setValue(value)
                    elif hasattr(widget, 'setText'):
                        widget.setText(str(value))

            # 更新区域坐标显示
            coord_text = None
            if 'region_coordinates' in self.widgets:
                coord_text = f"X={x}, Y={y}, 宽度={width}, 高度={height}"
                self.widgets['region_coordinates'].setText(coord_text)
                self.current_parameters['region_coordinates'] = coord_text

            # 发出参数更改信号
            if self.current_card_id is not None:
                self.parameters_changed.emit(self.current_card_id, {
                    'region_x': x,
                    'region_y': y,
                    'region_width': width,
                    'region_height': height,
                    'region_hwnd': binding_params['region_hwnd'],
                    'region_window_title': binding_params['region_window_title'],
                    'region_window_class': binding_params['region_window_class'],
                    'region_client_width': binding_params['region_client_width'],
                    'region_client_height': binding_params['region_client_height'],
                    'region_coordinates': coord_text if coord_text is not None else None
                })

            # 框选完成后只更新参数值，不调用应用参数，避免自动关闭面板
            # 用户需要手动点击"应用"按钮来应用参数并关闭面板
            logger.info("OCR区域选择完成，参数已更新，请点击'应用'按钮保存")

        except Exception as e:
            logger.exception(f"处理OCR区域选择结果失败: {e}")

    def _select_multi_coordinates(self, param_name: str):
        """启动多点坐标选择工具"""
        logger.info(f"多点坐标选择按钮被点击，参数名: {param_name}")

        selector = None
        try:
            from ui.selectors.coordinate_selector import MultiPointCoordinateSelectorWidget

            target_window_hwnd = self._get_target_window_hwnd()
            if not target_window_hwnd:
                QMessageBox.warning(self, "错误", "未找到目标窗口，请先绑定窗口")
                return
            existing = getattr(self, 'multi_coordinate_selector', None)
            if existing is not None and isValid(existing) and not existing.property("parameterDisposed"):
                logger.info("多点坐标采集尚未结束，忽略重复启动")
                return
            selector = MultiPointCoordinateSelectorWidget(self)
            self.multi_coordinate_selector = self._own_parameter_tool(selector)
            self.multi_coordinate_selector.target_window_hwnd = target_window_hwnd
            self.multi_coordinate_selector.selection_finished.connect(
                self.multi_coordinate_selector.close, Qt.ConnectionType.QueuedConnection,
            )

            # 连接信号
            self.multi_coordinate_selector.coordinates_selected.connect(
                lambda coords, timestamps: self._on_multi_coordinates_selected(param_name, coords, timestamps)
            )

            # 开始选择
            logger.info("开始启动多点坐标选择器...")
            self._start_parameter_tool(self.multi_coordinate_selector)

        except Exception as e:
            if selector is not None and isValid(selector):
                selector.close()
                selector.deleteLater()
            logger.error(f"启动多点坐标选择工具失败: {e}")
            QMessageBox.warning(self, "错误", f"启动多点坐标选择工具失败: {str(e)}")

    def _on_multi_coordinates_selected(self, param_name: str, coordinates: list, timestamps: list):
        """处理多点坐标选择完成"""
        try:
            logger.info(f"多点坐标选择完成: {param_name}, {len(coordinates)} 个点")

            # 将坐标列表和时间戳转换为文本格式
            # 格式: x,y,timestamp
            if not coordinates or len(timestamps) != len(coordinates):
                raise ValueError("采集坐标与时间戳数量不一致，不能保存拖拽路径")
            coord_text = "\n".join(f"{x},{y},{t:.3f}" for (x, y), t in zip(coordinates, timestamps))
            logger.info(f"已保存带时间戳的路径点：{len(coordinates)} 个点")

            # 更新对应的文本编辑框
            if param_name in self.widgets:
                widget = self.widgets[param_name]
                if hasattr(widget, 'setPlainText'):
                    widget.setPlainText(coord_text)
                    logger.info("已更新路径点坐标")

            # 同步更新current_parameters
            self.current_parameters[param_name] = coord_text

            # 自动应用参数（不关闭面板，以便用户继续编辑）
            self._apply_parameters(auto_close=False)

        except Exception as e:
            logger.exception("处理多点坐标选择结果失败")
            QMessageBox.warning(self, "错误", f"保存拖拽路径失败：{e}")

    def _ensure_offset_selector(self):
        existing = self.offset_selector
        if existing is not None and (not isValid(existing) or existing.property("parameterDisposed")):
            self.offset_selector = None
        from ui.selectors.coordinate_selector import OffsetSelectorWidget

        if self.offset_selector is None:
            self.offset_selector = self._own_parameter_tool(OffsetSelectorWidget(self))
            self.offset_selector.offset_selected.connect(self._handle_offset_selected)
            self.offset_selector.selection_finished.connect(
                self.offset_selector.close, Qt.ConnectionType.QueuedConnection,
            )
        return self.offset_selector

    def _select_offset(self, param_name):
        from .offset_reference import OffsetReferenceLookup
        try:
            hwnd = self._get_target_window_hwnd()
            if hwnd is None:
                raise ValueError('没有可用的绑定窗口，无法选择偏移')
            values = self._collect_current_parameters()
            if 'image_paths' in values:
                values['image_paths'] = self._convert_display_to_full_paths(values['image_paths'])
            lookup = OffsetReferenceLookup(values, self.param_definitions[param_name], hwnd, self.current_card_id)
            def ready(result):
                try:
                    if self._get_target_window_hwnd() != hwnd:
                        raise ValueError('绑定窗口已经改变，请重新选择偏移')
                    selector = self._ensure_offset_selector()
                    self._offset_param_name = param_name
                    selector.target_window_hwnd = hwnd
                    selector.base_point = None
                    selector.base_rect = None
                    x, y, rect = result
                    if x is not None and y is not None:
                        selector.set_base_point(x, y)
                    if rect is not None:
                        selector.set_base_rect(*rect)
                    self._start_parameter_tool(selector)
                except Exception as error:
                    failed(error)
            def failed(error):
                logger.error('定位偏移基准失败：%s', error)
                QMessageBox.warning(self, '选择偏移失败', str(error))
            self._background_jobs.submit('offset-reference', lookup.resolve, ready, failed)
        except Exception as error:
            QMessageBox.warning(self, '选择偏移失败', str(error))











    def _handle_offset_selected(self, dx: int, dy: int):
        param_name = self._offset_param_name
        if not param_name:
            logger.warning("偏移选择回调缺少参数名")
            return
        self._on_offset_selected(param_name, dx, dy)

    def _build_offset_updates(self, param_name, dx, dy):
        related = self.param_definitions[param_name]['related_params']
        if len(related) not in (2, 3) or any(name not in self.param_definitions for name in related):
            raise ValueError('偏移工具的参数定义无效')
        updates = {related[0]: int(dx), related[1]: int(dy)}
        if len(related) == 3:
            if '固定偏移' not in self.param_definitions[related[2]]['options']:
                raise ValueError('偏移工具的模式定义无效')
            updates[related[2]] = '固定偏移'
        return updates

    def _apply_offset_widget_value(self, widget, value) -> bool:
        if widget is None:
            return False
        try:
            if isinstance(widget, QSpinBox):
                widget.setValue(int(value))
                return widget.value() == int(value)
            if isinstance(widget, QDoubleSpinBox):
                widget.setValue(float(value))
                return abs(widget.value() - float(value)) < 1e-6
            if isinstance(widget, QComboBox):
                widget.setCurrentText(str(value))
                return widget.currentText() == str(value)
            if isinstance(widget, QLineEdit):
                widget.setText(str(value))
                return widget.text() == str(value)
            if hasattr(widget, "setValue"):
                widget.setValue(value)
                return True
            if hasattr(widget, "setCurrentText"):
                widget.setCurrentText(str(value))
                return True
            if hasattr(widget, "setText"):
                widget.setText(str(value))
                return True
        except Exception:
            return False
        return False

    def _sync_offset_updates_to_widgets(self, updates):
        needs_refresh = False
        for key, value in updates.items():
            self.current_parameters[key] = value
            widget = self._get_value_widget(key)
            if not self._apply_offset_widget_value(widget, value):
                needs_refresh = True

        if needs_refresh:
            self._rebuild_parameter_widgets()
            for key, value in updates.items():
                widget = self._get_value_widget(key)
                self._apply_offset_widget_value(widget, value)

    def _on_offset_selected(self, param_name: str, dx: int, dy: int):
        try:
            logger.info(
                f"偏移选择完成: param_name={param_name}, dx={dx}, dy={dy}"
            )
            updates = self._build_offset_updates(param_name, dx, dy)
            self._sync_offset_updates_to_widgets(updates)
            if self.current_card_id is not None:
                self.parameters_changed.emit(self.current_card_id, updates)
        except Exception as exc:
            logger.error(f"处理偏移选择结果失败: {exc}")

    def _select_coordinate_with_display(self, param_name: str):
        """启动坐标选择工具（带显示更新）"""
        logger.info(f"坐标选择按钮被点击（带显示），参数名: {param_name}")

        selector = None
        try:
            from ui.selectors.coordinate_selector import CoordinateSelectorWidget

            # 创建坐标选择器
            existing = getattr(self, 'coordinate_selector', None)
            if existing is not None and isValid(existing) and not existing.property("parameterDisposed"):
                logger.info("坐标采集尚未结束，忽略重复启动")
                return
            target_window_hwnd = self._get_target_window_hwnd()
            if not target_window_hwnd:
                QMessageBox.warning(self, "错误", "未找到目标窗口，请先绑定窗口")
                return
            selector = CoordinateSelectorWidget(self)
            self.coordinate_selector = self._own_parameter_tool(selector)
            self.coordinate_selector.target_window_hwnd = target_window_hwnd
            self.coordinate_selector.selection_finished.connect(
                self.coordinate_selector.close, Qt.ConnectionType.QueuedConnection,
            )

            # 连接信号
            self.coordinate_selector.coordinate_selected.connect(
                lambda x, y: self._on_coordinate_selected_with_display(param_name, x, y)
            )

            # 开始选择
            self._start_parameter_tool(self.coordinate_selector)

        except Exception as e:
            if selector is not None and isValid(selector):
                selector.close()
                selector.deleteLater()
            logger.error(f"启动坐标选择工具失败: {e}")
            QMessageBox.warning(self, "错误", f"启动坐标选择工具失败: {str(e)}")

    def _on_coordinate_selected_with_display(self, param_name: str, x: int, y: int):
        """处理坐标选择完成（更新显示控件）"""
        try:
            logger.info(f"坐标选择完成（带显示）: param_name={param_name}, x={x}, y={y}")

            # 更新显示控件（使用参数名作为key）
            coord_display_key = f'_coord_display_{param_name}'
            if hasattr(self, coord_display_key):
                coord_display = getattr(self, coord_display_key)
                if coord_display:
                    coord_display.setText(f"{x},{y}")

            # 根据关联参数动态回填坐标参数
            coord_params_key = f'_coord_params_{param_name}'
            params_tuple = getattr(self, coord_params_key, None)
            x_param = 'coordinate_x'
            y_param = 'coordinate_y'
            related_params = []
            if isinstance(params_tuple, tuple) and len(params_tuple) >= 2:
                x_param = params_tuple[0] or x_param
                y_param = params_tuple[1] or y_param
                if len(params_tuple) >= 3 and isinstance(params_tuple[2], (list, tuple)):
                    related_params = list(params_tuple[2])

            updates = {
                x_param: x,
                y_param: y,
            }

            # 若配置了第三个关联参数，则同步写入标准化坐标字符串，便于参数回显
            if len(related_params) >= 3 and related_params[2]:
                updates[str(related_params[2])] = f"{x},{y}"

            for key, value in updates.items():
                self.current_parameters[key] = value

            logger.info(f"更新坐标参数: {updates}")

            # 发出参数更改信号
            if self.current_card_id is not None:
                self.parameters_changed.emit(self.current_card_id, updates)

        except Exception as e:
            logger.error(f"处理坐标选择结果失败: {e}")

    def _select_coordinate(self, param_name: str):
        logger.info(f"坐标选择按钮被点击，参数名: {param_name}")
        selector = None
        try:
            from ui.selectors.coordinate_selector import CoordinateSelectorWidget

            existing = getattr(self, 'coordinate_selector', None)
            if existing is not None and isValid(existing) and not existing.property("parameterDisposed"):
                logger.info("坐标采集尚未结束，忽略重复启动")
                return
            target_window_hwnd = self._get_target_window_hwnd()
            if not target_window_hwnd:
                QMessageBox.warning(self, "错误", "未找到目标窗口，请先绑定窗口")
                return
            selector = CoordinateSelectorWidget(self)
            self.coordinate_selector = self._own_parameter_tool(selector)
            self.coordinate_selector.target_window_hwnd = target_window_hwnd
            self.coordinate_selector.selection_finished.connect(
                self.coordinate_selector.close, Qt.ConnectionType.QueuedConnection,
            )

            logger.info(f"设置坐标选择器窗口句柄: {target_window_hwnd}")
            self.coordinate_selector.coordinate_selected.connect(
                lambda x, y, selected_param=param_name: self._on_coordinate_selected(selected_param, x, y)
            )
            self._start_parameter_tool(self.coordinate_selector)
        except Exception as e:
            if selector is not None and isValid(selector):
                selector.close()
                selector.deleteLater()

            logger.error(f"启动坐标选择工具失败: {e}")
            QMessageBox.warning(self, "错误", f"启动坐标选择工具失败: {str(e)}")

    _TEXT_COORDINATE_SELECTORS = {
        "scroll_coordinate_selector": ("scroll_start_position", "更新滚动起始位置"),
        "drag_start_coordinate_selector": ("drag_start_position", "更新拖拽起点"),
        "drag_end_coordinate_selector": ("drag_end_position", "更新拖拽终点"),
        "move_start_coordinate_selector": ("move_start_position", "更新鼠标移动起点"),
        "move_end_coordinate_selector": ("move_end_position", "更新鼠标移动终点"),
    }

    def _set_widget_value(self, widget, value):
        if widget is None:
            return
        if hasattr(widget, "setValue"):
            widget.setValue(value)
            return
        if hasattr(widget, "setText"):
            widget.setText(str(value))

    def _set_named_widget_value(self, widget_name: str, value):
        if widget_name in self.widgets:
            self._set_widget_value(self.widgets[widget_name], value)

    def _emit_coordinate_updates(self, updates):
        if self.current_card_id is not None and updates:
            self.parameters_changed.emit(self.current_card_id, updates)

    def _update_text_coordinate_param(self, widget_name: str, param_name: str, x: int, y: int, log_text: str):
        value = f"{x},{y}"
        self._set_named_widget_value(widget_name, value)
        self.current_parameters[param_name] = value
        logger.info(f"{log_text}: {value}")
        self._emit_coordinate_updates({param_name: value})

    def _update_combo_mouse_coordinate_params(self, x: int, y: int):
        changed_params = {}
        self._set_named_widget_value("combo_seq_mouse_x", x)
        self._set_named_widget_value("combo_seq_mouse_y", y)
        self.current_parameters["combo_seq_mouse_x"] = x
        self.current_parameters["combo_seq_mouse_y"] = y
        changed_params["combo_seq_mouse_x"] = x
        changed_params["combo_seq_mouse_y"] = y

        logger.info(f"更新组合键鼠标坐标: x={x}, y={y}")
        self._emit_coordinate_updates(changed_params)

    def _update_combined_coordinate_param(self, param_name: str, x: int, y: int):
        value = f"{x},{y}"
        self._set_named_widget_value(param_name, value)
        self.current_parameters[param_name] = value
        logger.info(f"更新合并坐标参数 {param_name}: {value}")
        self._emit_coordinate_updates({param_name: value})

    def _update_anchor_point_coordinate(self, param_name: str, x: int, y: int):
        display_value = f"[{x}, {y}]"
        self._set_named_widget_value(param_name, display_value)
        self.current_parameters[param_name] = [x, y]
        logger.info(f"更新基准点坐标 {param_name}: {display_value}")
        self._emit_coordinate_updates({param_name: [x, y]})

    def _update_default_coordinate_params(self, x: int, y: int):
        self._set_named_widget_value("coordinate_x", x)
        self._set_named_widget_value("coordinate_y", y)
        self.current_parameters["coordinate_x"] = x
        self.current_parameters["coordinate_y"] = y
        logger.info(f"更新默认坐标参数: x={x}, y={y}")
        self._emit_coordinate_updates({"coordinate_x": x, "coordinate_y": y})

    def _on_coordinate_selected(self, param_name: str, x: int, y: int):
        try:
            logger.info(f"坐标选择完成: param_name={param_name}, x={x}, y={y}")

            if param_name in self._TEXT_COORDINATE_SELECTORS:
                widget_name, log_text = self._TEXT_COORDINATE_SELECTORS[param_name]
                self._update_text_coordinate_param(widget_name, widget_name, x, y, log_text)
                return

            if param_name in ("combo_key_sequence_mouse_coord_selector", "combo_mouse_coordinate_selector"):
                self._update_combo_mouse_coordinate_params(x, y)
                return

            if param_name in ["scroll_start_position"]:
                self._update_combined_coordinate_param(param_name, x, y)
                return

            if param_name == "anchor_point":
                self._update_anchor_point_coordinate(param_name, x, y)
                return

            self._update_default_coordinate_params(x, y)
        except Exception as e:
            logger.error(f"处理坐标选择结果失败: {e}")

    def _select_motion_region(self, param_name: str):
        logger.info(f"Motion region selector triggered: {param_name}")
        initial_region = self._get_named_region_values(
            ('minimap_x', 'minimap_y', 'minimap_width', 'minimap_height'),
            defaults=(1150, 40, 50, 50),
        )
        self._start_ocr_region_selection(
            'motion_region_selector',
            'motion region selection',
            initial_region,
            lambda x, y, w, h: self._on_motion_region_selected(param_name, x, y, w, h),
            '启动移动检测区域选择工具失败',
        )

    def _select_image_region(self, param_name: str):
        logger.info(f"Image region selector triggered: {param_name}")
        param_prefix = self._get_param_prefix_for_selector(param_name)
        initial_region = self._get_prefixed_region_values(param_prefix)
        self._start_ocr_region_selection(
            'image_region_selector',
            'image region selection',
            initial_region,
            lambda x, y, w, h: self._on_image_region_selected(param_name, x, y, w, h),
            '启动图片识别区域选择工具失败',
        )

    def _select_multi_image_region(self, param_name: str):
        logger.info(f"Multi-image region selector triggered: {param_name}")
        initial_region = self._get_named_region_values(
            (
                'multi_recognition_region_x',
                'multi_recognition_region_y',
                'multi_recognition_region_width',
                'multi_recognition_region_height',
            )
        )
        self._start_ocr_region_selection(
            'multi_image_region_selector',
            'multi image region selection',
            initial_region,
            lambda x, y, w, h: self._on_multi_image_region_selected(param_name, x, y, w, h),
            '启动多图识别区域选择工具失败',
        )

    def _select_color_search_region(self, param_name: str):
        logger.info(f"Color search region selector triggered: {param_name}")
        initial_region = self._get_named_region_values(
            ('search_region_x', 'search_region_y', 'search_region_width', 'search_region_height')
        )
        self._start_ocr_region_selection(
            'color_region_selector',
            'color search region selection',
            initial_region,
            lambda x, y, w, h: self._on_color_search_region_selected(param_name, x, y, w, h),
            '启动找色识别区域选择工具失败',
        )

    def _get_param_prefix_for_selector(self, param_name: str) -> str:
        if param_name in self.param_definitions:
            return self.param_definitions[param_name].get('param_prefix', 'recognition_region')
        return 'recognition_region'

    def _on_motion_region_selected(self, param_name: str, x: int, y: int, width: int, height: int):
        try:
            self._store_named_region_values(
                ('minimap_x', 'minimap_y', 'minimap_width', 'minimap_height'),
                x,
                y,
                width,
                height,
            )
            region_text = f"X={x}, Y={y}, 宽度={width}, 高度={height}"
            self._apply_region_button_text('motion_detection_region', region_text, '已更新运动区域文本')
            self.current_parameters['motion_detection_region'] = region_text
            self._apply_parameters(auto_close=False)
        except Exception as exc:
            logger.error(f"应用运动区域选择结果失败: {exc}")

    def _on_image_region_selected(self, param_name: str, x: int, y: int, width: int, height: int):
        try:
            logger.info(f"已选择图片区域: X={x}, Y={y}, W={width}, H={height}")
            param_prefix = self._get_param_prefix_for_selector(param_name)
            self._store_prefixed_region_values(param_prefix, x, y, width, height)
            button_text = self._build_region_button_text(x, y, width, height)
            self._apply_region_button_text(param_name, button_text, '已更新图片区域按钮文本')
            self._apply_parameters(auto_close=False)
        except Exception as exc:
            logger.error(f"应用图片区域选择结果失败: {exc}")

    def _on_multi_image_region_selected(self, param_name: str, x: int, y: int, width: int, height: int):
        try:
            logger.info(f"已选择多图区域: X={x}, Y={y}, W={width}, H={height}")
            self._store_named_region_values(
                (
                    'multi_recognition_region_x',
                    'multi_recognition_region_y',
                    'multi_recognition_region_width',
                    'multi_recognition_region_height',
                ),
                x,
                y,
                width,
                height,
            )
            button_text = self._build_region_button_text(x, y, width, height)
            self._apply_region_button_text(param_name, button_text, '已更新多图区域按钮文本')
            self._apply_parameters(auto_close=False)
        except Exception as exc:
            logger.error(f"应用多图区域选择结果失败: {exc}")

    def _on_color_search_region_selected(self, param_name: str, x: int, y: int, width: int, height: int):
        try:
            logger.info(f"已选择找色区域: X={x}, Y={y}, W={width}, H={height}")
            self._store_named_region_values(
                ('search_region_x', 'search_region_y', 'search_region_width', 'search_region_height'),
                x,
                y,
                width,
                height,
            )
            button_text = self._build_region_button_text(x, y, width, height)
            self._apply_region_button_text(param_name, button_text, 'Updated color search region button text')
            logger.info(f"发送找色区域参数: 卡片ID={self.current_card_id}")
            self.parameters_changed.emit(self.current_card_id, self.current_parameters.copy())
        except Exception as exc:
            logger.error(f"应用找色区域选择结果失败: {exc}")

    def _normalize_region_value(self, value, default):
        try:
            return int(value if value is not None and value != "" else default)
        except Exception:
            return int(default)

    def _get_prefixed_region_values(self, prefix: str, defaults=(0, 0, 0, 0)):
        return (
            self._normalize_region_value(self.current_parameters.get(f"{prefix}_x"), defaults[0]),
            self._normalize_region_value(self.current_parameters.get(f"{prefix}_y"), defaults[1]),
            self._normalize_region_value(self.current_parameters.get(f"{prefix}_width"), defaults[2]),
            self._normalize_region_value(self.current_parameters.get(f"{prefix}_height"), defaults[3]),
        )

    def _get_named_region_values(self, keys, defaults=(0, 0, 0, 0)):
        return tuple(
            self._normalize_region_value(self.current_parameters.get(key), default)
            for key, default in zip(keys, defaults)
        )

    def _create_ocr_region_selector(self, attr_name: str):
        from ui.selectors.ocr_region_selector import OCRRegionSelectorWidget

        previous = getattr(self, attr_name, None)
        if previous is not None and isValid(previous):
            previous.close()
        selector = self._own_parameter_tool(OCRRegionSelectorWidget(self))
        setattr(self, attr_name, selector)
        selector.selection_finished.connect(selector.close, Qt.ConnectionType.QueuedConnection)
        return selector

    def _configure_ocr_region_selector_target(self, selector, scene_name: str):
        target_hwnd = self._get_target_window_hwnd()
        if not target_hwnd:
            raise ValueError("没有可用的绑定窗口，无法选择识别区域")
        selector.set_target_window_hwnd(target_hwnd)

    def _start_ocr_region_selection(
        self,
        selector_attr_name: str,
        scene_name: str,
        initial_region,
        on_region_selected,
        error_prefix: str,
    ):
        try:
            selector = self._create_ocr_region_selector(selector_attr_name)
            self._configure_ocr_region_selector_target(selector, scene_name)
            selector.set_region(*initial_region)
            selector.region_selected.connect(on_region_selected)
            self._start_parameter_tool(selector)
        except Exception as exc:
            selector = getattr(self, selector_attr_name, None)
            if selector is not None and isValid(selector):
                selector.close()
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "错误", f"{error_prefix}: {exc}")

    def _store_prefixed_region_values(self, prefix: str, x: int, y: int, width: int, height: int):
        self.current_parameters[f'{prefix}_x'] = x
        self.current_parameters[f'{prefix}_y'] = y
        self.current_parameters[f'{prefix}_width'] = width
        self.current_parameters[f'{prefix}_height'] = height

    def _store_named_region_values(self, keys, x: int, y: int, width: int, height: int):
        values = (x, y, width, height)
        for key, value in zip(keys, values):
            self.current_parameters[key] = value
        if tuple(keys) == ('minimap_x', 'minimap_y', 'minimap_width', 'minimap_height'):
            try:
                if hasattr(self, '_refresh_arrow_preview'):
                    self._refresh_arrow_preview('arrow_color')
            except Exception:
                pass

    def _build_region_button_text(self, x: int, y: int, width: int, height: int):
        if width == 0 and height == 0:
            target_window = self._get_first_window_for_selection()
            if target_window:
                return f"框选区域 (目标: {target_window})"
            return "点击框选识别区域"
        return f"区域: X={x}, Y={y}, {width}x{height}"

    def _apply_region_button_text(self, param_name: str, button_text: str, log_prefix: str):
        if param_name not in self.widgets:
            return
        button_widget = self.widgets[param_name]
        if hasattr(button_widget, 'setText'):
            button_widget.setText(button_text)
            logger.info(f"{log_prefix}: {button_text}")
