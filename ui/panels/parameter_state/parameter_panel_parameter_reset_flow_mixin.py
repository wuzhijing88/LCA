from ..parameter_panel_support import *


class ParameterPanelParameterResetFlowMixin:

    def _reset_parameters(self):
        if not self.param_definitions:
            return

        logger.info("Start resetting parameters")
        tool_position_params = self._get_reset_tool_position_params()
        extra_hidden_params = self._get_reset_extra_hidden_params()

        self._reinitialize_reset_parameter_values(tool_position_params)
        reset_count = self._reset_parameter_widgets(tool_position_params)
        logger.info(f"Reset {reset_count} UI widgets")

        self._run_reset_cleanup_pipeline(tool_position_params, extra_hidden_params)
        self._emit_reset_parameter_state()
        logger.info("Parameter reset finished")

    def _get_reset_tool_position_params(self) -> Set[str]:
        return {
            'scroll_start_position',
            'drag_start_position', 'drag_end_position',
            'move_start_position', 'move_end_position',
        }

    def _get_reset_extra_hidden_params(self) -> List[str]:
        return [
            'recorded_actions',
            'minimap_x', 'minimap_y', 'minimap_width', 'minimap_height',
            'region_x', 'region_y', 'region_width', 'region_height',
            'region_hwnd', 'region_window_title', 'region_window_class', 'region_client_width', 'region_client_height',
            'region_x1', 'region_y1', 'region_x2', 'region_y2',
            'target_supports_counter',
            'recognition_region_x', 'recognition_region_y', 'recognition_region_width', 'recognition_region_height',
            'search_region_x', 'search_region_y', 'search_region_width', 'search_region_height',
            'connected_targets',
            'motion_detection_region',
            'region_coordinates',
            'combo_mouse_x', 'combo_mouse_y',
            'combo_seq_mouse_x', 'combo_seq_mouse_y',
            'anchor_point',
        ]

    def _reinitialize_reset_parameter_values(self, tool_position_params: Set[str]) -> None:
        self.current_parameters.clear()
        for name, param_def in self.param_definitions.items():
            param_type = param_def.get('type', 'text')
            if param_type in ('hidden', 'separator'):
                continue
            if name in tool_position_params:
                self.current_parameters[name] = ""
            else:
                self.current_parameters[name] = param_def.get('default')

    def _reset_parameter_widgets(self, tool_position_params: Set[str]) -> int:
        reset_count = 0
        for name, param_def in self.param_definitions.items():
            param_type = param_def.get('type', 'text')
            if param_type in ('hidden', 'separator'):
                continue
            if name not in self.widgets:
                continue

            widget = self.widgets[name]
            default_value = param_def.get('default')
            try:
                if name in tool_position_params:
                    if isinstance(widget, QLineEdit):
                        widget.clear()
                    reset_count += 1
                    continue
                self._reset_widget_to_default(widget, default_value, param_def)
                reset_count += 1
            except Exception as e:
                logger.error(f"重置控件失败 {name}：{e}")
        return reset_count

    def _run_reset_cleanup_pipeline(self, tool_position_params: Set[str], extra_hidden_params: List[str]) -> None:
        self._clear_image_previews()
        self._cleanup_keyboard_parameters()
        self._cleanup_extra_hidden_params(extra_hidden_params)
        self._cleanup_all_card_parameters()
        self._ensure_tool_position_params_cleared(tool_position_params)
        self._cleanup_workflow_context()
        self._reset_action_control_buttons()

    def _ensure_tool_position_params_cleared(self, tool_position_params: Set[str]) -> None:
        for param_name in tool_position_params:
            if param_name in self.current_parameters and self.current_parameters[param_name] != "":
                self.current_parameters[param_name] = ""
                logger.debug(f"Tool position parameter cleared: {param_name}")

    def _emit_reset_parameter_state(self) -> None:
        if self.current_card_id:
            logger.info(f"Emit reset parameter signal: card_id={self.current_card_id}")
            self.parameters_changed.emit(self.current_card_id, self.current_parameters.copy())
        QTimer.singleShot(100, self._refresh_conditional_widgets)
