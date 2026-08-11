from .parameter_panel_selector_region_apply_mixin import (
    ParameterPanelSelectorRegionApplyMixin,
)
from .parameter_panel_selector_region_common_mixin import (
    ParameterPanelSelectorRegionCommonMixin,
)
from .parameter_panel_selector_region_preview_mixin import (
    ParameterPanelSelectorRegionPreviewMixin,
)
from .parameter_panel_selector_region_runtime_mixin import (
    ParameterPanelSelectorRegionRuntimeMixin,
)


class ParameterPanelSelectorRegionMixin(
    ParameterPanelSelectorRegionRuntimeMixin,
    ParameterPanelSelectorRegionApplyMixin,
    ParameterPanelSelectorRegionPreviewMixin,
    ParameterPanelSelectorRegionCommonMixin,
):
    pass
