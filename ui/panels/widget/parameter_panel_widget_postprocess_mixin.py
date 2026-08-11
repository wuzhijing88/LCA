from ..parameter_panel_support import *
from .parameter_panel_widget_layout_mixin import ParameterPanelWidgetLayoutMixin
from .parameter_panel_widget_preview_mixin import ParameterPanelWidgetPreviewMixin
from .parameter_panel_widget_registration_mixin import ParameterPanelWidgetRegistrationMixin


class ParameterPanelWidgetPostprocessMixin(
    ParameterPanelWidgetRegistrationMixin,
    ParameterPanelWidgetLayoutMixin,
    ParameterPanelWidgetPreviewMixin,
):

    def _finalize_created_widget(
        self,
        name: str,
        param_def: Dict[str, Any],
        param_type: str,
        layout: QVBoxLayout,
        row_widget: QWidget,
        row_layout: QHBoxLayout,
        widget: Optional[QWidget],
        current_value: Any,
    ) -> None:
        self._register_created_widget(name, param_def, widget)
        self._attach_created_widget_row(name, param_type, layout, row_widget, row_layout, widget)
        self._append_image_preview_row(name, param_type, layout, current_value)
        self._append_help_text(param_def, layout)
