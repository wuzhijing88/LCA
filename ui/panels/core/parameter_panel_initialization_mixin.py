from ..parameter_panel_support import *


class ParameterPanelInitializationMixin:

    def _initialize_panel_core_state(self, parent=None) -> None:
        self.parent_window = parent
        self.current_card_id: Optional[int] = None
        self.current_task_type: Optional[str] = None
        self.current_parameters: Dict[str, Any] = {}
        self.param_definitions: Dict[str, Dict[str, Any]] = {}
        self.widgets: Dict[str, QWidget] = {}
        self.value_widgets: Dict[str, QWidget] = {}
        self.runtime_parameters: Dict[tuple[int, str], Any] = {}
        self.workflow_cards_info: Dict[int, tuple[str, int]] = {}
        self.app_mapping: Dict[str, str] = {}
        self.images_dir: Optional[str] = None
        self.conditional_widgets: Dict[str, QWidget] = {}
        self.target_window_title: Optional[str] = None
        self.target_window_hwnd: Optional[int] = None
        self.offset_selector = None
        self._offset_param_name: Optional[str] = None
        self.task_module = None
        self.main_window = None
        self._is_editing_locked: bool = False
        self._workflow_dependent_refreshers: Dict[str, list] = {}
        self._loading_parameter_panel: bool = False
        self._opened_parameters_snapshot: Dict[str, Any] = {}
        self._current_screenshot_target = None
        self._current_screenshot_param_name: Optional[str] = None
        self._screenshot_overlay = None

    def _initialize_recording_panel_state(self) -> None:
        self._is_recording_panel_active = False
        self._record_hotkey_registered = False
        self._replay_hotkey_registered = False
        self._record_hotkey_handle = None
        self._record_mouse_hook = None
        self._replay_hotkey_handle = None
        self._replay_mouse_hook = None
        self._record_thread = None
        self._recording_active = False
        self._recording_state_changing = False

    def _initialize_window_interaction_state(self) -> None:
        self.main_window_minimized: bool = False
        self.manually_closed: bool = False
        self._activation_in_progress: bool = False
        self._mouse_pressed: bool = False
        self._mouse_press_pos: QPoint = QPoint()
        self._window_pos_before_move: QPoint = QPoint()
        self._is_dragging: bool = False
        self._input_focus_protection_active: bool = False
        self._shadow_margin = 2
        self._use_native_shadow = False
        self._snap_to_parent_enabled: bool = True

    def _initialize_favorites_state(self) -> None:
        self._favorites_mode: bool = False
        self._favorites: List[Dict] = []
        self._favorite_workspaces: List[str] = []
        self._favorite_excluded: List[str] = []
        self._favorite_extras: List[str] = []
        self._favorites_pending_close_paths: Dict[str, str] = {}
        self._favorites_active_view: str = "favorites"
        self._favorites_config_path = get_favorites_path()

    def _configure_panel_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.FramelessWindowHint
        )
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
