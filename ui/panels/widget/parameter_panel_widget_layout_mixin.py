from ..parameter_panel_support import *


class ParameterPanelWidgetLayoutMixin:

    def _attach_created_widget_row(
        self,
        name: str,
        param_type: str,
        layout: QVBoxLayout,
        row_widget: QWidget,
        row_layout: QHBoxLayout,
        widget: Optional[QWidget],
    ):
        if widget:
            logger.debug(
                f"[DEBUG] Attach widget row: name={name}, type={param_type}, widget_type={type(widget).__name__}"
            )
            widget.setFixedWidth(240)
            row_layout.addWidget(widget)
            row_layout.addStretch()
            if param_type == 'textarea' or param_type == 'multiline':
                row_widget.setMinimumHeight(70)
            layout.addWidget(row_widget)
            return

        logger.warning(
            f"[DEBUG] Widget creation returned None: name={name}, type={param_type}"
        )
