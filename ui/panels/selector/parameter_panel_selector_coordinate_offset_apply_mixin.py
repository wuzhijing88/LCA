from ..parameter_panel_support import *


class ParameterPanelSelectorCoordinateOffsetApplyMixin:

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
