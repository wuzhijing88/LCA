from ..parameter_panel_support import *
from utils.window_activation_utils import show_and_raise_widget


class ParameterPanelPresentationMixin:

    def show_parameters(self, card_id: int, task_type: str, param_definitions: Dict[str, Dict[str, Any]],
                       current_parameters: Dict[str, Any], workflow_cards_info: Dict[int, tuple[str, int]] = None,
                       images_dir: str = None, target_window_hwnd: int = None, task_module=None, main_window=None,
                       custom_name: str = None):
        logger.info(f"显示参数面板: 卡片={card_id}, 任务={task_type}")

        if not self._prepare_parameter_panel_request(card_id, task_type, custom_name, task_module, main_window):
            return

        self._load_parameter_panel_values(card_id, param_definitions, current_parameters)
        self._store_parameter_panel_context(param_definitions, workflow_cards_info, images_dir, target_window_hwnd)
        self._restore_dynamic_select_options()
        self._log_parameter_panel_state()
        self._show_parameter_panel_window(card_id, task_type, custom_name)
        self._check_and_register_record_hotkey()

    def _prepare_parameter_panel_request(self, card_id: int, task_type: str, custom_name: Optional[str], task_module, main_window) -> bool:
        self._favorites_mode = False
        self._set_footer_buttons_visible(True)

        if not isinstance(card_id, int) or card_id < 0:
            logger.error(f"无效的卡片ID: {card_id}")
            return False

        if not task_type:
            logger.error("任务类型为空")
            return False

        self.current_card_id = card_id
        self.current_task_type = task_type
        self.current_custom_name = custom_name

        if main_window is not None:
            self.main_window = main_window
        if task_module is not None:
            self.task_module = task_module
        return True

    def _load_parameter_panel_values(self, card_id: int, param_definitions: Dict[str, Dict[str, Any]], current_parameters: Dict[str, Any]) -> None:
        self.current_parameters = current_parameters.copy()
        self._normalize_task_specific_parameters()
        self._normalize_operation_mode_parameter(param_definitions)
        self._log_initial_jump_targets()

        obsolete_params = self._prune_obsolete_panel_parameters(param_definitions)
        if obsolete_params:
            self._prune_obsolete_params_in_workflow(obsolete_params)

        self._fill_missing_parameter_defaults(param_definitions)
        self._merge_runtime_only_parameters(card_id, param_definitions)

    def _log_initial_jump_targets(self) -> None:
        for key in ['success_jump_target_id', 'failure_jump_target_id']:
            if key in self.current_parameters:
                logger.info(f"[INIT] {key} = {self.current_parameters[key]}")

    def _prune_obsolete_panel_parameters(self, param_definitions: Dict[str, Dict[str, Any]]) -> List[str]:
        valid_param_names = set(param_definitions.keys())
        obsolete_params = [
            param_name
            for param_name in self.current_parameters.keys()
            if param_name not in valid_param_names and not param_name.startswith('---') and not param_name.startswith('_')
        ]
        for param_name in obsolete_params:
            logger.debug(f"remove obsolete parameter: {param_name} = {self.current_parameters[param_name]}")
            del self.current_parameters[param_name]
        return obsolete_params

    def _fill_missing_parameter_defaults(self, param_definitions: Dict[str, Dict[str, Any]]) -> None:
        for param_name, param_def in param_definitions.items():
            if param_name not in self.current_parameters and 'default' in param_def:
                default_value = param_def['default']
                self.current_parameters[param_name] = default_value
                logger.debug(f"fill default parameter: {param_name} = {default_value}")

    def _normalize_task_specific_parameters(self) -> None:
        task_module = getattr(self, "task_module", None)
        if task_module is None:
            return

        for hook_name in ("normalize_panel_parameters", "normalize_parameters"):
            normalize_hook = getattr(task_module, hook_name, None)
            if not callable(normalize_hook):
                continue
            try:
                normalized_params = normalize_hook(self.current_parameters)
                if isinstance(normalized_params, dict):
                    self.current_parameters = normalized_params
            except Exception as e:
                logger.warning(f"任务参数归一化失败({hook_name}): {e}")
            break

    def _merge_runtime_only_parameters(self, card_id: int, param_definitions: Dict[str, Dict[str, Any]]) -> None:
        for param_name, param_def in param_definitions.items():
            if param_def.get('save_to_workflow', True):
                continue
            runtime_key = (card_id, param_name)
            runtime_value = self._get_runtime_parameter(card_id, param_name)
            if runtime_key in self.runtime_parameters:
                self.current_parameters[param_name] = self.runtime_parameters[runtime_key]
            elif runtime_value is not None:
                self.current_parameters[param_name] = runtime_value
            else:
                self.current_parameters[param_name] = param_def.get('default', '')

    def _store_parameter_panel_context(self, param_definitions: Dict[str, Dict[str, Any]], workflow_cards_info, images_dir: Optional[str], target_window_hwnd: Optional[int]) -> None:
        self.param_definitions = param_definitions
        self.workflow_cards_info = workflow_cards_info or {}
        self.images_dir = images_dir
        self.target_window_hwnd = target_window_hwnd

    def _restore_dynamic_select_options(self) -> None:
        for param_name, param_def in self.param_definitions.items():
            if param_def.get('type') not in ['select', 'choice', 'combo']:
                continue
            hidden_options_key = f'_{param_name}_dynamic_options'
            if hidden_options_key not in self.current_parameters:
                continue
            saved_options = self.current_parameters[hidden_options_key]
            if saved_options and isinstance(saved_options, list):
                param_def['options'] = saved_options
                logger.debug(f"restore dynamic options: {param_name} = {saved_options}")

    def _log_parameter_panel_state(self) -> None:
        logger.debug(f"parameter panel state ready: card_id={self.current_card_id}, task_type={self.current_task_type}")
        logger.debug(f"parameter definitions={len(self.param_definitions)}, current_parameters={len(self.current_parameters)}")
        logger.debug(f"workflow cards info={self.workflow_cards_info}")

    def _show_parameter_panel_window(self, card_id: int, task_type: str, custom_name: Optional[str]) -> None:
        self.title_input.setReadOnly(False)
        if custom_name:
            self.title_input.setText(f"{custom_name} (ID: {card_id})")
        else:
            self.title_input.setText(f"{task_type} (ID: {card_id})")

        self._clear_content()
        self._create_parameter_widgets()
        self.refresh_runtime_parameters(card_id)
        self._position_panel()
        self.manually_closed = False
        show_and_raise_widget(self, log_prefix='参数面板展示')
        if hasattr(self, 'close_button'):
            self.close_button.resetStyle()

    def _on_title_edited(self):
        if not self.current_card_id:
            return

        new_title = self.title_input.text().strip()
        if not new_title:
            return

        match = re.match(r'(.+?)\s*\(ID:\s*\d+\)', new_title)
        if match:
            custom_name = match.group(1).strip()
        else:
            custom_name = new_title

        if custom_name == self.current_task_type:
            custom_name = None
        if custom_name == self.current_custom_name:
            return

        self.current_custom_name = custom_name
        self.custom_name_changed.emit(self.current_card_id, custom_name or "")

        if custom_name:
            self.title_input.setText(f"{custom_name} (ID: {self.current_card_id})")
        else:
            self.title_input.setText(f"{self.current_task_type} (ID: {self.current_card_id})")
