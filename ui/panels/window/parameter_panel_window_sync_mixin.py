from ..parameter_panel_support import *


class ParameterPanelWindowSyncMixin:

    def sync_window_state(self, parent_state):
        logger.debug(f"[Parameter Panel] sync_window_state: parent_state={parent_state}")
        if parent_state == Qt.WindowState.WindowMinimized:
            logger.debug('[Parameter Panel] Parent minimized, hide panel')
            self.main_window_minimized = True
            self.hide()
            return

        if parent_state in (Qt.WindowState.WindowNoState, Qt.WindowState.WindowMaximized):
            logger.debug(
                f"[Parameter Panel] Parent restored: manually_closed={self.manually_closed}, current_card_id={self.current_card_id}"
            )
            self.main_window_minimized = False
            if not self.manually_closed and self.current_card_id is not None:
                logger.debug('[Parameter Panel] Delay show and reposition panel')
                QTimer.singleShot(100, self.show)
                QTimer.singleShot(250, self._position_panel)

    def sync_activation(self, activated):
        if self._activation_in_progress:
            return
        if activated and self.isVisible():
            self._position_panel()
            self._smart_activate_parameter_panel()
