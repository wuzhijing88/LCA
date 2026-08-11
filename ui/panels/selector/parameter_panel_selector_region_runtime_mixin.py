from .parameter_panel_selector_region_common_mixin import (
    ParameterPanelSelectorRegionCommonMixin,
)
from ..parameter_panel_support import logger


class ParameterPanelSelectorRegionRuntimeMixin(
    ParameterPanelSelectorRegionCommonMixin,
):

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
