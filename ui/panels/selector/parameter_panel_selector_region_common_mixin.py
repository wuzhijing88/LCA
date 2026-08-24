from ..parameter_panel_support import *


class ParameterPanelSelectorRegionCommonMixin:

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
