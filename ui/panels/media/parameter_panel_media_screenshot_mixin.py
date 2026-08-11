from .parameter_panel_media_screenshot_overlay_mixin import (
    ParameterPanelMediaScreenshotOverlayMixin,
)
from .parameter_panel_media_screenshot_result_mixin import (
    ParameterPanelMediaScreenshotResultMixin,
)
from .parameter_panel_media_screenshot_start_mixin import (
    ParameterPanelMediaScreenshotStartMixin,
)


class ParameterPanelMediaScreenshotMixin(
    ParameterPanelMediaScreenshotStartMixin,
    ParameterPanelMediaScreenshotOverlayMixin,
    ParameterPanelMediaScreenshotResultMixin,
):
    pass
