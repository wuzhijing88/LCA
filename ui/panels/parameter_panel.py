"""Parameter panel aggregator."""

from .parameter_panel_support import *
from .background_jobs import PanelBackgroundJobs
from .managed_resources import PanelResources
from .recognition_preview import initialize_recognition_preview
from .favorites.parameter_panel_favorites_mixin import ParameterPanelFavoritesMixin
from .ai.parameter_panel_ai_mixin import ParameterPanelAIMixin
from .media.parameter_panel_media_mixin import ParameterPanelMediaMixin
from .selector.parameter_panel_selector_mixin import ParameterPanelSelectorMixin
from .recording.parameter_panel_recording_mixin import ParameterPanelRecordingMixin
from .conditional.parameter_panel_conditional_mixin import ParameterPanelConditionalMixin
from .parameter_state.parameter_panel_parameter_state_mixin import ParameterPanelParameterStateMixin
from .widget.parameter_panel_widget_factory_mixin import ParameterPanelWidgetFactoryMixin
from .actions.parameter_panel_actions_mixin import ParameterPanelActionsMixin
from .core.parameter_panel_target_window_mixin import ParameterPanelTargetWindowMixin
from .core.parameter_panel_initialization_mixin import ParameterPanelInitializationMixin
from .window.parameter_panel_window_mixin import ParameterPanelWindowMixin
from .core.parameter_panel_presentation_mixin import ParameterPanelPresentationMixin
from .core.parameter_panel_workflow_selector_mixin import ParameterPanelWorkflowSelectorMixin
from .widget.parameter_panel_widget_registry_mixin import ParameterPanelWidgetRegistryMixin


class ParameterPanel(
    ParameterPanelFavoritesMixin,
    ParameterPanelAIMixin,
    ParameterPanelMediaMixin,
    ParameterPanelSelectorMixin,
    ParameterPanelRecordingMixin,
    ParameterPanelConditionalMixin,
    ParameterPanelParameterStateMixin,
    ParameterPanelWidgetFactoryMixin,
    ParameterPanelActionsMixin,
    ParameterPanelTargetWindowMixin,
    ParameterPanelInitializationMixin,
    ParameterPanelWindowMixin,
    ParameterPanelPresentationMixin,
    ParameterPanelWorkflowSelectorMixin,
    ParameterPanelWidgetRegistryMixin,
    QWidget,
):
    """Parameter panel window."""

    parameters_changed = Signal(int, dict)
    panel_closed = Signal()
    request_delete_random_connection = Signal(int, int)
    custom_name_changed = Signal(int, str)
    workflow_execute_requested = Signal(str)
    workflow_open_requested = Signal(str)
    batch_execute_requested = Signal(list)
    workflow_check_changed = Signal(str, bool)
    favorites_opened = Signal(list)

    def __init__(self, parent=None):
        from ui.panels.managed_resources import dispose_partial_widget
        if QApplication.instance() is None:
            raise RuntimeError("创建参数界面前必须创建应用程序")
        super().__init__(parent)
        try:
            initialize_recognition_preview()
            self._initialize_panel_core_state(parent)
            self._background_jobs = PanelBackgroundJobs(self)
            self._resources = PanelResources()
            self._picking_active = False
            self._picker_overlay = None
            self._picked_info = None
            self.destroyed.connect(self._resources.close)
            self._initialize_recording_panel_state()
            self._initialize_window_interaction_state()
            self._initialize_favorites_state()
            self._configure_panel_window()
            self._try_enable_native_shadow()
            self._setup_ui()
            self._apply_styles()

        except Exception:
            dispose_partial_widget(self, parent)
            raise

    def _release_panel_runtime(self):
        self._background_jobs.cancel_all()
        self._picking_active = False
        self._record_thread = None
        self._replay_thread = None
        self._recording_active = False
        self._replay_active = False
        errors = []
        for cleanup in (self._stop_combo_key_sequence_recording, self._unregister_record_hotkey, self._unregister_replay_hotkey):
            try:
                cleanup()
            except Exception as error:
                errors.append(error)
        self._is_recording_panel_active = False
        errors.extend(self._resources.close())
        if errors:
            raise RuntimeError(f"参数面板资源卸载失败：{errors[0]}")

    def discard_workflow_context(self):
        self._release_panel_runtime()
        self.manually_closed = True
        self.hide()
        self._clear_content()
        self.current_card_id = None
        self.current_task_type = None
        self.current_custom_name = None
        self.current_parameters.clear()
        self.param_definitions.clear()
        self._opened_parameters_snapshot.clear()
        self.runtime_parameters.clear()
        self.workflow_cards_info.clear()
        self._runtime_workflow_identity = None
        self.task_module = None
        self.main_window = None
        self.target_window_hwnd = None
        for name in ("images_dir", "sounds_dir", "dicts_dir", "yolo_dir", "replays_dir", "plugins_dir"):
            setattr(self, name, None)

    def _own_parameter_tool(self, widget):
        widget.setParent(self, widget.windowFlags())
        widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._watch_parameter_widget(widget)
        return self._resources.own_widget(widget, getattr(widget, "_cleanup_previous_overlay", None))

    def _start_parameter_tool(self, tool):
        self._tool_hiding = True
        try:
            tool.start_selection()
        finally:
            self._tool_hiding = False

    def _watch_parameter_widget(self, widget):
        import weakref
        owner_ref = weakref.ref(self)
        def forget(_object=None):
            owner = owner_ref()
            if owner is not None:
                for name, value in list(vars(owner).items()):
                    if value is widget:
                        setattr(owner, name, None)
        widget.destroyed.connect(forget)
