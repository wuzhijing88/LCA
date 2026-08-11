from .main_window_parameter_panel_display_mixin import MainWindowParameterPanelDisplayMixin
from .main_window_parameter_panel_positioning_mixin import MainWindowParameterPanelPositioningMixin
from .main_window_parameter_panel_sync_mixin import MainWindowParameterPanelSyncMixin


class MainWindowParameterPanelMixin(
    MainWindowParameterPanelDisplayMixin,
    MainWindowParameterPanelSyncMixin,
    MainWindowParameterPanelPositioningMixin,
):
    pass
