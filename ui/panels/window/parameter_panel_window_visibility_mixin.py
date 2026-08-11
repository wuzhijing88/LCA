from ..parameter_panel_support import *


class ParameterPanelWindowVisibilityMixin:

    def _auto_save_before_hide(self):
        if not self.current_card_id or not hasattr(self, 'widgets') or not self.widgets:
            return
        try:
            self._apply_parameters(auto_close=False)
            logger.info(f"Auto-save parameter panel before hide: card_id={self.current_card_id}")
        except Exception as exc:
            logger.warning(f"隐藏前自动保存失败：{exc}")

    def hide_panel(self):
        logger.debug(f"Hide parameter panel - card_id: {self.current_card_id}")
        self._auto_save_before_hide()
        self.manually_closed = True
        self.hide()
        self.panel_closed.emit()

    def is_panel_open(self) -> bool:
        return self.isVisible() and self.current_card_id is not None

    def apply_and_close(self):
        if not self.is_panel_open():
            return
        logger.info(
            f"[Auto Apply] Apply parameter panel before workflow run (card_id={self.current_card_id})"
        )
        self._apply_parameters(auto_close=True)

    def set_editing_locked(self, locked: bool):
        logger.info(f"[Parameter Panel] set_editing_locked ignored (locked={locked})")
