from ..parameter_panel_support import *
from .parameter_panel_picker_overlay import ParameterPanelPickerOverlay
from utils.window_activation_utils import show_and_activate_overlay


class ParameterPanelSelectorPickerStartMixin:
    _ELEMENT_PICKER_BUTTON_TEXT = "拾取元素 (右键确认)"

    _ELEMENT_PICKING_BUTTON_TEXT = "拾取中... (右键确认, ESC取消)"

    def _start_element_picking(self):
        """Start picking UI element."""
        try:
            if not self._ensure_element_picker_available():
                return
            self._set_element_picker_button_state(True)
            self._minimize_picker_host_window()
            self._show_picker_overlay()
            self._initialize_picker_runtime_state()
            self._start_element_pick_thread()
        except Exception as e:
            logger.error(f"启动元素拾取失败: {e}")
            self._set_element_picker_button_state(False)

    def _ensure_element_picker_available(self) -> bool:
        from utils.element_picker import ElementPicker

        if ElementPicker.is_available():
            return True
        QMessageBox.warning(self, "错误", "UIAutomation模块不可用，无法拾取元素")
        return False

    def _set_element_picker_button_state(self, is_picking: bool) -> None:
        if hasattr(self, '_element_picker_button') and self._element_picker_button:
            self._element_picker_button.setText(
                self._ELEMENT_PICKING_BUTTON_TEXT if is_picking else self._ELEMENT_PICKER_BUTTON_TEXT
            )
            self._element_picker_button.setEnabled(not is_picking)

    def _minimize_picker_host_window(self) -> None:
        if hasattr(self, 'main_window') and self.main_window:
            self.main_window.showMinimized()

    def _show_picker_overlay(self) -> None:
        self._picker_overlay = ParameterPanelPickerOverlay(self)
        logger.debug(
            f"[元素拾取] 创建PickerOverlay: geometry={self._picker_overlay.geometry()}, "
            f"DPI={self._picker_overlay.device_pixel_ratio}"
        )
        show_and_activate_overlay(self._picker_overlay, log_prefix='元素拾取覆盖层', focus=True)

    def _initialize_picker_runtime_state(self) -> None:
        self._picking_active = True
        self._current_element = None
        self._picked_info = None

    def _start_element_pick_thread(self) -> None:
        import threading

        self._pick_thread = threading.Thread(target=self._pick_loop, daemon=True)
        self._pick_thread.start()
