from ..parameter_panel_support import *


class ParameterPanelSelectorCoordinateOffsetBaseMixin:

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
