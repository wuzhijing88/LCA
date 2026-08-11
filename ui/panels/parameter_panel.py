"""Parameter panel aggregator."""

from .parameter_panel_support import *
from .favorites.parameter_panel_favorites_mixin import ParameterPanelFavoritesMixin
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
        super().__init__(None)
        self._initialize_panel_core_state(parent)
        self._initialize_recording_panel_state()
        self._initialize_window_interaction_state()
        self._initialize_favorites_state()
        self._configure_panel_window()
        self._try_enable_native_shadow()
        self._setup_ui()
        self._apply_styles()
