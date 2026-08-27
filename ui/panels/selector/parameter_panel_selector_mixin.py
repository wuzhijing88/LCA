from ..parameter_panel_support import *
from utils.window.window_activation_utils import show_and_activate_overlay
from utils.input.uiautomation_runtime import import_uiautomation, uiautomation_thread_context
from .parameter_panel_picker_overlay import ParameterPanelPickerOverlay
from ..parameter_panel_support import logger
from PySide6.QtCore import QThread, Signal
from utils.window.window_binding_utils import (
    get_active_bound_window_hwnd,
    get_active_bound_windows,
    get_active_target_window_title,
)

class _PackageListFetchThread(QThread):
    finished = Signal(object)

    def __init__(self, fetch_callback, parent=None):
        super().__init__(parent)
        self._fetch_callback = fetch_callback

    def run(self):
        packages = self._fetch_callback()
        self.finished.emit(packages)

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
        """Close picker overlay."""
        try:
            if hasattr(self, '_picker_overlay') and self._picker_overlay:
                self._picker_overlay.close()
                self._picker_overlay = None
        except Exception:
            pass

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

    def _pick_loop(self) -> None:
        import ctypes
        import time

        try:
            auto = import_uiautomation()
        except Exception as e:
            logger.error(f"[元素拾取] UIAutomation 初始化失败: {e}")
            self._cancel_current_element_pick()
            return

        last_rect = None
        last_element_hash = None
        keyboard_available, is_pressed = self._resolve_keyboard_listener()

        try:
            with uiautomation_thread_context(auto):
                while self._picking_active:
                    try:
                        if self._handle_pick_shortcuts(keyboard_available, is_pressed):
                            break

                        time.sleep(0.01)
                        element = self._get_element_at_cursor(auto, ctypes)
                        new_rect = self._extract_element_rect(element)
                        if new_rect is None:
                            time.sleep(0.05)
                            continue

                        element_hash = self._hash_element_identity(element)
                        if new_rect != last_rect or element_hash != last_element_hash:
                            last_rect = new_rect
                            last_element_hash = element_hash
                            self._current_element = element
                            logger.debug(f"[元素拾取] 检测到元素: {new_rect}, hash={element_hash}")
                            self._update_overlay_highlight(new_rect)

                        time.sleep(0.05)
                    except Exception as e:
                        logger.debug(f"元素拾取循环异常: {e}")
                        time.sleep(0.05)
        except Exception as e:
            logger.error(f"[元素拾取] UIAutomation 线程初始化失败: {e}")
            self._cancel_current_element_pick()

    def _resolve_keyboard_listener(self):
        try:
            from keyboard import is_pressed
            return True, is_pressed
        except ImportError:
            logger.warning("[元素拾取] keyboard库不可用，无法监听全局按键")
            return False, None

    def _handle_pick_shortcuts(self, keyboard_available: bool, is_pressed) -> bool:
        if keyboard_available and is_pressed is not None and is_pressed('esc'):
            logger.debug("[元素拾取] 检测到ESC键，取消拾取")
            self._cancel_current_element_pick()
            return True

        if self._is_global_right_button_pressed() and self._current_element:
            logger.debug("[元素拾取] 检测到右键，确认拾取")
            self._confirm_current_element_pick()
            return True

        return False

    def _is_global_right_button_pressed(self) -> bool:
        import ctypes
        return ctypes.windll.user32.GetAsyncKeyState(0x02) & 0x8000 != 0

    def _cancel_current_element_pick(self) -> None:
        if not getattr(self, '_picking_active', False):
            return
        self._picking_active = False
        self._picked_info = None
        self._queue_picker_overlay_close()
        self._queue_picker_callback('_on_picking_cancelled')

    def _confirm_current_element_pick(self) -> None:
        if not getattr(self, '_picking_active', False) or not self._current_element:
            return
        self._picking_active = False
        self._picked_info = self._build_picked_info_from_element(self._current_element)
        self._queue_picker_overlay_close()
        self._queue_picker_callback('_on_element_picked')

    def _build_picked_info_from_element(self, element):
        try:
            from utils.window.element_picker import ElementInfo

            rect = getattr(element, 'BoundingRectangle', None)
            return ElementInfo(
                name=self._safe_element_attr(element, 'Name'),
                automation_id=self._safe_element_attr(element, 'AutomationId'),
                class_name=self._safe_element_attr(element, 'ClassName'),
                control_type=self._safe_element_attr(element, 'ControlTypeName'),
                bounding_rect=(rect.left, rect.top, rect.width(), rect.height()) if rect else (0, 0, 0, 0),
            )
        except Exception as e:
            logger.error(f"[元素拾取] 获取属性失败: {e}")
            return None

    def _safe_element_attr(self, element, attr_name: str) -> str:
        try:
            return getattr(element, attr_name) or ""
        except Exception:
            return ""

    def _queue_picker_overlay_close(self) -> None:
        if hasattr(self, '_picker_overlay') and self._picker_overlay:
            self._picker_overlay.highlight_rect = None
            from PySide6.QtCore import QMetaObject, Qt as QtConst
            QMetaObject.invokeMethod(self._picker_overlay, 'close', QtConst.QueuedConnection)

    def _queue_picker_callback(self, method_name: str) -> None:
        from PySide6.QtCore import QMetaObject, Qt as QtConst
        QMetaObject.invokeMethod(self, method_name, QtConst.QueuedConnection)

    def _get_element_at_cursor(self, auto_module, ctypes_module):
        pt = ctypes_module.wintypes.POINT()
        ctypes_module.windll.user32.GetCursorPos(ctypes_module.byref(pt))
        return auto_module.ControlFromPoint(pt.x, pt.y)

    def _extract_element_rect(self, element):
        if not element:
            return None
        rect = getattr(element, 'BoundingRectangle', None)
        if not rect or rect.width() <= 0 or rect.height() <= 0:
            return None
        return (rect.left, rect.top, rect.width(), rect.height())

    def _hash_element_identity(self, element):
        try:
            return hash((element.ControlTypeName, element.AutomationId, element.Name))
        except Exception:
            return None

    def _update_overlay_highlight(self, new_rect) -> None:
        if hasattr(self, '_picker_overlay') and self._picker_overlay:
            self._picker_overlay.highlight_rect = new_rect
            logger.debug("[元素拾取] 设置highlight_rect并调用repaint")
            from PySide6.QtCore import QMetaObject, Qt as QtConst
            QMetaObject.invokeMethod(self._picker_overlay, 'repaint', QtConst.QueuedConnection)

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
            self._set_element_picker_button_state(True)
            self._minimize_picker_host_window()
            self._show_picker_overlay()
            self._initialize_picker_runtime_state()
            self._start_element_pick_thread()
        except Exception as e:
            logger.error(f"启动元素拾取失败: {e}")
            self._set_element_picker_button_state(False)

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
        self._picker_overlay = ParameterPanelPickerOverlay(self)
        logger.debug(
            f"[元素拾取] 创建PickerOverlay: geometry={self._picker_overlay.geometry()}, "
            f"DPI={self._picker_overlay.device_pixel_ratio}"
        )
        show_and_activate_overlay(self._picker_overlay, log_prefix='元素拾取覆盖层', focus=True)

    def _initialize_picker_runtime_state(self) -> None:
        self._picking_active = True
        self._current_element = None
        self._picked_info = None

    def _start_element_pick_thread(self) -> None:
        import threading

        self._pick_thread = threading.Thread(target=self._pick_loop, daemon=True)
        self._pick_thread.start()

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

        QTimer.singleShot(50, translate_color_dialog_buttons)

        if dialog.exec() == QDialog.Accepted:

            color = dialog.selectedColor()

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
                    self._store_color_picker_base_point(color_picker, updates)
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
        self._store_color_picker_base_point(color_picker, updates)
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

    def _select_package(self, line_edit: QLineEdit):
        logger.info("开始获取已安装应用包名列表...")
        try:
            packages = self._fetch_installed_packages_list()
            if not packages:
                self._show_package_list_unavailable_warning()
                return

            dialog, list_widget = self._create_package_select_dialog(packages, line_edit)
            if dialog.exec() != QDialog.Accepted:
                return

            current_item = list_widget.currentItem()
            if not current_item:
                logger.warning("未选择任何包名")
                return

            package_name = current_item.text()
            self._apply_selected_package_to_line_edit(line_edit, package_name)
            logger.info(f"用户选择了包名: {package_name}")
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox

            logger.error(f"获取应用包名列表失败: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "错误",
                f"获取应用列表时发生错误：\n\n{str(e)}\n\n请查看日志获取详细信息。",
            )

    def _create_package_search_edit(self, layout):
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("搜索包名...")
        layout.addWidget(search_edit)
        return search_edit

    def _create_package_list_widget(self, packages, layout):
        list_widget = QListWidget()
        list_widget.addItems(packages)
        layout.addWidget(list_widget)
        return list_widget

    def _apply_package_search_filter(self, list_widget, text):
        needle = text.lower()
        for index in range(list_widget.count()):
            item = list_widget.item(index)
            item.setHidden(needle not in item.text().lower())

    def _apply_selected_package_to_line_edit(self, line_edit, package_name):
        line_edit.setText(package_name)
        param_name = self._update_current_parameter_from_widget(line_edit, package_name)
        if param_name and self.current_card_id is not None:
            self.parameters_changed.emit(self.current_card_id, {param_name: package_name})

    def _create_package_select_dialog(self, packages, line_edit):
        from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

        dialog = QDialog(self)
        dialog.setWindowTitle(f"选择应用包名 (共{len(packages)}个)")
        dialog.setMinimumSize(500, 400)

        layout = QVBoxLayout(dialog)
        info_label = QLabel(f"找到 {len(packages)} 个已安装的第三方应用：")
        layout.addWidget(info_label)

        search_edit = self._create_package_search_edit(layout)
        list_widget = self._create_package_list_widget(packages, layout)
        search_edit.textChanged.connect(
            lambda text, widget=list_widget: self._apply_package_search_filter(widget, text)
        )

        button_layout = QHBoxLayout()
        ok_button = QPushButton("确定")
        cancel_button = QPushButton("取消")
        ok_button.clicked.connect(dialog.accept)
        cancel_button.clicked.connect(dialog.reject)
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

        def on_item_double_clicked(item):
            self._apply_selected_package_to_line_edit(line_edit, item.text())
            dialog.accept()

        list_widget.itemDoubleClicked.connect(on_item_double_clicked)
        return dialog, list_widget

    def _refresh_package_list(self, combo_box: QComboBox):
        logger.info("开始刷新已安装应用包名列表...")
        refresh_button = self._find_package_refresh_button(combo_box)
        self._set_package_refresh_button_state(refresh_button, False, "刷新中")
        current_text = combo_box.currentText().strip()
        thread = self._create_package_fetch_thread()

        def on_packages_fetched(packages):
            try:
                self._set_package_refresh_button_state(refresh_button, True, "刷新")
                self._apply_package_fetch_result(combo_box, current_text, packages)
            except Exception as e:
                logger.error(f"处理应用包名列表失败: {e}", exc_info=True)
                self._show_package_refresh_error(e)
            finally:
                self._forget_package_fetch_thread(thread)
                try:
                    if thread:
                        QTimer.singleShot(0, thread.deleteLater)
                except Exception:
                    pass

        thread.finished.connect(on_packages_fetched)
        thread.start()
        self._remember_package_fetch_thread(thread)

    def _fetch_installed_packages_list(self):
        try:
            from tasks import app_manager_task

            return app_manager_task.get_installed_packages_list()
        except Exception as e:
            logger.error(f"获取应用包名列表失败: {e}", exc_info=True)
            return None

    def _create_package_fetch_thread(self):
        return _PackageListFetchThread(self._fetch_installed_packages_list)

    def _show_package_list_unavailable_warning(self):
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(
            self,
            "无法获取应用列表",
            "未能获取已安装应用列表?\n\n"
            "可能的原因：\n"
            "1. ADB未正确连接\n"
            "2. 没有可用的模拟器设备\n"
            "3. 设备上没有安装第三方应用\n\n"
            "请检查ADB连接状态和设备。",
        )

    def _restore_package_combo_selection(self, combo_box: QComboBox, current_text: str, packages):
        combo_box.clear()
        combo_box.addItems(packages)
        if current_text and current_text in packages:
            index = combo_box.findText(current_text)
            if index >= 0:
                combo_box.setCurrentIndex(index)
            return
        if current_text:
            combo_box.addItem(current_text)
            combo_box.setCurrentText(current_text)

    def _apply_package_fetch_result(self, combo_box: QComboBox, current_text: str, packages):
        from shiboken6 import isValid

        if not isValid(combo_box) or not isValid(self):
            logger.warning("刷新完成时控件已被销毁，跳过更新")
            return
        if packages is None or not packages:
            self._show_package_list_unavailable_warning()
            return

        self._restore_package_combo_selection(combo_box, current_text, packages)
        logger.info(f"成功刷新包名列表，共 {len(packages)} 个应用")

    def _show_package_refresh_error(self, error):
        try:
            from shiboken6 import isValid

            if isValid(self):
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.critical(
                    self,
                    "错误",
                    f"刷新应用列表时发生错误：\n\n{str(error)}\n\n请查看日志获取详细信息。",
                )
        except Exception:
            pass

    def _find_package_refresh_button(self, combo_box: QComboBox):
        parent = combo_box.parent()
        if parent is None:
            return None
        for child in parent.children():
            if isinstance(child, QPushButton) and "刷新" in child.text():
                return child
        return None

    def _set_package_refresh_button_state(self, refresh_button, enabled: bool, text: str):
        try:
            from shiboken6 import isValid

            if refresh_button and isValid(refresh_button):
                refresh_button.setEnabled(enabled)
                refresh_button.setText(text)
        except Exception:
            pass

    def _remember_package_fetch_thread(self, thread):
        if not hasattr(self, "_fetch_threads"):
            self._fetch_threads = []
        self._fetch_threads.append(thread)

    def _forget_package_fetch_thread(self, thread):
        try:
            if thread and hasattr(self, "_fetch_threads") and thread in self._fetch_threads:
                self._fetch_threads.remove(thread)
        except Exception:
            pass

    def _select_ocr_region(self, param_name: str):
        """启动OCR区域选择工具"""
        logger.info(f"OCR区域选择按钮被点击，参数名: {param_name}")

        try:
            from ui.selectors.ocr_region_selector import OCRRegionSelectorWidget

            # 获取绑定的窗口句柄
            target_window_hwnd = self._get_bound_window_hwnd()

            if not target_window_hwnd:
                from PySide6.QtWidgets import QMessageBox
                logger.warning("未找到绑定的窗口")
                QMessageBox.warning(self, "警告", "未找到绑定的窗口，请先绑定目标窗口")
                return

            # 创建区域选择器，直接传递窗口句柄
            self.region_selector = OCRRegionSelectorWidget(self)

            # 设置目标窗口句柄
            if hasattr(self.region_selector, 'set_target_window_hwnd'):
                self.region_selector.set_target_window_hwnd(target_window_hwnd)
            elif hasattr(self.region_selector, 'set_target_window'):
                # 兼容旧版本，获取窗口标题
                try:
                    import win32gui
                    window_title = win32gui.GetWindowText(target_window_hwnd)
                    self.region_selector.set_target_window(window_title)
                except Exception as e:
                    logger.warning(f"获取窗口标题失败: {e}")
                    # 直接使用句柄作为标题
                    self.region_selector.set_target_window(f"窗口{target_window_hwnd}")

            # 连接信号
            self.region_selector.region_selected.connect(
                lambda x, y, w, h: self._on_ocr_region_selected(param_name, x, y, w, h)
            )

            # 开始选择
            self.region_selector.start_selection()

        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            logger.error(f"启动区域选择工具失败: {str(e)}")
            import traceback
            logger.error(f"详细错误信息:\n{traceback.format_exc()}")
            QMessageBox.warning(self, "错误", f"启动区域选择工具失败: {str(e)}")

    def _get_enabled_bound_windows_for_selector(self) -> List[Dict[str, Any]]:
        candidates = []

        try:
            if self.main_window is not None:
                if hasattr(self.main_window, "bound_windows") and isinstance(self.main_window.bound_windows, list):
                    candidates = self.main_window.bound_windows
                elif hasattr(self.main_window, "config"):
                    config = self.main_window.config
                    if isinstance(config, dict):
                        candidates = get_active_bound_windows(config)
                    else:
                        active_windows = getattr(config, "active_bound_windows", None)
                        if isinstance(active_windows, list):
                            candidates = active_windows
                        elif hasattr(config, "bound_windows"):
                            candidates = config.bound_windows or []

            if not candidates and self.parent_window is not None:
                if hasattr(self.parent_window, "bound_windows") and isinstance(self.parent_window.bound_windows, list):
                    candidates = self.parent_window.bound_windows
                elif hasattr(self.parent_window, "config"):
                    config = self.parent_window.config
                    if isinstance(config, dict):
                        candidates = get_active_bound_windows(config)
                    else:
                        active_windows = getattr(config, "active_bound_windows", None)
                        if isinstance(active_windows, list):
                            candidates = active_windows
                        elif hasattr(config, "bound_windows"):
                            candidates = config.bound_windows or []
        except Exception as e:
            logger.debug(f"绑定窗口选择器来源失败：{e}")
            return []

        enabled_windows = []
        for window_info in candidates or []:
            if not isinstance(window_info, dict):
                continue
            if not window_info.get("enabled", True):
                continue
            enabled_windows.append(window_info)
        return enabled_windows

    def _get_bound_window_hwnd(self) -> Optional[int]:
        """获取当前绑定的窗口句柄（带全局验证）"""
        try:
            # 1. 优先使用传入的target_window_hwnd(来自标签页绑定或全局配置)
            if hasattr(self, 'target_window_hwnd') and self.target_window_hwnd:
                logger.info(f"检测到标签页绑定的窗口句柄: {self.target_window_hwnd}")

                # 【关键修改】验证句柄是否仍在全局绑定列表中
                if self.main_window and hasattr(self.main_window, 'is_hwnd_bound'):
                    if self.main_window.is_hwnd_bound(self.target_window_hwnd):
                        logger.info(f"句柄 {self.target_window_hwnd} 已验证，在全局绑定列表中")
                        return self.target_window_hwnd
                    else:
                        logger.warning(f"句柄 {self.target_window_hwnd} 不在全局绑定列表中，静默切换到第一个有效句柄")
                        # 静默获取第一个有效句柄
                        validated_hwnd, is_original = self.main_window.validate_hwnd_or_get_first(self.target_window_hwnd)
                        if validated_hwnd:
                            logger.info(f"已静默切换到有效句柄: {validated_hwnd}（不修改标签页绑定）")
                            return validated_hwnd
                        else:
                            logger.warning("没有可用的全局绑定窗口，继续尝试其他方式获取")
                            # 继续往下执行，尝试从全局配置获取
                else:
                    # 如果无法验证（没有主窗口），直接返回
                    logger.warning("无法验证句柄有效性（未找到主窗口），使用标签页绑定的句柄")
                    return self.target_window_hwnd

            # 2. 回退到从parent_window的config获取
            if self.parent_window:
                # 检查 parent_window 是否有 config 属性
                if hasattr(self.parent_window, 'config'):
                    config = self.parent_window.config

                    # config 可能是字典
                    if isinstance(config, dict):
                        hwnd = get_active_bound_window_hwnd(config)
                        if hwnd:
                            logger.info(f"从活动配置获取窗口句柄: {hwnd}")
                            return hwnd

                        target_window_title = get_active_target_window_title(config)
                        if target_window_title:
                            # 需要通过标题查找窗口句柄
                            try:
                                import win32gui
                                def find_window_by_title(title):
                                    windows = []
                                    def enum_windows_callback(hwnd, _):
                                        if win32gui.IsWindowVisible(hwnd):
                                            window_title = win32gui.GetWindowText(hwnd)
                                            if window_title == title:
                                                windows.append(hwnd)
                                    win32gui.EnumWindows(enum_windows_callback, None)
                                    if len(windows) == 1:
                                        return windows[0]
                                    if len(windows) > 1:
                                        logger.warning(f"通过标题找到多个同名窗口，拒绝自动选择: {title} -> {windows}")
                                    return None

                                hwnd = find_window_by_title(target_window_title)
                                if hwnd:
                                    logger.info(f"通过标题查找到窗口句柄: {hwnd}")
                                    return hwnd
                            except Exception as e:
                                logger.warning(f"通过标题查找窗口句柄失败: {e}")

                    # config 可能是对象
                    else:
                        active_windows = getattr(config, 'active_bound_windows', None)
                        if not isinstance(active_windows, list):
                            active_windows = getattr(config, 'bound_windows', None)

                        if active_windows:
                            enabled_windows = [w for w in active_windows if w.get('enabled', True)]
                            if enabled_windows:
                                hwnd = enabled_windows[0].get('hwnd')
                                if hwnd:
                                    logger.info(f"从活动配置对象获取窗口句柄: {hwnd}")
                                    return hwnd

                        target_window_title = getattr(config, 'active_target_window_title', None) or getattr(config, 'target_window_title', None)
                        if target_window_title:
                            # 通过标题查找
                            try:
                                import win32gui
                                def find_window_by_title(title):
                                    windows = []
                                    def enum_windows_callback(hwnd, _):
                                        if win32gui.IsWindowVisible(hwnd):
                                            window_title = win32gui.GetWindowText(hwnd)
                                            if window_title == title:
                                                windows.append(hwnd)
                                    win32gui.EnumWindows(enum_windows_callback, None)
                                    if len(windows) == 1:
                                        return windows[0]
                                    if len(windows) > 1:
                                        logger.warning(f"通过标题找到多个同名窗口，拒绝自动选择: {title} -> {windows}")
                                    return None

                                hwnd = find_window_by_title(target_window_title)
                                if hwnd:
                                    logger.info(f"通过标题查找到窗口句柄: {hwnd}")
                                    return hwnd
                            except Exception as e:
                                logger.warning(f"通过标题查找窗口句柄失败: {e}")

            logger.warning("未找到任何窗口句柄")
            return None

        except Exception as e:
            logger.error(f"获取绑定窗口句柄时出错: {e}")
            import traceback
            logger.error(f"错误详情:\n{traceback.format_exc()}")
            return None

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

        try:
            from ui.selectors.coordinate_selector import MultiPointCoordinateSelectorWidget

            # 创建多点坐标选择器
            self.multi_coordinate_selector = MultiPointCoordinateSelectorWidget(self)

            # 获取目标窗口句柄
            target_window_hwnd = self._get_target_window_hwnd()
            if target_window_hwnd:
                self.multi_coordinate_selector.target_window_hwnd = target_window_hwnd
                logger.info(f"设置多点坐标选择器窗口句柄: {target_window_hwnd}")
            else:
                logger.error("未找到目标窗口句柄")
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "错误", "未找到目标窗口，请先绑定窗口")
                return

            # 连接信号
            self.multi_coordinate_selector.coordinates_selected.connect(
                lambda coords, timestamps: self._on_multi_coordinates_selected(param_name, coords, timestamps)
            )

            # 开始选择
            logger.info("开始启动多点坐标选择器...")
            self.multi_coordinate_selector.start_selection()

        except Exception as e:
            logger.error(f"启动多点坐标选择工具失败: {e}")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "错误", f"启动多点坐标选择工具失败: {str(e)}")

    def _on_multi_coordinates_selected(self, param_name: str, coordinates: list, timestamps: list):
        """处理多点坐标选择完成"""
        try:
            logger.info(f"多点坐标选择完成: {param_name}, {len(coordinates)} 个点")

            # 将坐标列表和时间戳转换为文本格式
            # 格式: x,y,timestamp
            if timestamps and len(timestamps) == len(coordinates):
                coord_text = "\n".join([f"{x},{y},{t:.3f}" for (x, y), t in zip(coordinates, timestamps)])
                logger.info(f"已保存带时间戳的路径点: {len(coordinates)}个点, 总时长={timestamps[-1]:.3f}s")
            else:
                # 如果没有时间戳，使用原格式
                coord_text = "\n".join([f"{x},{y}" for x, y in coordinates])
                logger.warning("未获取时间戳，使用默认格式保存坐标")

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
            logger.error(f"处理多点坐标选择结果失败: {e}")

    def _ensure_offset_selector(self):
        from ui.selectors.coordinate_selector import OffsetSelectorWidget

        if self.offset_selector is None:
            self.offset_selector = OffsetSelectorWidget(self)
            self.offset_selector.offset_selected.connect(self._handle_offset_selected)
        return self.offset_selector

    def _select_offset(self, param_name: str):
        logger.info(f"偏移选择按钮被点击，参数名: {param_name}")
        try:
            offset_selector = self._ensure_offset_selector()
            self._offset_param_name = param_name

            target_window_hwnd = self._get_target_window_hwnd()
            if not target_window_hwnd:
                logger.error("未找到目标窗口句柄")
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(
                    self,
                    "错误",
                    "未找到目标窗口，请先绑定窗口",
                )
                return

            offset_selector.target_window_hwnd = target_window_hwnd
            logger.info(
                f"设置偏移选择器窗口句柄: {target_window_hwnd}"
            )
            offset_selector.base_point = None
            offset_selector.base_rect = None

            base_x, base_y, base_rect = self._resolve_offset_base_for_selection(param_name)
            if base_x is not None and base_y is not None:
                offset_selector.set_base_point(int(base_x), int(base_y))
            if base_rect is not None:
                try:
                    offset_selector.set_base_rect(*base_rect)
                except Exception:
                    pass

            offset_selector.start_selection()
        except Exception as exc:
            logger.error(f"启动偏移选择工具失败: {exc}")
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                "错误",
                f"启动偏移选择工具失败: {str(exc)}",
            )

    def _resolve_offset_base_for_selection(self, param_name: str):
        base_x = None
        base_y = None
        base_rect = None

        param_def = self.param_definitions.get(param_name, {})
        related_params = param_def.get("related_params", [])
        if "coordinate_fixed_offset_x" in related_params or "fixed_offset_x" in related_params:
            base_x = self.current_parameters.get("coordinate_x")
            base_y = self.current_parameters.get("coordinate_y")
        elif "image_fixed_offset_x" in related_params:
            base = self._get_image_center_for_offset()
            if base:
                if len(base) >= 3:
                    base_x, base_y, base_rect = base[0], base[1], base[2]
                else:
                    base_x, base_y = base[0], base[1]
        elif "color_fixed_offset_x" in related_params:
            base = self._get_color_center_for_offset()
            if base:
                base_x, base_y = base
        return base_x, base_y, base_rect

    def _get_image_center_for_offset(self):
        image_path = (self.current_parameters.get("image_path") or "").strip()
        image_paths = (self.current_parameters.get("image_paths") or "").strip()
        if not image_path and not image_paths:
            logger.warning("偏移选择: 未配置图片路径，无法获取图片中心点")
            return None

        target_window_hwnd = self._get_target_window_hwnd()
        if not target_window_hwnd:
            logger.warning("偏移选择: 未绑定窗口，无法获取图片中心点")
            return None

        try:
            from tasks.image_match_click import locate_image_in_window
        except Exception as exc:
            logger.warning(f"偏移选择: 加载图像识别工具失败: {exc}")
            return None

        params = dict(self.current_parameters or {})
        if not image_path and image_paths:
            for raw_line in re.split(r"[\r\n;]+", image_paths):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "  # " in line:
                    line = line.split("  # ", 1)[0].strip()
                if line:
                    params["image_path"] = line
                    break

        found, location, _ = locate_image_in_window(
            params=params,
            target_hwnd=target_window_hwnd,
            card_id=self.current_card_id,
        )
        if not found or not location:
            logger.warning("偏移选择: 未找到图片中心点")
            return None

        x, y, w, h = location[:4]
        center_x = int(x + w / 2)
        center_y = int(y + h / 2)
        rect = (int(x), int(y), int(w), int(h))
        return center_x, center_y, rect

    def _build_color_match_payload_for_offset(self, target_color_str: str):
        text = str(target_color_str or "").strip()
        if not text:
            return None

        color_mode = "single"
        colors_data: List[Dict[str, Any]] = []
        try:
            if "|" in text:
                color_mode = "multipoint"
                parts = [part.strip() for part in text.split("|") if part.strip()]
                if not parts:
                    return None
                for idx, part in enumerate(parts):
                    values = [int(value.strip()) for value in part.split(",")]
                    if idx == 0:
                        if len(values) != 3:
                            return None
                        r, g, b = values
                        colors_data.append({"offset": (0, 0), "rgb": (r, g, b), "bgr": (b, g, r)})
                    else:
                        if len(values) != 5:
                            return None
                        ox, oy, r, g, b = values
                        colors_data.append({"offset": (ox, oy), "rgb": (r, g, b), "bgr": (b, g, r)})
            elif ";" in text:
                color_mode = "multi"
                parts = [part.strip() for part in text.split(";") if part.strip()]
                if not parts:
                    return None
                for part in parts:
                    values = [int(value.strip()) for value in part.split(",")]
                    if len(values) != 3:
                        return None
                    r, g, b = values
                    colors_data.append({"rgb": (r, g, b), "bgr": (b, g, r)})
            else:
                values = [int(value.strip()) for value in text.split(",")]
                if len(values) != 3:
                    return None
                r, g, b = values
                colors_data.append({"rgb": (r, g, b), "bgr": (b, g, r)})
        except Exception:
            return None

        if not colors_data:
            return None
        return color_mode, colors_data

    def _find_color_center_for_offset(self):
        target_color_str = str(self.current_parameters.get("target_color", "") or "").strip()
        if not target_color_str:
            return None

        target_window_hwnd = self._get_target_window_hwnd()
        if not target_window_hwnd:
            return None

        payload = self._build_color_match_payload_for_offset(target_color_str)
        if not payload:
            return None

        color_mode, colors_data = payload
        roi = None
        if bool(self.current_parameters.get("search_region_enabled", False)):
            try:
                rx = int(self.current_parameters.get("search_region_x", 0) or 0)
                ry = int(self.current_parameters.get("search_region_y", 0) or 0)
                rw = int(self.current_parameters.get("search_region_width", 0) or 0)
                rh = int(self.current_parameters.get("search_region_height", 0) or 0)
                if rw > 0 and rh > 0:
                    roi = (rx, ry, rw, rh)
            except Exception:
                roi = None

        try:
            from services.screenshot_pool import capture_and_find_color

            find_response = capture_and_find_color(
                hwnd=int(target_window_hwnd),
                color_mode=color_mode,
                colors_data=colors_data,
                h_tolerance=10,
                s_tolerance=40,
                v_tolerance=40,
                min_pixel_count=1,
                client_area_only=True,
                use_cache=False,
                timeout=4.0,
                roi=roi,
            )
        except Exception as exc:
            logger.warning(f"偏移选择: 实时查找颜色中心失败: {exc}")
            return None

        if not bool(find_response.get("success")) or not bool(find_response.get("found")):
            return None

        center = find_response.get("center")
        if isinstance(center, (list, tuple)) and len(center) >= 2:
            try:
                return int(center[0]), int(center[1])
            except Exception:
                return None
        return None

    def _get_color_center_for_offset(self):
        live_center = self._find_color_center_for_offset()
        if live_center is not None:
            try:
                live_x, live_y = int(live_center[0]), int(live_center[1])
                self.current_parameters["color_picker_base_x"] = live_x
                self.current_parameters["color_picker_base_y"] = live_y
                return live_x, live_y
            except Exception:
                pass

        manual_x = self.current_parameters.get("color_picker_base_x")
        manual_y = self.current_parameters.get("color_picker_base_y")
        if manual_x is not None and manual_y is not None:
            try:
                return int(manual_x), int(manual_y)
            except Exception:
                pass

        card_id = self.current_card_id
        if card_id is None:
            logger.warning("偏移选择: 未找到当前卡片ID，无法读取找色中心点")
            return None

        try:
            from task_workflow.workflow_context import get_workflow_context

            context = get_workflow_context()
            x = context.get_card_data(card_id, "color_target_x")
            y = context.get_card_data(card_id, "color_target_y")
        except Exception as exc:
            logger.warning(f"偏移选择: 读取找色中心点失败: {exc}")
            return None

        if x is None or y is None:
            logger.warning("偏移选择: 未找到找色中心点，请先执行找色")
            return None
        return int(x), int(y)

    def _handle_offset_selected(self, dx: int, dy: int):
        param_name = self._offset_param_name
        if not param_name:
            logger.warning("偏移选择回调缺少参数名")
            return
        self._on_offset_selected(param_name, dx, dy)

    def _build_offset_updates(self, param_name: str, dx: int, dy: int):
        param_def = self.param_definitions.get(param_name, {})
        related_params = param_def.get(
            "related_params",
            ["fixed_offset_x", "fixed_offset_y", "position_mode"],
        )
        offset_x_param = related_params[0] if len(related_params) > 0 else "fixed_offset_x"
        offset_y_param = related_params[1] if len(related_params) > 1 else "fixed_offset_y"
        mode_param = related_params[2] if len(related_params) > 2 else None

        updates = {offset_x_param: dx, offset_y_param: dy}
        if mode_param:
            updates[mode_param] = "固定偏移"
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

        try:
            from ui.selectors.coordinate_selector import CoordinateSelectorWidget

            # 创建坐标选择器
            self.coordinate_selector = CoordinateSelectorWidget(self)

            # 获取目标窗口句柄
            target_window_hwnd = self._get_target_window_hwnd()
            if target_window_hwnd:
                self.coordinate_selector.target_window_hwnd = target_window_hwnd
                logger.info(f"设置坐标选择器窗口句柄: {target_window_hwnd}")
            else:
                logger.error("未找到目标窗口句柄")
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "错误", "未找到目标窗口，请先绑定窗口")
                return

            # 连接信号
            self.coordinate_selector.coordinate_selected.connect(
                lambda x, y: self._on_coordinate_selected_with_display(param_name, x, y)
            )

            # 开始选择
            self.coordinate_selector.start_selection()

        except Exception as e:
            logger.error(f"启动坐标选择工具失败: {e}")
            from PySide6.QtWidgets import QMessageBox
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
        try:
            from PySide6.QtWidgets import QMessageBox
            from ui.selectors.coordinate_selector import CoordinateSelectorWidget

            self.coordinate_selector = CoordinateSelectorWidget(self)
            target_window_hwnd = self._get_target_window_hwnd()
            if not target_window_hwnd:
                logger.error("未找到目标窗口句柄")
                QMessageBox.warning(self, "错误", "未找到目标窗口，请先绑定窗口")
                return

            self.coordinate_selector.target_window_hwnd = target_window_hwnd
            logger.info(f"设置坐标选择器窗口句柄: {target_window_hwnd}")
            self.coordinate_selector.coordinate_selected.connect(
                lambda x, y, selected_param=param_name: self._on_coordinate_selected(selected_param, x, y)
            )
            self.coordinate_selector.start_selection()
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox

            logger.error(f"启动坐标选择工具失败: {e}")
            QMessageBox.warning(self, "错误", f"启动坐标选择工具失败: {str(e)}")

    _TEXT_COORDINATE_SELECTORS = {
        "scroll_coordinate_selector": ("scroll_start_position", "更新滚动起始位置"),
        "drag_start_coordinate_selector": ("drag_start_position", "更新拖拽起点"),
        "drag_end_coordinate_selector": ("drag_end_position", "更新拖拽终点"),
        "move_start_coordinate_selector": ("move_start_position", "更新鼠标移动起点"),
        "move_end_coordinate_selector": ("move_end_position", "更新鼠标移动终点"),
        "drag_coordinate_selector": ("drag_start_position", "更新拖拽起点(旧版)"),
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

        self._set_named_widget_value("combo_mouse_x", x)
        self._set_named_widget_value("combo_mouse_y", y)
        if "combo_mouse_x" in self.current_parameters or "combo_mouse_y" in self.current_parameters:
            self.current_parameters["combo_mouse_x"] = x
            self.current_parameters["combo_mouse_y"] = y
            changed_params["combo_mouse_x"] = x
            changed_params["combo_mouse_y"] = y

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

    def _start_yolo_realtime_preview(self):
        try:
            target_hwnd = self._get_bound_window_hwnd()
            if not target_hwnd:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(self, "提示", "请先绑定目标窗口")
                return

            model_path = self.current_parameters.get('model_path', '')
            if not model_path:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(self, "提示", "请先选择YOLO模型文件")
                return

            conf_threshold = self.current_parameters.get('confidence_threshold', 0.5)
            target_classes_str = self.current_parameters.get('target_classes', '')
            target_classes = None
            if target_classes_str and target_classes_str != "全部类别":
                target_classes = [target_classes_str.strip()]

            from tasks.yolo_detection import start_realtime_preview

            start_realtime_preview(
                hwnd=target_hwnd,
                model_path=model_path,
                conf_threshold=conf_threshold,
                target_classes=target_classes,
            )
            logger.info(f"YOLO 实时预览已启动: hwnd={target_hwnd}, model={model_path}")
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox

            logger.error(f"启动 YOLO 实时预览失败: {exc}")
            QMessageBox.warning(self, "错误", f"启动实时预览失败: {str(exc)}")

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

        selector = OCRRegionSelectorWidget(self)
        setattr(self, attr_name, selector)
        return selector

    def _configure_ocr_region_selector_target(self, selector, scene_name: str):
        target_hwnd = self._get_bound_window_hwnd()
        if target_hwnd:
            logger.info(f"Use hwnd for {scene_name}: {target_hwnd}")
            if hasattr(selector, 'set_target_hwnd'):
                selector.set_target_hwnd(target_hwnd)
            else:
                selector.target_window_hwnd = target_hwnd
            return

        logger.warning('未找到窗口句柄，回退到窗口标题')
        target_window_title = self._get_first_window_for_selection()
        if target_window_title and hasattr(selector, 'set_target_window'):
            selector.set_target_window(target_window_title)

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
            selector.start_selection()
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                "错误",
                f"{error_prefix}: {str(exc)}",
            )

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
