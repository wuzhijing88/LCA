"""原生参数工具的调用适配：只负责上下文、结果映射和装卸。"""
import copy
from functools import partial

from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtWidgets import QMessageBox
from shiboken6 import isValid

from app_core.card_plugin_conditions import validate_effective_value
from app_core.card_plugin_tools import tool_result_updates
from app_core.card_plugins import input_parameter_key
from ui.panels.parameter_compare import parameter_values_equal
from ui.panels.parameter_editors import apply_editor_values
from ui.panels.parameter_tool_capture import describe_window


class PluginToolController(QObject):
    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self._request = None
        self._tool = None
        self._connections = []
        self._error_timer = QTimer(self)
        self._error_timer.setSingleShot(True)
        self._error_timer.timeout.connect(self._show_error)
        self._error_message = ""

    def _global_window(self):
        host = self.controller.panel.main_window
        if host is None:
            raise ValueError("参数面板未关联主窗口，无法读取全局绑定窗口")
        windows = getattr(host, "bound_windows", None)
        if not isinstance(windows, list) or any(not isinstance(item, dict) or type(item.get("enabled")) is not bool for item in windows):
            raise ValueError("全局绑定窗口列表或启用状态无效")
        enabled = [item for item in windows if item["enabled"]]
        if len(enabled) != 1:
            raise ValueError("请在全局设置中绑定并仅启用一个目标窗口")
        hwnd = enabled[0].get("hwnd")
        if type(hwnd) is not int or hwnd <= 0:
            raise ValueError("全局绑定窗口句柄无效，请重新绑定")
        return describe_window(hwnd)

    def _require_stopped(self):
        host = self.controller.panel.main_window
        if host is not None and host.task_state_manager.get_current_state() != "stopped":
            raise ValueError("请先停止工作流，再使用参数工具")

    def _connect(self, signal, slot):
        signal.connect(slot)
        self._connections.append((signal, slot))

    def refresh(self, states):
        for name, editor in self.controller.editors.items():
            if editor.tool_button is None:
                continue
            own = self._request is not None and self._request["name"] == name
            editor.tool_button.setText("取消采集" if own else self.controller.definitions[name]["tool"]["类型"])
            editor.tool_button.setEnabled(self._request is None or own)

    @Slot()
    def start(self):
        name = self.sender().property("pluginToolParameter")
        if self._request is not None:
            if self._request["name"] == name:
                self.cancel()
            return
        self._error_timer.stop()
        self._error_message = ""
        try:
            self._require_stopped()
            window = self._global_window()
            declaration = self.controller.definitions[name]["tool"]
            self._request = {"name": name, "values": copy.deepcopy(self.controller.values()), "window": window}
            panel = self.controller.panel
            kind = declaration["类型"]
            if kind in {"取坐标", "取偏移"}:
                from ui.selectors.coordinate_selector import CoordinateSelectorWidget, OffsetSelectorWidget
                factory = CoordinateSelectorWidget if kind == "取坐标" else OffsetSelectorWidget
                tool = panel._own_parameter_tool(factory(panel))
                self._tool = tool
                tool.target_window_hwnd = window.hwnd
                if kind == "取坐标":
                    self._connect(tool.coordinate_selected, self._coordinate_selected)
                else:
                    tool.set_base_point(window.width // 2, window.height // 2)
                    self._connect(tool.offset_selected, self._offset_selected)
                self._connect(tool.selection_finished, self.cancel)
                panel._start_parameter_tool(tool)
            elif kind == "框选区域":
                tool = panel._create_ocr_region_selector("_plugin_region_selector")
                self._tool = tool
                tool.set_target_window_hwnd(window.hwnd)
                values = self.controller.values()
                tool.set_region(*(values[declaration["写入"][role]] for role in ("横坐标", "纵坐标", "宽度", "高度")))
                self._connect(tool.region_selected, self._region_selected)
                self._connect(tool.selection_finished, self.cancel)
                panel._start_parameter_tool(tool)
            elif kind == "取色":
                tool, picker = panel._create_color_coordinate_dialog(target_hwnd=window.hwnd)
                self._tool = tool
                panel._apply_initial_color_string_to_picker(picker, self.controller.values()[name])
                self._connect(tool.accepted, partial(self._color_selected, picker))
                self._connect(tool.rejected, self.cancel)
                panel._show_color_coordinate_dialog(tool)
            elif kind == "截图":
                panel._tool_hiding = True
                try:
                    panel._start_screenshot_for_param(self.controller.inputs[name], on_selected=self._screenshot_selected, on_cancelled=self.cancel, target_hwnd=window.hwnd)
                finally:
                    panel._tool_hiding = False
            self.refresh(self.controller._states)
        except Exception as error:
            self._failed(error)

    @Slot(int, int)
    def _coordinate_selected(self, horizontal, vertical):
        self._finish({"横坐标": horizontal, "纵坐标": vertical})

    @Slot(int, int)
    def _offset_selected(self, horizontal, vertical):
        self._finish({"横偏移": horizontal, "纵偏移": vertical})

    @Slot(int, int, int, int)
    def _region_selected(self, horizontal, vertical, width, height):
        self._finish({"横坐标": horizontal, "纵坐标": vertical, "宽度": width, "高度": height})

    def _color_selected(self, picker):
        self._finish({"颜色": picker.get_color_string()})

    def _screenshot_selected(self, path):
        self._finish({"图片": path})

    def _finish(self, result):
        if self.controller is None or self._request is None:
            return
        try:
            self._require_stopped()
            if not parameter_values_equal(self._request["values"], self.controller.values()):
                raise ValueError("工具运行期间参数已改变，结果未写入，请重新采集")
            if self._global_window().identity() != self._request["window"].identity():
                raise ValueError("工具运行期间绑定窗口、身份或尺寸已改变，结果未写入")
            declaration = self.controller.definitions[self._request["name"]]["tool"]
            if declaration["类型"] == "截图":
                target = input_parameter_key(declaration["写入"]["图片"])
                result = {"图片": self.controller.panel._store_resource_in_workspace(result["图片"], target)}
            updates = tool_result_updates(declaration, result)
            for name, value in updates.items():
                validate_effective_value(value, {**self.controller.definitions[name], "required": False}, f"参数 {name}")
            apply_editor_values(self.controller.editors, updates)
            self.controller.refresh()
            self.cancel()
        except Exception as error:
            self._failed(error)

    def _failed(self, error):
        self.cancel()
        if self.controller is not None:
            self._error_message = str(error)
            self._error_timer.start(0)

    @Slot()
    def _show_error(self):
        message, self._error_message = self._error_message, ""
        if self.controller is not None:
            QMessageBox.warning(self.controller.panel, "参数工具失败", message)

    @Slot(str)
    def open_image(self, path):
        if self.controller is not None and self._request is None:
            self.controller.panel._show_image_viewer(path)

    @Slot()
    def cancel(self, *, restore=True):
        self._error_timer.stop()
        self._error_message = ""
        for signal, slot in self._connections:
            try:
                signal.disconnect(slot)
            except RuntimeError:
                pass
        self._connections.clear()
        tool, self._tool = self._tool, None
        if tool is not None and isValid(tool):
            tool.setProperty("parameterDisposed", True)
            tool.blockSignals(True)
            tool.close()
            tool.deleteLater()
        request, self._request = self._request, None
        if self.controller is not None:
            panel = self.controller.panel
            if request is not None and self.controller.definitions[request["name"]]["tool"]["类型"] == "截图":
                panel._clear_screenshot_runtime_state()
                if restore:
                    panel._restore_windows_after_screenshot()
            self.refresh(self.controller._states)

    def close(self):
        if self.controller is None:
            return
        self.cancel(restore=False)
        self._error_timer.timeout.disconnect(self._show_error)
        self._error_timer.deleteLater()
        self.controller = None
