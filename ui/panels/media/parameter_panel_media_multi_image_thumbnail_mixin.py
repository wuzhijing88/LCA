from .parameter_panel_media_multi_image_thumbnail_clear_mixin import (
    ParameterPanelMediaMultiImageThumbnailClearMixin,
)
from .parameter_panel_media_multi_image_thumbnail_update_mixin import (
    ParameterPanelMediaMultiImageThumbnailUpdateMixin,
)


class ParameterPanelMediaMultiImageThumbnailMixin(
    ParameterPanelMediaMultiImageThumbnailUpdateMixin,
    ParameterPanelMediaMultiImageThumbnailClearMixin,
):
    pass
