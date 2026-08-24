from ..parameter_panel_support import *


class ParameterPanelWindowStyleMixin:

    def _remove_combobox_shadow(self, combobox):
        return

    def _apply_force_down_popup(self, combobox):
        pass

    def _install_wheel_filter(self, widget, name):
        if not isinstance(widget, (QComboBox, QSpinBox, QDoubleSpinBox, QSlider)):
            return
        wheel_filter = WheelEventFilter(f"{type(widget).__name__}_{name}")
        widget.installEventFilter(wheel_filter)
        if not hasattr(self, '_wheel_filters'):
            self._wheel_filters = []
        self._wheel_filters.append(wheel_filter)
        logger.debug(f"Install wheel filter for widget {name} ({type(widget).__name__})")

    def _apply_styles(self):
        pass
