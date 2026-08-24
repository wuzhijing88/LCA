from ..parameter_panel_support import *


class ParameterPanelSelectorBindingResultMixin:
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
