from ..parameter_panel_support import *


class ParameterPanelParameterApplyMainMixin:
    def _apply_live_parameter_changes(
        self,
        changes: Dict[str, Any],
        *,
        refresh_conditional: bool = True,
    ) -> None:
        if not changes:
            return
        self.current_parameters.update(changes)
        if self.current_card_id is not None:
            self.parameters_changed.emit(self.current_card_id, dict(changes))
        if refresh_conditional:
            self._refresh_conditional_widgets()

    def _apply_parameters(self, auto_close=True):
        if self._apply_favorites_parameters(auto_close):
            return

        if self.current_card_id is None:
            logger.warning('Current card id is empty, cannot apply parameters')
            return

        real_time_params = self._get_real_time_card_parameters()
        new_parameters = self._collect_hidden_apply_parameters(real_time_params)
        new_parameters.update(self._collect_visible_apply_parameters())

        needs_update = self._has_conditional_parameter_changes(new_parameters)
        self._apply_operation_mode_change_defaults(new_parameters)
        self._fill_missing_apply_defaults(new_parameters)
        self._preserve_internal_apply_parameters(new_parameters)

        self.current_parameters.update(new_parameters)
        if needs_update:
            self._update_conditional_display()

        self.parameters_changed.emit(self.current_card_id, new_parameters)
        if auto_close:
            self.hide_panel()

    def _apply_favorites_parameters(self, auto_close: bool) -> bool:
        if not getattr(self, '_favorites_mode', False):
            return False
        self._save_favorites_config()
        self._sync_favorites_tabs()
        if auto_close:
            self.hide_panel()
        return True
