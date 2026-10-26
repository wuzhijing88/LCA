import copy

from ..parameter_panel_support import *
from utils.window.window_activation_utils import show_and_raise_widget


class ParameterPanelPresentationMixin:

    def show_parameters(self, card_id: int, task_type: str, param_definitions: Dict[str, Dict[str, Any]],
                       current_parameters: Dict[str, Any], workflow_cards_info: Dict[int, tuple[str, int]] = None,
                       images_dir: str = None, target_window_hwnd: int = None, task_module=None, main_window=None,
                       custom_name: str = None, sounds_dir: str = None, resource_dirs: Optional[dict] = None):
        logger.info(f"显示参数面板: 卡片={card_id}, 任务={task_type}")
        if task_type == "自定义脚本":
            logger.warning("自定义脚本使用独立编辑器，已忽略参数面板请求")
            return

        self._loading_parameter_panel = True
        try:
            self._release_panel_runtime()
            if not self._prepare_parameter_panel_request(card_id, task_type, custom_name, task_module, main_window):
                return
            param_definitions = copy.deepcopy(param_definitions)
            self._store_parameter_panel_context(
                param_definitions,
                workflow_cards_info,
                images_dir,
                target_window_hwnd,
                sounds_dir,
                resource_dirs,
            )
            self._load_parameter_panel_values(card_id, param_definitions, current_parameters)
            self._restore_dynamic_select_options()
            self._log_parameter_panel_state()
            self._show_parameter_panel_window(card_id, task_type, custom_name)
            self._opened_parameters_snapshot = copy.deepcopy(self.current_parameters)
        except Exception:
            self._clear_content()
            self.current_card_id = None
            self.current_parameters.clear()
            self._opened_parameters_snapshot.clear()
            self.hide()
            raise
        finally:
            self._loading_parameter_panel = False
        self._check_and_register_record_hotkey()

    def _prepare_parameter_panel_request(self, card_id: int, task_type: str, custom_name: Optional[str], task_module, main_window) -> bool:
        self._favorites_mode = False
        self._restore_standard_footer_buttons()
        self._set_footer_buttons_visible(True)

        if isinstance(card_id, bool) or not isinstance(card_id, int) or card_id < 0:
            raise ValueError(f"无效的卡片编号：{card_id}")

        if not isinstance(task_type, str) or not task_type.strip():
            raise ValueError("任务类型必须是非空字符串")

        self.current_card_id = card_id
        self.current_task_type = task_type
        self.current_custom_name = custom_name

        identity = (id(main_window), main_window.workflow_tab_widget.get_current_task_id()) if main_window is not None else None
        if identity != getattr(self, "_runtime_workflow_identity", None):
            self.runtime_parameters.clear()
        self._runtime_workflow_identity = identity
        self.main_window = main_window
        self.task_module = task_module
        return True

    def _load_parameter_panel_values(self, card_id, param_definitions, current_parameters):
        self.current_parameters = copy.deepcopy(current_parameters)
        self._validate_panel_parameter_names(param_definitions)
        self._fill_missing_parameter_defaults(param_definitions)
        self._normalize_task_specific_parameters()
        self._validate_panel_parameter_names(param_definitions)
        self._normalize_operation_mode_parameter(param_definitions)
        self._log_initial_jump_targets()
        self._merge_runtime_only_parameters(card_id, param_definitions)

    def _log_initial_jump_targets(self) -> None:
        for key in ['success_jump_target_id', 'failure_jump_target_id']:
            if key in self.current_parameters:
                logger.info(f"[INIT] {key} = {self.current_parameters[key]}")

    def _validate_panel_parameter_names(self, param_definitions):
        unknown = [name for name in self.current_parameters if name not in param_definitions and not name.startswith('_') and not name.startswith('---')]
        if unknown:
            raise ValueError(f"参数不属于当前卡片定义：{'、'.join(unknown)}，请先转换为现行工程格式")

    def _fill_missing_parameter_defaults(self, param_definitions: Dict[str, Dict[str, Any]]) -> None:
        for param_name, param_def in param_definitions.items():
            if param_name not in self.current_parameters and 'default' in param_def:
                default_value = copy.deepcopy(param_def['default'])
                self.current_parameters[param_name] = default_value
                logger.debug(f"fill default parameter: {param_name} = {default_value}")

    def _normalize_task_specific_parameters(self) -> None:
        task_module = getattr(self, "task_module", None)
        if task_module is None:
            return

        normalize_hook = getattr(task_module, "normalize_panel_parameters", None)
        if normalize_hook is None:
            return
        normalized_params = normalize_hook(self.current_parameters)
        if not isinstance(normalized_params, dict):
            raise TypeError("任务面板参数处理结果必须是字典")
        self.current_parameters = normalized_params

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

    def _store_parameter_panel_context(
        self,
        param_definitions: Dict[str, Dict[str, Any]],
        workflow_cards_info,
        images_dir: Optional[str],
        target_window_hwnd: Optional[int],
        sounds_dir: Optional[str] = None,
        resource_dirs: Optional[dict] = None,
    ) -> None:
        self.param_definitions = param_definitions
        self.workflow_cards_info = workflow_cards_info or {}
        self.images_dir = images_dir
        self.sounds_dir = sounds_dir
        directories = resource_dirs or {}
        for key in ("dicts_dir", "yolo_dir", "replays_dir", "plugins_dir"):
            setattr(self, key, str(directories.get(key) or ""))
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
        if self.current_card_id is None:
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
