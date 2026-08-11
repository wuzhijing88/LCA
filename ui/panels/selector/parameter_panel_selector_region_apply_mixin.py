from .parameter_panel_selector_region_common_mixin import (
    ParameterPanelSelectorRegionCommonMixin,
)
from ..parameter_panel_support import logger


class ParameterPanelSelectorRegionApplyMixin(
    ParameterPanelSelectorRegionCommonMixin,
):

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
