from ..parameter_panel_support import *


class ParameterPanelSelectorCoordinateOffsetColorMixin:

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
