from ..parameter_panel_support import *


class ParameterPanelSelectorCoordinateBasicApplyMixin:

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
