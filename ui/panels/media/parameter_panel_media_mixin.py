from .parameter_panel_media_browser_mixin import ParameterPanelMediaBrowserMixin
from .parameter_panel_media_file_mixin import ParameterPanelMediaFileMixin
from .parameter_panel_media_multi_image_mixin import ParameterPanelMediaMultiImageMixin
from .parameter_panel_media_preview_mixin import ParameterPanelMediaPreviewMixin
from .parameter_panel_media_screenshot_mixin import ParameterPanelMediaScreenshotMixin


class ParameterPanelMediaMixin(
    ParameterPanelMediaFileMixin,
    ParameterPanelMediaScreenshotMixin,
    ParameterPanelMediaPreviewMixin,
    ParameterPanelMediaMultiImageMixin,
    ParameterPanelMediaBrowserMixin,
):
    pass
