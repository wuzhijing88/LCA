from .parameter_panel_media_multi_image_paths_display_clear_mixin import (
    ParameterPanelMediaMultiImagePathsDisplayClearMixin,
)
from .parameter_panel_media_multi_image_paths_display_count_mixin import (
    ParameterPanelMediaMultiImagePathsDisplayCountMixin,
)


class ParameterPanelMediaMultiImagePathsDisplayMixin(
    ParameterPanelMediaMultiImagePathsDisplayClearMixin,
    ParameterPanelMediaMultiImagePathsDisplayCountMixin,
):
    pass
