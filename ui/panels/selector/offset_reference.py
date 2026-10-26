"""偏移选择的基准识别；仅接收参数快照，不访问界面对象。"""
import logging
import re
from copy import deepcopy

logger = logging.getLogger(__name__)


class OffsetReferenceLookup:
    def __init__(self, parameters, definition, target_hwnd, card_id):
        self.current_parameters = deepcopy(parameters)
        self.definition = deepcopy(definition)
        self.target_hwnd = target_hwnd
        self.card_id = card_id

    def resolve(self, cancelled, progress):
        if cancelled.is_set():
            return None
        related = self.definition['related_params']
        if 'coordinate_fixed_offset_x' in related:
            try:
                return int(self.current_parameters['coordinate_x']), int(self.current_parameters['coordinate_y']), None
            except (TypeError, ValueError) as exc:
                raise ValueError('坐标基准使用了未确定的值，无法自动定位') from exc
        if 'image_fixed_offset_x' in related:
            return self._image_reference()
        if 'color_fixed_offset_x' in related:
            return self._color_reference()
        return None, None, None

    def _image_reference(self):
        from tasks.image_match_click import locate_image_in_window

        params = dict(self.current_parameters)
        if params['multi_image_mode'] == '多图识别':
            paths = [line.strip() for line in params['image_paths'].splitlines() if line.strip()]
            if not paths:
                raise ValueError('请先选择基准图片')
            params['image_path'] = paths[0]
        elif not params['image_path']:
            raise ValueError('请先选择基准图片')
        found, location, _detail = locate_image_in_window(params=params, target_hwnd=self.target_hwnd, card_id=self.card_id)
        if not found or location is None:
            raise ValueError('未识别到基准图片，无法自动定位偏移起点')
        x, y, width, height = location
        if width <= 0 or height <= 0:
            raise ValueError('基准图片识别区域无效')
        return int(x + width / 2), int(y + height / 2), (int(x), int(y), int(width), int(height))

    def _color_reference(self):
        from services.screenshot_pool import capture_and_find_color

        payload = self._build_color_match_payload_for_offset(self.current_parameters['target_color'])
        if payload is None:
            raise ValueError('目标颜色格式无效，无法定位偏移基准')
        mode, colors = payload
        roi = None
        if self.current_parameters.get('search_region_enabled', False):
            roi = tuple(int(self.current_parameters[key]) for key in ('search_region_x', 'search_region_y', 'search_region_width', 'search_region_height'))
            if roi[2] <= 0 or roi[3] <= 0:
                raise ValueError('找色区域无效，请先设置区域')
        response = capture_and_find_color(hwnd=self.target_hwnd, color_mode=mode, colors_data=colors, h_tolerance=10, s_tolerance=40, v_tolerance=40, min_pixel_count=1, client_area_only=True, use_cache=False, timeout=4.0, roi=roi)
        if not response['success']:
            raise RuntimeError('颜色基准识别失败')
        if not response['found']:
            raise ValueError('未识别到基准颜色，无法自动定位偏移起点')
        x, y = response['center']
        return int(x), int(y), None

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

