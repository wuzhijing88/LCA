from .parameter_panel_window_drag_mixin import ParameterPanelWindowDragMixin
from .parameter_panel_window_snap_mixin import ParameterPanelWindowSnapMixin
from .parameter_panel_window_sync_mixin import ParameterPanelWindowSyncMixin
from .parameter_panel_window_visibility_mixin import ParameterPanelWindowVisibilityMixin


class ParameterPanelWindowInteractionMixin(
    ParameterPanelWindowDragMixin,
    ParameterPanelWindowVisibilityMixin,
    ParameterPanelWindowSnapMixin,
    ParameterPanelWindowSyncMixin,
):
    pass
