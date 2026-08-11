from ..parameter_panel_support import *


class ParameterPanelWindowSnapMixin:

    def _detach_from_parent_snap(self):
        if not self.isVisible() or not self.parent_window:
            return
        try:
            client_geometry = self._get_parent_client_geometry()
            snapped_x = client_geometry.x() + client_geometry.width() + 2
            snapped_y = client_geometry.y()
            near_snapped_x = abs(self.x() - snapped_x) <= 40
            near_snapped_y = abs(self.y() - snapped_y) <= 80
            if near_snapped_x and near_snapped_y:
                self.move(self.x() + 32, self.y())
            client_height = int(client_geometry.height())
            if client_height > 0 and self.height() < client_height:
                self.resize(self.width(), client_height)
        except Exception:
            pass

    def set_snap_to_parent_enabled(self, enabled: bool):
        enabled = bool(enabled)
        self._snap_to_parent_enabled = enabled
        if enabled:
            if self.isVisible():
                self._position_panel()
            return

        self._release_panel_height_constraint()
        self._detach_from_parent_snap()
